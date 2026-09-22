# Robot Trading Web

Versão web simples para telemóvel, feita com Streamlit.

## Publicar no Streamlit Community Cloud

1. Cria uma conta no GitHub.
2. Cria um novo repositório.
3. Faz upload de `app.py` e `requirements.txt`.
4. Vai a https://share.streamlit.io/
5. Liga a conta GitHub.
6. Seleciona o repositório e escolhe `app.py` como ficheiro principal.
7. Carrega em Deploy.

Depois recebes um link que podes abrir no telemóvel.

## O que faz

- descarrega dados com yfinance;
- calcula EMA 20, EMA 50, RSI 14, ATR 14 e volume médio;
- mostra COMPRAR ou AGUARDAR segundo regras simples;
- calcula entrada, stop, alvo e quantidade teórica;
- não envia ordens reais.

## Importante

É um protótipo de simulação. Dados gratuitos podem ter atraso e não devem ser usados como feed profissional em tempo real.
