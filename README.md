# Analisador de Mercados v7 — identidade XTB

Nesta versão o **ticker XTB é o identificador principal do instrumento**.

Exemplos:
- `ASML.NL` -> dados técnicos `ASML.AS` -> Países Baixos / Euronext Amsterdam / EUR
- `ASML.US` -> dados técnicos `ASML` -> EUA / Nasdaq / USD
- `META.US` -> dados técnicos `META` -> EUA / Nasdaq / USD
- `FB2A.DE` -> dados técnicos `FB2A.DE` -> Alemanha / EUR
- `EDP.PT` -> dados técnicos `EDP.LS` -> Portugal / Euronext Lisbon / EUR

A app guarda e apresenta separadamente:
- ticker XTB;
- empresa;
- mercado/país;
- bolsa;
- moeda;
- ticker técnico usado pela fonte de dados.

## Regra importante

A app **não troca silenciosamente de bolsa ou moeda**. Se o ticker XTB for reconhecido mas o fornecedor técnico não tiver dados para a cotação correspondente, devolve erro em vez de usar outra praça.

## Mapeamentos especiais

O ficheiro `xtb_aliases.csv` permite manter exceções onde o ticker da XTB e o ticker da fonte técnica não seguem uma conversão simples. Pode ser atualizado sem reescrever a app.

## Atualizar no Streamlit

No repositório GitHub substitui/adiciona:
- `app.py`
- `requirements.txt`
- `xtb_aliases.csv`

Depois faz `Commit changes`. O Streamlit deverá fazer redeploy automaticamente.

## Dados

A identidade do instrumento segue a nomenclatura XTB. As séries de mercado e fundamentais continuam a ser obtidas pelo Yahoo Finance via `yfinance`, pelo que um ativo pode existir na XTB mas não estar disponível nessa fonte. Nesses casos a app deve indicar dados indisponíveis, não inventar ou substituir a cotação.
