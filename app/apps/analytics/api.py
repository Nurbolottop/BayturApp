from rest_framework.response import Response

from apps.common.errors import ApiError
from apps.common.throttling import EventsThrottle, PublicIpThrottle
from apps.common.views import PublicAPIView

from .services import ingest


class EventsIngestView(PublicAPIView):
    throttle_classes = [PublicIpThrottle, EventsThrottle]

    def post(self, request):
        if not isinstance(request.data, dict) or not isinstance(request.data.get('events'), list):
            raise ApiError('validation_error', 400, extra={'fields': {'events': ['список']}})
        member = request.user if getattr(request.user, 'is_member', False) else None
        return Response(ingest(request.data, member, request._request.device_id), status=202)
