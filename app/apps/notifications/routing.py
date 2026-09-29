from django.urls import path

from .consumers import MemberEventsConsumer, StaffEventsConsumer

websocket_urlpatterns = [
    path('api/v1/events', MemberEventsConsumer.as_asgi()),
    path('api/v1/staff/events', StaffEventsConsumer.as_asgi()),
]
