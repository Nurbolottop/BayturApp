"""Акции на цену: список со статусом и редактор (вид, охват, период, условия, аудитория, совместимость, лимит)."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Promotion, PromotionScope
from apps.catalog.promotions import is_active_at, used
from apps.common.audit import audit, model_snapshot
from apps.common.caching import bump_content_version

from ..access import forbidden, panel_view
from ..forms import PromotionForm
from ..modes import current_mode


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


def in_department(p, cats):
    """Акция целиком в разделах отдела: охват — услуги или подразделы, и всё, что она затрагивает, — свои."""
    if cats is None:
        return True
    if p.scope not in (PromotionScope.ITEMS, PromotionScope.SECTIONS):
        return False
    items = list(p.items.all()) + list(p.bundle_items.all()) + ([p.gift_item] if p.gift_item else [])
    return all(i.category_id in cats for i in items) and all(s.category_id in cats for s in p.sections.all())


def limit_form(form, cats):
    """Админ отдела: охват только услуги/подразделы, выбор — только своих разделов."""
    if cats is None:
        return
    form.fields['scope'].choices = [c for c in form.fields['scope'].choices
                                    if c[0] in (PromotionScope.ITEMS, PromotionScope.SECTIONS)]
    form.fields['sections'].queryset = form.fields['sections'].queryset.filter(category_id__in=cats)
    for name in ('items', 'bundle_items', 'gift_item'):
        form.fields[name].queryset = form.fields[name].queryset.filter(category_id__in=cats)
    form.fields['venues'].queryset = form.fields['venues'].queryset.none()


def _get_own(request, promotion_id):
    promo = get_object_or_404(Promotion.objects.prefetch_related('items', 'bundle_items', 'sections')
                              .select_related('gift_item'), pk=promotion_id)
    if not in_department(promo, request.user.category_ids):
        raise Http404
    return promo


@panel_view('promotions')
def promotions(request):
    now = timezone.now()
    venue = '' if request.GET.get('all') else current_mode(request)  # режим из шапки; ?all=1 — все режимы
    qs = Promotion.objects.prefetch_related('venues', 'sections', 'items').select_related('gift_item')
    if venue:
        qs = qs.filter(venues__pk=venue) | qs.filter(sections__venue_id=venue) | qs.filter(items__venue_id=venue) \
            | qs.filter(scope='all') | qs.filter(bundle_items__venue_id=venue)
        qs = qs.distinct()
    rows = []
    cats = request.user.category_ids
    qs = qs.prefetch_related('bundle_items')
    for p in qs:
        if not in_department(p, cats):
            continue
        key, label = status_of(p, now)
        rows.append({'obj': p, 'status': key, 'status_label': label,
                     'used': used(p) if p.usage_limit is not None else None})
    return render(request, 'panel/promotions/list.html', {
        'rows': rows, 'venue': venue,
        'can_edit': request.user.can('promotions.edit')})


@panel_view('promotions')
def promotion_edit(request, promotion_id=None):
    promo = _get_own(request, promotion_id) if promotion_id else None
    if not request.user.can('promotions.edit') and promo is None:
        return forbidden(request, 'Создавать акции может директор')
    form = PromotionForm(request.POST or None, instance=promo)
    limit_form(form, request.user.category_ids)
    if not request.user.can('promotions.edit'):
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
@panel_view(perm='promotions.edit')
def promotion_toggle(request, promotion_id):
    promo = _get_own(request, promotion_id)
    promo.is_active = not promo.is_active
    promo.save(update_fields=['is_active', 'updated_at'])
    audit(request, 'promotion.toggle', promo, after={'is_active': promo.is_active})
    messages.success(request, 'Акция включена' if promo.is_active else 'Акция выключена')
    return redirect('panel:promotion', promotion_id=promo.pk)
