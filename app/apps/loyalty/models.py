from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.ids import new_operation_id


class TierId(models.TextChoices):
    """Количество уровней фиксировано в мобилке (у каждого своя медаль)."""
    BRONZE = 'bronze', 'Бронза'
    SILVER = 'silver', 'Серебро'
    GOLD = 'gold', 'Золото'
    PLATINUM = 'platinum', 'Платина'
    DIAMOND = 'diamond', 'Бриллиант'


PERK_ICONS = [
    'cashback', 'birthday', 'drink', 'earlyCheckIn', 'beach', 'parking', 'lateCheckOut', 'upgrade', 'spa',
    'transfer', 'concierge', 'chef', 'villa', 'events', 'gift',
]


class Tier(models.Model):
    id = models.CharField(primary_key=True, max_length=20, choices=TierId.choices)
    name = models.JSONField('Название', default=dict)
    from_points = models.PositiveBigIntegerField('Порог, баллов (lifetime)')

    class Meta:
        ordering = ['from_points']
        verbose_name = 'Уровень'
        verbose_name_plural = 'Уровни'

    def __str__(self):
        return self.name.get('ru') or self.id


class Privilege(models.Model):
    id = models.SlugField(primary_key=True, max_length=40)
    tier = models.ForeignKey(Tier, on_delete=models.PROTECT, related_name='privileges')
    icon = models.CharField(max_length=30)
    title = models.JSONField('Название', default=dict)
    short = models.JSONField('Коротко (1–2 слова)', default=dict)
    description = models.JSONField('Описание', default=dict)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['tier__from_points', 'sort_order', 'id']
        verbose_name = 'Привилегия'
        verbose_name_plural = 'Привилегии'

    def __str__(self):
        return self.title.get('ru') or self.id


class Wallet(models.Model):
    """
    Кошелёк участника. balance — денормализованная сумма журнала Operation (сверяется
    командой check_ledger); все изменения — в транзакции с select_for_update.
    """

    member = models.OneToOneField('members.Member', on_delete=models.CASCADE, related_name='wallet',
                                  primary_key=True)
    balance = models.BigIntegerField(default=0)
    reserved = models.BigIntegerField(default=0)
    lifetime = models.BigIntegerField(default=0)
    tier = models.ForeignKey(Tier, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    last_activity_at = models.DateTimeField(null=True, blank=True,
                                            help_text='Последнее реальное действие: заявка, начисление, списание')
    expiry_warned = models.JSONField(default=list, blank=True, help_text='За сколько дней уже предупредили')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name='wallet_balance_gte_0'),
            models.CheckConstraint(condition=Q(reserved__gte=0), name='wallet_reserved_gte_0'),
            models.CheckConstraint(condition=Q(reserved__lte=models.F('balance')), name='wallet_reserved_lte_balance'),
        ]

    @property
    def available(self):
        return self.balance - self.reserved


class OperationKind(models.TextChoices):
    CASHBACK = 'cashback', 'Начисление'
    SPEND = 'spend', 'Списание'
    REFUND = 'refund', 'Возврат'
    ADJUSTMENT = 'adjustment', 'Корректировка'
    EXPIRE = 'expire', 'Сгорание'
    FORFEIT = 'forfeit', 'Списание при удалении'


class Operation(models.Model):
    """Журнал (ledger): записи не редактируются, корректировка — только новой операцией."""

    id = models.CharField(primary_key=True, max_length=32, default=new_operation_id, editable=False)
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='operations')
    kind = models.CharField(max_length=20, choices=OperationKind.choices)
    points = models.BigIntegerField()
    at = models.DateTimeField(default=timezone.now, db_index=True)
    item_id = models.CharField(max_length=60, blank=True, null=True)
    category = models.CharField(max_length=20, blank=True, null=True)
    request = models.ForeignKey('cashback.CashbackRequest', null=True, blank=True, on_delete=models.PROTECT,
                                related_name='operations')
    title = models.JSONField(null=True, blank=True, help_text='Fallback-название, если услугу удалили')
    reason = models.TextField(blank=True, help_text='Причина корректировки/возврата — клиент её видит')
    related = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                help_text='Исходная операция для refund / adjustment')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='+')
    complaint = models.ForeignKey('complaints.Complaint', null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='compensations')
    affects_lifetime = models.BooleanField(default=False)

    class Meta:
        ordering = ['-at', '-id']
        indexes = [models.Index(fields=['member', '-at'])]
        verbose_name = 'Операция'
        verbose_name_plural = 'Операции'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError('Операции журнала не редактируются')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError('Операции журнала не удаляются')
