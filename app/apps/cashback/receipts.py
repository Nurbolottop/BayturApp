"""
Разбор QR фискального чека ГНС КР: сумма оплаты и реквизиты чека (для защиты от повторного приёма).

QR чека ККМ — ссылка на проверку чека в налоговой: https://tax.salyk.kg/...?tin=…&fn_number=…&fd_number=…
&type=…&date=…&sum=… . sum — ЦЕЛОЕ число в тыйынах (API налоговой принимает только Long): 24000 = 240,00 сом.
Чек однозначно определяют ИНН продавца + номер фискального модуля + номер фискального документа.

Для других форматов (строка key=value, другие имена полей) разбор гибкий: сумма — по типичным именам,
номер — по фискальным реквизитам, иначе — хеш всего содержимого QR.
"""
import hashlib
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlsplit

from apps.common.errors import ApiError

MAX_QR_LENGTH = 2000
AMOUNT_KEYS = ('sum', 's', 'amount', 'total', 'totalsum', 'summa', 'ticketsum')
# фискальные реквизиты: номер ФН / модуля, номер документа, фискальный признак, номер чека
ID_KEYS = ('fn', 'fm', 'fd', 'fp', 'i', 'fiscalmodule', 'fiscalmoduleserialnumber', 'fiscaldocumentnumber',
           'fiscaldocumentmark', 'fiscalsign', 'ticket', 'ticketnumber', 'check', 'checknumber', 'number', 'id',
           'regnumber', 'kkm', 'date', 't')


def _pairs(raw):
    if '://' in raw:
        parts = urlsplit(raw)
        return parse_qsl(parts.query, keep_blank_values=False) + parse_qsl(parts.fragment, keep_blank_values=False)
    return parse_qsl(raw.replace(';', '&'), keep_blank_values=False)


def _amount(value):
    try:
        amount = Decimal(str(value).strip().replace(',', '.').replace(' ', ''))
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return int(amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP))  # тыйыны округляются до сома


def _salyk(raw, fields):
    """Чек ГНС КР (tax.salyk.kg): сумма в тыйынах, номер — ИНН + ФМ + ФД."""
    host = (urlsplit(raw).hostname or '').lower() if '://' in raw else ''
    if not (host == 'salyk.kg' or host.endswith('.salyk.kg')) or 'sum' not in fields:
        return None
    value = fields['sum'].strip()
    amount = _amount(value) if any(ch in value for ch in '.,') else (_amount(Decimal(value) / 100)
                                                                       if value.isdigit() else None)
    if amount is None:
        raise ApiError('receipt_unreadable', 422)
    ids = [fields.get(k, '').strip() for k in ('tin', 'fn_number', 'fd_number')]
    if not all(ids):
        raise ApiError('receipt_unreadable', 422)
    return {'key': 'salyk:' + ':'.join(ids), 'amount': amount, 'fields': fields, 'raw': raw}


def parse_receipt(raw):
    """→ {'key', 'amount', 'fields', 'raw'}; ApiError('receipt_unreadable') — если суммы в QR нет."""
    raw = (raw or '').strip()
    if not raw or len(raw) > MAX_QR_LENGTH:
        raise ApiError('receipt_unreadable', 422)
    fields = {k.strip().lower(): v.strip() for k, v in _pairs(raw) if k.strip()}
    salyk = _salyk(raw, fields)
    if salyk is not None:
        return salyk
    amount = next((a for a in (_amount(fields[k]) for k in AMOUNT_KEYS if k in fields) if a), None)
    if amount is None:
        raise ApiError('receipt_unreadable', 422)
    ids = sorted((k, fields[k]) for k in ID_KEYS if fields.get(k))
    # одних реквизитов вроде даты мало — нужен хотя бы один номер; иначе номер чека — хеш всего QR
    if [k for k, _ in ids if k not in ('date', 't')]:
        key = '|'.join(f'{k}={v}' for k, v in ids)[:200]
    else:
        key = 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()
    return {'key': key, 'amount': amount, 'fields': fields, 'raw': raw}
