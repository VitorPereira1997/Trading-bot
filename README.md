# Analisador de Mercados v6

Inclui:
- Plano de hoje com capital disponível e limites de perda definidos pelo utilizador;
- Ações e ETFs;
- análise técnica e fundamental/qualidade ETF separadas;
- cenários históricos de 5, 10, 15 e 30 dias;
- mercados EUA, Alemanha, Portugal, França, Países Baixos, Espanha, Itália, Reino Unido e Suíça;
- Top 10 global ou por mercados;
- watchlist automática durante a sessão;
- avaliação de carteira;
- backtest técnico com custos;
- indicação de fonte, data de referência e completude dos dados.

## Atualizar no Streamlit
Substituir no GitHub `app.py` e `requirements.txt`. O Streamlit deverá fazer redeploy após o commit.

## Integridade
A aplicação não preenche dados em falta por suposição. Campos indisponíveis aparecem como N/D/dados insuficientes. Cenários históricos não são previsões.
