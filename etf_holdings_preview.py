"""Instantâneo parcial Vanguard. Percentagens do fundo sem reescalar."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

AS_OF = '2026-10-31'
DATA = {
    'IE00BK5BQT80': (
        'VWCE', 'https://www.vanguard.co.uk/professional/product/etf/equity/9679/IE00BK5BQT80',
        [('Apple','4.74363'),('NVIDIA','4.54553'),('Microsoft','3.69160'),('Amazon','2.21951'),
         ('TSMC','1.68471'),('Alphabet','1.58169'),('Broadcom','1.44453'),('Meta','1.28715'),
         ('Alphabet','1.22962'),('Tesla','1.11218')]),
    'IE00BFMXXD54': (
        'VUAA', 'https://www.vanguard.co.uk/professional/product/etf/equity/9694/sp-500-ucits-etf-usd-accumulating',
        [('Apple','7.68796'),('NVIDIA','7.56979'),('Microsoft','5.92382'),('Amazon','3.60606'),
         ('Alphabet','2.51039'),('Broadcom','2.37129'),('Meta','2.07289'),('Alphabet','2.02103'),
         ('Eli Lilly','1.73375'),('Tesla','1.72228')]),
}
ALIASES = {
    'VWCE.DE':'IE00BK5BQT80','VWCE.MI':'IE00BK5BQT80','VWCE.AS':'IE00BK5BQT80',
    'VUAA.DE':'IE00BFMXXD54','VUAA.MI':'IE00BFMXXD54',
}
STOCK = {
    'AAPL.US':'Apple', 'NVDA.US':'NVIDIA','MSFT.US':'Microsoft','AMZN.US':'Amazon',
    'GOOG.US':'Alphabet','GOOGL.US':'Alphabet','AVGO.US':'Broadcom','META.US':'Meta',
    'LLY.US':'Eli Lilly','TSLA.US':'Tesla',
}


def fund_id(position):
    explicit = str(position.get('ISIN') or '').strip().upper()
    alias = ALIASES.get(str(position.get('Ticker XTB') or '').strip().upper())
    if explicit:
        return explicit if explicit in DATA and alias in (None,explicit) else None
    return alias


def eur_amount(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number>=0 else None


def exposure(items):
    contributions = defaultdict(dict)
    missing_positions = missing_funds = 0
    total = Decimal(0)
    for position, valuation in items:
        kind = position.get('Tipo instrumento') or valuation.get('Tipo instrumento')
        ticker = str(position.get('Ticker XTB') or '').strip().upper()
        value = eur_amount(valuation.get('Valor atual EUR'))
        if value is None or kind not in ('ETF','Ação'):
            missing_positions += 1
            continue
        total += value
        if kind=='ETF':
            isin = fund_id(position)
            if not isin:
                missing_funds += 1
                continue
            source = isin
            for name, weight in DATA[isin][2]:
                entry = contributions[name]
                entry[source] = entry.get(source,Decimal(0)) + value*Decimal(weight)/100
        elif ticker in STOCK:
            entry = contributions[STOCK[ticker]]
            entry['direto'] = entry.get('direto',Decimal(0)) + value
    return contributions, total if not missing_positions and total>0 else None, missing_positions, missing_funds
