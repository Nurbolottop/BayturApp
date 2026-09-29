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


def check_not_own(user, req):
    from apps.members.auth import normalize_phone
    if not user.phone or not req.member.phone:
        return
    try:
        phone = normalize_phone(user.phone)
    except ApiError:
        phone = user.phone
    if phone == req.member.phone:
        raise ApiError('own_account', 403)


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
