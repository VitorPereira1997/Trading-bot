"""Read XTB cash movements in EUR without saving them or accessing the network."""
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
import re
import unicodedata
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from openpyxl.utils.exceptions import InvalidFileException


def normal(value):
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii','ignore').decode()
    return ' '.join(text.casefold().split())


SHEETS = {'cash operations', 'cash operation', 'cash operation history', 'cash operations history',
          'operacoes em numerario', 'operacoes em dinheiro', 'historico de operacoes em numerario', 'historico de operacoes em dinheiro'}
ALIASES = {
    'id': {'id', 'identificador', 'id da operacao'}, 'tipo': {'type', 'tipo', 'tipo de operacao'},
    'data': {'time', 'date', 'date and time', 'hora', 'data', 'data e hora'}, 'ticker': {'ticker', 'symbol', 'simbolo', 'ticker do instrumento'},
    'montante': {'amount', 'montante', 'valor'}, 'moeda': {'currency', 'moeda'},
}
TYPES = {
    'deposit': 'deposito', 'withdrawal': 'levantamento',
    'dividend': 'credito_dividendo', 'divident': 'credito_dividendo',
    'withholding tax': 'retencao_dividendo', 'retencao sobre dividendos': 'retencao_dividendo',
    'retencao na fonte sobre dividendos': 'retencao_dividendo', 'commission': 'comissao', 'fee': 'taxa', 'sec fee': 'taxa',
    'internal transfer': 'transferencia_interna', 'cash transfer': 'transferencia_por_confirmar',
    'deposito': 'deposito', 'levantamento': 'levantamento', 'dividendo': 'credito_dividendo',
    'retencao de dividendo': 'retencao_dividendo', 'comissao': 'comissao', 'taxa': 'taxa', 'transferencia interna': 'transferencia_interna',
}


def amount(value):
    form = str(value).strip().replace('\u00a0', ' ').replace('\u202f', ' ')
    if re.fullmatch(r'[+-]?\d{1,3}(?:[. ]\d{3})+,\d{1,8}', form):
        form = form.replace('.', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d{1,14}(?:[.,]\d{1,8})?', form):
        raise ValueError('Montante ausente ou formato ambíguo.')
    return Decimal(form.replace(',', '.'))


def _read(raw, confirmed_currency):
    if not isinstance(raw, bytes) or not raw or len(raw) > 4_000_000:
        raise ValueError('O Excel está vazio ou é superior a 4 MB.')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            files = archive.infolist()
            if len(files) > 200 or sum(f.file_size for f in files) > 24_000_000:
                raise ValueError('O ficheiro ultrapassa os limites de leitura.')
            for f in files:
                name = f.filename.lower()
                if f.flag_bits & 1 or 'vbaproject' in name or name.startswith('xl/externallinks/'):
                    raise ValueError('Ficheiro encriptado, com macros ou com ligações externas.')
                if name.endswith(('.xml', '.rels')):
                    content = archive.read(f)
                    if b'\x00' in content or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                        raise ValueError('O ficheiro contém XML não suportado.')
        book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, InvalidFileException, KeyError, OSError, SyntaxError) as exc:
        raise ValueError('Não foi possível ler o ficheiro Excel.') from exc
    try:
        sheets = [s for s in book.worksheets if normal(s.title) in SHEETS]
        if len(sheets)!=1:
            raise ValueError('Não foi possível identificar uma única folha de operações em numerário.')
        sheet = sheets[0]
        # Some XTB exports declare the whole worksheet dimension as A1.
        sheet.reset_dimensions()
        columns = {}
        result = {}
        summary = 0
        for line, cells in enumerate(sheet.iter_rows(max_col=48), 1):
            if line>20025:
                raise ValueError('O ficheiro ultrapassa o limite de movimentos.')
            values = tuple(cell.value for cell in cells)
            if not any(value is not None for value in values):
                continue
            labels = [normal(v) for v in values]
            if not columns:
                if line>24:
                    raise ValueError('Cabeçalhos do formato não reconhecidos.')
                found = {key:[i for i,v in enumerate(labels) if v in names] for key,names in ALIASES.items()}
                if all(found[key] for key in ('id','tipo','data','montante','ticker')):
                    if any(len(index)>1 for index in found.values()):
                        raise ValueError('Cabeçalhos duplicados ou ambíguos.')
                    columns = {key:index[0] for key,index in found.items() if index}
                    if 'ticker' in labels:
                        columns['ticker'] = labels.index('ticker')
                continue
            def value(key):
                if key not in columns:
                    return None
                cell = cells[columns[key]]
                if cell.data_type in ('f','e'):
                    raise ValueError('Fórmula ou erro numa célula de movimentos.')
                return cell.value
            # Um Total sem ID e data é resumo, independentemente do seu significado.
            if any(v in ('total','totals') for v in labels) and (not value('id') or normal(value('id')) in ('total','totals')) and not value('data'):
                summary += 1
                continue
            identifier = str(value('id') or '').strip()
            if len(identifier) > 120:
                raise ValueError(f'Linha {line}: ID de movimento inválido.')
            if not identifier or not value('tipo'):
                raise ValueError(f'Linha {line}: falta o ID ou tipo do movimento.')
            day = value('data')
            if isinstance(day,(int,float)):
                try:
                    day = from_excel(day,book.epoch)
                except (OverflowError, ValueError) as exc:
                    raise ValueError('Data Excel inválida.') from exc
            if isinstance(day,str):
                try:
                    raw_date = day.strip()
                    if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}(?: \d{1,2}:\d{2}(?::\d{2})?)?', raw_date):
                        formats = {1: '%d/%m/%Y %H:%M', 2: '%d/%m/%Y %H:%M:%S'}
                        day = datetime.strptime(raw_date, formats.get(raw_date.count(':'), '%d/%m/%Y'))
                    else:
                        day = datetime.fromisoformat(raw_date)
                except ValueError as exc:
                    raise ValueError(f'Linha {line}: data não reconhecida sem ambiguidade.') from exc
            instant = day.isoformat() if isinstance(day, (date, datetime)) else None
            if isinstance(day,datetime):
                day = day.date()
            if not isinstance(day,date) or day>date.today():
                raise ValueError(f'Linha {line}: data de movimento inválida.')
            currency = str(value('moeda') or confirmed_currency or '').strip().upper()
            if not re.fullmatch(r'[A-Z]{3}',currency):
                raise ValueError('Confirma a moeda da conta antes de interpretar montantes.')
            if confirmed_currency and currency != confirmed_currency.upper():
                raise ValueError('A moeda de um movimento diverge da moeda confirmada.')
            ticker = str(value('ticker') or '').strip().upper()
            label = normal(value('tipo'))
            kind = TYPES.get(label, 'por_classificar')
            figure = amount(value('montante'))
            if kind in ('credito_dividendo','retencao_dividendo'):
                if not re.fullmatch(r'[A-Z0-9][A-Z0-9.:-]{0,29}', ticker):
                    raise ValueError(f'Linha {line}: dividendo ou retenção sem ticker válido.')
                if (kind == 'credito_dividendo' and figure < 0) or (kind == 'retencao_dividendo' and figure > 0):
                    raise ValueError(f'Linha {line}: sinal inesperado num dividendo ou numa retenção.')
            if (kind == 'deposito' and figure < 0) or (kind in ('levantamento','comissao','taxa') and figure > 0):
                kind = 'por_classificar'
            row = (day, kind, ticker, figure, instant, label)
            if identifier in result and result[identifier]!=row:
                raise ValueError('O mesmo identificador tem dados diferentes.')
            result[identifier] = row
        if not columns:
            raise ValueError('Cabeçalhos do formato não reconhecidos.')
        return tuple(result.values()),summary
    finally:
        book.close()


def preview(raw, confirmed_eur=False):
    """Return a ledger consumed by Dividendos, and counts only (not source IDs or rows)."""
    if not confirmed_eur:
        raise ValueError('Confirma que a conta do extrato XTB está em EUR. Não há conversão automática.')
    try:
        rows, summaries = _read(raw, 'EUR')
    except (ParseError, BadZipFile, InvalidFileException, KeyError, OSError, SyntaxError,
            TypeError, RuntimeError, OverflowError) as exc:
        raise ValueError('Não foi possível ler o formato deste Excel XTB.') from exc
    ledger, ignored = [], Counter()
    for day, kind, ticker, figure, _, label in rows:
        if kind == 'credito_dividendo':
            ledger.append((day, 'dividendo', ticker, figure, figure, Decimal(0)))
        elif kind == 'retencao_dividendo':
            ledger.append((day, 'dividendo', ticker, figure, Decimal(0), -figure))
        elif kind in {'deposito', 'levantamento', 'comissao', 'taxa'}:
            ledger.append((day, kind, ticker, figure, None, None))
        else:
            ignored['other'] += 1
            if ('divid' in label or 'retencao' in label or 'withholding' in label) and label != 'free funds interest tax':
                ignored['possible_dividend'] += 1
    if not ledger:
        raise ValueError('O Excel não contém movimentos suportados. Confirma o período e a folha de operações em numerário.')
    return tuple(sorted(ledger, key=lambda row: row[0])), (ignored['other'], ignored['possible_dividend'], summaries)
