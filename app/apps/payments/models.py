from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.ids import new_payment_id


class PaymentStatus(models.TextChoices):
    CREATED = 'created'
    PENDING = 'pending'
    PAID = 'paid'
    FAILED = 'failed'
    EXPIRED = 'expired'
    REFUNDED = 'refunded'


FINAL_STATUSES = {PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.REFUNDED}


class Payment(models.Model):
    """Онлайн-оплата денежной части заявки (Finik / Freedom Pay / ЭлQR)."""

    id = models.CharField(primary_key=True, max_length=32, default=new_payment_id, editable=False)
    member = models.ForeignKey('members.Member', on_delete=models.PROTECT, related_name='payments')
    method = models.CharField(max_length=20)
    provider = models.CharField('Шлюз', max_length=20, blank=True)  # fake | freedompay; пусто — PAYMENT_BACKEND
    amount = models.PositiveIntegerField('Сумма, сом')
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.CREATED,
                              db_index=True)
    provider_ref = models.CharField(max_length=100, blank=True, db_index=True)
    redirect_url = models.URLField(max_length=1000, blank=True)
    qr_payload = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    request = models.OneToOneField('cashback.CashbackRequest', null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='payment')
    # Параметры заявки, под которые создан платёж — для сверки и автосоздания заявки
    params = models.JSONField(default=dict)
    refunded_amount = models.PositiveIntegerField(default=0)
    is_test = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'

    def __str__(self):
        return self.id


class Refund(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='refunds')
    amount = models.PositiveIntegerField()
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, default='pending')  # pending | done | failed
    provider_ref = models.CharField(max_length=100, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='+')
    created_at = models.DateTimeField(default=timezone.now)


class WebhookEvent(models.Model):
    """Идемпотентность вебхуков: одно событие провайдера обрабатывается один раз."""

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=120)
    payload = models.JSONField()
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['provider', 'event_id'], name='webhook_event_unique')]
