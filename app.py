
import math
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Robot Trading", page_icon="📈", layout="wide")
st.title("📈 Robot Trading")
st.caption("Análise e simulação. Não envia ordens reais.")

DEFAULT_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","TSLA","JPM","V",
    "MA","LLY","WMT","COST","NFLX","AMD","ORCL","CRM","ADBE","QCOM",
    "INTC","MU","UBER","PLTR","BAC","GS","XOM","CVX","KO","PEP",
    "DIS","NKE","CAT","GE","IBM","NOW","AMAT","TXN","PANW","INTU"
]

if "watchlist" not in st.session_state:
    st.session_state.watchlist = []

def add_watchlist(ticker):
    t = ticker.upper().strip()
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
        return float(fx["Close"].dropna().iloc[-1])
    except Exception:
        return None

def estimar_tempo_alvo(df, movimento_pct, max_dias=90):
    closes = df["Close"].dropna()
    if len(closes) < 120 or movimento_pct <= 0:
        return None, None, 0

    tempos = []
    amostras = 0
    for i in range(0, len(closes) - max_dias - 1, 5):
        inicial = float(closes.iloc[i])
        alvo = inicial * (1 + movimento_pct / 100)
        futuro = closes.iloc[i + 1:i + 1 + max_dias]
        amostras += 1
        atingiu = futuro[futuro >= alvo]
        if not atingiu.empty:
            tempos.append(int(futuro.index.get_loc(atingiu.index[0]) + 1))

    if amostras == 0:
        return None, None, 0
    if not tempos:
        return None, 0.0, amostras

    return float(np.mean(tempos)), (len(tempos) / amostras) * 100, amostras

def score_tecnico(row):
    trend = 0
    if row["Close"] > row["EMA20"]:
        trend += 15
    if row["EMA20"] > row["EMA50"]:
        trend += 15
    if row["EMA50"] > row["EMA200"]:
        trend += 15

    rv = float(row["RSI14"])
    if 50 <= rv <= 65:
        rsi_score = 15
    elif 45 <= rv < 50 or 65 < rv <= 72:
        rsi_score = 8
    else:
        rsi_score = 2

    def norm(v, lo, hi):
        return max(0.0, min(1.0, (v-lo)/(hi-lo))) * 100

    mom20 = norm(float(row["RET20"]), -10, 15) * 0.10
    mom60 = norm(float(row["RET60"]), -20, 30) * 0.10
    vr = float(row["Volume"] / row["VOL20"]) if row["VOL20"] > 0 else 0
    volume_score = norm(vr, 0.7, 2.0) * 0.10
    atr_pct = float(row["ATR14"] / row["Close"] * 100)

    if 1.0 <= atr_pct <= 4.5:
        atr_score = 10
    elif 0.5 <= atr_pct < 1.0 or 4.5 < atr_pct <= 7.0:
        atr_score = 5
    else:
        atr_score = 1

    return round(min(100.0, trend+rsi_score+mom20+mom60+volume_score+atr_score), 1)

def risco_alvo(row, preco=None):
    entrada = float(preco if preco is not None else row["Close"])
    a = float(row["ATR14"])
    stop = entrada - 1.5*a
    alvo = entrada + 2.0*(entrada-stop)
    return entrada, stop, alvo

def classificar_liquidez(v):
    if pd.isna(v):
        return "N/D"
    if v >= 1_000_000_000:
        return "Muito alta"
    if v >= 250_000_000:
        return "Alta"
    if v >= 50_000_000:
        return "Média"
    return "Baixa"

def pos52(row):
    hi, lo, c = float(row["HIGH252"]), float(row["LOW252"]), float(row["Close"])
    if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
        return np.nan
    return (c-lo)/(hi-lo)*100

def analisar_universo(tickers, modo="proxima", horizonte_alvo=90):
    resultados = []
    fx = eurusd()

    for ticker in tickers:
        try:
            daily_raw = obter_dados(ticker, "5y", "1d")
            daily = preparar_indicadores(daily_raw).dropna()
            if len(daily) < 210:
                continue

            row = daily.iloc[-1]
            preco_ref = float(row["Close"])
            data_ref = daily.index[-1]
            intraday_change = np.nan
            intraday_volume_ratio = np.nan

            if modo == "hoje":
                try:
                    intra = obter_dados(ticker, "60d", "1h")
                    if len(intra) >= 20:
                        preco_ref = float(intra["Close"].iloc[-1])
                        data_ref = intra.index[-1]
                        if len(intra) >= 2:
                            intraday_change = (float(intra["Close"].iloc[-1]) / float(intra["Close"].iloc[-2]) - 1) * 100
                        vol20h = intra["Volume"].rolling(20).mean().iloc[-1]
                        if pd.notna(vol20h) and vol20h > 0:
                            intraday_volume_ratio = float(intra["Volume"].iloc[-1] / vol20h)
                except Exception:
                    pass

            entrada, stop, alvo = risco_alvo(row, preco_ref if modo == "hoje" else None)

            score = score_tecnico(row)
            if modo == "hoje" and pd.notna(intraday_change):
                score += max(-5, min(5, intraday_change*2))
                if pd.notna(intraday_volume_ratio):
                    score += max(-3, min(3, (intraday_volume_ratio-1)*2))
                score = round(max(0, min(100, score)), 1)

            mov_pct = (alvo/entrada - 1)*100
            tempo, taxa, amostras = estimar_tempo_alvo(daily_raw, mov_pct, horizonte_alvo)

            eur = preco_ref/fx if fx and fx > 0 else None
            acima = eur > 1000 if eur is not None else None

            resultados.append({
                "Ticker": ticker,
                "Score técnico": score,
                "Preço ref. USD": preco_ref,
                "Preço aprox. EUR": eur,
                "Acima plafond €1000": "Sim" if acima else ("Não" if acima is not None else "N/D"),
                "Entrada ref.": entrada,
                "Stop": stop,
                "Alvo": alvo,
                "Tempo médio até alvo": f"{tempo:.1f} dias de mercado" if tempo is not None else "Sem histórico suficiente",
                "Taxa histórica alvo %": taxa,
                "Risco/Retorno": "1:2",
                "RSI": float(row["RSI14"]),
                "Momentum 20d %": float(row["RET20"]),
                "Momentum 60d %": float(row["RET60"]),
                "ATR %": float(row["ATR14"]/row["Close"]*100),
                "Volume rel.": float(row["Volume"]/row["VOL20"]) if row["VOL20"] > 0 else np.nan,
                "Liquidez média": classificar_liquidez(float(row["DOLLAR_VOL20"])),
                "Posição 52 semanas %": pos52(row),
                "Variação última hora %": intraday_change,
                "Volume rel. 1h": intraday_volume_ratio,
                "Data/hora referência": str(data_ref)
            })
        except Exception:
            continue

    if not resultados:
        return pd.DataFrame()
    return pd.DataFrame(resultados).sort_values("Score técnico", ascending=False).reset_index(drop=True)

tab1, tab2, tab3 = st.tabs(["Analisar ação", "Minha carteira", "Top 10 diário"])

with tab1:
    st.subheader("Analisar uma ação")

    c1,c2,c3,c4,c5 = st.columns(5)
    with c1:
        ticker = st.text_input("Ticker", "AAPL").upper().strip()
    with c2:
        capital = st.number_input("Capital simulação (€)", min_value=100.0, value=1000.0, step=100.0)
    with c3:
        risco_pct = st.number_input("Risco por operação (%)", min_value=0.1, max_value=5.0, value=0.5, step=0.1)
    with c4:
        periodo = st.selectbox("Histórico", ["1y","2y","5y"], index=1)
    with c5:
        horizonte = st.selectbox("Horizonte alvo", [30,60,90,120,180], index=2,
                                 format_func=lambda x: f"{x} dias de mercado")

    if st.button("Analisar ação", type="primary", key="analise"):
        try:
            add_watchlist(ticker)

            raw5 = obter_dados(ticker, "5y", "1d")
            d = preparar_indicadores(obter_dados(ticker, periodo, "1d")).dropna()
            row = d.iloc[-1]
            entrada, stop, alvo = risco_alvo(row)
            score = score_tecnico(row)
            risco_unit = max(entrada-stop, 0.01)
            risco_eur = capital*risco_pct/100
            qtd = max(0, min(math.floor(risco_eur/risco_unit), math.floor(capital/entrada)))

            movimento = (alvo/entrada - 1)*100
            tempo, taxa, amostras = estimar_tempo_alvo(raw5, movimento, horizonte)

            st.success(f"{ticker} foi adicionada à watchlist do Top 10.")

            a,b,c,dcol = st.columns(4)
            a.metric("Preço", f"{entrada:.2f} USD")
            b.metric("Stop", f"{stop:.2f} USD")
            c.metric("Alvo", f"{alvo:.2f} USD")
            dcol.metric("Score técnico", f"{score}/100")

            e,f,g = st.columns(3)
            e.metric("Tempo médio até ao alvo", f"{tempo:.1f} dias de mercado" if tempo is not None else "Sem histórico suficiente")
            f.metric("Taxa histórica de atingir o alvo", f"{taxa:.1f}%" if taxa is not None else "N/D")
            g.metric("Quantidade teórica", str(qtd))

            st.caption(
                f"Estimativa baseada em movimentos históricos semelhantes nos últimos 5 anos, "
                f"com horizonte máximo de {horizonte} dias de mercado. Amostras analisadas: {amostras}."
            )

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
                            format_func=lambda x: f"{x} dias de mercado", key="portfolio_h")

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

            add_watchlist(t)

            try:
                d = obter_dados(t, "5y", "1d")
                atual = float(d["Close"].iloc[-1])
                valor = atual*q
                total += valor
                dist = (pa/atual-1)*100
                tempo, taxa, amostras = estimar_tempo_alvo(d, dist, max_dias) if dist > 0 else (0.0,100.0,0)

                rows.append({
                    "Ticker":t,
                    "Preço atual":atual,
                    "Preço médio":pm,
                    "Qtd":q,
                    "Valor atual":valor,
                    "P/L €":(atual-pm)*q,
                    "P/L %":(atual/pm-1)*100,
                    "Preço alvo":pa,
                    "Distância alvo %":dist,
                    "Ganho potencial até alvo":(pa-atual)*q,
                    "Tempo médio até alvo":f"{tempo:.1f} dias de mercado" if tempo is not None else "Sem histórico suficiente",
                    "Taxa histórica alvo %":taxa
                })
            except Exception:
                pass

        if rows:
            out = pd.DataFrame(rows)
            out["Peso %"] = out["Valor atual"]/total*100
            st.dataframe(out, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Top 10 diário")

    if st.session_state.watchlist:
        st.info("Watchlist atual: " + ", ".join(st.session_state.watchlist))
    else:
        st.info("Ainda não pesquisaste nenhuma ação nesta sessão.")

    modo = st.radio("Ranking", ["Hoje","Próxima sessão"], horizontal=True)
    horizonte_top = st.selectbox(
        "Horizonte para estimar tempo até ao alvo",
        [30,60,90,120,180],
        index=2,
        format_func=lambda x: f"{x} dias de mercado",
        key="top_h"
    )

    usar_watchlist = st.checkbox("Dar prioridade à watchlist", value=True)

    base_universe = list(DEFAULT_UNIVERSE)
    for t in st.session_state.watchlist:
        if t not in base_universe:
            base_universe.append(t)

    universo_txt = st.text_area("Universo analisado", value=", ".join(base_universe), height=110)

    if st.button("Gerar Top 10", type="primary", key="top10"):
        tickers = [x.strip().upper() for x in universo_txt.replace("\n",",").split(",") if x.strip()]
        tickers = list(dict.fromkeys(tickers))[:100]

        with st.spinner("A analisar dados..."):
            ranking = analisar_universo(tickers, "hoje" if modo=="Hoje" else "proxima", horizonte_top)

        if ranking.empty:
            st.error("Não foi possível obter dados suficientes.")
        else:
            if usar_watchlist and st.session_state.watchlist:
                ranking["Na watchlist"] = ranking["Ticker"].isin(st.session_state.watchlist)
                ranking = ranking.sort_values(["Na watchlist","Score técnico"], ascending=[False,False])
            else:
                ranking["Na watchlist"] = ranking["Ticker"].isin(st.session_state.watchlist)

            top = ranking.head(10).copy()

            cols = [
                "Ticker","Na watchlist","Score técnico","Preço ref. USD","Preço aprox. EUR",
                "Acima plafond €1000","Entrada ref.","Stop","Alvo","Tempo médio até alvo",
                "Taxa histórica alvo %","Risco/Retorno","RSI","Momentum 20d %",
                "Momentum 60d %","ATR %","Volume rel.","Liquidez média",
                "Posição 52 semanas %","Data/hora referência"
            ]
            if modo == "Hoje":
                cols += ["Variação última hora %","Volume rel. 1h"]

            st.dataframe(top[cols], use_container_width=True, hide_index=True)

            st.caption(
                "O tempo médio e a taxa histórica são calculados com movimentos semelhantes dos últimos 5 anos. "
                "São estatísticas históricas, não previsões garantidas."
            )

st.divider()
st.caption("Protótipo de análise. Não envia ordens nem garante que um alvo seja atingido.")
