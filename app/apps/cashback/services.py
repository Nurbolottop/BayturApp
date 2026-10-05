"""
Жизненный цикл заявки на кешбек (ТЗ §5.1):

  pending ──confirm──▶ confirmed ──credit──▶ credited
     │
     ├──reject──▶ rejected
     └──cancel──▶ cancelled

Отмена и отказ — только из pending. Каждый переход пишется в timeline.
Резерв баллов: pending держит points в reserved; confirm списывает их (spend);
credit начисляет кешбек (cashback, растит lifetime).
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.i18n import iso
from apps.catalog.models import ONLINE_METHODS, Item, PaymentMethod
from apps.common.errors import ApiError
from apps.common.models import ProgramSettings
from apps.common.realtime import publish_member, publish_outlets
from apps.loyalty.engine import evaluate
from apps.loyalty.services import accrue, change_reserved, lock_wallet, publish_wallet, spend_reserved

from .calc import Rules, compute_split, compute_total, resolve_rules
from .models import CashbackRequest, RejectReason, RequestStatus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- quote

def quote(member, item_id, quantity=None, check_amount=None, points_som=0, method=None, available=None):
    item = Item.objects.active().select_related('category').prefetch_related('promos').filter(pk=item_id).first()
    if item is None:
        raise ApiError('item_not_found', 404)
    ps = ProgramSettings.get()
    now = timezone.now()
    rules = resolve_rules(item, member, ps, now)
    total, quantity = compute_total(item, quantity, check_amount)
    if available is None:
        from apps.loyalty.services import get_wallet
        available = get_wallet(member).available
    split = compute_split(total, rules, available, points_som)
    return item, rules, split, available


def quote_payload(member, data):
    item, rules, split, available = quote(member, data.get('itemId'), data.get('quantity'),
                                          data.get('checkAmount'), data.get('pointsSom'), data.get('method'))
    return {
        **split.as_dict(),
        'maxPointsSom': split.max_points_som,
        'availablePoints': available,
        'methods': rules.methods if split.money_som > 0 else [],
        'bonuses': rules.bonuses,
    }


# ---------------------------------------------------------------- создание

def _check_member_can_act(member):
    from apps.members.models import MemberStatus
    if member.status == MemberStatus.BLOCKED:
        raise ApiError('account_blocked', 403)
    if member.status != MemberStatus.ACTIVE:
        raise ApiError('account_frozen', 403)


def _schedule(req, ps, now):
    req.expires_at = now + timedelta(hours=ps.pending_ttl_hours)
    auto = ps.auto_confirm or req.is_test
    if auto and (req.method != PaymentMethod.CASH or ps.auto_confirm_cash or req.is_test):
        req.auto_confirm_at = now + timedelta(milliseconds=ps.confirm_delay_ms)


def create_request(member, data, idempotency_key=None):
    """
    Клиент присылает только ввод; суммы, правила и кешбек пересчитываются здесь.
    Атомарно, с блокировкой кошелька. Повтор с тем же Idempotency-Key → та же заявка.
    Возвращает (request, created).
    """
    _check_member_can_act(member)
    if idempotency_key:
        existing = CashbackRequest.objects.filter(member=member, idempotency_key=idempotency_key).first()
        if existing:
            return existing, False

    item = Item.objects.active().select_related('category', 'outlet').prefetch_related('promos') \
        .filter(pk=data.get('itemId')).first()
    if item is None:
        raise ApiError('item_not_found', 404)

    ps = ProgramSettings.get()
    now = timezone.now()
    rules = resolve_rules(item, member, ps, now)
    total, quantity = compute_total(item, data.get('quantity'), data.get('checkAmount'))
    method = data.get('method') or None
    payment_id = data.get('paymentId') or None

    try:
        with transaction.atomic():
            wallet = lock_wallet(member)
            split = compute_split(total, rules, wallet.available, data.get('pointsSom'), strict=True)

            if split.money_som == 0:
                method = None
            else:
                if method is None or method not in rules.methods:
                    raise ApiError('method_not_allowed', 422)

            payment = None
            if method in ONLINE_METHODS:
                from apps.payments.models import Payment, PaymentStatus
                payment = Payment.objects.select_for_update().filter(pk=payment_id, member=member).first() \
                    if payment_id else None
                if (payment is None or payment.status != PaymentStatus.PAID or payment.amount != split.money_som
                        or payment.method != method or payment.request_id is not None):
                    raise ApiError('payment_invalid', 422)

            req = CashbackRequest(
                member=member, item=item, outlet=item.outlet, item_snapshot=item.snapshot(),
                rules=rules.snapshot(), bonuses=rules.bonuses, quantity=quantity,
                check_amount=total if item.pricing_type == 'check' else None,
                requested_points_som=int(data.get('pointsSom') or 0), method=method,
                total=split.total, points_som=split.points_som, points=split.points, money_som=split.money_som,
                rate=split.rate, cashback=split.cashback, idempotency_key=idempotency_key or None,
                is_test=member.is_test, created_at=now,
            )
            req.mark(RequestStatus.PENDING, now)
            _schedule(req, ps, now)
            req.save()

            if split.points:
                change_reserved(wallet, split.points, request=req, at=now)
            wallet.last_activity_at = now  # заявка — реальное действие
            wallet.save(update_fields=['last_activity_at', 'updated_at'])

            if payment is not None:
                payment.request = req
                payment.save(update_fields=['request', 'updated_at'])
    except IntegrityError:
        # параллельный повтор с тем же ключом
        if idempotency_key:
            existing = CashbackRequest.objects.filter(member=member, idempotency_key=idempotency_key).first()
            if existing:
                return existing, False
        raise

    _after_change(req, 'request.created', wallet)
    return req, True


# ---------------------------------------------------------------- переходы

def _lock_request(req_id):
    return CashbackRequest.objects.select_for_update().select_related('member', 'item').get(pk=req_id)


def _after_change(req, staff_event='request.updated', wallet=None):
    from .serializers import request_payload, staff_request_payload
    publish_member(req.member_id, 'request.updated', request_payload(req, lang=req.member.language))
    if wallet is not None:
        publish_wallet(req.member, wallet)
    publish_outlets([req.outlet_id], staff_event, staff_request_payload(req))


def _release_and_refund(req, wallet, reason):
    if req.points:
        change_reserved(wallet, -req.points, request=req)
    payment = getattr(req, 'payment', None)
    if payment is not None:
        from apps.payments.services import refund_payment
        transaction.on_commit(lambda: refund_payment(payment.pk, payment.amount - payment.refunded_amount, reason))


def cancel_request(member, req_id):
    with transaction.atomic():
        req = _lock_request(req_id)
        if req.member_id != member.pk:
            raise ApiError('not_found', 404)
        if req.status != RequestStatus.PENDING:
            raise ApiError('invalid_status', 409, extra={'status': req.status})
        wallet = lock_wallet(req.member)
        req.mark(RequestStatus.CANCELLED)
        req.closed_at = timezone.now()
        _clear_schedule(req)
        req.save()
        _release_and_refund(req, wallet, 'cancelled')
    _after_change(req, wallet=wallet)
    return req


def _clear_schedule(req):
    req.auto_confirm_at = None
    req.expires_at = None


def reject_request(req_id, staff=None, code=RejectReason.OTHER, comment='', expected_outlets=None):
    with transaction.atomic():
        req = _lock_request(req_id)
        if expected_outlets is not None and req.outlet_id not in expected_outlets:
            raise ApiError('outlet_forbidden', 403)
        if req.status != RequestStatus.PENDING:
            raise ApiError('invalid_status', 409, extra={'status': req.status})
        wallet = lock_wallet(req.member)
        req.mark(RequestStatus.REJECTED)
        req.rejected_at = req.closed_at = timezone.now()
        req.reject_code = code
        req.reject_reason = (comment or '').strip()
        req.rejected_by = staff
        req.escalated = False
        _clear_schedule(req)
        req.save()
        _release_and_refund(req, wallet, f'rejected:{code}')
    _after_change(req, wallet=wallet)
    from apps.notifications.services import notify_request_rejected
    transaction.on_commit(lambda: notify_request_rejected(req.pk))
    return req


def confirm_request(req_id, staff=None, cash_received=False):
    ps = ProgramSettings.get()
    with transaction.atomic():
        req = _lock_request(req_id)
        if req.status != RequestStatus.PENDING:
            raise ApiError('invalid_status', 409, extra={'status': req.status})
        if staff is not None and req.method == PaymentMethod.CASH and req.money_som > 0 and not cash_received:
            raise ApiError('cash_not_received', 422)
        wallet = lock_wallet(req.member)
        now = timezone.now()
        if req.points:
            spend_reserved(wallet, req.points, req, at=now)
        req.mark(RequestStatus.CONFIRMED, now)
        req.confirmed_at = req.closed_at = now
        req.confirmed_by = staff
        req.cash_received = bool(cash_received) or req.method != PaymentMethod.CASH
        req.escalated = False
        _clear_schedule(req)
        req.credit_due_at = now + timedelta(milliseconds=ps.credit_delay_ms)
        req.save()
    _after_change(req, wallet=wallet)
    from .tasks import credit_request_task
    transaction.on_commit(lambda: _enqueue(credit_request_task, req.pk, ps.credit_delay_ms / 1000))
    return req


def credit_request(req_id):
    with transaction.atomic():
        req = _lock_request(req_id)
        if req.status != RequestStatus.CONFIRMED:
            return req
        wallet = lock_wallet(req.member)
        now = timezone.now()
        if req.cashback:
            # +P во все три счётчика; повтор начисления той же заявки — та же проводка
            accrue(wallet, req.cashback, at=now, request=req, idempotency_key=f'cashback:{req.pk}')
        req.mark(RequestStatus.CREDITED, now)
        req.credited_at = now
        req.credit_due_at = None
        req.save()
        if req.cashback:
            evaluate(wallet, now)  # задания (по начисленным заявкам) и повышение уровня
    _after_change(req, wallet=wallet)
    from apps.notifications.services import notify_request_credited
    transaction.on_commit(lambda: notify_request_credited(req.pk))
    return req


def recalc_for_total(req, new_total, available_with_reserve):
    rules = Rules.from_snapshot(req.rules)
    return compute_split(new_total, rules, available_with_reserve, req.requested_points_som)


def adjust_preview(req, new_total):
    from apps.loyalty.services import get_wallet
    wallet = get_wallet(req.member)
    return recalc_for_total(req, int(new_total), wallet.available + req.points)


def adjust_request(req_id, new_total, staff=None, reason='', expected_outlets=None):
    """
    Правка суммы — только в pending. Запрошенные pointsSom урезаются до лимита от новой суммы
    и до баланса (available + текущий резерв заявки); originalTotal запоминается один раз.
    """
    new_total = int(new_total)
    if new_total <= 0:
        raise ApiError('amount_out_of_range', 422)
    with transaction.atomic():
        req = _lock_request(req_id)
        if expected_outlets is not None and req.outlet_id not in expected_outlets:
            raise ApiError('outlet_forbidden', 403)
        if req.status != RequestStatus.PENDING:
            raise ApiError('invalid_status', 409, extra={'status': req.status})
        wallet = lock_wallet(req.member)
        split = recalc_for_total(req, new_total, wallet.available + req.points)
        delta = split.points - req.points
        if delta:
            change_reserved(wallet, delta, request=req)
        if req.original_total is None:
            req.original_total = req.total
        old_money = req.money_som
        req.total, req.points_som, req.points = split.total, split.points_som, split.points
        req.money_som, req.cashback = split.money_som, split.cashback
        if req.check_amount is not None:
            req.check_amount = split.total
        if req.money_som > 0 and req.method is None:
            req.method = PaymentMethod.CASH  # доплата на ресепшене
        req.adjusted_by = staff
        req.adjust_reason = (reason or '').strip()
        req.escalated = False
        req.proposed_total = None
        timeline = dict(req.timeline)
        req.adjusted_at = timezone.now()
        timeline['adjusted'] = iso(req.adjusted_at)
        req.timeline = timeline
        req.save()
        payment = getattr(req, 'payment', None)
        if payment is not None and req.money_som < old_money:
            from apps.payments.services import refund_payment
            diff = min(old_money - req.money_som, payment.amount - payment.refunded_amount)
            if diff > 0:
                transaction.on_commit(lambda: refund_payment(payment.pk, diff, 'adjusted_down'))
    _after_change(req, wallet=wallet)
    return req


# ---------------------------------------------------------------- фон

def _enqueue(task, req_id, countdown):
    try:
        task.apply_async(args=[req_id], countdown=max(0, countdown))
    except Exception:  # брокер недоступен — подхватит периодическая задача
        log.warning('enqueue failed for %s, periodic job will pick it up', req_id)


def process_due(now=None):
    """Периодически: автоподтверждение, начисление с задержкой, автоотказ просроченных pending."""
    now = now or timezone.now()
    done = {'confirmed': 0, 'credited': 0, 'expired': 0}
    for rid in CashbackRequest.objects.filter(status=RequestStatus.PENDING, auto_confirm_at__lte=now) \
            .values_list('pk', flat=True)[:500]:
        try:
            confirm_request(rid)
            done['confirmed'] += 1
        except ApiError:
            pass
    for rid in CashbackRequest.objects.filter(status=RequestStatus.CONFIRMED, credit_due_at__lte=now) \
            .values_list('pk', flat=True)[:500]:
        credit_request(rid)
        done['credited'] += 1
    for rid in CashbackRequest.objects.filter(status=RequestStatus.PENDING, expires_at__lte=now) \
            .values_list('pk', flat=True)[:500]:
        try:
            reject_request(rid, code=RejectReason.EXPIRED)
            done['expired'] += 1
        except ApiError:
            pass
    return done
