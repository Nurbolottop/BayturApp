"""
Курсорная пагинация: {"items": [...], "nextCursor": "..." | null}, новые сверху.
Курсор — base64 от (время, id) последней записи; стабилен при вставке новых.
"""
import base64
import json
from datetime import datetime

from django.db.models import Q

from .errors import ApiError

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _encode(ts, pk):
    raw = json.dumps([ts.isoformat(), pk]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _decode(cursor):
    try:
        pad = '=' * (-len(cursor) % 4)
        ts, pk = json.loads(base64.urlsafe_b64decode(cursor + pad))
        return datetime.fromisoformat(ts), pk
    except Exception:
        raise ApiError('validation_error', 400, extra={'fields': {'cursor': ['invalid']}})


def get_limit(request, default=DEFAULT_LIMIT):
    try:
        limit = int(request.query_params.get('limit', default))
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, MAX_LIMIT))


def paginate(request, queryset, serialize, time_field='created_at', default_limit=DEFAULT_LIMIT):
    """queryset сортируется по (-time_field, -pk). serialize(list) → list of dict."""
    limit = get_limit(request, default_limit)
    qs = queryset.order_by(f'-{time_field}', '-pk')
    cursor = request.query_params.get('cursor')
    if cursor:
        ts, pk = _decode(cursor)
        qs = qs.filter(Q(**{f'{time_field}__lt': ts}) | Q(**{time_field: ts, 'pk__lt': pk}))
    rows = list(qs[:limit + 1])
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode(getattr(last, time_field), last.pk)
    return {'items': serialize(rows), 'nextCursor': next_cursor}
