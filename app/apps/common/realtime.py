"""
Realtime-события через Channels (WebSocket /api/v1/events и /api/v1/staff/events).
Формат: {"type": "request.updated", "data": {...}}. Отправка — после коммита транзакции.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

log = logging.getLogger(__name__)


def member_group(member_pk):
    return f'member.{member_pk}'


def outlet_group(outlet_id):
    return f'outlet.{outlet_id}'


ADMIN_GROUP = 'admins'


def _send(group, event_type, data):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group, {'type': 'push.event', 'event': {'type': event_type, 'data': data}})
    except Exception:  # realtime — best effort, клиент всё равно перезапросит GET
        log.exception('realtime send failed: %s %s', group, event_type)


def publish(group, event_type, data):
    transaction.on_commit(lambda: _send(group, event_type, data))


def publish_member(member_pk, event_type, data):
    publish(member_group(member_pk), event_type, data)


def publish_outlets(outlet_ids, event_type, data, include_admins=True):
    for oid in set(filter(None, outlet_ids)):
        publish(outlet_group(oid), event_type, data)
    if include_admins:
        publish(ADMIN_GROUP, event_type, data)
