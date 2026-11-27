"""Importação normalizada em EUR para pré-visualização. Não grava nem acede à rede."""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import io
import re

FIELDS = ('id', 'data', 'tipo', 'ticker', 'moeda', 'liquido', 'bruto', 'retencao')
TYPES = {'dividendo', 'deposito', 'levantamento', 'comissao', 'taxa'}
CENTS = Decimal('0.01')


def _money(value):
    if not re.fullmatch(r'[+-]?\d{1,12}(?:[.,]\d{1,2})?', value):
        raise ValueError('Montante inválido')
    try:
        return Decimal(value.replace(',', '.')).quantize(CENTS)
    except InvalidOperation as exc:
        raise ValueError('Montante inválido') from exc


def parse(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 2_000_000:
        raise ValueError('Ficheiro vazio ou superior a 2 MB.')
    try:
        rows = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter=';', strict=True)
        if tuple(k.strip() for k in (rows.fieldnames or [])) != FIELDS:
            raise ValueError('As colunas não correspondem ao modelo.')
        rows.fieldnames = FIELDS
        unique = {}
        for line, row in enumerate(rows, 2):
            if line > 20001:
                raise ValueError('O ficheiro excede 20 000 movimentos.')
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Colunas a mais ou em falta')
                row = {key: value.strip() for key, value in row.items()}
                identifier = row['id']
                if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', identifier):
                    raise ValueError('Identificador obrigatório ou inválido')
                day = date.fromisoformat(row['data'])
                if day.isoformat() != row['data'] or day > date.today():
                    raise ValueError('Usa uma data de liquidação passada ou de hoje, AAAA-MM-DD')
                kind, ticker = row['tipo'].lower(), row['ticker'].upper()
                if kind not in TYPES or row['moeda'].upper() != 'EUR':
                    raise ValueError('Tipo não suportado ou moeda diferente de EUR')
                if ticker and not re.fullmatch(r'[A-Z0-9][A-Z0-9.:-]{0,29}', ticker):
                    raise ValueError('Ticker inválido')
                net = _money(row['liquido'])
                gross = _money(row['bruto']) if row['bruto'] else None
                tax = _money(row['retencao']) if row['retencao'] else None
                if kind == 'dividendo':
                    if not ticker or net < 0 or (gross is None) != (tax is None):
                        raise ValueError('Dividendo sem ticker, líquido negativo ou detalhe incompleto')
                    if gross is not None and (tax < 0 or gross - tax != net):
                        raise ValueError('Bruto menos retenção não coincide com o líquido')
                elif gross is not None or tax is not None or (net <= 0 if kind == 'deposito' else net >= 0):
                    raise ValueError('Sinal do movimento inválido ou colunas exclusivas de dividendo preenchidas')
                movement = (day, kind, ticker, net, gross, tax)
                if identifier in unique and unique[identifier] != movement:
                    raise ValueError('O mesmo identificador tem dados diferentes')
                unique[identifier] = movement
            except ValueError as exc:
                raise ValueError(f'Linha {line}: {exc}.') from exc
        if not unique:
            raise ValueError('O ficheiro não contém movimentos.')
        return tuple(sorted(unique.values(), key=lambda item: item[0]))
    except UnicodeError as exc:
        raise ValueError('Usa um CSV em UTF-8.') from exc
    except csv.Error as exc:
        raise ValueError('CSV inválido.') from exc


def totals(rows):
    if not rows:
        return None
    net = sum(row[3] for row in rows)
    detailed = all(row[4] is not None and row[5] is not None for row in rows)
    return net, sum(row[4] for row in rows) if detailed else None, sum(row[5] for row in rows) if detailed else None
