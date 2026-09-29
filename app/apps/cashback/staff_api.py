"""
Рабочее место сотрудника (ТЗ §8.5). Логика и ограничения §8.3 — в apps.cashback.desk
(та же реализация используется админ-API и веб-панелью).
"""
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import audit
from apps.common.i18n import iso
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
    """Клиент для сотрудника: без баланса и истории — только уровень и заявки в его точках."""
    from apps.loyalty.services import get_wallet
    reqs = scoped_requests(user).filter(member=member).order_by('-created_at')[:20]
    return {
        'id': member.pk,
        'memberId': member.member_id,
        'name': member.full_name,
        'phone': mask_phone(member.phone),
        'tier': get_wallet(member).tier_id,
        'status': member.status,
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
        return Response(member_brief(member, request.user))


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
