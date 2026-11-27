"""Private, read-only merge preparation for manually confirmed XTB cash movements."""
from datetime import date
from decimal import Decimal, InvalidOperation
import re

FIELD = 'xtb_cash_history_v1'
_KEY = re.compile(r'[a-f0-9]{64}')
KINDS = {'dividendo','deposito','levantamento','comissao','taxa'}
MAX_ROWS = 20000
MAX_ACCOUNTS = 20


def _decode(row):
    if not isinstance(row, list) or len(row)!=6:
        raise ValueError('O histórico guardado tem um formato inesperado.')
    d,kind,ticker,*values = row
    if kind not in KINDS or not isinstance(ticker,str):
        raise ValueError('Movimento guardado com formato inesperado.')
    try:
        known = tuple(Decimal(value) if isinstance(value,str) else None for value in values)
        day = date.fromisoformat(d)
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError('Movimento guardado inválido.') from exc
    if day > date.today() or known[0] is None or any(v is not None and not v.is_finite() for v in known):
        raise ValueError('Data ou valor inválido no histórico guardado.')
    if kind == 'dividendo' and (not ticker or known[1] is None or known[2] is None or
                                known[1]<0 or known[2]<0 or known[1]-known[2]!=known[0]):
        raise ValueError('Dividendo guardado não conciliado.')
    return day,kind,ticker,*known


def _encode(row):
    day,kind,ticker,*values = row
    return [day.isoformat(),kind,ticker,*(str(value) if value is not None else None for value in values)]


def checked(saved):
    if saved is None:
        return {}
    if not isinstance(saved,dict) or len(saved)>MAX_ACCOUNTS:
        raise ValueError('O histórico guardado não está num formato reconhecido.')
    count = 0
    for account, rows in saved.items():
        if not isinstance(account,str) or not _KEY.fullmatch(account) or not isinstance(rows,dict):
            raise ValueError('Conta no histórico guardado não reconhecida.')
        count += len(rows)
        if count > MAX_ROWS:
            raise ValueError('O histórico ultrapassa o limite de movimentos.')
        for key,row in rows.items():
            if not isinstance(key,str) or not _KEY.fullmatch(key):
                raise ValueError('Movimento no histórico guardado não reconhecido.')
            _decode(row)
    return saved


def ledger(saved, account):
    return tuple(sorted((_decode(r) for r in saved.get(account,{}).values()),key=lambda r:r[0]))


def merge(saved, account, movements):
    saved = checked(saved)
    if not isinstance(account,str) or not _KEY.fullmatch(account) or not movements:
        raise ValueError('Falta uma conta XTB identificada ou não há movimentos novos para guardar.')
    if len(movements)>MAX_ROWS:
        raise ValueError('O extrato excede o limite de movimentos.')
    previous = saved.get(account,{})
    additions = {}
    for key,row in movements.items():
        if not isinstance(key,str) or not _KEY.fullmatch(key):
            raise ValueError('O Excel tem um identificador de movimento inválido.')
        encoded = _encode(row)
        if key in previous:
            if _decode(previous[key]) != row:
                raise ValueError('Há um movimento que já existe com dados diferentes. Nada foi guardado; compara os dois extratos.')
        else:
            _decode(encoded)
            additions[key] = encoded
    merged = {**saved,account:{**previous,**additions}}
    if len(merged)>MAX_ACCOUNTS or sum(len(rows) for rows in merged.values())>MAX_ROWS:
        raise ValueError('O histórico excederia o limite de contas ou movimentos.')
    return merged,len(additions),len(movements)-len(additions)
