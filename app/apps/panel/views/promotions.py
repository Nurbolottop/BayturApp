"""Акции на цену: список со статусом и редактор (вид, охват, период, условия, аудитория, совместимость, лимит)."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Promotion, Venue
from apps.catalog.promotions import is_active_at, used
from apps.common.audit import audit, model_snapshot
from apps.common.caching import bump_content_version

from ..access import forbidden, panel_view
from ..forms import PromotionForm


def status_of(p, now):
    if not p.is_active:
        return 'off', 'выключена'
    if p.ends_at and now >= p.ends_at:
        return 'ended', 'закончилась'
    if p.starts_at and now < p.starts_at:
        return 'scheduled', 'запланирована'
    if p.usage_limit is not None and used(p) >= p.usage_limit:
        return 'ended', 'лимит исчерпан'
    return ('active', 'действует') if is_active_at(p, now) else ('scheduled', 'вне дней/часов')


@panel_view('promotions')
def promotions(request):
    now = timezone.now()
    venue = request.GET.get('venue') or ''
    qs = Promotion.objects.prefetch_related('venues', 'sections', 'items').select_related('gift_item')
    if venue:
        qs = qs.filter(venues__pk=venue) | qs.filter(sections__venue_id=venue) | qs.filter(items__venue_id=venue) \
            | qs.filter(scope='all') | qs.filter(bundle_items__venue_id=venue)
        qs = qs.distinct()
    rows = []
    for p in qs:
        key, label = status_of(p, now)
        rows.append({'obj': p, 'status': key, 'status_label': label,
                     'used': used(p) if p.usage_limit is not None else None})
    return render(request, 'panel/promotions/list.html', {
        'rows': rows, 'venues': Venue.objects.all(), 'venue': venue,
        'can_edit': request.user.can('catalog.edit')})


@panel_view('promotions')
def promotion_edit(request, promotion_id=None):
    promo = get_object_or_404(Promotion, pk=promotion_id) if promotion_id else None
    if not request.user.can('catalog.edit') and promo is None:
        return forbidden(request, 'Создавать акции может директор')
    form = PromotionForm(request.POST or None, instance=promo)
    if not request.user.can('catalog.edit'):
        form.lock([n for n in form.fields if n not in ('title', 'description', 'tag')])
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(promo) if promo else None
        obj = form.save()
        bump_content_version()  # M2M (охват) сохраняется после save — сбросить кеш прайса ещё раз
        audit(request, 'promotion.update' if promo else 'promotion.create', obj, before=before,
              after=model_snapshot(obj))
        messages.success(request, 'Акция сохранена')
        return redirect('panel:promotion', promotion_id=obj.pk)
    ctx = {'form': form, 'promo': promo}
    if promo:
        ctx['status'] = status_of(promo, timezone.now())[1]
        ctx['used'] = used(promo)
    return render(request, 'panel/promotions/edit.html', ctx)


@require_POST
@panel_view(perm='catalog.edit')
def promotion_toggle(request, promotion_id):
    promo = get_object_or_404(Promotion, pk=promotion_id)
    promo.is_active = not promo.is_active
    promo.save(update_fields=['is_active', 'updated_at'])
    audit(request, 'promotion.toggle', promo, after={'is_active': promo.is_active})
    messages.success(request, 'Акция включена' if promo.is_active else 'Акция выключена')
    return redirect('panel:promotion', promotion_id=promo.pk)
