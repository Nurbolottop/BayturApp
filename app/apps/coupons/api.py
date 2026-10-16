"""Купоны: клиентский API (/me/coupons) и гашение на кассе (/staff/coupons/*)."""
from rest_framework import serializers
from rest_framework.response import Response

from apps.cashback.staff_api import StaffAPIView
from apps.common.errors import ApiError
from apps.common.i18n import iso
from apps.common.pagination import paginate
from apps.common.views import MemberAPIView

from . import services


class MyCouponsView(MemberAPIView):
    """Мои купоны, новые сверху."""

    def get(self, request):
        return Response(paginate(request, request.user.coupons.all(),
                                 lambda rows: [services.coupon_payload(c) for c in rows], time_field='issued_at'))


class MyCouponQrView(MemberAPIView):
    """QR купона для кассира (живёт ~90 с, обновлять перед истечением)."""

    def get(self, request, coupon_id):
        coupon = request.user.coupons.filter(pk=coupon_id).first()
        if coupon is None:
            raise ApiError('not_found', 404)
        if services.status_of(coupon) != 'active':
            raise ApiError('invalid_status', 409, extra={'status': services.status_of(coupon)})
        token, expires = services.make_qr(coupon)
        return Response({'token': token, 'expiresAt': iso(expires)})


class TokenInput(serializers.Serializer):
    token = serializers.CharField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)


class StaffCouponScanView(StaffAPIView):
    """QR купона → что за купон и можно ли погасить."""

    def post(self, request):
        s = TokenInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(services.staff_coupon_payload(services.read_qr(s.validated_data['token'])))


class StaffCouponRedeemView(StaffAPIView):
    """Погасить купон (один раз)."""

    def post(self, request):
        s = TokenInput(data=request.data)
        s.is_valid(raise_exception=True)
        coupon = services.redeem(request, s.validated_data['token'], s.validated_data.get('note'))
        return Response(services.staff_coupon_payload(coupon))
