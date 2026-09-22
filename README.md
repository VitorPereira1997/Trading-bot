# Robot Trading Web v3

Inclui:
- Análise individual;
- Minha carteira;
- Top 10 diário para Hoje e Próxima sessão;
- Não exclui ações acima do plafond de €1.000;
- Conversão aproximada USD/EUR para assinalar preço unitário acima do plafond;
- Score técnico com tendência, RSI, momentum 20/60 dias, volume, ATR e médias móveis;
- Liquidez média;
- posição no intervalo de 52 semanas;
- dados intradiários de 1h para o ranking Hoje quando disponíveis.

## Atualização no Streamlit
Substitui no GitHub:
- app.py
- requirements.txt

Depois do commit, o Streamlit normalmente faz redeploy automaticamente.

## Limitações
Dados Yahoo/yfinance podem ter atraso. O score não é uma probabilidade de lucro nem uma recomendação automática.
