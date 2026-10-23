import math
import html
import json
import urllib.request
import urllib.error
import urllib.parse
import hmac
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Carteira Inteligente', page_icon='📊', layout='wide')

# Proteção opcional da aplicação. Recomendado quando a carteira pessoal fica
# guardada permanentemente num backend. A palavra-passe existe apenas nos Secrets.
try:
    _APP_PASSWORD=str(st.secrets.get('APP_PASSWORD','') or '')
except Exception:
    _APP_PASSWORD=''
if _APP_PASSWORD and not st.session_state.get('_app_authenticated',False):
    st.title('🔒 Carteira Inteligente')
    _pw=st.text_input('Palavra-passe da aplicação',type='password')
    if st.button('Entrar',type='primary',use_container_width=True):
        if hmac.compare_digest(str(_pw),_APP_PASSWORD):
            st.session_state['_app_authenticated']=True
            st.rerun()
        else:
            st.error('Palavra-passe incorreta.')
    st.stop()
st.title('📊 Carteira Inteligente')
st.caption('Curto prazo · Longo prazo · Evidências essenciais. Dados identificados; não envia ordens reais.')


MARKETS = {
    'EUA': ['AAPL.US','MSFT.US','NVDA.US','AMZN.US','META.US','GOOGL.US','AVGO.US','TSLA.US','JPM.US','V.US','MA.US','LLY.US','WMT.US','COST.US','NFLX.US','AMD.US','ORCL.US','CRM.US','ADBE.US','QCOM.US','XOM.US','CVX.US','KO.US','PEP.US','DIS.US','CAT.US','GE.US','IBM.US'],
    'Alemanha': ['SAP.DE','SIE.DE','ALV.DE','DTE.DE','MBG.DE','BMW.DE','BAS.DE','BAYN.DE','ADS.DE','RWE.DE','DBK.DE','IFX.DE','MUV2.DE','VOW3.DE','DHL.DE','FB2A.DE'],
    'Portugal': ['EDP.PT','EDPR.PT','GALP.PT','JMT.PT','BCP.PT','SON.PT','REN.PT','SEM.PT','COR.PT','NOS.PT','ALTR.PT','IBS.PT'],
    'França': ['MC.FR','OR.FR','TTE.FR','SAN.FR','AIR.FR','BNP.FR','SU.FR','CS.FR','DG.FR','KER.FR','CAP.FR','RMS.FR'],
    'Países Baixos': ['ASML.NL','SHELL.NL','INGA.NL','PHIA.NL','AD.NL','HEIA.NL','PRX.NL','WKL.NL'],
    'Espanha': ['SAN1.ES','IBE.ES','ITX.ES','BBVA.ES','REP.ES','TEF.ES','ACS.ES','FER.ES'],
    'Itália': ['ENI.IT','ENEL.IT','ISP.IT','UCG.IT','STM.IT','RACE.IT','G.IT','LDO.IT'],
    'Reino Unido': ['AZN.UK','SHEL.UK','HSBA.UK','ULVR.UK','BP.UK','RIO.UK','GSK.UK','LSEG.UK','REL.UK','BARC.UK'],
    'Suíça': ['NESN.CH','NOVN.CH','ROG.CH','UBSG.CH','ABBN.CH','ZURN.CH','SREN.CH','GIVN.CH'],
}

# O ticker XTB é a identidade principal. O ticker técnico é apenas o símbolo necessário
# ao fornecedor de dados (Yahoo Finance/yfinance) para obter séries e fundamentais.
XTB_SUFFIX_MAP = {
    '.US': {'source_suffix':'',    'market':'EUA',              'venue':'NASDAQ/NYSE (conforme instrumento)', 'expected_currency':'USD'},
    '.DE': {'source_suffix':'.DE', 'market':'Alemanha',         'venue':'Xetra/Alemanha',                     'expected_currency':'EUR'},
    '.PT': {'source_suffix':'.LS', 'market':'Portugal',         'venue':'Euronext Lisbon',                    'expected_currency':'EUR'},
    '.NL': {'source_suffix':'.AS', 'market':'Países Baixos',    'venue':'Euronext Amsterdam',                 'expected_currency':'EUR'},
    '.FR': {'source_suffix':'.PA', 'market':'França',           'venue':'Euronext Paris',                     'expected_currency':'EUR'},
    '.ES': {'source_suffix':'.MC', 'market':'Espanha',          'venue':'Bolsa de Madrid',                    'expected_currency':'EUR'},
    '.IT': {'source_suffix':'.MI', 'market':'Itália',           'venue':'Borsa Italiana',                     'expected_currency':'EUR'},
    '.UK': {'source_suffix':'.L',  'market':'Reino Unido',      'venue':'London Stock Exchange',              'expected_currency':'GBP'},
    '.CH': {'source_suffix':'.SW', 'market':'Suíça',            'venue':'SIX Swiss Exchange',                 'expected_currency':'CHF'},
}

# Exceções em que o símbolo base do fornecedor não coincide exatamente com o da XTB.
# A app nunca troca silenciosamente de país/bolsa: estes aliases mantêm o mesmo instrumento económico/mercado.
XTB_SOURCE_ALIASES = {
    'ASML.NL':'ASML.AS',
    'ASML.US':'ASML',
    'META.US':'META',
    'FB2A.DE':'FB2A.DE',
    'EDP.PT':'EDP.LS',
    'SAN1.ES':'SAN.MC',
}

# Mapeamentos adicionais podem ser mantidos num CSV ao lado da app, sem alterar o código.
_alias_file = Path(__file__).with_name('xtb_aliases.csv')
if _alias_file.exists():
    try:
        _aliases_df = pd.read_csv(_alias_file)
        for _, _r in _aliases_df.iterrows():
            _x = str(_r.get('xtb_ticker','')).upper().strip()
            _s = str(_r.get('source_ticker','')).upper().strip()
            if _x and _s:
                XTB_SOURCE_ALIASES[_x] = _s
    except Exception:
        pass

SOURCE_TO_XTB_SUFFIX = {
    '.DE':'.DE', '.LS':'.PT', '.AS':'.NL', '.PA':'.FR', '.MC':'.ES',
    '.MI':'.IT', '.L':'.UK', '.SW':'.CH'
}
MARKET_XTB_SUFFIX = {
    'EUA':'.US','Alemanha':'.DE','Portugal':'.PT','Países Baixos':'.NL',
    'França':'.FR','Espanha':'.ES','Itália':'.IT','Reino Unido':'.UK','Suíça':'.CH'
}

def _xtb_suffix(ticker):
    t=str(ticker).upper().strip()
    for suffix in sorted(XTB_SUFFIX_MAP, key=len, reverse=True):
        if t.endswith(suffix):
            return suffix
    return None

def xtb_to_source(ticker):
    t=str(ticker).upper().strip()
    if t in XTB_SOURCE_ALIASES:
        return XTB_SOURCE_ALIASES[t]
    suffix=_xtb_suffix(t)
    if not suffix:
        return t
    base=t[:-len(suffix)]
    return base + XTB_SUFFIX_MAP[suffix]['source_suffix']

def source_to_xtb(ticker, market_hint=None):
    t=str(ticker).upper().strip()
    if market_hint in MARKET_XTB_SUFFIX and '.' not in t:
        return t + MARKET_XTB_SUFFIX[market_hint]
    for source_suffix, xtb_suffix in SOURCE_TO_XTB_SUFFIX.items():
        if t.endswith(source_suffix):
            return t[:-len(source_suffix)] + xtb_suffix
    return t

def instrument_identity(ticker, market_hint=None):
    requested=str(ticker).upper().strip()
    if not requested:
        raise ValueError('Ticker vazio.')

    # Se o utilizador já escreveu ticker XTB, preserva-o exatamente como identidade.
    if _xtb_suffix(requested):
        xtb=requested
        source=xtb_to_source(xtb)
    # Se escreveu um ticker Yahoo/bolsa conhecido, converte apenas o identificador visual.
    elif any(requested.endswith(s) for s in SOURCE_TO_XTB_SUFFIX):
        source=requested
        xtb=source_to_xtb(requested, market_hint)
    # Se escreveu só o símbolo base e indicou mercado, cria o ticker XTB desse mercado.
    elif market_hint in MARKET_XTB_SUFFIX:
        xtb=requested + MARKET_XTB_SUFFIX[market_hint]
        source=xtb_to_source(xtb)
    else:
        # Compatibilidade com símbolos sem sufixo; a app não inventa o país.
        xtb=requested
        source=requested

    suffix=_xtb_suffix(xtb)
    meta=XTB_SUFFIX_MAP.get(suffix, {})
    return {
        'requested':requested,
        'xtb_ticker':xtb,
        'source_ticker':source,
        'market':meta.get('market') or market_hint or 'Auto/N/D',
        'venue':meta.get('venue') or 'N/D',
        'expected_currency':meta.get('expected_currency'),
    }

@st.cache_data(ttl=1800)
def resolve_instrument(ticker, market_hint=None):
    # A identidade é resolvida sem um download extra. A validação real acontece
    # logo a seguir em price_data(), evitando duas chamadas de rede por ativo.
    return instrument_identity(ticker, market_hint)

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = []
if 'portfolio_input' not in st.session_state:
    st.session_state.portfolio_input = []
if 'decision_history' not in st.session_state:
    st.session_state.decision_history = []

# -----------------------------------------------------------------------------
# Persistência permanente (Supabase)
# -----------------------------------------------------------------------------
# A sessão do Streamlit é temporária. Quando estes 3 secrets existem, a carteira
# e o histórico de decisões são carregados e guardados numa tabela Supabase.
# A chave service_role fica apenas no servidor Streamlit e nunca é mostrada na UI.

def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

def persistence_config():
    url=str(_secret('SUPABASE_URL','') or '').strip().rstrip('/')
    key=str(_secret('SUPABASE_SECRET_KEY','') or _secret('SUPABASE_SERVICE_ROLE_KEY','') or '').strip()
    owner=str(_secret('PORTFOLIO_OWNER_ID','') or '').strip()
    return url,key,owner

def persistence_enabled():
    url,key,owner=persistence_config()
    return bool(url and key and owner)

def _json_safe(value):
    if isinstance(value, dict):
        return {str(k):_json_safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value=float(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, (datetime,pd.Timestamp)):
        return value.isoformat()
    if value is pd.NA:
        return None
    return value

def _supabase_headers():
    _,key,_=persistence_config()
    headers={
        'apikey':key,
        'Content-Type':'application/json',
        'Accept':'application/json',
        'User-Agent':'streamlit-portfolio-backend/1.0',
    }
    # As novas chaves sb_secret_* não são JWT e devem ir apenas em `apikey`.
    # Mantém compatibilidade com a legacy service_role (JWT) se o utilizador já a tiver.
    if key and not key.startswith('sb_secret_'):
        headers['Authorization']=f'Bearer {key}'
    return headers

def _supabase_request(method, path, payload=None, extra_headers=None, timeout=4):
    url,_,_=persistence_config()
    if not url:
        raise RuntimeError('SUPABASE_URL não configurado.')
    data=None
    if payload is not None:
        data=json.dumps(_json_safe(payload),ensure_ascii=False,allow_nan=False).encode('utf-8')
    headers=_supabase_headers()
    if extra_headers:
        headers.update(extra_headers)
    req=urllib.request.Request(url+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as resp:
            raw=resp.read().decode('utf-8')
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail=e.read().decode('utf-8',errors='replace')
        raise RuntimeError(f'Erro Supabase HTTP {e.code}: {detail[:300]}') from e
    except Exception as e:
        raise RuntimeError(f'Falha de ligação ao armazenamento: {e}') from e

def persistent_state_payload():
    return {
        'portfolio_input':_json_safe(st.session_state.get('portfolio_input',[])),
        'decision_history':_json_safe(st.session_state.get('decision_history',[])),
    }

def save_persistent_state(show_error=False):
    if not persistence_enabled():
        st.session_state['persistence_status']='Apenas sessão'
        return False
    _,_,owner=persistence_config()
    payload={
        'owner_id':owner,
        'state':persistent_state_payload(),
        'updated_at':datetime.now(timezone.utc).isoformat(),
    }
    try:
        _supabase_request(
            'POST',
            '/rest/v1/trading_bot_state?on_conflict=owner_id',
            payload,
            {'Prefer':'resolution=merge-duplicates,return=minimal'},
        )
        st.session_state['persistence_status']='Ligado'
        st.session_state['persistence_last_save']=payload['updated_at']
        st.session_state.pop('persistence_error',None)
        return True
    except Exception as e:
        st.session_state['persistence_status']='Erro'
        st.session_state['persistence_error']=str(e)
        if show_error:
            st.error(f'Não foi possível guardar permanentemente: {e}')
        return False

def load_persistent_state(force=False):
    if st.session_state.get('_persistent_loaded') and not force:
        return
    st.session_state['_persistent_loaded']=True
    if not persistence_enabled():
        st.session_state['persistence_status']='Apenas sessão'
        return
    _,_,owner=persistence_config()
    q=urllib.parse.quote(owner,safe='')
    try:
        rows=_supabase_request('GET',f'/rest/v1/trading_bot_state?owner_id=eq.{q}&select=state,updated_at') or []
        if rows:
            state=rows[0].get('state') or {}
            st.session_state.portfolio_input=list(state.get('portfolio_input') or [])
            st.session_state.decision_history=list(state.get('decision_history') or [])
            st.session_state['persistence_last_save']=rows[0].get('updated_at')
        st.session_state['persistence_status']='Ligado'
        st.session_state.pop('persistence_error',None)
    except Exception as e:
        st.session_state['persistence_status']='Erro'
        st.session_state['persistence_error']=str(e)

# A persistencia deixa de ser carregada no arranque global.
# E carregada apenas quando o utilizador abre a pagina Carteira, evitando bloquear a abertura da app.

def add_watchlist(ticker):
    t = str(ticker).upper().strip()
    if t and t not in st.session_state.watchlist:
        st.session_state.watchlist.append(t)

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    pc = df['Close'].shift(1)
    tr = pd.concat([(df['High']-df['Low']), (df['High']-pc).abs(), (df['Low']-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def indicators(df):
    d = df.copy()
    d['EMA20'] = d['Close'].ewm(span=20, adjust=False).mean()
    d['EMA50'] = d['Close'].ewm(span=50, adjust=False).mean()
    d['EMA200'] = d['Close'].ewm(span=200, adjust=False).mean()
    d['RSI14'] = rsi(d['Close'])
    d['ATR14'] = atr(d)
    d['VOL20'] = d['Volume'].rolling(20).mean()
    d['RET20'] = d['Close'].pct_change(20)*100
    d['RET60'] = d['Close'].pct_change(60)*100
    d['HIGH252'] = d['High'].rolling(252, min_periods=60).max()
    d['LOW252'] = d['Low'].rolling(252, min_periods=60).min()
    d['VALUE20'] = (d['Close']*d['Volume']).rolling(20).mean()
    return d

@st.cache_data(ttl=300)
def price_data(ticker, period='5y', interval='1d'):
    # Import tardio: o arranque da interface não depende do yfinance.
    import yfinance as yf
    df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    if df.empty:
        raise ValueError(f'Sem dados de mercado para {ticker}.')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna().copy()

@st.cache_data(ttl=1800)
def asset_info(ticker):
    # Import tardio: só carrega yfinance quando o utilizador pede análise.
    import yfinance as yf
    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    return info

@st.cache_data(ttl=900)
def fx_per_eur(currency):
    currency = (currency or 'EUR').upper()
    if currency == 'EUR':
        return 1.0
    pair = {'USD':'EURUSD=X','GBP':'EURGBP=X','CHF':'EURCHF=X'}.get(currency)
    if not pair:
        return None
    try:
        d = price_data(pair, '5d', '1d')
        return float(d['Close'].iloc[-1])
    except Exception:
        return None

def to_eur(value, currency):
    rate = fx_per_eur(currency)
    if rate is None or rate <= 0:
        return None
    return float(value)/rate

def technical_score(row):
    tests = {
        'Preço acima EMA20': bool(row['Close'] > row['EMA20']),
        'EMA20 acima EMA50': bool(row['EMA20'] > row['EMA50']),
        'EMA50 acima EMA200': bool(row['EMA50'] > row['EMA200']),
        'RSI entre 50 e 68': bool(50 <= row['RSI14'] <= 68),
        'Momentum 20d positivo': bool(row['RET20'] > 0),
        'Momentum 60d positivo': bool(row['RET60'] > 0),
        'Volume >= média 20d': bool(row['Volume'] >= row['VOL20']),
        'ATR entre 0,8% e 6%': bool(0.8 <= (row['ATR14']/row['Close']*100) <= 6),
    }
    passed = sum(tests.values())
    score = passed/len(tests)*100
    label = 'Forte' if passed >= 6 else ('Neutro' if passed >= 4 else 'Fraco')
    return round(score,1), label, tests

def _num(info, key):
    v = info.get(key)
    return float(v) if isinstance(v, (int,float,np.integer,np.floating)) and np.isfinite(v) else None

def _metric_score(value, bad, good, higher_better=True):
    if value is None or not np.isfinite(value):
        return None
    v=float(value)
    if higher_better:
        if good <= bad:
            return None
        return max(0.0,min(100.0,(v-bad)/(good-bad)*100.0))
    if bad <= good:
        return None
    return max(0.0,min(100.0,(bad-v)/(bad-good)*100.0))


def _sector_fundamental_profile(info):
    sector=str(info.get('sector') or 'Other')
    base={
        'revenueGrowth':      {'weight':0.14,'bad':-0.05,'good':0.15,'higher':True},
        'earningsGrowth':     {'weight':0.12,'bad':-0.10,'good':0.20,'higher':True},
        'operatingMargins':   {'weight':0.12,'bad':0.03,'good':0.20,'higher':True},
        'profitMargins':      {'weight':0.10,'bad':0.02,'good':0.15,'higher':True},
        'returnOnEquity':     {'weight':0.18,'bad':0.03,'good':0.20,'higher':True},
        'freeCashflow':       {'weight':0.14,'binary_positive':True},
        'operatingCashflow':  {'weight':0.08,'binary_positive':True},
        'debtToEquity':       {'weight':0.12,'bad':200.0,'good':50.0,'higher':False},
    }
    overrides={
        'Technology': {
            'revenueGrowth':{'weight':0.18,'bad':-0.03,'good':0.20,'higher':True},
            'earningsGrowth':{'weight':0.14,'bad':-0.08,'good':0.22,'higher':True},
            'operatingMargins':{'weight':0.14,'bad':0.05,'good':0.25,'higher':True},
            'profitMargins':{'weight':0.12,'bad':0.03,'good':0.20,'higher':True},
            'returnOnEquity':{'weight':0.18,'bad':0.05,'good':0.25,'higher':True},
            'freeCashflow':{'weight':0.12,'binary_positive':True},
            'operatingCashflow':{'weight':0.06,'binary_positive':True},
            'debtToEquity':{'weight':0.06,'bad':150.0,'good':30.0,'higher':False},
        },
        'Financial Services': {
            'revenueGrowth':{'weight':0.15,'bad':-0.03,'good':0.12,'higher':True},
            'earningsGrowth':{'weight':0.20,'bad':-0.10,'good':0.18,'higher':True},
            'operatingMargins':{'weight':0.00,'bad':0.00,'good':1.00,'higher':True},
            'profitMargins':{'weight':0.15,'bad':0.04,'good':0.25,'higher':True},
            'returnOnEquity':{'weight':0.35,'bad':0.05,'good':0.18,'higher':True},
            'freeCashflow':{'weight':0.00,'binary_positive':True},
            'operatingCashflow':{'weight':0.15,'binary_positive':True},
            'debtToEquity':{'weight':0.00,'bad':1000.0,'good':0.0,'higher':False},
        },
        'Utilities': {
            'revenueGrowth':{'weight':0.10,'bad':-0.04,'good':0.08,'higher':True},
            'earningsGrowth':{'weight':0.10,'bad':-0.10,'good':0.12,'higher':True},
            'operatingMargins':{'weight':0.15,'bad':0.08,'good':0.25,'higher':True},
            'profitMargins':{'weight':0.10,'bad':0.04,'good':0.15,'higher':True},
            'returnOnEquity':{'weight':0.15,'bad':0.03,'good':0.12,'higher':True},
            'freeCashflow':{'weight':0.15,'binary_positive':True},
            'operatingCashflow':{'weight':0.10,'binary_positive':True},
            'debtToEquity':{'weight':0.15,'bad':320.0,'good':100.0,'higher':False},
        },
        'Real Estate': {
            'revenueGrowth':{'weight':0.15,'bad':-0.04,'good':0.10,'higher':True},
            'earningsGrowth':{'weight':0.10,'bad':-0.12,'good':0.12,'higher':True},
            'operatingMargins':{'weight':0.15,'bad':0.08,'good':0.30,'higher':True},
            'profitMargins':{'weight':0.15,'bad':0.04,'good':0.25,'higher':True},
            'returnOnEquity':{'weight':0.10,'bad':0.02,'good':0.10,'higher':True},
            'freeCashflow':{'weight':0.10,'binary_positive':True},
            'operatingCashflow':{'weight':0.10,'binary_positive':True},
            'debtToEquity':{'weight':0.15,'bad':260.0,'good':80.0,'higher':False},
        },
        'Energy': {
            'revenueGrowth':{'weight':0.08,'bad':-0.12,'good':0.12,'higher':True},
            'earningsGrowth':{'weight':0.10,'bad':-0.20,'good':0.20,'higher':True},
            'operatingMargins':{'weight':0.12,'bad':0.04,'good':0.22,'higher':True},
            'profitMargins':{'weight':0.10,'bad':0.02,'good':0.15,'higher':True},
            'returnOnEquity':{'weight':0.15,'bad':0.04,'good':0.18,'higher':True},
            'freeCashflow':{'weight':0.20,'binary_positive':True},
            'operatingCashflow':{'weight':0.10,'binary_positive':True},
            'debtToEquity':{'weight':0.15,'bad':180.0,'good':40.0,'higher':False},
        },
        'Basic Materials': {
            'revenueGrowth':{'weight':0.08,'bad':-0.12,'good':0.12,'higher':True},
            'earningsGrowth':{'weight':0.10,'bad':-0.20,'good':0.20,'higher':True},
            'operatingMargins':{'weight':0.12,'bad':0.04,'good':0.20,'higher':True},
            'profitMargins':{'weight':0.10,'bad':0.02,'good':0.14,'higher':True},
            'returnOnEquity':{'weight':0.15,'bad':0.04,'good':0.18,'higher':True},
            'freeCashflow':{'weight':0.20,'binary_positive':True},
            'operatingCashflow':{'weight':0.10,'binary_positive':True},
            'debtToEquity':{'weight':0.15,'bad':180.0,'good':40.0,'higher':False},
        },
        'Healthcare': {
            'revenueGrowth':{'weight':0.17,'bad':-0.04,'good':0.18,'higher':True},
            'earningsGrowth':{'weight':0.13,'bad':-0.10,'good':0.20,'higher':True},
            'operatingMargins':{'weight':0.13,'bad':0.04,'good':0.22,'higher':True},
            'profitMargins':{'weight':0.12,'bad':0.02,'good':0.18,'higher':True},
            'returnOnEquity':{'weight':0.15,'bad':0.04,'good':0.20,'higher':True},
            'freeCashflow':{'weight':0.15,'binary_positive':True},
            'operatingCashflow':{'weight':0.07,'binary_positive':True},
            'debtToEquity':{'weight':0.08,'bad':180.0,'good':40.0,'higher':False},
        },
    }
    cfg={k:dict(v) for k,v in base.items()}
    for k,v in overrides.get(sector,{}).items():
        cfg[k]=dict(v)
    roe_floor={
        'Technology':0.10,'Financial Services':0.08,'Utilities':0.06,'Real Estate':0.04,
        'Energy':0.07,'Basic Materials':0.07,'Healthcare':0.08,
    }.get(sector,0.08)
    debt_critical={
        'Utilities':380.0,'Real Estate':320.0,'Financial Services':None,
        'Technology':200.0,'Energy':240.0,'Basic Materials':240.0,
    }.get(sector,260.0)
    return sector,cfg,roe_floor,debt_critical


def fundamental_equity(info):
    # Sector-aware weighted score. Missing data reduce completeness but are never invented.
    sector,cfg,roe_floor,debt_critical=_sector_fundamental_profile(info)
    labels={
        'revenueGrowth':'Crescimento de receitas',
        'earningsGrowth':'Crescimento de lucros',
        'operatingMargins':'Margem operacional',
        'profitMargins':'Margem liquida',
        'returnOnEquity':'ROE',
        'freeCashflow':'Fluxo de caixa livre',
        'operatingCashflow':'Caixa operacional',
        'debtToEquity':'Divida/Capital proprio',
    }
    rows=[]
    weighted=0.0
    available_weight=0.0
    total_weight=sum(float(v.get('weight',0)) for v in cfg.values())
    metric_scores={}
    for key,spec in cfg.items():
        weight=float(spec.get('weight',0))
        if weight<=0:
            continue
        value=_num(info,key)
        score=None
        if value is not None:
            if spec.get('binary_positive'):
                score=100.0 if value>0 else 0.0
            else:
                score=_metric_score(value,float(spec['bad']),float(spec['good']),bool(spec.get('higher',True)))
        if score is not None:
            weighted += score*weight
            available_weight += weight
            metric_scores[key]=score
        if score is None:
            reading='N/D'
        elif score>=70:
            reading='Forte para o setor'
        elif score>=40:
            reading='Intermedio para o setor'
        else:
            reading='Fraco para o setor'
        rows.append({
            'Criterio':labels.get(key,key),'Valor':value,'Peso %':round(weight*100,1),
            'Score setorial':round(score,1) if score is not None else None,'Leitura':reading,
        })
    completeness=(available_weight/total_weight*100.0) if total_weight>0 else 0.0
    score=(weighted/available_weight) if available_weight>0 else None
    notes=[]
    roe=_num(info,'returnOnEquity')
    if score is not None and roe is not None and roe<roe_floor and cfg.get('returnOnEquity',{}).get('weight',0)>=0.10:
        score=min(score,69.0)
        notes.append('ROE baixo para o setor')
    fcf=_num(info,'freeCashflow')
    if score is not None and fcf is not None and fcf<0 and cfg.get('freeCashflow',{}).get('weight',0)>=0.10:
        score=min(score,64.0)
        notes.append('FCF negativo')
    de=_num(info,'debtToEquity')
    if score is not None and debt_critical is not None and de is not None and de>debt_critical and cfg.get('debtToEquity',{}).get('weight',0)>0:
        score=min(score,64.0)
        notes.append('endividamento elevado para o setor')
    rg=_num(info,'revenueGrowth'); eg=_num(info,'earningsGrowth')
    if score is not None and rg is not None and eg is not None and rg<0 and eg<0:
        score=min(score,59.0)
        notes.append('receitas e lucros em contracao')
    if rows and notes:
        rows.append({'Criterio':'Alertas de qualidade','Valor':None,'Peso %':0.0,'Score setorial':None,'Leitura':' · '.join(notes)})
    if score is None or completeness<45:
        label='Dados insuficientes'
    elif score>=72:
        label='Forte'
    elif score>=48:
        label='Neutro'
    else:
        label='Fraco'
    return label, round(score,1) if score is not None else None, round(completeness,1), pd.DataFrame(rows)


def fundamental_etf(info):
    specs=[]
    expense=_num(info,'annualReportExpenseRatio')
    if expense is None: expense=_num(info,'expenseRatio')
    assets=_num(info,'totalAssets')
    avgvol=_num(info,'averageVolume')
    nav=_num(info,'navPrice')
    ytd=_num(info,'ytdReturn')
    raw=[
        ('TER <= 0,50%', expense, lambda x: x <= 0.005),
        ('Ativos >= 500 M', assets, lambda x: x >= 500_000_000),
        ('Volume médio >= 100 mil', avgvol, lambda x: x >= 100_000),
        ('NAV disponível', nav, lambda x: x > 0),
        ('Retorno YTD disponível', ytd, lambda x: np.isfinite(x)),
    ]
    passed=0; available=0
    for name,v,fn in raw:
        ok=None if v is None else bool(fn(v))
        if v is not None:
            available += 1; passed += int(ok)
        specs.append({'Critério':name,'Valor':v,'Cumpre':('Sim' if ok else 'Não') if ok is not None else 'N/D'})
    completeness = available/len(raw)*100
    ratio = passed/available if available else 0
    label = 'Dados insuficientes' if available < 3 else ('Forte' if ratio >= 0.70 else ('Neutro' if ratio >= 0.45 else 'Fraco'))
    return label, round(ratio*100,1) if available else None, round(completeness,1), pd.DataFrame(specs)

def asset_kind(info):
    qt = str(info.get('quoteType','')).upper()
    return 'ETF' if qt == 'ETF' else 'Ação'

def fundamental_analysis(ticker):
    info = asset_info(ticker)
    kind = asset_kind(info)
    if kind == 'ETF':
        label, score, completeness, table = fundamental_etf(info)
    else:
        label, score, completeness, table = fundamental_equity(info)
    return info, kind, label, score, completeness, table

def historical_scenarios(raw, current_row, horizons=(5,10,15,30)):
    d = indicators(raw).dropna().copy()
    if len(d) < 260:
        return pd.DataFrame()
    current_score,_,_ = technical_score(current_row)
    curr_rsi=float(current_row['RSI14'])
    curr_trend = bool(current_row['EMA20'] > current_row['EMA50'] > current_row['EMA200'])
    rows=[]
    for i in range(200, len(d)-max(horizons)):
        r=d.iloc[i]
        sc,_,_=technical_score(r)
        tr=bool(r['EMA20'] > r['EMA50'] > r['EMA200'])
        if abs(sc-current_score) <= 12.5 and abs(float(r['RSI14'])-curr_rsi) <= 7 and tr == curr_trend:
            rec={'i':i}
            for h in horizons:
                rec[h]=(float(d['Close'].iloc[i+h])/float(r['Close'])-1)*100
            rows.append(rec)
    if len(rows) < 10:
        return pd.DataFrame()
    hist=pd.DataFrame(rows)
    current=float(current_row['Close'])
    out=[]
    for h in horizons:
        s=hist[h].dropna()
        out.append({
            'Horizonte':f'{h} dias de mercado',
            'Amostras':len(s),
            'Retorno mediano %':float(s.median()),
            'Percentil 25 %':float(s.quantile(.25)),
            'Percentil 75 %':float(s.quantile(.75)),
            'Casos positivos %':float((s>0).mean()*100),
            'Nível mediano histórico':current*(1+float(s.median())/100),
        })
    return pd.DataFrame(out)

def target_time_stats(raw, current_row, target_price, max_days=60):
    """
    Estima historicamente o tempo até um movimento equivalente ao alvo atual.
    Usa apenas estados técnicos semelhantes e o máximo diário (High) para saber
    quando o nível teria sido tocado. Não é uma previsão.
    """
    d = indicators(raw).dropna().copy()
    if len(d) < 320:
        return {'median_days': None, 'hit_rate': None, 'samples': 0, 'hits': 0, 'move_pct': None}

    current_price = float(current_row['Close'])
    if current_price <= 0 or target_price <= current_price:
        return {'median_days': None, 'hit_rate': None, 'samples': 0, 'hits': 0, 'move_pct': None}

    move_pct = float(target_price / current_price - 1.0)
    current_score, _, _ = technical_score(current_row)
    curr_rsi = float(current_row['RSI14'])
    curr_trend = bool(current_row['EMA20'] > current_row['EMA50'] > current_row['EMA200'])

    times = []
    samples = 0
    last_selected = -999

    # Espaçamento mínimo de 5 dias reduz observações quase duplicadas.
    for i in range(200, len(d) - max_days):
        if i - last_selected < 5:
            continue
        r = d.iloc[i]
        sc, _, _ = technical_score(r)
        tr = bool(r['EMA20'] > r['EMA50'] > r['EMA200'])
        if abs(sc-current_score) <= 12.5 and abs(float(r['RSI14'])-curr_rsi) <= 7 and tr == curr_trend:
            samples += 1
            last_selected = i
            hist_target = float(r['Close']) * (1.0 + move_pct)
            future_high = d['High'].iloc[i+1:i+1+max_days]
            touched = np.where(future_high.to_numpy(dtype=float) >= hist_target)[0]
            if len(touched):
                times.append(int(touched[0]) + 1)

    if samples < 10:
        return {'median_days': None, 'hit_rate': None, 'samples': samples, 'hits': len(times), 'move_pct': move_pct*100}

    return {
        'median_days': float(np.median(times)) if times else None,
        'hit_rate': float(len(times) / samples * 100),
        'samples': samples,
        'hits': len(times),
        'move_pct': move_pct*100,
    }

def entry_levels(row):
    entry=float(row['Close'])
    a=float(row['ATR14'])
    stop=entry-1.5*a
    target=entry+2*(entry-stop)
    return entry,stop,target

def market_regime():
    try:
        d=indicators(price_data('SPY','2y','1d')).dropna()
        r=d.iloc[-1]
        if r['Close'] > r['EMA50'] > r['EMA200']:
            return 'Alta'
        if r['Close'] < r['EMA50'] < r['EMA200']:
            return 'Baixa'
        return 'Misto/lateral'
    except Exception:
        return 'N/D'

def analyze_asset(ticker, market_hint=None, detailed=True):
    ident=resolve_instrument(ticker, market_hint)
    source=ident['source_ticker']
    raw=price_data(source,'5y' if detailed else '2y','1d')
    d=indicators(raw).dropna()
    if len(d) < 210:
        raise ValueError('Histórico insuficiente para análise técnica robusta.')
    row=d.iloc[-1]
    tech_score, tech_label, tech_tests=technical_score(row)
    info,kind,fund_label,fund_score,complete,fund_table=fundamental_analysis(source)
    entry,stop,target=entry_levels(row)
    scenarios=historical_scenarios(raw,row) if detailed else pd.DataFrame()
    target_time=target_time_stats(raw,row,target,max_days=60) if detailed else {'median_days':None,'hit_rate':None,'samples':0,'hits':0,'move_pct':None}
    currency=str(info.get('currency') or ident.get('expected_currency') or 'N/D').upper()
    company=str(info.get('longName') or info.get('shortName') or 'N/D')
    exchange=str(info.get('exchange') or info.get('fullExchangeName') or ident.get('venue') or 'N/D')
    return {
        'requested_ticker':ident['requested'],
        'xtb_ticker':ident['xtb_ticker'],
        'source_ticker':source,
        'market':ident['market'],
        'venue':ident['venue'],
        'company':company,
        'exchange':exchange,
        'currency':currency,
        'expected_currency':ident.get('expected_currency'),
        'raw':raw,'df':d,'row':row,'tech_score':tech_score,'tech_label':tech_label,'tech_tests':tech_tests,
        'info':info,'kind':kind,'fund_label':fund_label,'fund_score':fund_score,'fund_complete':complete,
        'fund_table':fund_table,'entry':entry,'stop':stop,'target':target,'scenarios':scenarios,
        'target_time':target_time
    }

def decision(a):
    # Regra transparente: ambos os blocos devem ser fortes e dados fundamentais suficientemente completos.
    if a['tech_label']=='Forte' and a['fund_label']=='Forte' and a['fund_complete'] >= 60:
        return 'CANDIDATO A ENTRADA'
    return 'AGUARDAR'

def universe_for(markets):
    out=[]
    for m in markets:
        out += MARKETS[m]
    out += st.session_state.watchlist
    return list(dict.fromkeys(out))

SECTOR_PT = {
    'Technology':'Tecnologia',
    'Financial Services':'Serviços financeiros',
    'Financial':'Serviços financeiros',
    'Industrials':'Industriais',
    'Communication Services':'Serviços de comunicação',
    'Healthcare':'Saúde',
    'Consumer Cyclical':'Consumo discricionário',
    'Consumer Defensive':'Consumo defensivo',
    'Energy':'Energia',
    'Basic Materials':'Materiais básicos',
    'Real Estate':'Imobiliário',
    'Utilities':'Serviços públicos',
}

def sector_name(info):
    raw=str(info.get('sector') or '').strip()
    if raw:
        return SECTOR_PT.get(raw, raw)
    if asset_kind(info) == 'ETF':
        cat=str(info.get('category') or '').strip()
        return f'ETF — {cat}' if cat else 'ETF — categoria N/D'
    return 'N/D'

def _return_pct(df, days):
    s=df['Close'].dropna()
    if len(s) <= days:
        return None
    return float((s.iloc[-1]/s.iloc[-days-1]-1)*100)

def _norm(v, lo, hi):
    if v is None or not np.isfinite(v):
        return None
    if hi <= lo:
        return None
    return float(max(0.0,min(100.0,(v-lo)/(hi-lo)*100)))

def sector_asset_row(ticker):
    a=analyze_asset(ticker, detailed=False)
    info=a['info']; d=a['df']; row=a['row']
    market_cap=_num(info,'marketCap')
    trailing_pe=_num(info,'trailingPE')
    forward_pe=_num(info,'forwardPE')
    price_to_book=_num(info,'priceToBook')
    ev_ebitda=_num(info,'enterpriseToEbitda')
    fcf=_num(info,'freeCashflow')
    fcf_yield=(fcf/market_cap*100) if fcf is not None and market_cap and market_cap>0 else None
    ret1=_return_pct(d,21); ret3=_return_pct(d,63); ret6=_return_pct(d,126); ret12=_return_pct(d,252)
    vol_rel=float(row['Volume']/row['VOL20']) if row['VOL20'] and np.isfinite(row['VOL20']) else None
    above200=bool(row['Close']>row['EMA200'])
    tech=float(a['tech_score'])
    fund=float(a['fund_score']) if a['fund_score'] is not None else None
    short_parts=[
        (tech,0.60),
        (_norm(ret1,-12,18),0.18),
        (_norm(ret3,-25,35),0.12),
        (_norm(vol_rel,0.7,2.0),0.10),
    ]
    valid=[(v,w) for v,w in short_parts if v is not None]
    short_score=sum(v*w for v,w in valid)/sum(w for _,w in valid) if valid else None
    return {
        'Ticker XTB':a['xtb_ticker'],'Ticker técnico':a['source_ticker'],'Empresa':a['company'],
        'Mercado':a['market'],'Setor':sector_name(info),'Indústria':str(info.get('industry') or 'N/D'),
        'Moeda':a['currency'],'Tipo':a['kind'],'Preço':float(row['Close']),
        'Capitalização':market_cap,'Retorno 1M %':ret1,'Retorno 3M %':ret3,'Retorno 6M %':ret6,'Retorno 12M %':ret12,
        'Acima EMA200':above200,'RSI':float(row['RSI14']),'Volume relativo':vol_rel,
        'Técnica':a['tech_label'],'Score técnico':tech,'Fundamental/ETF':a['fund_label'],
        'Score fundamental':fund,'Completude fundamental %':float(a['fund_complete']),
        'P/E':trailing_pe,'Forward P/E':forward_pe,'P/B':price_to_book,'EV/EBITDA':ev_ebitda,'FCF yield %':fcf_yield,
        'Crescimento receitas %':(_num(info,'revenueGrowth')*100 if _num(info,'revenueGrowth') is not None else None),
        'Crescimento lucros %':(_num(info,'earningsGrowth')*100 if _num(info,'earningsGrowth') is not None else None),
        'Margem operacional %':(_num(info,'operatingMargins')*100 if _num(info,'operatingMargins') is not None else None),
        'ROE %':(_num(info,'returnOnEquity')*100 if _num(info,'returnOnEquity') is not None else None),
        'Dívida/Capital próprio %':_num(info,'debtToEquity'),
        'Score curto prazo':round(short_score,1) if short_score is not None else None,
        'Data ref.':str(d.index[-1].date()),
    }

def add_sector_relative_scores(df):
    if df.empty:
        return df
    out=df.copy()
    out['Score avaliação relativa']=np.nan
    out['Score longo prazo']=np.nan
    out['Passa filtros integrados']='Não'
    for sector, idx in out.groupby('Setor').groups.items():
        sub=out.loc[idx]
        val_parts=[]
        for col, higher_better in [('P/E',False),('Forward P/E',False),('P/B',False),('EV/EBITDA',False),('FCF yield %',True)]:
            s=pd.to_numeric(sub[col],errors='coerce')
            valid=s.where(s>0) if col!='FCF yield %' else s
            if valid.notna().sum() >= 4:
                ranks=valid.rank(pct=True,ascending=True)
                score=(ranks*100) if higher_better else ((1-ranks)*100)
                val_parts.append(score)
        if val_parts:
            val=pd.concat(val_parts,axis=1).mean(axis=1,skipna=True)
            out.loc[idx,'Score avaliação relativa']=val
        for i in idx:
            fund=out.at[i,'Score fundamental']; val=out.at[i,'Score avaliação relativa']
            trend=_norm(out.at[i,'Retorno 12M %'],-35,60)
            complete=out.at[i,'Completude fundamental %']
            parts=[]
            if pd.notna(fund): parts.append((float(fund),0.55))
            if pd.notna(val): parts.append((float(val),0.20))
            if trend is not None: parts.append((float(trend),0.15))
            if pd.notna(complete): parts.append((float(complete),0.10))
            if parts:
                out.at[i,'Score longo prazo']=round(sum(v*w for v,w in parts)/sum(w for _,w in parts),1)
            tech=out.at[i,'Score técnico']; comp=out.at[i,'Completude fundamental %']
            fundv=out.at[i,'Score fundamental']
            if pd.notna(tech) and pd.notna(fundv) and tech>=75 and fundv>=70 and comp>=60:
                out.at[i,'Passa filtros integrados']='Sim'
    return out

def sector_summary(df):
    if df.empty:
        return pd.DataFrame()
    total_cap=pd.to_numeric(df['Capitalização'],errors='coerce').sum(min_count=1)
    rows=[]
    for sector,g in df.groupby('Setor'):
        cap=pd.to_numeric(g['Capitalização'],errors='coerce').sum(min_count=1)
        rows.append({
            'Setor':sector,
            'Nº ativos':len(g),
            'Peso no universo analisado %':(float(cap/total_cap*100) if pd.notna(cap) and pd.notna(total_cap) and total_cap>0 else None),
            'Retorno mediano 1M %':pd.to_numeric(g['Retorno 1M %'],errors='coerce').median(),
            'Retorno mediano 3M %':pd.to_numeric(g['Retorno 3M %'],errors='coerce').median(),
            'Retorno mediano 6M %':pd.to_numeric(g['Retorno 6M %'],errors='coerce').median(),
            'Retorno mediano 12M %':pd.to_numeric(g['Retorno 12M %'],errors='coerce').median(),
            'Acima EMA200 %':float(pd.Series(g['Acima EMA200']).mean()*100),
            'RSI mediano':pd.to_numeric(g['RSI'],errors='coerce').median(),
            'Score técnico mediano':pd.to_numeric(g['Score técnico'],errors='coerce').median(),
            'Score curto prazo mediano':pd.to_numeric(g['Score curto prazo'],errors='coerce').median(),
            'Score fundamental mediano':pd.to_numeric(g['Score fundamental'],errors='coerce').median(),
            'Score longo prazo mediano':pd.to_numeric(g['Score longo prazo'],errors='coerce').median(),
            'P/E mediano':pd.to_numeric(g['P/E'],errors='coerce').where(pd.to_numeric(g['P/E'],errors='coerce')>0).median(),
            'Crescimento receitas mediano %':pd.to_numeric(g['Crescimento receitas %'],errors='coerce').median(),
            'Completude fundamental média %':pd.to_numeric(g['Completude fundamental %'],errors='coerce').mean(),
        })
    return pd.DataFrame(rows).sort_values('Score longo prazo mediano',ascending=False,na_position='last').reset_index(drop=True)

def compact_candidate(ticker):
    a=analyze_asset(ticker, detailed=False)
    row=a['row']
    currency=a['currency']
    price=float(row['Close'])
    price_eur=to_eur(price,currency)
    return {
        'Ticker XTB':a['xtb_ticker'],'Ticker técnico':a['source_ticker'],
        'Empresa':a['company'],'Mercado':a['market'],'Bolsa/fonte':a['exchange'],
        'Tipo':a['kind'],'Moeda':currency,
        'Técnica':a['tech_label'],'Score técnico':a['tech_score'],
        'Fundamental/ETF':a['fund_label'],'Completude %':a['fund_complete'],
        'Preço':price,'Preço aprox. EUR':price_eur,
        'Stop':a['stop'],'Alvo técnico (2× o risco)':a['target'],
        'Decisão':decision(a),'Data ref.':str(a['df'].index[-1].date()),
        '_analysis':a
    }

def backtest(ticker, score_min=75, max_days=20, cost_bps=10):
    ident=resolve_instrument(ticker)
    raw=price_data(ident['source_ticker'],'10y','1d')
    d=indicators(raw).dropna().copy()
    if len(d)<300: return pd.DataFrame()
    trades=[]
    i=1
    while i < len(d)-max_days-1:
        row=d.iloc[i-1]
        sc,_,_=technical_score(row)
        if sc < score_min:
            i += 1; continue
        entry=float(d['Open'].iloc[i])
        atrv=float(row['ATR14'])
        stop=entry-1.5*atrv
        target=entry+2*(entry-stop)
        exit_price=float(d['Close'].iloc[min(i+max_days,len(d)-1)])
        exit_i=min(i+max_days,len(d)-1)
        reason='Tempo'
        for j in range(i, min(i+max_days+1,len(d))):
            lo=float(d['Low'].iloc[j]); hi=float(d['High'].iloc[j])
            if lo <= stop:
                exit_price=stop; exit_i=j; reason='Stop'; break
            if hi >= target:
                exit_price=target; exit_i=j; reason='Alvo'; break
        gross=(exit_price/entry-1)*100
        net=gross - 2*(cost_bps/100.0)
        trades.append({'Entrada':d.index[i],'Saída':d.index[exit_i],'Resultado %':net,'Motivo':reason,'Dias':exit_i-i+1})
        i=exit_i+1
    return pd.DataFrame(trades)

def source_block(ticker, a):
    source=a['source_ticker']
    xtb=a['xtb_ticker']
    url=f'https://finance.yahoo.com/quote/{source}'
    st.caption(
        f"Identidade principal: XTB {xtb} · empresa: {a['company']} · mercado: {a['market']} · "
        f"bolsa/fonte: {a['exchange']} · moeda: {a['currency']} · ticker técnico: {source} · "
        f"referência de preço: {a['df'].index[-1]} · recolha da app: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    if a.get('expected_currency') and a['currency'] != 'N/D' and a['currency'] != a['expected_currency']:
        st.warning(
            f"Validação de moeda: o ticker XTB sugere {a['expected_currency']}, mas a fonte técnica devolveu {a['currency']}. "
            "Confirma o instrumento na XTB antes de usar estes dados."
        )
    if a['requested_ticker'] != xtb:
        st.info(f"Símbolo introduzido: {a['requested_ticker']} → identidade XTB usada: {xtb} → ticker técnico: {source}.")
    elif xtb != source:
        st.info(f"Ticker XTB: {xtb} → ticker técnico usado apenas para dados: {source}. A identidade da posição continua a ser {xtb}.")
    st.markdown(f'[Abrir fonte técnica de {source}]({url})')



def annualized_volatility(df, days=252):
    s=df['Close'].dropna().pct_change().dropna().tail(days)
    if len(s) < 60:
        return None
    return float(s.std(ddof=1)*np.sqrt(252)*100)

def max_drawdown_pct(df, days=756):
    s=df['Close'].dropna().tail(days)
    if len(s) < 60:
        return None
    peak=s.cummax()
    dd=(s/peak-1)*100
    return float(dd.min())

def analyst_consensus(info, current_price):
    mean=_num(info,'targetMeanPrice')
    low=_num(info,'targetLowPrice')
    high=_num(info,'targetHighPrice')
    n=_num(info,'numberOfAnalystOpinions')
    upside=(mean/current_price-1)*100 if mean is not None and current_price>0 else None
    return {
        'Preço alvo médio consenso':mean,
        'Preço alvo baixo consenso':low,
        'Preço alvo alto consenso':high,
        'Nº analistas':int(n) if n is not None else None,
        'Potencial consenso %':upside,
    }

def portfolio_exposures():
    rows=st.session_state.get('portfolio_rows',[])
    if not rows:
        return {},{},0.0
    df=pd.DataFrame(rows)
    if 'Valor atual EUR' not in df.columns:
        return {},{},0.0
    vals=pd.to_numeric(df['Valor atual EUR'],errors='coerce')
    total=float(vals.sum()) if vals.notna().any() else 0.0
    if total<=0:
        return {},{},0.0
    asset={}
    sector={}
    for _,r in df.iterrows():
        v=float(r.get('Valor atual EUR') or 0)
        if v<=0: continue
        t=str(r.get('Ticker XTB') or '')
        s=str(r.get('Setor') or 'N/D')
        asset[t]=asset.get(t,0.0)+v/total*100
        sector[s]=sector.get(s,0.0)+v/total*100
    return asset,sector,total

def diversification_adjustment(ticker, sector, asset_weights, sector_weights):
    adj=0.0
    reasons=[]
    aw=float(asset_weights.get(ticker,0.0))
    sw=float(sector_weights.get(sector,0.0))
    if aw >= 25:
        adj -= 18; reasons.append(f'posição já representa {aw:.1f}% da carteira')
    elif aw >= 15:
        adj -= 10; reasons.append(f'posição já representa {aw:.1f}% da carteira')
    elif aw >= 8:
        adj -= 5; reasons.append(f'posição já representa {aw:.1f}% da carteira')
    if sector != 'N/D':
        if sw >= 40:
            adj -= 12; reasons.append(f'setor já representa {sw:.1f}% da carteira')
        elif sw >= 25:
            adj -= 6; reasons.append(f'setor já representa {sw:.1f}% da carteira')
        elif sw < 10:
            adj += 5; reasons.append('setor pouco representado na carteira')
    return adj, reasons

def wealth_candidate_row(ticker, asset_weights=None, sector_weights=None, max_tolerated_drawdown=30):
    asset_weights=asset_weights or {}
    sector_weights=sector_weights or {}
    base=sector_asset_row(ticker)
    a=analyze_asset(ticker, detailed=False)
    d=a['df']; row=a['row']; info=a['info']
    vol=annualized_volatility(d,252)
    mdd1=max_drawdown_pct(d,252)
    mdd3=max_drawdown_pct(d,756)
    current=float(row['Close'])
    cur=a['currency']
    price_eur=to_eur(current,cur)
    cons=analyst_consensus(info,current) if a['kind']=='Ação' else {
        'Preço alvo médio consenso':None,'Preço alvo baixo consenso':None,'Preço alvo alto consenso':None,
        'Nº analistas':None,'Potencial consenso %':None}
    sector=base['Setor']
    adj,reasons=diversification_adjustment(a['xtb_ticker'],sector,asset_weights,sector_weights)
    risk_penalty=0.0
    risk_note=''
    if mdd3 is not None and abs(mdd3) > float(max_tolerated_drawdown):
        risk_penalty=-12.0
        risk_note=f'drawdown histórico 3 anos ({mdd3:.1f}%) excede a tolerância indicada'
    return {
        **base,
        'Preço aprox. EUR':price_eur,
        'Volatilidade anualizada 1A %':vol,
        'Drawdown máx. 1A %':mdd1,
        'Drawdown máx. 3A %':mdd3,
        **cons,
        'Ajuste diversificação':adj,
        'Penalização risco':risk_penalty,
        'Motivos ajuste':'; '.join(reasons+[risk_note] if risk_note else reasons) or 'Sem ajuste',
    }

def add_wealth_scores(df):
    if df.empty:
        return df
    out=add_sector_relative_scores(df.copy())
    out['Score próximo euro']=np.nan
    out['Decisão longo prazo']='AGUARDAR'
    for i in out.index:
        longv=out.at[i,'Score longo prazo']
        if pd.isna(longv):
            continue
        score=float(longv)+float(out.at[i,'Ajuste diversificação'] or 0)+float(out.at[i,'Penalização risco'] or 0)
        score=max(0.0,min(100.0,score))
        out.at[i,'Score próximo euro']=round(score,1)
        comp=float(out.at[i,'Completude fundamental %']) if pd.notna(out.at[i,'Completude fundamental %']) else 0.0
        fund=out.at[i,'Score fundamental']
        if score >= 75 and comp >= 60 and pd.notna(fund) and float(fund) >= 65:
            out.at[i,'Decisão longo prazo']='CANDIDATO A NOVO CAPITAL'
        elif score >= 65:
            out.at[i,'Decisão longo prazo']='OBSERVAR / AGUARDAR MELHOR ENTRADA'
        else:
            out.at[i,'Decisão longo prazo']='NÃO PRIORIZAR AGORA'
    return out


def _now_utc_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def _safe_float(v):
    try:
        x=float(v)
        return x if np.isfinite(x) else None
    except Exception:
        return None

def log_decision(a, action, suggested_qty=None, suggested_invested_eur=None, actual_entry=None, actual_qty=None, objective=None, note=None):
    price=float(a['entry'])
    currency=a['currency'] if a['currency']!='N/D' else 'EUR'
    decision_price=float(actual_entry) if actual_entry is not None and actual_entry>0 else price
    price_eur=to_eur(decision_price,currency)
    row={
        'Data decisão UTC':_now_utc_iso(),
        'Ticker XTB':a['xtb_ticker'],
        'Ticker técnico':a['source_ticker'],
        'Empresa':a['company'],
        'Mercado':a['market'],
        'Tipo':a['kind'],
        'Moeda':currency,
        'Decisão utilizador':str(action),
        'Preço na decisão':decision_price,
        'Preço na decisão EUR':price_eur,
        'Quantidade sugerida':_safe_float(suggested_qty),
        'Capital sugerido EUR':_safe_float(suggested_invested_eur),
        'Quantidade efetiva':_safe_float(actual_qty),
        'Stop no momento':float(a['stop']),
        'Alvo técnico no momento':float(a['target']),
        'Score técnico no momento':float(a['tech_score']),
        'Técnica no momento':a['tech_label'],
        'Fundamental/ETF no momento':a['fund_label'],
        'Completude fundamental %':float(a['fund_complete']),
        'Objetivo':objective or '',
        'Nota':note or '',
    }
    st.session_state.decision_history.append(row)
    save_persistent_state()
    return row

def add_or_merge_portfolio_position(ticker, qty, entry_price, objective='Longo prazo', personal_target=0.0, origin='Oportunidade aceite', entry_date=None, thesis=''):
    t=str(ticker).upper().strip()
    q=float(qty)
    ep=float(entry_price)
    if not t or q<=0 or ep<=0:
        return
    rows=list(st.session_state.portfolio_input)
    found=False
    for r in rows:
        if str(r.get('Ticker XTB','')).upper().strip()==t and str(r.get('Objetivo','Longo prazo'))==str(objective):
            oldq=float(r.get('Quantidade',0) or 0)
            oldp=float(r.get('Preço médio',0) or 0)
            newq=oldq+q
            if newq>0:
                r['Preço médio']=(oldq*oldp+q*ep)/newq if oldq>0 else ep
                r['Quantidade']=newq
            if personal_target and float(personal_target)>0:
                r['Preço alvo pessoal']=float(personal_target)
            if entry_date:
                r['Data entrada']=str(entry_date)
            if thesis:
                r['Tese/nota']=str(thesis)
            r['Origem']=origin
            found=True
            break
    if not found:
        rows.append({
            'Ticker XTB':t,'Quantidade':q,'Preço médio':ep,
            'Preço alvo pessoal':float(personal_target or 0),
            'Data entrada':str(entry_date) if entry_date else datetime.now().date().isoformat(),
            'Objetivo':objective,'Origem':origin,'Tese/nota':str(thesis or ''),
        })
    st.session_state.portfolio_input=rows
    save_persistent_state()

def portfolio_rule_action(a, personal_target=0.0, weight_pct=None):
    current=float(a['row']['Close'])
    target=_safe_float(personal_target) or 0.0
    if target>0 and current>=target:
        return 'ALVO PESSOAL ATINGIDO — REVER', f'Preço atual atingiu/superou o alvo pessoal ({target:.2f}).'
    if a['fund_complete'] < 40:
        return 'REVER — DADOS INSUFICIENTES', 'Cobertura fundamental/ETF insuficiente para uma decisão forte.'
    if a['fund_label']=='Fraco' and a['tech_label']=='Fraco':
        return 'VENDER / REDUZIR — REGRA', 'Fundamentais/qualidade e técnica estão simultaneamente fracos pelas regras atuais.'
    if a['fund_label']=='Forte' and a['tech_label']=='Forte':
        if weight_pct is not None and weight_pct>=25:
            return 'MANTER / NÃO REFORÇAR', f'Qualidade forte, mas a posição já pesa cerca de {weight_pct:.1f}% da carteira.'
        return 'MANTER / CANDIDATO A REFORÇO', 'Técnica e fundamentais/qualidade estão fortes pelas regras atuais.'
    if a['fund_label']=='Forte':
        return 'MANTER / AGUARDAR', 'Fundamentais/qualidade fortes, mas a técnica ainda não confirma reforço.'
    if a['tech_label']=='Fraco':
        return 'AGUARDAR / NÃO REFORÇAR', 'Técnica fraca e fundamentais/qualidade não são fortes.'
    return 'MANTER / REVER', 'Condições mistas; não existe sinal forte para reforçar ou reduzir.'

def decision_path_status(a, hist_row):
    try:
        ts=pd.to_datetime(hist_row.get('Data decisão UTC'),utc=True,errors='coerce')
        if pd.isna(ts):
            return 'N/D'
        start_date=ts.tz_convert(None).date()
        raw=a['raw'].copy()
        idx=pd.to_datetime(raw.index)
        if getattr(idx,'tz',None) is not None:
            idx=idx.tz_localize(None)
        mask=idx.date>=start_date
        future=raw.loc[mask]
        if future.empty:
            return 'Sem dados posteriores'
        target=_safe_float(hist_row.get('Alvo técnico no momento'))
        stop=_safe_float(hist_row.get('Stop no momento'))
        target_date=None; stop_date=None
        if target is not None:
            hit=future[future['High']>=target]
            if not hit.empty: target_date=pd.to_datetime(hit.index[0]).date()
        if stop is not None:
            hit=future[future['Low']<=stop]
            if not hit.empty: stop_date=pd.to_datetime(hit.index[0]).date()
        if target_date and stop_date:
            if target_date==stop_date:
                return f'Alvo e stop tocados no mesmo dia ({target_date}); ordem intradiária desconhecida'
            return f'Alvo tocado primeiro em {target_date}' if target_date<stop_date else f'Stop tocado primeiro em {stop_date}'
        if target_date: return f'Alvo tocado em {target_date}'
        if stop_date: return f'Stop tocado em {stop_date}'
        return 'Nem alvo nem stop tocados'
    except Exception:
        return 'N/D'

def revalue_decision_history():
    out=[]
    for h in st.session_state.decision_history:
        row=dict(h)
        try:
            a=analyze_asset(h['Ticker XTB'], detailed=False)
            current=float(a['row']['Close'])
            old=float(h['Preço na decisão'])
            change=(current/old-1)*100 if old>0 else None
            cur=a['currency'] if a['currency']!='N/D' else h.get('Moeda','EUR')
            current_eur=to_eur(current,cur)
            old_eur=_safe_float(h.get('Preço na decisão EUR'))
            qty=_safe_float(h.get('Quantidade efetiva')) or _safe_float(h.get('Quantidade sugerida'))
            hypothetical=None
            if qty and current_eur is not None and old_eur is not None:
                hypothetical=(current_eur-old_eur)*qty
            row.update({
                'Preço atual':current,
                'Preço atual EUR':current_eur,
                'Variação desde decisão %':change,
                'Diferença € na quantidade registada':hypothetical,
                'Técnica atual':a['tech_label'],
                'Fundamental/ETF atual':a['fund_label'],
                'Regra atual':decision(a),
                'Percurso desde decisão':decision_path_status(a,h),
                'Data preço atual':str(a['df'].index[-1]),
            })
        except Exception as e:
            row['Erro atualização']=str(e)
        out.append(row)
    return pd.DataFrame(out)


def _fmt_num(v, digits=1, suffix=''):
    try:
        x=float(v)
        if not np.isfinite(x):
            return 'N/D'
        return f'{x:.{digits}f}{suffix}'
    except Exception:
        return 'N/D'


def _quick_scores(a):
    row=a['row']
    tech=float(a['tech_score'])
    r20=_norm(float(row['RET20']), -12, 18)
    r60=_norm(float(row['RET60']), -25, 35)
    short_parts=[(tech,0.65)]
    if r20 is not None: short_parts.append((r20,0.20))
    if r60 is not None: short_parts.append((r60,0.15))
    short_score=sum(v*w for v,w in short_parts)/sum(w for _,w in short_parts)

    fund=a.get('fund_score')
    comp=float(a.get('fund_complete') or 0)
    peer_quality=a.get('peer_quality_score')
    peer_valuation=a.get('peer_valuation_score')
    long_parts=[]
    if fund is not None: long_parts.append((float(fund),0.50))
    if peer_quality is not None: long_parts.append((float(peer_quality),0.18))
    if peer_valuation is not None: long_parts.append((float(peer_valuation),0.10))
    long_parts.append((tech,0.12))
    long_parts.append((comp,0.10))
    long_score=sum(v*w for v,w in long_parts)/sum(w for _,w in long_parts) if long_parts else None
    return round(short_score,1), (round(long_score,1) if long_score is not None else None)


def _short_context(a):
    """Traduz os principais indicadores técnicos para uma leitura prática e curta."""
    r=a['row']
    price=float(r['Close'])
    ema20=float(r['EMA20']); ema50=float(r['EMA50']); ema200=float(r['EMA200'])
    rsi_v=float(r['RSI14'])
    ret20=float(r['RET20']); ret60=float(r['RET60'])
    vol20=float(r['VOL20'])
    vol_rel=(float(r['Volume'])/vol20) if vol20>0 else None

    if price>ema20>ema50>ema200:
        trend_label='Forte tendência ascendente'
    elif price>ema200:
        trend_label='Tendência principal positiva'
    elif price<ema20<ema50<ema200:
        trend_label='Forte tendência descendente'
    else:
        trend_label='Tendência mista / sem confirmação'

    if ret20>=5 and ret60>=10:
        momentum_label='Momentum forte'
    elif ret20>0 and ret60>0:
        momentum_label='Momentum positivo'
    elif ret20<0 and ret60<0:
        momentum_label='Momentum negativo'
    else:
        momentum_label='Momentum misto'

    if rsi_v>=78:
        rsi_label='muito esticado / sobrecomprado'
    elif rsi_v>=70:
        rsi_label='esticado / sobrecomprado'
    elif rsi_v>=55:
        rsi_label='positivo, sem extremo'
    elif rsi_v>=45:
        rsi_label='neutro'
    elif rsi_v>=30:
        rsi_label='fraco'
    else:
        rsi_label='muito pressionado / sobrevenda'

    if vol_rel is None:
        volume_label='volume sem referência suficiente'
    elif vol_rel>=1.20:
        volume_label='volume confirma o movimento'
    elif vol_rel<=0.80:
        volume_label='volume abaixo do normal'
    else:
        volume_label='volume normal'

    stretched = bool(rsi_v>=70 and ret20>0)
    very_stretched = bool(rsi_v>=78 and ret20>0)
    return {
        'trend':trend_label,
        'momentum':momentum_label,
        'rsi_label':rsi_label,
        'volume_label':volume_label,
        'rsi':rsi_v,
        'ret20':ret20,
        'ret60':ret60,
        'vol_rel':vol_rel,
        'stretched':stretched,
        'very_stretched':very_stretched,
    }


def _short_action(a, holding=False):
    s,_=_quick_scores(a)
    ctx=_short_context(a)

    # Uma tendência forte pode estar demasiado esticada para uma nova entrada.
    # Para uma posição já detida, isto não é por si só motivo para vender.
    if a['tech_label']=='Forte' and s>=72:
        if ctx['very_stretched']:
            return ('MANTER / NÃO REFORÇAR AGORA' if holding else 'MUITO FORTE, MAS ESTICADA — AGUARDAR'), s
        if ctx['stretched']:
            return ('MANTER / AGUARDAR PARA REFORÇAR' if holding else 'FORTE, MAS ESTICADA — AGUARDAR MELHOR ENTRADA'), s
        return ('MANTER / REFORÇO TÁTICO' if holding else 'CANDIDATO A ENTRADA'), s
    if s>=55:
        if ctx['stretched']:
            return ('MANTER / NÃO REFORÇAR AGORA' if holding else 'AGUARDAR — PREÇO ESTICADO'), s
        return ('MANTER / AGUARDAR' if holding else 'AGUARDAR'), s
    return ('REDUZIR / NÃO REFORÇAR' if holding else 'NÃO ENTRAR AGORA'), s


def _long_action(a, holding=False):
    _,s=_quick_scores(a)
    comp=float(a.get('fund_complete') or 0)
    fund=a.get('fund_score')
    if fund is None or comp < 45:
        return 'DADOS INSUFICIENTES', s
    if a['fund_label']=='Forte' and s is not None and s>=70:
        return ('MANTER / CANDIDATO A REFORÇO' if holding else 'CANDIDATO A LONGO PRAZO'), s
    if a['fund_label']=='Forte':
        return ('MANTER / AGUARDAR MELHOR ENTRADA' if holding else 'OBSERVAR / AGUARDAR MELHOR ENTRADA'), s
    if a['fund_label']=='Fraco' and s is not None and s<50:
        return ('REVER / REDUZIR' if holding else 'NÃO PRIORIZAR'), s
    return ('MANTER / REVER' if holding else 'AGUARDAR'), s


def _short_evidence(a):
    ctx=_short_context(a)
    vol_txt=_fmt_num(ctx['vol_rel'],2,'×')
    return [
        f"{ctx['trend']} — preço {'acima' if float(a['row']['Close'])>float(a['row']['EMA200']) else 'abaixo'} da EMA200",
        f"{ctx['momentum']} — 20d {_fmt_num(ctx['ret20'],1,'%')} · 60d {_fmt_num(ctx['ret60'],1,'%')}",
        f"RSI {_fmt_num(ctx['rsi'],1)}: {ctx['rsi_label']} · {ctx['volume_label']} ({vol_txt} da média)",
    ]


def _long_evidence(a):
    info=a['info']
    fundscore='N/D' if a.get('fund_score') is None else f'{float(a["fund_score"]):.0f}/100'
    sector=sector_name(info)
    out=[f'Qualidade ajustada ao setor ({sector}): {a["fund_label"]} · {fundscore} · dados {float(a["fund_complete"]):.0f}%']
    if a['kind']=='ETF':
        expense=_num(info,'annualReportExpenseRatio')
        if expense is None: expense=_num(info,'expenseRatio')
        assets=_num(info,'totalAssets')
        out.append(f'TER: {expense*100:.2f}%' if expense is not None else 'TER: N/D')
        out.append(f'Ativos do fundo: EUR/USD {assets/1e9:.1f} mil M' if assets is not None else 'Ativos do fundo: N/D')
    else:
        peer=a.get('peer_quality_score'); pval=a.get('peer_valuation_score'); pcount=a.get('peer_count')
        if peer is not None:
            valtxt=f' · avaliacao relativa {float(pval):.0f}/100' if pval is not None else ''
            out.append(f'Vs. {int(pcount)} pares do setor: qualidade {float(peer):.0f}/100{valtxt}')
        rg=_num(info,'revenueGrowth'); roe=_num(info,'returnOnEquity'); fcf=_num(info,'freeCashflow'); de=_num(info,'debtToEquity')
        sector_raw=str(info.get('sector') or '')
        roe_floor=_sector_fundamental_profile(info)[2]
        roe_note=' · ROE fraco para o setor' if roe is not None and roe<roe_floor else ''
        fcf_txt='FCF positivo' if fcf is not None and fcf>0 else ('FCF negativo' if fcf is not None else 'FCF N/D')
        metrics=f'Receitas {_fmt_num(rg*100 if rg is not None else None,1,"%")} · ROE {_fmt_num(roe*100 if roe is not None else None,1,"%")}'+roe_note
        if peer is None:
            out.append(metrics)
            debt_txt='N/D' if de is None else _fmt_num(de,0,'%')
            if sector_raw=='Financial Services':
                out.append(f'{fcf_txt} · divida/capital proprio nao usada como criterio principal em financeiras')
            else:
                out.append(f'{fcf_txt} · Divida/Capital proprio {debt_txt}')
        else:
            out.append(metrics+' · '+fcf_txt)
    return out[:3]


def _rank_score(series, higher_better=True):
    s=pd.to_numeric(series,errors='coerce')
    n=int(s.notna().sum())
    if n<3:
        return pd.Series(np.nan,index=s.index,dtype=float)
    ranks=s.rank(method='average',ascending=True)
    if n==1:
        return pd.Series(50.0,index=s.index,dtype=float)
    pct=(ranks-1.0)/(n-1.0)*100.0
    return pct if higher_better else (100.0-pct)


def apply_peer_context(rows):
    # Uses only assets already downloaded by the Today scan; no extra network calls.
    if not rows:
        return rows
    records=[]
    for rec in rows:
        a=rec.get('_analysis') or {}
        if a.get('kind')!='A\u00e7\u00e3o':
            continue
        info=a.get('info') or {}
        market_cap=_num(info,'marketCap')
        fcf=_num(info,'freeCashflow')
        records.append({
            'Ticker':a.get('xtb_ticker'),
            'Setor':sector_name(info),
            'Receitas':(_num(info,'revenueGrowth')*100 if _num(info,'revenueGrowth') is not None else None),
            'Lucros':(_num(info,'earningsGrowth')*100 if _num(info,'earningsGrowth') is not None else None),
            'Margem operacional':(_num(info,'operatingMargins')*100 if _num(info,'operatingMargins') is not None else None),
            'Margem liquida':(_num(info,'profitMargins')*100 if _num(info,'profitMargins') is not None else None),
            'ROE':(_num(info,'returnOnEquity')*100 if _num(info,'returnOnEquity') is not None else None),
            'Divida':_num(info,'debtToEquity'),
            'FCF yield':((fcf/market_cap*100) if fcf is not None and market_cap and market_cap>0 else None),
            'P/E':_num(info,'trailingPE'),
            'Forward P/E':_num(info,'forwardPE'),
            'P/B':_num(info,'priceToBook'),
            'EV/EBITDA':_num(info,'enterpriseToEbitda'),
        })
    if not records:
        return rows
    frame=pd.DataFrame(records).set_index('Ticker')
    peer_map={}
    for sector,sub in frame.groupby('Setor'):
        if len(sub)<3:
            continue
        raw_sector=None
        for rec in rows:
            a=rec.get('_analysis') or {}
            if a.get('xtb_ticker') in sub.index:
                raw_sector=str((a.get('info') or {}).get('sector') or '')
                break
        quality_cols=['Receitas','Lucros','Margem operacional','Margem liquida','ROE','FCF yield']
        lower_quality=['Divida']
        if raw_sector=='Financial Services':
            quality_cols=['Receitas','Lucros','Margem liquida','ROE']
            lower_quality=[]
        quality_parts=[]
        for col in quality_cols:
            if col in sub and pd.to_numeric(sub[col],errors='coerce').notna().sum()>=3:
                quality_parts.append(_rank_score(sub[col],True).rename(col))
        for col in lower_quality:
            if col in sub and pd.to_numeric(sub[col],errors='coerce').notna().sum()>=3:
                quality_parts.append(_rank_score(sub[col],False).rename(col))
        valuation_parts=[]
        for col in ['P/E','Forward P/E','P/B','EV/EBITDA']:
            if col in sub:
                vals=pd.to_numeric(sub[col],errors='coerce').where(pd.to_numeric(sub[col],errors='coerce')>0)
                if vals.notna().sum()>=3:
                    valuation_parts.append(_rank_score(vals,False).rename(col))
        if 'FCF yield' in sub and pd.to_numeric(sub['FCF yield'],errors='coerce').notna().sum()>=3:
            valuation_parts.append(_rank_score(sub['FCF yield'],True).rename('FCF yield'))
        qscore=pd.concat(quality_parts,axis=1).mean(axis=1,skipna=True) if quality_parts else pd.Series(np.nan,index=sub.index)
        vscore=pd.concat(valuation_parts,axis=1).mean(axis=1,skipna=True) if valuation_parts else pd.Series(np.nan,index=sub.index)
        for ticker in sub.index:
            peer_map[ticker]={
                'quality':(float(qscore.loc[ticker]) if pd.notna(qscore.loc[ticker]) else None),
                'valuation':(float(vscore.loc[ticker]) if pd.notna(vscore.loc[ticker]) else None),
                'count':int(len(sub)),
            }
    for rec in rows:
        a=rec.get('_analysis') or {}
        peer=peer_map.get(a.get('xtb_ticker'))
        if peer:
            a['peer_quality_score']=peer['quality']
            a['peer_valuation_score']=peer['valuation']
            a['peer_count']=peer['count']
            rec['Qualidade relativa setor']=peer['quality']
            rec['Valor relativo setor']=peer['valuation']
            rec['Pares setor']=peer['count']
            long_action,long_score=_long_action(a,holding=False)
            rec['Longo prazo']=long_action
            rec['Score longo']=long_score
            rec['Evid\u00eancias longo']=' · '.join(_long_evidence(a))
    return rows


def quick_candidate_row(ticker):
    a=analyze_asset(ticker, detailed=False)
    short_action,short_score=_short_action(a,holding=False)
    long_action,long_score=_long_action(a,holding=False)
    row=a['row']; info=a['info']
    return {
        'Ticker':a['xtb_ticker'],
        'Empresa':a['company'],
        'Mercado':a['market'],
        'Setor':sector_name(info),
        'Tipo':a['kind'],
        'Moeda':a['currency'],
        'Preço':float(row['Close']),
        'Curto prazo':short_action,
        'Score curto':short_score,
        'Evidências curto':' · '.join(_short_evidence(a)),
        'Longo prazo':long_action,
        'Score longo':long_score,
        'Evidências longo':' · '.join(_long_evidence(a)),
        'Qualidade relativa setor':None,
        'Valor relativo setor':None,
        'Pares setor':None,
        'Data':str(a['df'].index[-1].date()),
        '_analysis':a,
    }


def quick_universe(markets, mode='Rápido'):
    per_market=10 if mode=='Rápido' else 18
    out=[]
    for m in markets:
        out += MARKETS[m][:per_market]
    out += st.session_state.watchlist
    return list(dict.fromkeys(out))


def _compact_table(df, horizon):
    if df.empty:
        return df
    if horizon=='curto':
        cols=['Ticker','Empresa','Setor','Preço','Moeda','Curto prazo','Score curto','Evidências curto']
    else:
        cols=['Ticker','Empresa','Setor','Preço','Moeda','Longo prazo','Score longo','Evidências longo']
    return df[[c for c in cols if c in df.columns]].copy()


def _show_evidence(title, action, score, evidence):
    st.markdown(f'### {title}')
    st.metric('Decisão', action)
    if score is not None:
        st.caption(f'Score: {score:.1f}/100')
    for e in evidence:
        st.write('• '+e)


def _portfolio_quick_row(r):
    t=str(r.get('Ticker XTB','')).upper().strip()
    q=_safe_float(r.get('Quantidade')) or 0
    pm=_safe_float(r.get('Preço médio')) or 0
    if not t or q<=0 or pm<=0:
        return None
    a=analyze_asset(t,detailed=False)
    price=float(a['row']['Close'])
    cur=a['currency']
    pe=to_eur(price,cur)
    pm_eur=to_eur(pm,cur)
    short_action,short_score=_short_action(a,holding=True)
    long_action,long_score=_long_action(a,holding=True)
    objective=str(r.get('Objetivo') or 'Longo prazo')
    primary=short_action if objective=='Curto prazo' else long_action
    ev=_short_evidence(a) if objective=='Curto prazo' else _long_evidence(a)
    pa=_safe_float(r.get('Preço alvo pessoal')) or 0
    if pa>0 and price>=pa:
        primary='ALVO PESSOAL ATINGIDO — REVER'
    return {
        'Ticker XTB':a['xtb_ticker'],'Empresa':a['company'],'Setor':sector_name(a['info']),'Objetivo':objective,
        'Preço atual':price,'Moeda':cur,'Quantidade':q,'Preço médio':pm,
        'P/L %':(price/pm-1)*100,'P/L EUR aprox.':((pe-pm_eur)*q if pe is not None and pm_eur is not None else None),
        'Decisão principal':primary,'Curto prazo':short_action,'Score curto':short_score,
        'Longo prazo':long_action,'Score longo':long_score,'Resumo':' · '.join(ev),
        'Preço alvo pessoal':pa if pa>0 else None,'Origem':str(r.get('Origem') or ''),'Data':str(a['df'].index[-1].date()),
        '_analysis':a,
    }


# -----------------------------------------------------------------------------
# Interface simples / rápida (v14)
# -----------------------------------------------------------------------------
st.markdown('''
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1180px;}
[data-testid="stMetric"] {background: rgba(127,127,127,.06); border: 1px solid rgba(127,127,127,.18); padding: .7rem; border-radius: 14px;}
.asset-card {border:1px solid rgba(127,127,127,.20); border-radius:16px; padding:14px 15px; margin:9px 0; background:rgba(127,127,127,.035);}
.asset-head {display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:7px;}
.asset-title {font-size:1.02rem; font-weight:750; line-height:1.2;}
.asset-sub {opacity:.68; font-size:.82rem; margin-top:2px;}
.asset-action {font-weight:750; text-align:right; font-size:.90rem;}
.ev {font-size:.88rem; margin-top:4px; opacity:.92;}
.score {opacity:.70; font-size:.78rem; margin-top:3px;}
.good {color:#16a34a;} .wait {color:#d97706;} .bad {color:#dc2626;} .neutral {color:#64748b;}
.section-note {opacity:.72; font-size:.88rem; margin-bottom:.5rem;}
@media (max-width: 700px) {
  .block-container {padding-left: .85rem; padding-right: .85rem;}
  .asset-card {padding:12px;}
  .asset-head {display:block;}
  .asset-action {text-align:left; margin-top:7px;}
}
</style>
''', unsafe_allow_html=True)


def _action_css(action):
    a=str(action).upper()
    if any(x in a for x in ['CANDIDATO','REFORÇO','MANTER']): return 'good'
    if any(x in a for x in ['REDUZIR','NÃO ENTRAR','NÃO PRIORIZAR']): return 'bad'
    if any(x in a for x in ['AGUARDAR','OBSERVAR','REVER']): return 'wait'
    return 'neutral'


def _asset_card(ticker, company, action, score, evidence, price=None, currency='', subtitle=''):
    title=html.escape(str(ticker))
    company=html.escape(str(company or ''))
    action_txt=html.escape(str(action))
    cls=_action_css(action)
    sub_parts=[]
    if company and company!='N/D': sub_parts.append(company)
    if subtitle: sub_parts.append(html.escape(str(subtitle)))
    if price is not None:
        try: sub_parts.append(f'{float(price):.2f} {html.escape(str(currency))}')
        except Exception: pass
    sub=' · '.join(sub_parts)
    ev=''.join(f'<div class="ev">• {html.escape(str(x))}</div>' for x in evidence[:3])
    score_txt=f'<div class="score">Score {float(score):.0f}/100</div>' if score is not None else ''
    st.markdown(
        f'<div class="asset-card"><div class="asset-head"><div><div class="asset-title">{title}</div>'
        f'<div class="asset-sub">{sub}</div></div><div class="asset-action {cls}">{action_txt}{score_txt}</div></div>{ev}</div>',
        unsafe_allow_html=True,
    )


def _top_cards(df, rows, horizon, n=5):
    if df.empty:
        st.info('Sem resultados suficientes para este filtro.')
        return
    action_col='Curto prazo' if horizon=='curto' else 'Longo prazo'
    score_col='Score curto' if horizon=='curto' else 'Score longo'
    evidence_fn=_short_evidence if horizon=='curto' else _long_evidence
    for _,rr in df.head(n).iterrows():
        rec=next((x for x in rows if x['Ticker']==rr['Ticker']),None)
        if rec is None: continue
        a=rec['_analysis']
        _asset_card(
            rr['Ticker'], rr['Empresa'], rr[action_col], rr.get(score_col), evidence_fn(a),
            rr.get('Preço'), rr.get('Moeda',''), f"{rr.get('Setor','N/D')} · {rr.get('Mercado','')}"
        )


def _today_dashboard_groups(view):
    """Classifica o scan já calculado sem fazer novas chamadas de rede.

    'Valor relativo setor' é um ranking entre pares analisados, não um valor justo intrínseco.
    """
    if view is None or view.empty:
        return view, view, view
    d=view.copy()
    short_txt=d['Curto prazo'].astype(str).str.upper()
    long_txt=d['Longo prazo'].astype(str).str.upper()
    short_score=pd.to_numeric(d['Score curto'],errors='coerce')
    long_score=pd.to_numeric(d['Score longo'],errors='coerce')
    value_score=pd.to_numeric(d.get('Valor relativo setor'),errors='coerce') if 'Valor relativo setor' in d.columns else pd.Series(np.nan,index=d.index)
    quality_peer=pd.to_numeric(d.get('Qualidade relativa setor'),errors='coerce') if 'Qualidade relativa setor' in d.columns else pd.Series(np.nan,index=d.index)

    # Entrada agora: técnica permite entrada e longo prazo não é fraco.
    now_mask=short_txt.str.contains('CANDIDATO A ENTRADA',na=False) & (long_score>=60) & ~long_txt.str.contains('NÃO PRIORIZAR|DADOS INSUFICIENTES',regex=True,na=False)
    now=d.loc[now_mask].copy().sort_values(['Score curto','Score longo'],ascending=False,na_position='last')

    # Possível subavaliação: avaliação relativa forte vs. pelo menos 3 pares + qualidade suficiente.
    value_mask=(value_score>=65) & (long_score>=60) & ((quality_peer>=45) | quality_peer.isna())
    value=d.loc[value_mask].copy().sort_values(['Valor relativo setor','Score longo'],ascending=False,na_position='last')

    # Boa qualidade/score de longo prazo, mas o timing técnico pede espera.
    wait_mask=(long_score>=65) & ~now_mask & short_txt.str.contains('AGUARDAR|ESTICADA|NÃO ENTRAR',regex=True,na=False)
    wait=d.loc[wait_mask].copy().sort_values(['Score longo','Score curto'],ascending=False,na_position='last')
    return now, value, wait


def _dashboard_card(rec, label, score=None, extra=None):
    a=rec['_analysis']
    evidence=[]
    if label=='agora':
        evidence=_short_evidence(a)[:2] + [_long_evidence(a)[0]]
        action=rec['Curto prazo']
        score=rec.get('Score curto') if score is None else score
    elif label=='valor':
        val=rec.get('Valor relativo setor')
        peers=rec.get('Pares setor')
        evidence=[
            f"Valor relativo ao setor: {_fmt_num(val,0,'/100')}" + (f" · {int(peers)} pares analisados" if peers else ''),
            _long_evidence(a)[0],
            f"Timing atual: {rec.get('Curto prazo','N/D')}",
        ]
        action='POSSÍVEL VALOR RELATIVO'
        score=val if score is None else score
    else:
        evidence=_long_evidence(a)[:2] + [f"Timing: {rec.get('Curto prazo','N/D')}"]
        action='BOA TESE · AGUARDAR ENTRADA'
        score=rec.get('Score longo') if score is None else score
    if extra:
        evidence.append(extra)
    _asset_card(
        rec['Ticker'],rec['Empresa'],action,score,evidence,rec.get('Preço'),rec.get('Moeda',''),
        f"{rec.get('Setor','N/D')} · {rec.get('Mercado','')}"
    )


st.caption('Modo simples: decisão prática primeiro, 3 evidências interpretadas e detalhe apenas quando pedes.')
PAGE = st.radio('Navegação', ['Hoje', 'Carteira', 'Analisar'], horizontal=True, label_visibility='collapsed', key='main_page')

if PAGE == 'Hoje':
    st.subheader('Dashboard de oportunidades')
    st.markdown('<div class="section-note">Primeiro a decisão prática. O mesmo scan é organizado por entrada, valor relativo ao setor e oportunidades que pedem paciência.</div>', unsafe_allow_html=True)

    c1,c2=st.columns([3,1])
    with c1:
        scan_markets=st.multiselect('Mercados',list(MARKETS.keys()),default=['EUA','Alemanha','Portugal'],key='v14_markets')
    with c2:
        scan_mode=st.selectbox('Pesquisa',['Rápida','Alargada'],index=0,key='v14_speed',help='Rápida analisa menos ativos e é a opção recomendada no telemóvel.')
    only_type=st.selectbox('Tipo',['Todos','Ação','ETF'],index=0,key='v14_type')

    if st.button('Atualizar oportunidades',type='primary',use_container_width=True,key='v14_scan'):
        if not scan_markets:
            st.error('Escolhe pelo menos um mercado.')
        else:
            rows=[]
            universe=quick_universe(scan_markets,'Rápido' if scan_mode=='Rápida' else 'Alargado')
            prog=st.progress(0,text='A analisar apenas o essencial...')
            for i,t in enumerate(universe,1):
                try:
                    q=quick_candidate_row(t)
                    if only_type=='Todos' or q['Tipo']==only_type:
                        rows.append(q)
                except Exception:
                    pass
                prog.progress(i/max(len(universe),1),text=f'{i}/{len(universe)}')
            prog.empty()
            rows=apply_peer_context(rows)
            st.session_state['v14_scan_rows']=rows
            st.session_state['v20_scan_time']=datetime.now().strftime('%d/%m/%Y %H:%M')

    rows=st.session_state.get('v14_scan_rows',[])
    if rows:
        df=pd.DataFrame([{k:v for k,v in r.items() if k!='_analysis'} for r in rows])
        sectors=sorted([x for x in df['Setor'].dropna().unique().tolist() if x and x!='N/D'])
        chosen_sector=st.selectbox('Setor',['Todos']+sectors,key='v14_sector')
        view=df if chosen_sector=='Todos' else df[df['Setor']==chosen_sector]
        scan_time=st.session_state.get('v20_scan_time')
        if scan_time:
            st.caption(f'Última análise nesta sessão: {scan_time}. Os preços podem ser atrasados conforme a fonte.')

        now,value,wait=_today_dashboard_groups(view)
        m1,m2,m3,m4=st.columns(4)
        m1.metric('Analisados',len(view))
        m2.metric('Entrada agora',len(now))
        m3.metric('Valor relativo',len(value))
        m4.metric('Aguardar entrada',len(wait))

        st.markdown('### 🟢 Oportunidades de entrada agora')
        st.caption('Técnica permite entrada e o quadro de longo prazo não é fraco. Não é uma ordem de compra.')
        if now.empty:
            st.info('Nenhuma oportunidade passa estes filtros neste momento. AGUARDAR também é uma decisão válida.')
        else:
            for _,rr in now.head(5).iterrows():
                rec=next((x for x in rows if x['Ticker']==rr['Ticker']),None)
                if rec: _dashboard_card(rec,'agora')

        st.markdown('### 💎 Possivelmente subvalorizadas vs. setor')
        st.caption('Avaliação atrativa relativamente aos pares analisados do mesmo setor + qualidade suficiente. Isto não é um valor justo intrínseco.')
        if value.empty:
            st.info('Sem casos com comparação setorial suficientemente forte neste scan.')
        else:
            for _,rr in value.head(5).iterrows():
                rec=next((x for x in rows if x['Ticker']==rr['Ticker']),None)
                if rec: _dashboard_card(rec,'valor')

        st.markdown('### 🟠 Boas empresas · aguardar melhor entrada')
        st.caption('O longo prazo é interessante, mas o timing técnico não justifica perseguir o preço agora.')
        if wait.empty:
            st.info('Sem casos relevantes nesta categoria.')
        else:
            for _,rr in wait.head(5).iterrows():
                rec=next((x for x in rows if x['Ticker']==rr['Ticker']),None)
                if rec: _dashboard_card(rec,'espera')

        short=view.sort_values('Score curto',ascending=False,na_position='last').head(10)
        long=view.sort_values('Score longo',ascending=False,na_position='last').head(10)
        with st.expander('Explorar rankings completos'):
            hshort,hlong=st.tabs(['Top 10 curto prazo','Top 10 longo prazo'])
            with hshort:
                st.dataframe(_compact_table(short,'curto'),hide_index=True,use_container_width=True)
            with hlong:
                st.dataframe(_compact_table(long,'longo'),hide_index=True,use_container_width=True)

        candidates=list(dict.fromkeys(now['Ticker'].tolist()+value['Ticker'].tolist()+wait['Ticker'].tolist()+short['Ticker'].tolist()+long['Ticker'].tolist()))
        if candidates:
            st.divider()
            st.markdown('### Decidir sobre uma oportunidade')
            pick=st.selectbox('Ativo',candidates,key='v14_pick')
            rec=next((r for r in rows if r['Ticker']==pick),None)
            if rec:
                a=rec['_analysis']
                cshort,clong=st.columns(2)
                cshort.metric('Curto prazo',rec['Curto prazo'],f"{rec['Score curto']:.0f}/100")
                clong.metric('Longo prazo',rec['Longo prazo'],f"{rec['Score longo']:.0f}/100" if rec['Score longo'] is not None else 'N/D')
                with st.expander('Ver 3 evidências de cada horizonte'):
                    e1,e2=st.columns(2)
                    with e1:
                        st.markdown('**Curto prazo**')
                        for e in _short_evidence(a): st.write('• '+e)
                    with e2:
                        st.markdown('**Longo prazo**')
                        for e in _long_evidence(a): st.write('• '+e)

                with st.expander('Aceitar / rejeitar'):
                    objective=st.selectbox('Objetivo',['Longo prazo','Curto prazo'],key='v14_obj')
                    actual_qty=st.number_input('Quantidade efetivamente comprada',min_value=0.0,value=0.0,step=0.01,key='v14_qty')
                    actual_entry=st.number_input('Preço efetivo',min_value=0.0,value=float(a['row']['Close']),step=0.01,key='v14_entry')
                    b1,b2=st.columns(2)
                    with b1:
                        if st.button('✅ Aceitar',use_container_width=True,key='v14_accept'):
                            if actual_qty<=0:
                                st.error('Indica a quantidade efetivamente comprada.')
                            else:
                                log_decision(a,'ACEITE',actual_entry=actual_entry,actual_qty=actual_qty,objective=objective)
                                add_or_merge_portfolio_position(a['xtb_ticker'],actual_qty,actual_entry,objective,0,'Oportunidade aceite',datetime.now().date(),'Aceite através do resumo de oportunidades')
                                st.success('Adicionada à carteira.')
                    with b2:
                        if st.button('❌ Rejeitar e acompanhar',use_container_width=True,key='v14_reject'):
                            log_decision(a,'REJEITADA',objective=objective)
                            st.success('Guardada para comparação futura.')
    else:
        st.info('A dashboard está pronta. Carrega em **Atualizar oportunidades** para gerar a análise atual sem tornar o arranque da app lento.')

elif PAGE == 'Carteira':
    st.subheader('Minha carteira')
    if not st.session_state.get('_persistent_loaded'):
        with st.spinner('A carregar a carteira guardada...'):
            load_persistent_state()
    status=st.session_state.get('persistence_status','Apenas sessão')
    if status=='Ligado':
        last=st.session_state.get('persistence_last_save')
        msg='Dados permanentes: **Ligado**' + (f' · última gravação {last}' if last else '')
        st.success(msg)
    elif status=='Erro':
        st.error('Dados permanentes: erro de ligação. A sessão continua a funcionar, mas as alterações podem não sobreviver a um reinício.')
        with st.expander('Ver erro de armazenamento'):
            st.code(st.session_state.get('persistence_error','Erro desconhecido'))
    else:
        st.warning('Dados permanentes: **não configurados**. A carteira fica apenas nesta sessão. Configura o Supabase nos Secrets do Streamlit para guardar automaticamente.')
        with st.expander('Como ativar a gravação permanente'):
            st.markdown('''
1. Cria um projeto gratuito no **Supabase**.
2. Executa o ficheiro `supabase_setup.sql` no SQL Editor do projeto.
3. No Streamlit Cloud abre **App settings → Secrets** e adiciona:
```toml
SUPABASE_URL = "https://SEU-PROJETO.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
PORTFOLIO_OWNER_ID = "carteira-principal"
APP_PASSWORD = "uma-palavra-passe-forte"
```
4. Guarda os Secrets e reinicia a app. A carteira passa a carregar e gravar automaticamente.

**Não coloques a chave secreta nem a palavra-passe no GitHub.** Devem existir apenas nos Secrets do Streamlit.
''')

    cstore1,cstore2=st.columns(2)
    with cstore1:
        if st.button('Guardar carteira agora',use_container_width=True,key='persist_save_now'):
            if save_persistent_state(show_error=True):
                st.success('Carteira e histórico guardados permanentemente.')
    with cstore2:
        if st.button('Recarregar dados guardados',use_container_width=True,key='persist_reload_now',disabled=not persistence_enabled()):
            load_persistent_state(force=True)
            st.success('Dados permanentes recarregados.')
            st.rerun()

    st.caption('A pergunta principal aqui é simples: manter, reforçar, aguardar ou rever?')

    with st.expander('➕ Adicionar posição'):
        with st.form('v14_manual_position',clear_on_submit=False):
            a1,a2,a3=st.columns(3)
            with a1: mt=st.text_input('Ticker XTB',placeholder='Ex.: ASML.NL')
            with a2: mq=st.number_input('Quantidade',min_value=0.0,value=0.0,step=0.01)
            with a3: mp=st.number_input('Preço médio',min_value=0.0,value=0.0,step=0.01)
            a4,a5=st.columns(2)
            with a4: mo=st.selectbox('Objetivo',['Longo prazo','Curto prazo'])
            with a5: mtarget=st.number_input('Alvo pessoal (opcional)',min_value=0.0,value=0.0,step=0.01)
            md=st.date_input('Data de entrada',value=datetime.now().date())
            thesis=st.text_input('Nota (opcional)',placeholder='Porque compraste / o que queres acompanhar')
            submitted=st.form_submit_button('Adicionar à carteira',type='primary',use_container_width=True)
        if submitted:
            if not str(mt).strip() or mq<=0 or mp<=0:
                st.error('Indica ticker, quantidade e preço médio válidos.')
            else:
                try:
                    aa=analyze_asset(str(mt).upper().strip(),detailed=False)
                    add_or_merge_portfolio_position(aa['xtb_ticker'],mq,mp,mo,mtarget,'Posição existente adicionada por mim',md,thesis)
                    add_watchlist(aa['xtb_ticker'])
                    st.success(f"{aa['xtb_ticker']} adicionada.")
                except Exception as e:
                    st.error(f'Não foi possível adicionar: {e}')

    with st.expander('Importar / exportar'):
        up=st.file_uploader('Carregar carteira CSV',type=['csv'],key='v14_port_upload')
        if up is not None and st.button('Importar CSV',key='v14_port_import'):
            try:
                imp=pd.read_csv(up)
                if not {'Ticker XTB','Quantidade','Preço médio'}.issubset(imp.columns):
                    st.error('O CSV precisa de: Ticker XTB, Quantidade e Preço médio.')
                else:
                    st.session_state.portfolio_input=imp.to_dict('records')
                    save_persistent_state(show_error=True)
                    st.success('Carteira importada e guardada.')
            except Exception as e:
                st.error(str(e))
        pexport=pd.DataFrame(st.session_state.portfolio_input)
        if not pexport.empty:
            st.download_button('Descarregar carteira CSV',pexport.to_csv(index=False).encode('utf-8'),'minha_carteira.csv','text/csv',use_container_width=True)

    if st.session_state.portfolio_input:
        if st.button('Atualizar carteira',type='primary',use_container_width=True,key='v14_port_refresh'):
            out=[]
            prog=st.progress(0,text='A atualizar decisões...')
            for i,r in enumerate(st.session_state.portfolio_input,1):
                try:
                    qr=_portfolio_quick_row(r)
                    if qr: out.append(qr)
                except Exception as e:
                    out.append({'Ticker XTB':str(r.get('Ticker XTB','')),'Erro':str(e)})
                prog.progress(i/max(len(st.session_state.portfolio_input),1),text=f'{i}/{len(st.session_state.portfolio_input)}')
            prog.empty()
            st.session_state['v14_portfolio_rows']=out
            st.session_state['portfolio_rows']=[{k:v for k,v in x.items() if k!='_analysis'} for x in out]

        prow=st.session_state.get('v14_portfolio_rows',[])
        if prow:
            good=[r for r in prow if '_analysis' in r]
            if good:
                attention=sum(1 for r in good if any(x in str(r['Decisão principal']).upper() for x in ['REVER','REDUZIR','ALVO']))
                pnl_vals=[_safe_float(r.get('P/L EUR aprox.')) for r in good]
                pnl_total=sum(x for x in pnl_vals if x is not None)
                k1,k2,k3=st.columns(3)
                k1.metric('Posições',len(good))
                k2.metric('Atenção',attention)
                k3.metric('P/L aprox.',f'€{pnl_total:,.0f}')

                st.markdown('### Resumo das posições')
                for r in good:
                    ev=[x.strip() for x in str(r.get('Resumo','')).split(' · ') if x.strip()]
                    subtitle=f"{r.get('Objetivo','')} · P/L {float(r.get('P/L %',0)):+.1f}%"
                    _asset_card(r['Ticker XTB'],r['Empresa'],r['Decisão principal'],r['Score longo'] if r.get('Objetivo')!='Curto prazo' else r['Score curto'],ev,r['Preço atual'],r['Moeda'],subtitle)

                with st.expander('Ver tabela da carteira'):
                    pdf=pd.DataFrame([{k:v for k,v in r.items() if k!='_analysis'} for r in good])
                    showcols=['Ticker XTB','Objetivo','Preço atual','Moeda','P/L %','Decisão principal','Curto prazo','Longo prazo']
                    st.dataframe(pdf[[c for c in showcols if c in pdf.columns]],hide_index=True,use_container_width=True)

                st.divider()
                sel=st.selectbox('Detalhe de uma posição',[r['Ticker XTB'] for r in good],key='v14_port_pick')
                if st.button('Ver alvos e prazos',key='v14_port_detail',use_container_width=True):
                    with st.spinner('A calcular histórico apenas desta posição...'):
                        a=analyze_asset(sel,detailed=True)
                    st.session_state['v14_port_detail_result']=a
                detail=st.session_state.get('v14_port_detail_result')
                if detail is not None and detail.get('xtb_ticker')==sel:
                    current=float(detail['row']['Close'])
                    d1,d2,d3=st.columns(3)
                    d1.metric('Preço',f'{current:.2f} {detail["currency"]}')
                    d2.metric('Alvo técnico',f'{detail["target"]:.2f} {detail["currency"]}')
                    tt=detail.get('target_time',{})
                    d3.metric('Tempo histórico',f'{tt.get("median_days"):.0f} dias' if tt.get('median_days') is not None else 'N/D')
                    if tt.get('hit_rate') is not None:
                        st.caption(f"{tt['hit_rate']:.1f}% das amostras semelhantes tocaram um movimento equivalente em até 60 dias de mercado. Histórico, não previsão.")
            else:
                st.warning('Não foi possível atualizar posições válidas.')
        else:
            st.info('Carrega em **Atualizar carteira** para ver as decisões atuais.')
    else:
        st.info('Ainda não tens posições registadas.')

    if st.session_state.decision_history:
        with st.expander('Decisões rejeitadas / aceites'):
            hist=pd.DataFrame(st.session_state.decision_history)
            cols=['Data decisão UTC','Ticker XTB','Decisão utilizador','Preço na decisão','Moeda','Objetivo']
            st.dataframe(hist[[c for c in cols if c in hist.columns]],hide_index=True,use_container_width=True)
            if st.button('Comparar com preços atuais',key='v14_hist_refresh',use_container_width=True):
                with st.spinner('A atualizar decisões guardadas...'):
                    st.session_state['v14_hist_revalued']=revalue_decision_history()
            h2=st.session_state.get('v14_hist_revalued')
            if isinstance(h2,pd.DataFrame) and not h2.empty:
                cols2=['Ticker XTB','Decisão utilizador','Preço na decisão','Preço atual','Variação desde decisão %','Percurso desde decisão','Regra atual']
                st.dataframe(h2[[c for c in cols2 if c in h2.columns]],hide_index=True,use_container_width=True)

elif PAGE == 'Analisar':
    st.subheader('Analisar uma ação ou ETF')
    st.caption('Primeiro uma resposta rápida. Histórico, alvos e prazos só são calculados quando pedires.')
    t1,t2=st.columns([2,1])
    with t1:
        ticker=st.text_input('Ticker XTB',value='AAPL.US',key='v14_an_ticker').upper().strip()
    with t2:
        market_hint=st.selectbox('Mercado (opcional)',['Auto']+list(MARKETS.keys()),key='v14_an_market')
    if st.button('Analisar agora',type='primary',use_container_width=True,key='v14_an_run'):
        try:
            with st.spinner('A analisar o essencial...'):
                a=analyze_asset(ticker,None if market_hint=='Auto' else market_hint,detailed=False)
            st.session_state['v14_analysis']=a
            st.session_state.pop('v14_analysis_detail',None)
            add_watchlist(a['xtb_ticker'])
        except Exception as e:
            st.error(str(e))

    a=st.session_state.get('v14_analysis')
    if a is not None:
        st.markdown(f"## {a['xtb_ticker']} · {a['company']}")
        st.caption(f"{a['market']} · {a['currency']} · dados até {a['df'].index[-1].date()}")
        short_action,short_score=_short_action(a,holding=False)
        long_action,long_score=_long_action(a,holding=False)

        sh,lh=st.tabs(['Curto prazo','Longo prazo'])
        with sh:
            _asset_card(a['xtb_ticker'],a['company'],short_action,short_score,_short_evidence(a),float(a['row']['Close']),a['currency'],'5–30 dias de mercado')
        with lh:
            _asset_card(a['xtb_ticker'],a['company'],long_action,long_score,_long_evidence(a),float(a['row']['Close']),a['currency'],'Meses / anos')

        p1,p2=st.columns(2)
        p1.metric('Preço atual',f"{float(a['row']['Close']):.2f} {a['currency']}")
        p2.metric('Tipo',a['kind'])

        if st.button('Ver alvos, prazo e histórico',use_container_width=True,key='v14_an_detail'):
            try:
                with st.spinner('A calcular histórico desta ação...'):
                    detailed=analyze_asset(a['xtb_ticker'],detailed=True)
                st.session_state['v14_analysis_detail']=detailed
            except Exception as e:
                st.error(str(e))

        detailed=st.session_state.get('v14_analysis_detail')
        if detailed is not None and detailed.get('xtb_ticker')==a['xtb_ticker']:
            st.markdown('### Alvos e prazo')
            p1,p2,p3=st.columns(3)
            p1.metric('Stop técnico',f"{detailed['stop']:.2f} {detailed['currency']}")
            p2.metric('Alvo técnico (2× risco)',f"{detailed['target']:.2f} {detailed['currency']}")
            tt=detailed.get('target_time',{})
            p3.metric('Tempo histórico',f"{tt.get('median_days'):.0f} dias" if tt.get('median_days') is not None else 'N/D')
            if tt.get('hit_rate') is not None:
                st.caption(f"Taxa histórica de toque do movimento equivalente: {tt['hit_rate']:.1f}% em até 60 dias de mercado · {tt.get('samples',0)} amostras. Não é previsão.")
            if isinstance(detailed.get('scenarios'),pd.DataFrame) and not detailed['scenarios'].empty:
                with st.expander('Cenários históricos 5 / 10 / 15 / 30 dias'):
                    st.dataframe(detailed['scenarios'],hide_index=True,use_container_width=True)

        with st.expander('Ver critérios e fontes'):
            st.markdown('**Técnica**')
            st.dataframe(pd.DataFrame([{'Critério':k,'Cumpre':'Sim' if v else 'Não'} for k,v in a['tech_tests'].items()]),hide_index=True,use_container_width=True)
            st.markdown('**Fundamentais / ETF**')
            st.dataframe(a['fund_table'],hide_index=True,use_container_width=True)
            source_block(ticker,a)

with st.expander('Como ler a app'):
    st.markdown('''
- **Curto prazo**: aproximadamente 5–30 dias de mercado. Dá prioridade a tendência, momentum, RSI e volume.
- **Longo prazo**: meses/anos. Dá prioridade a qualidade fundamental/ETF e qualidade dos dados.
- Cada cartão mostra no máximo **3 evidências** para explicar a conclusão.
- **AGUARDAR** é uma decisão válida; a app não força uma compra.
- **Alvo técnico (2× risco)** não é um valor justo fundamental.
- Prazo e cenários são comparações históricas, não previsões.
- A fonte atual é Yahoo Finance via `yfinance`; confirma preço, spread, sessão e informação oficial antes de executar uma ordem.
''')
