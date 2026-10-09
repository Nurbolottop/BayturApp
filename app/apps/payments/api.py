from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
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
    method = serializers.ChoiceField(choices=[PaymentMethod.FREEDOM_PAY, PaymentMethod.ELQR])  # Finik отключён
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


RETURN_TEXTS = {
    'ru': {'title': 'BAYTUR — оплата', 'som': 'сом', 'back': 'Вернуться в приложение',
           'hint': 'Если приложение не открылось — откройте BAYTUR на телефоне, статус оплаты обновится сам.',
           'paid': ('Оплата прошла', 'Спасибо! Вернитесь в приложение — заявка оформится автоматически.'),
           'pending': ('Проверяем оплату…', 'Обычно это занимает несколько секунд.'),
           'refunded': ('Оплата возвращена', 'Деньги вернутся на карту — обычно в течение нескольких дней.'),
           'failed': ('Оплата не прошла', 'Деньги не списаны. Вернитесь в приложение и попробуйте ещё раз.')},
    'ky': {'title': 'BAYTUR — төлөм', 'som': 'сом', 'back': 'Колдонмого кайтуу',
           'hint': 'Колдонмо ачылбаса — телефондон BAYTUR ачыңыз, төлөмдүн абалы өзү жаңыланат.',
           'paid': ('Төлөм өттү', 'Рахмат! Колдонмого кайтыңыз — өтүнмө автоматтык түрдө түзүлөт.'),
           'pending': ('Төлөмдү текшерип жатабыз…', 'Адатта бул бир нече секунд алат.'),
           'refunded': ('Төлөм кайтарылды', 'Акча картага кайтат — адатта бир нече күндүн ичинде.'),
           'failed': ('Төлөм өткөн жок', 'Акча алынган жок. Колдонмого кайтып, кайра аракет кылыңыз.')},
    'en': {'title': 'BAYTUR — payment', 'som': 'som', 'back': 'Back to the app',
           'hint': 'If the app did not open, open BAYTUR on your phone — the payment status updates by itself.',
           'paid': ('Payment successful', 'Thank you! Go back to the app — your request will be created automatically.'),
           'pending': ('Checking the payment…', 'This usually takes a few seconds.'),
           'refunded': ('Payment refunded', 'The money will be returned to your card, usually within a few days.'),
           'failed': ('Payment failed', 'No money was charged. Go back to the app and try again.')},
}


def payment_return(request, payment_id):
    """pg_success_url / pg_failure_url провайдера: браузер оплаты → диплинк baytur://payment/{id}."""
    payment = get_object_or_404(Payment, pk=payment_id)
    # Результат вебхука может прийти на пару секунд позже редиректа — страница ждёт его (pending)
    status = {PaymentStatus.PAID: 'paid', PaymentStatus.CREATED: 'pending',
              PaymentStatus.PENDING: 'pending', PaymentStatus.REFUNDED: 'refunded'}.get(payment.status, 'failed')
    if status == 'pending' and payment.created_at < timezone.now() - timedelta(minutes=40):
        status = 'failed'
    lang = payment.member.language if payment.member.language in RETURN_TEXTS else 'ru'
    texts = RETURN_TEXTS[lang]
    heading, text = texts[status]
    return render(request, 'payments/return.html', {
        'return_url': f'baytur://payment/{payment.pk}', 'status': status, 'amount': payment.amount,
        'payment_id': payment.pk, 'lang': lang, 't': texts, 'heading': heading, 'text': text})


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
