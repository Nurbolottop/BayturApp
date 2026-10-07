"""
Разбор QR фискального чека ГНС КР: сумма оплаты и реквизиты чека (для защиты от повторного приёма).

Точный формат QR будет уточнён по образцу реального чека. Пока разбор гибкий: QR — ссылка на проверку
чека или строка вида key=value&key=value; сумма ищется по типичным именам параметров, номер чека — по
фискальным реквизитам (ФН/ФМ/ФД/ФП), а если их нет — берётся хеш всего содержимого QR.
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


def parse_receipt(raw):
    """→ {'key', 'amount', 'fields', 'raw'}; ApiError('receipt_unreadable') — если суммы в QR нет."""
    raw = (raw or '').strip()
    if not raw or len(raw) > MAX_QR_LENGTH:
        raise ApiError('receipt_unreadable', 422)
    fields = {k.strip().lower(): v.strip() for k, v in _pairs(raw) if k.strip()}
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
