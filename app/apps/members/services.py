import logging
import re
from datetime import date, timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from apps.common.errors import ApiError
from apps.common.i18n import iso, tr
from apps.common.models import ProgramSettings

from . import auth
from .models import (Consent, ConsentKind, Device, LegalDocument, LegalKind, Member, MemberRefreshToken, MemberStatus,
                     OtpPurpose, SocialAccount, SocialProvider)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- профиль

def pending_consents(member):
    result = []
    for kind in (LegalKind.TERMS, LegalKind.PRIVACY):
        doc = LegalDocument.current(kind)
        if doc and doc.requires_acceptance and not Consent.objects.filter(
                member=member, kind=kind, version=doc.version, granted=True).exists():
            result.append({'kind': kind, 'version': doc.version, 'url': tr(doc.url)})
    return result


def profile_payload(member):
    return {
        'firstName': member.first_name,
        'lastName': member.last_name,
        'phone': member.phone,
        'email': member.email or None,
        'birthday': member.birthday.isoformat() if member.birthday else None,
        'avatar': member.avatar.url if member.avatar_id else None,
        'memberId': member.member_id,
        'memberSince': member.member_since.isoformat(),
        'settings': {
            'language': member.language,
            'notifyCashback': member.notify_cashback,
            'notifyPromos': member.notify_promos,
        },
        'marketingConsent': member.marketing_consent,
        'pendingConsents': pending_consents(member),
        'socialAccounts': sorted(member.social_accounts.values_list('provider', flat=True)),
        'hasPin': bool(member.pin_hash),
    }


def _validate_name(value, field):
    value = (value or '').strip()
    if not 1 <= len(value) <= 50:
        raise ApiError('validation_error', 400, extra={'fields': {field: ['1–50 символов']}})
    return value


def _validate_email(value):
    value = (value or '').strip()
    if not value:
        return ''
    try:
        validate_email(value)
    except DjangoValidationError:
        raise ApiError('validation_error', 400, extra={'fields': {'email': ['неверный формат']}})
    return value.lower()


def _parse_birthday(value, required):
    if value in (None, ''):
        if required:
            raise ApiError('validation_error', 400, extra={'fields': {'birthday': ['обязательно']}})
        return None
    try:
        bd = date.fromisoformat(str(value))
    except ValueError:
        raise ApiError('validation_error', 400, extra={'fields': {'birthday': ['формат YYYY-MM-DD']}})
    today = timezone.localdate()
    age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    if age < ProgramSettings.get().min_age:
        raise ApiError('age_restricted', 422)
    if age > 120:
        raise ApiError('validation_error', 400, extra={'fields': {'birthday': ['неверная дата']}})
    return bd


def update_profile(member, data):
    fields = []
    if 'firstName' in data:
        member.first_name = _validate_name(data['firstName'], 'firstName')
        fields.append('first_name')
    if 'lastName' in data:
        member.last_name = _validate_name(data['lastName'], 'lastName')
        fields.append('last_name')
    if 'email' in data:
        member.email = _validate_email(data['email'])
        fields.append('email')
    if 'birthday' in data:
        new = _parse_birthday(data['birthday'], required=False)
        if member.birthday and new != member.birthday:
            # клиент ставит ДР один раз, дальше меняет только админ (иначе меняли бы ради кешбека ×2)
            raise ApiError('birthday_locked', 403)
        if new and not member.birthday:
            member.birthday = new
            fields.append('birthday')
    if fields:
        member.save(update_fields=fields + ['updated_at'])
    return member


def update_settings(member, data, ip=None):
    fields = []
    if 'language' in data:
        if data['language'] not in ('ru', 'ky', 'en'):
            raise ApiError('validation_error', 400, extra={'fields': {'language': ['ru | ky | en']}})
        member.language = data['language']
        fields.append('language')
    if 'notifyCashback' in data:
        member.notify_cashback = bool(data['notifyCashback'])
        fields.append('notify_cashback')
    if 'notifyPromos' in data:
        member.notify_promos = bool(data['notifyPromos'])
        fields.append('notify_promos')
        if member.notify_promos != member.marketing_consent:
            # включение рекламных push = явное согласие на рекламу; выключение — отзыв
            member.marketing_consent = member.notify_promos
            fields.append('marketing_consent')
            Consent.objects.create(member=member, kind=ConsentKind.MARKETING, granted=member.marketing_consent, ip=ip)
    if fields:
        member.save(update_fields=fields + ['updated_at'])
    return member


def accept_consent(member, kind, version, ip=None):
    doc = LegalDocument.objects.filter(kind=kind, version=version, published_at__isnull=False).first()
    if doc is None:
        raise ApiError('consent_unknown', 404)
    Consent.objects.get_or_create(member=member, kind=kind, version=version, granted=True, defaults={'ip': ip})


def legal_payload():
    docs = {}
    for kind in LegalKind.values:
        doc = LegalDocument.current(kind)
        docs[kind] = {'version': doc.version, 'url': tr(doc.url)} if doc else None
    return docs


# ---------------------------------------------------------------- аватар

AVATAR_MAX_SIZE = 10 * 1024 * 1024


def set_avatar(member, uploaded_file):
    """Необязательный аватар: JPEG/PNG/WebP/HEIC до 10 МБ → квадрат 512×512 без EXIF."""
    from apps.common.media import process_avatar
    from apps.common.models import Upload
    if uploaded_file is None or uploaded_file.size > AVATAR_MAX_SIZE:
        raise ApiError('file_invalid', 422)
    content = process_avatar(uploaded_file)
    if content is None:
        raise ApiError('file_invalid', 422)
    upload = Upload(kind=Upload.KIND_AVATAR, member=member, width=512, height=512)
    upload.file.save(f'{upload.id}.jpg', content, save=False)
    upload.save()
    old = member.avatar
    member.avatar = upload
    member.save(update_fields=['avatar', 'updated_at'])
    if old is not None:
        old.file.delete(save=False)
        old.delete()
    return member


def remove_avatar(member):
    old = member.avatar
    if old is None:
        return member
    member.avatar = None
    member.save(update_fields=['avatar', 'updated_at'])
    old.file.delete(save=False)
    old.delete()
    return member


def _flag(value):
    """Булево из JSON или multipart («true» / «1» / «on»)."""
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'on', 'yes')
    return value is True


# ---------------------------------------------------------------- вход

def link_device(member, device_id):
    if not device_id:
        return
    from apps.analytics.models import DeviceLink
    DeviceLink.objects.update_or_create(device_id=device_id, defaults={'member': member})
    if not member.first_device_id:
        Member.objects.filter(pk=member.pk).update(first_device_id=device_id)


def login_result(member, device_id=None):
    """Ответ входа для существующего участника: токены, блок или предложение восстановить."""
    if member.status == MemberStatus.BLOCKED:
        raise ApiError('account_blocked', 403)
    if member.status == MemberStatus.DEACTIVATED:
        from apps.loyalty.services import get_wallet
        return {
            'deactivated': True,
            'restoreToken': auth.make_restore_token(member),
            'purgeAt': iso(member.purge_at) if member.purge_at else None,
            'balance': get_wallet(member).balance,
        }
    link_device(member, device_id)
    return auth.issue_tokens(member, device_id)


def verify(phone, code, device_id=None, social_token=None):
    social = auth.read_social_token(social_token) if social_token else None
    phone = auth.check_otp(phone, code)
    member = Member.objects.filter(phone=phone).exclude(status=MemberStatus.PURGED).first()
    if member is None:
        return {'isNew': True, 'registrationToken': auth.make_registration_token(phone, device_id, social)}
    if social and member.status != MemberStatus.BLOCKED:
        link_social(member, social)
    return login_result(member, device_id)


# ---------------------------------------------------------------- PIN: вход по номеру без SMS

PIN_RE = re.compile(r'^\d{6}$')
_DUMMY_PIN_HASH = None


def validate_pin(pin):
    """6 цифр; отклоняются 000000/111111 и подряд идущие 123456/654321."""
    pin = str(pin or '').strip()
    if not PIN_RE.match(pin):
        raise ApiError('pin_format', 400)
    if len(set(pin)) == 1 or pin in '0123456789' or pin in '9876543210':
        raise ApiError('pin_weak', 422)
    return pin


def set_pin(member, pin):
    member.pin_hash = make_password(validate_pin(pin))
    member.pin_set_at = timezone.now()
    member.save(update_fields=['pin_hash', 'pin_set_at', 'updated_at'])


def pin_login(phone, pin, device_id=None):
    """Номер + PIN. Ограничения на число ошибок нет (решение заказчика) — только rate limit по IP."""
    global _DUMMY_PIN_HASH
    phone = auth.normalize_phone(phone)
    member = Member.objects.filter(phone=phone).exclude(status=MemberStatus.PURGED).first()
    if member is not None and not member.pin_hash:
        raise ApiError('pin_not_set', 400)
    if member is None:
        # то же время ответа, что и при неверном PIN: по скорости не узнать, зарегистрирован ли номер
        _DUMMY_PIN_HASH = _DUMMY_PIN_HASH or make_password('000000')
        check_password(str(pin or ''), _DUMMY_PIN_HASH)
        raise ApiError('pin_invalid', 400)
    if not check_password(str(pin or ''), member.pin_hash):
        raise ApiError('pin_invalid', 400)
    return login_result(member, device_id)


def pin_reset(phone, code, pin, device_id=None):
    """«Забыл PIN»: SMS-код (из /auth/otp/request) + новый PIN. Остальные сессии завершаются."""
    pin = validate_pin(pin)  # до проверки кода — чтобы не сжечь код из-за слабого PIN
    phone = auth.check_otp(phone, code)
    member = Member.objects.filter(phone=phone).exclude(status=MemberStatus.PURGED).first()
    if member is None:
        return {'isNew': True, 'registrationToken': auth.make_registration_token(phone, device_id)}
    if member.status == MemberStatus.BLOCKED:
        raise ApiError('account_blocked', 403)
    set_pin(member, pin)
    auth.revoke_all(member)
    return login_result(member, device_id)


def change_pin(member, pin, current_pin=None):
    """Задать PIN (если не задан) или сменить — со старым PIN. Забыл старый → /auth/pin/reset."""
    if member.pin_hash and not check_password(str(current_pin or ''), member.pin_hash):
        raise ApiError('pin_invalid', 400)
    set_pin(member, pin)
    return profile_payload(member)


# ---------------------------------------------------------------- Google / Apple ID

APPLE_PENDING_TTL = 3600  # refresh-токен Apple ждёт подтверждения номера и регистрации


def _apple_pending_key(subject):
    return f'social:apple-rt:{subject}'


def _store_apple_token(provider, identity, authorization_code):
    """Обмен authorizationCode → refresh-токен Apple: у привязанного аккаунта — сразу, иначе — до привязки."""
    from django.core.cache import cache
    from . import social
    if provider != SocialProvider.APPLE or not authorization_code:
        return
    refresh = social.apple_exchange_code(authorization_code, identity['audience'])
    if not refresh:
        return
    updated = SocialAccount.objects.filter(provider=provider, subject=identity['subject']).exclude(
        member__status=MemberStatus.PURGED)
    old = list(updated.exclude(refresh_token='').exclude(refresh_token=refresh)
               .values_list('client_id', 'refresh_token'))
    if updated.update(client_id=identity['audience'], refresh_token=refresh):
        _enqueue_revoke(old)
    else:
        cache.set(_apple_pending_key(identity['subject']), [identity['audience'], refresh], APPLE_PENDING_TTL)


def _enqueue_revoke(tokens):
    from .tasks import revoke_apple_token
    for client_id, refresh in tokens:
        transaction.on_commit(lambda c=client_id, r=refresh: revoke_apple_token.delay(c, r))


def revoke_social(accounts):
    """Отозвать доступ у Apple (App Store 5.1.1(v)) и забыть токены. Привязка остаётся — её удаляет вызывающий."""
    accounts = accounts.filter(provider=SocialProvider.APPLE).exclude(refresh_token='')
    _enqueue_revoke(list(accounts.values_list('client_id', 'refresh_token')))
    accounts.update(refresh_token='')


def link_social(member, social):
    """Привязка (или перепривязка) аккаунта провайдера. Номер уже подтверждён — владелец доказан."""
    from django.core.cache import cache
    defaults = {'member': member, 'email': social.get('email') or ''}
    if social['provider'] == SocialProvider.APPLE:
        pending = cache.get(_apple_pending_key(social['subject']))
        if pending:
            defaults.update(client_id=pending[0], refresh_token=pending[1])
    with transaction.atomic():
        replaced = SocialAccount.objects.filter(member=member, provider=social['provider']).exclude(
            subject=social['subject'])
        revoke_social(replaced)
        replaced.delete()
        SocialAccount.objects.update_or_create(provider=social['provider'], subject=social['subject'],
                                               defaults=defaults)
    if social['provider'] == SocialProvider.APPLE:
        cache.delete(_apple_pending_key(social['subject']))


def social_login(provider, token, device_id=None, nonce=None, first_name='', last_name='',
                 authorization_code=None):
    """
    Аккаунт провайдера привязан → обычный ответ входа. Иначе номер всё равно нужен (по нему находят
    участника на точках и подтверждают удаление): needPhone + socialToken для /auth/otp/verify.
    """
    from . import social
    identity = social.verify_token(provider, token, nonce)
    _store_apple_token(provider, identity, authorization_code)
    account = SocialAccount.objects.select_related('member').filter(
        provider=provider, subject=identity['subject']).first()
    if account is not None and account.member.status != MemberStatus.PURGED:
        SocialAccount.objects.filter(pk=account.pk).update(last_login_at=timezone.now())
        return login_result(account.member, device_id)
    payload = {'provider': provider, 'subject': identity['subject'], 'email': identity['email']}
    return {
        'needPhone': True,
        'socialToken': auth.make_social_token(payload),
        # Apple отдаёт имя только приложению и только при первом входе — приложение передаёт его сюда
        'prefill': {'firstName': (first_name or '').strip()[:50] or None,
                    'lastName': (last_name or '').strip()[:50] or None,
                    'email': identity['email'] or None},
    }


def social_link(member, provider, token, nonce=None, authorization_code=None):
    from . import social
    identity = social.verify_token(provider, token, nonce)
    other = SocialAccount.objects.filter(provider=provider, subject=identity['subject']).exclude(member=member)
    if other.exclude(member__status=MemberStatus.PURGED).exists():
        raise ApiError('social_taken', 409)
    _store_apple_token(provider, identity, authorization_code)
    link_social(member, {'provider': provider, 'subject': identity['subject'], 'email': identity['email']})
    return profile_payload(member)


def social_unlink(member, provider):
    with transaction.atomic():
        accounts = SocialAccount.objects.filter(member=member, provider=provider)
        revoke_social(accounts)
        accounts.delete()


def register(data, device_id=None, ip=None, avatar_file=None):
    token = auth.read_registration_token(data.get('registrationToken'))
    phone = token['phone']
    if not _flag(data.get('acceptTerms')):
        raise ApiError('terms_required', 422)
    first = _validate_name(data.get('firstName'), 'firstName')
    last = _validate_name(data.get('lastName'), 'lastName')
    email = _validate_email(data.get('email'))
    birthday = _parse_birthday(data.get('birthday'), required=True)
    marketing = _flag(data.get('marketingConsent'))
    pin = validate_pin(data.get('pin')) if data.get('pin') not in (None, '') else None
    ps = ProgramSettings.get()
    if avatar_file is not None and avatar_file.size > AVATAR_MAX_SIZE:
        raise ApiError('file_invalid', 422)

    with transaction.atomic():
        existing = Member.objects.select_for_update().filter(phone=phone).exclude(
            status=MemberStatus.PURGED).first()
        if existing is not None:
            # двойная отправка формы: номер уже зарегистрирован
            auth.ensure_can_login(existing)
            member = existing
        else:
            member = Member.objects.create(
                phone=phone, first_name=first, last_name=last, email=email, birthday=birthday,
                marketing_consent=marketing, notify_promos=marketing,
                gender=(data.get('gender') or '')[:10],
                language=data.get('language') if data.get('language') in ('ru', 'ky', 'en') else 'ru',
                is_test=bool(ps.test_enabled and ps.test_phone == phone),
                first_device_id=device_id or token.get('device') or '')
            from apps.loyalty.services import get_wallet
            get_wallet(member)
            for kind in (LegalKind.TERMS, LegalKind.PRIVACY):
                doc = LegalDocument.current(kind)
                Consent.objects.create(member=member, kind=kind, version=doc.version if doc else '', ip=ip)
            Consent.objects.create(member=member, kind=ConsentKind.MARKETING, granted=marketing, ip=ip)
    if token.get('social') and member.status != MemberStatus.BLOCKED:
        link_social(member, token['social'])
    if pin and not member.pin_hash:
        set_pin(member, pin)
    if avatar_file is not None and member.avatar_id is None:
        set_avatar(member, avatar_file)
    link_device(member, device_id or token.get('device'))
    return {**auth.issue_tokens(member, device_id), 'profile': profile_payload(member)}


def logout(member, refresh_token=None, push_token=None):
    if refresh_token:
        auth.revoke_refresh(refresh_token)
    if push_token:
        Device.objects.filter(member=member, token=push_token).delete()


# ---------------------------------------------------------------- удаление аккаунта (§2.5)

def active_obligations(member):
    """Незавершённые брони и заявки в работе — сохраняются после удаления."""
    from apps.cashback.models import ACTIVE_STATUSES
    return list(member.cashback_requests.filter(status__in=ACTIVE_STATUSES).select_related('item'))


def deletion_info(member):
    from apps.loyalty.services import get_wallet
    wallet = get_wallet(member)
    ps = ProgramSettings.get()
    return {
        'balance': wallet.balance,
        'tier': wallet.tier_id,
        'purgeDays': ps.purge_days,
        'purgeAt': iso((timezone.now() + timedelta(days=ps.purge_days))),
        'keeps': [{'requestId': r.pk, 'itemId': r.item_id, 'category': r.item_snapshot.get('category'),
                   'title': tr(r.item_snapshot.get('title')), 'status': r.status} for r in active_obligations(member)],
    }


def deletion_request(member, ip=None, device_id=None):
    otp = auth.request_otp(member.phone, OtpPurpose.DELETION, ip=ip, device_id=device_id)
    return {**otp, **deletion_info(member)}


def deactivate(member, actor=None, immediately=False):
    """Для клиента аккаунт удалён сразу; на беке — деактивация на purge_days с возможностью восстановления."""
    ps = ProgramSettings.get()
    now = timezone.now()
    with transaction.atomic():
        member = Member.objects.select_for_update().get(pk=member.pk)
        member.status = MemberStatus.DEACTIVATED
        member.deleted_at = now
        member.purge_at = now if immediately else now + timedelta(days=ps.purge_days)
        member.purge_immediately = immediately
        member.save()
        auth.revoke_all(member)
        member.devices.all().delete()
    return member


def deletion_confirm(member, code):
    auth.check_otp(member.phone, code, OtpPurpose.DELETION)
    deactivate(member)
    # Apple требует отзыва при удалении; привязка остаётся до стирания — при восстановлении вход через Apple
    # снова запросит согласие, sub не меняется
    revoke_social(member.social_accounts.all())
    return {'deleted': True}


def restore(member):
    with transaction.atomic():
        member = Member.objects.select_for_update().get(pk=member.pk)
        if member.status != MemberStatus.DEACTIVATED:
            raise ApiError('restore_expired', 400)
        member.status = MemberStatus.ACTIVE
        member.deleted_at = None
        member.purge_at = None
        member.purge_immediately = False
        member.restored_at = timezone.now()
        member.save()
    return member


def restore_with_token(token, device_id=None):
    member = restore(auth.read_restore_token(token))
    link_device(member, device_id)
    return {**auth.issue_tokens(member, device_id), 'profile': profile_payload(member)}


def start_over(token, device_id=None):
    """«Начать заново»: старый аккаунт стирается сразу, дальше обычная регистрация."""
    member = auth.read_restore_token(token)
    phone = member.phone
    purge(member)
    return {'isNew': True, 'registrationToken': auth.make_registration_token(phone, device_id)}


def purge(member):
    """
    Окончательное удаление: ПДн, устройства, фото и тексты обращений удаляются; остаток баллов —
    операция forfeit; заявки, операции и платежи остаются обезличенными; номер освобождается.
    """
    from apps.analytics.models import AppEvent, DeviceLink
    from apps.loyalty.models import OperationKind
    from apps.loyalty.services import lock_wallet, post_operation

    with transaction.atomic():
        member = Member.objects.select_for_update().get(pk=member.pk)
        if member.status == MemberStatus.PURGED:
            return member
        wallet = lock_wallet(member)
        left = wallet.balance - wallet.reserved
        if left > 0:
            post_operation(wallet, OperationKind.FORFEIT, -left, activity=False, reason='Аккаунт удалён')
        member.first_name = ''
        member.last_name = ''
        member.phone = None
        member.email = ''
        member.birthday = None
        member.gender = ''
        member.blocked_reason = ''
        member.status = MemberStatus.PURGED
        member.purged_at = timezone.now()
        member.marketing_consent = False
        member.notify_promos = False
        member.first_device_id = ''
        member.pin_hash = ''
        member.pin_set_at = None
        member.avatar = None
        member.save()
        member.devices.all().delete()
        revoke_social(member.social_accounts.all())
        member.social_accounts.all().delete()
        MemberRefreshToken.objects.filter(member=member).delete()
        member.notifications.all().delete()
        Consent.objects.filter(member=member).update(ip=None)
        # обращения: тексты и фото удаляются, статистика остаётся
        for complaint in member.complaints.all():
            for msg in complaint.messages.all():
                for upload in msg.attachments.all():
                    upload.file.delete(save=False)
                    upload.delete()
                msg.text = ''
                msg.save(update_fields=['text'])
            complaint.rating_comment = ''
            complaint.save(update_fields=['rating_comment'])
        for upload in member.uploads.all():
            upload.file.delete(save=False)
            upload.delete()
        # связь событий аналитики с участником разрывается
        AppEvent.objects.filter(member=member).update(member=None)
        DeviceLink.objects.filter(member=member).update(member=None)
    return member


def purge_due_members(now=None):
    """Раз в сутки. Незавершённая бронь/заявка откладывает удаление до её завершения."""
    now = now or timezone.now()
    purged = postponed = 0
    for member in Member.objects.filter(status=MemberStatus.DEACTIVATED, purge_at__lte=now):
        if active_obligations(member) and not member.purge_immediately:
            Member.objects.filter(pk=member.pk).update(purge_at=now + timedelta(days=1))
            postponed += 1
            continue
        purge(member)
        purged += 1
    return {'purged': purged, 'postponed': postponed}
