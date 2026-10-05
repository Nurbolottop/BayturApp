"""
Платёжные шлюзы (ТЗ §11). Единый интерфейс Gateway:
- FreedomPayGateway — реальный Freedom Pay (KG) для метода freedomPay, включается заданием
  FREEDOMPAY_MERCHANT_ID / FREEDOMPAY_SECRET_KEY;
- FakeGateway для dev/staging и пока не подключённых Finik / ЭлQR: имитирует redirect / QR,
  «оплату» на тестовой странице и подписанный вебхук.
Новый провайдер — класс с теми же методами + строка в GATEWAYS + условие в gateway_for.
"""
import hashlib
import hmac
import json
import logging
import secrets
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.response import Response

log = logging.getLogger(__name__)


@dataclass
class CreateResult:
    provider_ref: str
    redirect_url: str = ''
    qr_payload: str = ''
    expires_at: object = None


@dataclass
class WebhookResult:
    event_id: str
    payment_id: str
    status: str        # paid | failed | expired | pending
    amount: int
    extra: dict = None


class GatewayError(Exception):
    """Провайдер недоступен или отклонил запрос."""


class WebhookSignatureError(Exception):
    pass


class Gateway:
    code = ''

    def create(self, payment):
        raise NotImplementedError

    def check(self, payment):
        """Запрос статуса у провайдера (кнопка «Я оплатил»). → 'paid' | 'pending' | 'failed' | None."""
        raise NotImplementedError

    def refund(self, payment, amount):
        """→ (ok: bool, provider_ref: str)."""
        raise NotImplementedError

    def parse_webhook(self, request):
        raise NotImplementedError

    def webhook_response(self, result, payment):
        """Ответ провайдеру на вебхук. payment — None, если событие повторное или платёж неизвестен."""
        return Response({'ok': True})


def sign(body: bytes, secret=None):
    secret = (secret or settings.PAYMENT_WEBHOOK_SECRET).encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


class FakeGateway(Gateway):
    """Тестовый режим: платёж «проводится» на странице /api/v1/payments/fake/{id}/checkout."""

    code = 'fake'
    QR_TTL = timedelta(minutes=5)
    REDIRECT_TTL = timedelta(minutes=30)

    def create(self, payment):
        ref = f'fake-{payment.pk}'
        if payment.method == 'elqr':
            return CreateResult(provider_ref=ref,
                                qr_payload=f'00020101021232BAYTUR-TEST|{payment.pk}|{payment.amount}|KGS',
                                expires_at=timezone.now() + self.QR_TTL)
        return CreateResult(provider_ref=ref,
                            redirect_url=f'{settings.PUBLIC_BASE_URL}/api/v1/payments/fake/{payment.pk}/checkout',
                            expires_at=timezone.now() + self.REDIRECT_TTL)

    def check(self, payment):
        return None  # статус приходит только вебхуком со страницы оплаты

    def refund(self, payment, amount):
        return True, f'fake-refund-{payment.pk}-{amount}'

    def parse_webhook(self, request):
        body = request.body
        signature = request.headers.get('X-Signature', '')
        if not hmac.compare_digest(sign(body), signature):
            raise WebhookSignatureError()
        data = json.loads(body)
        return WebhookResult(event_id=str(data['eventId']), payment_id=data['paymentId'], status=data['status'],
                             amount=int(data['amount']))


def freedompay_sig(script, params, secret=None):
    """
    Подпись Freedom Pay: значения, отсортированные по имени параметра, между именем скрипта
    и секретным ключом, через «;» → md5. pg_sig в подпись не входит.
    """
    secret = secret if secret is not None else settings.FREEDOMPAY_SECRET_KEY
    values = [str(params[k]) for k in sorted(params) if k != 'pg_sig']
    return hashlib.md5(';'.join([script, *values, secret]).encode()).hexdigest()


def _som(value):
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return -1


class FreedomPayGateway(Gateway):
    """
    Freedom Pay Merchant API (https://freedompay.kg/docs-en/merchant-api/pay):
    init_payment.php → страница оплаты (redirectUrl), результат — server-to-server на
    pg_result_url (= /api/v1/payments/webhooks/freedompay), «Я оплатил» → get_status3.php,
    возврат → revoke.php. pg_order_id = id нашего платежа, provider_ref = pg_payment_id.
    """

    code = 'freedompay'
    LIFETIME = 1800  # pg_lifetime, с
    # Свой срок чуть дольше, чем у провайдера: поздний успешный вебхук не попадёт в уже истёкший платёж
    EXPIRE_GRACE = timedelta(minutes=5)
    TIMEOUT = 15

    def _call(self, script, params):
        params = {**params, 'pg_merchant_id': settings.FREEDOMPAY_MERCHANT_ID, 'pg_salt': secrets.token_hex(8)}
        params['pg_sig'] = freedompay_sig(script, params)
        url = f'{settings.FREEDOMPAY_API_URL}/{script}'
        try:
            r = requests.post(url, data=params, timeout=self.TIMEOUT)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except (requests.RequestException, ET.ParseError) as e:
            log.error('freedompay %s failed: %s', script, e)
            raise GatewayError(str(e)) from e
        data = {el.tag: (el.text or '') for el in root}
        if data.get('pg_status') == 'error':
            log.error('freedompay %s error %s: %s', script, data.get('pg_error_code'), data.get('pg_error_description'))
        return data

    def _description(self, payment):
        from apps.catalog.models import Item
        from apps.common.i18n import tr
        item = Item.objects.filter(pk=payment.params.get('itemId')).first()
        title = tr(item.title, 'ru') if item else ''
        return f'BAYTUR: {title}' if title else 'BAYTUR'

    def create(self, payment):
        base = settings.PUBLIC_BASE_URL
        back = f'{base}/api/v1/payments/{payment.pk}/return'
        params = {
            'pg_order_id': payment.pk,
            'pg_amount': payment.amount,
            'pg_currency': 'KGS',
            'pg_description': self._description(payment),
            'pg_lifetime': self.LIFETIME,
            'pg_result_url': f'{base}/api/v1/payments/webhooks/{self.code}',
            'pg_request_method': 'POST',
            'pg_success_url': back,
            'pg_failure_url': back,
            'pg_language': 'ru',
            'pg_auto_clearing': 1,  # списать сразу, а не держать холд до ручного clearing
        }
        if settings.FREEDOMPAY_TESTING_MODE:
            params['pg_testing_mode'] = 1
        phone = (payment.member.phone or '').lstrip('+')
        if phone:
            params['pg_user_phone'] = phone
        data = self._call('init_payment.php', params)
        if data.get('pg_status') != 'ok' or not data.get('pg_redirect_url'):
            raise GatewayError(data.get('pg_error_description') or 'init_payment failed')
        return CreateResult(provider_ref=data.get('pg_payment_id', ''), redirect_url=data['pg_redirect_url'],
                            expires_at=timezone.now() + timedelta(seconds=self.LIFETIME) + self.EXPIRE_GRACE)

    STATUS_MAP = {'success': 'paid', 'failed': 'failed', 'incomplete': 'expired'}

    def check(self, payment):
        try:
            data = self._call('get_status3.php', {'pg_order_id': payment.pk})
        except GatewayError:
            return None
        if data.get('pg_status') != 'ok':
            return None
        status = self.STATUS_MAP.get(data.get('pg_payment_status'))
        if status == 'paid' and _som(data.get('pg_amount')) != payment.amount:
            log.error('freedompay status: amount mismatch for %s: %s', payment.pk, data.get('pg_amount'))
            return 'failed'
        return status

    def refund(self, payment, amount):
        if not payment.provider_ref:
            return False, ''
        try:
            data = self._call('revoke.php', {'pg_payment_id': payment.provider_ref, 'pg_refund_amount': amount})
        except GatewayError:
            return False, ''
        ok = data.get('pg_status') in ('ok', 'success', 'pending')
        return ok, f'{payment.provider_ref}:revoke:{amount}' if ok else ''

    def parse_webhook(self, request):
        params = {k: v for k, v in request.POST.items()}
        signature = params.get('pg_sig', '')
        if not signature or not hmac.compare_digest(freedompay_sig(self.code, params), signature):
            raise WebhookSignatureError()
        result = {'1': 'paid', '0': 'failed'}.get(params.get('pg_result'), 'pending')
        return WebhookResult(event_id=f"{params.get('pg_payment_id')}:{params.get('pg_result')}",
                             payment_id=params.get('pg_order_id', ''), status=result,
                             amount=_som(params.get('pg_amount')),
                             extra={'canReject': params.get('pg_can_reject') == '1',
                                    'providerRef': params.get('pg_payment_id', '')})

    def webhook_response(self, result, payment):
        """
        XML-ответ, подписанный именем нашего скрипта. Деньги списаны, а платёж у нас не оплачен
        (истёк / сумма не совпала) → rejected, если провайдер позволяет отказ.
        """
        status, description = 'ok', ''
        if result.status == 'paid' and payment is not None and payment.status != 'paid':
            if result.extra.get('canReject'):
                status, description = 'rejected', f'payment {payment.status}'
            else:
                log.error('freedompay: paid callback for %s in status %s cannot be rejected — нужен ручной возврат',
                          payment.pk, payment.status)
        params = {'pg_status': status, 'pg_description': description, 'pg_salt': secrets.token_hex(8)}
        params['pg_sig'] = freedompay_sig(self.code, params)
        body = '<?xml version="1.0" encoding="utf-8"?><response>' + ''.join(
            f'<{k}>{escape(str(v))}</{k}>' for k, v in params.items()) + '</response>'
        return HttpResponse(body, content_type='application/xml')


GATEWAYS = {
    'fake': FakeGateway,
    'freedompay': FreedomPayGateway,
}


def freedompay_enabled():
    return bool(settings.FREEDOMPAY_MERCHANT_ID and settings.FREEDOMPAY_SECRET_KEY)


def gateway_for(method):
    """Шлюз для нового платежа: Freedom Pay — свой, остальные методы пока через PAYMENT_BACKEND."""
    if method == 'freedomPay' and freedompay_enabled():
        return FreedomPayGateway()
    return GATEWAYS[settings.PAYMENT_BACKEND]()


def gateway_of(payment):
    """Шлюз, через который платёж создан (проверка статуса, возврат)."""
    return GATEWAYS[payment.provider or settings.PAYMENT_BACKEND]()


def gateway_by_provider(provider):
    """Вебхуки принимаются только от включённых провайдеров (фейковый шлюз в проде не слушаем)."""
    enabled = {settings.PAYMENT_BACKEND}
    if freedompay_enabled():
        enabled.add('freedompay')
    if provider not in enabled:
        return None
    cls = GATEWAYS.get(provider)
    return cls() if cls else None
