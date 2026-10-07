"""
Разбор QR фискального чека ГНС КР: сумма оплаты и реквизиты чека (для защиты от повторного приёма).

QR чека ККМ — ссылка на проверку чека в налоговой: https://tax.salyk.kg/...?tin=…&fn_number=…&fd_number=…
&type=…&date=…&sum=… . sum — ЦЕЛОЕ число в тыйынах (API налоговой принимает только Long): 24000 = 240,00 сом.
Чек однозначно определяют ИНН продавца + номер фискального модуля + номер фискального документа.

Для других форматов (строка key=value, другие имена полей) разбор гибкий: сумма — по типичным именам,
номер — по фискальным реквизитам, иначе — хеш всего содержимого QR.
"""
import hashlib
import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.common.errors import ApiError

log = logging.getLogger(__name__)

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


# ---------------------------------------------------------------- проверка чека в налоговой

SALYK_URL = 'https://tax.salyk.kg/tax-web-control/client/api/v1/ticket'
# в запрос к налоговой уходят только эти параметры QR — присланный URL как есть не открывается (SSRF)
SALYK_PARAMS = ('date', 'type', 'operation_type', 'fn_number', 'fd_number', 'fm', 'tin', 'regNumber', 'sum')
SALYK_CACHE_TTL = 600


def _tyiyn_to_som(value):
    return int((Decimal(int(value)) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _salyk_details(data):
    """JSON налоговой → то, что видит кассир и что хранится в журнале."""
    cr = data.get('crData') or {}
    try:
        at = timezone.localtime(datetime.fromisoformat(str(data.get('dateTime')).replace('Z', '+00:00'))).isoformat()
    except (TypeError, ValueError):
        at = None
    return {
        'verified': True,
        'number': data.get('ticketNumber'),
        'shift': cr.get('shiftNumber'),
        'dateTime': at,
        'seller': cr.get('locationName') or '',
        'address': cr.get('locationAddress') or '',
        'tin': data.get('tin'),
        'fnNumber': data.get('fnSerialNumber'),
        'fdNumber': data.get('fdNumber'),
        'registerNumber': data.get('crRegisterNumber'),
        'fiscalMark': data.get('documentFiscalMark'),
        'operationType': data.get('operationType'),
        'total': _tyiyn_to_som(data.get('ticketTotalSum') or 0),
        'cash': _tyiyn_to_som(data.get('ticketTotalCashSum') or 0),
        'cashless': _tyiyn_to_som(data.get('ticketTotalCashlessSum') or 0),
        'items': [{'name': i.get('goodName') or '', 'quantity': i.get('goodQuantity'),
                   'sum': _tyiyn_to_som(i.get('goodCost') or 0)} for i in (data.get('items') or [])][:50],
    }


def fetch_salyk(params, key):
    """
    Чек из налоговой по реквизитам QR. None — налоговая недоступна (оплату можно принять по сумме из QR,
    чек помечается «не проверен»); receipt_not_found — налоговая такого чека не знает (поддельный QR).
    """
    cached = cache.get(f'salyk:{key}')
    if cached is not None:
        return cached
    url = SALYK_URL + '?' + urlencode([(k, params[k]) for k in SALYK_PARAMS if params.get(k)])
    try:
        resp = requests.get(url, timeout=8, headers={'Accept': 'application/json',
                                                     'User-Agent': 'Mozilla/5.0 (BAYTUR receipt check)'})
    except requests.RequestException as e:
        log.warning('salyk unavailable: %s', e)
        return None
    if resp.status_code in (400, 404):
        raise ApiError('receipt_not_found', 422)
    if resp.status_code != 200:
        log.warning('salyk %s: %s', resp.status_code, resp.text[:200])
        return None
    try:
        data = resp.json()
    except ValueError:
        log.warning('salyk: not json')
        return None
    if not isinstance(data, dict) or data.get('ticketTotalSum') is None:
        raise ApiError('receipt_not_found', 422)
    details = _salyk_details(data)
    cache.set(f'salyk:{key}', details, SALYK_CACHE_TTL)
    return details


def _salyk(raw, fields, original):
    """Чек ГНС КР (tax.salyk.kg): сумма в тыйынах, номер — ИНН + ФМ + ФД; данные — из налоговой."""
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
    key = 'salyk:' + ':'.join(ids)
    allowed = getattr(settings, 'RECEIPT_ALLOWED_TINS', [])
    if allowed and ids[0] not in allowed:
        raise ApiError('receipt_foreign', 422)
    details = fetch_salyk(original, key) if getattr(settings, 'RECEIPT_VERIFY', True) else None
    if details is not None:
        if details['operationType'] not in (1, None):  # 1 — приход; возврат и прочее не принимаются
            raise ApiError('receipt_not_sale', 422)
        amount = details['total'] or amount
    else:
        details = {'verified': False, 'total': amount}
    return {'key': key, 'amount': amount, 'fields': {**fields, 'details': details}, 'raw': raw, 'details': details}


def parse_receipt(raw):
    """→ {'key', 'amount', 'fields', 'raw'}; ApiError('receipt_unreadable') — если суммы в QR нет."""
    raw = (raw or '').strip()
    if not raw or len(raw) > MAX_QR_LENGTH:
        raise ApiError('receipt_unreadable', 422)
    pairs = [(k.strip(), v.strip()) for k, v in _pairs(raw) if k.strip()]
    fields = {k.lower(): v for k, v in pairs}
    salyk = _salyk(raw, fields, dict(pairs))
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
