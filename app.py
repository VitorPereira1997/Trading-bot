import math
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title='Analisador de Mercados', page_icon='📊', layout='wide')
st.title('📊 Analisador de Mercados')
st.caption('Análise técnica + fundamental com dados identificados. Não envia ordens reais.')

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
    ident=instrument_identity(ticker, market_hint)
    source=ident['source_ticker']
    try:
        probe=yf.download(source, period='1mo', interval='1d', auto_adjust=True, progress=False, threads=False)
    except Exception as e:
        raise ValueError(f"Não foi possível validar {ident['xtb_ticker']} na fonte técnica ({source}).") from e
    if probe is None or probe.empty:
        raise ValueError(
            f"Ticker XTB reconhecido como {ident['xtb_ticker']}, mas a fonte técnica não tem dados para {source}. "
            "A app não substitui automaticamente por outra bolsa/moeda."
        )
    return ident

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = []

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
    df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    if df.empty:
        raise ValueError(f'Sem dados de mercado para {ticker}.')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna().copy()

@st.cache_data(ttl=1800)
def asset_info(ticker):
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

def fundamental_equity(info):
    # Critérios transparentes; dados em falta não contam como aprovados nem reprovados.
    specs = [
        ('Crescimento receitas > 0', 'revenueGrowth', lambda x: x > 0),
        ('Crescimento lucros > 0', 'earningsGrowth', lambda x: x > 0),
        ('Margem operacional > 10%', 'operatingMargins', lambda x: x > 0.10),
        ('Margem líquida > 8%', 'profitMargins', lambda x: x > 0.08),
        ('ROE > 10%', 'returnOnEquity', lambda x: x > 0.10),
        ('Fluxo de caixa livre positivo', 'freeCashflow', lambda x: x > 0),
        ('Caixa operacional positivo', 'operatingCashflow', lambda x: x > 0),
        ('Dívida/Capital próprio < 150%', 'debtToEquity', lambda x: x < 150),
    ]
    rows=[]
    passed=0
    available=0
    for name,key,fn in specs:
        v=_num(info,key)
        ok=None if v is None else bool(fn(v))
        if v is not None:
            available += 1
            passed += int(ok)
        rows.append({'Critério':name,'Valor':v,'Cumpre':('Sim' if ok else 'Não') if ok is not None else 'N/D'})
    completeness = available/len(specs)*100
    ratio = passed/available if available else 0
    label = 'Dados insuficientes' if available < 5 else ('Forte' if ratio >= 0.70 else ('Neutro' if ratio >= 0.45 else 'Fraco'))
    return label, round(ratio*100,1) if available else None, round(completeness,1), pd.DataFrame(rows)

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

def analyze_asset(ticker, market_hint=None):
    ident=resolve_instrument(ticker, market_hint)
    source=ident['source_ticker']
    raw=price_data(source,'5y','1d')
    d=indicators(raw).dropna()
    if len(d) < 210:
        raise ValueError('Histórico insuficiente para análise técnica robusta.')
    row=d.iloc[-1]
    tech_score, tech_label, tech_tests=technical_score(row)
    info,kind,fund_label,fund_score,complete,fund_table=fundamental_analysis(source)
    entry,stop,target=entry_levels(row)
    scenarios=historical_scenarios(raw,row)
    target_time=target_time_stats(raw,row,target,max_days=60)
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
    a=analyze_asset(ticker)
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
    a=analyze_asset(ticker)
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

TABS = st.tabs(['Plano de hoje','Analisar ativo','Setores','Minha carteira','Top 10','Desempenho','Metodologia'])

with TABS[0]:
    st.subheader('Quero usar capital hoje')
    st.write('A app só sugere entrada quando a análise técnica e a análise fundamental/qualidade do ETF são fortes. Caso contrário, devolve **AGUARDAR**.')
    c1,c2,c3,c4=st.columns(4)
    with c1: available=st.number_input('Capital disponível hoje (€)',min_value=0.0,value=400.0,step=50.0)
    with c2: max_loss_trade=st.number_input('Perda máxima por operação (€)',min_value=0.0,value=0.0,step=1.0)
    with c3: max_loss_day=st.number_input('Perda máxima no dia (€)',min_value=0.0,value=0.0,step=1.0)
    with c4: markets_today=st.multiselect('Mercados',list(MARKETS.keys()),default=['EUA','Alemanha','Portugal'])
    include_type=st.multiselect('Tipos', ['Ação','ETF'], default=['Ação','ETF'])
    if st.button('Analisar oportunidades de hoje',type='primary'):
        if max_loss_trade <= 0 or max_loss_day <= 0:
            st.error('Para dimensionar uma posição pessoal, define primeiro a perda máxima por operação e por dia.')
        elif not markets_today:
            st.error('Escolhe pelo menos um mercado.')
        else:
            candidates=[]
            with st.spinner('A analisar técnica, fundamentais e qualidade dos dados...'):
                for t in universe_for(markets_today)[:100]:
                    try:
                        c=compact_candidate(t)
                        if c['Tipo'] in include_type:
                            candidates.append(c)
                    except Exception:
                        pass
            if not candidates:
                st.warning('Não foi possível obter dados suficientes.')
            else:
                df=pd.DataFrame([{k:v for k,v in x.items() if k!='_analysis'} for x in candidates])
                valid=df[(df['Decisão']=='CANDIDATO A ENTRADA') & (df['Completude %']>=60)].copy()
                valid=valid.sort_values(['Score técnico','Completude %'],ascending=False)
                st.write(f'Regime geral de referência (SPY): **{market_regime()}**')
                if valid.empty:
                    st.warning('AGUARDAR — nenhum ativo analisado passou simultaneamente os filtros técnico e fundamental/ETF definidos.')
                else:
                    best=valid.iloc[0]
                    a=next(x['_analysis'] for x in candidates if x['Ticker XTB']==best['Ticker XTB'])
                    currency=a['currency'] if a['currency']!='N/D' else 'EUR'
                    entry_eur=to_eur(a['entry'],currency)
                    stop_eur=to_eur(a['stop'],currency)
                    if entry_eur is None or stop_eur is None:
                        st.warning('Existe candidato, mas não há conversão cambial suficiente para dimensionar em euros.')
                    else:
                        risk_per_unit=max(entry_eur-stop_eur,0.01)
                        risk_budget=min(max_loss_trade,max_loss_day)
                        qty_risk=math.floor(risk_budget/risk_per_unit)
                        qty_capital=math.floor(available/entry_eur)
                        qty=max(0,min(qty_risk,qty_capital))
                        if qty < 1:
                            st.warning(f"AGUARDAR — {best['Ticker XTB']} passou os filtros, mas uma unidade inteira não cabe simultaneamente no capital e no risco definidos.")
                        else:
                            invested=qty*entry_eur
                            potential_loss=qty*risk_per_unit
                            target_eur=to_eur(a['target'],currency)
                            potential_gain=(target_eur-entry_eur)*qty if target_eur is not None else None
                            st.success(f"CANDIDATO: {best['Ticker XTB']} ({best['Tipo']})")
                            x1,x2,x3,x4=st.columns(4)
                            x1.metric('Valor a usar',f'€{invested:.2f}')
                            x2.metric('Quantidade',str(qty))
                            x3.metric('Perda planeada',f'€{potential_loss:.2f}')
                            x4.metric('Ganho no alvo técnico (2× o risco)',f'€{potential_gain:.2f}' if potential_gain is not None else 'N/D')
                            st.write(f"Entrada ref.: **{a['entry']:.2f} {currency}** · Stop: **{a['stop']:.2f}** · Alvo técnico (2× o risco): **{a['target']:.2f}**")
                            st.write(f"Técnica: **{a['tech_label']} ({a['tech_score']}/100)** · Fundamental/ETF: **{a['fund_label']}** · Completude: **{a['fund_complete']}%**")
                            if not a['scenarios'].empty:
                                st.markdown('**Cenários históricos comparáveis — não são previsões:**')
                                st.dataframe(a['scenarios'],use_container_width=True,hide_index=True)
                            source_block(best['Ticker XTB'],a)
                st.markdown('**Candidatos analisados**')
                st.dataframe(df.drop(columns=[],errors='ignore').sort_values(['Decisão','Score técnico'],ascending=[True,False]).head(25),use_container_width=True,hide_index=True)

with TABS[1]:
    st.subheader('Analisar ação ou ETF')
    cta, ctb = st.columns([2,1])
    with cta:
        t=st.text_input('Ticker',value='AAPL.US',key='single').upper().strip()
    with ctb:
        market_hint=st.selectbox('Mercado (opcional)', ['Auto']+list(MARKETS.keys()), index=0, key='single_market')
    if st.button('Analisar',type='primary',key='single_btn'):
        try:
            a=analyze_asset(t, None if market_hint=='Auto' else market_hint)
            add_watchlist(a['xtb_ticker'])
            dec=decision(a)
            st.success(f'{dec} · {a["kind"]}') if dec!='AGUARDAR' else st.warning(f'{dec} · {a["kind"]}')
            st.write(f"Ticker XTB: **{a['xtb_ticker']}** · Empresa: **{a['company']}** · Mercado: **{a['market']}** · Moeda: **{a['currency']}** · Ticker técnico: **{a['source_ticker']}**")
            m1,m2,m3,m4=st.columns(4)
            m1.metric('Preço',f'{a["entry"]:.2f}')
            m2.metric('Stop técnico',f'{a["stop"]:.2f}')
            m3.metric('Alvo técnico (2× o risco)',f'{a["target"]:.2f}')
            m4.metric('Score técnico',f'{a["tech_score"]}/100')

            tt=a.get('target_time',{})
            t1,t2,t3=st.columns(3)
            if tt.get('median_days') is not None:
                t1.metric('Tempo histórico mediano até ao alvo',f"{tt['median_days']:.1f} dias de mercado")
            else:
                t1.metric('Tempo histórico mediano até ao alvo','Dados insuficientes')
            t2.metric('Casos que atingiram o alvo em até 60 dias',f"{tt['hit_rate']:.1f}%" if tt.get('hit_rate') is not None else 'Dados insuficientes')
            t3.metric('Amostras históricas semelhantes',str(tt.get('samples',0)))
            st.caption('Tempo até ao alvo = mediana dos casos históricos tecnicamente semelhantes que tocaram um movimento percentual equivalente ao alvo técnico (2× o risco) atual. Usa o máximo diário e um horizonte de 60 dias de mercado; não é uma previsão.')

            st.write(f"Técnica: **{a['tech_label']}** · Fundamental/qualidade ETF: **{a['fund_label']}** · Dados fundamentais disponíveis: **{a['fund_complete']}%**")
            st.markdown('**Critérios técnicos**')
            st.dataframe(pd.DataFrame([{'Critério':k,'Cumpre':'Sim' if v else 'Não'} for k,v in a['tech_tests'].items()]),hide_index=True,use_container_width=True)
            st.markdown('**Critérios fundamentais / ETF**')
            st.dataframe(a['fund_table'],hide_index=True,use_container_width=True)
            if not a['scenarios'].empty:
                st.markdown('**Cenários históricos comparáveis (5/10/15/30 dias)**')
                st.dataframe(a['scenarios'],hide_index=True,use_container_width=True)
                st.caption('O nível mediano histórico é calculado a partir de situações técnicas passadas semelhantes. Não é um preço-alvo previsto.')
            else:
                st.info('Não existem observações históricas comparáveis suficientes para gerar cenários 5/10/15/30 dias.')
            st.line_chart(a['df'][['Close','EMA20','EMA50','EMA200']].tail(260))
            source_block(t,a)
            st.info('A ação foi adicionada à watchlist desta sessão.')
        except Exception as e:
            st.error(str(e))

with TABS[2]:
    st.subheader('Análise por setor')
    st.write(
        'Esta área compara setores e empresas com dois horizontes separados: **curto prazo (aprox. 5–30 dias de mercado)** '
        'e **longo prazo (aprox. 6–24 meses)**. O ranking não é uma garantia de retorno.'
    )
    s1,s2=st.columns([2,1])
    with s1:
        sector_markets=st.multiselect('Mercados para análise setorial',list(MARKETS.keys()),default=['EUA','Alemanha','Portugal'],key='sector_markets')
    with s2:
        max_sector_assets=st.slider('Máximo de ativos a analisar',20,140,80,10,key='sector_max')
    include_watch=st.checkbox('Incluir watchlist',value=True,key='sector_watch')

    if st.button('Gerar análise setorial',type='primary',key='sector_generate'):
        tickers=[]
        for m in sector_markets:
            tickers += MARKETS[m]
        if include_watch:
            tickers += st.session_state.watchlist
        tickers=list(dict.fromkeys(tickers))[:max_sector_assets]
        rows=[]
        prog=st.progress(0,text='A recolher dados por setor...')
        for n,ticker in enumerate(tickers, start=1):
            try:
                row=sector_asset_row(ticker)
                if row['Tipo']=='Ação':
                    rows.append(row)
            except Exception:
                pass
            prog.progress(n/max(len(tickers),1),text=f'A analisar {n}/{len(tickers)}')
        prog.empty()
        if rows:
            sdf=add_sector_relative_scores(pd.DataFrame(rows))
            st.session_state['sector_df']=sdf
            st.session_state['sector_summary']=sector_summary(sdf)
        else:
            st.session_state['sector_df']=pd.DataFrame()
            st.session_state['sector_summary']=pd.DataFrame()

    sdf=st.session_state.get('sector_df',pd.DataFrame())
    ssum=st.session_state.get('sector_summary',pd.DataFrame())
    if not ssum.empty:
        st.markdown('### Visão geral dos setores')
        st.dataframe(ssum,use_container_width=True,hide_index=True)
        st.caption('“Peso no universo analisado” usa apenas a capitalização das empresas carregadas pela app; não é o peso oficial do setor num índice.')

        sectors=sorted([x for x in sdf['Setor'].dropna().unique().tolist() if x!='N/D'])
        chosen=st.selectbox('Ver ranking de um setor',['Todos']+sectors,key='sector_choice')
        view=sdf.copy() if chosen=='Todos' else sdf[sdf['Setor']==chosen].copy()
        if view.empty:
            st.info('Sem ativos suficientes neste setor.')
        else:
            cshort,clong=st.columns(2)
            with cshort:
                st.markdown('### Top 10 — curto prazo')
                short=view.sort_values(['Score curto prazo','Score técnico'],ascending=False,na_position='last').head(10)
                st.dataframe(short[[
                    'Ticker XTB','Empresa','Mercado','Setor','Score curto prazo','Score técnico','Técnica',
                    'Retorno 1M %','Retorno 3M %','RSI','Volume relativo','Passa filtros integrados','Data ref.'
                ]],use_container_width=True,hide_index=True)
                st.caption('Curto prazo privilegia tendência técnica, momentum recente e volume. O filtro integrado só marca “Sim” quando técnica e fundamentais também são fortes e os dados são suficientes.')
            with clong:
                st.markdown('### Top 10 — longo prazo')
                long=view.sort_values(['Score longo prazo','Score fundamental'],ascending=False,na_position='last').head(10)
                st.dataframe(long[[
                    'Ticker XTB','Empresa','Mercado','Setor','Score longo prazo','Score fundamental','Fundamental/ETF',
                    'Score avaliação relativa','Retorno 12M %','P/E','Forward P/E','FCF yield %',
                    'Crescimento receitas %','ROE %','Completude fundamental %','Passa filtros integrados','Data ref.'
                ]],use_container_width=True,hide_index=True)
                st.caption('Longo prazo combina qualidade fundamental, avaliação relativa ao próprio setor, tendência de 12 meses e completude dos dados. Avaliação relativa não é um preço-alvo.')

            st.markdown('### Dados completos do setor selecionado')
            st.dataframe(view.sort_values('Score longo prazo',ascending=False,na_position='last'),use_container_width=True,hide_index=True)
    else:
        st.info('Gera a análise para ver os setores e os rankings de curto e longo prazo.')

with TABS[3]:
    st.subheader('Minha carteira')
    st.caption('Introduz preço médio e preço alvo definidos por ti. A app calcula dados atuais e cenários históricos sem inventar um alvo.')
    initial=pd.DataFrame([{'Ticker XTB':'AAPL.US','Quantidade':1.0,'Preço médio':180.0,'Preço alvo':210.0}])
    portfolio=st.data_editor(
        initial,num_rows='dynamic',hide_index=True,use_container_width=True,
        column_config={'Ticker XTB': st.column_config.TextColumn('Ticker XTB', help='Ex.: AAPL.US, ASML.NL, FB2A.DE, EDP.PT')}
    )
    if st.button('Avaliar carteira',type='primary'):
        rows=[]
        for _,r in portfolio.iterrows():
            t=str(r.get('Ticker XTB','')).upper().strip(); q=float(r.get('Quantidade',0) or 0); pm=float(r.get('Preço médio',0) or 0); pa=float(r.get('Preço alvo',0) or 0)
            if not t or q<=0 or pm<=0 or pa<=0: continue
            try:
                a=analyze_asset(t); add_watchlist(a['xtb_ticker'])
                price=float(a['row']['Close']); cur=a['currency']
                rows.append({'Ticker XTB':a['xtb_ticker'],'Ticker técnico':a['source_ticker'],'Empresa':a['company'],'Mercado':a['market'],'Bolsa':a['exchange'],'Tipo':a['kind'],'Moeda':cur,'Preço atual':price,'Quantidade':q,'Preço médio':pm,'P/L %':(price/pm-1)*100,'Preço alvo':pa,'Distância ao alvo %':(pa/price-1)*100,'Técnica':a['tech_label'],'Fundamental/ETF':a['fund_label'],'Decisão':decision(a)})
            except Exception as e:
                rows.append({'Ticker':t,'Erro':str(e)})
        if rows: st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)

with TABS[4]:
    st.subheader('Top 10 por mercado ou global')
    markets=st.multiselect('Mercados a comparar',list(MARKETS.keys()),default=['EUA','Alemanha','Portugal'],key='topmarkets')
    if st.session_state.watchlist:
        st.info('Watchlist desta sessão: '+', '.join(st.session_state.watchlist))
    if st.button('Gerar Top 10',type='primary'):
        rows=[]
        with st.spinner('A analisar...'):
            for t in universe_for(markets)[:120]:
                try:
                    c=compact_candidate(t)
                    c.pop('_analysis',None)
                    c['Na watchlist']='Sim' if c['Ticker XTB'] in st.session_state.watchlist else 'Não'
                    rows.append(c)
                except Exception:
                    pass
        if rows:
            df=pd.DataFrame(rows).sort_values(['Score técnico','Completude %'],ascending=False)
            st.dataframe(df.head(10),use_container_width=True,hide_index=True)
            st.caption('A ordenação usa apenas métricas calculadas. “CANDIDATO A ENTRADA” exige técnica forte + fundamental/ETF forte + dados suficientes.')
        else: st.warning('Sem dados suficientes.')

with TABS[5]:
    st.subheader('Desempenho histórico da regra técnica')
    bt=st.text_input('Ticker para backtest',value='AAPL.US').upper().strip()
    b1,b2,b3=st.columns(3)
    with b1: score_min=st.slider('Score técnico mínimo',50,100,75,5)
    with b2: max_days=st.slider('Máximo dias em posição',5,60,20,5)
    with b3: costs=st.number_input('Custos ida+volta por lado (bps)',min_value=0,value=10,step=1)
    if st.button('Executar backtest',type='primary'):
        try:
            tr=backtest(bt,score_min,max_days,costs)
            if tr.empty: st.warning('Sem operações suficientes.')
            else:
                win=(tr['Resultado %']>0).mean()*100
                avgwin=tr.loc[tr['Resultado %']>0,'Resultado %'].mean()
                avgloss=tr.loc[tr['Resultado %']<=0,'Resultado %'].mean()
                expectancy=tr['Resultado %'].mean()
                equity=(1+tr['Resultado %']/100).cumprod()
                dd=(equity/equity.cummax()-1)*100
                c1,c2,c3,c4=st.columns(4)
                c1.metric('Operações',len(tr)); c2.metric('Taxa sucesso',f'{win:.1f}%'); c3.metric('Expectativa média',f'{expectancy:.2f}%'); c4.metric('Drawdown máx.',f'{dd.min():.2f}%')
                st.write(f'Ganho médio: **{avgwin:.2f}%** · Perda média: **{avgloss:.2f}%** · Tempo médio: **{tr["Dias"].mean():.1f} dias de mercado**')
                st.line_chart(pd.DataFrame({'Capital relativo':equity.values},index=tr['Saída']))
                st.dataframe(tr.tail(100),hide_index=True,use_container_width=True)
                st.caption('Backtest técnico, não inclui análise fundamental histórica ponto-a-ponto. Custos são os valores introduzidos acima.')
        except Exception as e: st.error(str(e))

with TABS[6]:
    st.subheader('Metodologia e regras de integridade dos dados')
    st.markdown('''
- **Nenhum número é preenchido por suposição.** Se o fornecedor não disponibilizar um campo, aparece `N/D` ou “dados insuficientes”.
- **Técnica e fundamental são separadas.** Uma entrada só passa a regra quando ambos os blocos são fortes e a completude fundamental/ETF é suficiente.
- **Cenários de 5/10/15/30 dias** usam retornos observados em estados técnicos históricos semelhantes. São estatísticas condicionais, não previsões.
- **Preço, stop e alvo técnico (2× o risco)** são calculados a partir do último fecho e ATR; a fórmula é reproduzível e visível.
- **Dimensionamento pessoal** só é feito quando o utilizador introduz capital, perda máxima por operação e perda máxima diária.
- **Ações acima do plafond não são ocultadas.** Podem aparecer no ranking; a app apenas impede dimensionamento incompatível com o capital/risco introduzido.
- **Mercados suportados:** EUA, Alemanha, Portugal, França, Países Baixos, Espanha, Itália, Reino Unido e Suíça, conforme disponibilidade do fornecedor.
- **Identidade do instrumento:** o ticker XTB é a chave principal (ex.: `AAPL.US`, `ASML.NL`, `FB2A.DE`, `EDP.PT`). O ticker técnico serve apenas para obter dados do fornecedor.
- **Sem substituição silenciosa de bolsa:** se a fonte técnica não tiver o instrumento correspondente, a app devolve erro em vez de trocar para outra praça/moeda.
- **Fonte atual de séries/fundamentais:** Yahoo Finance via `yfinance`. Para decisões reais, confirma preço, spread, sessão e documentos da empresa/ETF na XTB e nas relações com investidores/regulador.
- **Análise setorial:** agrega apenas os ativos efetivamente analisados. O peso setorial é relativo a esse universo, não a um índice oficial.
- **Curto prazo setorial:** score composto de técnica, momentum 1/3 meses e volume relativo; horizonte aproximado de 5–30 dias de mercado.
- **Longo prazo setorial:** combina qualidade fundamental, avaliação relativa dentro do setor, tendência de 12 meses e completude dos dados; horizonte aproximado de 6–24 meses.
- **Avaliação relativa:** P/E, Forward P/E, P/B, EV/EBITDA e FCF yield são comparados dentro do setor quando existem pelo menos quatro observações válidas; métricas em falta não são inventadas.
''')


# Nota de interface: "Alvo técnico (2× o risco)" é distinto de qualquer preço alvo fundamental.
