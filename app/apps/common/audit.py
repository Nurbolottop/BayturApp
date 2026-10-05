from django.core.serializers.json import DjangoJSONEncoder
import json

from .models import AuditLog
from .throttling import client_ip


def _jsonable(value):
    if value is None:
        return None
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, default=str))


def audit(request_or_actor, action, obj=None, before=None, after=None, comment='', object_type=None,
          object_id=None):
    """
    Пишет запись аудит-лога. Первый аргумент — HTTP-запрос (берутся сотрудник и IP)
    или сам сотрудник (фоновые действия), или None (система).
    """
    actor = None
    ip = None
    if request_or_actor is not None and hasattr(request_or_actor, 'META'):
        user = getattr(request_or_actor, 'user', None)
        actor = user if getattr(user, 'is_staff_user', False) else None
        ip = client_ip(request_or_actor)
    elif request_or_actor is not None:
        actor = request_or_actor
    if obj is not None:
        object_type = object_type or obj._meta.label_lower
        object_id = object_id or str(obj.pk)
    return AuditLog.objects.create(
        actor=actor,
        actor_label=(actor.email if actor else 'system'),
        ip=ip,
        action=action,
        object_type=object_type or '',
        object_id=str(object_id or ''),
        before=_jsonable(before),
        after=_jsonable(after),
        comment=comment or '',
    )


def model_snapshot(obj, fields=None):
    data = {}
    for f in obj._meta.concrete_fields:
        if fields and f.name not in fields:
            continue
        value = getattr(obj, f.attname)
        if hasattr(value, 'name') and hasattr(value, 'url'):
            value = value.name
        data[f.attname] = value
    return _jsonable(data)


def audit_system(action, before=None, after=None, comment='', object_type='', object_id=''):
    """Запись от имени системы (фоновые задачи, сверки)."""
    return audit(None, action, before=before, after=after, comment=comment, object_type=object_type,
                 object_id=object_id)
