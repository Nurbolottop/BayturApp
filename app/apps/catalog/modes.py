"""
Режим запроса (ТЗ экосистемы §3.2): X-Baytur-App (resort | sk; нет заголовка — resort) и необязательный
X-Baytur-Mode (resort | ski | kymyz). Для sk без явного режима — активный сезон по датам из админки,
между сезонами — режим, выбранный для межсезонья, иначе ближайший предстоящий сезон.
"""
from django.utils import timezone

from apps.common.errors import ApiError

from .models import APP_MODES, Season

SEASON_NAMES = {'ski': 'winter', 'kymyz': 'summer'}


def request_app(request):
    app = (request.headers.get('X-Baytur-App') or 'resort').strip().lower()
    if app not in APP_MODES:
        raise ApiError('mode_not_allowed', 400)
    return app


def forced_sk_mode():
    """Сезон, выбранный в админке для всех пользователей S&K; '' — по датам."""
    from apps.common.models import ProgramSettings
    return ProgramSettings.get().sk_mode or ''


def active_sk_mode(today=None):
    forced = forced_sk_mode()
    if forced:
        return forced
    today = today or timezone.localdate()
    seasons = list(Season.objects.filter(venue__app='sk', venue__is_active=True).order_by('starts_at'))
    for s in seasons:
        if s.starts_at <= today <= s.ends_at:
            return s.venue_id
    upcoming = [s for s in seasons if s.starts_at > today]
    if upcoming:
        nxt = upcoming[0]
        return nxt.off_season_mode_id or nxt.venue_id
    return seasons[-1].venue_id if seasons else APP_MODES['sk'][0]


def resolve_mode(request):
    """Режим запроса; кешируется на объекте запроса. Недопустимая пара → 400 mode_not_allowed."""
    raw = getattr(request, '_request', request)
    cached = getattr(raw, '_baytur_mode', None)
    if cached:
        return cached
    app = request_app(request)
    explicit = (request.headers.get('X-Baytur-Mode') or '').strip().lower()
    if explicit and explicit not in APP_MODES[app]:
        raise ApiError('mode_not_allowed', 400)
    forced = forced_sk_mode() if app == 'sk' else ''
    if forced:  # сезон выбран в админке — все пользователи S&K видят только его
        mode = forced
    elif explicit:
        mode = explicit
    elif app == 'resort':
        mode = 'resort'
    else:
        mode = active_sk_mode()
    raw._baytur_mode = mode
    return mode


def seasons_payload(today=None):
    today = today or timezone.localdate()
    out = []
    for s in Season.objects.filter(venue__app='sk', ends_at__gte=today).order_by('starts_at'):
        item = {'mode': s.venue_id, 'season': SEASON_NAMES.get(s.venue_id), 'startsAt': s.starts_at.isoformat(),
                'endsAt': s.ends_at.isoformat()}
        if s.early_booking_from:
            item['earlyBookingFrom'] = s.early_booking_from.isoformat()
        out.append(item)
    return out
