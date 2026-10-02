"""Клиенты: поиск и фильтры, карточка, корректировка баллов, блокировка, ДР, восстановление и стирание."""
from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.cashback.desk import scoped_requests
from apps.common.audit import audit
from apps.common.models import ProgramSettings
from apps.loyalty.services import expires_at, get_wallet, pending_cashback, tier_progress, tiers_ordered
from apps.members.models import Member, MemberStatus

from ..access import panel_view, run_action
from ..forms import AdjustPointsForm, BirthdayForm, tier_choices
from .money import _date, page


@panel_view('members')
def members_list(request):
    g = request.GET
    q = (g.get('q') or '').strip()
    if not request.user.can('members.history'):
        # сотрудник точки: только точный поиск по memberId / телефону, без списка всех клиентов
        from ..actions import search_members
        found = search_members(q) if q else []
        return render(request, 'panel/members/list.html', {
            'page': found, 'f': g, 'limited': True, 'show_balance': False})
    qs = Member.objects.select_related('wallet', 'wallet__tier', 'avatar')
    if q:
        digits = ''.join(ch for ch in q if ch.isdigit())
        cond = Q(member_id__iexact=q) | Q(member_id__iexact=f'BT-{q}') | Q(first_name__icontains=q) | \
            Q(last_name__icontains=q)
        if len(digits) >= 4:
            cond |= Q(phone__contains=digits[-9:])
        parts = q.split()
        if len(parts) == 2:
            cond |= Q(first_name__icontains=parts[0], last_name__icontains=parts[1])
        qs = qs.filter(cond)
    if g.get('tier'):
        qs = qs.filter(wallet__tier_id=g['tier'])
    if g.get('status'):
        qs = qs.filter(status=g['status'])
    else:
        qs = qs.exclude(status=MemberStatus.PURGED)
    if _date(g.get('from')):
        qs = qs.filter(created_at__gte=_date(g['from']))
    if _date(g.get('to'), True):
        qs = qs.filter(created_at__lte=_date(g['to'], True))
    if g.get('test') != '1':
        qs = qs.filter(is_test=False)
    return render(request, 'panel/members/list.html', {
        'page': page(request, qs.order_by('-created_at')), 'f': g, 'tiers': tier_choices(),
        'statuses': MemberStatus.choices, 'show_balance': request.user.can('members.history'),
    })


@panel_view('members')
def member_detail(request, pk):
    member = get_object_or_404(Member, pk=pk)
    user = request.user
    wallet = get_wallet(member)
    full = user.can('members.history')
    ctx = {'m': member, 'wallet': wallet, 'full': full, 'tier': wallet.tier_id,
           'can_manage': user.can('members.manage'), 'can_restore': user.can('members.restore')}
    if full:
        current, nxt, left, progress = tier_progress(wallet.lifetime, tiers_ordered())
        ctx.update({
            'next_tier': nxt, 'left': left, 'progress': int(progress * 100),
            'pending_cashback': pending_cashback(member), 'expires': expires_at(wallet),
            'balance_som': wallet.balance // max(1, ProgramSettings.get().points_per_som),
            'requests': member.cashback_requests.select_related('outlet').order_by('-created_at')[:50],
            'operations': member.operations.select_related('author').order_by('-at')[:100],
            'consents': member.consents.all()[:50],
            'devices': member.devices.all(),
            'complaints': member.complaints.select_related('category').order_by('-created_at')[:20],
        })
    else:
        # сотрудник: без баланса и истории — только заявки своих точек и уровень
        ctx['requests'] = scoped_requests(user).filter(member=member).order_by('-created_at')[:20]
    ctx['adjust_form'] = AdjustPointsForm()
    ctx['birthday_form'] = BirthdayForm(initial={'birthday': member.birthday})
    return render(request, 'panel/members/detail.html', ctx)


@require_POST
@panel_view(perm='members.manage')
def member_action(request, pk, action):
    member = get_object_or_404(Member, pk=pk)
    back = redirect('panel:member', pk=member.pk)
    if member.status == MemberStatus.PURGED:
        messages.error(request, 'Аккаунт стёрт — действия недоступны')
        return back
    if action == 'adjust':
        form = AdjustPointsForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Корректировка: ' + '; '.join(e for errs in form.errors.values() for e in errs))
            return back
        from apps.loyalty.services import manual_adjustment
        before = {'balance': get_wallet(member).balance}
        op, ok = run_action(request, lambda: manual_adjustment(
            member, form.cleaned_data['points'], form.cleaned_data['comment'], request.user))
        if ok:
            audit(request, 'member.adjust', member, before=before,
                  after={'balance': get_wallet(member).balance, 'points': op.points, 'operation': op.pk},
                  comment=form.cleaned_data['comment'])
            messages.success(request, f'Корректировка {op.points:+,} баллов проведена'.replace(',', ' '))
    elif action in ('block', 'unblock'):
        before = {'status': member.status}
        if action == 'block':
            if member.status != MemberStatus.ACTIVE:
                messages.error(request, 'Заблокировать можно только активного клиента')
                return back
            reason = (request.POST.get('reason') or '').strip()
            if not reason:
                messages.error(request, 'Укажите причину блокировки')
                return back
            member.status = MemberStatus.BLOCKED
            member.blocked_reason = reason
            member.save(update_fields=['status', 'blocked_reason', 'updated_at'])
            from apps.members.auth import revoke_all
            revoke_all(member)
            audit(request, 'member.block', member, before=before, after={'status': member.status}, comment=reason)
            messages.success(request, 'Клиент заблокирован')
        else:
            if member.status != MemberStatus.BLOCKED:
                messages.error(request, 'Клиент не заблокирован')
                return back
            member.status = MemberStatus.ACTIVE
            member.blocked_reason = ''
            member.save(update_fields=['status', 'blocked_reason', 'updated_at'])
            audit(request, 'member.unblock', member, before=before, after={'status': member.status})
            messages.success(request, 'Клиент разблокирован')
    elif action == 'birthday':
        form = BirthdayForm(request.POST)
        if form.is_valid():
            before = {'birthday': member.birthday}
            member.birthday = form.cleaned_data['birthday']
            member.save(update_fields=['birthday', 'updated_at'])
            audit(request, 'member.birthday', member, before=before, after={'birthday': member.birthday},
                  comment=request.POST.get('comment', ''))
            messages.success(request, 'Дата рождения изменена')
        else:
            messages.error(request, 'Неверная дата')
    else:
        raise Http404
    return back


@require_POST
@panel_view(perm='members.restore')
def member_lifecycle(request, pk, action):
    from apps.members import services as ms
    member = get_object_or_404(Member, pk=pk)
    before = {'status': member.status, 'purgeAt': member.purge_at}
    if action == 'restore':
        m, ok = run_action(request, lambda: ms.restore(member), 'Аккаунт восстановлен')
        if ok:
            audit(request, 'member.restore', m, before=before, after={'status': m.status})
    elif action == 'purge':
        if member.status != MemberStatus.DEACTIVATED:
            messages.error(request, 'Стереть можно только удалённый аккаунт')
        elif request.POST.get('confirm') != member.member_id:
            messages.error(request, f'Для подтверждения введите номер участника {member.member_id}')
        else:
            m, ok = run_action(request, lambda: ms.purge(member), 'Аккаунт окончательно стёрт')
            if ok:
                audit(request, 'member.purge', m, before=before, after={'status': m.status})
    else:
        raise Http404
    return redirect('panel:member', pk=member.pk)


@panel_view(perm='members.manage')
def member_export(request, pk):
    """Выгрузка всех данных клиента одним JSON (запрос клиента на свои данные) — как в админ-API."""
    import json

    from django.core.serializers.json import DjangoJSONEncoder
    from django.http import HttpResponse

    from apps.backoffice.views.members import export_payload
    member = get_object_or_404(Member, pk=pk)
    audit(request, 'member.export', member)
    response = HttpResponse(json.dumps(export_payload(member), cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
                            content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{member.member_id}.json"'
    return response
