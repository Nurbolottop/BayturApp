"""Обращения (ТЗ §9.3): входящие с фильтрами, карточка с перепиской, заметки, ответ по шаблону, компенсация."""
from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Outlet
from apps.common.audit import audit
from apps.complaints import services as cs
from apps.complaints.models import Complaint, ComplaintCategory, ComplaintStatus, ReplyTemplate
from apps.loyalty.services import get_wallet
from apps.staff.models import StaffUser
from apps.staff.roles import PERMISSIONS

from ..access import forbidden, panel_view, run_action
from ..forms import ComplaintCategoryForm, ReplyTemplateForm
from .money import page


def scoped(user):
    qs = Complaint.objects.select_related('member', 'category', 'outlet', 'assignee')
    if user.is_outlet_bound:
        qs = qs.filter(outlet_id__in=user.outlet_ids)
    return qs


def assignees():
    roles = PERMISSIONS['complaints.reply']
    return StaffUser.objects.filter(is_active=True).filter(Q(role__in=roles) | Q(is_superuser=True)).order_by('full_name')


@panel_view('complaints')
def complaints(request):
    g = request.GET
    qs = scoped(request.user)
    if g.get('status'):
        qs = qs.filter(status=g['status'])
    elif not g.get('all'):
        qs = qs.exclude(status=ComplaintStatus.CLOSED)
    if g.get('category'):
        qs = qs.filter(category_id=g['category'])
    if g.get('outlet'):
        qs = qs.filter(outlet_id=g['outlet'])
    if g.get('assignee') == 'me':
        qs = qs.filter(assignee=request.user)
    elif g.get('assignee') == 'none':
        qs = qs.filter(assignee__isnull=True)
    elif g.get('assignee'):
        qs = qs.filter(assignee_id=g['assignee'])
    if g.get('overdue'):
        qs = qs.filter(first_reply_at__isnull=True, due_at__lt=timezone.now()).exclude(status=ComplaintStatus.CLOSED)
    if g.get('q'):
        q = g['q'].strip().replace('О-', '').replace('O-', '')
        cond = Q(member__member_id__iexact=g['q'].strip())
        if q.isdigit():
            cond |= Q(seq=int(q))
        qs = qs.filter(cond)
    return render(request, 'panel/complaints/list.html', {
        'page': page(request, qs.order_by('-created_at')), 'f': g, 'statuses': ComplaintStatus.choices,
        'categories': ComplaintCategory.objects.all(), 'outlets': Outlet.objects.all(), 'assignees': assignees(),
        'now': timezone.now(),
    })


@panel_view('complaints')
def complaint_detail(request, pk):
    c = get_object_or_404(scoped(request.user), pk=pk)
    user = request.user
    if not cs.staff_can_see(user, c):
        return forbidden(request)
    m = c.member
    templates = ReplyTemplate.objects.filter(Q(category__isnull=True) | Q(category=c.category))
    return render(request, 'panel/complaints/detail.html', {
        'c': c, 'm': m, 'tier': get_wallet(m).tier_id,
        'previous': m.complaints.exclude(pk=c.pk).count(),
        'thread': c.messages.select_related('staff').prefetch_related('attachments'),
        'notes': c.notes.select_related('staff'),
        'templates': [{'id': t.pk, 'title': t.title, 'text': t.text} for t in templates],
        'assignees': assignees(),
        'can_reply': user.can('complaints.reply') and c.status != ComplaintStatus.CLOSED,
        'can_manage': user.can('complaints.reply'),
        'can_compensate': user.can('complaints.compensate'),
        'can_note': user.can('complaints.notes'),
        'show_member_link': user.can('members.view'),
        'statuses': ComplaintStatus.choices,
    })


@require_POST
@panel_view('complaints')
def complaint_action(request, pk, action):
    user = request.user
    c = get_object_or_404(scoped(user), pk=pk)
    if not cs.staff_can_see(user, c):
        return forbidden(request)
    back = redirect('panel:complaint', pk=c.pk)
    if action == 'note':
        if not user.can('complaints.notes'):
            return forbidden(request)
        note, ok = run_action(request, lambda: cs.add_note(c.pk, user, request.POST.get('text')), 'Заметка добавлена')
        if ok:
            audit(request, 'complaint.note', c, after={'note': note.pk})
        return back
    if action == 'reply':
        close = bool(request.POST.get('close'))
        _, ok = run_action(request, lambda: cs.resort_reply(c.pk, user, request.POST.get('text'), close=close),
                           'Ответ отправлен клиенту')
        if ok:
            audit(request, 'complaint.reply', c, before={'status': c.status}, after={'close': close})
        return back
    if not user.can('complaints.reply'):
        return forbidden(request, 'Сотрудник точки читает и пишет внутренние заметки, но не отвечает клиенту')
    if action == 'assign':
        aid = request.POST.get('assignee')
        assignee = assignees().filter(pk=aid).first() if aid else None
        before = {'assignee': c.assignee_id}
        _, ok = run_action(request, lambda: cs.assign(c.pk, assignee), 'Ответственный назначен')
        if ok:
            audit(request, 'complaint.assign', c, before=before, after={'assignee': assignee.pk if assignee else None})
    elif action == 'status':
        status = request.POST.get('status')
        before = {'status': c.status}
        _, ok = run_action(request, lambda: cs.set_status(c.pk, user, status), 'Статус изменён')
        if ok:
            audit(request, 'complaint.status', c, before=before, after={'status': status})
    elif action == 'compensate':
        try:
            points = int(request.POST.get('points') or 0)
        except ValueError:
            points = 0
        comment = (request.POST.get('comment') or '').strip()
        if points <= 0:
            messages.error(request, 'Укажите количество баллов')
            return back
        op, ok = run_action(request, lambda: cs.compensate(c, user, points, comment), 'Компенсация начислена')
        if ok:
            audit(request, 'complaint.compensate', c, after={'points': points, 'operation': op.pk},
                  comment=comment or f'Компенсация по обращению {c.number}')
    else:
        raise Http404
    return back


@panel_view(perm='complaints.settings')
def reply_templates(request, pk=None):
    obj = get_object_or_404(ReplyTemplate, pk=pk) if pk else None
    form = ReplyTemplateForm(request.POST or None, instance=obj)
    if request.method == 'POST':
        if request.POST.get('delete') and obj:
            audit(request, 'reply_template.delete', obj)
            obj.delete()
            messages.success(request, 'Шаблон удалён')
            return redirect('panel:reply-templates')
        if form.is_valid():
            saved = form.save()
            audit(request, 'reply_template.update' if obj else 'reply_template.create', saved,
                  after={'title': saved.title})
            messages.success(request, 'Шаблон сохранён')
            return redirect('panel:reply-templates')
    request.panel_section = 'complaints'
    return render(request, 'panel/complaints/templates.html', {
        'form': form, 'obj': obj, 'items': ReplyTemplate.objects.select_related('category')})


@panel_view(perm='complaints.settings')
def complaint_categories(request, pk=None):
    """Темы обращений на 3 языках. Тему с обращениями нельзя удалить — только скрыть."""
    obj = get_object_or_404(ComplaintCategory, pk=pk) if pk else None
    form = ComplaintCategoryForm(request.POST or None, instance=obj)
    if request.method == 'POST':
        if request.POST.get('delete') and obj:
            if obj.complaints.exists():
                messages.error(request, 'По теме есть обращения — её можно только скрыть')
                return redirect('panel:complaint-category', pk=obj.pk)
            audit(request, 'complaint_category.delete', obj)
            obj.delete()
            messages.success(request, 'Тема удалена')
            return redirect('panel:complaint-categories')
        if form.is_valid():
            saved = form.save()
            audit(request, 'complaint_category.update' if obj else 'complaint_category.create', saved,
                  after={'title': saved.title, 'isActive': saved.is_active})
            messages.success(request, 'Тема сохранена')
            return redirect('panel:complaint-categories')
    request.panel_section = 'complaints'
    return render(request, 'panel/complaints/categories.html', {
        'form': form, 'obj': obj, 'items': ComplaintCategory.objects.all()})
