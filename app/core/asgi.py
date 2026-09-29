"""
ASGI: HTTP — Django, WebSocket — Channels.

WS: /api/v1/events (клиент), /api/v1/staff/events (сотрудник/админка).
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.dev')

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.notifications.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    # сессия браузера — для админки; мобилка передаёт ?token=<access>
    'websocket': AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
