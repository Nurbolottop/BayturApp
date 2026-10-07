"""
Рабочее место сотрудника (ТЗ §8.5). Логика и ограничения §8.3 — в apps.cashback.desk
(та же реализация используется админ-API и веб-панелью).
"""
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import audit
from apps.common.i18n import iso
from apps.common.models import ProgramSettings
from apps.members.auth import read_member_qr
from apps.members.models import MemberStatus
from apps.staff.auth import HasPerm, StaffAuthentication

from . import desk
from .desk import get_scoped, scoped_requests
from .models import CashbackRequest
from .serializers import mask_phone, staff_request_payload


class StaffAPIView(APIView):
    authentication_classes = [StaffAuthentication]
    permission_classes = [HasPerm]
    required_perms = 'requests.process'


def payload(req):
    return staff_request_payload(CashbackRequest.objects.select_related('member', 'payment').get(pk=req.pk))


def result(req, escalated):
    """202 — действие ушло на подтверждение менеджеру."""
    return Response(payload(req), status=202 if escalated else 200)


class QueueView(StaffAPIView):
    """Заявки pending своих точек, старые сверху."""

    def get(self, request):
        items = [staff_request_payload(r) for r in desk.queue(request.user, request.query_params.get('outlet'))[:200]]
        return Response({'items': items, 'count': len(items)})


class StaffRequestView(StaffAPIView):
    def get(self, request, request_id):
        return Response(staff_request_payload(get_scoped(request.user, request_id)))


class ConfirmView(StaffAPIView):
    def post(self, request, request_id):
        return result(*desk.confirm(request, request_id, bool(request.data.get('cashReceived'))))


class AdjustInput(serializers.Serializer):
    total = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class AdjustPreviewView(StaffAPIView):
    """Новый расчёт без сохранения — сотрудник видит цифры до подтверждения правки."""

    def post(self, request, request_id):
        s = AdjustInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(desk.adjust_preview(request, request_id, s.validated_data['total']))


class AdjustView(StaffAPIView):
    def post(self, request, request_id):
        s = AdjustInput(data=request.data)
        s.is_valid(raise_exception=True)
        return result(*desk.adjust(request, request_id, s.validated_data['total'], s.validated_data.get('reason')))


class RejectInput(serializers.Serializer):
    reasonCode = serializers.ChoiceField(choices=desk.STAFF_REJECT_REASONS)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True)


class RejectView(StaffAPIView):
    def post(self, request, request_id):
        s = RejectInput(data=request.data)
        s.is_valid(raise_exception=True)
        req = desk.reject(request, request_id, s.validated_data['reasonCode'], s.validated_data.get('comment'))
        return Response(payload(req))


def member_brief(member, user):
    """Клиент для сотрудника: уровень, баланс баллов и заявки в его точках (без истории операций)."""
    from apps.loyalty.services import get_wallet
    reqs = scoped_requests(user).filter(member=member).order_by('-created_at')[:20]
    wallet = get_wallet(member)
    return {
        'id': member.pk,
        'memberId': member.member_id,
        'name': member.full_name,
        'phone': mask_phone(member.phone),
        'tier': wallet.tier_id,
        'status': member.status,
        # сколько баллов клиент может потратить сейчас (без зарезервированных под заявки); 1 балл = 1 тыйын
        'points': wallet.available,
        'pointsSom': max(0, wallet.available) // ProgramSettings.get().points_per_som,
        'deletedNote': iso(member.purge_at) if member.status == MemberStatus.DEACTIVATED else None,
        'requests': [staff_request_payload(r) for r in reqs],
    }


class MemberSearchView(StaffAPIView):
    required_perms = 'members.view'

    def get(self, request):
        return Response({'items': [member_brief(m, request.user)
                                   for m in desk.search_members(request.query_params.get('q'))]})


class ScanView(StaffAPIView):
    """QR участника → клиент (токен живёт 1–2 мин)."""

    required_perms = 'members.view'

    def post(self, request):
        member = read_member_qr(request.data.get('token'))
        audit(request, 'member.scan', member)
        # payToken — разрешение на оплату баллами этого клиента в течение 10 минут после скана
        return Response({**member_brief(member, request.user), 'payToken': desk.make_pay_token(request.user, member)})


class ShiftView(StaffAPIView):
    """Итог смены: подтверждено / отклонено сегодня, наличные для сверки кассы."""

    def get(self, request):
        s = desk.shift(request.user)
        return Response({
            'date': s['date'].isoformat(),
            'confirmed': [staff_request_payload(r) for r in s['confirmed']],
            'rejected': [staff_request_payload(r) for r in s['rejected']],
            'adjustedCount': s['adjusted_count'],
            'cashTotal': s['cash_total'],
        })


# ---------------------------------------------------------------- оплата баллами по QR клиента

class PayInput(serializers.Serializer):
    payToken = serializers.CharField()
    itemId = serializers.CharField(max_length=60)
    quantity = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    checkAmount = serializers.IntegerField(required=False, allow_null=True, min_value=1)


def _pay_input(request):
    s = PayInput(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


class PayItemsView(StaffAPIView):
    """Услуги точек сотрудника для оплаты баллами."""

    def get(self, request):
        from apps.catalog.serializers import pricing_payload
        from apps.common.i18n import tr
        return Response({'items': [{
            'id': i.pk, 'category': i.category_id, 'title': tr(i.title, 'ru'), 'price': i.price,
            'pricing': pricing_payload(i), 'outlet': i.outlet_id} for i in desk.pay_items(request.user)]})


class PayQuoteView(StaffAPIView):
    """Хватает ли баллов клиента на услугу: {enough, total, points, shortSom, reason: limit|balance}."""

    def post(self, request):
        d = _pay_input(request)
        member = desk.read_pay_token(request.user, d['payToken'])
        return Response(desk.points_quote(request.user, member, d['itemId'], d.get('quantity'), d.get('checkAmount')))


class PayChargeView(StaffAPIView):
    """Списать баллы: заявка «оплачено баллами», подтверждённая этим сотрудником."""

    def post(self, request):
        d = _pay_input(request)
        req = desk.charge_points(request, d['payToken'], d['itemId'], d.get('quantity'), d.get('checkAmount'))
        return Response(payload(req), status=201)


class ReceiptInput(serializers.Serializer):
    payToken = serializers.CharField()
    itemId = serializers.CharField()
    receiptQr = serializers.CharField(max_length=2000)
    requestId = serializers.CharField(required=False, allow_blank=True)


def _receipt_input(request):
    s = ReceiptInput(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


class ReceiptPreviewView(StaffAPIView):
    """Скан QR чека: сумма и кешбек клиенту до «Принять оплату»; принятый ранее чек → receipt_used."""

    def post(self, request):
        d = _receipt_input(request)
        return Response(desk.receipt_preview(request.user, d['payToken'], d['itemId'], d['receiptQr'],
                                             d.get('requestId') or None))


class ReceiptAcceptView(StaffAPIView):
    """«Принять оплату» наличными по чеку: операция проведена сразу, кешбек начисляется клиенту."""

    def post(self, request):
        d = _receipt_input(request)
        req = desk.receipt_accept(request, d['payToken'], d['itemId'], d['receiptQr'], d.get('requestId') or None)
        return Response(payload(req), status=201)
