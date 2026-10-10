"""Режимы экосистемы в панели (ТЗ §7): переключатель, «Объект» (контакты, сезоны), «Главная», «Вечная новость»."""
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.catalog.models import SHOWCASE_ICONS, AppRelease, EternalNews, Section, Showcase, Venue
from apps.common.audit import audit, model_snapshot

from ..access import forbidden, is_staff_user, panel_view
from ..forms import AppReleaseForm, EternalNewsForm, NewsFormSet, SeasonFormSet, ShowcaseForm, VenueForm
from ..modes import SESSION_KEY, allowed_modes, current_mode
from ..sections import BY_KEY


def mode_switch(request, mode):
    """Переключить режим и вернуться в тот же раздел (его список — детальные страницы принадлежат режиму)."""
    if not is_staff_user(request.user):
        return redirect('panel:login')
    if mode not in {v.pk for v in allowed_modes(request.user)}:
        return forbidden(request, 'Этот режим вам недоступен')
    request.session[SESSION_KEY] = mode
    section = BY_KEY.get(request.GET.get('section') or '')
    nxt = request.GET.get('next') or ''
    if section and section.allowed(request.user):
        target = section.url
    elif nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}) and nxt.startswith('/panel/'):
        target = nxt.split('?')[0]
    else:
        target = reverse('panel:home')
    return redirect(f'{target}?mode={mode}')


def _venue(request):
    return get_object_or_404(Venue, pk=current_mode(request))


@panel_view('venue')
def venue_current(request):
    return redirect('panel:venue', venue_id=current_mode(request))


@panel_view('venue')
def venue_edit(request, venue_id):
    """Объект: тексты, контакты, карты, «открыт», ранняя бронь, сезоны и (для S&K) версии приложения."""
    venue = get_object_or_404(Venue, pk=venue_id)
    if venue_id not in {v.pk for v in allowed_modes(request.user)}:
        return forbidden(request, 'Этот режим вам недоступен')
    can_edit = request.user.can('catalog.edit')
    data = request.POST or None
    form = VenueForm(data, instance=venue)
    if not can_edit:
        form.lock(['sort_order', 'is_active', 'is_open', 'early_booking_enabled', 'accent'])
    is_sk = venue.app == 'sk'
    seasons = SeasonFormSet(data if can_edit else None, instance=venue, prefix='seasons') if is_sk else None
    release = AppReleaseForm(data if can_edit else None, instance=AppRelease.objects.get_or_create(app='sk')[0],
                             prefix='app') if is_sk else None
    if request.method == 'POST':
        ok = form.is_valid() and (not can_edit or not is_sk or (seasons.is_valid() and release.is_valid()))
        if ok:
            before = model_snapshot(venue)
            with transaction.atomic():
                obj = form.save()
                if is_sk and can_edit:
                    seasons.save()
                    release.save()
            audit(request, 'venue.update', obj, before=before, after=model_snapshot(obj))
            messages.success(request, 'Объект сохранён')
            return redirect('panel:venue', venue_id=obj.pk)
    return render(request, 'panel/modes/venue.html', {
        'form': form, 'venue': venue, 'seasons': seasons, 'release': release, 'can_edit': can_edit})


SHOWCASE_ICON_LABELS = {'skipass': 'скипасс', 'rental': 'прокат', 'stay': 'проживание', 'transfer': 'трансфер',
                        'cafe': 'кафе', 'trails': 'трассы', 'yurt': 'юрта', 'massage': 'массаж', 'kymyz': 'кымыз',
                        'banya': 'баня', 'horses': 'лошади'}


def _section_choices(venue):
    qs = Section.objects.filter(venue=venue, parent__isnull=True).exclude(key='').order_by('sort_order', 'id')
    return [(s.key, s.title.get('ru') or s.key) for s in qs]


@panel_view('showcase')
def showcase_edit(request):
    """Главная режима: шапка, факты, кнопка, плитки и новости. Лента акций — акции с «показать на главной»."""
    venue = _venue(request)
    showcase, _ = Showcase.objects.get_or_create(venue=venue)
    data = request.POST or None
    form = ShowcaseForm(data, instance=showcase, sections=_section_choices(venue))
    news = NewsFormSet(data, instance=venue, prefix='news')
    if request.method == 'POST' and form.is_valid() and news.is_valid():
        before = model_snapshot(showcase)
        with transaction.atomic():
            obj = form.save()
            news.save()
        audit(request, 'showcase.update', obj, before=before, after=model_snapshot(obj))
        messages.success(request, 'Главная сохранена')
        return redirect(f"{reverse('panel:showcase')}?mode={venue.pk}")
    from apps.catalog.models import Item, Promotion
    from apps.catalog.promotions import covers
    items = list(Item.objects.filter(venue=venue, is_active=True).select_related('section__parent'))
    promos = [p for p in Promotion.objects.filter(show_on_home=True, is_active=True).prefetch_related(
        'items', 'sections', 'venues') if any(covers(p, i) for i in items)]
    return render(request, 'panel/modes/showcase.html', {
        'form': form, 'news': news, 'venue': venue, 'promos': promos,
        'showcase_icons': [(k, SHOWCASE_ICON_LABELS.get(k, k)) for k in SHOWCASE_ICONS]})


@panel_view('eternal')
def eternal_edit(request):
    """«Вечная новость» режима S&K: одна на режим показа; рассказывает о другом сезоне."""
    venue = _venue(request)
    if venue.app != 'sk':
        messages.warning(request, '«Вечная новость» есть только у Ski и Kymyz')
        return redirect('panel:home')
    eternal = EternalNews.objects.filter(show_in__contains=[venue.pk]).first()
    if eternal is None:
        other = Venue.objects.filter(app='sk').exclude(pk=venue.pk).first()
        eternal = EternalNews(about=other, show_in=[venue.pk])
    form = EternalNewsForm(request.POST or None, instance=eternal,
                           initial=None if eternal.pk else {'about': eternal.about_id, 'show_in': [venue.pk]})
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(eternal) if eternal.pk else None
        obj = form.save()
        audit(request, 'eternal.update' if before else 'eternal.create', obj, before=before,
              after=model_snapshot(obj))
        messages.success(request, '«Вечная новость» сохранена')
        return redirect(f"{reverse('panel:eternal')}?mode={venue.pk}")
    return render(request, 'panel/modes/eternal.html', {'form': form, 'venue': venue, 'eternal': eternal})
