from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.i18n import iso
from apps.common.ids import new_request_id


class RequestStatus(models.TextChoices):
    PENDING = 'pending', 'Ожидает'
    CONFIRMED = 'confirmed', 'Подтверждена'
    CREDITED = 'credited', 'Кешбек начислен'
    REJECTED = 'rejected', 'Отклонена'
    CANCELLED = 'cancelled', 'Отменена'


ACTIVE_STATUSES = (RequestStatus.PENDING, RequestStatus.CONFIRMED)


class RejectReason(models.TextChoices):
    NOT_PROVIDED = 'not_provided', 'Услуга не оказана'
    WRONG_AMOUNT = 'wrong_amount', 'Неверная сумма'
    DUPLICATE = 'duplicate', 'Дубль'
    EXPIRED = 'expired', 'Истёк срок подтверждения'
    PAYMENT_FAILED = 'payment_failed', 'Оплата не прошла'
    OTHER = 'other', 'Другое'


class CashbackRequest(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_request_id, editable=False)
    member = models.ForeignKey('members.Member', on_delete=models.PROTECT, related_name='cashback_requests')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='requests')
    outlet = models.ForeignKey('catalog.Outlet', null=True, blank=True, on_delete=models.PROTECT,
                               related_name='requests')
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING,
                              db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    timeline = models.JSONField(default=dict)

    # Снимки на момент отправки — смена правил/акции/курса после отправки не влияет
    item_snapshot = models.JSONField()
    rules = models.JSONField(help_text='{rate, maxPointsShare, methods, pointsPerSom} с учётом акции/ДР')
    bonuses = models.JSONField(default=list, blank=True)

    # Ввод клиента
    quantity = models.PositiveIntegerField(default=1)
    check_amount = models.PositiveIntegerField(null=True, blank=True)
    requested_points_som = models.PositiveIntegerField(default=0)
    method = models.CharField(max_length=20, null=True, blank=True)

    # PaymentSplit (всё считает бек)
    total = models.PositiveIntegerField()
    points_som = models.PositiveIntegerField()
    points = models.PositiveBigIntegerField()
    money_som = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=6, decimal_places=4)
    cashback = models.PositiveBigIntegerField()

    original_total = models.PositiveIntegerField(null=True, blank=True)
    reject_code = models.CharField(max_length=30, blank=True)
    reject_reason = models.TextField(blank=True)
    adjust_reason = models.TextField(blank=True)
    cash_received = models.BooleanField(default=False)

    # Эскалация менеджеру (правка > N % или кешбек выше лимита)
    escalated = models.BooleanField(default=False)
    escalation_reason = models.CharField(max_length=200, blank=True)
    proposed_total = models.PositiveIntegerField(null=True, blank=True)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+')

    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='+')
    rejected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+')
    adjusted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+')
    confirmed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    rejected_at = models.DateTimeField(null=True, blank=True, db_index=True)
    adjusted_at = models.DateTimeField(null=True, blank=True)
    credited_at = models.DateTimeField(null=True, blank=True, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                     help_text='Когда заявка вышла из pending (confirm/reject/cancel)')

    # Фоновые сроки (переживают рестарт — их обрабатывает периодическая задача)
    auto_confirm_at = models.DateTimeField(null=True, blank=True, db_index=True)
    credit_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    idempotency_key = models.CharField(max_length=100, null=True, blank=True)
    is_test = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['member', '-created_at']), models.Index(fields=['outlet', 'status'])]
        constraints = [
            models.UniqueConstraint(fields=['member', 'idempotency_key'], condition=Q(idempotency_key__isnull=False),
                                    name='request_idempotency_unique'),
        ]
        verbose_name = 'Заявка на кешбек'
        verbose_name_plural = 'Заявки на кешбек'

    def __str__(self):
        return self.id

    def mark(self, status, at=None):
        self.status = status
        timeline = dict(self.timeline or {})
        timeline[status] = iso((at or timezone.now()))
        self.timeline = timeline

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES
