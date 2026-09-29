from rest_framework import serializers
from rest_framework.response import Response

from apps.catalog.models import PaymentMethod
from apps.common.errors import ApiError
from apps.common.pagination import paginate
from apps.common.views import MemberAPIView

from . import services
from .models import ACTIVE_STATUSES, CashbackRequest
from .serializers import request_payload


class RequestInput(serializers.Serializer):
    itemId = serializers.CharField(max_length=60)
    quantity = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    checkAmount = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    pointsSom = serializers.IntegerField(required=False, allow_null=True, min_value=0, default=0)
    method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False, allow_null=True)
    paymentId = serializers.CharField(required=False, allow_null=True, allow_blank=True)


def _input(request):
    s = RequestInput(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


class QuoteView(MemberAPIView):
    """Мобилка вызывает на каждое изменение ввода (с задержкой ~300 мс)."""

    def post(self, request):
        return Response(services.quote_payload(request.user, _input(request)))


class RequestsView(MemberAPIView):
    def get(self, request):
        qs = request.user.cashback_requests.select_related('payment')
        status = request.query_params.get('status', 'all')
        if status == 'active':
            qs = qs.filter(status__in=ACTIVE_STATUSES)
        elif status != 'all':
            raise ApiError('validation_error', 400, extra={'fields': {'status': ['active | all']}})
        return Response(paginate(request, qs, lambda rows: [request_payload(r) for r in rows]))

    def post(self, request):
        key = request.headers.get('Idempotency-Key') or None
        if key and len(key) > 100:
            raise ApiError('validation_error', 400, extra={'fields': {'Idempotency-Key': ['≤ 100 символов']}})
        req, created = services.create_request(request.user, _input(request), key)
        req = CashbackRequest.objects.select_related('payment').get(pk=req.pk)
        return Response(request_payload(req), status=201 if created else 200)


class RequestDetailView(MemberAPIView):
    def get(self, request, request_id):
        req = request.user.cashback_requests.select_related('payment').filter(pk=request_id).first()
        if req is None:
            raise ApiError('not_found', 404)
        return Response(request_payload(req))


class RequestCancelView(MemberAPIView):
    def post(self, request, request_id):
        req = services.cancel_request(request.user, request_id) \
            if request.user.cashback_requests.filter(pk=request_id).exists() else None
        if req is None:
            raise ApiError('not_found', 404)
        return Response(request_payload(CashbackRequest.objects.select_related('payment').get(pk=req.pk)))
