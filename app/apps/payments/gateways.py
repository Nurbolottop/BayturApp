"""
Платёжные шлюзы. Провайдеры (Finik, Freedom Pay, ЭлQR) ещё не выбраны заказчиком (ТЗ §11),
поэтому сейчас есть единый интерфейс и FakeGateway для dev/staging: он имитирует
redirect / QR, «оплату» на тестовой странице и подписанный вебхук. Реальный провайдер —
новый класс с теми же методами + строка в GATEWAYS.
"""
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


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
    status: str        # paid | failed | expired
    amount: int


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


GATEWAYS = {
    'fake': FakeGateway,
}


def gateway_for(method):
    """Пока реальных провайдеров нет, все онлайн-методы идут через PAYMENT_BACKEND."""
    return GATEWAYS[settings.PAYMENT_BACKEND]()


def gateway_by_provider(provider):
    """Вебхуки принимаются только от включённого провайдера (фейковый шлюз в проде не слушаем)."""
    if provider != settings.PAYMENT_BACKEND:
        return None
    cls = GATEWAYS.get(provider)
    return cls() if cls else None
