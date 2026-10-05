"""Push-рассылки: тексты на 3 языках, ссылка, сегмент, отложенная и тестовая отправка; шаблоны push."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.common.audit import audit, model_snapshot
from apps.notifications.models import Campaign, CampaignStatus, PushKind, PushTemplate

from ..access import forbidden, panel_view, run_action
from ..forms import CampaignForm, PushTemplateForm

EDITABLE = (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED)


@panel_view('campaigns')
def campaigns(request):
    from apps.notifications.services import campaign_stats
    rows = []
    for c in Campaign.objects.select_related('created_by', 'article', 'item')[:200]:
        rows.append({'c': c, 'stats': campaign_stats(c) if c.status == CampaignStatus.SENT else None})
    return render(request, 'panel/campaigns/list.html', {'rows': rows})


@panel_view('campaigns')
def campaign_edit(request, pk=None):
    from apps.notifications.services import campaign_audience, campaign_stats
    user = request.user
    c = get_object_or_404(Campaign, pk=pk) if pk else None
    locked = c is not None and c.status not in EDITABLE
    if c and c.status == CampaignStatus.SCHEDULED and not user.can('campaigns.send'):
        locked = True
    form = CampaignForm(request.POST or None, instance=c)
    if request.method == 'POST' and not locked and form.is_valid():
        before = model_snapshot(c) if c else None
        obj = form.save(commit=False)
        if obj.pk is None:
            obj.created_by = user
        obj.status = CampaignStatus.DRAFT
        obj.save()
        audit(request, 'campaign.update' if c else 'campaign.create', obj, before=before, after=model_snapshot(obj))
        messages.success(request, 'Черновик сохранён')
        return redirect('panel:campaign', pk=obj.pk)
    ctx = {'form': form, 'c': c, 'locked': locked, 'can_send': user.can('campaigns.send'),
           'audience': campaign_audience(c).count() if c else None,
           'stats': campaign_stats(c) if c and c.status == CampaignStatus.SENT else None,
           'now': timezone.now()}
    return render(request, 'panel/campaigns/edit.html', ctx)


@require_POST
@panel_view('campaigns')
def campaign_action(request, pk, action):
    from apps.notifications import services as ns
    user = request.user
    c = get_object_or_404(Campaign, pk=pk)
    if action in ('send', 'schedule', 'cancel') and not user.can('campaigns.send'):
        return forbidden(request, 'Редактор создаёт только черновики — отправляет директор')
    back = redirect('panel:campaign', pk=c.pk)
    if action == 'test':
        n, ok = run_action(request, lambda: ns.send_campaign_test(c, user))
        if ok:
            if n is None:
                messages.error(request, 'Тест не отправлен: в профиле сотрудника нет телефона клиента-участника')
            else:
                audit(request, 'campaign.test', c)
                messages.success(request, 'Тестовый push отправлен на ваш номер')
    elif action == 'schedule':
        if c.status != CampaignStatus.DRAFT:
            messages.error(request, 'Запланировать можно только черновик')
        elif not c.scheduled_at or c.scheduled_at <= timezone.now():
            messages.error(request, 'Укажите время отправки в будущем')
        else:
            c.status = CampaignStatus.SCHEDULED
            c.save(update_fields=['status'])
            audit(request, 'campaign.schedule', c, after={'scheduledAt': c.scheduled_at})
            messages.success(request, 'Рассылка запланирована')
    elif action == 'send':
        if c.status not in EDITABLE:
            messages.error(request, 'Рассылка уже отправлена')
        else:
            sent, ok = run_action(request, lambda: ns.send_campaign(c.pk))
            if ok:
                audit(request, 'campaign.send', c, after=sent.stats)
                messages.success(request, f'Отправлено: {sent.stats.get("sent", 0)}, пропущено по лимиту: '
                                          f'{sent.stats.get("skipped", 0)}')
    elif action == 'cancel':
        if c.status not in EDITABLE:
            messages.error(request, 'Отменить можно только черновик или запланированную')
        else:
            before = {'status': c.status}
            c.status = CampaignStatus.CANCELLED
            c.save(update_fields=['status'])
            audit(request, 'campaign.cancel', c, before=before, after={'status': c.status})
            messages.success(request, 'Рассылка отменена')
    return back


@panel_view(perm='campaigns.send')
def push_templates(request):
    from apps.notifications.services import DEFAULT_TEMPLATES
    kind = request.GET.get('kind') or request.POST.get('kind') or PushKind.REQUEST_CREDITED
    if kind not in PushKind.values or kind == PushKind.CAMPAIGN:
        kind = PushKind.REQUEST_CREDITED
    tpl = PushTemplate.objects.filter(pk=kind).first()
    initial = {}
    if tpl is None and kind in DEFAULT_TEMPLATES:
        initial = {'title': DEFAULT_TEMPLATES[kind][0], 'body': DEFAULT_TEMPLATES[kind][1]}
    form = PushTemplateForm(request.POST or None, instance=tpl or PushTemplate(kind=kind), initial=initial)
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(tpl) if tpl else None
        obj = form.save()
        audit(request, 'push_template.update', obj, before=before, after=model_snapshot(obj))
        messages.success(request, 'Шаблон сохранён')
        return redirect(f'{request.path}?kind={kind}')
    kinds = [(k, label) for k, label in PushKind.choices if k != PushKind.CAMPAIGN]
    request.panel_section = 'campaigns'
    return render(request, 'panel/campaigns/templates.html', {'form': form, 'kind': kind, 'kinds': kinds,
                                                              'custom': tpl is not None})
