"""
Жизненный цикл заявки на кешбек (ТЗ §5.1):

  pending ──confirm──▶ confirmed ──credit──▶ credited
     │
     ├──reject──▶ rejected
     └──cancel──▶ cancelled

Продажа кассира по QR клиента (POST /staff/sales, apps.cashback.desk.sale):
  баллы — awaiting_client ──клиент approve──▶ confirmed; decline / не успел ──▶ rejected;
  QR    — awaiting_payment ──оплата прошла──▶ confirmed; истекло ──▶ rejected;
  кассир отменяет свою продажу до cancel_until из любого статуса, кроме rejected/cancelled (cancel_sale).

Отмена клиентом и отказ — только из pending. Каждый переход пишется в timeline.
Резерв баллов: pending держит points в reserved; confirm списывает их (spend);
credit начисляет кешбек (cashback, растит lifetime).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.i18n import iso, tr
from apps.catalog.models import ONLINE_METHODS, Item, PaymentMethod
from apps.common.errors import ApiError
from apps.common.models import ProgramSettings
from apps.common.realtime import publish_member, publish_outlets
from apps.loyalty.engine import evaluate
from apps.loyalty.services import accrue, change_reserved, lock_wallet, publish_wallet, spend_reserved

from .calc import Rules, compute_split, compute_total, resolve_rules
from .models import OPEN_STATUSES, CashbackRequest, RejectReason, RequestStatus

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
    total, rules.promotion = _with_promotions(item, total, quantity, member, now)
    if available is None:
        from apps.loyalty.services import get_wallet
        available = get_wallet(member).available
    split = compute_split(total, rules, available, points_som)
    return item, rules, split, available


def _with_promotions(item, total, quantity, member, now):
    """Цена с лучшей подходящей акцией (базовая цена услуги не меняется). → (сумма, снимок акции или None)."""
    from apps.catalog.promotions import best_price
    if item.pricing_type == 'check':
        return total, None
    promo_total, snap = best_price(item, quantity, member, now)
    return (promo_total, snap) if snap else (total, None)


def promotion_payload(snap, lang=None):
    if not snap:
        return None
    gift = snap.get('gift')
    return {'id': snap['id'], 'title': tr(snap['title'], lang), 'kind': snap['kind'], 'basePrice': snap['basePrice'],
            'discount': snap['discount'],
            'gift': {'itemId': gift['itemId'], 'title': tr(gift['title'], lang)} if gift else None}


def quote_payload(member, data):
    item, rules, split, available = quote(member, data.get('itemId'), data.get('quantity'),
                                          data.get('checkAmount'), data.get('pointsSom'), data.get('method'))
    return {
        **split.as_dict(),
        'maxPointsSom': split.max_points_som,
        'availablePoints': available,
        'methods': rules.methods if split.money_som > 0 else [],
        'bonuses': rules.bonuses,
        'promotion': promotion_payload(getattr(rules, 'promotion', None)),
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


def create_request(member, data, idempotency_key=None, created_by=None, extra=None):
    """
    Клиент присылает только ввод; суммы, правила и кешбек пересчитываются здесь.
    Атомарно, с блокировкой кошелька. Повтор с тем же Idempotency-Key → та же заявка.
    created_by — продажа кассира: способ оплаты выбирает кассир (наличные, карта, QR), правила раздела
    и оплаченный заранее платёж не проверяются; extra — поля заявки (cancel_until, duplicate_of…).
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
    if not data.get('_noPromotions'):
        total, promotion = _with_promotions(item, total, quantity, member, now)
    else:
        promotion = None
    method = data.get('method') or None
    payment_id = data.get('paymentId') or None

    try:
        with transaction.atomic():
            wallet = lock_wallet(member)
            split = compute_split(total, rules, wallet.available, data.get('pointsSom'), strict=True)

            if split.money_som == 0:
                method = None
            elif created_by is None and (method is None or method not in rules.methods):
                raise ApiError('method_not_allowed', 422)
            elif method is None:
                raise ApiError('method_not_allowed', 422)

            payment = None
            if method in ONLINE_METHODS and created_by is None:
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
                promotion=promotion, created_by=created_by,
                is_test=member.is_test, created_at=now, **(extra or {}),
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
    if req.method in ONLINE_METHODS and created_by is None:
        transaction.on_commit(lambda: _notify_staff_paid_online(req.pk))
    return req, True


def _notify_staff_paid_online(req_id):
    from apps.notifications.tasks import notify_staff_paid_online_task
    try:
        notify_staff_paid_online_task.delay(req_id)
    except Exception:
        log.warning('broker unavailable, staff push inline')
        from apps.notifications.services import notify_staff_paid_online
        notify_staff_paid_online(req_id)


# ---------------------------------------------------------------- переходы

def _lock_request(req_id):
    return CashbackRequest.objects.select_for_update().select_related('member', 'item').get(pk=req_id)


def _after_change(req, staff_event='request.updated', wallet=None):
    from .serializers import request_payload, staff_request_payload
    publish_member(req.member_id, 'request.updated', request_payload(req, lang=req.member.language))
    if wallet is not None:
        publish_wallet(req.member, wallet)
    publish_outlets([req.outlet_id], staff_event, staff_request_payload(req), category_id=req.item.category_id)


def _release_and_refund(req, wallet, reason):
    if req.points:
        change_reserved(wallet, -req.points, request=req)
    payment = getattr(req, 'payment', None)
    if payment is not None:
        from apps.payments.services import close_unpaid, refund_payment
        # QR кассира ещё не оплачен — закрываем, чтобы поздняя оплата не прошла (провайдеру ответим отказом)
        transaction.on_commit(lambda: close_unpaid(payment.pk))
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


def reject_request(req_id, staff=None, code=RejectReason.OTHER, comment='', expected_outlets=None,
                   statuses=(RequestStatus.PENDING,)):
    with transaction.atomic():
        req = _lock_request(req_id)
        if expected_outlets is not None and req.outlet_id not in expected_outlets:
            raise ApiError('outlet_forbidden', 403)
        if req.status not in statuses:
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
    if code != RejectReason.CLIENT_DECLINED:  # отказался сам — сообщать нечего
        from apps.notifications.services import notify_request_rejected
        transaction.on_commit(lambda: notify_request_rejected(req.pk))
    return req


def confirm_request(req_id, staff=None, cash_received=False, statuses=(RequestStatus.PENDING,)):
    ps = ProgramSettings.get()
    with transaction.atomic():
        req = _lock_request(req_id)
        if req.status not in statuses:
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
    """Заявка, оплаченная баллами, остаётся оплаченной баллами целиком — или правка отклоняется."""
    rules = Rules.from_snapshot(req.rules)
    rules.max_points_share = Decimal('1')  # снимок старых заявок мог хранить лимит категории
    requested = new_total if req.points_som > 0 else 0
    return compute_split(new_total, rules, available_with_reserve, requested, strict=True)


def adjust_preview(req, new_total):
    from apps.loyalty.services import get_wallet
    wallet = get_wallet(req.member)
    return recalc_for_total(req, int(new_total), wallet.available + req.points)


def adjust_request(req_id, new_total, staff=None, reason='', expected_outlets=None):
    """
    Правка суммы — только в pending. Оплата «всё или ничего»: заявка баллами списывает баллами всю новую
    сумму (баланс = available + текущий резерв заявки; не хватает → insufficient_points), денежная остаётся
    денежной. originalTotal запоминается один раз.
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
        req.requested_points_som = split.points_som
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


# ---------------------------------------------------------------- продажа кассира: ответ клиента, оплата, отмена

def approve_by_client(member, req_id):
    """Клиент подтвердил списание баллов (charge.confirm). Повтор после подтверждения — та же заявка."""
    req = CashbackRequest.objects.filter(pk=req_id, member=member).first()
    if req is None:
        raise ApiError('not_found', 404)
    if req.status in (RequestStatus.CONFIRMED, RequestStatus.CREDITED) and 'clientApproved' in (req.timeline or {}):
        return req
    if req.status != RequestStatus.AWAITING_CLIENT or (req.confirm_until and req.confirm_until <= timezone.now()):
        raise ApiError('invalid_status', 409, extra={'status': req.status})
    with transaction.atomic():
        locked = _lock_request(req.pk)
        timeline = dict(locked.timeline)
        timeline['clientApproved'] = iso(timezone.now())
        locked.timeline = timeline
        locked.save(update_fields=['timeline'])
        req = confirm_request(req.pk, staff=locked.created_by, cash_received=True,
                              statuses=(RequestStatus.AWAITING_CLIENT,))
    return req


def decline_by_client(member, req_id):
    req = CashbackRequest.objects.filter(pk=req_id, member=member).first()
    if req is None:
        raise ApiError('not_found', 404)
    return reject_request(req.pk, code=RejectReason.CLIENT_DECLINED, statuses=(RequestStatus.AWAITING_CLIENT,))


def on_payment_status(payment_id):
    """Оплата QR кассира: прошла → продажа подтверждена; не прошла / истекла → отклонена."""
    from apps.payments.models import Payment, PaymentStatus
    p = Payment.objects.filter(pk=payment_id, request__isnull=False).first()
    if p is None:
        return None
    req = CashbackRequest.objects.get(pk=p.request_id)
    if p.status == PaymentStatus.PAID:
        if req.status == RequestStatus.AWAITING_PAYMENT:
            return confirm_request(req.pk, staff=req.created_by, cash_received=True,
                                   statuses=(RequestStatus.AWAITING_PAYMENT,))
        if req.status in (RequestStatus.REJECTED, RequestStatus.CANCELLED):
            from apps.payments.services import refund_payment  # оплатили уже после отмены — деньги назад
            refund_payment(p.pk, p.amount - p.refunded_amount, f'late:{req.status}')
    elif p.status in (PaymentStatus.FAILED, PaymentStatus.EXPIRED) and req.status == RequestStatus.AWAITING_PAYMENT:
        code = RejectReason.EXPIRED if p.status == PaymentStatus.EXPIRED else RejectReason.PAYMENT_FAILED
        return reject_request(req.pk, code=code, statuses=(RequestStatus.AWAITING_PAYMENT,))
    return req


CANCELLABLE = (*OPEN_STATUSES, RequestStatus.CONFIRMED, RequestStatus.CREDITED)


def cancel_sale(req_id, staff, reason, director=False):
    """
    Отмена продажи: кассир — только свою и до cancel_until (позже 409 cancel_expired), директор — любую.
    Кешбек отзывается, списанные баллы возвращаются, резерв снимается, оплата по QR возвращается;
    наличные и карта выпадают из итога смены (он считается по статусу).
    """
    from apps.loyalty.engine import _request_fields, post_operation, reverse_cashback
    from apps.loyalty.models import OperationKind
    reason = (reason or '').strip()
    if not reason:
        raise ApiError('validation_error', 400, extra={'fields': {'reason': ['обязательно']}})
    now = timezone.now()
    with transaction.atomic():
        req = _lock_request(req_id)
        if not director:
            if req.created_by_id != staff.pk:
                raise ApiError('permission_denied', 403, message='Отменить можно только свою операцию')
            if req.status in CANCELLABLE and (req.cancel_until is None or req.cancel_until <= now):
                raise ApiError('cancel_expired', 409, message='Время на отмену вышло — отменяет директор')
        if req.status not in CANCELLABLE:
            raise ApiError('invalid_status', 409, extra={'status': req.status})
        before = req.status
        wallet = lock_wallet(req.member)
        if before == RequestStatus.CREDITED and req.cashback:
            reverse_cashback(req, actor=staff, reason=reason)
            wallet = lock_wallet(req.member)
        if before in (RequestStatus.CONFIRMED, RequestStatus.CREDITED):
            if req.points:  # баллы уже списаны — возвращаем
                post_operation(wallet, OperationKind.REFUND, req.points, idempotency_key=f'refund:{req.pk}',
                               reason=reason, author=staff, activity=False, at=now, **_request_fields(req))
            payment = getattr(req, 'payment', None)
            if payment is not None:
                from apps.payments.services import refund_payment
                transaction.on_commit(lambda: refund_payment(payment.pk, payment.amount - payment.refunded_amount,
                                                             'cancelled', author=staff))
        else:
            _release_and_refund(req, wallet, 'cancelled')
        req.mark(RequestStatus.CANCELLED, now)
        req.cancelled_at = req.closed_at = now
        req.cancelled_by = staff
        req.cancel_reason = reason
        req.escalated = False
        req.credit_due_at = None
        _clear_schedule(req)
        req.save()
        from .models import FiscalReceipt
        receipt = FiscalReceipt.objects.filter(request=req).first()
        if receipt is not None:  # чек освобождается: кассир может принять его заново (с верной услугой)
            receipt.key = f'{receipt.key}#cancelled-{req.pk}'[:200]
            receipt.save(update_fields=['key'])
    _after_change(req, wallet=wallet)
    from apps.notifications.services import notify_request_cancelled
    transaction.on_commit(lambda: notify_request_cancelled(req.pk))
    return req, before


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
    # продажи кассира: клиент не подтвердил баллы / не оплатил QR вовремя
    for rid in CashbackRequest.objects.filter(status=RequestStatus.AWAITING_CLIENT, confirm_until__lte=now) \
            .values_list('pk', flat=True)[:500]:
        try:
            reject_request(rid, code=RejectReason.CLIENT_TIMEOUT, statuses=(RequestStatus.AWAITING_CLIENT,))
            done['expired'] += 1
        except ApiError:
            pass
    for req in CashbackRequest.objects.filter(status=RequestStatus.AWAITING_PAYMENT, confirm_until__lte=now) \
            .select_related('payment')[:100]:
        payment = getattr(req, 'payment', None)
        if payment is not None:
            from apps.payments.services import check_payment
            if check_payment(payment).status == 'paid':  # вебхук мог не дойти — спрашиваем провайдера
                continue
        try:
            reject_request(req.pk, code=RejectReason.EXPIRED, statuses=(RequestStatus.AWAITING_PAYMENT,))
            done['expired'] += 1
        except ApiError:
            pass
    return done
