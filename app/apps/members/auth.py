"""
Вход по телефону + SMS-коду (ТЗ §2): один сценарий для входа и регистрации, паролей нет.
Access — JWT ≈15 мин; refresh — непрозрачный, 30 дней, ротация (старый сразу недействителен;
повторное использование отозванного → отзыв всей цепочки).
"""
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from apps.common.errors import ApiError
from apps.common.models import ProgramSettings
from apps.common.tokens import bearer_token, decode_access, hash_token, issue_access, new_refresh_value

from .models import Member, MemberRefreshToken, MemberStatus, OtpChallenge, OtpPurpose
from .sms import SmsError, real_sms_for, send_sms

E164 = re.compile(r'^\+[1-9]\d{7,14}$')

REGISTRATION_SALT = 'baytur.registration'
RESTORE_SALT = 'baytur.restore'
MEMBER_QR_SALT = 'baytur.member-qr'
SOCIAL_SALT = 'baytur.social'
REGISTRATION_TTL = 15 * 60


def normalize_phone(phone):
    phone = re.sub(r'[\s\-()]', '', str(phone or ''))
    if phone.startswith('00'):
        phone = '+' + phone[2:]
    if not phone.startswith('+'):
        phone = '+' + phone
    if not E164.match(phone):
        raise ApiError('phone_invalid', 400)
    return phone


# ---------------------------------------------------------------- OTP

def _code_hash(phone, code):
    return hmac.new(settings.SECRET_KEY.encode(), f'{phone}:{code}'.encode(), hashlib.sha256).hexdigest()


def _is_test_phone(phone, ps):
    return ps.test_enabled and ps.test_phone and phone == ps.test_phone


def _count_limit(key, limit, ttl):
    """Счётчик в кеше; True — лимит превышен."""
    added = cache.add(key, 1, ttl)
    if added:
        return False
    try:
        value = cache.incr(key)
    except ValueError:
        cache.set(key, 1, ttl)
        return False
    return value > limit


def fixed_otp_code(phone):
    """OTP_FIXED_CODE: один код на dev/staging для номеров, на которые настоящая SMS не уходит."""
    if settings.APP_ENV == 'production' or real_sms_for(phone):
        return ''
    return settings.OTP_FIXED_CODE


def request_otp(phone, purpose=OtpPurpose.LOGIN, ip=None, device_id=None):
    ps = ProgramSettings.get()
    phone = normalize_phone(phone)
    now = timezone.now()
    last = OtpChallenge.objects.filter(phone=phone, purpose=purpose).order_by('-created_at').first()
    if last and (now - last.created_at).total_seconds() < ps.otp_retry_seconds:
        retry = ps.otp_retry_seconds - int((now - last.created_at).total_seconds())
        raise ApiError('otp_too_often', 429, extra={'retryIn': retry})

    test = _is_test_phone(phone, ps)
    if not test:
        # защита от SMS-флуда: на номер в сутки и на IP в час
        if _count_limit(f'otp:phone:{phone}:{now:%Y%m%d}', ps.otp_per_phone_day, 86400):
            raise ApiError('otp_limit', 429, extra={'retryIn': 3600})
        if ip and _count_limit(f'otp:ip:{ip}:{now:%Y%m%d%H}', ps.otp_per_ip_hour, 3600):
            raise ApiError('otp_limit', 429, extra={'retryIn': 3600})

    fixed = fixed_otp_code(phone)
    if test:
        code = ps.test_code
    elif fixed:
        code = fixed  # временно, пока не подключён SMS-провайдер (только не production)
    else:
        code = ''.join(secrets.choice('0123456789') for _ in range(ps.otp_length))
    if not test:
        # сначала отправка: если провайдер не принял SMS, прежний код остаётся в силе и повтор доступен сразу
        text = {'login': f'BAYTUR: код входа {code}', 'deletion': f'BAYTUR: код для удаления аккаунта {code}'}
        try:
            send_sms(phone, text.get(purpose, code))
        except SmsError:
            raise ApiError('sms_unavailable', 503)
    OtpChallenge.objects.filter(phone=phone, purpose=purpose, used_at__isnull=True).update(burned=True)
    OtpChallenge.objects.create(phone=phone, purpose=purpose, code_hash=_code_hash(phone, code),
                                expires_at=now + timedelta(seconds=ps.otp_ttl_seconds), ip=ip,
                                device_id=device_id or '')
    return {'expiresIn': ps.otp_ttl_seconds, 'retryIn': ps.otp_retry_seconds}


def check_otp(phone, code, purpose=OtpPurpose.LOGIN):
    """После 5 ошибок код сгорает."""
    ps = ProgramSettings.get()
    phone = normalize_phone(phone)
    error = None
    with transaction.atomic():
        ch = OtpChallenge.objects.select_for_update().filter(
            phone=phone, purpose=purpose, used_at__isnull=True, burned=False).order_by('-created_at').first()
        if ch is None or timezone.now() > ch.expires_at:
            error = ApiError('otp_expired', 400)
        elif not hmac.compare_digest(ch.code_hash, _code_hash(phone, str(code or '').strip())):
            ch.attempts += 1
            if ch.attempts >= ps.otp_max_attempts:
                ch.burned = True
            ch.save(update_fields=['attempts', 'burned'])
            error = ApiError('otp_expired', 400) if ch.burned else \
                ApiError('otp_invalid', 400, extra={'attemptsLeft': ps.otp_max_attempts - ch.attempts})
        else:
            ch.used_at = timezone.now()
            ch.save(update_fields=['used_at'])
    # ошибка — после коммита, иначе счётчик попыток откатится вместе с транзакцией
    if error:
        raise error
    return phone


# ---------------------------------------------------------------- токены

def issue_tokens(member, device_id=None, family=None):
    value = new_refresh_value()
    MemberRefreshToken.objects.create(
        member=member, token_hash=hash_token(value), family=family or uuid.uuid4().hex,
        device_id=device_id or '', expires_at=timezone.now() + settings.JWT_REFRESH_TTL)
    return {'accessToken': issue_access('member', member.pk), 'refreshToken': value,
            'expiresIn': int(settings.JWT_ACCESS_TTL.total_seconds())}


def rotate_refresh(value, device_id=None):
    reused = False
    with transaction.atomic():
        token = MemberRefreshToken.objects.select_for_update().select_related('member') \
            .filter(token_hash=hash_token(value or '')).first()
        if token is not None and token.revoked_at is not None:
            # повторное использование отозванного refresh — вероятная кража: отзываем всю цепочку
            MemberRefreshToken.objects.filter(family=token.family, revoked_at__isnull=True) \
                .update(revoked_at=timezone.now())
            reused = True
    if token is None or reused or token.expires_at < timezone.now():
        raise ApiError('token_invalid', 401)
    with transaction.atomic():
        token = MemberRefreshToken.objects.select_for_update().select_related('member').get(pk=token.pk)
        if token.revoked_at is not None:  # параллельная ротация тем же токеном
            raise ApiError('token_invalid', 401)
        member = token.member
        ensure_can_login(member)
        token.revoked_at = timezone.now()
        token.save(update_fields=['revoked_at'])
        return issue_tokens(member, device_id or token.device_id, family=token.family)


def revoke_refresh(value):
    MemberRefreshToken.objects.filter(token_hash=hash_token(value or ''), revoked_at__isnull=True) \
        .update(revoked_at=timezone.now())


def revoke_all(member):
    MemberRefreshToken.objects.filter(member=member, revoked_at__isnull=True).update(revoked_at=timezone.now())


def ensure_can_login(member):
    if member.status == MemberStatus.BLOCKED:
        raise ApiError('account_blocked', 403)
    if member.status != MemberStatus.ACTIVE:
        raise ApiError('account_deactivated', 403)


# ---------------------------------------------------------------- подписанные токены

def make_registration_token(phone, device_id=None, social=None):
    data = {'phone': phone, 'device': device_id or ''}
    if social:
        data['social'] = social
    return signing.dumps(data, salt=REGISTRATION_SALT)


def read_registration_token(token):
    try:
        return signing.loads(token or '', salt=REGISTRATION_SALT, max_age=REGISTRATION_TTL)
    except signing.BadSignature:
        raise ApiError('registration_expired', 400)


def make_social_token(social):
    """Вход через Google/Apple без привязанного номера: держит провайдера и sub до подтверждения номера."""
    return signing.dumps(social, salt=SOCIAL_SALT)


def read_social_token(token):
    try:
        return signing.loads(token or '', salt=SOCIAL_SALT, max_age=REGISTRATION_TTL)
    except signing.BadSignature:
        raise ApiError('registration_expired', 400)


def make_restore_token(member):
    return signing.dumps({'m': member.pk}, salt=RESTORE_SALT)


def read_restore_token(token):
    try:
        data = signing.loads(token or '', salt=RESTORE_SALT, max_age=REGISTRATION_TTL)
    except signing.BadSignature:
        raise ApiError('restore_expired', 400)
    member = Member.objects.filter(pk=data['m']).first()
    if member is None or member.status != MemberStatus.DEACTIVATED:
        raise ApiError('restore_expired', 400)
    return member


def make_member_qr(member):
    ttl = ProgramSettings.get().member_qr_ttl_seconds
    token = signing.dumps({'m': member.pk, 'n': secrets.token_hex(4)}, salt=MEMBER_QR_SALT, compress=True)
    return token, timezone.now() + timedelta(seconds=ttl)


def read_member_qr(token):
    ttl = ProgramSettings.get().member_qr_ttl_seconds
    try:
        data = signing.loads(token or '', salt=MEMBER_QR_SALT, max_age=ttl)
    except signing.BadSignature:
        raise ApiError('qr_invalid', 400)
    member = Member.objects.filter(pk=data['m']).first()
    if member is None or member.status == MemberStatus.PURGED:
        raise ApiError('qr_invalid', 400)
    return member


# ---------------------------------------------------------------- DRF

class MemberAuthentication(BaseAuthentication):
    """Authorization: Bearer <access_token> клиента."""

    def authenticate(self, request):
        token = bearer_token(request)
        if not token:
            return None
        payload = decode_access(token, 'member')
        if payload is None:
            raise ApiError('token_invalid', 401)
        member = Member.objects.filter(pk=payload['sub']).first()
        if member is None:
            raise ApiError('token_invalid', 401)
        if member.status == MemberStatus.BLOCKED:
            raise ApiError('account_blocked', 403)
        if member.status != MemberStatus.ACTIVE:
            raise ApiError('token_invalid', 401)
        return member, payload

    def authenticate_header(self, request):
        return 'Bearer'


class OptionalMemberAuthentication(MemberAuthentication):
    """Публичные эндпоинты: токен не обязателен, битый токен игнорируется."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except ApiError:
            return None
