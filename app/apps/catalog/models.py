from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CategoryId(models.TextChoices):
    """Набор фиксирован в мобилке (иконки, быстрые кнопки)."""
    ROOMS = 'rooms', 'Номера'
    SPA = 'spa', 'SPA'
    FOOD = 'food', 'Рестораны'
    POOLS = 'pools', 'Бассейны'
    SPORT = 'sport', 'Спорт'


class PaymentMethod(models.TextChoices):
    CASH = 'cash', 'Наличные'
    FINIK = 'finik', 'Finik'
    FREEDOM_PAY = 'freedomPay', 'Freedom Pay'
    ELQR = 'elqr', 'ЭлQR'


# Finik отключён (10.10.2026): остаётся только в старых заявках и отчётах, новых платежей и заявок с ним нет
DISABLED_METHODS = {PaymentMethod.FINIK}
ONLINE_METHODS = {PaymentMethod.FREEDOM_PAY, PaymentMethod.ELQR}
ACTIVE_METHOD_CHOICES = [(v, label) for v, label in PaymentMethod.choices if v not in DISABLED_METHODS]


class PricingUnit(models.TextChoices):
    NIGHT = 'night'
    SESSION = 'session'
    GUEST = 'guest'
    HOUR = 'hour'
    VISIT = 'visit'


FEATURE_ICONS = [
    'view', 'bed', 'people', 'area', 'wifi', 'breakfast', 'terrace', 'pool', 'time', 'towel', 'tea', 'music',
    'fire', 'chef', 'drink', 'sun', 'water', 'gym', 'trainer', 'bath', 'nature', 'cold', 'warm', 'tv', 'flower',
]

rate_validators = [MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('1'))]


DEFAULT_VENUE = 'baytur'
DEFAULT_VENUE_NAME = {'ru': 'BAYTUR Иссык-Куль', 'ky': 'BAYTUR Ысык-Көл', 'en': 'BAYTUR Issyk-Kul'}


def default_venue():
    """Объект по умолчанию — курорт на Иссык-Куле; создаётся, если его ещё нет (чистая база, тесты)."""
    Venue.objects.get_or_create(id=DEFAULT_VENUE, defaults={'name': DEFAULT_VENUE_NAME})
    return DEFAULT_VENUE


class Venue(models.Model):
    """
    Объект экосистемы BAYTUR: курорт на Иссык-Куле, «Тоо-Ашуу», кымызолечение в Суусамыре… У каждого объекта
    своё приложение, бэкенд один: аккаунт, баллы и уровни — общие.
    contacts — [{label: l10n, phone, whatsapp: bool, email}];
    info — инфоблоки: [{title: l10n, text: l10n}] или [{title: l10n, rows: [{label: l10n, value: l10n}]}].
    """

    id = models.SlugField(primary_key=True, max_length=40)
    name = models.JSONField('Название', default=dict)
    short = models.JSONField('Подзаголовок', default=dict, blank=True)
    description = models.JSONField('Описание', default=dict, blank=True)
    address = models.JSONField('Адрес', default=dict, blank=True)
    cover = models.CharField('Обложка', max_length=500, blank=True)
    contacts = models.JSONField('Контакты', default=list, blank=True)
    info = models.JSONField('Инфоблоки', default=list, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField('Показывать', default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Объект'
        verbose_name_plural = 'Объекты'

    def __str__(self):
        return self.name.get('ru') or self.id


class Outlet(models.Model):
    """Точка обслуживания: «Ресепшен», «Da Vinci», «SPA»… Сотрудник видит заявки только своих точек."""

    id = models.SlugField(primary_key=True, max_length=40)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='outlets', default=default_venue,
                              verbose_name='Объект')
    name = models.JSONField('Название', default=dict)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Точка обслуживания'
        verbose_name_plural = 'Точки обслуживания'

    def __str__(self):
        return self.name.get('ru') or self.id


class Category(models.Model):
    id = models.CharField(primary_key=True, max_length=20, choices=CategoryId.choices)
    title = models.JSONField('Название', default=dict)
    cover = models.CharField('Обложка', max_length=500, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # CashbackRules
    rate = models.DecimalField('Доля кешбека', max_digits=5, decimal_places=4, validators=rate_validators)
    max_points_share = models.DecimalField('Доля оплаты баллами', max_digits=5, decimal_places=4,
                                           validators=rate_validators)
    methods = models.JSONField('Способы доплаты', default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'

    def __str__(self):
        return self.title.get('ru') or self.id


class Section(models.Model):
    """
    Подраздел прайса объекта: «Прокат», «Кафе» → «Супы»… category — раздел программы, чьи правила (способы
    оплаты) действуют на услуги подраздела; в старом приложении курорта услуги видны по category.
    """

    id = models.SlugField(primary_key=True, max_length=60)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='sections', verbose_name='Объект')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children',
                               verbose_name='Внутри раздела')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='sections',
                                 verbose_name='Раздел программы (правила)')
    title = models.JSONField('Название', default=dict)
    note = models.JSONField('Пояснение', default=dict, blank=True, help_text='Мелким шрифтом под названием')
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField('Показывать', default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['venue__sort_order', 'sort_order', 'id']
        verbose_name = 'Подраздел'
        verbose_name_plural = 'Подразделы'

    def __str__(self):
        return self.title.get('ru') or self.id


class ItemQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, category__is_active=True)


class Item(models.Model):
    id = models.SlugField('Slug', primary_key=True, max_length=60,
                          help_text='Стабильный: на него ссылаются заявки, история, сторис')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='items', default=default_venue,
                              verbose_name='Объект')
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='items', null=True, blank=True,
                                verbose_name='Подраздел')
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name='items', null=True, blank=True)
    title = models.JSONField('Название', default=dict)
    meta = models.JSONField('Короткая строка', default=dict, blank=True)
    image = models.CharField('Главное фото', max_length=500, blank=True)
    gallery = models.JSONField('Галерея', default=list, blank=True)
    price = models.PositiveIntegerField('Цена, сом')
    pricing = models.JSONField('Тип цены', default=dict)
    tag = models.JSONField('Бейдж', default=dict, blank=True)
    description = models.JSONField('Описание', default=dict, blank=True)
    features = models.JSONField('Что входит', default=list, blank=True)
    price_note = models.JSONField('Подпись к цене', default=dict, blank=True,
                                  help_text='«за сутки», «500 сом в час», «от 10 000 до 22 000», «бесплатно»')
    season_from = models.DateField('Доступна с', null=True, blank=True)
    season_to = models.DateField('Доступна по', null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ItemQuerySet.as_manager()

    class Meta:
        ordering = ['category__sort_order', 'sort_order', 'id']
        verbose_name = 'Услуга'
        verbose_name_plural = 'Услуги'

    def __str__(self):
        return self.title.get('ru') or self.id

    # --- правила ---
    def active_promo(self, at=None):
        at = at or timezone.now()
        promos = getattr(self, '_prefetched_promos', None)
        if promos is None:
            promos = list(self.promos.all())
        best = None
        for p in promos:
            if p.is_active_at(at) and (best is None or p.rate > best.rate):
                best = p
        return best

    def promo_rate(self, at=None):
        promo = self.active_promo(at)
        return promo.rate if promo else None

    def current_tag(self, at=None):
        promo = self.active_promo(at)
        if promo and promo.tag and any(promo.tag.values()):
            return promo.tag
        return self.tag or None

    @property
    def pricing_type(self):
        return (self.pricing or {}).get('type', 'unit')

    def pricing_bounds(self):
        p = self.pricing or {}
        if self.pricing_type == 'check':
            return int(p.get('min', 1)), int(p.get('max', 10_000_000))
        return int(p.get('min', 1)), int(p.get('max', 10))

    def snapshot(self):
        """Снимок услуги для заявки: id, category, title, image на момент заявки."""
        return {'id': self.id, 'category': self.category_id, 'title': self.title, 'image': self.image}


class ItemPromo(models.Model):
    """Акция на услугу: повышенная ставка с датами; по окончании ставка и бейдж снимаются сами."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='promos')
    rate = models.DecimalField('Ставка', max_digits=5, decimal_places=4, validators=rate_validators)
    tag = models.JSONField('Бейдж', default=dict, blank=True)
    starts_at = models.DateTimeField('Начало', null=True, blank=True)
    ends_at = models.DateTimeField('Конец', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Акция на услугу'
        verbose_name_plural = 'Акции на услуги'

    def is_active_at(self, at):
        return (self.is_active
                and (self.starts_at is None or self.starts_at <= at)
                and (self.ends_at is None or at < self.ends_at))

    @staticmethod
    def active_q(at):
        return Q(is_active=True) & (Q(starts_at__isnull=True) | Q(starts_at__lte=at)) & (
            Q(ends_at__isnull=True) | Q(ends_at__gt=at))
