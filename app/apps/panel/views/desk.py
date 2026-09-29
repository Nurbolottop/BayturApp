"""Рабочее место сотрудника (ТЗ §8): очередь, карточка заявки, действия, поиск клиента, QR, смена."""
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.cashback.serializers import REJECT_LABELS
from apps.cashback.desk import get_scoped, needs_manager, scoped_requests
from apps.catalog.models import Outlet
from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.loyalty.services import get_wallet

from .. import actions
from ..access import api_error_message, back_or, panel_view


def _int(v):
    try:
        return int(str(v).replace(' ', '').replace(' ', ''))
    except (TypeError, ValueError):
        return None


def request_card_context(request, req):
    user = request.user
    wallet = get_wallet(req.member)
    pending = req.status == 'pending'
    can_process = user.can('requests.process') and pending
    blocked_by_escalation = req.escalated and needs_manager(user)
    return {
        'req': req,
        'member_tier': wallet.tier_id,
        'title': (req.item_snapshot or {}).get('title'),
        'can_process': can_process and not blocked_by_escalation,
        'awaiting_manager': pending and req.escalated,
        'can_approve': pending and req.escalated and user.can('requests.approve_escalated'),
        'reasons': [(code, REJECT_LABELS[code]['ru']) for code in actions.STAFF_REJECT_REASONS],
        'payment': getattr(req, 'payment', None) if hasattr(req, 'payment') else None,
        'is_cash': req.method == 'cash' and req.money_som > 0,
    }


def _payment(req):
    try:
        return req.payment
    except Exception:
        return None


@panel_view('desk')
def desk(request):
    user = request.user
    outlet = request.GET.get('outlet') or ''
    items = list(actions.queue(user, outlet or None)[:200])
    outlets = Outlet.objects.filter(pk__in=user.outlet_ids) if user.is_outlet_bound else Outlet.objects.all()
    ctx = {'items': items, 'outlets': outlets, 'outlet': outlet, 'count': len(items)}
    if request.GET.get('partial'):
        return render(request, 'panel/desk/_queue.html', ctx)
    return render(request, 'panel/desk/queue.html', ctx)


@panel_view('desk')
def desk_request(request, request_id):
    try:
        req = get_scoped(request.user, request_id)
    except ApiError:
        raise Http404
    ctx = request_card_context(request, req)
    ctx['payment'] = _payment(req)
    ctx['back'] = request.GET.get('back') or '/panel/desk/'
    if request.GET.get('partial'):
        return render(request, 'panel/requests/_card.html', ctx)
    return render(request, 'panel/desk/request.html', ctx)


@require_POST
@panel_view(perm='requests.process')
def request_action(request, request_id, action):
    default = request.POST.get('next') or '/panel/desk/'
    try:
        if action == 'confirm':
            req, escalated = actions.confirm(request, request_id, bool(request.POST.get('cash_received')))
            if escalated:
                messages.warning(request, 'Кешбек выше лимита — заявка ушла на подтверждение менеджеру')
            else:
                messages.success(request, 'Заявка подтверждена — кешбек начислится автоматически')
        elif action == 'adjust':
            req, escalated = actions.adjust(request, request_id, _int(request.POST.get('total')),
                                            request.POST.get('reason'))
            if escalated:
                messages.warning(request, 'Правка больше допустимого порога — ушла на подтверждение менеджеру')
            else:
                messages.success(request, 'Сумма изменена')
        elif action == 'reject':
            actions.reject(request, request_id, request.POST.get('reason_code'), request.POST.get('comment'))
            messages.success(request, 'Заявка отклонена — клиент увидит причину')
        elif action == 'approve':
            actions.approve_escalated(request, request_id)
            messages.success(request, 'Эскалация утверждена')
        elif action == 'decline':
            actions.decline_escalation(request, request_id)
            messages.success(request, 'Эскалация отклонена, заявка вернулась в очередь')
        else:
            raise Http404
    except ApiError as e:
        msg = api_error_message(e)
        if e.code == 'invalid_status':
            from ..templatetags.panel import STATUS
            st = (e.extra or {}).get('status')
            msg = f'Заявка уже обработана: {STATUS["request"].get(st, (st,))[0]}'
        messages.error(request, msg)
    return back_or(request, default)


@require_POST
@panel_view(perm='requests.process')
def adjust_preview(request, request_id):
    try:
        data = actions.adjust_preview(request, request_id, _int(request.POST.get('total')))
    except ApiError as e:
        return JsonResponse({'error': api_error_message(e)}, status=e.status_code)
    return JsonResponse(data)


def _member_view(user, member):
    wallet = get_wallet(member)
    reqs = scoped_requests(user).filter(member=member).select_related('outlet').order_by('-created_at')[:20]
    return {'member': member, 'tier': wallet.tier_id, 'requests': list(reqs)}


@panel_view('desk')
def desk_members(request):
    q = request.GET.get('q', '').strip()
    results = [_member_view(request.user, m) for m in actions.search_members(q)] if q else []
    if q and len(q) < 3:
        messages.info(request, 'Введите хотя бы 3 символа')
    return render(request, 'panel/desk/members.html', {'q': q, 'results': results})


@require_POST
@panel_view(perm='members.view')
def desk_scan(request):
    from apps.members.auth import read_member_qr
    token = (request.POST.get('token') or '').strip()
    try:
        member = read_member_qr(token)
    except ApiError as e:
        messages.error(request, api_error_message(e))
        return redirect('panel:desk-members')
    audit(request, 'member.scan', member)
    return render(request, 'panel/desk/members.html', {'q': member.member_id, 'scanned': True,
                                                       'results': [_member_view(request.user, member)]})


@panel_view('desk')
def desk_shift(request):
    return render(request, 'panel/desk/shift.html', {'shift': actions.shift(request.user)})
