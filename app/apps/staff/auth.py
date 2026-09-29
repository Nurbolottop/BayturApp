"""
Вход в админку и рабочее место: email + пароль + TOTP (обязательно, ТЗ §7.1).
Первый вход без настроенной 2FA → otpauthUri для приложения-аутентификатора, код подтверждает настройку.
"""
import uuid

from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission

from apps.common.errors import ApiError
from apps.common.tokens import bearer_token, decode_access, hash_token, issue_access, new_refresh_value

from .models import StaffRefreshToken, StaffUser
from .roles import PERMISSIONS

PASSWORD_CHANGE_PATHS = ('/api/v1/admin/me', '/api/v1/admin/me/password', '/api/v1/admin/auth/logout')
TWO_FACTOR_SALT = 'baytur.staff-2fa'
TWO_FACTOR_TTL = 300
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW = 900


def _too_many(key):
    attempts = cache.get(key, 0)
    return attempts >= LOGIN_ATTEMPTS


def _fail(key):
    if not cache.add(key, 1, LOGIN_WINDOW):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOGIN_WINDOW)


def check_password_step(email, password, ip=None):
    """→ (user, payload для ответа). Не выдаёт токены: второй шаг обязателен."""
    email = (email or '').strip().lower()
    key = f'staff-login:{email}:{ip}'
    if _too_many(key):
        raise ApiError('rate_limited', 429, extra={'retryIn': LOGIN_WINDOW})
    user = authenticate(username=email, password=password)
    if user is None or not user.is_active:
        _fail(key)
        raise ApiError('invalid_credentials', 401)
    cache.delete(key)
    token = signing.dumps({'u': user.pk}, salt=TWO_FACTOR_SALT)
    if user.totp_enabled:
        return user, {'twoFactorRequired': True, 'twoFactorToken': token}
    return user, {'twoFactorRequired': True, 'twoFactorSetup': True, 'twoFactorToken': token,
                  'otpauthUri': user.totp_uri()}


def check_totp_step(two_factor_token, code):
    try:
        data = signing.loads(two_factor_token or '', salt=TWO_FACTOR_SALT, max_age=TWO_FACTOR_TTL)
    except signing.BadSignature:
        raise ApiError('token_invalid', 401)
    user = StaffUser.objects.filter(pk=data['u'], is_active=True).first()
    if user is None:
        raise ApiError('token_invalid', 401)
    key = f'staff-2fa:{user.pk}'
    if _too_many(key):
        raise ApiError('rate_limited', 429, extra={'retryIn': LOGIN_WINDOW})
    if not user.verify_totp(code):
        _fail(key)
        raise ApiError('two_factor_required', 401)
    cache.delete(key)
    if not user.totp_enabled:
        user.totp_enabled = True
        user.save(update_fields=['totp_enabled'])
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])
    return user


def issue_tokens(user, family=None):
    value = new_refresh_value()
    StaffRefreshToken.objects.create(staff=user, token_hash=hash_token(value), family=family or uuid.uuid4().hex,
                                     expires_at=timezone.now() + settings.JWT_REFRESH_TTL)
    return {'accessToken': issue_access('staff', user.pk), 'refreshToken': value,
            'expiresIn': int(settings.JWT_ACCESS_TTL.total_seconds()), 'profile': staff_profile(user)}


def rotate(value):
    reused = False
    with transaction.atomic():
        t = StaffRefreshToken.objects.select_for_update().select_related('staff') \
            .filter(token_hash=hash_token(value or '')).first()
        if t is not None and t.revoked_at:
            StaffRefreshToken.objects.filter(family=t.family).update(revoked_at=timezone.now())
            reused = True
    if t is None or reused or t.expires_at < timezone.now() or not t.staff.is_active:
        raise ApiError('token_invalid', 401)
    with transaction.atomic():
        t = StaffRefreshToken.objects.select_for_update().select_related('staff').get(pk=t.pk)
        if t.revoked_at:
            raise ApiError('token_invalid', 401)
        t.revoked_at = timezone.now()
        t.save(update_fields=['revoked_at'])
        return issue_tokens(t.staff, family=t.family)


def revoke(value):
    StaffRefreshToken.objects.filter(token_hash=hash_token(value or '')).update(revoked_at=timezone.now())


def staff_profile(user):
    return {
        'id': user.pk,
        'email': user.email,
        'fullName': user.full_name,
        'role': user.role,
        'outlets': sorted(user.outlet_ids),
        'permissions': sorted(p for p in PERMISSIONS if user.can(p)),
        'mustChangePassword': user.must_change_password,
    }


def change_password(user, current, new):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    if not user.check_password(current or ''):
        raise ApiError('invalid_credentials', 401)
    try:
        validate_password(new or '', user)
    except ValidationError as e:
        raise ApiError('validation_error', 400, extra={'fields': {'newPassword': e.messages}})
    if current == new:
        raise ApiError('validation_error', 400, extra={'fields': {'newPassword': ['совпадает с текущим']}})
    user.set_password(new)
    user.must_change_password = False
    user.save(update_fields=['password', 'must_change_password'])


class StaffAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = bearer_token(request)
        if not token:
            return None
        payload = decode_access(token, 'staff')
        if payload is None:
            raise ApiError('token_invalid', 401)
        user = StaffUser.objects.filter(pk=payload['sub'], is_active=True).first()
        if user is None:
            raise ApiError('token_invalid', 401)
        # временный пароль: до смены доступны только профиль, смена пароля и выход
        if user.must_change_password and request.path not in PASSWORD_CHANGE_PATHS:
            raise ApiError('password_change_required', 403)
        return user, payload

    def authenticate_header(self, request):
        return 'Bearer'


class IsStaff(BasePermission):
    def has_permission(self, request, view):
        return bool(getattr(request.user, 'is_staff_user', False))


class HasPerm(BasePermission):
    """view.required_perms = {'GET': 'members.view', 'POST': 'members.manage'} или строка."""

    def has_permission(self, request, view):
        user = request.user
        if not getattr(user, 'is_staff_user', False):
            return False
        req = getattr(view, 'required_perms', None)
        if req is None:
            return True
        if isinstance(req, dict):
            perm = req.get(request.method) or req.get('*')
        else:
            perm = req
        if perm is None:
            return False
        perms = perm if isinstance(perm, (list, tuple, set)) else [perm]
        return any(user.can(p) for p in perms)
