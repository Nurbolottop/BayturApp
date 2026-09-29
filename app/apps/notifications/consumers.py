"""
WebSocket:
  /api/v1/events?token=<access>        — клиент: request.updated, wallet.updated, notification.created,
                                         payment.updated, complaint.updated
  /api/v1/staff/events?token=<access>  — сотрудник: request.created / request.updated по своим точкам;
                                         админка (сессия браузера) — все события + complaint.*
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.common.realtime import ADMIN_GROUP, member_group, outlet_group
from apps.common.tokens import decode_access


def _query_token(scope):
    qs = parse_qs(scope.get('query_string', b'').decode())
    token = (qs.get('token') or [None])[0]
    if token:
        return token
    for name, value in scope.get('headers', []):
        if name == b'authorization' and value.lower().startswith(b'bearer '):
            return value[7:].decode()
    return None


@database_sync_to_async
def _member_for(token):
    from apps.members.models import Member, MemberStatus
    payload = decode_access(token or '', 'member')
    if not payload:
        return None
    return Member.objects.filter(pk=payload['sub'], status=MemberStatus.ACTIVE).first()


def _same_origin(scope):
    """Сессионное подключение админки — только со своего домена (защита от cross-site WS hijacking)."""
    from urllib.parse import urlparse

    from django.conf import settings
    from django.http.request import validate_host
    origin = dict(scope.get('headers', [])).get(b'origin')
    if not origin:
        return False
    host = urlparse(origin.decode()).hostname or ''
    return validate_host(host, settings.ALLOWED_HOSTS or ['localhost', '127.0.0.1'])


@database_sync_to_async
def _staff_groups(token, session_user):
    from apps.staff.models import StaffUser
    user = None
    if token:
        payload = decode_access(token, 'staff')
        if payload:
            user = StaffUser.objects.filter(pk=payload['sub'], is_active=True).first()
    elif session_user is not None and getattr(session_user, 'is_staff_user', False) and session_user.is_active:
        user = session_user
    if user is None or not user.can('requests.process') and not user.can('complaints.view'):
        return None
    if user.is_outlet_bound:
        return [outlet_group(o) for o in user.outlet_ids]
    return [ADMIN_GROUP]


class _Base(AsyncJsonWebsocketConsumer):
    groups_joined = ()

    async def disconnect(self, code):
        for g in self.groups_joined:
            await self.channel_layer.group_discard(g, self.channel_name)

    async def push_event(self, message):
        await self.send_json(message['event'])

    async def receive_json(self, content, **kwargs):
        if content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})


class MemberEventsConsumer(_Base):
    async def connect(self):
        member = await _member_for(_query_token(self.scope))
        if member is None:
            await self.close(code=4401)
            return
        self.groups_joined = [member_group(member.pk)]
        for g in self.groups_joined:
            await self.channel_layer.group_add(g, self.channel_name)
        await self.accept()


class StaffEventsConsumer(_Base):
    async def connect(self):
        token = _query_token(self.scope)
        session_user = self.scope.get('user') if not token and _same_origin(self.scope) else None
        groups = await _staff_groups(token, session_user)
        if not groups:
            await self.close(code=4403)
            return
        self.groups_joined = groups
        for g in groups:
            await self.channel_layer.group_add(g, self.channel_name)
        await self.accept()
