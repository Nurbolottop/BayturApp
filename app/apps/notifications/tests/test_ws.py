from asgiref.sync import async_to_sync, sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase

from apps.common.realtime import _send, member_group, outlet_group
from apps.notifications.routing import websocket_urlpatterns

app = URLRouter(websocket_urlpatterns)


class WebSocketTests(TransactionTestCase):
    def setUp(self):
        from apps.members.models import Member
        self.member = Member.objects.create(phone='+996555777888', first_name='A', last_name='B')

    def test_member_events(self):
        from apps.members.auth import issue_tokens
        token = issue_tokens(self.member)['accessToken']

        async def run():
            ws = WebsocketCommunicator(app, f'/api/v1/events?token={token}')
            connected, _ = await ws.connect()
            self.assertTrue(connected)
            await sync_to_async(_send)(member_group(self.member.pk), 'wallet.updated', {'balance': 1})
            self.assertEqual(await ws.receive_json_from(), {'type': 'wallet.updated', 'data': {'balance': 1}})
            await ws.send_json_to({'type': 'ping'})
            self.assertEqual(await ws.receive_json_from(), {'type': 'pong'})
            await ws.disconnect()

            anon = WebsocketCommunicator(app, '/api/v1/events')
            connected, code = await anon.connect()
            self.assertFalse(connected)
        async_to_sync(run)()

    def test_staff_events_only_own_outlet(self):
        from apps.catalog.models import Outlet
        from apps.staff.auth import issue_tokens
        from apps.staff.models import StaffUser
        Outlet.objects.create(id='spa', name={'ru': 'SPA'})
        user = StaffUser.objects.create_user('s@baytur.kg', 'Passw0rd!x', full_name='S', role='staff')
        user.outlets.set(['spa'])
        token = issue_tokens(user)['accessToken']

        async def run():
            ws = WebsocketCommunicator(app, f'/api/v1/staff/events?token={token}')
            connected, _ = await ws.connect()
            self.assertTrue(connected)
            await sync_to_async(_send)(outlet_group('davinci'), 'request.created', {'id': 'other'})
            await sync_to_async(_send)(outlet_group('spa'), 'request.created', {'id': 'mine'})
            self.assertEqual((await ws.receive_json_from())['data'], {'id': 'mine'})
            await ws.disconnect()
            member_token = WebsocketCommunicator(app, '/api/v1/staff/events?token=bad')
            connected, _ = await member_token.connect()
            self.assertFalse(connected)
        async_to_sync(run)()
