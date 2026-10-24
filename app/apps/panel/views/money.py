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
def discounts(request):
    """Скидки кассиров: кто, кому, сколько — заявки, где итог ниже прайса (originalTotal), и сводка по сотрудникам."""
    from django.db.models import Count, F, Sum
    g = request.GET
    qs = scoped_requests(request.user).filter(original_total__isnull=False, total__lt=F('original_total')) \
        .exclude(status__in=(RequestStatus.REJECTED, RequestStatus.CANCELLED)) \
        .select_related('member', 'outlet', 'created_by', 'adjusted_by', 'confirmed_by')
    if _date(g.get('from')):
        qs = qs.filter(created_at__gte=_date(g['from']))
    if _date(g.get('to'), True):
        qs = qs.filter(created_at__lte=_date(g['to'], True))
    if g.get('staff'):
        qs = qs.filter(Q(created_by_id=g['staff']) | Q(adjusted_by_id=g['staff']))
    by_staff = []
    for r in qs.values('created_by', 'created_by__full_name', 'adjusted_by', 'adjusted_by__full_name') \
            .annotate(n=Count('pk'), price=Sum('original_total'), paid=Sum('total')):
        sid = r['adjusted_by'] or r['created_by']
        name = r['adjusted_by__full_name'] or r['created_by__full_name'] or '—'
        row = next((x for x in by_staff if x['id'] == sid), None)
        if row is None:
            row = {'id': sid, 'name': name, 'count': 0, 'price': 0, 'discount': 0}
            by_staff.append(row)
        row['count'] += r['n']
        row['price'] += r['price'] or 0
        row['discount'] += (r['price'] or 0) - (r['paid'] or 0)
    for row in by_staff:
        row['percent'] = round(row['discount'] * 100 / row['price']) if row['price'] else 0
    by_staff.sort(key=lambda x: -x['discount'])
    totals = qs.aggregate(price=Sum('original_total'), paid=Sum('total'))
    pg = page(request, qs.order_by('-created_at'))
    for r in pg:
        r.discount = r.original_total - r.total
        r.discount_pct = round(r.discount * 100 / r.original_total) if r.original_total else 0
        r.discount_by = r.adjusted_by or r.created_by or r.confirmed_by
    return render(request, 'panel/requests/discounts.html', {
        'page': pg, 'by_staff': by_staff, 'f': g,
        'discount_total': (totals['price'] or 0) - (totals['paid'] or 0),
        'staff_users': StaffUser.objects.filter(is_active=True).order_by('full_name'),
    })


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


# ---------------------------------------------------------------- сверка с R-Keeper

@panel_view('pos')
def pos_list(request):
    """Загрузка выгрузки оплат «Баллы» из R-Keeper → сверка по коду и сумме; список прошлых сверок."""
    from apps.cashback import pos_reconcile
    from apps.cashback.models import PosReconciliation
    from apps.common.errors import ApiError
    if request.method == 'POST':
        f = request.FILES.get('file')
        if f is None or f.size > 10 * 1024 * 1024:
            messages.error(request, 'Выберите файл выгрузки из R-Keeper (XLSX или CSV, до 10 МБ)')
            return redirect('panel:pos')
        try:
            rows = pos_reconcile.read_rows(f, f.name)
        except ApiError as e:
            messages.error(request, e.message or 'Не удалось прочитать файл')
            return redirect('panel:pos')
        start, end = pos_reconcile.period_of(rows)
        if _date(request.POST.get('from')):
            start = timezone.localtime(_date(request.POST['from'])).date()
        if _date(request.POST.get('to')):
            end = timezone.localtime(_date(request.POST['to'])).date()
        if start is None or end is None:
            messages.error(request, 'В файле нет дат — укажите период выгрузки')
            return redirect('panel:pos')
        result = pos_reconcile.reconcile(rows, scoped_requests(request.user), start, end)
        rec = PosReconciliation.objects.create(
            uploaded_by=request.user, file_name=f.name[:200], period_from=start, period_to=end,
            summary=result.pop('summary'), result=result)
        audit(request, 'pos.reconcile', rec, after={'file': rec.file_name, **rec.summary})
        return redirect('panel:pos-detail', pk=rec.pk)
    items = PosReconciliation.objects.select_related('uploaded_by')[:50]
    return render(request, 'panel/pos/list.html', {'items': items})


@panel_view('pos')
def pos_detail(request, pk):
    from apps.cashback.models import PosReconciliation
    rec = get_object_or_404(PosReconciliation.objects.select_related('uploaded_by'), pk=pk)
    show = request.GET.get('show') or 'problems'
    rows = rec.result.get('rows', [])
    if show == 'problems':
        rows = [r for r in rows if r['status'] != 'ok']
    elif show in ('red', 'yellow', 'ok'):
        rows = [r for r in rows if r['status'] == show]
    return render(request, 'panel/pos/detail.html', {
        'rec': rec, 'rows': rows, 'show': show, 'missing': rec.result.get('missing', []),
        'tabs': [('problems', 'Проблемы'), ('red', '🔴'), ('yellow', '🟡'), ('ok', '✅'), ('all', 'Все')],
        'by_cashier': rec.result.get('byCashier', []), 's': rec.summary})
