"""Уровни и привилегии: порог базового — 0, остальных > 0; предпросмотр «N клиентов получат новый уровень»."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.audit import audit, model_snapshot
from apps.catalog.models import Venue
from apps.loyalty.models import PERK_ICONS, Privilege, Tier
from apps.common.errors import ApiError, message_for
from apps.loyalty.services import (create_tier, delete_tier, delete_tier_preview, preview_tier_change,
                                   recalc_all_tiers)

from ..access import panel_view
from ..modes import current_mode
from ..forms import PrivilegeForm, TierForm, TierStyleForm


def _tier_forms(request, tiers, data=None):
    forms = []
    for t in tiers:
        f = TierForm(data, instance=t, prefix=t.pk)
        if not request.user.can('tiers.edit'):
            f.lock(['threshold'])
        forms.append(f)
    return forms


def validate_thresholds(values):
    """values: [threshold по порядку уровней]. У базового — 0, у остальных > 0."""
    if not values or values[0] != 0:
        return False
    return all(v > 0 for v in values[1:])


@panel_view('tiers')
def tiers(request):
    tier_list = list(Tier.objects.live().order_by('order').prefetch_related('privileges'))
    data = request.POST if request.method == 'POST' else None
    forms = _tier_forms(request, tier_list, data)
    preview = None
    if request.method == 'POST':
        if all(f.is_valid() for f in forms):
            new = {f.instance.pk: f.cleaned_data['threshold'] for f in forms}
            ordered = [new[t.pk] for t in tier_list]
            if not validate_thresholds(ordered):
                messages.error(request, message_for('tiers_invalid', 'ru'))
            else:
                changed = any(new[t.pk] != Tier.objects.get(pk=t.pk).threshold for t in tier_list)
                if changed and request.POST.get('confirm') != '1':
                    preview = preview_tier_change(new)
                else:
                    before = {t.pk: model_snapshot(Tier.objects.get(pk=t.pk)) for t in tier_list}
                    for f in forms:
                        f.save()
                    upgraded = recalc_all_tiers() if changed else 0
                    audit(request, 'tiers.update', None, object_type='loyalty.tier', object_id='*', before=before,
                          after={t.pk: model_snapshot(Tier.objects.get(pk=t.pk)) for t in tier_list},
                          comment=f'повышено клиентов: {upgraded}' if changed else '')
                    messages.success(request, 'Уровни сохранены' + (f'. Новый уровень получили {upgraded} клиентов'
                                                                    if changed else ''))
                    return redirect('panel:tiers')
    venues = list(Venue.objects.all())
    # привилегии по объектам: общие — во всех; фильтр — объект из шапки, ?obj=all — все объекты
    shown = request.GET.get('obj') or current_mode(request)
    rows = []
    for t, f in zip(tier_list, forms):
        privileges = list(t.privileges.all())
        sections = [{'id': '', 'title': 'Общие — во всех объектах', 'items': [p for p in privileges if not p.modes]}]
        for v in venues:
            if shown in ('all', v.pk):
                sections.append({'id': v.pk, 'title': str(v), 'accent': v.accent,
                                 'items': [p for p in privileges if v.pk in (p.modes or [])]})
        rows.append({'tier': t, 'form': f, 'privileges': privileges, 'sections': sections})
    return render(request, 'panel/tiers/index.html', {
        'rows': rows, 'preview': preview, 'can_edit': request.user.can('tiers.edit'),
        'venues': venues, 'shown': shown,
        'perks': {r['tier'].pk: [p.short for p in r['privileges']] for r in rows}})


@panel_view('tiers')
def privilege_edit(request, privilege_id=None):
    user = request.user
    obj = get_object_or_404(Privilege, pk=privilege_id) if privilege_id else None
    if obj is None and not user.can('tiers.edit'):
        from ..access import forbidden
        return forbidden(request, 'Добавлять привилегии может директор')
    initial = {'tier': request.GET.get('tier')} if obj is None else {}
    form = PrivilegeForm(request.POST or None, instance=obj, initial=initial)
    if obj is None and request.GET.get('mode'):  # «+» в разделе объекта — привилегия сразу для этого объекта
        form.initial['modes'] = [request.GET['mode']]
    if not user.can('tiers.edit'):
        form.lock(PrivilegeForm.RULE_FIELDS)
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(obj) if obj else None
        saved = form.save()
        audit(request, 'privilege.update' if obj else 'privilege.create', saved, before=before,
              after=model_snapshot(saved))
        messages.success(request, 'Привилегия сохранена')
        return redirect('panel:tiers')
    return render(request, 'panel/tiers/privilege.html', {
        'form': form, 'obj': obj, 'icons': PERK_ICONS, 'tiers': Tier.objects.live().order_by('order'),
        'tier_names': {t.pk: t.name for t in Tier.objects.live()}})


@require_POST
@panel_view(perm='tiers.edit')
def privilege_delete(request, privilege_id):
    obj = get_object_or_404(Privilege, pk=privilege_id)
    audit(request, 'privilege.delete', obj, before=model_snapshot(obj))
    obj.delete()
    messages.success(request, 'Привилегия удалена')
    return redirect('panel:tiers')


def _medal_path(value):
    """URL из виджета загрузки → путь в хранилище."""
    from django.conf import settings
    value = value or ''
    for prefix in (settings.PUBLIC_BASE_URL + settings.MEDIA_URL, settings.MEDIA_URL):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


@panel_view(perm='tiers.edit')
def tier_edit(request, tier_id=None):
    """Новый уровень или оформление существующего (название, градиент, медаль) + удаление."""
    tier = get_object_or_404(Tier.objects.live(), pk=tier_id) if tier_id else None
    creating = tier is None
    initial = {}
    if tier:
        c = tier.gradient
        initial = {'name': tier.name, 'color0': c[0], 'color1': c[1], 'color2': c[2], 'medal': tier.medal}
    else:
        initial = {'color0': '#232C38', 'color1': '#627488', 'color2': '#B4C2D3'}
    form = TierStyleForm(request.POST or None, initial=initial, creating=creating)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            if creating:
                saved, upgraded = create_tier(d['name'], d['threshold'], form.colors, _medal_path(d['medal']))
                audit(request, 'tier.create', saved, after=model_snapshot(saved))
                messages.success(request, f'Уровень «{saved.name.get("ru")}» добавлен')
            else:
                before = model_snapshot(tier)
                tier.name, tier.colors, tier.medal = d['name'], form.colors, _medal_path(d['medal'])
                tier.save()
                audit(request, 'tier.update', tier, before=before, after=model_snapshot(tier))
                messages.success(request, 'Уровень сохранён')
            return redirect('panel:tiers')
        except ApiError as e:
            messages.error(request, e.message or message_for(e.code, 'ru'))
    ctx = {'form': form, 'tier': tier, 'creating': creating,
           'existing': list(Tier.objects.live().order_by('order'))}
    if tier:
        ctx['deletion'] = delete_tier_preview(tier)
        ctx['is_base'] = not Tier.objects.live().filter(order__lt=tier.order).exists()
    return render(request, 'panel/tiers/tier.html', ctx)


@require_POST
@panel_view(perm='tiers.edit')
def tier_delete(request, tier_id):
    tier = get_object_or_404(Tier.objects.live(), pk=tier_id)
    target_id = request.POST.get('privileges_to') or ''
    target = Tier.objects.filter(pk=target_id).first() if target_id not in ('', 'delete') else None
    before = model_snapshot(tier)
    try:
        result = delete_tier(tier, privileges_to=target, actor=request.user)
    except ApiError as e:
        messages.error(request, e.message or message_for(e.code, 'ru'))
        return redirect('panel:tier', tier_id=tier.pk)
    audit(request, 'tier.delete', None, object_type='loyalty.tier', object_id=tier_id, before=before, after=result)
    messages.success(request, f'Уровень удалён. Клиентов переведено: {result["reassigned"]}')
    return redirect('panel:tiers')
