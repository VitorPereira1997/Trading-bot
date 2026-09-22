
import math
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Robot Trading", page_icon="📈", layout="centered")

st.title("📈 Robot Trading")
st.caption("Protótipo de simulação — não envia ordens reais.")

with st.sidebar:
    st.header("Configuração")
    ticker = st.text_input("Ticker", value="AAPL").upper().strip()
    capital_total = st.number_input("Capital máximo da simulação (€)", min_value=100.0, value=1000.0, step=100.0)
    risco_pct = st.number_input(
        "Risco por operação (%) — simulação",
        min_value=0.1,
        max_value=5.0,
        value=0.5,
        step=0.1
    )
    periodo = st.selectbox("Histórico", ["3mo", "6mo", "1y"], index=1)
    intervalo = st.selectbox("Intervalo", ["1d", "1h"], index=0)

st.info(
    "Os dados gratuitos podem ter atraso. Este protótipo serve para testar a lógica "
    "e não substitui dados intradiários profissionais."
)

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

@st.cache_data(ttl=300)
def obter_dados(ticker, periodo, intervalo):
    df = yf.download(
        ticker,
        period=periodo,
        interval=intervalo,
        auto_adjust=True,
        progress=False
    )
    if df.empty:
        raise ValueError("Não foi possível obter dados para este ticker.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna().copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["RSI14"] = rsi(df["Close"], 14)
    df["ATR14"] = atr(df, 14)
    df["VOL20"] = df["Volume"].rolling(20).mean()
    return df.dropna()

def analisar(df, capital_total, risco_pct):
    if len(df) < 55:
        raise ValueError("Histórico insuficiente para calcular os indicadores.")

    atual = df.iloc[-1]
    anterior = df.iloc[-2]

    tendencia_alta = bool(atual["EMA20"] > atual["EMA50"])
    rsi_ok = bool(52 <= atual["RSI14"] <= 68)
    volume_ok = bool(atual["Volume"] > atual["VOL20"])
    cruzamento_alta = bool(
        anterior["EMA20"] <= anterior["EMA50"] and
        atual["EMA20"] > atual["EMA50"]
    )

    pontos = int(tendencia_alta) + int(rsi_ok) + int(volume_ok)

    sinal = "AGUARDAR"
    if pontos == 3 or (cruzamento_alta and pontos >= 2):
        sinal = "COMPRAR"

    entrada = float(atual["Close"])
    atr_val = float(atual["ATR14"])
    stop = entrada - 1.5 * atr_val
    risco_unitario = max(entrada - stop, 0.01)
    alvo = entrada + 2.0 * risco_unitario

    risco_euros = capital_total * (risco_pct / 100)
    qtd_por_risco = math.floor(risco_euros / risco_unitario)
    qtd_por_capital = math.floor(capital_total / entrada)
    quantidade = max(0, min(qtd_por_risco, qtd_por_capital))

    return {
        "sinal": sinal,
        "pontos": pontos,
        "entrada": entrada,
        "stop": stop,
        "alvo": alvo,
        "rsi": float(atual["RSI14"]),
        "ema20": float(atual["EMA20"]),
        "ema50": float(atual["EMA50"]),
        "volume_ok": volume_ok,
        "tendencia_alta": tendencia_alta,
        "quantidade": quantidade,
        "risco_euros": risco_euros,
        "data": df.index[-1]
    }

if st.button("Analisar ação", type="primary", use_container_width=True):
    try:
        if not ticker:
            st.error("Escreve um ticker, por exemplo AAPL.")
            st.stop()

        df = obter_dados(ticker, periodo, intervalo)
        res = analisar(df, capital_total, risco_pct)

        if res["sinal"] == "COMPRAR":
            st.success(f"Resultado: {res['sinal']}")
        else:
            st.warning(f"Resultado: {res['sinal']}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Preço", f"{res['entrada']:.2f}")
        c2.metric("Stop", f"{res['stop']:.2f}")
        c3.metric("Alvo", f"{res['alvo']:.2f}")

        st.subheader("Resumo")
        st.write(
            f"**Pontuação:** {res['pontos']}/3  \n"
            f"**RSI:** {res['rsi']:.1f}  \n"
            f"**EMA20:** {res['ema20']:.2f}  \n"
            f"**EMA50:** {res['ema50']:.2f}  \n"
            f"**Tendência de alta:** {'Sim' if res['tendencia_alta'] else 'Não'}  \n"
            f"**Volume acima da média:** {'Sim' if res['volume_ok'] else 'Não'}"
        )

        st.subheader("Dimensionamento teórico")
        st.write(
            f"Com o capital definido e risco de simulação de **{risco_pct:.2f}%**, "
            f"a perda planeada seria de cerca de **€{res['risco_euros']:.2f}** por operação."
        )
        st.write(f"Quantidade teórica máxima pelas regras: **{res['quantidade']} ação(ões)**.")

        st.subheader("Gráfico")
        chart_df = df[["Close", "EMA20", "EMA50"]].copy()
        st.line_chart(chart_df)

        st.caption(
            "Um stop não garante o preço de execução; gaps, slippage, spread, comissões e câmbio "
            "podem aumentar a perda real."
        )

    except Exception as e:
        st.error(f"Erro: {e}")

st.divider()
st.caption(
    "Este protótipo usa regras simples e dados gratuitos. Antes de qualquer utilização real, "
    "é necessário testar a estratégia historicamente e em paper trading."
)
