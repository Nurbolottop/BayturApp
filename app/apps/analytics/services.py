from datetime import datetime, timedelta

from django.utils import timezone

from apps.common.models import ProgramSettings

from .models import ALLOWED_PROPS, EVENT_NAMES, AppEvent, DeviceLink

MAX_BATCH = 200
MAX_SKEW = timedelta(days=7)


def _clean_props(props):
    """Только разрешённые ключи и простые значения — персональные данные в props запрещены."""
    if not isinstance(props, dict):
        return {}
    clean = {}
    for k, v in props.items():
        if k not in ALLOWED_PROPS:
            continue
        if isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) <= 80):
            clean[k] = v
    return clean


def ingest(batch, member=None, device_id=None):
    """POST /events — пачка раз в 30 с и при уходе в фон. Неизвестные события отбрасываются."""
    device = str(batch.get('deviceId') or device_id or '')[:36]
    if not device:
        return {'accepted': 0, 'dropped': len(batch.get('events') or [])}
    platform = str(batch.get('platform') or '')[:10]
    now = timezone.now()
    rows, dropped = [], 0
    for e in (batch.get('events') or [])[:MAX_BATCH]:
        name = e.get('name') if isinstance(e, dict) else None
        if name not in EVENT_NAMES:
            dropped += 1
            continue
        try:
            at = datetime.fromisoformat(str(e.get('at')).replace('Z', '+00:00'))
            if timezone.is_naive(at):
                at = timezone.make_aware(at)
        except (TypeError, ValueError):
            at = now
        if abs(at - now) > MAX_SKEW:
            at = now
        rows.append(AppEvent(device_id=device, member=member, platform=platform,
                             app_version=str(batch.get('appVersion') or '')[:20],
                             language=str(batch.get('language') or '')[:2], name=name, at=at,
                             props=_clean_props(e.get('props'))))
    AppEvent.objects.bulk_create(rows)
    link, created = DeviceLink.objects.get_or_create(device_id=device, defaults={'platform': platform,
                                                                                   'member': member})
    if member and link.member_id is None:
        DeviceLink.objects.filter(pk=link.pk).update(member=member)
    return {'accepted': len(rows), 'dropped': dropped + max(0, len(batch.get('events') or []) - MAX_BATCH)}


def purge_old_events():
    days = ProgramSettings.get().analytics_raw_retention_days
    return AppEvent.objects.filter(at__lt=timezone.now() - timedelta(days=days)).delete()[0]
