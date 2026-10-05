import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.i18n import iso
from apps.catalog.models import ONLINE_METHODS
from apps.common.errors import ApiError
from apps.common.realtime import publish_member

from .gateways import GatewayError, gateway_by_provider, gateway_for, gateway_of
from .models import FINAL_STATUSES, Payment, PaymentStatus, Refund, WebhookEvent

log = logging.getLogger(__name__)


def payment_payload(p):
    return {
        'id': p.pk,
        'method': p.method,
        'amount': p.amount,
        'status': p.status,
        'redirectUrl': p.redirect_url or None,
        'qrPayload': p.qr_payload or None,
        'expiresAt': iso(p.expires_at) if p.expires_at else None,
        'paidAt': iso(p.paid_at) if p.paid_at else None,
        'requestId': p.request_id,
    }


def _publish(p):
    publish_member(p.member_id, 'payment.updated', payment_payload(p))


def create_payment(member, data):
    """Сервер сам проверяет, что amountSom = moneySom по переданным параметрам."""
    from apps.cashback.calc import compute_split
    from apps.cashback.services import _check_member_can_act, quote

    _check_member_can_act(member)
    method = data.get('method')
    if method not in ONLINE_METHODS:
        raise ApiError('method_not_allowed', 422)
    item, rules, base, available = quote(member, data.get('itemId'), data.get('quantity'), data.get('checkAmount'),
                                         0)
    split = compute_split(base.total, rules, available, data.get('pointsSom'), strict=True)
    if method not in rules.methods:
        raise ApiError('method_not_allowed', 422)
    if split.money_som <= 0 or int(data.get('amountSom') or 0) != split.money_som:
        raise ApiError('payment_invalid', 422, extra={'moneySom': split.money_som})

    payment = Payment.objects.create(
        member=member, method=method, amount=split.money_som, is_test=member.is_test,
        params={'itemId': item.pk, 'quantity': data.get('quantity'), 'checkAmount': data.get('checkAmount'),
                'pointsSom': split.points_som, 'method': method},
    )
    gateway = gateway_for(method)
    payment.provider = gateway.code
    try:
        result = gateway.create(payment)
    except GatewayError:
        payment.status = PaymentStatus.FAILED
        payment.save(update_fields=['provider', 'status', 'updated_at'])
        raise ApiError('payment_unavailable', 503)
    payment.provider_ref = result.provider_ref
    payment.redirect_url = result.redirect_url
    payment.qr_payload = result.qr_payload
    payment.expires_at = result.expires_at
    payment.save()
    return payment


def set_status(payment_id, status, amount=None):
    """Переход статуса по вебхуку/проверке. Сверка суммы: не совпала → failed."""
    with transaction.atomic():
        p = Payment.objects.select_for_update().get(pk=payment_id)
        if p.status in FINAL_STATUSES or p.status == status:
            return p
        if p.status == PaymentStatus.PAID:
            return p  # оплаченный платёж меняется только возвратом
        if status == PaymentStatus.PAID:
            if amount is not None and int(amount) != p.amount:
                log.error('payment %s amount mismatch: %s != %s', p.pk, amount, p.amount)
                p.status = PaymentStatus.FAILED
            else:
                p.status = PaymentStatus.PAID
                p.paid_at = timezone.now()
        elif status in (PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.PENDING):
            p.status = status
        p.save()
    _publish(p)
    return p


def handle_webhook(provider, request):
    """→ ответ провайдеру (у каждого шлюза свой формат)."""
    gw = gateway_by_provider(provider)
    if gw is None:
        raise ApiError('not_found', 404)
    result = gw.parse_webhook(request)  # WebhookSignatureError → 401 во view
    return gw.webhook_response(result, _apply_webhook(provider, result))


def _apply_webhook(provider, result):
    try:
        with transaction.atomic():
            WebhookEvent.objects.create(provider=provider, event_id=result.event_id,
                                        payload={'paymentId': result.payment_id, 'status': result.status,
                                                 'amount': result.amount})
    except IntegrityError:
        return None  # уже обработано — идемпотентно
    if not Payment.objects.filter(pk=result.payment_id).exists():
        log.warning('webhook for unknown payment %s', result.payment_id)
        return None
    return set_status(result.payment_id, result.status, result.amount)


def check_payment(payment):
    """«Я оплатил» — спросить провайдера."""
    if payment.status in (PaymentStatus.CREATED, PaymentStatus.PENDING):
        status = gateway_of(payment).check(payment)
        if status:
            payment = set_status(payment.pk, status, payment.amount if status == PaymentStatus.PAID else None)
    return payment


def refund_payment(payment_id, amount, reason='', author=None):
    """Возврат у провайдера (полный при отказе/отмене, частичный при правке суммы вниз)."""
    with transaction.atomic():
        p = Payment.objects.select_for_update().get(pk=payment_id)
        left = p.amount - p.refunded_amount
        amount = min(int(amount), left)
        if amount <= 0 or p.status not in (PaymentStatus.PAID,):
            return None
        refund = Refund.objects.create(payment=p, amount=amount, reason=reason, author=author)
    ok, ref = gateway_of(p).refund(p, amount)
    with transaction.atomic():
        p = Payment.objects.select_for_update().get(pk=payment_id)
        refund.status = 'done' if ok else 'failed'
        refund.provider_ref = ref or ''
        refund.save()
        if ok:
            p.refunded_amount += amount
            if p.refunded_amount >= p.amount:
                p.status = PaymentStatus.REFUNDED
            p.save()
    _publish(p)
    return refund


def expire_payments(now=None):
    now = now or timezone.now()
    ids = list(Payment.objects.filter(status__in=[PaymentStatus.CREATED, PaymentStatus.PENDING],
                                      expires_at__lt=now).values_list('pk', flat=True))
    for pid in ids:
        set_status(pid, PaymentStatus.EXPIRED)
    return len(ids)


def resolve_orphan_payments(grace_minutes=10):
    """
    «Оплачено, но без заявки»: клиент закрыл приложение после оплаты. Сервер создаёт заявку сам
    по данным платежа; если это уже невозможно (баллов не хватает, услуга скрыта) — возврат денег.
    """
    from apps.cashback.services import create_request
    cutoff = timezone.now() - timedelta(minutes=grace_minutes)
    handled = 0
    for p in Payment.objects.filter(status=PaymentStatus.PAID, request__isnull=True, paid_at__lt=cutoff) \
            .select_related('member'):
        params = dict(p.params)
        try:
            create_request(p.member, {**params, 'paymentId': p.pk}, idempotency_key=f'auto:{p.pk}')
        except ApiError as e:
            log.warning('orphan payment %s: cannot create request (%s), refunding', p.pk, e.code)
            refund_payment(p.pk, p.amount, f'orphan:{e.code}')
        handled += 1
    return handled
