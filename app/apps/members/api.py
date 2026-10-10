from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from apps.common.errors import ApiError
from apps.common.i18n import iso, tr
from apps.common.models import ProgramSettings
from apps.common.pagination import paginate
from apps.common.throttling import client_ip
from apps.common.views import MemberAPIView, PublicAPIView
from apps.common.versions import is_below

from . import auth, services
from .models import Device, Platform, SocialProvider


class OtpIpThrottle(SimpleRateThrottle):
    scope = 'otp_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


def _body(request, *required):
    data = request.data if isinstance(request.data, dict) else {}
    missing = [f for f in required if data.get(f) in (None, '')]
    if missing:
        raise ApiError('validation_error', 400, extra={'fields': {f: ['обязательно'] for f in missing}})
    return data


# ---------------------------------------------------------------- auth

class OtpRequestView(PublicAPIView):
    throttle_classes = PublicAPIView.throttle_classes + [OtpIpThrottle]

    def post(self, request):
        data = _body(request, 'phone')
        return Response(auth.request_otp(data['phone'], ip=client_ip(request), device_id=request._request.device_id))


class OtpVerifyView(PublicAPIView):
    def post(self, request):
        data = _body(request, 'phone', 'code')
        return Response(services.verify(data['phone'], data['code'], request._request.device_id,
                                        social_token=data.get('socialToken')))


class PinThrottle(SimpleRateThrottle):
    """Только защита сервера от перебора/нагрузки (хеш PIN считается дорого); блокировки аккаунта нет."""
    scope = 'pin_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class PinLoginView(PublicAPIView):
    """{phone, pin} — вход без SMS."""
    throttle_classes = PublicAPIView.throttle_classes + [PinThrottle]

    def post(self, request):
        data = _body(request, 'phone', 'pin')
        return Response(services.pin_login(data['phone'], data['pin'], request._request.device_id))


class PinResetView(PublicAPIView):
    """{phone, code, pin} — «Забыл PIN»: код из /auth/otp/request и новый PIN."""
    throttle_classes = PublicAPIView.throttle_classes + [PinThrottle]

    def post(self, request):
        data = _body(request, 'phone', 'code', 'pin')
        return Response(services.pin_reset(data['phone'], data['code'], data['pin'], request._request.device_id))


class GoogleLoginView(PublicAPIView):
    """{idToken} из Google Sign-In."""

    def post(self, request):
        data = _body(request, 'idToken')
        return Response(services.social_login(SocialProvider.GOOGLE, data['idToken'], request._request.device_id))


class AppleLoginView(PublicAPIView):
    """{identityToken, authorizationCode?, nonce?, firstName?, lastName?} из Sign in with Apple."""

    def post(self, request):
        data = _body(request, 'identityToken')
        return Response(services.social_login(
            SocialProvider.APPLE, data['identityToken'], request._request.device_id, nonce=data.get('nonce'),
            first_name=data.get('firstName') or '', last_name=data.get('lastName') or '',
            authorization_code=data.get('authorizationCode')))


class RegisterView(PublicAPIView):
    def post(self, request):
        data = _body(request, 'registrationToken', 'firstName', 'lastName')
        return Response(services.register(data, request._request.device_id, client_ip(request),
                                          avatar_file=request.FILES.get('avatar')), status=201)


class RefreshView(PublicAPIView):
    def post(self, request):
        data = _body(request, 'refreshToken')
        return Response(auth.rotate_refresh(data['refreshToken'], request._request.device_id))


class RestoreView(PublicAPIView):
    def post(self, request):
        data = _body(request, 'restoreToken')
        return Response(services.restore_with_token(data['restoreToken'], request._request.device_id))


class StartOverView(PublicAPIView):
    """«Начать заново» вместо восстановления: старый аккаунт стирается, дальше регистрация."""

    def post(self, request):
        data = _body(request, 'restoreToken')
        return Response(services.start_over(data['restoreToken'], request._request.device_id))


class LogoutView(MemberAPIView):
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        services.logout(request.user, data.get('refreshToken'), data.get('pushToken'))
        return Response(status=204)


# ---------------------------------------------------------------- профиль

class MeView(MemberAPIView):
    def get(self, request):
        return Response(services.profile_payload(request.user))

    def patch(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        if 'phone' in data:
            raise ApiError('permission_denied', 403,
                           message='Номер меняет ресепшен после проверки личности')
        services.update_profile(request.user, data)
        return Response(services.profile_payload(request.user))


class MeAvatarView(MemberAPIView):
    """Необязательный аватар: multipart, поле «file». DELETE — убрать."""

    def post(self, request):
        services.set_avatar(request.user, request.FILES.get('file'))
        return Response(services.profile_payload(request.user))

    def delete(self, request):
        services.remove_avatar(request.user)
        return Response(services.profile_payload(request.user))


class MePinView(MemberAPIView):
    """POST {pin, currentPin?} — задать PIN или сменить (currentPin обязателен, если PIN уже есть)."""

    def post(self, request):
        data = _body(request, 'pin')
        return Response(services.change_pin(request.user, data['pin'], data.get('currentPin')))


class MeSocialView(MemberAPIView):
    """Привязать Google / Apple ID из профиля: POST {idToken | identityToken, authorizationCode?, nonce?}. DELETE — отвязать."""

    def post(self, request, provider):
        data = request.data if isinstance(request.data, dict) else {}
        field = 'identityToken' if provider == SocialProvider.APPLE else 'idToken'
        _body(request, field)
        return Response(services.social_link(request.user, provider, data[field], data.get('nonce'),
                                             authorization_code=data.get('authorizationCode')))

    def delete(self, request, provider):
        services.social_unlink(request.user, provider)
        return Response(services.profile_payload(request.user))


class MeSettingsView(MemberAPIView):
    def patch(self, request):
        services.update_settings(request.user, request.data if isinstance(request.data, dict) else {},
                                 client_ip(request))
        return Response(services.profile_payload(request.user)['settings'])


class ConsentsView(MemberAPIView):
    def post(self, request):
        data = _body(request, 'kind', 'version')
        services.accept_consent(request.user, data['kind'], data['version'], client_ip(request))
        return Response({'pendingConsents': services.pending_consents(request.user)})


class DeviceSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(choices=Platform.choices)
    appVersion = serializers.CharField(max_length=20, required=False, allow_blank=True)


class DevicesView(MemberAPIView):
    def post(self, request):
        s = DeviceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        Device.objects.update_or_create(token=d['token'], defaults={
            'member': request.user, 'platform': d['platform'], 'app_version': d.get('appVersion', ''),
            'device_id': request._request.device_id or ''})
        return Response(status=204)


class DeviceDeleteView(MemberAPIView):
    def delete(self, request, token):
        Device.objects.filter(member=request.user, token=token).delete()
        return Response(status=204)


class MemberQrView(MemberAPIView):
    """Подписанный токен со сроком жизни 1–2 мин — скриншот чужого QR не сработает."""

    def get(self, request):
        token, expires = auth.make_member_qr(request.user)
        return Response({'token': token, 'expiresAt': iso(expires)})


class DeletionRequestView(MemberAPIView):
    def get(self, request):
        """Данные для экрана предупреждения без отправки SMS."""
        return Response(services.deletion_info(request.user))

    def post(self, request):
        return Response(services.deletion_request(request.user, client_ip(request), request._request.device_id))


class DeletionConfirmView(MemberAPIView):
    def post(self, request):
        data = _body(request, 'code')
        return Response(services.deletion_confirm(request.user, data['code']))


# ---------------------------------------------------------------- уведомления

class NotificationsView(MemberAPIView):
    def get(self, request):
        from apps.notifications.services import notification_payload
        page = paginate(request, request.user.notifications.all(),
                        lambda rows: [notification_payload(n) for n in rows])
        page['unread'] = request.user.notifications.filter(read_at__isnull=True).count()
        return Response(page)


class NotificationsReadView(MemberAPIView):
    """{id} — одно; {all: true} — все."""

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        qs = request.user.notifications.filter(read_at__isnull=True)
        if not data.get('all'):
            ids = data.get('ids') or ([data['id']] if data.get('id') else [])
            if not ids:
                raise ApiError('validation_error', 400, extra={'fields': {'id': ['обязательно']}})
            qs = qs.filter(pk__in=ids)
        qs.update(read_at=timezone.now())
        return Response({'unread': request.user.notifications.filter(read_at__isnull=True).count()})


# ---------------------------------------------------------------- справочные

class LegalView(PublicAPIView):
    def get(self, request):
        from apps.common.caching import cached_public
        return cached_public('legal', services.legal_payload, request)


class ResortContactsView(PublicAPIView):
    def get(self, request):
        from apps.common.caching import cached_public

        from apps.catalog.models import Venue
        from apps.catalog.modes import resolve_mode
        mode = resolve_mode(request)

        def build():
            ps = ProgramSettings.get()
            legal = services.legal_payload()
            data = {
                'phone': ps.resort_phone,
                'whatsapp': ps.resort_whatsapp.lstrip('+'),
                'mapsUrl': ps.resort_maps_url or None,
                'termsUrl': (legal.get('terms') or {}).get('url'),
                'privacyUrl': (legal.get('privacy') or {}).get('url'),
                'deletionUrl': (legal.get('deletion') or {}).get('url'),
            }
            venue = Venue.objects.filter(pk=mode).first() if mode != 'resort' else None
            if venue is not None:  # контакты текущего режима S&K (ТЗ экосистемы §6.1)
                data.update({'phone': venue.phone or None, 'whatsapp': (venue.whatsapp or '').lstrip('+') or None,
                             'email': venue.email or None, 'mapsUrl': venue.maps_url or None,
                             'twoGisUrl': venue.two_gis_url or None, 'address': tr(venue.address) or None})
            return data
        return cached_public('contacts', build, request, mode=mode)


class AppConfigView(PublicAPIView):
    """Минимальная версия приложения (принудительное обновление) и техработы."""

    def get(self, request):
        from apps.catalog.models import AppRelease, Venue
        from apps.catalog.modes import SEASON_NAMES, request_app, resolve_mode, seasons_payload
        ps = ProgramSettings.get()
        platform = request._request.platform
        version = request._request.app_version
        app = request_app(request)
        mode = resolve_mode(request)
        if app == 'sk':  # у Baytur S&K свои версии и техработы (ТЗ экосистемы §6.1)
            rel, _ = AppRelease.objects.get_or_create(app='sk')
            minimum = {'ios': rel.min_version_ios, 'android': rel.min_version_android}
            maintenance, message = rel.maintenance, rel.maintenance_message
        else:
            minimum = {'ios': ps.min_version_ios, 'android': ps.min_version_android}
            maintenance, message = ps.maintenance, ps.maintenance_message
        data = {
            'minVersion': minimum,
            'updateRequired': bool(platform in minimum and is_below(version, minimum[platform])),
            'maintenance': maintenance,
            'maintenanceMessage': tr(message) or None,
            'mode': mode,
        }
        if app == 'sk':
            venue = Venue.objects.filter(pk=mode).first()
            data.update({'season': SEASON_NAMES.get(mode), 'seasons': seasons_payload(),
                         'isOpen': bool(venue and venue.is_open), 'pointsPerSom': ps.points_per_som})
        return Response(data)
