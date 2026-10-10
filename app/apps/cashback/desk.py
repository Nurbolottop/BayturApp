"""
Действия сотрудника/менеджера с заявками — единая реализация для API сотрудника (§8.5),
админ-API (§7.3) и веб-панели. Ограничения §8.3:
- только заявки своих точек (владелец/менеджер — все);
- нельзя обработать заявку своего клиентского аккаунта (связь по телефону);
- правка суммы больше N % или кешбек выше лимита → на подтверждение менеджеру (эскалация);
- сотрудник фиксируется в заявке и в аудит-логе;
- повторная обработка → 409 invalid_status с актуальным статусом.
Каждая функция принимает HTTP-запрос (для аудита: сотрудник + IP).
"""
from datetime import datetime, time

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.common.models import ProgramSettings

from . import services
from .models import CashbackRequest, RejectReason, RequestStatus

STAFF_REJECT_REASONS = [RejectReason.NOT_PROVIDED, RejectReason.WRONG_AMOUNT, RejectReason.DUPLICATE,
                        RejectReason.OTHER]


# ---------------------------------------------------------------- область и проверки

def outlet_scope(user):
    """None — все точки; иначе множество id точек сотрудника."""
    return user.outlet_ids if user.is_outlet_bound else None


def scoped_requests(user):
    qs = CashbackRequest.objects.select_related('member', 'payment', 'item')
    scope = outlet_scope(user)
    if scope is not None:
        qs = qs.filter(outlet_id__in=scope)
    return qs


def get_scoped(user, request_id):
    req = scoped_requests(user).filter(pk=request_id).first()
    if req is None:
        raise ApiError('not_found', 404)
    return req


def check_not_own_member(user, member):
    from apps.members.auth import normalize_phone
    if not user.phone or not member.phone:
        return
    try:
        phone = normalize_phone(user.phone)
    except ApiError:
        phone = user.phone
    if phone == member.phone:
        raise ApiError('own_account', 403)


def check_not_own(user, req):
    check_not_own_member(user, req.member)


def needs_manager(user):
    """Владелец/менеджер эскалацию не проходят."""
    return user.is_outlet_bound


def exceeds_threshold(req, new_total):
    base = req.original_total or req.total
    pct = ProgramSettings.get().staff_adjust_threshold_percent
    return abs(new_total - base) * 100 > base * pct


def _pending(req):
    if req.status != RequestStatus.PENDING:
        raise ApiError('invalid_status', 409, extra={'status': req.status})


# ---------------------------------------------------------------- эскалация

def _escalate(request, req, reason, action, before=None, proposed_total=None, cash=None, comment=''):
    with transaction.atomic():
        locked = CashbackRequest.objects.select_for_update().get(pk=req.pk)
        _pending(locked)
        locked.escalated = True
        locked.escalation_reason = reason
        locked.proposed_by = request.user
        if proposed_total is not None:
            locked.proposed_total = proposed_total
            locked.adjust_reason = comment
        if cash:
            locked.cash_received = True
        locked.save()
    after = {'reason': reason, 'cashback': locked.cashback} if proposed_total is None else \
        {'proposedTotal': proposed_total}
    audit(request, action, locked, before=before, after=after, comment=comment)
    services._after_change(locked)
    return locked


# ---------------------------------------------------------------- действия

def confirm(request, request_id, cash_received=False):
    """→ (req, escalated). Кешбек выше лимита у сотрудника точки уходит менеджеру."""
    user = request.user
    req = get_scoped(user, request_id)
    check_not_own(user, req)
    _pending(req)
    if req.escalated and needs_manager(user):
        raise ApiError('needs_manager', 409)
    if needs_manager(user) and req.cashback > ProgramSettings.get().staff_cashback_limit_points:
        return _escalate(request, req, 'cashback_limit', 'request.escalate', cash=cash_received), True
    req = services.confirm_request(req.pk, staff=user, cash_received=cash_received)
    audit(request, 'request.confirm', req, before={'status': RequestStatus.PENDING},
          after={'status': req.status, 'cashReceived': cash_received})
    return req, False


def adjust_preview(request, request_id, total):
    req = get_scoped(request.user, request_id)
    if not total or total <= 0:
        raise ApiError('amount_out_of_range', 422)
    split = services.adjust_preview(req, total)
    return {**split.as_dict(), 'maxPointsSom': split.max_points_som,
            'cashToCollect': split.money_som if req.method in ('cash', None) else 0,
            'needsManager': needs_manager(request.user) and exceeds_threshold(req, split.total)}


def adjust(request, request_id, total, reason):
    """→ (req, escalated). Причина обязательна; правка больше N % у сотрудника точки уходит менеджеру."""
    user = request.user
    req = get_scoped(user, request_id)
    check_not_own(user, req)
    reason = (reason or '').strip()
    if not reason:
        raise ApiError('validation_error', 400, extra={'fields': {'reason': ['обязательно']}})
    if not total or total <= 0:
        raise ApiError('amount_out_of_range', 422)
    _pending(req)
    before = {'total': req.total, 'pointsSom': req.points_som, 'cashback': req.cashback}
    if needs_manager(user) and exceeds_threshold(req, total):
        return _escalate(request, req, 'adjust_threshold', 'request.adjust_escalate', before=before,
                         proposed_total=total, comment=reason), True
    req = services.adjust_request(req.pk, total, staff=user, reason=reason, expected_outlets=outlet_scope(user))
    audit(request, 'request.adjust', req, before=before,
          after={'total': req.total, 'pointsSom': req.points_som, 'cashback': req.cashback}, comment=reason)
    return req, False


def reject(request, request_id, code, comment=''):
    user = request.user
    req = get_scoped(user, request_id)
    check_not_own(user, req)
    if code not in STAFF_REJECT_REASONS:
        raise ApiError('validation_error', 400, extra={'fields': {'reasonCode': ['выберите причину']}})
    comment = (comment or '').strip()
    if code == RejectReason.OTHER and not comment:
        raise ApiError('validation_error', 400, extra={'fields': {'comment': ['обязательно для «другое»']}})
    req = services.reject_request(req.pk, staff=user, code=code, comment=comment, expected_outlets=outlet_scope(user))
    audit(request, 'request.reject', req, before={'status': RequestStatus.PENDING},
          after={'status': req.status, 'code': code}, comment=comment)
    return req


def approve_escalation(request, request_id, confirm_after_adjust=False, cash_received=None):
    """
    Менеджер/владелец одобряет эскалацию:
    - adjust_threshold — применяется предложенная сумма (confirm_after_adjust — сразу и подтвердить);
    - cashback_limit — заявка подтверждается.
    """
    user = request.user
    if not user.can('requests.approve_escalated'):
        raise ApiError('permission_denied', 403)
    req = get_scoped(user, request_id)
    check_not_own(user, req)
    _pending(req)
    if not req.escalated:
        raise ApiError('invalid_status', 409, extra={'status': req.status, 'escalated': False})
    cash = bool(cash_received) or req.cash_received or req.method != 'cash'
    before = {'total': req.total, 'cashback': req.cashback, 'escalationReason': req.escalation_reason,
              'proposedTotal': req.proposed_total, 'proposedBy': req.proposed_by_id}
    if req.proposed_total:
        req = services.adjust_request(req.pk, req.proposed_total, staff=user, reason=req.adjust_reason)
        if confirm_after_adjust:
            req = services.confirm_request(req.pk, staff=user, cash_received=cash)
    else:
        req = services.confirm_request(req.pk, staff=user, cash_received=cash)
    audit(request, 'request.approve_escalation', req, before=before,
          after={'status': req.status, 'total': req.total, 'cashback': req.cashback})
    return req


def decline_escalation(request, request_id, comment=''):
    """Предложение сотрудника отклонено: заявка остаётся pending с прежней суммой и возвращается в очередь."""
    user = request.user
    if not user.can('requests.approve_escalated'):
        raise ApiError('permission_denied', 403)
    with transaction.atomic():
        req = CashbackRequest.objects.select_for_update().get(pk=get_scoped(user, request_id).pk)
        if req.status != RequestStatus.PENDING or not req.escalated:
            raise ApiError('invalid_status', 409, extra={'status': req.status, 'escalated': req.escalated})
        before = {'escalationReason': req.escalation_reason, 'proposedTotal': req.proposed_total}
        req.escalated = False
        req.escalation_reason = ''
        req.proposed_total = None
        req.save(update_fields=['escalated', 'escalation_reason', 'proposed_total'])
    audit(request, 'request.decline_escalation', req, before=before, after={'escalated': False},
          comment=(comment or '').strip())
    services._after_change(req)
    return req


# ---------------------------------------------------------------- очередь, поиск, смена

def queue(user, outlet=None):
    """Заявки pending своих точек, старые сверху."""
    qs = scoped_requests(user).filter(status=RequestStatus.PENDING).select_related('outlet').order_by('created_at')
    if outlet:
        qs = qs.filter(outlet_id=outlet)
    return qs


def search_members(q):
    """memberId (с BT- и без) или хвост телефона; удалённые окончательно не ищутся."""
    from apps.members.models import Member, MemberStatus
    q = (q or '').strip()
    if len(q) < 3:
        return []
    cond = Q(member_id__iexact=q) | Q(member_id__iexact=f'BT-{q}')
    digits = ''.join(ch for ch in q if ch.isdigit())
    if len(digits) >= 6:
        cond |= Q(phone__endswith=digits[-9:])
    return list(Member.objects.filter(cond).exclude(status=MemberStatus.PURGED)[:10])


def shift(user):
    """Итог смены: подтверждено / отклонено сегодня, наличные для сверки кассы."""
    start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    confirmed = CashbackRequest.objects.filter(confirmed_by=user, confirmed_at__gte=start) \
        .select_related('member', 'outlet', 'payment').order_by('-confirmed_at')
    rejected = CashbackRequest.objects.filter(rejected_by=user, rejected_at__gte=start) \
        .select_related('member', 'outlet', 'payment').order_by('-rejected_at')
    return {
        'date': timezone.localdate(),
        'confirmed': list(confirmed),
        'rejected': list(rejected),
        'adjusted_count': CashbackRequest.objects.filter(adjusted_by=user, adjusted_at__gte=start).count(),
        'cash_total': confirmed.filter(method='cash').aggregate(s=Sum('money_som'))['s'] or 0,
        'cashback_total': confirmed.aggregate(s=Sum('cashback'))['s'] or 0,
    }


# ---------------------------------------------------------------- оплата баллами по QR клиента

PAY_SALT = 'baytur.desk-pay'
PAY_TTL = 600  # 10 минут после скана QR


def make_pay_token(user, member):
    """Разрешение на списание: выдаётся только при скане свежего QR с телефона клиента."""
    from django.core import signing
    return signing.dumps({'m': member.pk, 's': user.pk}, salt=PAY_SALT)


def read_pay_token(user, token):
    from django.core import signing

    from apps.members.models import Member, MemberStatus
    try:
        data = signing.loads(token or '', salt=PAY_SALT, max_age=PAY_TTL)
    except signing.BadSignature:
        raise ApiError('qr_invalid', 400, message='Отсканируйте QR клиента ещё раз')
    if data.get('s') != user.pk:
        raise ApiError('qr_invalid', 400, message='Отсканируйте QR клиента ещё раз')
    member = Member.objects.filter(pk=data['m'], status=MemberStatus.ACTIVE).first()
    if member is None:
        raise ApiError('account_frozen', 403)
    return member


def pay_items(user):
    """Услуги, которые сотрудник может провести: только своих точек (владелец/менеджер — все)."""
    from apps.catalog.models import Item
    qs = Item.objects.active().select_related('category', 'outlet').order_by('category__sort_order', 'sort_order')
    scope = outlet_scope(user)
    return qs.filter(outlet_id__in=scope) if scope is not None else qs


def _pay_item(user, item_id):
    item = pay_items(user).prefetch_related('promos').filter(pk=item_id).first()
    if item is None:
        raise ApiError('item_not_found', 404)
    return item


def points_quote(user, member, item_id, quantity=None, check_amount=None):
    """
    Хватает ли баллов, чтобы оплатить услугу целиком. Баланс клиента сотруднику не показывается —
    только «хватает» или «не хватает N сом». Лимита доли по разделам нет: reason — только 'balance'.
    """
    from django.utils import timezone

    from apps.loyalty.services import get_wallet

    from .calc import balance_som, compute_total, resolve_rules
    item = _pay_item(user, item_id)
    rules = resolve_rules(item, member, ProgramSettings.get(), timezone.now())
    total, quantity = compute_total(item, quantity, check_amount)
    total, promotion = services._with_promotions(item, total, quantity, member, timezone.now())
    available = get_wallet(member).available
    balance = balance_som(available, rules)
    enough = balance >= total
    return {
        'itemId': item.pk, 'total': total, 'quantity': quantity, 'points': total * rules.points_per_som,
        'enough': enough, 'shortSom': max(0, total - balance), 'reason': None if enough else 'balance',
        'promotion': services.promotion_payload(promotion),
        'limitPercent': 100,  # устарело: лимита доли больше нет, оставлено для совместимости
    }


def charge_points(request, pay_token, item_id, quantity=None, check_amount=None):
    """
    Оплата баллами по QR: заявка «оплачено баллами» сразу подтверждается этим сотрудником (баллы списываются,
    кешбек 0). Напрямую сотрудник баллы не списывает — только через заявку (ТЗ §8.3).
    """
    user = request.user
    member = read_pay_token(user, pay_token)
    quote = points_quote(user, member, item_id, quantity, check_amount)
    if not quote['enough']:
        raise ApiError('insufficient_points', 422, extra={'shortSom': quote['shortSom']})
    check_not_own_member(user, member)
    with transaction.atomic():  # заявка и подтверждение — вместе, без «висящего» резерва при сбое
        req, _ = services.create_request(member, {
            'itemId': item_id, 'quantity': quote['quantity'],
            'checkAmount': quote['total'] if check_amount is not None else None,
            'pointsSom': quote['total'], 'method': None})
        req = services.confirm_request(req.pk, staff=user, cash_received=True)
    audit(request, 'request.points_payment', req,
          after={'member': member.member_id, 'total': req.total, 'points': req.points})
    return req


# ---------------------------------------------------------------- наличные по QR фискального чека

def _receipt_used(key):
    from .models import FiscalReceipt
    used = FiscalReceipt.objects.select_related('accepted_by', 'outlet').filter(key=key).first()
    if used is not None:
        raise ApiError('receipt_used', 409, extra={
            'acceptedAt': used.accepted_at.isoformat(), 'requestId': used.request_id,
            'acceptedBy': used.accepted_by_id, 'acceptedByName': getattr(used.accepted_by, 'full_name', '') or None,
            'outlet': used.outlet_id})


def _cash_input(item, amount):
    """Сумма чека → ввод заявки: «по сумме чека» — сумма; фиксированная цена — количество, сумма должна делиться."""
    if item.pricing_type == 'check':
        return {'checkAmount': amount, 'quantity': None}
    if not item.price or amount % item.price:
        raise ApiError('receipt_amount_mismatch', 422, extra={'price': item.price, 'amount': amount})
    return {'checkAmount': None, 'quantity': amount // item.price}


def _client_cash_request(user, member, request_id, item_id):
    """Заявка «наличными», которую клиент заранее создал в приложении, — чек привязывается к ней."""
    req = get_scoped(user, request_id)
    if req.member_id != member.pk or req.status != RequestStatus.PENDING or req.points:
        raise ApiError('invalid_status', 409, extra={'status': req.status})
    if str(req.item_id) != str(item_id):
        raise ApiError('validation_error', 400, extra={'fields': {'itemId': ['не совпадает с заявкой клиента']}})
    return req


def receipt_preview(user, pay_token, item_id, receipt_qr, request_id=None):
    """Что увидит сотрудник после скана чека: сумма, кешбек клиенту; чек ещё не принят."""
    from django.utils import timezone as tz

    from .calc import compute_split, compute_total, resolve_rules
    from .receipts import parse_receipt
    member = read_pay_token(user, pay_token)
    receipt = parse_receipt(receipt_qr)
    _receipt_used(receipt['key'])
    item = _pay_item(user, item_id)
    if request_id:
        _client_cash_request(user, member, request_id, item_id)
    rules = resolve_rules(item, member, ProgramSettings.get(), tz.now())
    if 'cash' not in rules.methods:
        raise ApiError('method_not_allowed', 422)
    data = _cash_input(item, receipt['amount'])
    total, quantity = compute_total(item, data['quantity'], data['checkAmount'])
    split = compute_split(total, rules, 0, 0)
    return {'itemId': item.pk, 'amount': receipt['amount'], 'total': total, 'quantity': quantity,
            'cashback': split.cashback, 'rate': str(split.rate), 'receiptNumber': receipt['key'],
            'requestId': request_id or None,
            # данные чека из налоговой (verified=false — налоговая не ответила, сумма взята из QR)
            'receipt': receipt.get('details')}


def receipt_accept(request, pay_token, item_id, receipt_qr, request_id=None):
    """
    «Принять оплату» по чеку: операция проводится сразу (без очереди подтверждения), кешбек начисляется
    клиенту. Чек запоминается — повторный скан даёт receipt_used.
    """
    from django.db import IntegrityError

    from apps.catalog.models import PaymentMethod

    from .models import FiscalReceipt
    from .receipts import parse_receipt
    user = request.user
    member = read_pay_token(user, pay_token)
    receipt = parse_receipt(receipt_qr)
    _receipt_used(receipt['key'])
    item = _pay_item(user, item_id)
    check_not_own_member(user, member)
    data = _cash_input(item, receipt['amount'])
    try:
        with transaction.atomic():
            if request_id:
                req = _client_cash_request(user, member, request_id, item_id)
                if req.total != receipt['amount'] or req.method != PaymentMethod.CASH:
                    req = services.adjust_request(req.pk, receipt['amount'], staff=user, reason='По фискальному чеку',
                                                  expected_outlets=outlet_scope(user))
            else:
                req, _ = services.create_request(member, {
                    'itemId': item.pk, 'quantity': data['quantity'], 'checkAmount': data['checkAmount'],
                    'pointsSom': 0, 'method': PaymentMethod.CASH, '_noPromotions': True})
            FiscalReceipt.objects.create(key=receipt['key'], raw=receipt['raw'], amount=receipt['amount'],
                                         fields=receipt['fields'], request=req, outlet=req.outlet, accepted_by=user)
            req = services.confirm_request(req.pk, staff=user, cash_received=True)
    except IntegrityError:
        _receipt_used(receipt['key'])  # параллельный приём того же чека
        raise
    audit(request, 'request.receipt_accepted', req,
          after={'member': member.member_id, 'total': req.total, 'receipt': receipt['key'], 'cashback': req.cashback})
    return req
