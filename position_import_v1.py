"""Read-only CSV parsing and preparation for reviewed position imports."""
import csv
from datetime import date
from hashlib import sha256
import io
import json
import math
import re

REQUIRED = ('Ticker XTB','Quantidade','Preço médio')
OPTIONAL = ('Tipo instrumento','Tipo','Ticker técnico','Multiplicador contrato','Preço alvo pessoal',
            'Data entrada','Objetivo','Origem','Tese/nota','Moeda')
MAX_BYTES = 2_000_000
MAX_ROWS = 2000
MAX_NUM = 1_000_000_000_000
TICKER = re.compile(r'[A-Z0-9^][A-Z0-9.=_^-]{0,39}')
NUMBER = re.compile(r'[+]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)(?:[eE][+-]?[0-9]{1,3})?')
TYPE = {'':'Auto','auto':'Auto','ação':'Ação','acao':'Ação','stock':'Ação',
        'equity':'Ação','etf':'ETF','etn':'ETN'}


def _number(raw, title, *, optional=False):
    if optional and not raw:
        return 0.0
    if not NUMBER.fullmatch(raw):
        raise ValueError(f'{title}: usa um número sem separador de milhares.')
    value = float(raw.replace(',','.'))
    if not math.isfinite(value) or value>MAX_NUM or (not optional and value<=0.0):
        raise ValueError(f'{title}: valor fora dos limites.')
    return value


def read_positions_csv(raw, instrument_identity):
    if not isinstance(raw, bytes) or not raw or len(raw)>MAX_BYTES:
        raise ValueError('O CSV está vazio ou excede 2 MB.')
    try:
        content=raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('Usa um ficheiro CSV guardado em UTF-8.') from exc
    if '\x00' in content:
        raise ValueError('O CSV contém caracteres inválidos.')
    chosen = []
    for sep in (',',';'):
        parser = csv.reader(io.StringIO(content,newline=''),delimiter=sep,strict=True)
        try:
            fields = [s.strip() for s in next(parser, [])]
            if set(REQUIRED).issubset(fields):
                chosen.append((fields,parser))
        except csv.Error:
            pass
    if len(chosen)!=1:
        raise ValueError('Usa um CSV com as colunas Ticker XTB, Quantidade e Preço médio.')
    fields, parser = chosen[0]
    if len(fields)!=len(set(fields)):
        raise ValueError('O CSV tem nomes de colunas repetidos.')
    ignored = tuple(s for s in fields if s not in REQUIRED+OPTIONAL)
    rows=[]
    count=0
    try:
        for values in parser:
            count+=1
            if count>MAX_ROWS:
                raise ValueError('O CSV excede 2 000 linhas.')
            if not any(values):
                continue
            try:
                if len(values)!=len(fields):
                    raise ValueError('O número de colunas não corresponde ao cabeçalho.')
                source={k:v.strip() for k,v in zip(fields,values) if k in REQUIRED+OPTIONAL}
                if any(len(v)>1024 for v in source.values()):
                    raise ValueError('Há um campo demasiado longo.')
                ticker=source['Ticker XTB'].upper()
                technical=source.get('Ticker técnico','').upper()
                if not TICKER.fullmatch(ticker) or (technical and not TICKER.fullmatch(technical)):
                    raise ValueError('Ticker XTB ou ticker técnico inválido.')
                ident=instrument_identity(ticker)
                ticker=ident['xtb_ticker']
                kind=source.get('Tipo instrumento') or source.get('Tipo') or ''
                if kind.casefold()=='cfd':
                    raise ValueError('O mandato da Casa não aceita CFDs.')
                if kind.casefold() not in TYPE:
                    raise ValueError('Tipo desconhecido. Usa Auto, Ação, ETF ou ETN.')
                goal=source.get('Objetivo') or 'Longo prazo'
                if goal not in ('Longo prazo','Curto prazo'):
                    raise ValueError('Objetivo inválido.')
                entered=source.get('Data entrada','')
                if entered:
                    when=date.fromisoformat(entered)
                    if entered!=when.isoformat() or when>date.today():
                        raise ValueError('Data de entrada inválida. Usa AAAA-MM-DD, sem data futura.')
                currency=source.get('Moeda','').upper()
                if currency and not re.fullmatch(r'[A-Z]{3}',currency):
                    raise ValueError('A moeda não está num código válido de três letras.')
                row={'Ticker XTB':ticker,'Quantidade':_number(source['Quantidade'],'Quantidade'),
                     'Preço médio':_number(source['Preço médio'],'Preço médio'),'Tipo instrumento':TYPE[kind.casefold()],
                     'Objetivo':goal,'Ticker técnico':technical,
                     'Preço alvo pessoal':_number(source.get('Preço alvo pessoal',''),'Preço alvo pessoal',optional=True),
                     'Multiplicador contrato':_number(source.get('Multiplicador contrato',''),'Multiplicador',optional=True),
                     'Origem':source.get('Origem') or 'Importação CSV',
                     'Tese/nota':source.get('Tese/nota',''),'Data entrada':entered}
                if currency:
                    row['Moeda']=currency
                rows.append(row)
            except ValueError as exc:
                raise ValueError(f'Linha {parser.line_num}: {exc}') from exc
    except csv.Error as exc:
        raise ValueError(f'CSV inválido na linha {parser.line_num}.') from exc
    if not rows:
        raise ValueError('O CSV não contém posições válidas.')
    labels=[row['Ticker XTB'] for row in rows]
    if len(labels)!=len(set(labels)):
        raise ValueError('O CSV repete um ticker. Não foi possível escolher entre as linhas.')
    seen=set()
    for row in rows:
        matches=_keys(row,instrument_identity)
        if seen & matches:
            raise ValueError('Há dois tickers no CSV que apontam para o mesmo título. Revê o ficheiro antes de importar.')
        seen.update(matches)
    return rows, ignored


def _keys(row, instrument_identity):
    t=str(row.get('Ticker XTB') or '').strip().upper()
    if not t:
        return set()
    ident=instrument_identity(t)
    technical=str(row.get('Ticker técnico') or '').strip().upper()
    out={('ticker', ident['xtb_ticker']),('source',ident['source_ticker'])}
    if technical and technical.lower() not in ('nan','none'):
        out.add(('source',technical))
    return out


def plan_import(current, rows, mode, instrument_identity):
    """Only additions in add mode; whole replacement explicit and separate."""
    if mode=='replace':
        return list(rows),list(rows),[]
    if mode!='add':
        raise ValueError('Modo de importação desconhecido.')
    existing=set().union(*(_keys(row,instrument_identity) for row in current))
    add, skipped=[],[]
    for row in rows:
        (skipped if _keys(row,instrument_identity) & existing else add).append(row)
    return list(current)+add, add, skipped


def confirmation_digest(positions):
    return sha256(json.dumps(positions,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
