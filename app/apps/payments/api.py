from django.conf import settings
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import PaymentMethod
from apps.common.errors import ApiError
from apps.common.views import MemberAPIView

from . import services
from .gateways import WebhookSignatureError
from .models import Payment, PaymentStatus


class PaymentInput(serializers.Serializer):
    method = serializers.ChoiceField(choices=[PaymentMethod.FINIK, PaymentMethod.FREEDOM_PAY, PaymentMethod.ELQR])
    amountSom = serializers.IntegerField(min_value=1)
    itemId = serializers.CharField(max_length=60)
    quantity = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    checkAmount = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    pointsSom = serializers.IntegerField(required=False, min_value=0, default=0)


class PaymentsView(MemberAPIView):
    def post(self, request):
        s = PaymentInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(services.payment_payload(services.create_payment(request.user, s.validated_data)), status=201)


def _own(request, payment_id):
    p = Payment.objects.filter(pk=payment_id, member=request.user).first()
    if p is None:
        raise ApiError('not_found', 404)
    return p


class PaymentDetailView(MemberAPIView):
    def get(self, request, payment_id):
        return Response(services.payment_payload(_own(request, payment_id)))


class PaymentCheckView(MemberAPIView):
    """Кнопка «Я оплатил» в ЭлQR — запускает проверку у провайдера."""

    def post(self, request, payment_id):
        return Response(services.payment_payload(services.check_payment(_own(request, payment_id))))


class WebhookView(APIView):
    """Вебхук провайдера: проверка подписи, идемпотентная обработка, сверка суммы."""

    authentication_classes = []
    permission_classes = []

    def post(self, request, provider):
        try:
            return services.handle_webhook(provider, request._request)
        except WebhookSignatureError:
            raise ApiError('token_invalid', 401, message='bad signature')


def payment_return(request, payment_id):
    """pg_success_url / pg_failure_url провайдера: браузер оплаты → диплинк baytur://payment/{id}."""
    payment = get_object_or_404(Payment, pk=payment_id)
    return render(request, 'payments/return.html', {'return_url': f'baytur://payment/{payment.pk}'})


@csrf_exempt
def fake_checkout(request, payment_id):
    """
    Страница тестового шлюза (только PAYMENT_BACKEND=fake): «Оплатить» / «Отказ» → статус платежа
    (как по вебхуку) → возврат в приложение по baytur://payment/{id}.
    """
    if settings.PAYMENT_BACKEND != 'fake':
        return HttpResponse(status=404)
    payment = get_object_or_404(Payment, pk=payment_id)
    if request.method == 'POST':
        status = PaymentStatus.PAID if request.POST.get('result') == 'paid' else PaymentStatus.FAILED
        services.set_status(payment.pk, status, payment.amount)
        return render(request, 'payments/fake_done.html', {'payment': payment, 'status': status,
                                                           'return_url': f'baytur://payment/{payment.pk}'})
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET', 'POST'])
    return render(request, 'payments/fake_checkout.html', {'payment': payment})
