from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import ApiError
from apps.common.throttling import client_ip

from . import auth


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        _, payload = auth.check_password_step(request.data.get('email'), request.data.get('password'),
                                              client_ip(request))
        return Response(payload)


class TwoFactorView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user = auth.check_totp_step(request.data.get('twoFactorToken'), request.data.get('code'))
        return Response(auth.issue_tokens(user))


class RefreshView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not request.data.get('refreshToken'):
            raise ApiError('validation_error', 400, extra={'fields': {'refreshToken': ['обязательно']}})
        return Response(auth.rotate(request.data['refreshToken']))


class LogoutView(APIView):
    authentication_classes = [auth.StaffAuthentication]
    permission_classes = [auth.IsStaff]

    def post(self, request):
        auth.revoke(request.data.get('refreshToken'))
        return Response(status=204)


class MeView(APIView):
    authentication_classes = [auth.StaffAuthentication]
    permission_classes = [auth.IsStaff]

    def get(self, request):
        return Response(auth.staff_profile(request.user))


class PasswordView(APIView):
    """Смена пароля (обязательна после выдачи временного)."""

    authentication_classes = [auth.StaffAuthentication]
    permission_classes = [auth.IsStaff]

    def post(self, request):
        auth.change_password(request.user, request.data.get('currentPassword'), request.data.get('newPassword'))
        return Response(auth.staff_profile(request.user))


# ---------------------------------------------------------------- приложение кассира (телефон + PIN)

class PinLoginView(APIView):
    """POST {phone, pin} → {accessToken, refreshToken, expiresIn, profile}. Только администраторы касс."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user = auth.check_pin_login(request.data.get('phone'), request.data.get('pin'), client_ip(request))
        from apps.common.audit import audit
        audit(user, 'staff.login', user, comment='приложение кассира')
        return Response(auth.issue_tokens(user))


class PinChangeView(APIView):
    """POST {currentPin, newPin} — администратор меняет свой PIN."""

    authentication_classes = [auth.StaffAuthentication]
    permission_classes = [auth.IsStaff]

    def post(self, request):
        auth.change_pin(request.user, request.data.get('currentPin'), request.data.get('newPin'))
        return Response(auth.staff_profile(request.user))


class DevicesView(APIView):
    """POST {token, platform, appVersion} — push-токен приложения кассира (после входа и при onTokenRefresh)."""

    authentication_classes = [auth.StaffAuthentication]
    permission_classes = [auth.IsStaff]

    def post(self, request):
        from .models import StaffDevice
        data = request.data if isinstance(request.data, dict) else {}
        token, platform = str(data.get('token') or '').strip(), data.get('platform')
        if not token or len(token) > 512 or platform not in ('ios', 'android'):
            raise ApiError('validation_error', 400, extra={'fields': {'token': ['обязательно'],
                                                                      'platform': ['ios | android']}})
        StaffDevice.objects.update_or_create(token=token, defaults={
            'staff': request.user, 'platform': platform, 'app_version': str(data.get('appVersion') or '')[:20]})
        return Response(status=204)


class DeviceDeleteView(APIView):
    authentication_classes = [auth.StaffAuthentication]
    permission_classes = [auth.IsStaff]

    def delete(self, request, token):
        from .models import StaffDevice
        StaffDevice.objects.filter(staff=request.user, token=token).delete()
        return Response(status=204)
