"""Заявки (все) и онлайн-платежи: фильтры, те же действия, что у сотрудника, эскалации, возвраты."""
from datetime import datetime, time

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.cashback.models import RequestStatus
from apps.cashback.desk import scoped_requests
from apps.catalog.models import Category, Outlet
from apps.common.audit import audit
from apps.payments.models import Payment, PaymentStatus
from apps.staff.models import StaffUser

from ..access import panel_view, run_action
from .desk import _payment, request_card_context


def _date(v, end=False):
    try:
        d = datetime.strptime(v, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    return timezone.make_aware(datetime.combine(d, time.max if end else time.min))


def page(request, qs, per=50):
    p = Paginator(qs, per).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    p.query = params.urlencode()
    return p


@panel_view('requests')
def requests_list(request):
    g = request.GET
    qs = scoped_requests(request.user).select_related('member', 'outlet', 'confirmed_by', 'rejected_by', 'created_by',
                                                      'cancelled_by')
    if g.get('status'):
        qs = qs.filter(status=g['status'])
    if g.get('escalated'):
        qs = qs.filter(escalated=True, status=RequestStatus.PENDING)
    if g.get('category'):
        qs = qs.filter(item__category_id=g['category'])
    if g.get('outlet'):
        qs = qs.filter(outlet_id=g['outlet'])
    if g.get('staff'):
        qs = qs.filter(Q(confirmed_by_id=g['staff']) | Q(rejected_by_id=g['staff']) | Q(adjusted_by_id=g['staff'])
                       | Q(created_by_id=g['staff']) | Q(cancelled_by_id=g['staff']))
    if g.get('duplicate'):
        qs = qs.exclude(duplicate_of='')
    if _date(g.get('from')):
        qs = qs.filter(created_at__gte=_date(g['from']))
    if _date(g.get('to'), True):
        qs = qs.filter(created_at__lte=_date(g['to'], True))
    if g.get('q'):
        q = g['q'].strip()
        qs = qs.filter(Q(pk__iexact=q) | Q(member__member_id__iexact=q) | Q(member__phone__endswith=q[-9:])
                       | Q(member__last_name__icontains=q))
    ctx = {
        'page': page(request, qs.order_by('-created_at')),
        'statuses': RequestStatus.choices,
        'categories': (Category.objects.filter(pk__in=request.user.category_ids)
                       if request.user.category_ids is not None else Category.objects.all()),
        'outlets': Outlet.objects.all(),
        'staff_users': StaffUser.objects.filter(role__in=['staff', 'owner']).order_by('full_name'),
        'f': g,
    }
    return render(request, 'panel/requests/list.html', ctx)


@panel_view('requests')
def shifts(request):
    """Отчёт по сменам: наличные и карта каждого кассира за день, отмены с причинами, повторы."""
    from django.db.models import Count, Sum

    from apps.cashback.desk import DONE_STATUSES
    g = request.GET
    day = (_date(g.get('date')) or timezone.now()).astimezone(timezone.get_current_timezone()).date()
    start, end = _date(day.isoformat()), _date(day.isoformat(), True)
    base = scoped_requests(request.user)
    done = base.filter(confirmed_at__range=(start, end), status__in=DONE_STATUSES, confirmed_by__isnull=False)
    rows = {}
    for r in done.values('confirmed_by', 'confirmed_by__full_name', 'method').annotate(
            n=Count('pk'), money=Sum('money_som'), points=Sum('points_som')):
        row = rows.setdefault(r['confirmed_by'], {'name': r['confirmed_by__full_name'], 'count': 0, 'cash': 0,
                                                   'card': 0, 'online': 0, 'points': 0, 'cancelled': 0})
        row['count'] += r['n']
        row['points'] += r['points'] or 0
        key = {'cash': 'cash', 'card': 'card'}.get(r['method'], 'online' if r['method'] else None)
        if key:
            row[key] += r['money'] or 0
    cancelled = base.filter(status=RequestStatus.CANCELLED, cancelled_at__range=(start, end)) \
        .select_related('member', 'outlet', 'created_by', 'cancelled_by').order_by('-cancelled_at')
    for r in cancelled:
        if r.created_by_id:
            rows.setdefault(r.created_by_id, {'name': r.created_by.full_name, 'count': 0, 'cash': 0, 'card': 0,
                                              'online': 0, 'points': 0, 'cancelled': 0})['cancelled'] += 1
    duplicates = base.filter(created_at__range=(start, end)).exclude(duplicate_of='') \
        .select_related('member', 'outlet', 'created_by').order_by('-created_at')
    totals = {k: sum(r[k] for r in rows.values()) for k in ('count', 'cash', 'card', 'online', 'points')}
    return render(request, 'panel/requests/shifts.html', {
        'day': day, 'rows': sorted(rows.values(), key=lambda r: r['name'] or ''), 'totals': totals,
        'cancelled': cancelled, 'duplicates': duplicates})


@panel_view('requests')
def request_detail(request, request_id):
    req = scoped_requests(request.user).filter(pk=request_id).select_related('member', 'outlet').first()
    if req is None:
        raise Http404
    ctx = request_card_context(request, req)
    ctx['payment'] = _payment(req)
    ctx['back'] = '/panel/requests/'
    ctx['operations'] = req.operations.all() if request.user.can('members.history') else None
    return render(request, 'panel/requests/detail.html', ctx)


# ---------------------------------------------------------------- платежи

def scoped_payments(user):
    """Админ отдела видит только платежи по заявкам своих разделов."""
    qs = Payment.objects.select_related('member', 'request')
    if user.category_ids is not None:
        qs = qs.filter(request__item__category_id__in=user.category_ids)
    return qs


@panel_view('payments')
def payments_list(request):
    g = request.GET
    qs = scoped_payments(request.user)
    if g.get('status'):
        qs = qs.filter(status=g['status'])
    if g.get('method'):
        qs = qs.filter(method=g['method'])
    if g.get('orphan'):
        qs = qs.filter(status=PaymentStatus.PAID, request__isnull=True)
    if _date(g.get('from')):
        qs = qs.filter(created_at__gte=_date(g['from']))
    if _date(g.get('to'), True):
        qs = qs.filter(created_at__lte=_date(g['to'], True))
    if g.get('q'):
        q = g['q'].strip()
        qs = qs.filter(Q(pk__iexact=q) | Q(provider_ref__iexact=q) | Q(member__member_id__iexact=q))
    orphan_count = scoped_payments(request.user).filter(status=PaymentStatus.PAID, request__isnull=True).count()
    return render(request, 'panel/payments/list.html', {
        'page': page(request, qs.order_by('-created_at')), 'statuses': PaymentStatus.choices, 'f': g,
        'orphan_count': orphan_count,
        'methods': [('finik', 'Finik'), ('freedomPay', 'Freedom Pay'), ('elqr', 'ЭлQR')],
    })


@panel_view('payments')
def payment_detail(request, payment_id):
    p = get_object_or_404(scoped_payments(request.user), pk=payment_id)
    return render(request, 'panel/payments/detail.html', {'p': p, 'refunds': p.refunds.select_related('author'),
                                                          'left': p.amount - p.refunded_amount})


@require_POST
@panel_view(perm='payments.refund')
def payment_refund(request, payment_id):
    from apps.payments.services import refund_payment
    p = get_object_or_404(scoped_payments(request.user), pk=payment_id)
    try:
        amount = int(request.POST.get('amount') or 0)
    except ValueError:
        amount = 0
    reason = (request.POST.get('reason') or '').strip()
    if amount <= 0 or not reason:
        messages.error(request, 'Укажите сумму и причину возврата')
        return redirect('panel:payment', payment_id=p.pk)
    before = {'status': p.status, 'refunded': p.refunded_amount}
    refund, ok = run_action(request, lambda: refund_payment(p.pk, amount, reason, author=request.user))
    if ok:
        if refund is None:
            messages.error(request, 'Возврат невозможен: платёж не в статусе «оплачен» или уже возвращён')
        else:
            p.refresh_from_db()
            audit(request, 'payment.refund', p, before=before,
                  after={'status': p.status, 'refunded': p.refunded_amount, 'refund': refund.status}, comment=reason)
            if refund.status == 'done':
                messages.success(request, f'Возврат {amount} сом выполнен')
            else:
                messages.error(request, 'Провайдер отклонил возврат')
    return redirect('panel:payment', payment_id=p.pk)
