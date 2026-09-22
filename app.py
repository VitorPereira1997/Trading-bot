
import math
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from datetime import datetime, timezone

st.set_page_config(page_title="Robot Trading", page_icon="📈", layout="wide")
st.title("📈 Robot Trading")
st.caption("Análise e simulação. Não envia ordens reais.")

# Universo inicial: ações grandes e normalmente líquidas nos EUA.
DEFAULT_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","TSLA","JPM","V",
    "MA","LLY","WMT","COST","NFLX","AMD","ORCL","CRM","ADBE","QCOM",
    "INTC","MU","UBER","PLTR","BAC","GS","XOM","CVX","KO","PEP",
    "DIS","NKE","CAT","GE","IBM","NOW","AMAT","TXN","PANW","INTU"
]

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def preparar_indicadores(df):
    d = df.copy()
    d["EMA20"] = d["Close"].ewm(span=20, adjust=False).mean()
    d["EMA50"] = d["Close"].ewm(span=50, adjust=False).mean()
    d["EMA200"] = d["Close"].ewm(span=200, adjust=False).mean()
    d["RSI14"] = rsi(d["Close"], 14)
    d["ATR14"] = atr(d, 14)
    d["VOL20"] = d["Volume"].rolling(20).mean()
    d["RET20"] = d["Close"].pct_change(20) * 100
    d["RET60"] = d["Close"].pct_change(60) * 100
    d["HIGH252"] = d["High"].rolling(252, min_periods=60).max()
    d["LOW252"] = d["Low"].rolling(252, min_periods=60).min()
    d["DOLLAR_VOL20"] = (d["Close"] * d["Volume"]).rolling(20).mean()
    return d

@st.cache_data(ttl=300)
def obter_dados(ticker, period="2y", interval="1d"):
    df = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False
    )
    if df.empty:
        raise ValueError(f"Sem dados para {ticker}.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna().copy()

@st.cache_data(ttl=900)
def eurusd():
    try:
        fx = yf.download("EURUSD=X", period="5d", interval="1d", auto_adjust=True, progress=False, threads=False)
        if isinstance(fx.columns, pd.MultiIndex):
            fx.columns = fx.columns.get_level_values(0)
        # EURUSD = USD por EUR. USD->EUR = dividir por EURUSD.
        return float(fx["Close"].dropna().iloc[-1])
    except Exception:
        return None

def normalizar_score(x, low, high, invert=False):
    if pd.isna(x):
        return 0.0
    if high == low:
        return 0.0
    v = max(0.0, min(1.0, (x - low) / (high - low)))
    if invert:
        v = 1.0 - v
    return v * 100

def score_tecnico(row):
    # Pontuação técnica 0-100. Não é probabilidade.
    trend = 0
    if row["Close"] > row["EMA20"]:
        trend += 15
    if row["EMA20"] > row["EMA50"]:
        trend += 15
    if row["EMA50"] > row["EMA200"]:
        trend += 15

    rsi_val = float(row["RSI14"])
    if 50 <= rsi_val <= 65:
        rsi_score = 15
    elif 45 <= rsi_val < 50 or 65 < rsi_val <= 72:
        rsi_score = 8
    else:
        rsi_score = 2

    mom20 = normalizar_score(float(row["RET20"]), -10, 15) * 0.10
    mom60 = normalizar_score(float(row["RET60"]), -20, 30) * 0.10

    vol_ratio = float(row["Volume"] / row["VOL20"]) if row["VOL20"] > 0 else 0
    volume_score = normalizar_score(vol_ratio, 0.7, 2.0) * 0.10

    atr_pct = float(row["ATR14"] / row["Close"] * 100) if row["Close"] > 0 else np.nan
    # Preferência por volatilidade suficiente mas não extrema.
    if 1.0 <= atr_pct <= 4.5:
        atr_score = 10
    elif 0.5 <= atr_pct < 1.0 or 4.5 < atr_pct <= 7.0:
        atr_score = 5
    else:
        atr_score = 1

    total = trend + rsi_score + mom20 + mom60 + volume_score + atr_score
    return round(min(100.0, total), 1)

def distancia_52w(row):
    high = float(row["HIGH252"])
    low = float(row["LOW252"])
    close = float(row["Close"])
    if not np.isfinite(high) or not np.isfinite(low) or high <= low:
        return np.nan
    return (close - low) / (high - low) * 100

def risco_alvo(row):
    entrada = float(row["Close"])
    a = float(row["ATR14"])
    stop = entrada - 1.5 * a
    alvo = entrada + 2.0 * (entrada - stop)
    return entrada, stop, alvo

def classificar_liquidez(dollar_vol):
    if pd.isna(dollar_vol):
        return "N/D"
    if dollar_vol >= 1_000_000_000:
        return "Muito alta"
    if dollar_vol >= 250_000_000:
        return "Alta"
    if dollar_vol >= 50_000_000:
        return "Média"
    return "Baixa"

def analisar_universo(tickers, modo="proxima"):
    resultados = []
    fx = eurusd()

    for ticker in tickers:
        try:
            daily = preparar_indicadores(obter_dados(ticker, "2y", "1d")).dropna()
            if len(daily) < 210:
                continue

            row = daily.iloc[-1]
            preco_ref = float(row["Close"])
            data_ref = daily.index[-1]

            intraday_change = np.nan
            intraday_volume_ratio = np.nan
            intraday_time = None

            if modo == "hoje":
                try:
                    intra = obter_dados(ticker, "60d", "1h")
                    if len(intra) >= 20:
                        preco_ref = float(intra["Close"].iloc[-1])
                        data_ref = intra.index[-1]
                        intraday_time = str(data_ref)
                        if len(intra) >= 2:
                            intraday_change = (float(intra["Close"].iloc[-1]) / float(intra["Close"].iloc[-2]) - 1) * 100
                        vol20h = intra["Volume"].rolling(20).mean().iloc[-1]
                        if pd.notna(vol20h) and vol20h > 0:
                            intraday_volume_ratio = float(intra["Volume"].iloc[-1] / vol20h)
                except Exception:
                    pass

            entrada, stop, alvo = risco_alvo(row)

            # No modo hoje, usa o preço intradiário como entrada de referência,
            # mas mantém o ATR diário para níveis de risco mais estáveis.
            if modo == "hoje":
                entrada = preco_ref
                atr_abs = float(row["ATR14"])
                stop = entrada - 1.5 * atr_abs
                alvo = entrada + 2.0 * (entrada - stop)

            score = score_tecnico(row)
            if modo == "hoje" and pd.notna(intraday_change):
                # Ajuste pequeno, sem deixar 1h dominar o contexto diário.
                score += max(-5, min(5, intraday_change * 2))
                if pd.notna(intraday_volume_ratio):
                    score += max(-3, min(3, (intraday_volume_ratio - 1) * 2))
                score = round(max(0, min(100, score)), 1)

            price_eur = None
            acima_plafond = None
            if fx and fx > 0:
                price_eur = preco_ref / fx
                acima_plafond = price_eur > 1000

            resultados.append({
                "Ticker": ticker,
                "Score técnico": score,
                "Preço ref. USD": preco_ref,
                "Preço aprox. EUR": price_eur,
                "Acima plafond €1000": "Sim" if acima_plafond else ("Não" if acima_plafond is not None else "N/D"),
                "Entrada ref.": entrada,
                "Stop": stop,
                "Alvo": alvo,
                "Risco/Retorno": "1:2",
                "RSI": float(row["RSI14"]),
                "Momentum 20d %": float(row["RET20"]),
                "Momentum 60d %": float(row["RET60"]),
                "ATR %": float(row["ATR14"] / row["Close"] * 100),
                "Volume rel.": float(row["Volume"] / row["VOL20"]) if row["VOL20"] > 0 else np.nan,
                "Liquidez média": classificar_liquidez(float(row["DOLLAR_VOL20"])),
                "Posição 52 semanas %": distancia_52w(row),
                "Variação última hora %": intraday_change,
                "Volume rel. 1h": intraday_volume_ratio,
                "Data/hora referência": str(data_ref),
            })
        except Exception:
            continue

    if not resultados:
        return pd.DataFrame()

    df = pd.DataFrame(resultados)
    return df.sort_values("Score técnico", ascending=False).reset_index(drop=True)

def estimar_tempo_alvo(df, movimento_pct, max_dias=90):
    closes = df["Close"].dropna()
    if len(closes) < 120 or movimento_pct <= 0:
        return None, None, 0
    tempos = []
    amostras = 0
    for i in range(0, len(closes) - max_dias - 1, 5):
        inicial = float(closes.iloc[i])
        alvo = inicial * (1 + movimento_pct / 100)
        futuro = closes.iloc[i+1:i+1+max_dias]
        amostras += 1
        atingiu = futuro[futuro >= alvo]
        if not atingiu.empty:
            tempos.append(int(futuro.index.get_loc(atingiu.index[0]) + 1))
    if not tempos:
        return None, 0.0, amostras
    return float(np.mean(tempos)), len(tempos) / amostras * 100, amostras

tab1, tab2, tab3 = st.tabs(["Analisar ação", "Minha carteira", "Top 10 diário"])

with tab1:
    st.subheader("Analisar uma ação")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ticker = st.text_input("Ticker", "AAPL").upper().strip()
    with c2:
        capital = st.number_input("Capital da simulação (€)", min_value=100.0, value=1000.0, step=100.0)
    with c3:
        risco_pct = st.number_input("Risco por operação (%)", min_value=0.1, max_value=5.0, value=0.5, step=0.1)
    with c4:
        periodo = st.selectbox("Histórico", ["1y","2y","5y"], index=1)

    if st.button("Analisar ação", type="primary", key="analise"):
        try:
            d = preparar_indicadores(obter_dados(ticker, periodo, "1d")).dropna()
            row = d.iloc[-1]
            entrada, stop, alvo = risco_alvo(row)
            score = score_tecnico(row)
            risco_unit = max(entrada-stop, 0.01)
            risco_eur = capital * risco_pct / 100
            qtd = max(0, min(math.floor(risco_eur/risco_unit), math.floor(capital/entrada)))

            st.metric("Score técnico", f"{score}/100")
            a,b,c,dcol = st.columns(4)
            a.metric("Preço", f"{entrada:.2f} USD")
            b.metric("Stop", f"{stop:.2f} USD")
            c.metric("Alvo", f"{alvo:.2f} USD")
            dcol.metric("Quantidade teórica", str(qtd))
            st.write(
                f"RSI **{row['RSI14']:.1f}** · Momentum 20d **{row['RET20']:.1f}%** · "
                f"Momentum 60d **{row['RET60']:.1f}%** · ATR **{row['ATR14']/row['Close']*100:.1f}%**"
            )
            st.line_chart(d[["Close","EMA20","EMA50","EMA200"]].tail(260))
        except Exception as e:
            st.error(str(e))

with tab2:
    st.subheader("Minha carteira")
    st.write("O preço alvo é definido por ti. A estimativa de tempo usa movimentos históricos semelhantes.")

    inicial = pd.DataFrame([
        {"Ticker":"AAPL","Quantidade":1.0,"Preço médio compra":180.0,"Preço alvo":210.0},
        {"Ticker":"MSFT","Quantidade":1.0,"Preço médio compra":400.0,"Preço alvo":450.0},
    ])
    carteira = st.data_editor(inicial, num_rows="dynamic", use_container_width=True, hide_index=True)
    max_dias = st.selectbox("Horizonte da estimativa", [30,60,90,120,180], index=2,
                            format_func=lambda x: f"{x} dias de mercado")

    if st.button("Avaliar carteira", type="primary", key="portfolio"):
        rows = []
        total = 0
        for _, r in carteira.iterrows():
            t = str(r.get("Ticker","")).upper().strip()
            q = float(r.get("Quantidade",0) or 0)
            pm = float(r.get("Preço médio compra",0) or 0)
            pa = float(r.get("Preço alvo",0) or 0)
            if not t or q <= 0 or pm <= 0 or pa <= 0:
                continue
            try:
                d = obter_dados(t, "5y", "1d")
                atual = float(d["Close"].iloc[-1])
                valor = atual*q
                total += valor
                dist = (pa/atual-1)*100
                tempo, taxa, amostras = estimar_tempo_alvo(d, dist, max_dias) if dist > 0 else (0.0,100.0,0)
                rows.append({
                    "Ticker":t,"Preço atual":atual,"Preço médio":pm,"Qtd":q,
                    "Valor atual":valor,"P/L €":(atual-pm)*q,"P/L %":(atual/pm-1)*100,
                    "Preço alvo":pa,"Distância alvo %":dist,
                    "Ganho potencial até alvo":(pa-atual)*q,
                    "Tempo médio até alvo (dias de mercado)":tempo,
                    "Taxa histórica no horizonte %":taxa,
                    "Amostras":amostras
                })
            except Exception:
                pass
        if rows:
            out = pd.DataFrame(rows)
            out["Peso %"] = out["Valor atual"]/total*100
            st.dataframe(out, use_container_width=True, hide_index=True)
            st.caption("Tempo médio e taxa são estatísticas históricas, não garantias.")

with tab3:
    st.subheader("Top 10 diário")
    st.write(
        "Ranking técnico de ações líquidas. **Não exclui ações acima do plafond de €1.000**; "
        "essas posições continuam visíveis e ficam assinaladas."
    )

    modo = st.radio(
        "Escolher ranking",
        ["Hoje", "Próxima sessão"],
        horizontal=True,
        help="Hoje usa dados de 1h quando disponíveis + contexto diário. Próxima sessão usa o último fecho diário completo."
    )

    universo_txt = st.text_area(
        "Universo analisado (podes editar)",
        value=", ".join(DEFAULT_UNIVERSE),
        height=110
    )

    if st.button("Gerar Top 10", type="primary", key="top10"):
        tickers = [x.strip().upper() for x in universo_txt.replace("\n",",").split(",") if x.strip()]
        tickers = list(dict.fromkeys(tickers))[:80]

        with st.spinner("A analisar dados diários e intradiários..."):
            ranking = analisar_universo(tickers, "hoje" if modo == "Hoje" else "proxima")

        if ranking.empty:
            st.error("Não foi possível obter dados suficientes.")
        else:
            top = ranking.head(10).copy()
            st.caption(
                "Score técnico 0-100 = combinação de tendência, RSI, momentum, volume, volatilidade e contexto de médias móveis. "
                "Não representa probabilidade de lucro."
            )

            cols = [
                "Ticker","Score técnico","Preço ref. USD","Preço aprox. EUR","Acima plafond €1000",
                "Entrada ref.","Stop","Alvo","Risco/Retorno","RSI","Momentum 20d %",
                "Momentum 60d %","ATR %","Volume rel.","Liquidez média",
                "Posição 52 semanas %","Data/hora referência"
            ]
            if modo == "Hoje":
                cols += ["Variação última hora %","Volume rel. 1h"]

            st.dataframe(top[cols], use_container_width=True, hide_index=True)

            st.subheader("Como ler")
            st.write(
                "- **Hoje**: usa a última observação de 1h disponível quando existe, mas mantém ATR e tendência diária para reduzir ruído.\n"
                "- **Próxima sessão**: usa o último fecho diário completo, mais apropriado para preparar o dia seguinte.\n"
                "- **Acima plafond €1000**: não remove a ação; apenas assinala que 1 ação inteira poderá ultrapassar o plafond após conversão aproximada USD/EUR.\n"
                "- **Liquidez média**: baseada no valor médio negociado em 20 dias."
            )

            st.warning(
                "Dados Yahoo/yfinance podem ter atraso e não constituem um feed intradiário profissional. "
                "Antes de usar níveis intradiários com dinheiro real, confirma preço, spread e sessão na corretora."
            )

st.divider()
st.caption("Protótipo de análise. Não envia ordens nem garante que um alvo seja atingido.")
