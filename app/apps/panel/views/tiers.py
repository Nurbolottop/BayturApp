"""Уровни и привилегии: пороги строго возрастают (первый — 0), предпросмотр «N клиентов сменят уровень»."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.audit import audit, model_snapshot
from apps.common.errors import message_for
from apps.loyalty.models import PERK_ICONS, Privilege, Tier
from apps.loyalty.services import preview_tier_change, recalc_all_tiers

from ..access import panel_view
from ..forms import PrivilegeForm, TierForm


def _tier_forms(request, tiers, data=None):
    forms = []
    for t in tiers:
        f = TierForm(data, instance=t, prefix=t.pk)
        if not request.user.can('tiers.edit'):
            f.lock(['from_points'])
        forms.append(f)
    return forms


def validate_thresholds(values):
    """values: [from_points по порядку уровней]. Строго возрастают, у первого — 0."""
    if not values or values[0] != 0:
        return False
    return all(b > a for a, b in zip(values, values[1:]))


@panel_view('tiers')
def tiers(request):
    tier_list = list(Tier.objects.order_by('from_points').prefetch_related('privileges'))
    data = request.POST if request.method == 'POST' else None
    forms = _tier_forms(request, tier_list, data)
    preview = None
    if request.method == 'POST':
        if all(f.is_valid() for f in forms):
            new = {f.instance.pk: f.cleaned_data['from_points'] for f in forms}
            ordered = [new[t.pk] for t in tier_list]
            if not validate_thresholds(ordered):
                messages.error(request, message_for('tiers_invalid', 'ru'))
            else:
                changed = any(new[t.pk] != Tier.objects.get(pk=t.pk).from_points for t in tier_list)
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
                    messages.success(request, 'Уровни сохранены' + (f'. Уровень повышен у {upgraded} клиентов'
                                                                    if changed else ''))
                    return redirect('panel:tiers')
    rows = [{'tier': t, 'form': f, 'privileges': list(t.privileges.all())} for t, f in zip(tier_list, forms)]
    return render(request, 'panel/tiers/index.html', {
        'rows': rows, 'preview': preview, 'can_edit': request.user.can('tiers.edit'),
        'perks': {r['tier'].pk: [p.short for p in r['privileges']] for r in rows}})


@panel_view('tiers')
def privilege_edit(request, privilege_id=None):
    user = request.user
    obj = get_object_or_404(Privilege, pk=privilege_id) if privilege_id else None
    if obj is None and not user.can('tiers.edit'):
        from ..access import forbidden
        return forbidden(request, 'Добавлять привилегии может владелец или менеджер')
    initial = {'tier': request.GET.get('tier')} if obj is None else {}
    form = PrivilegeForm(request.POST or None, instance=obj, initial=initial)
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
        'form': form, 'obj': obj, 'icons': PERK_ICONS, 'tiers': Tier.objects.order_by('from_points'),
        'tier_names': {t.pk: t.name for t in Tier.objects.all()}})


@require_POST
@panel_view(perm='tiers.edit')
def privilege_delete(request, privilege_id):
    obj = get_object_or_404(Privilege, pk=privilege_id)
    audit(request, 'privilege.delete', obj, before=model_snapshot(obj))
    obj.delete()
    messages.success(request, 'Привилегия удалена')
    return redirect('panel:tiers')
