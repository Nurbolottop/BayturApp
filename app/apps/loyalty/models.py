from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.ids import new_operation_id


class TierId(models.TextChoices):
    """Уровни по умолчанию (сид). Набор уровней редактируется в админке: можно добавлять и удалять."""
    BRONZE = 'bronze', 'Бронза'
    SILVER = 'silver', 'Серебро'
    GOLD = 'gold', 'Золото'
    PLATINUM = 'platinum', 'Платина'
    DIAMOND = 'diamond', 'Бриллиант'


PERK_ICONS = [
    'cashback', 'birthday', 'drink', 'earlyCheckIn', 'beach', 'parking', 'lateCheckOut', 'upgrade', 'spa',
    'transfer', 'concierge', 'chef', 'villa', 'events', 'gift',
]


# Градиенты уровней по умолчанию — из tier_style.dart мобилки (ТЗ §7.4)
DEFAULT_TIER_COLORS = {
    'bronze': ['#4A220F', '#99562C', '#D9976A'],
    'silver': ['#3F4A56', '#7D8B99', '#C3CCD6'],
    'gold': ['#5E4206', '#AE7E17', '#E6BF58'],
    'platinum': ['#232C38', '#627488', '#B4C2D3'],
    'diamond': ['#140F3A', '#4B3DB0', '#8FD8FF'],
}
FALLBACK_TIER_COLORS = ['#232C38', '#627488', '#B4C2D3']


class Tier(models.Model):
    """Уровень программы. Набор уровней задаётся в админке; оформление (градиент, медаль) — тоже."""

    id = models.SlugField(primary_key=True, max_length=30)
    name = models.JSONField('Название', default=dict)
    from_points = models.PositiveBigIntegerField('Порог, баллов (lifetime)')
    colors = models.JSONField('Градиент: 3 цвета #RRGGBB', default=list, blank=True)
    medal = models.CharField('Картинка медали (необязательно)', max_length=500, blank=True)

    @property
    def gradient(self):
        c = self.colors if isinstance(self.colors, list) and len(self.colors) == 3 else \
            DEFAULT_TIER_COLORS.get(self.id, FALLBACK_TIER_COLORS)
        return list(c)

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
