from rest_framework.permissions import BasePermission
from rest_framework.views import APIView

from apps.members.auth import MemberAuthentication, OptionalMemberAuthentication

from .throttling import PUBLIC_THROTTLES


class IsMember(BasePermission):
    def has_permission(self, request, view):
        return bool(getattr(request.user, 'is_member', False))


class PublicAPIView(APIView):
    """Без токена; с токеном отвечает так же (один кеш для всех). Rate limit по IP и X-Device-Id."""

    authentication_classes = [OptionalMemberAuthentication]
    permission_classes = []
    throttle_classes = PUBLIC_THROTTLES


class MemberAPIView(APIView):
    """Личные эндпоинты: без токена → 401 auth_required."""

    authentication_classes = [MemberAuthentication]
    permission_classes = [IsMember]
    throttle_classes = PUBLIC_THROTTLES
