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
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.common.models import ProgramSettings

from . import services
from .models import AWAITING_STATUSES, CashbackRequest, RejectReason, RequestStatus

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
    if req.escalation_reason == SALE_THRESHOLD:  # продажа кассира выше порога — дальше выбранным способом
        req = start_sale(req)
        audit(request, 'request.approve_escalation', req, before={'status': RequestStatus.PENDING},
              after={'status': req.status})
        return req, False
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
    if req.escalation_reason == SALE_THRESHOLD:
        req = start_sale(req)  # продажа кассира выше порога: дальше — выбранным способом
    elif req.proposed_total:
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
    req = get_scoped(user, request_id)
    if req.escalation_reason == SALE_THRESHOLD and req.status == RequestStatus.PENDING:
        # продажа кассира выше порога: директор не разрешил — заявка отклоняется, резерв баллов снимается
        req = services.reject_request(req.pk, staff=user, code=RejectReason.OTHER,
                                      comment=(comment or '').strip() or 'Директор не разрешил')
        audit(request, 'request.decline_escalation', req, before={'escalationReason': SALE_THRESHOLD},
              after={'status': req.status}, comment=(comment or '').strip())
        return req
    with transaction.atomic():
        req = CashbackRequest.objects.select_for_update().get(pk=req.pk)
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


DONE_STATUSES = (RequestStatus.CONFIRMED, RequestStatus.CREDITED)


def shift(user, day=None):
    """
    Итог смены: оформлено (подтверждено + ждёт клиента/оплату) / отклонено / отменено за день,
    наличные и карта для сверки кассы — только по проведённым (отменённые выпадают сами).
    """
    day = day or timezone.localdate()
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = timezone.make_aware(datetime.combine(day, time.max))
    related = ('member', 'outlet', 'payment')
    confirmed = CashbackRequest.objects.filter(confirmed_by=user, confirmed_at__range=(start, end),
                                               status__in=DONE_STATUSES)
    waiting = CashbackRequest.objects.filter(created_by=user, created_at__range=(start, end),
                                             status__in=AWAITING_STATUSES)
    done = (confirmed | waiting).select_related(*related).order_by('-created_at')
    rejected = CashbackRequest.objects.filter(Q(rejected_by=user) | Q(created_by=user, rejected_by__isnull=True),
                                              status=RequestStatus.REJECTED, rejected_at__range=(start, end)) \
        .select_related(*related).order_by('-rejected_at')
    cancelled = CashbackRequest.objects.filter(Q(created_by=user) | Q(confirmed_by=user), status=RequestStatus.CANCELLED,
                                               cancelled_at__range=(start, end)) \
        .select_related(*related).order_by('-cancelled_at')
    return {
        'date': day,
        'confirmed': list(done),
        'rejected': list(rejected),
        'cancelled': list(cancelled),
        'adjusted_count': CashbackRequest.objects.filter(adjusted_by=user, adjusted_at__range=(start, end)).count(),
        'cash_total': confirmed.filter(method='cash').aggregate(s=Sum('money_som'))['s'] or 0,
        'card_total': confirmed.filter(method='card').aggregate(s=Sum('money_som'))['s'] or 0,
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


def receipt_preview(user, pay_token, item_id, receipt_qr, request_id=None, amount=None):
    """Что увидит сотрудник после скана чека: сумма, кешбек клиенту; чек ещё не принят."""
    from django.utils import timezone as tz

    from .calc import compute_split, compute_total, resolve_rules
    from .receipts import parse_receipt
    member = read_pay_token(user, pay_token)
    receipt = parse_receipt(receipt_qr, amount)
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
            # данные чека из налоговой (verified=false — налоговая не ответила, сумма взята из QR;
            # manual=true — суммы в QR нет, её ввёл кассир)
            'receipt': receipt.get('details')}


def receipt_accept(request, pay_token, item_id, receipt_qr, request_id=None, amount=None):
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
    receipt = parse_receipt(receipt_qr, amount)
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


# ---------------------------------------------------------------- продажа кассира по QR клиента (/staff/sales)

SALE_METHODS = ('points', 'cash', 'card', 'qr')
SALE_THRESHOLD = 'amount_threshold'   # причина эскалации: сумма выше порога точки
CANCEL_WINDOW = 600                   # с: кассир отменяет свою продажу 10 минут
CLIENT_CONFIRM_TTL = 120              # с: клиент подтверждает списание баллов
DUPLICATE_WINDOW = 600                # с: та же услуга тому же клиенту — повтор


def receipt_required(item):
    """Точка с фискальным чеком (ресторан): деньги — только по QR чека (/staff/cash/*)."""
    return bool(item.outlet and item.outlet.receipt_required)


def _check_sale_method(item, method, check_amount):
    if method == 'points':
        return
    if receipt_required(item):
        raise ApiError('method_not_allowed', 422, message='В этой точке деньги принимаются только по чеку')
    if item.pricing_type == 'check':
        # сумму вписал кассир — без чека принимаем её только баллами: клиент подтверждает списание сам
        raise ApiError('method_not_allowed', 422, message='Услуга по сумме чека — только баллами')


def _threshold_exceeded(user, item, total):
    limit = item.outlet.manager_threshold if item.outlet else None
    return bool(needs_manager(user) and limit and total > limit)


def find_duplicate(member, item, exclude=None):
    """Та же услуга этому клиенту за последние 10 минут (кроме отклонённых и отменённых)."""
    since = timezone.now() - timedelta(seconds=DUPLICATE_WINDOW)
    qs = CashbackRequest.objects.filter(member=member, item=item, created_at__gte=since) \
        .exclude(status__in=(RequestStatus.REJECTED, RequestStatus.CANCELLED)).order_by('-created_at')
    if exclude:
        qs = qs.exclude(pk=exclude)
    return qs.first()


def sale_quote(user, member, item_id, quantity=None, check_amount=None):
    """Расчёт до оформления: сумма по прайсу, кешбек за деньги, хватает ли баллов, порог, повтор."""
    from .calc import compute_split, resolve_rules
    q = points_quote(user, member, item_id, quantity, check_amount)
    item = _pay_item(user, item_id)
    rules = resolve_rules(item, member, ProgramSettings.get(), timezone.now())
    dup = find_duplicate(member, item)
    from apps.common.i18n import iso
    return {
        'itemId': item.pk, 'total': q['total'], 'quantity': q['quantity'],
        'cashback': compute_split(q['total'], rules, 0, 0).cashback,
        'points': q['points'], 'enough': q['enough'], 'shortSom': q['shortSom'],
        'needsManager': _threshold_exceeded(user, item, q['total']),
        'receiptRequired': receipt_required(item),
        'promotion': q['promotion'],
        'duplicate': {'requestId': dup.pk, 'at': iso(dup.created_at)} if dup else None,
    }


def sale(request, pay_token, item_id, method, quantity=None, check_amount=None, idempotency_key=None):
    """
    Кассир оформляет услугу по QR клиента. → (req, escalated).
    cash / card — сразу confirmed; points — awaiting_client (клиент подтверждает за 2 мин);
    qr — awaiting_payment (клиент платит по QR на экране кассира). Сумма выше порога точки → pending
    на решение директору (202). Повтор с тем же Idempotency-Key → та же заявка.
    """
    from apps.catalog.models import PaymentMethod
    user = request.user
    member = read_pay_token(user, pay_token)
    if idempotency_key:
        existing = CashbackRequest.objects.filter(member=member, idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing, existing.escalated
    if method not in SALE_METHODS:
        raise ApiError('validation_error', 400, extra={'fields': {'method': [' | '.join(SALE_METHODS)]}})
    item = _pay_item(user, item_id)
    check_not_own_member(user, member)
    _check_sale_method(item, method, check_amount)
    q = points_quote(user, member, item_id, quantity, check_amount)
    if method == 'points' and not q['enough']:
        raise ApiError('insufficient_points', 422, extra={'shortSom': q['shortSom']})
    escalated = _threshold_exceeded(user, item, q['total'])
    dup = find_duplicate(member, item)
    now = timezone.now()
    req_method = {'cash': PaymentMethod.CASH, 'card': PaymentMethod.CARD, 'qr': PaymentMethod.FREEDOM_PAY}.get(method)
    extra = {'cancel_until': now + timedelta(seconds=CANCEL_WINDOW), 'duplicate_of': dup.pk if dup else ''}
    if escalated:
        extra.update(escalated=True, escalation_reason=SALE_THRESHOLD, proposed_by=user)
    with transaction.atomic():
        req, created = services.create_request(member, {
            'itemId': item.pk, 'quantity': q['quantity'],
            'checkAmount': q['total'] if item.pricing_type == 'check' else None,
            'pointsSom': q['total'] if method == 'points' else 0, 'method': req_method,
        }, idempotency_key=idempotency_key, created_by=user, extra=extra)
        if not created:
            return req, req.escalated
        # продажа кассира сама не подтверждается — подтверждают кассир, клиент или оплата
        CashbackRequest.objects.filter(pk=req.pk).update(auto_confirm_at=None)
        if not escalated:
            req = start_sale(req)
    audit(request, 'request.sale', req, after={
        'member': member.member_id, 'method': method, 'total': req.total, 'status': req.status,
        'escalated': escalated, 'duplicateOf': req.duplicate_of or None})
    if escalated:
        services._after_change(req)
    return req, escalated


def start_sale(req):
    """Провести продажу выбранным способом (сразу или после одобрения директора)."""
    from apps.catalog.models import PaymentMethod
    req = CashbackRequest.objects.select_related('member', 'created_by').get(pk=req.pk)
    now = timezone.now()
    if req.points:
        _await(req, RequestStatus.AWAITING_CLIENT, now + timedelta(seconds=CLIENT_CONFIRM_TTL))
        from apps.notifications.services import notify_charge_confirm
        transaction.on_commit(lambda: notify_charge_confirm(req.pk))
        return req
    if req.method == PaymentMethod.FREEDOM_PAY:
        from apps.payments.services import STAFF_QR_LIFETIME, create_staff_payment
        create_staff_payment(req)
        _await(req, RequestStatus.AWAITING_PAYMENT, now + timedelta(seconds=STAFF_QR_LIFETIME))
        return req
    return services.confirm_request(req.pk, staff=req.created_by, cash_received=True)


def _await(req, status, until):
    with transaction.atomic():
        locked = CashbackRequest.objects.select_for_update().get(pk=req.pk)
        locked.mark(status)
        locked.confirm_until = until
        locked.escalated = False
        locked.auto_confirm_at = locked.expires_at = None
        locked.save()
    req.refresh_from_db()
    services._after_change(req)


def cancel(request, request_id, reason, director=False):
    """Кассир отменяет свою продажу до cancel_until; позже — только директор (панель, director=True)."""
    user = request.user
    req = get_scoped(user, request_id)
    if director and not user.can('requests.approve_escalated'):
        raise ApiError('permission_denied', 403)
    req, before = services.cancel_sale(req.pk, user, reason, director=director)
    audit(request, 'request.cancel', req, before={'status': before}, after={'status': req.status},
          comment=req.cancel_reason)
    return req
