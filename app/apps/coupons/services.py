import logging
import secrets
from datetime import timedelta

from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.common.i18n import iso, tr
from apps.common.models import ProgramSettings

from .models import Coupon, CouponGrant, CouponKind, CouponStatus, WelcomeOffer

log = logging.getLogger(__name__)

QR_SALT = 'baytur.coupon-qr'


# ---------------------------------------------------------------- выдача

def issue_welcome_coupon(member):
    """
    Подарок за первую регистрацию: если включён в админке — купон с условиями на момент выдачи.
    Один раз на номер навсегда. → Coupon | None.
    """
    from apps.loyalty.services import welcome_phone_hash
    offer = WelcomeOffer.get()
    if not offer.enabled or not member.phone or not (offer.title or {}).get('ru'):
        return None
    now = timezone.now()
    try:
        with transaction.atomic():
            CouponGrant.objects.create(phone_hash=welcome_phone_hash(member.phone), member=member)
            coupon = Coupon.objects.create(
                member=member, source='welcome', kind=offer.kind, value=offer.value, title=offer.title,
                description=offer.description, terms=offer.terms, issued_at=now,
                expires_at=now + timedelta(days=offer.valid_days) if offer.valid_days else None)
    except IntegrityError:
        return None  # номер уже получал подарок
    transaction.on_commit(lambda: _notify_issued(coupon))
    return coupon


def _notify_issued(coupon):
    from apps.notifications.services import notify
    m = coupon.member
    titles = {'ru': 'Подарок за регистрацию', 'ky': 'Каттоо үчүн белек', 'en': 'Welcome gift'}
    notify(m, 'coupon.issued', tr(titles, m.language), tr(coupon.title, m.language) or '',
           {'couponId': coupon.pk}, push=True)


# ---------------------------------------------------------------- представление

def value_text(coupon, lang=None):
    if coupon.kind == CouponKind.PERCENT:
        return f'−{coupon.value}%'
    if coupon.kind == CouponKind.AMOUNT:
        return f'−{coupon.value:,} сом'.replace(',', ' ')
    return tr({'ru': 'Подарок', 'ky': 'Белек', 'en': 'Gift'}, lang)


def status_of(coupon):
    """Истёкший по дате купон показываем как expired, даже если фоновая задача ещё не отметила."""
    if coupon.status == CouponStatus.ACTIVE and coupon.expires_at and coupon.expires_at <= timezone.now():
        return CouponStatus.EXPIRED
    return coupon.status


def coupon_payload(coupon, lang=None):
    return {
        'id': coupon.pk,
        'source': coupon.source,
        'kind': coupon.kind,
        'value': coupon.value,
        'valueText': value_text(coupon, lang),
        'title': tr(coupon.title, lang),
        'description': tr(coupon.description, lang) or None,
        'terms': tr(coupon.terms, lang) or None,
        'status': status_of(coupon),
        'issuedAt': iso(coupon.issued_at),
        'expiresAt': iso(coupon.expires_at),
        'redeemedAt': iso(coupon.redeemed_at),
    }


def staff_coupon_payload(coupon):
    from apps.cashback.serializers import mask_phone
    m = coupon.member
    return {**coupon_payload(coupon, 'ru'),
            'member': {'memberId': m.member_id, 'name': m.full_name, 'phone': mask_phone(m.phone)},
            'redeemedBy': coupon.redeemed_by.full_name if coupon.redeemed_by_id else None,
            'note': coupon.note or None}


# ---------------------------------------------------------------- QR

def make_qr(coupon):
    """Подписанный токен, живёт как QR участника (~90 с): скриншот чужого купона не сработает."""
    ttl = ProgramSettings.get().member_qr_ttl_seconds
    token = signing.dumps({'c': coupon.pk, 'n': secrets.token_hex(4)}, salt=QR_SALT, compress=True)
    return token, timezone.now() + timedelta(seconds=ttl)


def read_qr(token):
    ttl = ProgramSettings.get().member_qr_ttl_seconds
    try:
        data = signing.loads(token or '', salt=QR_SALT, max_age=ttl)
    except signing.BadSignature:
        raise ApiError('qr_invalid', 400, message='QR купона недействителен или устарел — попросите обновить')
    coupon = Coupon.objects.select_related('member', 'redeemed_by').filter(pk=data.get('c')).first()
    if coupon is None:
        raise ApiError('qr_invalid', 400)
    return coupon


def is_coupon_token(token):
    try:
        signing.loads(token or '', salt=QR_SALT)
        return True
    except signing.BadSignature:
        return False


# ---------------------------------------------------------------- гашение

def active_coupons(member):
    """Неиспользованные купоны клиента — кассир видит их сразу после скана QR участника."""
    now = timezone.now()
    from django.db.models import Q
    return list(member.coupons.filter(status=CouponStatus.ACTIVE)
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).order_by('issued_at'))


def redeem(request, token, note=''):
    """Кассир гасит купон по QR купона. Повторно погасить нельзя; свой купон — нельзя."""
    return _redeem(request, read_qr(token), note)


def redeem_for_member(request, pay_token, coupon_id, note=''):
    """Кассир гасит купон, выбрав его после скана QR участника (payToken из /staff/scan)."""
    from apps.cashback.desk import read_pay_token
    member = read_pay_token(request.user, pay_token)
    coupon = member.coupons.filter(pk=coupon_id).first()
    if coupon is None:
        raise ApiError('not_found', 404)
    return _redeem(request, coupon, note)


def _redeem(request, coupon, note=''):
    from apps.cashback.desk import check_not_own_member
    user = request.user
    check_not_own_member(user, coupon.member)
    with transaction.atomic():
        c = Coupon.objects.select_for_update().get(pk=coupon.pk)
        status = status_of(c)
        if status != CouponStatus.ACTIVE:
            raise ApiError('invalid_status', 409, message={
                CouponStatus.REDEEMED: 'Купон уже использован',
                CouponStatus.EXPIRED: 'Срок купона истёк',
                CouponStatus.CANCELLED: 'Купон отменён'}.get(status, 'Купон недоступен'), extra={'status': status})
        c.status = CouponStatus.REDEEMED
        c.redeemed_at = timezone.now()
        c.redeemed_by = user
        c.note = (note or '').strip()[:300]
        c.save(update_fields=['status', 'redeemed_at', 'redeemed_by', 'note'])
    audit(request, 'coupon.redeem', c, after={'member': c.member.member_id, 'title': c.title.get('ru')},
          comment=c.note)
    from apps.common.realtime import publish_member
    publish_member(c.member_id, 'coupon.updated', coupon_payload(c, c.member.language))
    return c


def expire_coupons(now=None):
    now = now or timezone.now()
    return Coupon.objects.filter(status=CouponStatus.ACTIVE, expires_at__lte=now).update(status=CouponStatus.EXPIRED)
