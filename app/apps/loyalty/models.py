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
    TITANIUM = 'titanium', 'Титан'
    AMBASSADOR = 'ambassador', 'Амбассадор'


PERK_ICONS = [
    'cashback', 'birthday', 'drink', 'earlyCheckIn', 'beach', 'parking', 'lateCheckOut', 'upgrade', 'spa',
    'transfer', 'concierge', 'chef', 'villa', 'events', 'gift',
    'wifi', 'coffee', 'gym', 'bike', 'breakfast', 'yoga', 'kids', 'laundry', 'pool', 'excursion', 'photo',
]

# Иконки заданий, нарисованные в приложении (AchievementIcon мобилки); курорт выбирает только из них
ACHIEVEMENT_ICONS = ['calendar', 'ticket', 'users', 'bed', 'spa', 'food', 'star', 'gift']


# Градиенты уровней по умолчанию — из tier_style.dart мобилки (ТЗ §7.4)
DEFAULT_TIER_COLORS = {
    'bronze': ['#4A220F', '#99562C', '#D9976A'],
    'silver': ['#3F4A56', '#7D8B99', '#C3CCD6'],
    'gold': ['#5E4206', '#AE7E17', '#E6BF58'],
    'platinum': ['#232C38', '#627488', '#B4C2D3'],
    'titanium': ['#140F3A', '#4B3DB0', '#8FD8FF'],
    'ambassador': ['#1A1A1A', '#4A4A4A', '#D4AF37'],
}
FALLBACK_TIER_COLORS = ['#232C38', '#627488', '#B4C2D3']


class Retention(models.TextChoices):
    NONE = 'none', 'Не нужно'
    POINTS = 'points', 'Баллы'
    POINTS_AND_ACHIEVEMENTS = 'points_and_achievements', 'Баллы и задания'


class EntryRule(models.TextChoices):
    ALL = 'all', 'Все задания'
    ANY_N = 'any_n', 'Любые N из M'


class TierQuerySet(models.QuerySet):
    def live(self):
        """Не удалённые (мягкое удаление)."""
        return self.filter(deleted_at__isnull=True)

    def active(self):
        """Уровни, которые присваиваются клиентам и видны в приложении."""
        return self.live().filter(active=True)


class Tier(models.Model):
    """
    Уровень программы (ТЗ лояльности §3.1). Порядок — order снизу вверх, у базового 0.
    threshold — сколько «Нынешних» собрать на предыдущем уровне за один период.
    """

    id = models.SlugField(primary_key=True, max_length=30)
    order = models.IntegerField('Порядок снизу вверх', default=0, db_index=True)
    name = models.JSONField('Название', default=dict)
    threshold = models.PositiveBigIntegerField('Порог, «Нынешних» баллов за период', default=0)
    entry_rule = models.CharField('Задания для получения', max_length=10, choices=EntryRule.choices,
                                  default=EntryRule.ALL)
    entry_n = models.PositiveSmallIntegerField('N для «любые N из M»', null=True, blank=True)
    retention = models.CharField('Подтверждение каждый год', max_length=30, choices=Retention.choices,
                                 default=Retention.POINTS)
    can_be_floor = models.BooleanField('Может стать вечным', default=True)  # не используется: см. permanent_*
    cashback_bonus = models.DecimalField('Надбавка к кешбеку, %', max_digits=6, decimal_places=2, default=0,
                                         help_text='Баллы = Сумма × базовая ставка × (1 + надбавка / 100)')
    permanent_lifetime = models.PositiveBigIntegerField('Навсегда: баллов за всё время', null=True, blank=True,
                                                        help_text='Пусто — уровень не бывает постоянным')
    permanent_years = models.PositiveSmallIntegerField('Навсегда: лет в программе', default=0)
    limit_bonus = models.PositiveBigIntegerField('Надбавка к лимиту', default=10_000)
    limit_only_grows = models.BooleanField('Лимит только растёт', default=True)
    min_limit = models.PositiveBigIntegerField('Минимальный лимит', default=0)
    drop_to = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                verbose_name='При потере переходит на (пусто — на один ниже)')
    colors = models.JSONField('Градиент: 3 цвета #RRGGBB', default=list, blank=True)
    glow = models.CharField('Цвет свечения #RRGGBB', max_length=7, blank=True)
    medal = models.CharField('Картинка медали (необязательно)', max_length=500, blank=True)
    icon = models.CharField('Иконка', max_length=40, blank=True)
    active = models.BooleanField('Активен', default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TierQuerySet.as_manager()

    @property
    def gradient(self):
        c = self.colors if isinstance(self.colors, list) and len(self.colors) == 3 else \
            DEFAULT_TIER_COLORS.get(self.id, FALLBACK_TIER_COLORS)
        return list(c)

    @property
    def glow_color(self):
        return self.glow or self.gradient[2]

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Уровень'
        verbose_name_plural = 'Уровни'

    def __str__(self):
        return self.name.get('ru') or self.id


class LoyaltySettings(models.Model):
    """Настройки балловой системы (одна запись). version растёт при любой правке настроек, уровней, заданий."""

    CACHE_KEY = 'loyalty_settings'

    class PeriodType(models.TextChoices):
        CALENDAR_YEAR = 'calendar_year', 'Календарный год'
        ANNIVERSARY = 'anniversary', 'Год от получения уровня'

    period_type = models.CharField('Период', max_length=20, choices=PeriodType.choices,
                                   default=PeriodType.CALENDAR_YEAR)
    timezone = models.CharField('Часовой пояс', max_length=40, default='Asia/Bishkek')
    floor_depth = models.PositiveSmallIntegerField('Глубина пола', default=1)
    carry_over = models.BooleanField('Переносить излишек «Нынешних» при повышении', default=False)
    at_risk_days = models.PositiveSmallIntegerField('Предупреждать о риске за N дней', default=60)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Настройки балловой системы'
        verbose_name_plural = 'Настройки балловой системы'

    def save(self, *args, **kwargs):
        from django.core.cache import cache
        self.pk = 1
        if not kwargs.pop('keep_version', False):
            self.version = (LoyaltySettings.objects.filter(pk=1).values_list('version', flat=True).first() or 0) + 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def get(cls):
        from django.core.cache import cache
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj = cls.objects.filter(pk=1).first()
            if obj is None:
                obj = cls(pk=1)
                obj.save()
            cache.set(cls.CACHE_KEY, obj, 30)
        return obj

    @classmethod
    def bump_version(cls, *args, **kwargs):
        """Правка уровней или заданий тоже меняет версию программы."""
        from django.core.cache import cache
        cls.get()
        cls.objects.filter(pk=1).update(version=models.F('version') + 1)
        cache.delete(cls.CACHE_KEY)


class Privilege(models.Model):
    """
    Привилегия уровня. group объединяет одну привилегию на разных уровнях для экрана «Апгрейдер»
    (поздний выезд 13:00 → 14:00 → 16:00 → 18:00). {rate} в текстах — ставка кешбека уровня, %.
    """

    id = models.SlugField(primary_key=True, max_length=40)
    modes = models.JSONField('Режимы', default=list, blank=True, help_text='Пусто — везде; ["ski"] — только Тоо-Ашуу')
    group = models.SlugField('Группа (апгрейдер)', max_length=40, blank=True)
    group_title = models.JSONField('Название группы', default=dict, blank=True)  # «Поздний выезд» — заголовок апгрейдера
    footnote = models.JSONField('Сноска мелким шрифтом', default=dict, blank=True)
    tier = models.ForeignKey(Tier, on_delete=models.PROTECT, related_name='privileges')
    icon = models.CharField(max_length=30)
    title = models.JSONField('Название', default=dict)
    short = models.JSONField('Коротко (1–2 слова)', default=dict)
    description = models.JSONField('Описание', default=dict)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['tier__order', 'sort_order', 'id']
        verbose_name = 'Привилегия'
        verbose_name_plural = 'Привилегии'

    def __str__(self):
        return self.title.get('ru') or self.id


class Wallet(models.Model):
    """
    Состояние клиента в программе (client_loyalty). Счётчики — кеш суммы проводок журнала Operation
    (сверка — check_ledger); меняются только через проводки, в транзакции с select_for_update.

    balance  — хранимые «Доступные» (вместе с резервом); в API available = balance − reserved
    current  — «Нынешние»: заработанные с последнего сброса (повышение, смена периода)
    lifetime — «За всё время»
    """

    member = models.OneToOneField('members.Member', on_delete=models.CASCADE, related_name='wallet',
                                  primary_key=True)
    balance = models.BigIntegerField(default=0)
    reserved = models.BigIntegerField(default=0)
    current = models.BigIntegerField(default=0)
    lifetime = models.BigIntegerField(default=0)
    tier = models.ForeignKey(Tier, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    tier_since = models.DateTimeField(null=True, blank=True)
    max_reached = models.ForeignKey(Tier, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True, db_index=True)
    settings_version = models.PositiveIntegerField(default=0)
    risk_warned = models.JSONField(default=dict, blank=True,
                                   help_text='{period: ключ, days: [за сколько дней уже предупредили]}')
    last_activity_at = models.DateTimeField(null=True, blank=True,
                                            help_text='Последнее реальное действие: заявка, начисление, списание')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name='wallet_balance_gte_0'),
            models.CheckConstraint(condition=Q(reserved__gte=0), name='wallet_reserved_gte_0'),
            models.CheckConstraint(condition=Q(reserved__lte=models.F('balance')), name='wallet_reserved_lte_balance'),
            models.CheckConstraint(condition=Q(current__gte=0), name='wallet_current_gte_0'),
            models.CheckConstraint(condition=Q(lifetime__gte=0), name='wallet_lifetime_gte_0'),
        ]

    @property
    def available(self):
        return self.balance - self.reserved


class OperationKind(models.TextChoices):
    CASHBACK = 'cashback', 'Начисление'
    SPEND = 'spend', 'Списание'
    RESERVE = 'reserve', 'Резерв'
    RELEASE = 'release', 'Снятие резерва'
    REFUND = 'refund', 'Возврат'
    REVERSAL = 'reversal', 'Отмена начисления'
    ADJUSTMENT = 'adjustment', 'Корректировка'
    PERIOD_RESET = 'period_reset', 'Сброс «Нынешних» (новый период)'
    PROMOTION_RESET = 'promotion_reset', 'Сброс «Нынешних» (новый уровень)'
    EXPIRE = 'expire', 'Сгорание'
    FORFEIT = 'forfeit', 'Списание при удалении'


# Служебные проводки — клиенту в истории не показываются
SERVICE_KINDS = (OperationKind.RESERVE, OperationKind.RELEASE, OperationKind.PERIOD_RESET,
                 OperationKind.PROMOTION_RESET)


class Operation(models.Model):
    """
    Журнал проводок (ledger): записи не редактируются, исправление — только новой проводкой.
    points — изменение «Доступных» (dAvailable); d_current, d_lifetime, d_reserved — остальных счётчиков.
    """

    id = models.CharField(primary_key=True, max_length=32, default=new_operation_id, editable=False)
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='operations')
    kind = models.CharField(max_length=20, choices=OperationKind.choices)
    points = models.BigIntegerField(default=0)
    d_current = models.BigIntegerField(default=0)
    d_lifetime = models.BigIntegerField(default=0)
    d_reserved = models.BigIntegerField(default=0)
    period_key = models.CharField(max_length=20, blank=True, help_text='В каком периоде засчитаны «Нынешние»')
    idempotency_key = models.CharField(max_length=120, null=True, blank=True, unique=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    item_id = models.CharField(max_length=60, blank=True, null=True)
    category = models.CharField(max_length=20, blank=True, null=True)
    request = models.ForeignKey('cashback.CashbackRequest', null=True, blank=True, on_delete=models.PROTECT,
                                related_name='operations')
    title = models.JSONField(null=True, blank=True, help_text='Fallback-название, если услугу удалили')
    reason = models.TextField(blank=True, help_text='Причина корректировки/возврата — клиент её видит')
    related = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                help_text='Исходная операция для refund / reversal / adjustment')
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
        self.affects_lifetime = self.d_lifetime != 0
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError('Операции журнала не удаляются')


class LimitSource(models.TextChoices):
    PERIOD_CLOSE = 'period_close', 'Закрытие периода'
    ADMIN = 'admin', 'Администратор'
    MIGRATION = 'migration', 'Миграция'


class TierLimit(models.Model):
    """Лимит удержания уровня у клиента — хранится по каждому уровню и не теряется при понижении."""

    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='tier_limits')
    tier = models.ForeignKey(Tier, on_delete=models.CASCADE, related_name='+')
    limit = models.BigIntegerField(default=0)
    source = models.CharField(max_length=20, choices=LimitSource.choices, default=LimitSource.PERIOD_CLOSE)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['member', 'tier'], name='tier_limit_unique')]


class TierChangeCause(models.TextChoices):
    PROMOTION = 'promotion', 'Повышение'
    PERMANENT = 'permanent', 'Постоянный статус'
    PERIOD_DROP = 'period_drop', 'Понижение при закрытии периода'
    ADMIN = 'admin', 'Администратор'
    MIGRATION = 'migration', 'Миграция'


class TierChange(models.Model):
    """История уровней клиента."""

    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='tier_changes')
    from_tier = models.ForeignKey(Tier, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    to_tier = models.ForeignKey(Tier, on_delete=models.PROTECT, related_name='+')
    at = models.DateTimeField(default=timezone.now, db_index=True)
    cause = models.CharField(max_length=20, choices=TierChangeCause.choices)
    reason = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+')

    class Meta:
        ordering = ['-at', '-id']


class PeriodResultKind(models.TextChoices):
    RETAINED = 'retained', 'Подтверждён'
    DROPPED = 'dropped', 'Понижен'
    PROMOTED_IN_PERIOD = 'promoted_in_period', 'Получен в этом периоде'
    FLOOR = 'floor', 'Вечный'
    NOT_REQUIRED = 'not_required', 'Подтверждение не нужно'


class PeriodResult(models.Model):
    """Итог периода клиента. Уникальность (member, period_key) — идемпотентность закрытия года."""

    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='period_results')
    period_key = models.CharField(max_length=20)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    tier_start = models.ForeignKey(Tier, on_delete=models.PROTECT, related_name='+')
    tier_end = models.ForeignKey(Tier, on_delete=models.PROTECT, related_name='+')
    current = models.BigIntegerField()
    limit_before = models.BigIntegerField(null=True, blank=True)
    limit_after = models.BigIntegerField(null=True, blank=True)
    checked = models.BooleanField(default=False)
    result = models.CharField(max_length=20, choices=PeriodResultKind.choices)
    settings_version = models.PositiveIntegerField(default=0)
    closed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-period_start']
        constraints = [models.UniqueConstraint(fields=['member', 'period_key'], name='period_result_unique')]


# ---------------------------------------------------------------- задания (ачивки)

class AchievementType(models.TextChoices):
    CONSECUTIVE_YEARS = 'consecutive_years', 'N лет подряд с покупками'
    MEMBER_YEARS = 'member_years', 'N лет в программе'
    REQUESTS_COUNT = 'requests_count', 'N заявок'
    NIGHTS = 'nights', 'N ночей'
    SPEND_SOM = 'spend_som', 'Потратить N сом'
    CATEGORIES_USED = 'categories_used', 'Попробовать категории'
    LIFETIME_POINTS = 'lifetime_points', 'Накопить N баллов за всё время'
    MANUAL = 'manual', 'Отмечает администратор'


class AchievementScope(models.TextChoices):
    LIFETIME = 'lifetime', 'За всё время'
    PERIOD = 'period', 'За текущий период'


class AchievementQuerySet(models.QuerySet):
    def live(self):
        return self.filter(deleted_at__isnull=True)

    def active(self):
        return self.live().filter(active=True)


class Achievement(models.Model):
    """
    Задание — условие помимо баллов. params по типу:
    consecutive_years {years, minPerYear=1}; member_years {years}; requests_count {count, category?};
    nights {nights, category='rooms'}; spend_som {amount, category?}; categories_used {categories: [...]};
    lifetime_points {points}; manual {}.
    """

    id = models.SlugField(primary_key=True, max_length=40)
    modes = models.JSONField('Режимы', default=list, blank=True, help_text='Пусто — везде')
    title = models.JSONField('Название', default=dict)
    description = models.JSONField('Описание', default=dict, blank=True)
    icon = models.CharField('Иконка', max_length=40, blank=True, choices=[(i, i) for i in ACHIEVEMENT_ICONS])
    type = models.CharField('Тип', max_length=30, choices=AchievementType.choices)
    params = models.JSONField('Параметры', default=dict, blank=True)
    scope = models.CharField('Область', max_length=10, choices=AchievementScope.choices,
                             default=AchievementScope.LIFETIME)
    visible = models.BooleanField('Показывать клиенту', default=True)
    active = models.BooleanField('Активно', default=True)
    sort_order = models.IntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = AchievementQuerySet.as_manager()

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Задание'
        verbose_name_plural = 'Задания'

    def __str__(self):
        return self.title.get('ru') or self.id


class AchievementUsage(models.TextChoices):
    ENTRY = 'entry', 'Для получения'
    RETENTION = 'retention', 'Для подтверждения'
    BOTH = 'both', 'Оба'


class TierAchievement(models.Model):
    tier = models.ForeignKey(Tier, on_delete=models.CASCADE, related_name='tier_achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name='tier_links')
    usage = models.CharField(max_length=10, choices=AchievementUsage.choices, default=AchievementUsage.BOTH)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(fields=['tier', 'achievement'], name='tier_achievement_unique')]


class MemberAchievement(models.Model):
    """Прогресс клиента по заданию. period_key пуст для заданий «за всё время»."""

    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name='member_states')
    period_key = models.CharField(max_length=20, blank=True)
    progress = models.BigIntegerField(default=0)
    target = models.BigIntegerField(default=1)
    completed_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    reason = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['member', 'achievement', 'period_key'],
                                               name='member_achievement_unique')]
