"""
Переключатель режима в шапке панели (ТЗ экосистемы §7.1): Resort & Spa · Ski · Kymyz.
Выбор хранится в сессии сотрудника и виден в URL (?mode=ski) — ссылкой можно поделиться.
Сотруднику, привязанному к точкам, доступны только режимы своих точек; если режим один — переключатель скрыт.
"""
from django.utils import timezone

from apps.catalog.models import DEFAULT_VENUE, Venue

SESSION_KEY = 'panel_mode'


def allowed_modes(user):
    venues = list(Venue.objects.prefetch_related('seasons'))
    if getattr(user, 'is_outlet_bound', False):
        own = set(user.outlets.values_list('venue_id', flat=True))
        venues = [v for v in venues if v.pk in own] or venues[:1]
    return venues


def current_mode(request):
    """Режим из ?mode= (или старого ?venue=), иначе из сессии, иначе первый доступный."""
    if hasattr(request, '_panel_mode'):
        return request._panel_mode
    venues = allowed_modes(request.user)
    ids = [v.pk for v in venues]
    wanted = request.GET.get('mode') or request.GET.get('venue') or request.session.get(SESSION_KEY)
    mode = wanted if wanted in ids else (DEFAULT_VENUE if DEFAULT_VENUE in ids else (ids[0] if ids else DEFAULT_VENUE))
    if request.session.get(SESSION_KEY) != mode:
        request.session[SESSION_KEY] = mode
    request._panel_mode = mode
    request._panel_venues = venues
    return mode


def season_status(venue, today=None, forced=''):
    """«Сезон идёт» / «До сезона N дн.» / «Закрыто» — для S&K по датам сезонов или по выбору в админке."""
    if not venue.is_open:
        return 'Закрыто'
    if venue.app != 'sk':
        return 'Открыт'
    if forced:
        return 'Показывается всем' if forced == venue.pk else 'Скрыт: выбран другой сезон'
    today = today or timezone.localdate()
    seasons = [s for s in venue.seasons.all() if s.ends_at >= today]
    if not seasons:
        return 'Сезон не задан'
    first = min(seasons, key=lambda s: s.starts_at)
    if first.starts_at <= today:
        return 'Сезон идёт'
    return f'До сезона {(first.starts_at - today).days} дн.'


def modes_context(request):
    from apps.cashback.models import CashbackRequest, RequestStatus
    mode = current_mode(request)
    venues = request._panel_venues
    queue = {}
    if request.user.can('requests.process'):
        qs = CashbackRequest.objects.filter(status=RequestStatus.PENDING)
        if request.user.is_outlet_bound:
            qs = qs.filter(outlet_id__in=request.user.outlet_ids)
        for venue_id in qs.values_list('item__venue_id', flat=True):
            queue[venue_id] = queue.get(venue_id, 0) + 1
    current = next((v for v in venues if v.pk == mode), None)
    from apps.common.models import ProgramSettings
    forced = ProgramSettings.get().sk_mode or ''
    return {
        'panel_sk_mode': forced,
        'panel_can_season': request.user.can('catalog.edit') and any(v.app == 'sk' for v in venues),
        'panel_mode': mode,
        'panel_mode_venue': current,
        'panel_accent': current.accent if current else '#C6F24E',
        'panel_modes': [{'id': v.pk, 'name': v.name.get('ru') or v.pk, 'accent': v.accent, 'on': v.pk == mode,
                         'status': season_status(v, forced=forced), 'queue': queue.get(v.pk, 0)} for v in venues]
        if len(venues) > 1 else [],
    }
