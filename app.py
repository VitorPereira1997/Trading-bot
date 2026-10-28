import math
import html
import io
import json
import urllib.request
import urllib.error
import urllib.parse
import hmac
import hashlib
import re
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Carteira Inteligente', page_icon='📊', layout='wide')

# -----------------------------------------------------------------------------
# Autenticação multiutilizador
# -----------------------------------------------------------------------------
# Para poucos utilizadores conhecidos, as credenciais ficam apenas nos Secrets
# do Streamlit. Cada utilizador recebe um owner_id independente no Supabase.

def _configured_users():
    try:
        raw=st.secrets.get('USERS',{}) or {}
    except Exception:
        raw={}
    out={}
    try:
        names=list(raw.keys())
    except Exception:
        names=[]
    for name in names:
        try:
            cfg=raw[name]
            password=str(cfg.get('password','') or '')
            owner_id=str(cfg.get('owner_id',name) or name).strip()
            display_name=str(cfg.get('display_name',name) or name).strip()
            if password and owner_id:
                out[str(name).strip().lower()]={'username':str(name).strip(),'password':password,'owner_id':owner_id,'display_name':display_name}
        except Exception:
            continue
    return out

def _clear_user_session(clear_auth=False):
    exact={
        'watchlist','portfolio_input','decision_history','investingpro_data','investingpro_import_meta',
        'alerts','portfolio_rows','persistence_status','persistence_last_save','persistence_error',
        '_persistent_loaded','v14_portfolio_rows','v14_hist_revalued','v14_port_detail_result',
        'comparison_df','comparison_time','v14_scan_rows','v20_scan_time','v14_analysis','v14_analysis_detail',
        'report_parsed','report_result','report_file_name','report_library','_report_last_upload_hash',
    }
    prefixes=('alert_','risk_','decision_stats_')
    for key in list(st.session_state.keys()):
        if key in exact or any(str(key).startswith(pref) for pref in prefixes):
            st.session_state.pop(key,None)
    if clear_auth:
        for key in ['_app_authenticated','_authenticated_user','_owner_id','_user_display']:
            st.session_state.pop(key,None)

_USERS=_configured_users()
try:
    _APP_PASSWORD=str(st.secrets.get('APP_PASSWORD','') or '')
except Exception:
    _APP_PASSWORD=''

if _USERS and not st.session_state.get('_app_authenticated',False):
    st.title('🔒 Carteira Inteligente')
    st.caption('Entra com o teu utilizador. Cada conta tem carteira, histórico e dados próprios.')
    _login_user=st.text_input('Utilizador').strip().lower()
    _login_pw=st.text_input('Palavra-passe',type='password')
    if st.button('Entrar',type='primary',use_container_width=True):
        cfg=_USERS.get(_login_user)
        if cfg and hmac.compare_digest(str(_login_pw),str(cfg['password'])):
            _clear_user_session(clear_auth=True)
            st.session_state['_app_authenticated']=True
            st.session_state['_authenticated_user']=cfg['username']
            st.session_state['_owner_id']=cfg['owner_id']
            st.session_state['_user_display']=cfg['display_name']
            st.rerun()
        else:
            st.error('Utilizador ou palavra-passe incorretos.')
    st.stop()
elif (not _USERS) and _APP_PASSWORD and not st.session_state.get('_app_authenticated',False):
    # Compatibilidade com a configuração antiga de uma única palavra-passe.
    st.title('🔒 Carteira Inteligente')
    _pw=st.text_input('Palavra-passe da aplicação',type='password')
    if st.button('Entrar',type='primary',use_container_width=True):
        if hmac.compare_digest(str(_pw),_APP_PASSWORD):
            _clear_user_session(clear_auth=True)
            st.session_state['_app_authenticated']=True
            st.session_state['_authenticated_user']='principal'
            try:
                st.session_state['_owner_id']=str(st.secrets.get('PORTFOLIO_OWNER_ID','carteira-principal') or 'carteira-principal')
            except Exception:
                st.session_state['_owner_id']='carteira-principal'
            st.session_state['_user_display']='Utilizador principal'
            st.rerun()
        else:
            st.error('Palavra-passe incorreta.')
    st.stop()

if st.session_state.get('_app_authenticated'):
    st.sidebar.caption(f"👤 {st.session_state.get('_user_display') or st.session_state.get('_authenticated_user') or 'Utilizador'}")
    if st.sidebar.button('Sair',use_container_width=True,key='logout_user'):
        _clear_user_session(clear_auth=True)
        st.rerun()

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
if 'investingpro_data' not in st.session_state:
    st.session_state.investingpro_data = {}
if 'investingpro_import_meta' not in st.session_state:
    st.session_state.investingpro_import_meta = {}
if 'alerts' not in st.session_state:
    st.session_state.alerts = []
if 'report_library' not in st.session_state:
    st.session_state.report_library = {}

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
    owner=str(st.session_state.get('_owner_id') or _secret('PORTFOLIO_OWNER_ID','') or '').strip()
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
        'watchlist':_json_safe(st.session_state.get('watchlist',[])),
        'alerts':_json_safe(st.session_state.get('alerts',[])),
        'investingpro_data':_json_safe(st.session_state.get('investingpro_data',{})),
        'investingpro_import_meta':_json_safe(st.session_state.get('investingpro_import_meta',{})),
        'report_library':_json_safe(st.session_state.get('report_library',{})),
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
            st.session_state.watchlist=list(state.get('watchlist') or [])
            st.session_state.alerts=list(state.get('alerts') or [])
            st.session_state.investingpro_data=dict(state.get('investingpro_data') or {})
            st.session_state.investingpro_import_meta=dict(state.get('investingpro_import_meta') or {})
            st.session_state.report_library=dict(state.get('report_library') or {})
            st.session_state['persistence_last_save']=rows[0].get('updated_at')
        else:
            # Um owner_id novo começa sempre vazio; nunca reutiliza dados de outro login.
            st.session_state.portfolio_input=[]
            st.session_state.decision_history=[]
            st.session_state.watchlist=[]
            st.session_state.alerts=[]
            st.session_state.investingpro_data={}
            st.session_state.investingpro_import_meta={}
            st.session_state.report_library={}
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


def _norm_label(value):
    txt=str(value or '').strip().lower()
    txt=unicodedata.normalize('NFKD',txt)
    txt=''.join(ch for ch in txt if not unicodedata.combining(ch))
    txt=txt.replace('&',' and ').replace('/',' ').replace('\\',' ')
    txt=re.sub(r'[^a-z0-9%]+',' ',txt)
    return re.sub(r'\s+',' ',txt).strip()


# Campos que a app sabe aproveitar diretamente dos exports do InvestingPro.
# Os aliases são deliberadamente conservadores para evitar preencher uma métrica
# com um número de significado diferente.
_IP_ALIASES = {
    'revenueGrowth':['revenue growth','sales growth','crescimento receitas','crescimento de receitas'],
    'earningsGrowth':['earnings growth','net income growth','crescimento lucros','crescimento de lucros'],
    'operatingMargins':['operating margin','operating margin %','margem operacional'],
    'profitMargins':['net margin','net profit margin','profit margin','margem liquida','margem de lucro'],
    'returnOnEquity':['return on equity','roe','roe %','rentabilidade dos capitais proprios'],
    'freeCashflow':['free cash flow','free cashflow','fcf','fluxo de caixa livre'],
    'operatingCashflow':['operating cash flow','cash from operations','operating cashflow','fluxo de caixa operacional'],
    'debtToEquity':['debt to equity','debt equity','debt equity ratio','divida capital proprio','divida patrimonio'],
    'marketCap':['market cap','market capitalization','capitalizacao bolsista','capitalizacao de mercado'],
    'trailingPE':['p e','pe ratio','p e ratio','price earnings','price to earnings','preco lucro'],
    'forwardPE':['forward p e','forward pe','forward p e ratio','p e forward','preco lucro forward'],
    'priceToBook':['price to book','p b','pb ratio','p b ratio','preco valor contabilistico'],
    'enterpriseToEbitda':['ev ebitda','enterprise value ebitda','ev to ebitda'],
    'targetMeanPrice':['analyst target','average target price','mean target price','price target','preco alvo medio','preco alvo'],
    'numberOfAnalystOpinions':['number of analysts','analysts','analyst count','numero de analistas','n analistas'],
    'recommendationKey':['analyst consensus','recommendation','recomendacao analistas','consenso analistas'],
    'sector':['sector','setor'],
    'industry':['industry','industria'],
    'currency':['currency','moeda'],
    'longName':['company','company name','name','empresa'],
    # Campos exclusivos/complementares do InvestingPro.
    'investingFcfYield':['fcf yield','free cash flow yield','rendimento fcf','yield fluxo caixa livre'],
    'investingFairValue':['fair value','investingpro fair value','valor justo','preco justo'],
    'investingFairValueUpside':['fair value upside','upside to fair value','potencial fair value','potencial valor justo'],
    'investingHealthScore':['financial health score','health score','financial health','saude financeira','pontuacao saude financeira'],
}

_IP_TICKER_ALIASES={
    'ticker','ticker symbol','symbol','simbolo','codigo','code','instrument','instrumento','security','acao','stock'
}

_IP_FRACTION_FIELDS={'revenueGrowth','earningsGrowth','operatingMargins','profitMargins','returnOnEquity'}
_IP_ABSOLUTE_FIELDS={'freeCashflow','operatingCashflow','marketCap','targetMeanPrice','investingFairValue'}
_IP_NUMERIC_FIELDS=set(_IP_ALIASES)-{'recommendationKey','sector','industry','currency','longName'}


def _metric_from_label(label):
    n=_norm_label(label)
    if not n:
        return None
    candidates=[]
    for key,aliases in _IP_ALIASES.items():
        for alias in aliases:
            a=_norm_label(alias)
            candidates.append((len(a),key,a))
    # Prioriza aliases mais específicos: "forward p e" antes de "p e".
    for _,key,a in sorted(candidates,reverse=True):
        if n==a or n.startswith(a+' ') or n.endswith(' '+a):
            return key
    return None


def _clean_ticker_value(value):
    t=str(value or '').strip().upper()
    if not t or t in {'NAN','NONE','N/D'}:
        return ''
    # Formatos comuns: NASDAQ:NVDA, NASDAQ - NVDA, NVDA (NASDAQ).
    if ':' in t:
        parts=[x.strip() for x in t.split(':') if x.strip()]
        if len(parts)>=2 and len(parts[-1])<=12:
            t=parts[-1]
    t=re.sub(r'\s*\([^)]*\)\s*$','',t).strip()
    return t


def _parse_ip_number(value, key=None, label=''):
    if value is None or (isinstance(value,float) and not np.isfinite(value)):
        return None
    if isinstance(value,(int,float,np.integer,np.floating)):
        x=float(value)
        raw=''
    else:
        raw=str(value).strip()
        if not raw or raw.lower() in {'n/a','na','nan','none','-','--','n/d'}:
            return None
        neg=raw.startswith('(') and raw.endswith(')')
        txt=raw.strip('()').replace('\xa0',' ').replace('€','').replace('$','').replace('£','')
        multiplier=1.0
        m=re.search(r'([kmbt])\s*$',txt.strip(),flags=re.I)
        if m:
            multiplier={'k':1e3,'m':1e6,'b':1e9,'t':1e12}[m.group(1).lower()]
            txt=txt[:m.start()].strip()
        txt=txt.replace('x','').replace('X','').replace('%','').strip()
        # Resolve decimal comma / thousands separators conservatively.
        if ',' in txt and '.' in txt:
            if txt.rfind(',') > txt.rfind('.'):
                txt=txt.replace('.','').replace(',','.')
            else:
                txt=txt.replace(',','')
        elif ',' in txt:
            if re.search(r',\d{1,3}$',txt):
                txt=txt.replace('.','').replace(',','.')
            else:
                txt=txt.replace(',','')
        txt=re.sub(r'[^0-9eE+\-.]','',txt)
        try:
            x=float(txt)*multiplier
        except Exception:
            return None
        if neg:
            x=-x
    if not np.isfinite(x):
        return None
    nlabel=_norm_label(label)
    if key in _IP_FRACTION_FIELDS:
        # A Yahoo usa frações (0.15 = 15%). InvestingPro normalmente mostra %.
        if '%' in str(value) or '%' in str(label) or abs(x)>2:
            x=x/100.0
    elif key=='debtToEquity':
        # A Yahoo representa 75% como 75. InvestingPro pode exportar 0.75x.
        if '%' not in str(value) and '%' not in str(label) and abs(x)<=10:
            x=x*100.0
    elif key=='investingFairValueUpside':
        # Guardamos este campo em percentagem, não em fração.
        if abs(x)<=2 and '%' not in str(value) and '%' not in str(label):
            x=x*100.0
    return float(x)


def _ticker_lookup_keys(xtb_ticker, source_ticker=None):
    vals=[]
    for raw in [xtb_ticker,source_ticker]:
        t=_clean_ticker_value(raw)
        if not t:
            continue
        vals.append(t)
        if '.' in t:
            vals.append(t.split('.')[0])
    return list(dict.fromkeys(vals))


def _lookup_investingpro_record(xtb_ticker, source_ticker=None):
    db=st.session_state.get('investingpro_data',{}) or {}
    for key in _ticker_lookup_keys(xtb_ticker,source_ticker):
        rec=db.get(key)
        if isinstance(rec,dict):
            return rec
    return None


def _value_available(v):
    if v is None:
        return False
    if isinstance(v,(int,float,np.integer,np.floating)):
        return bool(np.isfinite(float(v)))
    return bool(str(v).strip() and str(v).strip().upper() not in {'N/D','N/A','NONE','NAN'})


def _enrich_info_with_investingpro(base_info, xtb_ticker, source_ticker):
    info=dict(base_info or {})
    tracked=set(_IP_ALIASES)
    sources={k:'Yahoo' for k in tracked if _value_available(info.get(k))}
    rec=_lookup_investingpro_record(xtb_ticker,source_ticker)
    if rec:
        metrics=rec.get('metrics') or {}
        for key,val in metrics.items():
            if key not in tracked or not _value_available(val):
                continue
            if not _value_available(info.get(key)):
                info[key]=val
                sources[key]='InvestingPro'
        # Campos exclusivos do InvestingPro não existem normalmente na Yahoo.
        for key in ['investingFcfYield','investingFairValue','investingFairValueUpside','investingHealthScore']:
            if _value_available(metrics.get(key)):
                info[key]=metrics.get(key)
                sources[key]='InvestingPro'
    return info,sources,rec


def _read_investingpro_upload(uploaded):
    name=str(getattr(uploaded,'name','')).lower()
    uploaded.seek(0)
    if name.endswith('.xlsx'):
        book=pd.read_excel(uploaded,sheet_name=None,engine='openpyxl')
        return [(str(k),v) for k,v in book.items() if isinstance(v,pd.DataFrame) and not v.empty]
    # sep=None reconhece CSV com vírgula ou ponto e vírgula.
    try:
        df=pd.read_csv(uploaded,sep=None,engine='python')
    except Exception:
        uploaded.seek(0)
        df=pd.read_csv(uploaded)
    return [('CSV',df)] if isinstance(df,pd.DataFrame) and not df.empty else []


def _extract_ip_from_wide_df(df, ticker_hint=''):
    if df is None or df.empty:
        return {},0
    norm_cols={c:_norm_label(c) for c in df.columns}
    ticker_col=next((c for c,n in norm_cols.items() if n in _IP_TICKER_ALIASES),None)
    metric_cols={c:_metric_from_label(c) for c in df.columns}
    metric_cols={c:k for c,k in metric_cols.items() if k}
    if not metric_cols:
        return {},0
    out={}; recognized=0
    for _,row in df.iterrows():
        ticker=_clean_ticker_value(row.get(ticker_col)) if ticker_col else _clean_ticker_value(ticker_hint)
        if not ticker:
            continue
        metrics={}
        for col,key in metric_cols.items():
            raw=row.get(col)
            if key in _IP_NUMERIC_FIELDS:
                val=_parse_ip_number(raw,key,col)
            else:
                val=str(raw).strip() if _value_available(raw) else None
            if _value_available(val):
                metrics[key]=val
                recognized+=1
        if metrics:
            out[ticker]={
                'metrics':metrics,
                'source':'InvestingPro import',
                'imported_at':datetime.now(timezone.utc).isoformat(),
            }
    return out,recognized


def _extract_ip_from_long_df(df, ticker_hint=''):
    # Suporta exports simples "Métrica | Valor" de uma única empresa.
    ticker=_clean_ticker_value(ticker_hint)
    if not ticker or df is None or df.empty or len(df.columns)<2:
        return {},0
    best_metrics={}; best_count=0
    for metric_col in df.columns:
        mapped=[_metric_from_label(x) for x in df[metric_col].astype(str).tolist()]
        if sum(x is not None for x in mapped)<2:
            continue
        other_cols=[c for c in df.columns if c!=metric_col]
        for value_col in reversed(other_cols):
            metrics={}; count=0
            for (_,r),key in zip(df.iterrows(),mapped):
                if not key:
                    continue
                raw=r.get(value_col)
                val=_parse_ip_number(raw,key,str(r.get(metric_col))) if key in _IP_NUMERIC_FIELDS else (str(raw).strip() if _value_available(raw) else None)
                if _value_available(val):
                    metrics[key]=val; count+=1
            if count>best_count:
                best_metrics=metrics; best_count=count
    if not best_metrics:
        return {},0
    return {ticker:{'metrics':best_metrics,'source':'InvestingPro import','imported_at':datetime.now(timezone.utc).isoformat()}},best_count


def parse_investingpro_file(uploaded, ticker_hint=''):
    records={}; recognized=0; sheets=[]
    for sheet,df in _read_investingpro_upload(uploaded):
        sheets.append(sheet)
        wide,n1=_extract_ip_from_wide_df(df,ticker_hint)
        long,n2=({},0) if wide else _extract_ip_from_long_df(df,ticker_hint)
        for batch in [wide,long]:
            for ticker,rec in batch.items():
                old=records.get(ticker,{'metrics':{},'source':'InvestingPro import','imported_at':rec.get('imported_at')})
                old['metrics'].update(rec.get('metrics') or {})
                records[ticker]=old
        recognized += n1+n2
    return records,recognized,sheets


def merge_investingpro_records(records):
    db=dict(st.session_state.get('investingpro_data',{}) or {})
    for ticker,rec in (records or {}).items():
        t=_clean_ticker_value(ticker)
        if not t:
            continue
        current=db.get(t,{'metrics':{},'source':'InvestingPro import'})
        current['metrics']=dict(current.get('metrics') or {})
        current['metrics'].update(rec.get('metrics') or {})
        current['source']='InvestingPro import'
        current['imported_at']=rec.get('imported_at') or datetime.now(timezone.utc).isoformat()
        db[t]=current
    st.session_state.investingpro_data=db
    st.session_state.investingpro_import_meta={
        'updated_at':datetime.now(timezone.utc).isoformat(),
        'tickers':len(db),
    }
    return len(db)


def _source_for(a,key,default='N/D'):
    return str((a.get('data_sources') or {}).get(key) or default)


def _sources_summary(a, keys):
    vals=[]
    for key in keys:
        src=(a.get('data_sources') or {}).get(key)
        if src and src not in vals:
            vals.append(src)
    return ' + '.join(vals) if vals else 'N/D'

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

INSTRUMENT_TYPES = ['Auto','Ação','ETF','ETN','CFD']

def _normalize_instrument_type(value):
    raw=str(value or '').strip().lower()
    mapping={
        '':'Auto','auto':'Auto',
        'acao':'Ação','ação':'Ação','equity':'Ação','stock':'Ação',
        'etf':'ETF','etn':'ETN','cfd':'CFD',
    }
    return mapping.get(raw, 'Auto')

def _auto_instrument_kind(info):
    qt=str(info.get('quoteType','')).upper().strip()
    name_blob=' '.join(str(info.get(k) or '') for k in ['longName','shortName','category']).upper()
    if ('EXCHANGE TRADED NOTE' in name_blob or 'EXCHANGE-TRADED NOTE' in name_blob
            or ' ETN ' in f' {name_blob} ' or name_blob.endswith(' ETN')):
        return 'ETN'
    if qt == 'ETF':
        return 'ETF'
    return 'Ação'

def _cfd_underlying_kind(info):
    qt=str(info.get('quoteType','')).upper().strip()
    auto=_auto_instrument_kind(info)
    if auto in ['ETF','ETN']:
        return auto
    if qt in ['EQUITY','STOCK'] or not qt:
        return 'Ação'
    return 'Outro'

def asset_kind(info, override=None):
    forced=_normalize_instrument_type(override)
    return forced if forced!='Auto' else _auto_instrument_kind(info)

def fundamental_etn(info):
    # ETN e uma nota de divida negociada em bolsa: nao usa fundamentais de empresa.
    expense=_num(info,'annualReportExpenseRatio')
    if expense is None:
        expense=_num(info,'expenseRatio')
    assets=_num(info,'totalAssets')
    avgvol=_num(info,'averageVolume')
    nav=_num(info,'navPrice')
    ytd=_num(info,'ytdReturn')
    specs=[
        ('Custo anual <= 1,50%', expense, (lambda x: x <= 0.015)),
        ('Ativos/valor indicativo >= 50 M', assets, (lambda x: x >= 50_000_000)),
        ('Volume medio >= 10 mil', avgvol, (lambda x: x >= 10_000)),
        ('NAV/valor indicativo disponivel', nav, (lambda x: x > 0)),
        ('Retorno YTD disponivel', ytd, (lambda x: np.isfinite(x))),
    ]
    rows=[]; passed=0; available=0
    for name,v,fn in specs:
        ok=None if v is None else bool(fn(v))
        if v is not None:
            available += 1; passed += int(ok)
        rows.append({'Critério':name,'Valor':v,'Cumpre':('Sim' if ok else 'Não') if ok is not None else 'N/D'})
    completeness=available/len(specs)*100.0
    ratio=passed/available if available else None
    if available < 2:
        label='Dados insuficientes'
    elif ratio >= 0.70:
        label='Forte'
    elif ratio >= 0.45:
        label='Neutro'
    else:
        label='Fraco'
    return label, (round(ratio*100,1) if ratio is not None else None), round(completeness,1), pd.DataFrame(rows)

def _fundamental_for_kind(info, kind):
    if kind=='ETF':
        return fundamental_etf(info)
    if kind=='ETN':
        return fundamental_etn(info)
    if kind=='Ação':
        return fundamental_equity(info)
    table=pd.DataFrame([{'Critério':'Qualidade do subjacente','Valor':None,'Leitura':'N/D para este tipo de subjacente'}])
    return 'Dados insuficientes', None, 0.0, table

def fundamental_analysis(ticker, xtb_ticker=None, instrument_type=None):
    base_info = asset_info(ticker)
    info, data_sources, ip_record = _enrich_info_with_investingpro(base_info, xtb_ticker or ticker, ticker)
    kind = asset_kind(info, instrument_type)
    if kind=='CFD':
        underlying_kind=_cfd_underlying_kind(info)
        label, score, completeness, table = _fundamental_for_kind(info, underlying_kind)
    else:
        underlying_kind=kind
        label, score, completeness, table = _fundamental_for_kind(info, kind)
    return info, kind, label, score, completeness, table, data_sources, ip_record, underlying_kind

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

def analyze_asset(ticker, market_hint=None, detailed=True, instrument_type=None, source_override=None):
    ident=resolve_instrument(ticker, market_hint)
    source=str(source_override or '').upper().strip() or ident['source_ticker']
    raw=price_data(source,'5y' if detailed else '2y','1d')
    d=indicators(raw).dropna()
    if len(d) < 210:
        raise ValueError('Histórico insuficiente para análise técnica robusta.')
    row=d.iloc[-1]
    tech_score, tech_label, tech_tests=technical_score(row)
    info,kind,fund_label,fund_score,complete,fund_table,data_sources,ip_record,underlying_kind=fundamental_analysis(
        source,ident['xtb_ticker'],instrument_type
    )
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
        'info':info,'kind':kind,'underlying_kind':underlying_kind,'fund_label':fund_label,'fund_score':fund_score,'fund_complete':complete,
        'fund_table':fund_table,'entry':entry,'stop':stop,'target':target,'scenarios':scenarios,
        'target_time':target_time,'data_sources':data_sources,'investingpro_record':ip_record
    }

def decision(a):
    if a.get('kind')=='CFD':
        return 'CFD - PLANO TATICO / REVER RISCO'
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

# Normaliza variações que podem aparecer nas fontes. O objetivo é comparar o
# setor económico, não diferenças de capitalização, idioma ou subindústria.
_SECTOR_CANONICAL = {
    'technology':'Technology',
    'information technology':'Technology',
    'information_technology':'Technology',
    'tech':'Technology',
    # Algumas respostas podem devolver a subindústria no campo de setor.
    'semiconductors':'Technology',
    'semiconductor equipment & materials':'Technology',
    'semiconductor equipment and materials':'Technology',
    'financial services':'Financial Services',
    'financial':'Financial Services',
    'financials':'Financial Services',
    'industrials':'Industrials',
    'communication services':'Communication Services',
    'communications services':'Communication Services',
    'healthcare':'Healthcare',
    'health care':'Healthcare',
    'consumer cyclical':'Consumer Cyclical',
    'consumer discretionary':'Consumer Cyclical',
    'consumer defensive':'Consumer Defensive',
    'consumer staples':'Consumer Defensive',
    'energy':'Energy',
    'basic materials':'Basic Materials',
    'materials':'Basic Materials',
    'real estate':'Real Estate',
    'utilities':'Utilities',
}

_TECH_INDUSTRY_HINTS = (
    'semiconductor', 'software', 'computer hardware', 'consumer electronics',
    'electronic components', 'communication equipment', 'scientific & technical instruments',
)

def _canonical_sector(info):
    for key in ('sector','sectorDisp','sectorKey'):
        raw=str(info.get(key) or '').strip()
        if not raw:
            continue
        norm=raw.lower().replace('-', ' ').strip()
        if norm in _SECTOR_CANONICAL:
            return _SECTOR_CANONICAL[norm]
        # Chaves de API podem vir com underscores.
        norm2=norm.replace('_',' ')
        if norm2 in _SECTOR_CANONICAL:
            return _SECTOR_CANONICAL[norm2]
        return raw

    # Fallback conservador: só infere Tecnologia quando a indústria é inequívoca.
    industry=' '.join(str(info.get(k) or '') for k in ('industry','industryDisp','industryKey')).lower()
    if any(h in industry for h in _TECH_INDUSTRY_HINTS):
        return 'Technology'
    return ''

def sector_name(info):
    raw=_canonical_sector(info)
    if raw:
        return SECTOR_PT.get(raw, raw)
    if asset_kind(info) == 'ETF':
        cat=str(info.get('category') or '').strip()
        return f'ETF — {cat}' if cat else 'ETF — categoria N/D'
    return 'N/D'

def industry_name(info):
    raw=str(info.get('industry') or info.get('industryDisp') or info.get('industryKey') or '').strip()
    return raw if raw else 'N/D'

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
    used=[]
    for src in (a.get('data_sources') or {}).values():
        if src and src not in used:
            used.append(src)
    if used:
        st.caption('Fontes fundamentais efetivamente usadas: '+ ' + '.join(used) + '. Yahoo é principal; InvestingPro apenas preenche campos ausentes.')
    if a.get('kind')=='CFD':
        st.warning('CFD: os dados de mercado/fundamentais referem-se ao subjacente. Custos de financiamento, margem, alavancagem, spread e multiplicador do contrato devem ser confirmados na XTB.')
    elif a.get('kind')=='ETN':
        st.info('ETN: a app avalia sobretudo liquidez/custos e técnica. Confirma também risco de crédito do emissor e condições do produto.')
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

def add_or_merge_portfolio_position(ticker, qty, entry_price, objective='Longo prazo', personal_target=0.0, origin='Oportunidade aceite', entry_date=None, thesis='', instrument_type='Auto', source_ticker='', contract_multiplier=0.0):
    t=str(ticker).upper().strip()
    q=float(qty)
    ep=float(entry_price)
    inst=_normalize_instrument_type(instrument_type)
    src=str(source_ticker or '').upper().strip()
    mult=_safe_float(contract_multiplier) or 0.0
    if not t or q<=0 or ep<=0:
        return
    rows=list(st.session_state.portfolio_input)
    found=False
    for r in rows:
        existing_type=_normalize_instrument_type(r.get('Tipo instrumento') or r.get('Tipo') or 'Auto')
        if (str(r.get('Ticker XTB','')).upper().strip()==t
                and str(r.get('Objetivo','Longo prazo'))==str(objective)
                and existing_type==inst):
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
            r['Tipo instrumento']=inst
            if src:
                r['Ticker técnico']=src
            if mult>0:
                r['Multiplicador contrato']=mult
            found=True
            break
    if not found:
        rows.append({
            'Ticker XTB':t,'Quantidade':q,'Preço médio':ep,
            'Preço alvo pessoal':float(personal_target or 0),
            'Data entrada':str(entry_date) if entry_date else datetime.now().date().isoformat(),
            'Objetivo':objective,'Origem':origin,'Tese/nota':str(thesis or ''),
            'Tipo instrumento':inst,'Ticker técnico':src,'Multiplicador contrato':mult,
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
            a=analyze_asset(
                h['Ticker XTB'],detailed=False,
                instrument_type=h.get('Tipo') or 'Auto',
                source_override=(str(h.get('Ticker técnico') or '').upper().strip() or None),
            )
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
    if a.get('kind')=='CFD':
        if holding:
            return 'REVER - CFD / CUSTOS E ALAVANCAGEM', s
        return 'CFD - NAO PRIORIZAR PARA LONGO PRAZO', s
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
    kind=a.get('kind')
    if kind=='CFD':
        underlying=a.get('underlying_kind') or 'subjacente'
        out=[f'CFD sobre {underlying}: a análise usa o preço/dados do subjacente, não do contrato XTB']
        if a.get('fund_score') is not None:
            out.append(f'Qualidade do subjacente: {a["fund_label"]} · {fundscore} · dados {float(a["fund_complete"]):.0f}%')
        else:
            out.append('Qualidade do subjacente: dados insuficientes')
        out.append('CFD: confirmar alavancagem, margem, spread e financiamento overnight na XTB')
        return out[:3]
    if kind=='ETN':
        expense=_num(info,'annualReportExpenseRatio')
        if expense is None: expense=_num(info,'expenseRatio')
        avgvol=_num(info,'averageVolume')
        out=[f'ETN: qualidade do produto {a["fund_label"]} · {fundscore} · dados {float(a["fund_complete"]):.0f}%']
        out.append(f'Custo anual: {expense*100:.2f}%' if expense is not None else 'Custo anual: N/D')
        out.append(f'Volume médio: {avgvol:,.0f}' if avgvol is not None else 'Risco do emissor/liquidez: confirmar antes de reforçar')
        return out[:3]
    sector=sector_name(info)
    out=[f'Qualidade ajustada ao setor ({sector}): {a["fund_label"]} · {fundscore} · dados {float(a["fund_complete"]):.0f}%']
    if kind=='ETF':
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
    inst=_normalize_instrument_type(r.get('Tipo instrumento') or r.get('Tipo') or 'Auto')
    src_raw=r.get('Ticker técnico')
    src='' if src_raw is None or str(src_raw).strip().lower() in ['','nan','none'] else str(src_raw).upper().strip()
    a=analyze_asset(t,detailed=False,instrument_type=inst,source_override=(src or None))
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
        primary='ALVO PESSOAL ATINGIDO - REVER'
    movement_pct=(price/pm-1)*100
    multiplier=_safe_float(r.get('Multiplicador contrato')) or 0.0
    if a.get('kind')=='CFD':
        pnl_pct=None
        pnl_eur=((pe-pm_eur)*q*multiplier if multiplier>0 and pe is not None and pm_eur is not None else None)
        current_value_eur=None
        cfd_notional_eur=(pe*q*multiplier if multiplier>0 and pe is not None else None)
    else:
        pnl_pct=movement_pct
        pnl_eur=((pe-pm_eur)*q if pe is not None and pm_eur is not None else None)
        current_value_eur=(pe*q if pe is not None else None)
        cfd_notional_eur=None
    return {
        'Ticker XTB':a['xtb_ticker'],'Empresa':a['company'],'Setor':sector_name(a['info']),'Objetivo':objective,
        'Tipo instrumento':a.get('kind'),'Subjacente':a.get('underlying_kind'),'Ticker técnico':a.get('source_ticker'),
        'Preço atual':price,'Moeda':cur,'Quantidade':q,'Preço médio':pm,
        'Valor atual EUR':current_value_eur,'Notional CFD EUR aprox.':cfd_notional_eur,
        'P/L %':pnl_pct,'Movimento subjacente %':movement_pct,'P/L EUR aprox.':pnl_eur,
        'Multiplicador contrato':multiplier if multiplier>0 else None,
        'Decisão principal':primary,'Curto prazo':short_action,'Score curto':short_score,
        'Longo prazo':long_action,'Score longo':long_score,'Resumo':' · '.join(ev),
        'Preço alvo pessoal':pa if pa>0 else None,'Origem':str(r.get('Origem') or ''),'Data':str(a['df'].index[-1].date()),
        '_analysis':a,
    }


def valuation_scenarios(a):
    """Estimativa transparente por cenários; não é previsão nem DCF completo."""
    kind=a.get('kind')
    underlying=a.get('underlying_kind')
    if kind not in ['Ação','CFD'] or (kind=='CFD' and underlying!='Ação'):
        return {'available':False,'reason':'Valor intrínseco aplicado apenas a ações/subjacentes de ações.'}
    info=a.get('info') or {}
    price=float(a['row']['Close'])
    fair=_num(info,'investingFairValue')
    anchors=[]
    source_parts=[]
    if fair is not None and fair>0:
        base=float(fair)
        source_parts.append('Fair Value InvestingPro')
        confidence='Alta' if float(a.get('fund_complete') or 0)>=60 else 'Média'
    else:
        sector=_canonical_sector(info) or 'Other'
        pe_base={
            'Technology':25.0,'Financial Services':13.0,'Industrials':18.0,'Communication Services':20.0,
            'Healthcare':22.0,'Consumer Cyclical':18.0,'Consumer Defensive':20.0,'Energy':12.0,
            'Basic Materials':14.0,'Real Estate':18.0,'Utilities':16.0,
        }.get(sector,18.0)
        growth_vals=[]
        for key in ['revenueGrowth','earningsGrowth']:
            v=_num(info,key)
            if v is not None:
                growth_vals.append(v*100.0)
        growth=float(np.median(growth_vals)) if growth_vals else 0.0
        growth_adj=max(-0.15,min(0.30,growth/100.0*0.8))
        target_pe=pe_base*(1.0+growth_adj)
        for key,label in [('trailingPE','P/E'),('forwardPE','Forward P/E')]:
            pe=_num(info,key)
            if pe is not None and pe>0:
                implied=price*target_pe/pe
                if np.isfinite(implied) and implied>0:
                    anchors.append(float(implied)); source_parts.append(label+' normalizado ao setor')
        fcf=_num(info,'freeCashflow'); cap=_num(info,'marketCap')
        if fcf is not None and cap and cap>0 and fcf>0:
            fcf_yield=fcf/cap
            target_yield={
                'Technology':0.035,'Industrials':0.045,'Communication Services':0.04,'Healthcare':0.04,
                'Consumer Cyclical':0.045,'Consumer Defensive':0.045,'Energy':0.07,'Basic Materials':0.06,
                'Real Estate':0.055,'Utilities':0.055,'Financial Services':0.07,
            }.get(sector,0.05)
            implied=price*(fcf_yield/target_yield)
            if np.isfinite(implied) and implied>0:
                anchors.append(float(implied)); source_parts.append('FCF yield normalizado ao setor')
        if not anchors:
            return {'available':False,'reason':'Sem âncoras de avaliação suficientes para estimar cenários.'}
        base=float(np.median(anchors))
        base=max(price*0.45,min(price*2.0,base))
        confidence='Média' if len(anchors)>=2 and float(a.get('fund_complete') or 0)>=55 else 'Baixa'
    conservative=base*0.85
    optimistic=base*1.15
    upside=(base/price-1.0)*100.0 if price>0 else None
    return {
        'available':True,'conservative':conservative,'base':base,'optimistic':optimistic,
        'upside_pct':upside,'confidence':confidence,'sources':' + '.join(dict.fromkeys(source_parts)),
        'method':'Cenários heurísticos de avaliação; não é um DCF completo nem preço-alvo garantido.',
    }


def entry_zone(a, valuation=None):
    row=a['row']; price=float(row['Close']); atrv=float(row['ATR14'])
    ema20=float(row['EMA20']); ema50=float(row['EMA50']); ema200=float(row['EMA200'])
    supports=[x for x in [ema20,ema50,ema200] if np.isfinite(x) and x<price]
    anchor=max(supports) if supports else max(0.01,price-atrv)
    low=max(0.01,anchor-0.75*atrv)
    high=max(low,min(price,anchor+0.25*atrv))
    deep=max(0.01,(ema200 if ema200<price else price-2.5*atrv))
    status='AGUARDAR APROXIMAÇÃO À ZONA'
    if low <= price <= high:
        status='NA ZONA TÉCNICA — CONFIRMAR ENTRADA'
    elif price < low:
        status='ABAIXO DA ZONA — REVER TENDÊNCIA ANTES DE ENTRAR'
    if price < ema200:
        status='TENDÊNCIA LONGA FRACA — AGUARDAR ESTABILIZAÇÃO'
    if valuation and valuation.get('available'):
        base=_safe_float(valuation.get('base'))
        if base and price > base*1.10:
            status='AGUARDAR — PREÇO ACIMA DO CENÁRIO BASE'
        elif base and price <= base*0.90 and float(a.get('tech_score') or 0)>=55 and price>=ema200:
            status='AVALIAÇÃO ATRATIVA — CONFIRMAR TÉCNICA'
    return {'low':low,'high':high,'deep':deep,'status':status,'anchor':anchor}


# -----------------------------------------------------------------------------
# Analisador de relatórios PDF (InvestingPro Research)
# -----------------------------------------------------------------------------

def _pdf_clean_text(text):
    text=str(text or '').replace('\u00a0',' ').replace('\u2011','-').replace('\u2013','-').replace('\u2014','-')
    text=re.sub(r'[ \t]+',' ',text)
    text=re.sub(r'\n{3,}','\n\n',text)
    return text.strip()


def _extract_pdf_pages(uploaded_file):
    """Extrai texto de PDF digital. Não faz OCR nem inventa conteúdo ausente."""
    try:
        from pypdf import PdfReader
    except Exception as e:
        raise RuntimeError('Falta a dependência pypdf. Atualiza o requirements.txt da v28.') from e
    raw=uploaded_file.getvalue() if hasattr(uploaded_file,'getvalue') else bytes(uploaded_file)
    reader=PdfReader(io.BytesIO(raw))
    pages=[]
    for page in reader.pages:
        try:
            pages.append(_pdf_clean_text(page.extract_text() or ''))
        except Exception:
            pages.append('')
    full='\n\n'.join(pages)
    if len(re.sub(r'\s+','',full)) < 300:
        raise ValueError('O PDF tem pouco texto pesquisável. Esta versão lê PDFs digitais; um PDF digitalizado precisa de OCR.')
    return pages,full


def _rx_value(text, pattern, flags=re.I):
    m=re.search(pattern,text,flags)
    if not m:
        return None
    try:
        return float(str(m.group(1)).replace(',',''))
    except Exception:
        return None


def _rx_text(text, pattern, flags=re.I):
    m=re.search(pattern,text,flags)
    return str(m.group(1)).strip() if m else None


def _money_abs(value):
    if value is None:
        return None
    raw=str(value).strip().upper().replace('$','').replace(',','')
    m=re.match(r'^(-?[0-9]*\.?[0-9]+)\s*([KMBT]?)$',raw)
    if not m:
        return None
    n=float(m.group(1)); unit=m.group(2)
    mult={'':1.0,'K':1e3,'M':1e6,'B':1e9,'T':1e12}.get(unit,1.0)
    return n*mult


def _report_pt_text(text, kind='neutral'):
    """Converte frases típicas de relatórios financeiros em inglês para PT-PT.

    É deliberadamente local/determinístico: preserva números, tickers e siglas e
    não envia conteúdo do relatório para serviços externos. Quando a frase não
    encaixa num padrão conhecido, aplica um glossário financeiro conservador.
    """
    s=re.sub(r'\s+',' ',str(text or '')).strip()
    if not s:
        return s

    # Padrões completos mais frequentes nos relatórios ProResearch.
    patterns=[
        (r'^Intensifying competition from (.+?), combined with (.+?), could pressure (.+?)\.$',
         r'A intensificação da concorrência de \1, em conjunto com \2, poderá pressionar \3.'),
        (r'^(.+?), which derived (.+?) of its (.+?) revenue from (.+?), faces rising default risk \((.+?)\), representing (.+?)\.$',
         r'\1, que obteve \2 das suas receitas de \3 através de \4, enfrenta um risco crescente de incumprimento (\5), representando \6.'),
        (r'^Forward P/E compresses from ([0-9.,]+x) in (FY\d+) to ([0-9.,]+x) in (FY\d+), reflecting expected EPS growth of (.+?) annually through (FY\d+)\.$',
         r'O Forward P/E deverá descer de \1 em \2 para \3 em \4, refletindo um crescimento esperado do EPS de \5 por ano até \6.'),
        (r'^Capital expenditures reached (.+?), with (FY\d+) capex expected to exceed (.+?), compressing free cash flow and gross margins\.$',
         r'As despesas de capital (CapEx) atingiram \1, sendo esperado que o CapEx em \2 ultrapasse \3, o que poderá pressionar o Free Cash Flow e as margens brutas.'),
        (r'^(.+?) revenue declined ([0-9.,]+%) to (.+?), with (.+?) revenue down ([0-9.,]+%) and (.+?) down ([0-9.,]+%); (.+?) guidance implies (.+?) will decline (.+?)\.$',
         r'As receitas de \1 diminuíram \2 para \3, com as receitas de \4 a cair \5 e \6 a cair \7; o guidance de \8 indica que \9 deverá diminuir \10.'),
    ]
    for pat,repl in patterns:
        if re.search(pat,s,flags=re.I):
            s=re.sub(pat,repl,s,flags=re.I)
            break

    # Tradução conservadora de expressões financeiras comuns. Mantém nomes próprios.
    replacements=[
        (r'cloud infrastructure leader','líder em infraestrutura cloud'),
        (r'strong AI/model capabilities','fortes capacidades de IA/modelos'),
        (r'deep investments in','fortes investimentos em'),
        (r'CDS implying','CDS a indicar'),
        (r'5-year default probability','probabilidade de incumprimento a 5 anos'),
        (r'a potential concentration and counterparty risk','um potencial risco de concentração e de contraparte'),
        (r"in Microsoft's AI infrastructure ecosystem",'no ecossistema de infraestrutura de IA da Microsoft'),
        (r"Azure's market share",'a quota de mercado da Azure'),
        (r"Azure's pricing power",'o poder de fixação de preços da Azure'),
        (r'Q4 alone','apenas no Q4'),
        (r'in the high teens','na faixa alta dos dois dígitos'),
        (r'\bbillion\b','mil milhões'),
        (r'\bmillion\b','milhões'),
        (r'\btrillion\b','biliões'),
        (r'\brevenue\b','receitas'),
        (r'\band\b','e'),
        (r'\bBullish Highlights\b','Destaques positivos'),
        (r'\bBearish Highlights\b','Destaques negativos'),
        (r'\bBull Case\b','Cenário positivo'),
        (r'\bBear Case\b','Cenário negativo'),
        (r'\bstrong demand\b','procura forte'),
        (r'\bstrong growth\b','crescimento forte'),
        (r'\brevenue growth\b','crescimento das receitas'),
        (r'\bearnings growth\b','crescimento dos lucros'),
        (r'\bnet income growth\b','crescimento do lucro líquido'),
        (r'\bgross margin\b','margem bruta'),
        (r'\boperating margin\b','margem operacional'),
        (r'\bfree cash flow\b','Free Cash Flow'),
        (r'\bcash flow\b','cash flow'),
        (r'\bcapital expenditures\b','despesas de capital (CapEx)'),
        (r'\bcapex\b','CapEx'),
        (r'\bcustomer concentration\b','concentração de clientes'),
        (r'\bcounterparty risk\b','risco de contraparte'),
        (r'\bdefault risk\b','risco de incumprimento'),
        (r'\bsupply chain tightness\b','restrições na cadeia de abastecimento'),
        (r'\bsupply chain\b','cadeia de abastecimento'),
        (r'\bpricing power\b','poder de fixação de preços'),
        (r'\bmarket share\b','quota de mercado'),
        (r'\bcompetitive moat\b','vantagem competitiva'),
        (r'\bcompetition\b','concorrência'),
        (r'\bovervalued\b','sobreavaliada'),
        (r'\bundervalued\b','subavaliada'),
        (r'\bdebt\b','dívida'),
        (r'\bcash and marketable securities\b','caixa e títulos negociáveis'),
        (r'\bno funded debt\b','sem dívida financiada'),
        (r'\bprice target\b','preço-alvo'),
        (r'\banalyst target\b','alvo dos analistas'),
        (r'\banalysts\b','analistas'),
        (r'\bguidance\b','guidance'),
        (r'\braised\b','aumentou'),
        (r'\bdeclined\b','diminuiu'),
        (r'\bdecline\b','queda'),
        (r'\bdown\b','em queda'),
        (r'\bup\b','em alta'),
        (r'\bexpected to\b','espera-se que'),
        (r'\bcould pressure\b','poderá pressionar'),
        (r'\bpressure\b','pressão'),
        (r'\bcompressing\b','pressionando'),
        (r'\breflecting\b','refletindo'),
        (r'\brepresenting\b','representando'),
        (r'\bdriven by\b','impulsionado por'),
        (r'\bdue to\b','devido a'),
        (r'\bthrough\b','até'),
        (r'\bannually\b','por ano'),
    ]
    out=s
    for pat,repl in replacements:
        out=re.sub(pat,repl,out,flags=re.I)

    # Se ainda parecer maioritariamente inglês, mostra um resumo PT seguro em vez
    # de fingir uma tradução perfeita; o original continua acessível na interface.
    # Pequenos acertos gramaticais depois das substituições.
    out=re.sub(r"em conjunto com ([A-Z][A-Za-z0-9.&-]+) e ([A-Z][A-Za-z0-9.&-]+)'s fortes investimentos em",lambda m:f"em conjunto com os fortes investimentos da {m.group(1)} e da {m.group(2)} em",out)
    out=out.replace('a quota de mercado da Azure e poder de fixação de preços','a quota de mercado e o poder de fixação de preços da Azure')
    out=re.sub(r'\bin apenas no\b','apenas no',out,flags=re.I)
    out=re.sub(r'CDS a indicar (.+?) probabilidade de incumprimento',r'CDS a indicar uma probabilidade de incumprimento de \1',out,flags=re.I)
    out=re.sub(r'receitas de (\d{4}) através de ([A-Z][A-Za-z0-9.& -]+)',r'receitas de \1 provenientes de \2',out)
    out=out.replace('provenientes de Microsoft','provenientes da Microsoft')
    out=re.sub(r'\bFree cash flow\b','Free Cash Flow',out,flags=re.I)
    out=re.sub(r'(?<=\d)\.(?=\d)',',',out)
    low=out.lower()
    english_hits=sum(low.count(w) for w in [' the ',' and ',' with ',' from ',' which ',' of ',' to ',' in ',' is ',' are ',' has ',' have ',' could ',' expected '])
    if english_hits>=4:
        src=s.lower()
        nums=', '.join(re.findall(r'(?<![A-Za-z])(?:\$|€)?\s*~?[0-9]+(?:[.,][0-9]+)?(?:%|x|\s*(?:million|billion|trillion|M|B|T))?',s,flags=re.I)[:5])
        detail=f' Valores mencionados: {nums}.' if nums else ''
        if any(k in src for k in ['competition','market share','pricing power']):
            return 'O relatório destaca concorrência crescente, com possível pressão sobre quota de mercado, preços e/ou margens.'+detail
        if any(k in src for k in ['default risk','counterparty','concentration']):
            return 'O relatório identifica risco de concentração e/ou de contraparte, que pode aumentar a exposição a clientes ou parceiros específicos.'+detail
        if any(k in src for k in ['capex','capital expenditures','free cash flow']):
            return 'O relatório aponta investimento de capital elevado, que poderá pressionar o Free Cash Flow e as margens no curto/médio prazo.'+detail
        if any(k in src for k in ['declined','down','slowdown','headwind']):
            return 'O relatório assinala deterioração em algumas métricas operacionais, que merece acompanhamento.'+detail
        if kind=='positive':
            return 'O relatório identifica um fator positivo relevante para crescimento, procura, rentabilidade ou execução.'+detail
        if kind=='risk':
            return 'O relatório identifica um risco relevante que pode afetar crescimento, margens, procura ou execução.'+detail
    return out


def _pdf_technical_pt(value):
    return {
        'Strong Sell':'Venda forte','Sell':'Venda','Neutral':'Neutro',
        'Buy':'Compra','Strong Buy':'Compra forte'
    }.get(str(value or '').strip(), value or 'N/D')


def _report_sentence_candidates(text, positive=True, limit=4):
    clean=str(text or '')
    clean=re.sub(r'page\s+\d+/\d+',' ',clean,flags=re.I)
    clean=re.sub(r'\b(?:Bull Case|Bear Case|Additional Insights|SWOT Analysis|Latest Insights|Strengths|Weaknesses|Opportunities|Threats)\b',' ',clean,flags=re.I)
    clean=re.sub(r'\s+',' ',clean)
    sentences=re.split(r'(?<=[.!?])\s+',clean)
    pos=['raised','growth','grew','cash','no funded debt','strong','record','beat','upward','moat','customers','guidance','opportunity','expansion','profitable','return on equity']
    neg=['risk','declined','pressure','concentration','overvalued','tightness','volatile','threat','delay','slowdown','compress','competition','inventory','headwind']
    words=pos if positive else neg
    scored=[]
    for sent in sentences:
        sent=re.sub(r'^.*?Pro Research\s+','',sent,flags=re.I).strip()
        low=sent.lower()
        score=sum(1 for w in words if w in low)
        if score and 40 <= len(sent) <= 420:
            scored.append((score,len(sent),sent.strip()))
    scored=sorted(scored,key=lambda x:(-x[0],x[1]))
    out=[]
    for _,_,sent in scored:
        if sent not in out:
            out.append(sent)
        if len(out)>=limit:
            break
    return out


def parse_investingpro_report(pages, full_text):
    text=_pdf_clean_text(full_text)
    flat=re.sub(r'\s+',' ',text)
    first=re.sub(r'\s+',' ',pages[0] if pages else '')
    peer=re.sub(r'\s+',' ',pages[5] if len(pages)>5 else '')
    header=re.search(r'(.+?)\s*\((NYSE|NASDAQ|AMEX|LSE|XETRA|EPA|BIT|BME|SWX|EURONEXT)\s*:\s*([A-Z0-9.\-]+)\)',first,re.I)
    if not header:
        header=re.search(r'(.+?)\s*\([^:()]+\s*:\s*([A-Z0-9.\-]+)\)',first,re.I)
        company=header.group(1).strip() if header else None
        ticker=header.group(2).upper().strip() if header else None
        exchange=None
    else:
        company=header.group(1).strip(); exchange=header.group(2).upper(); ticker=header.group(3).upper().strip()
    if company:
        company=re.sub(r'\s+',' ',company).strip()
    report_date=_rx_text(first,r'Date:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})')
    report_price=_rx_value(first,r'Stock Price\s*\$?([0-9.,]+)')
    market_cap_raw=_rx_text(first,r'Market Cap\s*\$?([0-9.,]+\s*[KMBT])')
    revenue_raw=_rx_text(first,r'Revenue\s*\$?([0-9.,]+\s*[KMBT])')
    revenue_forecast_raw=_rx_text(first,r'Revenue Forecast\s*\$?([0-9.,]+\s*[KMBT])')
    analyst_avg=_rx_value(first,r'Analyst Avg\.\s*\(([0-9.,]+)\)')
    analyst_low=_rx_value(first,r'Analyst Low\s*\(([0-9.,]+)\)')
    analyst_high=_rx_value(first,r'Analyst High\s*\(([0-9.,]+)\)')
    # Lê cada rating pelo respetivo rótulo. Não assume que a ordem visual do PDF
    # coincide com a ordem devolvida pelo extrator de texto.
    financial_health=_rx_value(first,r'Financial Health.*?([0-9]+(?:\.[0-9]+)?)/10',re.I|re.S)
    growth_rating=_rx_value(first,r'Growth Rating.*?([0-9]+(?:\.[0-9]+)?)/10',re.I|re.S)
    profitability_rating=_rx_value(first,r'Profitability Rating.*?([0-9]+(?:\.[0-9]+)?)/10',re.I|re.S)
    cashflow_rating=_rx_value(first,r'Cash Flow Rating.*?([0-9]+(?:\.[0-9]+)?)/10',re.I|re.S)


    analyst_count=None
    if len(pages)>2:
        p3=re.sub(r'\s+',' ',pages[2])
        year=(report_date[-4:] if report_date and len(report_date)>=4 else r'20\d{2}')
        m=re.search(rf'{year}\s+[0-9.]+\s+[0-9.]+%\s+[0-9.]+x\s+(\d+)',p3,re.I)
        if m: analyst_count=int(m.group(1))

    eps_up=eps_down=None
    m=re.search(r'EPS\s*Revisions\s*\(90d\).*?(\d+)\s*[^0-9]+\s*(\d+)',first,re.I)
    if m:
        eps_up=int(m.group(1)); eps_down=int(m.group(2))

    report={
        'format':'InvestingPro Research' if 'Pro Research' in text and 'Investing' in text else 'PDF financeiro',
        'company':company,'ticker':ticker,'exchange':exchange,'report_date':report_date,'report_price':report_price,
        'market_cap':_money_abs(market_cap_raw),'revenue':_money_abs(revenue_raw),'revenue_forecast':_money_abs(revenue_forecast_raw),
        'pe':_rx_value(first,r'P/E Ratio\s*([0-9.,]+)'),
        'forward_pe':_rx_value(first,r'P/E\s*\(Fwd\.\)\s*([0-9.,]+)'),
        'peg':_rx_value(first,r'PEG Ratio\s*([0-9.,]+)'),
        'fcf_yield':_rx_value(first,r'FCF Yield\s*([0-9.,]+)'),
        'ev_ebitda':_rx_value(first,r'EV\s*/\s*EBITDA\s*([0-9.,]+)'),
        'beta':_rx_value(first,r'Beta\s*\(5Y\)\s*([0-9.,]+)'),
        'eps_actual':_rx_value(first,r'EPS Actual\s*([0-9.,]+)'),
        'eps_estimate':_rx_value(first,r'EPS Estimate\s*([0-9.,]+)'),
        'fair_value':_rx_value(first,r'Fair Value\s*\$([0-9.,]+)'),
        'financial_health':financial_health,'growth_rating':growth_rating,'profitability_rating':profitability_rating,'cashflow_rating':cashflow_rating,
        'analyst_avg':analyst_avg,'analyst_low':analyst_low,'analyst_high':analyst_high,'analyst_count':analyst_count,
        'eps_revisions_up':eps_up,'eps_revisions_down':eps_down,
        'pdf_technical':_rx_text(peer,r'Technical Summary\s*(Strong Sell|Sell|Neutral|Buy|Strong Buy)'),
        'revenue_growth_pct':_rx_value(peer,r'Revenue Growth\s*(-?[0-9.,]+)%'),
        'revenue_cagr_5y_pct':_rx_value(peer,r'Revenue CAGR\s*\(5y\)\s*(-?[0-9.,]+)%'),
        'net_income_growth_pct':_rx_value(peer,r'Net Income Growth\s*(-?[0-9.,]+)%'),
        'net_income_cagr_5y_pct':_rx_value(peer,r'Net\s*Income\s*CAGR\s*\(5y\)\s*(-?[0-9.,]+)%'),
        'revenue_forecast_cagr_5y_pct':_rx_value(peer,r'Revenue\s*Forecast\s*CAGR\s*\(5y\)\s*(-?[0-9.,]+)%'),
        'net_income_forecast_cagr_5y_pct':_rx_value(peer,r'Net\s*Income\s*Forecast\s*CAGR\s*\(5y\)\s*(-?[0-9.,]+)%'),
        'gross_margin_pct':_rx_value(peer,r'Gross Profit Margin\s*(-?[0-9.,]+)'),
        'roe_pct':_rx_value(peer,r'\bROE\s*(-?[0-9.,]+)'),
        'roa_pct':_rx_value(peer,r'\bROA\s*(-?[0-9.,]+)'),
        'analyst_upside_report_pct':_rx_value(peer,r'Analyst Upside\s*(-?[0-9.,]+)%'),
        'fair_value_upside_report_pct':_rx_value(peer,r'Fair Value Upside\s*(-?[0-9.,]+)%'),
    }
    debt_raw=_rx_text(peer,r'Total Debt\s*\$?([0-9.,]+\s*[KMBT]?)')
    report['total_debt']=_money_abs(debt_raw)
    opm=_rx_value(flat,r'Operating margin reached\s*([0-9.,]+)%')
    report['operating_margin_pct']=opm
    cash_raw=_rx_text(flat,r'holds\s*\$?([0-9.,]+\s*[KMBT])\s+in cash')
    report['cash']=_money_abs(cash_raw)
    ocf_raw=None
    if len(pages)>3:
        p4=re.sub(r'\s+',' ',pages[3])
        m=re.search(r'Cash from\s*Operations\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)',p4,re.I)
        if m:
            ocf_raw=m.group(5)+'M'
        revm=re.search(r'Income Statement.*?Revenue\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)',p4,re.I|re.S)
        nim=re.search(r'Net Income to\s*Stockholders\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)',p4,re.I)
        if revm and nim:
            try:
                rev_ltm=float(revm.group(5).replace(',',''))
                ni_ltm=float(nim.group(5).replace(',',''))
                report['profit_margin_pct']=ni_ltm/rev_ltm*100 if rev_ltm>0 else None
            except Exception:
                report['profit_margin_pct']=None
    report['operating_cashflow']=_money_abs(ocf_raw)
    report.setdefault('profit_margin_pct',None)

    warnings=[]
    if report.get('report_price') and report.get('fair_value') and report.get('fair_value_upside_report_pct') is not None:
        calc=(float(report['fair_value'])/float(report['report_price'])-1)*100
        if abs(calc-float(report['fair_value_upside_report_pct']))>3:
            warnings.append(f"Fair Value/Preço do PDF implicam {calc:+.1f}%, diferente do Fair Value Upside apresentado ({float(report['fair_value_upside_report_pct']):+.1f}%).")
    report['warnings']=warnings

    report['positive_points']=_report_sentence_candidates('\n'.join(pages[:9]),True,5)
    report['risk_points']=_report_sentence_candidates('\n'.join(pages[:9]),False,5)
    report['pages']=len(pages)
    keys=['report_price','pe','forward_pe','peg','fcf_yield','ev_ebitda','fair_value','financial_health','revenue_growth_pct','net_income_growth_pct','roe_pct','gross_margin_pct','analyst_avg','analyst_count']
    report['coverage_pct']=round(sum(report.get(k) is not None for k in keys)/len(keys)*100,1)
    return report


def _report_xtb_ticker(report):
    ticker=str(report.get('ticker') or '').upper().strip()
    exch=str(report.get('exchange') or '').upper()
    if not ticker:
        return None
    if exch in ['NYSE','NASDAQ','AMEX']:
        return ticker+'.US'
    return ticker


def _portfolio_holds_ticker(xtb_ticker, source_ticker=None):
    xtb=str(xtb_ticker or '').upper().strip(); source=str(source_ticker or '').upper().strip()
    for r in st.session_state.get('portfolio_input',[]) or []:
        rt=str(r.get('Ticker XTB') or '').upper().strip()
        rs=str(r.get('Ticker técnico') or '').upper().strip()
        if rt and rt==xtb:
            return True
        if source and (rt==source or rs==source):
            return True
    return False


def _analysis_with_report(a, report):
    """Recalcula fundamentais usando o PDF como evidência, sem mexer na técnica atual."""
    info=dict(a.get('info') or {})
    derived_fcf=None
    if report.get('market_cap') is not None and report.get('fcf_yield') is not None:
        derived_fcf=float(report['market_cap'])*float(report['fcf_yield'])/100.0
    mapping={
        'marketCap':report.get('market_cap'),
        'trailingPE':report.get('pe'),
        'forwardPE':report.get('forward_pe'),
        'enterpriseToEbitda':report.get('ev_ebitda'),
        'investingFcfYield':report.get('fcf_yield'),
        'investingFairValue':report.get('fair_value'),
        'investingHealthScore':report.get('financial_health'),
        'returnOnEquity':(report.get('roe_pct')/100 if report.get('roe_pct') is not None else None),
        'revenueGrowth':(report.get('revenue_growth_pct')/100 if report.get('revenue_growth_pct') is not None else None),
        'earningsGrowth':(report.get('net_income_growth_pct')/100 if report.get('net_income_growth_pct') is not None else None),
        'operatingMargins':(report.get('operating_margin_pct')/100 if report.get('operating_margin_pct') is not None else None),
        'profitMargins':(report.get('profit_margin_pct')/100 if report.get('profit_margin_pct') is not None else None),
        'freeCashflow':derived_fcf,
        'operatingCashflow':report.get('operating_cashflow'),
        'totalDebt':report.get('total_debt'),
        'totalCash':report.get('cash'),
        'targetMeanPrice':report.get('analyst_avg'),
        'numberOfAnalystOpinions':report.get('analyst_count'),
    }
    if report.get('total_debt') == 0:
        mapping['debtToEquity']=0.0
    for key,val in mapping.items():
        if val is not None and np.isfinite(val):
            info[key]=float(val)
    # Margem líquida aproximada só é usada quando o relatório dá valores LTM de receita/lucro de forma consistente.
    a2=dict(a); a2['info']=info
    if a2.get('kind')=='Ação':
        label,score,complete,table=fundamental_equity(info)
        a2['fund_label']=label; a2['fund_score']=score; a2['fund_complete']=complete; a2['fund_table']=table
    return a2


def _report_valuation_score(report, a):
    price=float(a['row']['Close']); parts=[]
    fair=_safe_float(report.get('fair_value'))
    if fair and price>0:
        upside=(fair/price-1)*100
        parts.append((_norm(upside,-25,35),0.45,'Fair Value'))
    peg=_safe_float(report.get('peg'))
    if peg and peg>0:
        parts.append((_metric_score(peg,3.5,1.0,False),0.20,'PEG'))
    fpe=_safe_float(report.get('forward_pe'))
    growth=_safe_float(report.get('net_income_forecast_cagr_5y_pct')) or _safe_float(report.get('revenue_forecast_cagr_5y_pct'))
    if fpe and growth and growth>0:
        ratio=fpe/growth
        parts.append((_metric_score(ratio,2.2,0.8,False),0.20,'Forward P/E / crescimento'))
    fy=_safe_float(report.get('fcf_yield'))
    if fy is not None:
        parts.append((_metric_score(fy,1.0,5.0,True),0.15,'FCF yield'))
    valid=[(v,w,n) for v,w,n in parts if v is not None]
    if not valid:
        return None,[]
    score=sum(v*w for v,w,_ in valid)/sum(w for _,w,_ in valid)
    return round(score,1),[(n,round(v,1)) for v,_,n in valid]


def _report_analyst_score(report, a):
    price=float(a['row']['Close']); target=_safe_float(report.get('analyst_avg')); n=_safe_float(report.get('analyst_count'))
    parts=[]
    if target and price>0 and (n is None or n>=3):
        upside=(target/price-1)*100
        parts.append((_norm(upside,-20,45),0.70))
    up=_safe_float(report.get('eps_revisions_up')); down=_safe_float(report.get('eps_revisions_down'))
    if up is not None and down is not None and up+down>0:
        parts.append((up/(up+down)*100,0.30))
    valid=[(v,w) for v,w in parts if v is not None]
    return round(sum(v*w for v,w in valid)/sum(w for _,w in valid),1) if valid else None


def _report_decision(a, report, holding=False):
    fund_raw=_safe_float(a.get('fund_score')); tech=_safe_float(a.get('tech_score'))
    rating_values=[_safe_float(report.get(k)) for k in ['growth_rating','profitability_rating','cashflow_rating']]
    rating_values=[x*10 for x in rating_values if x is not None]
    rating_score=float(np.mean(rating_values)) if rating_values else None
    if fund_raw is not None and rating_score is not None:
        fund=round(0.65*fund_raw+0.35*rating_score,1)
    else:
        fund=fund_raw if fund_raw is not None else rating_score
    if fund is not None:
        fund=min(96.0,float(fund))
    val,val_parts=_report_valuation_score(report,a)
    analyst=_report_analyst_score(report,a)
    parts=[]
    for value,weight in [(fund,0.40),(val,0.25),(tech,0.25),(analyst,0.10)]:
        if value is not None: parts.append((value,weight))
    overall=round(sum(v*w for v,w in parts)/sum(w for _,w in parts),1) if parts else None
    if holding:
        if fund is not None and fund<45 and tech is not None and tech<45:
            action='VENDER / REDUZIR'
        elif fund is not None and fund>=72 and val is not None and val>=65 and tech is not None and tech>=65:
            action='REFORÇAR'
        elif fund is not None and fund>=55:
            action='MANTER'
        else:
            action='REVER / REDUZIR'
    else:
        if fund is not None and fund>=72 and val is not None and val>=58 and tech is not None and tech>=62 and (overall or 0)>=68:
            action='COMPRAR'
        else:
            action='AGUARDAR'
    coverage=float(report.get('coverage_pct') or 0)
    fund_comp=float(a.get('fund_complete') or 0)
    confidence=max(0,min(90,0.55*coverage+0.45*fund_comp))
    report_age_days=None
    try:
        if report.get('report_date'):
            report_dt=datetime.strptime(str(report['report_date']),'%b %d, %Y')
            report_age_days=max(0,(datetime.now()-report_dt).days)
            if report_age_days>180: confidence-=20
            elif report_age_days>90: confidence-=10
            elif report_age_days>45: confidence-=5
    except Exception:
        pass
    confidence=round(max(0,min(90,confidence)),0)
    if confidence>=80: conf_label='Alta'
    elif confidence>=60: conf_label='Média-alta'
    elif confidence>=45: conf_label='Média'
    else: conf_label='Baixa'
    return {'action':action,'overall':overall,'fundamental':fund,'valuation':val,'technical':tech,'analysts':analyst,'confidence':confidence,'confidence_label':conf_label,'valuation_parts':val_parts,'report_age_days':report_age_days}


def _report_summary_reasons(a, report, decision):
    reasons=[]
    fund=decision.get('fundamental'); val=decision.get('valuation'); tech=decision.get('technical')
    rg=_safe_float(report.get('revenue_growth_pct')); roe=_safe_float(report.get('roe_pct'))
    if fund is not None and fund>=70:
        txt=f'Fundamentais fortes ({fund:.0f}/100)'
        extras=[]
        if rg is not None: extras.append(f'receitas +{rg:.1f}%')
        if roe is not None: extras.append(f'ROE {roe:.1f}%')
        if extras: txt+=' - '+', '.join(extras)
        reasons.append(txt)
    elif fund is not None:
        reasons.append(f'Qualidade fundamental {fund:.0f}/100, sem margem para uma conclusão forte')
    if val is not None:
        reasons.append(('Avaliação atrativa' if val>=65 else ('Avaliação equilibrada' if val>=50 else 'Avaliação exigente'))+f' ({val:.0f}/100)')
    if tech is not None:
        short,_=_short_action(a,holding=False)
        reasons.append(f'Técnica atual {tech:.0f}/100 - {short}')
    return reasons[:3]


def _report_date_obj(value):
    if not value:
        return None
    txt=str(value).strip()
    for fmt in ('%b %d, %Y','%Y-%m-%d','%d/%m/%Y'):
        try:
            return datetime.strptime(txt,fmt)
        except Exception:
            pass
    return None


def _report_archive_entry(report, file_name='', file_hash=''):
    return {
        'report':_json_safe(report),
        'file_name':str(file_name or ''),
        'file_hash':str(file_hash or ''),
        'saved_at':datetime.now(timezone.utc).isoformat(),
    }


def _choose_latest_report(xtb, uploaded_report, file_name='', file_hash=''):
    """Escolhe o relatório mais recente já conhecido para o ticker.

    O PDF nunca é guardado no estado JSON; apenas os dados extraídos.
    Um relatório com data anterior não substitui um mais recente.
    """
    library=st.session_state.setdefault('report_library',{})
    current=library.get(xtb) if isinstance(library,dict) else None
    current_report=(current or {}).get('report') or {}
    cur_dt=_report_date_obj(current_report.get('report_date'))
    new_dt=_report_date_obj(uploaded_report.get('report_date'))

    if current_report:
        if cur_dt and new_dt and new_dt < cur_dt:
            return current_report,'older',current
        if cur_dt and not new_dt:
            return current_report,'undated_older',current
        if cur_dt and new_dt and new_dt == cur_dt and str((current or {}).get('file_hash') or '') == str(file_hash or ''):
            return current_report,'same',current

    entry=_report_archive_entry(uploaded_report,file_name,file_hash)
    library[xtb]=entry
    st.session_state.report_library=library
    if current_report and cur_dt and new_dt and new_dt == cur_dt:
        status='replaced_same_date'
    elif current_report:
        status='newer'
    else:
        status='first'
    return uploaded_report,status,entry


def build_report_analysis_from_report(report):
    if not report.get('ticker'):
        raise ValueError('Não consegui identificar o ticker no relatório guardado.')
    xtb=_report_xtb_ticker(report)
    if not xtb:
        raise ValueError('Ticker identificado, mas não foi possível mapear o instrumento para análise de mercado.')
    a=analyze_asset(xtb,detailed=False,instrument_type='Ação')
    a=_analysis_with_report(a,report)
    holding=_portfolio_holds_ticker(xtb,a.get('source_ticker'))
    decision=_report_decision(a,report,holding)
    valuation=valuation_scenarios(a)
    zone=entry_zone(a,valuation)
    return {'report':report,'analysis':a,'decision':decision,'holding':holding,'valuation':valuation,'zone':zone}


def build_report_analysis(uploaded_file):
    raw=uploaded_file.getvalue() if hasattr(uploaded_file,'getvalue') else bytes(uploaded_file)
    file_hash=hashlib.sha256(raw).hexdigest()
    pages,text=_extract_pdf_pages(uploaded_file)
    uploaded_report=parse_investingpro_report(pages,text)
    if not uploaded_report.get('ticker'):
        raise ValueError('Não consegui identificar o ticker no PDF. O formato esperado é semelhante a InvestingPro Research.')
    xtb=_report_xtb_ticker(uploaded_report)
    if not xtb:
        raise ValueError('Ticker identificado, mas não foi possível mapear o instrumento para análise de mercado.')
    chosen,status,entry=_choose_latest_report(xtb,uploaded_report,getattr(uploaded_file,'name',''),file_hash)
    result=build_report_analysis_from_report(chosen)
    result.update({'pages':pages,'upload_status':status,'uploaded_report':uploaded_report,'archive_entry':entry,'file_hash':file_hash})
    return result


def _portfolio_health_report(rows):
    good=[r for r in rows if isinstance(r,dict) and r.get('_analysis')]
    invest=[r for r in good if r.get('Tipo instrumento')!='CFD']
    if not invest:
        return {'score':None,'label':'Sem investimentos avaliáveis','risks':['Sem posições de investimento com dados suficientes.'],'sector_weights':{},'currency_weights':{},'asset_weights':{}}
    vals=[]
    for r in invest:
        v=_safe_float(r.get('Valor atual EUR'))
        if v is not None and v>0:
            vals.append((r,v))
    total=sum(v for _,v in vals)
    asset_weights={}; sector_weights={}; currency_weights={}
    if total>0:
        for r,v in vals:
            w=v/total*100.0
            asset_weights[r['Ticker XTB']]=w
            sec=str(r.get('Setor') or 'N/D')
            cur=str(r.get('Moeda') or 'N/D')
            sector_weights[sec]=sector_weights.get(sec,0.0)+w
            currency_weights[cur]=currency_weights.get(cur,0.0)+w
    quality=[_safe_float(r['_analysis'].get('fund_score')) for r in invest]
    quality=[x for x in quality if x is not None]
    tech=[_safe_float(r['_analysis'].get('tech_score')) for r in invest]
    tech=[x for x in tech if x is not None]
    comp=[_safe_float(r['_analysis'].get('fund_complete')) for r in invest]
    comp=[x for x in comp if x is not None]
    qscore=float(np.mean(quality)) if quality else 45.0
    tscore=float(np.mean(tech)) if tech else 45.0
    cscore=float(np.mean(comp)) if comp else 40.0
    max_asset=max(asset_weights.values()) if asset_weights else 0.0
    max_sector=max(sector_weights.values()) if sector_weights else 0.0
    asset_div=100.0 if max_asset<=15 else (20.0 if max_asset>=40 else 100-(max_asset-15)*(80/25))
    sector_div=100.0 if max_sector<=30 else (20.0 if max_sector>=65 else 100-(max_sector-30)*(80/35))
    divscore=(asset_div+sector_div)/2.0
    attention=sum(1 for r in invest if any(k in str(r.get('Decisão principal','')).upper() for k in ['REVER','REDUZIR','ALVO']))
    decision_score=max(20.0,100.0-attention/max(len(invest),1)*100.0)
    score=0.35*qscore+0.25*divscore+0.20*tscore+0.10*cscore+0.10*decision_score
    score=max(0.0,min(100.0,score))
    label='Forte' if score>=80 else ('Saudável' if score>=65 else ('Mista' if score>=50 else 'Atenção'))
    risks=[]
    if max_asset>20:
        ticker=max(asset_weights,key=asset_weights.get); risks.append(f'Concentração: {ticker} representa cerca de {max_asset:.1f}% do valor de investimento.')
    if max_sector>40:
        sec=max(sector_weights,key=sector_weights.get); risks.append(f'Concentração setorial: {sec} representa cerca de {max_sector:.1f}%.')
    if cscore<60:
        risks.append(f'Cobertura média dos fundamentais/qualidade é {cscore:.0f}%.')
    if attention:
        risks.append(f'{attention} posição(ões) pedem revisão, redução ou atingiram um alvo.')
    cfd_count=sum(1 for r in good if r.get('Tipo instrumento')=='CFD')
    if cfd_count:
        risks.append(f'{cfd_count} CFD(s) ficam fora da nota de saúde de investimento e devem ser avaliados como trading.')
    if not risks:
        risks.append('Sem alertas estruturais relevantes pelas regras atuais.')
    return {'score':round(score,1),'label':label,'quality':round(qscore,1),'technical':round(tscore,1),'data':round(cscore,1),'diversification':round(divscore,1),'risks':risks,'sector_weights':sector_weights,'currency_weights':currency_weights,'asset_weights':asset_weights}


def _active_alerts(rows):
    by_ticker={str(r.get('Ticker XTB','')).upper():r for r in rows if isinstance(r,dict)}
    active=[]
    for t,r in by_ticker.items():
        action=str(r.get('Decisão principal') or '')
        if any(k in action.upper() for k in ['REVER','REDUZIR','ALVO']):
            active.append({'Ticker':t,'Tipo':'Sistema','Mensagem':action})
        elif 'CANDIDATO A REFORÇO' in action.upper():
            active.append({'Ticker':t,'Tipo':'Sistema','Mensagem':'Candidato a reforço pelas regras atuais'})
    for al in st.session_state.get('alerts',[]) or []:
        t=str(al.get('ticker') or '').upper().strip(); r=by_ticker.get(t)
        if not r: continue
        cond=str(al.get('condition') or '')
        threshold=_safe_float(al.get('threshold'))
        price=_safe_float(r.get('Preço atual'))
        triggered=False
        if cond=='Preço <=' and threshold is not None and price is not None: triggered=price<=threshold
        elif cond=='Preço >=' and threshold is not None and price is not None: triggered=price>=threshold
        elif cond=='Rever / reduzir': triggered=any(k in str(r.get('Decisão principal','')).upper() for k in ['REVER','REDUZIR'])
        elif cond=='Candidato a reforço': triggered='CANDIDATO A REFORÇO' in str(r.get('Decisão principal','')).upper()
        if triggered:
            msg=f'{cond} {threshold:g}' if threshold is not None and cond.startswith('Preço') else cond
            active.append({'Ticker':t,'Tipo':'Pessoal','Mensagem':msg})
    return active


def decision_performance_standardized():
    rows=[]
    cache={}
    for h in st.session_state.get('decision_history',[]) or []:
        try:
            ts=pd.to_datetime(h.get('Data decisão UTC'),utc=True,errors='coerce')
            if pd.isna(ts):
                continue
            source=str(h.get('Ticker técnico') or '').upper().strip()
            if not source:
                source=resolve_instrument(h.get('Ticker XTB'))['source_ticker']
            if source not in cache:
                cache[source]=price_data(source,'5y','1d')
            d=cache[source]
            idx=pd.to_datetime(d.index)
            if getattr(idx,'tz',None) is not None:
                idx=idx.tz_localize(None)
            decision_day=ts.tz_convert(None).normalize()
            positions=np.where(idx.normalize()>=decision_day)[0]
            if not len(positions):
                continue
            i=int(positions[0]); base=_safe_float(h.get('Preço na decisão'))
            if base is None or base<=0:
                base=float(d['Close'].iloc[i])
            rec={'Data decisão':str(decision_day.date()),'Ticker XTB':h.get('Ticker XTB'),'Decisão':h.get('Decisão utilizador')}
            for horizon in [5,20,60]:
                j=i+horizon
                rec[f'{horizon}d %']=((float(d['Close'].iloc[j])/base-1)*100 if j<len(d) else None)
            r20=_safe_float(rec.get('20d %')); action=str(h.get('Decisão utilizador') or '').upper()
            if r20 is not None:
                if 'ACEIT' in action:
                    rec['Resultado 20d']='Favorável' if r20>0 else ('Desfavorável' if r20<0 else 'Neutro')
                elif 'REJEIT' in action:
                    rec['Resultado 20d']='Favorável' if r20<0 else ('Desfavorável' if r20>0 else 'Neutro')
                else:
                    rec['Resultado 20d']='N/D'
            else:
                rec['Resultado 20d']='A aguardar dados'
            rows.append(rec)
        except Exception as e:
            rows.append({'Ticker XTB':h.get('Ticker XTB'),'Decisão':h.get('Decisão utilizador'),'Erro':str(e)})
    return pd.DataFrame(rows)


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



def _comparison_rank(values, higher_better=True):
    """Score 0-100 apenas dentro do conjunto comparado; requer pelo menos 2 valores."""
    series=pd.to_numeric(pd.Series(values),errors='coerce')
    valid=series.dropna()
    if len(valid)<2:
        return [None]*len(series)
    ranks=valid.rank(method='average',ascending=True)
    pct=(ranks-1.0)/(len(valid)-1.0)*100.0
    scores={i:(float(v) if higher_better else float(100.0-v)) for i,v in pct.items()}
    return [scores.get(i) for i in range(len(series))]


def _comparison_rows(analyses):
    rows=[]
    for a in analyses:
        info=a['info']; row=a['row']; price=float(row['Close'])
        short_action,short_score=_short_action(a,holding=False)
        long_action,long_score=_long_action(a,holding=False)
        fcf=_num(info,'freeCashflow'); market_cap=_num(info,'marketCap')
        fcf_yield=_num(info,'investingFcfYield')
        if fcf_yield is None:
            fcf_yield=(fcf/market_cap*100) if fcf is not None and market_cap and market_cap>0 else None
        fair_value=_num(info,'investingFairValue')
        fair_upside=_num(info,'investingFairValueUpside')
        if fair_upside is None and fair_value is not None and price>0:
            fair_upside=(fair_value/price-1)*100
        health_score=_num(info,'investingHealthScore')
        cons=analyst_consensus(info,price) if a['kind']=='Ação' else {
            'Preço alvo médio consenso':None,'Nº analistas':None,'Potencial consenso %':None
        }
        rows.append({
            'Ticker':a['xtb_ticker'],
            'Empresa':a['company'],
            'Setor':sector_name(info),
            'Indústria':industry_name(info),
            'Mercado':a['market'],
            'Moeda':a['currency'],
            'Preço':price,
            'Qualidade':a['fund_label'],
            'Score qualidade':a['fund_score'],
            'Dados fundamentais %':a['fund_complete'],
            'Crescimento receitas %':(_num(info,'revenueGrowth')*100 if _num(info,'revenueGrowth') is not None else None),
            'Crescimento lucros %':(_num(info,'earningsGrowth')*100 if _num(info,'earningsGrowth') is not None else None),
            'Margem operacional %':(_num(info,'operatingMargins')*100 if _num(info,'operatingMargins') is not None else None),
            'Margem líquida %':(_num(info,'profitMargins')*100 if _num(info,'profitMargins') is not None else None),
            'ROE %':(_num(info,'returnOnEquity')*100 if _num(info,'returnOnEquity') is not None else None),
            'FCF yield %':fcf_yield,
            'Dívida/Capital próprio %':_num(info,'debtToEquity'),
            'P/E':_num(info,'trailingPE'),
            'Forward P/E':_num(info,'forwardPE'),
            'P/B':_num(info,'priceToBook'),
            'EV/EBITDA':_num(info,'enterpriseToEbitda'),
            'Fair Value InvestingPro':fair_value,
            'Potencial Fair Value %':fair_upside,
            'Saúde financeira InvestingPro':health_score,
            'Fonte qualidade':_sources_summary(a,['revenueGrowth','earningsGrowth','operatingMargins','profitMargins','returnOnEquity','freeCashflow','operatingCashflow','debtToEquity']),
            'Fonte avaliação':_sources_summary(a,['trailingPE','forwardPE','priceToBook','enterpriseToEbitda','freeCashflow','marketCap','investingFcfYield']),
            'Fonte ROE':_source_for(a,'returnOnEquity'),
            'Fonte FCF':_source_for(a,'freeCashflow'),
            'Fonte P/E':_source_for(a,'trailingPE'),
            'Fonte Forward P/E':_source_for(a,'forwardPE'),
            'Fonte P/B':_source_for(a,'priceToBook'),
            'Fonte EV/EBITDA':_source_for(a,'enterpriseToEbitda'),
            'Fonte analistas':_sources_summary(a,['targetMeanPrice','numberOfAnalystOpinions','recommendationKey']),
            'Técnica':a['tech_label'],
            'Score técnico':a['tech_score'],
            'RSI':float(row['RSI14']),
            'Retorno 20d %':float(row['RET20']),
            'Retorno 60d %':float(row['RET60']),
            'Curto prazo':short_action,
            'Score entrada':short_score,
            'Longo prazo':long_action,
            'Score longo':long_score,
            'Alvo médio analistas':cons.get('Preço alvo médio consenso'),
            'Potencial analistas %':cons.get('Potencial consenso %'),
            'Nº analistas':cons.get('Nº analistas'),
            'Recomendação analistas':str(info.get('recommendationKey') or 'N/D').replace('_',' ').title(),
            '_analysis':a,
        })
    df=pd.DataFrame(rows)
    if df.empty:
        return df

    # Avaliação relativa apenas entre as empresas selecionadas. Métricas inválidas/negativas são ignoradas.
    val_parts=[]
    for col in ['P/E','Forward P/E','P/B','EV/EBITDA']:
        vals=pd.to_numeric(df[col],errors='coerce').where(pd.to_numeric(df[col],errors='coerce')>0)
        sc=_comparison_rank(vals.tolist(),higher_better=False)
        if any(v is not None for v in sc): val_parts.append(pd.Series(sc,index=df.index))
    sc=_comparison_rank(pd.to_numeric(df['FCF yield %'],errors='coerce').tolist(),higher_better=True)
    if any(v is not None for v in sc): val_parts.append(pd.Series(sc,index=df.index))
    df['Score avaliação comparada']=pd.concat(val_parts,axis=1).mean(axis=1,skipna=True) if val_parts else np.nan

    # Rentabilidade: combinação simples das métricas de eficiência disponíveis no conjunto.
    profit_parts=[]
    for col in ['ROE %','Margem operacional %','Margem líquida %']:
        sc=_comparison_rank(pd.to_numeric(df[col],errors='coerce').tolist(),higher_better=True)
        if any(v is not None for v in sc): profit_parts.append(pd.Series(sc,index=df.index))
    df['Score rentabilidade comparada']=pd.concat(profit_parts,axis=1).mean(axis=1,skipna=True) if profit_parts else np.nan

    # Analistas: só usa potencial quando há pelo menos 3 opiniões, para reduzir leituras frágeis.
    analyst_up=pd.to_numeric(df['Potencial analistas %'],errors='coerce')
    analyst_n=pd.to_numeric(df['Nº analistas'],errors='coerce')
    analyst_up=analyst_up.where(analyst_n>=3)
    df['Score analistas comparado']=_comparison_rank(analyst_up.tolist(),higher_better=True)

    # Score geral é um resumo heurístico, não uma previsão. Repondera automaticamente dados em falta.
    overall=[]
    for _,r in df.iterrows():
        parts=[]
        for col,w in [('Score qualidade',0.40),('Score avaliação comparada',0.25),('Score entrada',0.25),('Score analistas comparado',0.10)]:
            v=pd.to_numeric(pd.Series([r.get(col)]),errors='coerce').iloc[0]
            if pd.notna(v): parts.append((float(v),w))
        overall.append(round(sum(v*w for v,w in parts)/sum(w for _,w in parts),1) if parts else None)
    df['Score equilíbrio geral']=overall
    return df


def _winner_ticker(df, column, higher=True):
    if df is None or df.empty or column not in df.columns:
        return None
    s=pd.to_numeric(df[column],errors='coerce')
    if s.notna().sum()==0:
        return None
    idx=s.idxmax() if higher else s.idxmin()
    return str(df.loc[idx,'Ticker'])


def _comparison_metric_card(label, ticker, note=''):
    st.metric(label,ticker or 'N/D')
    if note:
        st.caption(note)

st.caption('Modo simples: decisão prática primeiro, 3 evidências interpretadas e detalhe apenas quando pedes.')
PAGE = st.radio('Navegação', ['Hoje', 'Carteira', 'Risco', 'Analisar', 'Relatório', 'Comparar'], horizontal=True, label_visibility='collapsed', key='main_page')

if PAGE == 'Hoje':
    st.subheader('Dashboard de oportunidades')
    st.markdown('<div class="section-note">Primeiro a decisão prática. O mesmo scan é organizado por entrada, valor relativo ao setor e oportunidades que pedem paciência.</div>', unsafe_allow_html=True)

    c1,c2=st.columns([3,1])
    with c1:
        scan_markets=st.multiselect('Mercados',list(MARKETS.keys()),default=['EUA','Alemanha','Portugal'],key='v14_markets')
    with c2:
        scan_mode=st.selectbox('Pesquisa',['Rápida','Alargada'],index=0,key='v14_speed',help='Rápida analisa menos ativos e é a opção recomendada no telemóvel.')
    only_type=st.selectbox('Tipo',['Todos','Ação','ETF','ETN'],index=0,key='v14_type')

    if st.button('Atualizar oportunidades',type='primary',use_container_width=True,key='v14_scan'):
        if persistence_enabled() and not st.session_state.get('_persistent_loaded'):
            load_persistent_state()
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
                                add_or_merge_portfolio_position(a['xtb_ticker'],actual_qty,actual_entry,objective,0,'Oportunidade aceite',datetime.now().date(),'Aceite através do resumo de oportunidades',instrument_type=a.get('kind','Auto'),source_ticker=a.get('source_ticker',''))
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

[USERS.vitor]
password = "uma-palavra-passe-forte"
owner_id = "carteira-principal" # usa o owner_id atual para manter a carteira existente
display_name = "Vítor"

[USERS.utilizador2]
password = "outra-palavra-passe"
owner_id = "utilizador2"
display_name = "Utilizador 2"
```
4. Guarda os Secrets e reinicia a app. Cada login passa a usar o seu `owner_id` e os dados ficam separados.

A configuração antiga com `APP_PASSWORD` + `PORTFOLIO_OWNER_ID` continua compatível para uma única conta.

**Não coloques chaves nem palavras-passe no GitHub.** Devem existir apenas nos Secrets do Streamlit.
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
            with a1: mt=st.text_input('Ticker XTB',placeholder='Ex.: ASML.NL ou US100')
            with a2: mq=st.number_input('Quantidade',min_value=0.0,value=0.0,step=0.01)
            with a3: mp=st.number_input('Preço médio',min_value=0.0,value=0.0,step=0.01)
            a4,a5,a6=st.columns(3)
            with a4: mi=st.selectbox('Tipo de instrumento',INSTRUMENT_TYPES,index=0)
            with a5: mo=st.selectbox('Objetivo',['Longo prazo','Curto prazo'])
            with a6: mtarget=st.number_input('Alvo pessoal (opcional)',min_value=0.0,value=0.0,step=0.01)
            ax1,ax2=st.columns(2)
            with ax1:
                msource=st.text_input('Ticker técnico/subjacente (opcional)',placeholder='Ex.: ^NDX, GC=F ou NVDA')
            with ax2:
                mmult=st.number_input('Multiplicador do contrato (CFD, opcional)',min_value=0.0,value=0.0,step=0.01)
            md=st.date_input('Data de entrada',value=datetime.now().date())
            thesis=st.text_input('Nota (opcional)',placeholder='Porque compraste / o que queres acompanhar')
            submitted=st.form_submit_button('Adicionar à carteira',type='primary',use_container_width=True)
        if submitted:
            if not str(mt).strip() or mq<=0 or mp<=0:
                st.error('Indica ticker, quantidade e preço médio válidos.')
            else:
                try:
                    aa=analyze_asset(str(mt).upper().strip(),detailed=False,instrument_type=mi,source_override=(str(msource).upper().strip() or None))
                    add_or_merge_portfolio_position(
                        aa['xtb_ticker'],mq,mp,mo,mtarget,'Posição existente adicionada por mim',md,thesis,
                        instrument_type=aa.get('kind','Auto'),source_ticker=aa.get('source_ticker',''),contract_multiplier=mmult
                    )
                    add_watchlist(aa['xtb_ticker'])
                    st.success(f"{aa['xtb_ticker']} ({aa['kind']}) adicionada.")
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
                    if 'Tipo instrumento' not in imp.columns:
                        imp['Tipo instrumento']='Auto'
                    if 'Ticker técnico' not in imp.columns:
                        imp['Ticker técnico']=''
                    if 'Multiplicador contrato' not in imp.columns:
                        imp['Multiplicador contrato']=0.0
                    imp['Tipo instrumento']=imp['Tipo instrumento'].apply(_normalize_instrument_type)
                    st.session_state.portfolio_input=imp.to_dict('records')
                    save_persistent_state(show_error=True)
                    st.success('Carteira importada e guardada. A coluna Tipo instrumento e opcional: Auto, Ação, ETF, ETN ou CFD.')
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

                health=_portfolio_health_report(good)
                st.markdown('### Radar da carteira')
                h1,h2,h3,h4=st.columns(4)
                h1.metric('Saúde',f"{health['score']:.0f}/100" if health.get('score') is not None else 'N/D',health.get('label',''))
                h2.metric('Qualidade',f"{health.get('quality',0):.0f}/100" if health.get('score') is not None else 'N/D')
                h3.metric('Diversificação',f"{health.get('diversification',0):.0f}/100" if health.get('score') is not None else 'N/D')
                h4.metric('Cobertura dados',f"{health.get('data',0):.0f}%" if health.get('score') is not None else 'N/D')
                for risk in health.get('risks',[])[:3]:
                    st.caption('• '+risk)

                active=_active_alerts(good)
                if active:
                    with st.expander(f'🔔 Alertas ativos ({len(active)})'):
                        st.dataframe(pd.DataFrame(active),hide_index=True,use_container_width=True)

                st.markdown('### Resumo das posições')
                cfd_sem_mult=0
                for r in good:
                    ev=[x.strip() for x in str(r.get('Resumo','')).split(' · ') if x.strip()]
                    if r.get('Tipo instrumento')=='CFD':
                        mov=_safe_float(r.get('Movimento subjacente %'))
                        subtitle=f"{r.get('Objetivo','')} · CFD · movimento subjacente {mov:+.1f}%" if mov is not None else f"{r.get('Objetivo','')} · CFD"
                        if _safe_float(r.get('Multiplicador contrato')) is None:
                            cfd_sem_mult += 1
                    else:
                        pl=_safe_float(r.get('P/L %'))
                        subtitle=f"{r.get('Objetivo','')} · P/L {pl:+.1f}%" if pl is not None else str(r.get('Objetivo',''))
                    _asset_card(r['Ticker XTB'],r['Empresa'],r['Decisão principal'],r['Score longo'] if r.get('Objetivo')!='Curto prazo' else r['Score curto'],ev,r['Preço atual'],r['Moeda'],subtitle)
                if cfd_sem_mult:
                    st.caption(f'{cfd_sem_mult} CFD(s) sem multiplicador de contrato: o P/L em euros fica N/D para evitar um valor enganador.')

                with st.expander('Ver tabela da carteira'):
                    pdf=pd.DataFrame([{k:v for k,v in r.items() if k!='_analysis'} for r in good])
                    showcols=['Ticker XTB','Tipo instrumento','Subjacente','Objetivo','Preço atual','Moeda','P/L %','Movimento subjacente %','P/L EUR aprox.','Decisão principal','Curto prazo','Longo prazo']
                    st.dataframe(pdf[[c for c in showcols if c in pdf.columns]],hide_index=True,use_container_width=True)

                st.divider()
                sel=st.selectbox('Detalhe de uma posição',[r['Ticker XTB'] for r in good],key='v14_port_pick')
                if st.button('Ver alvos e prazos',key='v14_port_detail',use_container_width=True):
                    selected_row=next((x for x in good if x.get('Ticker XTB')==sel),None)
                    with st.spinner('A calcular histórico apenas desta posição...'):
                        a=analyze_asset(
                            sel,detailed=True,
                            instrument_type=(selected_row or {}).get('Tipo instrumento') or 'Auto',
                            source_override=((selected_row or {}).get('Ticker técnico') or None),
                        )
                    st.session_state['v14_port_detail_result']=a
                detail=st.session_state.get('v14_port_detail_result')
                if detail is not None and detail.get('xtb_ticker')==sel:
                    current=float(detail['row']['Close'])
                    d1,d2,d3=st.columns(3)
                    d1.metric('Preço',f'{current:.2f} {detail["currency"]}')
                    d2.metric('Alvo técnico',f'{detail["target"]:.2f} {detail["currency"]}')
                    tt=detail.get('target_time',{})
                    d3.metric('Tempo histórico',f'{tt.get("median_days"):.0f} dias' if tt.get('median_days') is not None else 'N/D')
                    val=valuation_scenarios(detail); zone=entry_zone(detail,val)
                    st.caption(f"Zona técnica potencial: {zone['low']:.2f}–{zone['high']:.2f} {detail['currency']} · {zone['status']}")
                    if val.get('available'):
                        st.caption(f"Cenário de valor base: {val['base']:.2f} {detail['currency']} · confiança {val['confidence']} · {val['sources']}.")
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

            if st.button('Avaliar método a 5 / 20 / 60 dias de mercado',key='decision_stats_run',use_container_width=True):
                with st.spinner('A medir as decisões com horizontes comparáveis...'):
                    st.session_state['decision_stats_df']=decision_performance_standardized()
            ds=st.session_state.get('decision_stats_df')
            if isinstance(ds,pd.DataFrame) and not ds.empty:
                valid=ds[ds['Resultado 20d'].isin(['Favorável','Desfavorável','Neutro'])] if 'Resultado 20d' in ds.columns else pd.DataFrame()
                if not valid.empty:
                    fav=(valid['Resultado 20d']=='Favorável').mean()*100
                    d1,d2=st.columns(2)
                    d1.metric('Decisões favoráveis a 20 dias',f'{fav:.0f}%')
                    d2.metric('Amostras comparáveis',len(valid))
                cols3=['Data decisão','Ticker XTB','Decisão','5d %','20d %','60d %','Resultado 20d']
                st.dataframe(ds[[c for c in cols3 if c in ds.columns]],hide_index=True,use_container_width=True)
                st.caption('“Favorável” significa que uma decisão aceite subiu ou uma decisão rejeitada caiu ao fim de 20 dias de mercado. É uma métrica de aprendizagem, não prova causal.')


elif PAGE == 'Risco':
    st.subheader('Risco e alertas')
    st.caption('Saúde, concentração e alertas da carteira. CFDs são tratados separadamente dos investimentos.')
    if not st.session_state.get('_persistent_loaded'):
        with st.spinner('A carregar a carteira guardada...'):
            load_persistent_state()

    if st.session_state.get('portfolio_input'):
        if st.button('Atualizar radar de risco',type='primary',use_container_width=True,key='risk_refresh'):
            out=[]
            prog=st.progress(0,text='A atualizar risco da carteira...')
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

        rows=st.session_state.get('v14_portfolio_rows',[])
        good=[r for r in rows if isinstance(r,dict) and r.get('_analysis')]
        if good:
            health=_portfolio_health_report(good)
            r1,r2,r3,r4=st.columns(4)
            r1.metric('Saúde da carteira',f"{health['score']:.0f}/100" if health.get('score') is not None else 'N/D',health.get('label',''))
            r2.metric('Qualidade',f"{health.get('quality',0):.0f}/100" if health.get('score') is not None else 'N/D')
            r3.metric('Diversificação',f"{health.get('diversification',0):.0f}/100" if health.get('score') is not None else 'N/D')
            r4.metric('Técnica média',f"{health.get('technical',0):.0f}/100" if health.get('score') is not None else 'N/D')

            st.markdown('### Principais riscos')
            for risk in health.get('risks',[]): st.write('• '+risk)

            e1,e2=st.columns(2)
            with e1:
                st.markdown('#### Exposição por setor')
                sec=pd.DataFrame([{'Setor':k,'Peso %':v} for k,v in sorted(health.get('sector_weights',{}).items(),key=lambda x:x[1],reverse=True)])
                if not sec.empty: st.dataframe(sec,hide_index=True,use_container_width=True)
                else: st.caption('Sem valores suficientes.')
            with e2:
                st.markdown('#### Exposição por moeda')
                cur=pd.DataFrame([{'Moeda':k,'Peso %':v} for k,v in sorted(health.get('currency_weights',{}).items(),key=lambda x:x[1],reverse=True)])
                if not cur.empty: st.dataframe(cur,hide_index=True,use_container_width=True)
                else: st.caption('Sem valores suficientes.')

            cfds=[r for r in good if r.get('Tipo instrumento')=='CFD']
            if cfds:
                st.markdown('### Trading / CFDs')
                cdf=pd.DataFrame([{
                    'Ticker':r.get('Ticker XTB'),'Subjacente':r.get('Ticker técnico'),'Movimento %':r.get('Movimento subjacente %'),
                    'Notional EUR aprox.':r.get('Notional CFD EUR aprox.'),'Decisão':r.get('Decisão principal')
                } for r in cfds])
                st.dataframe(cdf,hide_index=True,use_container_width=True)
                st.caption('O notional só aparece quando existe multiplicador de contrato. Não é tratado como valor de investimento da carteira.')

            st.markdown('### Alertas')
            active=_active_alerts(good)
            if active:
                st.dataframe(pd.DataFrame(active),hide_index=True,use_container_width=True)
            else:
                st.success('Nenhum alerta ativo nas regras avaliadas agora.')
            st.caption('Os alertas desta página são avaliados quando atualizas a carteira/radar; não enviam notificações push em segundo plano.')

            with st.expander('➕ Criar alerta pessoal'):
                at=st.selectbox('Ticker',[r['Ticker XTB'] for r in good],key='alert_ticker')
                ac=st.selectbox('Condição',['Preço <=','Preço >=','Rever / reduzir','Candidato a reforço'],key='alert_condition')
                ath=None
                if ac.startswith('Preço'):
                    current=next((_safe_float(r.get('Preço atual')) for r in good if r.get('Ticker XTB')==at),None) or 0.0
                    ath=st.number_input('Nível de preço',min_value=0.0,value=float(current),step=0.01,key='alert_threshold')
                if st.button('Guardar alerta',use_container_width=True,key='alert_save'):
                    alerts=list(st.session_state.get('alerts',[]) or [])
                    alerts.append({'ticker':at,'condition':ac,'threshold':ath,'created_at':_now_utc_iso()})
                    st.session_state.alerts=alerts
                    save_persistent_state(show_error=True)
                    st.success('Alerta guardado para este utilizador.')
                    st.rerun()
            alerts=list(st.session_state.get('alerts',[]) or [])
            if alerts:
                with st.expander('Gerir alertas guardados'):
                    adf=pd.DataFrame(alerts)
                    st.dataframe(adf,hide_index=True,use_container_width=True)
                    choices=[f"{i+1} · {a.get('ticker')} · {a.get('condition')}" for i,a in enumerate(alerts)]
                    rem=st.selectbox('Remover alerta',choices,key='alert_remove_pick')
                    if st.button('Remover selecionado',use_container_width=True,key='alert_remove'):
                        idx=choices.index(rem); alerts.pop(idx); st.session_state.alerts=alerts
                        save_persistent_state(show_error=True); st.rerun()
        else:
            st.info('Carrega em **Atualizar radar de risco** para calcular a saúde e as exposições atuais.')
    else:
        st.info('Ainda não tens posições registadas nesta conta.')


elif PAGE == 'Relatório':
    st.subheader('Analisar relatório')
    st.caption('Carrega um relatório InvestingPro em PDF. A app usa o PDF para fundamentais/avaliação e recalcula a técnica com preços atuais.')
    if persistence_enabled() and not st.session_state.get('_persistent_loaded'):
        load_persistent_state()

    st.markdown('### 📄 Selecionar relatório')
    st.caption('Seleciona o PDF mais recente do InvestingPro. A análise começa automaticamente - não precisas de indicar ticker, empresa ou data.')
    report_file=st.file_uploader('Relatório InvestingPro (PDF)',type=['pdf'],key='report_pdf_upload',label_visibility='collapsed')

    if report_file is not None:
        try:
            raw=report_file.getvalue()
            upload_hash=hashlib.sha256(raw).hexdigest()
            if st.session_state.get('_report_last_upload_hash') != upload_hash:
                with st.spinner('A identificar o relatório, confirmar a versão mais recente e atualizar a análise...'):
                    result=build_report_analysis(report_file)
                st.session_state['_report_last_upload_hash']=upload_hash
                st.session_state['report_result']=result
                st.session_state['report_parsed']=result['report']
                entry=result.get('archive_entry') or {}
                st.session_state['report_file_name']=entry.get('file_name') or report_file.name
                status=result.get('upload_status')
                if status in ['first','newer','replaced_same_date']:
                    save_persistent_state(show_error=False)
                st.session_state['report_import_status']=status
        except Exception as e:
            st.error(str(e))

    library=st.session_state.get('report_library',{}) or {}
    if library:
        with st.expander('Relatórios mais recentes guardados'):
            options=sorted(library.keys())
            labels={}
            for t in options:
                rep=(library.get(t) or {}).get('report') or {}
                labels[t]=f"{t} · {rep.get('company') or 'Empresa N/D'} · {rep.get('report_date') or 'data N/D'}"
            saved_ticker=st.selectbox('Relatório',options,format_func=lambda x:labels.get(x,x),key='saved_report_pick')
            b1,b2=st.columns([2,1])
            with b1:
                if st.button('Atualizar análise deste relatório',use_container_width=True,key='saved_report_analyze'):
                    try:
                        with st.spinner('A atualizar preços e análise técnica...'):
                            rep=dict((library.get(saved_ticker) or {}).get('report') or {})
                            result=build_report_analysis_from_report(rep)
                        st.session_state['report_result']=result
                        st.session_state['report_parsed']=rep
                        st.session_state['report_file_name']=(library.get(saved_ticker) or {}).get('file_name','')
                        st.session_state['report_import_status']='saved'
                    except Exception as e:
                        st.error(str(e))
            with b2:
                if st.button('Remover guardado',use_container_width=True,key='saved_report_remove'):
                    library.pop(saved_ticker,None)
                    st.session_state.report_library=library
                    save_persistent_state(show_error=False)
                    st.rerun()

    if st.button('Limpar análise do ecrã',use_container_width=True,key='report_clear'):
        for k in ['report_parsed','report_result','report_file_name','report_import_status']:
            st.session_state.pop(k,None)
        st.rerun()

    rr=st.session_state.get('report_result')
    if rr:
        report=rr['report']; a=rr['analysis']; dec=rr['decision']; holding=rr['holding']; val=rr['valuation']; zone=rr['zone']
        st.markdown(f"## {a['xtb_ticker']} · {report.get('company') or a['company']}")
        st.caption(f"PDF: {st.session_state.get('report_file_name','')} · relatório {report.get('report_date') or 'data N/D'} · técnica atual até {a['df'].index[-1].date()}")
        import_status=st.session_state.get('report_import_status')
        if import_status=='first':
            st.success('Primeiro relatório desta ação guardado. Nas próximas vezes, a app compara automaticamente a data.')
        elif import_status=='newer':
            st.success('Relatório mais recente detetado e guardado. A versão anterior deixou de ser usada na análise atual.')
        elif import_status=='replaced_same_date':
            st.info('Foi carregada uma versão diferente com a mesma data; a versão acabada de selecionar passou a ser a referência.')
        elif import_status in ['older','undated_older']:
            uploaded=(rr.get('uploaded_report') or {})
            st.warning(f"O PDF selecionado ({uploaded.get('report_date') or 'data N/D'}) é mais antigo do que o relatório guardado ({report.get('report_date') or 'data N/D'}). A análise abaixo usa automaticamente o mais recente.")
        elif import_status=='same':
            st.caption('Este PDF já estava guardado; a parte técnica foi atualizada com os dados de mercado disponíveis.')
        elif import_status=='saved':
            st.caption('A usar o relatório mais recente guardado para esta ação; a parte técnica foi recalculada agora.')
        for w in report.get('warnings',[]) or []:
            st.warning('Verificação do PDF: '+w)

        action=dec['action']
        reasons=_report_summary_reasons(a,report,dec)
        _asset_card(a['xtb_ticker'],report.get('company') or a['company'],action,dec.get('overall'),reasons,float(a['row']['Close']),a['currency'],('Já em carteira' if holding else 'Ainda não registada na carteira'))

        if holding:
            st.success(f"**Decisão para a posição atual: {action}** · qualidade/cobertura da análise {dec['confidence_label']} ({dec['confidence']:.0f}%).")
        else:
            st.info(f"**Decisão para nova entrada: {action}** · qualidade/cobertura da análise {dec['confidence_label']} ({dec['confidence']:.0f}%).")

        st.caption('A percentagem acima mede cobertura/qualidade dos dados usados; não é probabilidade de retorno nem de acerto da decisão.')

        k1,k2,k3,k4=st.columns(4)
        k1.metric('Fundamental',_fmt_num(dec.get('fundamental'),0,'/100'))
        k2.metric('Avaliação',_fmt_num(dec.get('valuation'),0,'/100'))
        k3.metric('Técnica atual',_fmt_num(dec.get('technical'),0,'/100'))
        k4.metric('Analistas',_fmt_num(dec.get('analysts'),0,'/100'))

        st.markdown('### Resumo')
        for reason in reasons:
            st.write('• '+reason)
        current=float(a['row']['Close'])
        fair=_safe_float(report.get('fair_value')); target=_safe_float(report.get('analyst_avg'))
        if fair:
            st.write(f"• Fair Value do PDF: **{fair:.2f} {a['currency']}** ({(fair/current-1)*100:+.1f}% vs preço atual da análise).")
        if target:
            st.write(f"• Alvo médio de analistas no PDF: **{target:.2f} {a['currency']}** ({(target/current-1)*100:+.1f}% vs preço atual da análise).")
        st.write(f"• Zona técnica potencial: **{zone['low']:.2f}-{zone['high']:.2f} {a['currency']}** · {zone['status']}.")

        if action in ['AGUARDAR','MANTER']:
            st.markdown('**O que faria melhorar a decisão**')
            st.write('Melhoria do timing técnico e/ou maior margem de segurança na avaliação, mantendo crescimento, margens e balanço sólidos.')
        elif action=='COMPRAR':
            st.markdown('**O que invalidaria a compra**')
            st.write('Deterioração material dos fundamentais, quebra da tendência de longo prazo ou perda da margem de segurança que sustentou a entrada.')
        elif 'VENDER' in action or 'REDUZIR' in action:
            st.markdown('**Porque a decisão é defensiva**')
            st.write('A regra exige deterioração suficientemente forte dos fundamentais e/ou da técnica; não vende apenas porque o preço caiu.')

        tf,ta,tt,tr,td=st.tabs(['Fundamentais','Avaliação','Técnica','Riscos & catalisadores','Dados do PDF'])
        with tf:
            st.markdown('#### Leitura fundamental')
            f1,f2,f3=st.columns(3)
            f1.metric('Qualidade',f"{a['fund_label']} · {_fmt_num(a.get('fund_score'),0,'/100')}")
            f2.metric('Cobertura',_fmt_num(a.get('fund_complete'),0,'%'))
            pro_ratings=[_safe_float(report.get(k)) for k in ['growth_rating','profitability_rating','cashflow_rating']]
            pro_ratings=[x for x in pro_ratings if x is not None]
            f3.metric('Média ratings Pro',_fmt_num(float(np.mean(pro_ratings)) if pro_ratings else None,1,'/10'))
            metrics=pd.DataFrame([
                ['Crescimento receitas',report.get('revenue_growth_pct'),'%',6],
                ['CAGR receitas 5A',report.get('revenue_cagr_5y_pct'),'%',6],
                ['Crescimento lucro líquido',report.get('net_income_growth_pct'),'%',6],
                ['CAGR receitas previsto 5A',report.get('revenue_forecast_cagr_5y_pct'),'%',6],
                ['ROE',report.get('roe_pct'),'%',6],
                ['Margem bruta',report.get('gross_margin_pct'),'%',6],
                ['Margem operacional',report.get('operating_margin_pct'),'%',1],
                ['Margem líquida LTM',report.get('profit_margin_pct'),'%',4],
            ],columns=['Métrica','Valor','Unidade','Página'])
            st.dataframe(metrics.dropna(subset=['Valor']),hide_index=True,use_container_width=True)
            with st.expander('Critérios do score fundamental'):
                st.dataframe(a['fund_table'],hide_index=True,use_container_width=True)

        with ta:
            st.markdown('#### Avaliação')
            av1,av2,av3=st.columns(3)
            av1.metric('P/E',_fmt_num(report.get('pe'),1,'x'))
            av2.metric('Forward P/E',_fmt_num(report.get('forward_pe'),1,'x'))
            av3.metric('EV/EBITDA',_fmt_num(report.get('ev_ebitda'),1,'x'))
            av4,av5,av6=st.columns(3)
            av4.metric('PEG',_fmt_num(report.get('peg'),2,'x'))
            av5.metric('FCF Yield',_fmt_num(report.get('fcf_yield'),2,'%'))
            av6.metric('Fair Value',f"{fair:.2f} {a['currency']}" if fair else 'N/D')
            if dec.get('valuation_parts'):
                st.caption('Componentes do score: '+ ' · '.join(f'{n} {v:.0f}/100' for n,v in dec['valuation_parts']))
            if val.get('available'):
                v1,v2,v3=st.columns(3)
                v1.metric('Cenário conservador',f"{val['conservative']:.2f} {a['currency']}")
                v2.metric('Cenário base',f"{val['base']:.2f} {a['currency']}")
                v3.metric('Cenário otimista',f"{val['optimistic']:.2f} {a['currency']}")
                st.caption(val['method'])

        with tt:
            st.markdown('#### Técnica atual - recalculada pela app')
            short_action,short_score=_short_action(a,holding=holding)
            _asset_card(a['xtb_ticker'],a['company'],short_action,short_score,_short_evidence(a),float(a['row']['Close']),a['currency'],'Dados atuais da fonte de mercado')
            t1,t2,t3,t4=st.columns(4)
            t1.metric('RSI',_fmt_num(float(a['row']['RSI14']),1))
            t2.metric('Retorno 20d',_fmt_num(float(a['row']['RET20']),1,'%'))
            t3.metric('Retorno 60d',_fmt_num(float(a['row']['RET60']),1,'%'))
            t4.metric('PDF na data',_pdf_technical_pt(report.get('pdf_technical')))
            st.caption('A técnica do PDF é apenas referência histórica. A decisão usa a técnica recalculada com preços atuais.')

        with tr:
            st.caption('Leitura automática em português. Números, percentagens e siglas financeiras são preservados; o texto original fica disponível para conferência.')
            st.markdown('#### Pontos positivos do relatório')
            positives=report.get('positive_points') or []
            if positives:
                for x in positives: st.write('• '+_report_pt_text(x,'positive'))
                with st.expander('Ver texto original · pontos positivos'):
                    for x in positives: st.write('• '+x)
            else: st.write('Sem pontos positivos estruturados suficientes no texto extraído.')
            st.markdown('#### Riscos / pontos de atenção')
            risks=report.get('risk_points') or []
            if risks:
                for x in risks: st.write('• '+_report_pt_text(x,'risk'))
                with st.expander('Ver texto original · riscos'):
                    for x in risks: st.write('• '+x)
            else: st.write('Sem riscos estruturados suficientes no texto extraído.')

        with td:
            st.markdown('#### Dados estruturados extraídos')
            rows=[]
            labels={
                'report_date':'Data do relatório','report_price':'Preço no relatório','market_cap':'Capitalização','revenue':'Receitas','revenue_forecast':'Receitas previstas',
                'pe':'P/E','forward_pe':'Forward P/E','peg':'PEG','fcf_yield':'FCF Yield %','ev_ebitda':'EV/EBITDA','beta':'Beta 5A','fair_value':'Fair Value',
                'financial_health':'Financial Health /10','growth_rating':'Growth Rating /10','profitability_rating':'Profitability Rating /10','analyst_avg':'Alvo médio analistas',
                'analyst_low':'Alvo baixo','analyst_high':'Alvo alto','analyst_count':'Nº analistas','eps_revisions_up':'Revisões EPS ↑','eps_revisions_down':'Revisões EPS ↓',
            }
            for key,label in labels.items():
                if report.get(key) is not None:
                    rows.append({'Campo':label,'Valor':report.get(key)})
            st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
            st.caption(f"Cobertura automática do PDF: {report.get('coverage_pct',0):.0f}% · {report.get('pages',0)} páginas. O relatório pode conter dados de terceiros/IA e não é tratado como feed em tempo real.")

    else:
        st.info('Carrega um PDF InvestingPro e escolhe **Analisar relatório**.')


elif PAGE == 'Comparar':
    st.subheader('Comparador de ações')
    st.caption('Compara 2 a 4 ações lado a lado. Primeiro a conclusão; depois os números que a justificam.')

    # Carrega também o cache InvestingPro persistido, mas apenas quando o utilizador
    # entra no comparador; não volta a atrasar o arranque global da app.
    if persistence_enabled() and not st.session_state.get('_persistent_loaded'):
        with st.spinner('A carregar fontes complementares guardadas...'):
            load_persistent_state()

    with st.expander('📥 InvestingPro · fonte complementar (opcional)'):
        ip_db=st.session_state.get('investingpro_data',{}) or {}
        if ip_db:
            total_metrics=sum(len((r or {}).get('metrics') or {}) for r in ip_db.values())
            st.success(f'Dados InvestingPro guardados: {len(ip_db)} ticker(s) · {total_metrics} métricas reconhecidas.')
        else:
            st.info('Ainda não há dados InvestingPro importados. A app continua a funcionar apenas com Yahoo Finance.')
        st.caption('Exporta uma vista/tabela do InvestingPro em CSV ou Excel. A app usa estes dados só para preencher campos que estejam em falta na Yahoo.')
        ip_file=st.file_uploader('CSV ou Excel do InvestingPro',type=['csv','xlsx'],key='ip_upload')
        ip_hint=st.text_input('Ticker XTB se o ficheiro for de uma única empresa (opcional)',placeholder='Ex.: AMD.US',key='ip_ticker_hint')
        ib1,ib2=st.columns(2)
        with ib1:
            if st.button('Importar InvestingPro',use_container_width=True,key='ip_import',disabled=ip_file is None):
                try:
                    recs,recognized,sheets=parse_investingpro_file(ip_file,ip_hint)
                    if not recs or recognized<=0:
                        st.error('Não reconheci métricas úteis neste ficheiro. Tenta exportar uma tabela com ticker/símbolo e colunas como ROE, P/E, EV/EBITDA, crescimento, margens, FCF ou Fair Value.')
                    else:
                        total=merge_investingpro_records(recs)
                        st.session_state.pop('comparison_df',None)
                        st.session_state.pop('v14_analysis',None)
                        saved=save_persistent_state(show_error=False) if persistence_enabled() else False
                        msg=f'Importadas {recognized} métricas para {len(recs)} ticker(s). Total guardado: {total} ticker(s).'
                        if persistence_enabled():
                            msg += ' Guardado no Supabase.' if saved else ' Ficou nesta sessão; o Supabase não confirmou a gravação.'
                        st.success(msg)
                except Exception as e:
                    st.error(f'Não foi possível importar o ficheiro: {e}')
        with ib2:
            if st.button('Limpar dados InvestingPro',use_container_width=True,key='ip_clear',disabled=not bool(ip_db)):
                st.session_state.investingpro_data={}
                st.session_state.investingpro_import_meta={}
                st.session_state.pop('comparison_df',None)
                if persistence_enabled():
                    save_persistent_state(show_error=False)
                st.success('Dados InvestingPro removidos da app.')
                st.rerun()

    c1,c2=st.columns(2)
    with c1:
        cmp1=st.text_input('1 · Ticker XTB',value='AAPL.US',key='cmp_1',placeholder='Ex.: AAPL.US')
        cmp3=st.text_input('3 · Opcional',value='',key='cmp_3',placeholder='Ex.: GOOGL.US')
    with c2:
        cmp2=st.text_input('2 · Ticker XTB',value='MSFT.US',key='cmp_2',placeholder='Ex.: MSFT.US')
        cmp4=st.text_input('4 · Opcional',value='',key='cmp_4',placeholder='Ex.: NVDA.US')

    b1,b2=st.columns([2,1])
    with b1:
        run_compare=st.button('Comparar',type='primary',use_container_width=True,key='cmp_run')
    with b2:
        if st.button('Limpar resultado',use_container_width=True,key='cmp_clear'):
            st.session_state.pop('comparison_df',None)
            st.session_state.pop('comparison_time',None)
            st.rerun()

    if run_compare:
        tickers=[]
        for raw in [cmp1,cmp2,cmp3,cmp4]:
            t=str(raw or '').upper().strip()
            if t and t not in tickers:
                tickers.append(t)
        if len(tickers)<2:
            st.error('Indica pelo menos 2 tickers diferentes.')
        else:
            analyses=[]; errors=[]
            prog=st.progress(0,text='A comparar o essencial...')
            for i,t in enumerate(tickers,1):
                try:
                    a=analyze_asset(t,detailed=False)
                    if a['kind']!='Ação':
                        errors.append(f'{t}: é {a["kind"]}; este comparador está otimizado para ações.')
                    else:
                        analyses.append(a)
                        add_watchlist(a['xtb_ticker'])
                except Exception as e:
                    errors.append(f'{t}: {e}')
                prog.progress(i/max(len(tickers),1),text=f'{i}/{len(tickers)}')
            prog.empty()
            if len(analyses)>=2:
                st.session_state['comparison_df']=_comparison_rows(analyses)
                st.session_state['comparison_time']=datetime.now().strftime('%d/%m/%Y %H:%M')
            else:
                st.session_state.pop('comparison_df',None)
            if errors:
                with st.expander('Avisos da comparação'):
                    for e in errors: st.write('• '+e)

    cdf=st.session_state.get('comparison_df')
    if isinstance(cdf,pd.DataFrame) and not cdf.empty:
        sector_values=[str(x).strip() for x in cdf['Setor'].fillna('N/D').tolist()]
        known_sectors=[x for x in sector_values if x and x!='N/D']
        unique_known=set(known_sectors)
        same_sector=(len(unique_known)==1 and len(known_sectors)==len(sector_values))
        ctime=st.session_state.get('comparison_time')
        if ctime:
            st.caption(f'Comparação calculada em {ctime} · preços/dados podem ter atraso conforme a fonte.')
        if len(unique_known)>1:
            st.warning('As empresas são de setores diferentes. Qualidade continua ajustada ao setor, mas múltiplos de avaliação (P/E, P/B, EV/EBITDA) são apenas uma comparação indicativa entre as selecionadas.')
        elif len(known_sectors)<len(sector_values):
            st.info('A classificação setorial está incompleta para pelo menos uma empresa. A app não assume que isso significa setores diferentes; usa os restantes dados com cautela.')

        best_overall=_winner_ticker(cdf,'Score equilíbrio geral')
        best_quality=_winner_ticker(cdf,'Score qualidade')
        best_value=_winner_ticker(cdf,'Score avaliação comparada')
        best_entry=_winner_ticker(cdf,'Score entrada')
        best_profit=_winner_ticker(cdf,'Score rentabilidade comparada')
        best_analysts=_winner_ticker(cdf,'Score analistas comparado')

        st.markdown('### Conclusão rápida')
        if best_overall:
            br=cdf[cdf['Ticker']==best_overall].iloc[0]
            st.success(f"**Melhor equilíbrio no conjunto: {best_overall}** · qualidade {_fmt_num(br.get('Score qualidade'),0,'/100')} · entrada {_fmt_num(br.get('Score entrada'),0,'/100')} · avaliação comparada {_fmt_num(br.get('Score avaliação comparada'),0,'/100')}")
        q1,q2,q3=st.columns(3)
        with q1: _comparison_metric_card('🏆 Melhor qualidade',best_quality,'Score fundamental ajustado ao setor')
        with q2: _comparison_metric_card('💎 Avaliação mais atrativa',best_value,'Relativa apenas às ações comparadas')
        with q3: _comparison_metric_card('📈 Melhor entrada agora',best_entry,'Técnica, momentum, RSI e volume')
        q4,q5=st.columns(2)
        with q4: _comparison_metric_card('💰 Melhor rentabilidade',best_profit,'ROE + margens, quando disponíveis')
        with q5: _comparison_metric_card('👥 Maior potencial dos analistas',best_analysts,'Só conta quando existem ≥3 opiniões')

        st.markdown('### Lado a lado')
        overview=cdf[['Ticker','Empresa','Setor','Preço','Moeda','Score qualidade','Score avaliação comparada','Score entrada','Score equilíbrio geral','Curto prazo','Longo prazo']].copy()
        st.dataframe(overview,hide_index=True,use_container_width=True)

        tq,tv,te,ta,ts=st.tabs(['Qualidade','Avaliação','Entrada','Analistas','Fontes'])
        with tq:
            cols=['Ticker','Qualidade','Score qualidade','Dados fundamentais %','Crescimento receitas %','Crescimento lucros %','Margem operacional %','Margem líquida %','ROE %','FCF yield %','Dívida/Capital próprio %']
            st.dataframe(cdf[[c for c in cols if c in cdf.columns]],hide_index=True,use_container_width=True)
            st.caption('A qualidade usa critérios ajustados ao setor. Dívida não é tratada da mesma forma numa financeira e numa tecnológica.')
        with tv:
            cols=['Ticker','Score avaliação comparada','P/E','Forward P/E','P/B','EV/EBITDA','FCF yield %','Fair Value InvestingPro','Potencial Fair Value %','Saúde financeira InvestingPro']
            st.dataframe(cdf[[c for c in cols if c in cdf.columns]],hide_index=True,use_container_width=True)
            st.caption('“Mais barata” aqui significa melhor avaliação relativa entre as selecionadas. Fair Value e Saúde financeira só aparecem quando foram importados do InvestingPro; não substituem a análise da app.')
        with te:
            cols=['Ticker','Técnica','Score técnico','RSI','Retorno 20d %','Retorno 60d %','Curto prazo','Score entrada']
            st.dataframe(cdf[[c for c in cols if c in cdf.columns]],hide_index=True,use_container_width=True)
            for _,r in cdf.iterrows():
                a=r['_analysis']
                _asset_card(r['Ticker'],r['Empresa'],r['Curto prazo'],r['Score entrada'],_short_evidence(a),r['Preço'],r['Moeda'],r['Setor'])
        with ta:
            cols=['Ticker','Recomendação analistas','Alvo médio analistas','Potencial analistas %','Nº analistas']
            st.dataframe(cdf[[c for c in cols if c in cdf.columns]],hide_index=True,use_container_width=True)
            st.caption('O consenso dos analistas é informação externa e pode mudar; não substitui a análise fundamental nem garante retorno.')
        with ts:
            cols=['Ticker','Fonte qualidade','Fonte avaliação','Fonte ROE','Fonte FCF','Fonte P/E','Fonte Forward P/E','Fonte P/B','Fonte EV/EBITDA','Fonte analistas']
            st.dataframe(cdf[[c for c in cols if c in cdf.columns]],hide_index=True,use_container_width=True)
            st.caption('Yahoo é a fonte principal. InvestingPro só preenche campos ausentes; a app não substitui silenciosamente um valor Yahoo existente.')

        st.markdown('### Veredito por ação')
        for _,r in cdf.sort_values('Score equilíbrio geral',ascending=False,na_position='last').iterrows():
            a=r['_analysis']
            evidence=[
                f"Qualidade {r.get('Qualidade','N/D')} · {_fmt_num(r.get('Score qualidade'),0,'/100')}",
                f"Avaliação comparada {_fmt_num(r.get('Score avaliação comparada'),0,'/100')} · entrada {_fmt_num(r.get('Score entrada'),0,'/100')}",
                f"Longo prazo: {r.get('Longo prazo','N/D')}",
            ]
            _asset_card(r['Ticker'],r['Empresa'],f"EQUILÍBRIO { _fmt_num(r.get('Score equilíbrio geral'),0,'/100') }",r.get('Score equilíbrio geral'),evidence,r['Preço'],r['Moeda'],r['Setor'])
    else:
        st.info('Escolhe 2 a 4 ações e carrega em **Comparar**.')

elif PAGE == 'Analisar':
    st.subheader('Analisar ação, ETF, ETN ou CFD')
    st.caption('Primeiro uma resposta rápida. Para CFD podes indicar o ticker do subjacente/fonte; custos do contrato não são inferidos.')
    t1,t2,t3=st.columns([2,1,1])
    with t1:
        ticker=st.text_input('Ticker XTB',value='AAPL.US',key='v14_an_ticker').upper().strip()
    with t2:
        market_hint=st.selectbox('Mercado (opcional)',['Auto']+list(MARKETS.keys()),key='v14_an_market')
    with t3:
        instrument_hint=st.selectbox('Tipo',INSTRUMENT_TYPES,index=0,key='v24_an_type')
    source_hint=st.text_input('Ticker técnico/subjacente (opcional)',value='',key='v24_an_source',placeholder='Ex.: ^NDX, GC=F ou NVDA')
    if st.button('Analisar agora',type='primary',use_container_width=True,key='v14_an_run'):
        if persistence_enabled() and not st.session_state.get('_persistent_loaded'):
            load_persistent_state()
        try:
            with st.spinner('A analisar o essencial...'):
                a=analyze_asset(ticker,None if market_hint=='Auto' else market_hint,detailed=False,instrument_type=instrument_hint,source_override=(source_hint.upper().strip() or None))
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

        val=valuation_scenarios(a)
        zone=entry_zone(a,val)
        st.markdown('### Entrada e avaliação')
        z1,z2=st.columns(2)
        z1.metric('Zona técnica potencial',f"{zone['low']:.2f}–{zone['high']:.2f} {a['currency']}")
        z2.metric('Leitura',zone['status'])
        st.caption(f"Referência de suporte mais profunda: {zone['deep']:.2f} {a['currency']}. Zona baseada em EMA/ATR; não é uma ordem de compra.")
        if val.get('available'):
            v1,v2,v3=st.columns(3)
            v1.metric('Conservador',f"{val['conservative']:.2f} {a['currency']}")
            v2.metric('Base',f"{val['base']:.2f} {a['currency']}",f"{val.get('upside_pct',0):+.1f}% vs preço")
            v3.metric('Otimista',f"{val['optimistic']:.2f} {a['currency']}")
            st.caption(f"Confiança {val['confidence']} · {val['sources']} · {val['method']}")
        elif a.get('kind') in ['Ação','CFD']:
            st.caption(val.get('reason','Sem cenário de avaliação disponível.'))

        if st.button('Ver alvos, prazo e histórico',use_container_width=True,key='v14_an_detail'):
            try:
                with st.spinner('A calcular histórico desta ação...'):
                    detailed=analyze_asset(a['xtb_ticker'],detailed=True,instrument_type=a.get('kind','Auto'),source_override=a.get('source_ticker'))
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
- **Longo prazo**: meses/anos. Dá prioridade a qualidade fundamental/ETF/ETN e qualidade dos dados. CFD é tratado separadamente como derivado.
- Cada cartão mostra no máximo **3 evidências** para explicar a conclusão.
- **AGUARDAR** é uma decisão válida; a app não força uma compra.
- **Alvo técnico (2× risco)** não é um valor justo fundamental.
- Prazo e cenários são comparações históricas, não previsões.
- **Fontes**: Yahoo Finance é a fonte principal; dados InvestingPro importados servem apenas de fallback para campos em falta e aparecem identificados.
- **Relatório**: o PDF alimenta a análise fundamental/avaliação; a técnica é recalculada com dados atuais e a app mostra uma decisão resumida no topo.
- Confirma preço, spread, sessão e informação oficial antes de executar uma ordem.
''')
