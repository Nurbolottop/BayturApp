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


DEFAULT_VENUE = 'resort'
DEFAULT_VENUE_NAME = {'ru': 'Baytur Resort & Spa', 'ky': 'Baytur Resort & Spa', 'en': 'Baytur Resort & Spa'}
# приложение → его режимы (ТЗ экосистемы §3.2): bayturapp — resort; Baytur S&K — ski (зима) и kymyz (лето)
APP_MODES = {'resort': ('resort',), 'sk': ('ski', 'kymyz')}


class AppChoice(models.TextChoices):
    RESORT = 'resort', 'bayturapp (Resort & Spa)'
    SK = 'sk', 'Baytur S&K'


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

    id = models.SlugField('Режим', primary_key=True, max_length=40, help_text='resort, ski, kymyz')
    app = models.CharField('Приложение', max_length=10, choices=AppChoice.choices, default=AppChoice.RESORT)
    name = models.JSONField('Название', default=dict)
    short = models.JSONField('Подзаголовок', default=dict, blank=True)
    description = models.JSONField('Описание', default=dict, blank=True)
    address = models.JSONField('Адрес', default=dict, blank=True)
    cover = models.CharField('Обложка', max_length=500, blank=True)
    icon = models.CharField('Иконка', max_length=500, blank=True)
    phone = models.CharField('Телефон', max_length=30, blank=True)
    whatsapp = models.CharField('WhatsApp', max_length=30, blank=True)
    email = models.EmailField('Email', blank=True)
    maps_url = models.CharField('Карты (ссылка)', max_length=500, blank=True)
    two_gis_url = models.CharField('2ГИС (ссылка)', max_length=500, blank=True)
    timezone = models.CharField('Часовой пояс', max_length=40, default='Asia/Bishkek')
    is_open = models.BooleanField('Объект открыт', default=True)
    early_booking_enabled = models.BooleanField('Ранняя бронь', default=False)
    accent = models.CharField('Цвет в админке', max_length=9, default='#C6F24E')
    contacts = models.JSONField('Контакты', default=list, blank=True)
    info = models.JSONField('Инфоблоки', default=list, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField('Показывать', default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Объект (режим)'
        verbose_name_plural = 'Объекты (режимы)'

    def __str__(self):
        return self.name.get('ru') or self.id


class Season(models.Model):
    """Сезон объекта S&K (ТЗ §4.1): по датам сервер решает, какой режим сейчас у Baytur S&K."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='seasons', verbose_name='Режим')
    year = models.PositiveIntegerField('Год')
    starts_at = models.DateField('Начало')
    ends_at = models.DateField('Конец')
    early_booking_from = models.DateField('Ранняя бронь с', null=True, blank=True)
    off_season_mode = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                        verbose_name='Режим в межсезонье перед этим сезоном')

    class Meta:
        ordering = ['starts_at']
        constraints = [models.UniqueConstraint(fields=['venue', 'year'], name='season_venue_year_unique')]
        verbose_name = 'Сезон'
        verbose_name_plural = 'Сезоны'

    def __str__(self):
        return f'{self.venue_id} {self.starts_at:%d.%m.%Y}–{self.ends_at:%d.%m.%Y}'


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


class SectionKind(models.TextChoices):
    STAY = 'stay', 'Проживание'
    PASS = 'pass', 'Скипасс, билеты'
    RENTAL = 'rental', 'Прокат'
    MENU = 'menu', 'Меню'
    PROCEDURE = 'procedure', 'Процедуры'
    TRANSFER = 'transfer', 'Трансфер'
    EXTRA = 'extra', 'Доп. услуги'
    INFO = 'info', 'Справка'


class ServiceUnit(models.TextChoices):
    NIGHT = 'night', 'ночь'
    DAY = 'day', 'сутки'
    HOUR = 'hour', 'час'
    MIN30 = 'min30', '30 минут'
    HOURS3 = 'hours3', '3 часа'
    SESSION = 'session', 'сеанс'
    PERSON = 'person', 'человек'
    GUEST = 'guest', 'гость'
    VISIT = 'visit', 'посещение'
    VEHICLE_ONE_WAY = 'vehicle_one_way', 'машина в одну сторону'
    VEHICLE_ROUND_TRIP = 'vehicle_round_trip', 'машина туда и обратно'
    SEAT = 'seat', 'место'
    PORTION = 'portion', 'порция'
    PIECE = 'piece', 'штука'
    NONE = 'none', '—'


class ServiceAction(models.TextChoices):
    BOOK_STAY = 'book_stay', 'Бронь проживания'
    BOOK_SLOT = 'book_slot', 'Запись на время'
    BOOK_SEATS = 'book_seats', 'Места в рейсе'
    BUY_TICKET = 'buy_ticket', 'Купить билет'
    PAY_CASHIER = 'pay_cashier', 'Оплата у кассира'
    REQUEST = 'request', 'Заявка администратору'
    INFO = 'info', 'Только информация'


class Section(models.Model):
    """
    Подраздел прайса объекта: «Прокат», «Кафе» → «Супы»… category — раздел программы, чьи правила (способы
    оплаты) действуют на услуги подраздела; в старом приложении курорта услуги видны по category.
    """

    id = models.SlugField(primary_key=True, max_length=60)
    key = models.SlugField('id в приложении', max_length=40, blank=True,
                           help_text='Короткий id раздела в режиме: skipass, rental, stay…')
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='sections', verbose_name='Объект')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children',
                               verbose_name='Внутри раздела')
    kind = models.CharField('Тип раздела', max_length=20, choices=SectionKind.choices, blank=True)
    icon = models.CharField('Иконка', max_length=30, blank=True)
    subtitle = models.JSONField('Подзаголовок', default=dict, blank=True)
    cover = models.CharField('Обложка', max_length=500, blank=True)
    cashback_rate = models.DecimalField('Ставка кешбека', max_digits=5, decimal_places=4, null=True, blank=True,
                                        help_text='Пусто — базовая ставка программы')
    methods = models.JSONField('Способы оплаты', null=True, blank=True, help_text='Пусто — из раздела программы')
    default_unit = models.CharField('Единица по умолчанию', max_length=20, blank=True)
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
    price_up_to = models.PositiveIntegerField('Цена до (вилка)', null=True, blank=True)
    price_on_request = models.BooleanField('Цену уточняйте', default=False)
    unit = models.CharField('Единица', max_length=20, choices=ServiceUnit.choices, blank=True)
    action = models.CharField('Кнопка в карточке', max_length=20, choices=ServiceAction.choices,
                              default=ServiceAction.PAY_CASHIER)
    methods = models.JSONField('Способы оплаты', null=True, blank=True, help_text='Пусто — из раздела')
    cashback_rate = models.DecimalField('Ставка кешбека', max_digits=5, decimal_places=4, null=True, blank=True)
    capacity = models.JSONField('Вместимость', null=True, blank=True, help_text='{"minGuests": 1, "maxGuests": 6}')
    featured = models.BooleanField('Хит', default=False)
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


class PromotionKind(models.TextChoices):
    PERCENT = 'percent', 'Скидка в процентах'
    AMOUNT = 'amount', 'Скидка суммой'
    SPECIAL_PRICE = 'specialPrice', 'Специальная цена'
    GIFT = 'gift', 'Бесплатная услуга в подарок'
    BUNDLE = 'bundle', 'Пакет (комбо)'
    N_PLUS_ONE = 'nPlusOne', 'N+1'


class PromotionScope(models.TextChoices):
    ITEMS = 'items', 'Услуги'
    SECTIONS = 'sections', 'Разделы'
    VENUES = 'venues', 'Объекты'
    ALL = 'all', 'Все объекты'


class PromotionAudience(models.TextChoices):
    ALL = 'all', 'Все гости'
    MEMBERS = 'members', 'Участники программы лояльности'
    TIERS = 'tiers', 'Участники выбранных уровней'
    GROUPS = 'groups', 'Группы (от N человек)'
    CHILDREN = 'children', 'Дети'


class Promotion(models.Model):
    """
    Акция на цену (ТЗ «BAYTUR полный список услуг», раздел «Акции»). Базовая цена услуги сохраняется, акционная
    считается сервером: в прайсе (promo у услуги), в расчёте и в заявке — клиент платит акционную цену.

    value: percent — %, amount — сом с заказа, specialPrice — цена за единицу, nPlusOne — N (каждая N+1-я бесплатно).
    gift — услуга gift_item в подарок (цена заказа не меняется), bundle — пакет bundle_items за bundle_price.
    Совместимость: несовместимая акция не сочетается ни с чем; совместимые применяются вместе.
    """

    title = models.JSONField('Название', default=dict)
    description = models.JSONField('Описание', default=dict, blank=True)
    tag = models.JSONField('Бейдж', default=dict, blank=True, help_text='«−20%», «Суперцена»')
    note = models.JSONField('Условие (коротко)', default=dict, blank=True, help_text='«по будням», «от 3 ночей»')
    image = models.CharField('Картинка', max_length=500, blank=True)
    show_on_home = models.BooleanField('Показать на главной', default=False)
    kind = models.CharField('Вид', max_length=20, choices=PromotionKind.choices)
    value = models.DecimalField('Размер', max_digits=12, decimal_places=2, default=0)
    # охват
    scope = models.CharField('Охват', max_length=10, choices=PromotionScope.choices, default=PromotionScope.ITEMS)
    venues = models.ManyToManyField(Venue, blank=True, related_name='promotions', verbose_name='Объекты')
    sections = models.ManyToManyField(Section, blank=True, related_name='promotions', verbose_name='Разделы')
    items = models.ManyToManyField(Item, blank=True, related_name='promotions', verbose_name='Услуги')
    # подарок и пакет
    gift_item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                  verbose_name='Услуга в подарок')
    bundle_items = models.ManyToManyField(Item, blank=True, related_name='bundles', verbose_name='Состав пакета')
    bundle_price = models.PositiveIntegerField('Цена пакета', null=True, blank=True)
    # период
    starts_at = models.DateTimeField('Начало', null=True, blank=True)
    ends_at = models.DateTimeField('Конец', null=True, blank=True)
    weekdays = models.JSONField('Дни недели', default=list, blank=True, help_text='0 — пн … 6 — вс; пусто — все')
    time_from = models.TimeField('С', null=True, blank=True)
    time_to = models.TimeField('До', null=True, blank=True)
    # условия
    min_quantity = models.PositiveIntegerField('Минимум (ночей, гостей, единиц)', null=True, blank=True)
    min_amount = models.PositiveIntegerField('Минимальная сумма заказа, сом', null=True, blank=True)
    # для кого
    audience = models.CharField('Для кого', max_length=10, choices=PromotionAudience.choices,
                                default=PromotionAudience.ALL)
    tiers = models.JSONField('Уровни', default=list, blank=True, help_text='Для «участники выбранных уровней»')
    group_min = models.PositiveIntegerField('Группа от, человек', null=True, blank=True)
    # совместимость и лимит
    stackable = models.BooleanField('Суммируется с другими акциями', default=False)
    usage_limit = models.PositiveIntegerField('Лимит использований', null=True, blank=True,
                                              help_text='Пусто — без лимита')
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField('Включена', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        verbose_name = 'Акция'
        verbose_name_plural = 'Акции'

    def __str__(self):
        return self.title.get('ru') or f'Акция {self.pk}'


class InfoBlock(models.Model):
    """Справка раздела (ТЗ §4.1): трассы, расписание, как добраться. lines — [{title, value, phone, whatsapp, slopeDeg}]."""

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='info_blocks', verbose_name='Раздел')
    title = models.JSONField('Заголовок', default=dict)
    lines = models.JSONField('Строки', default=list, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Справка'
        verbose_name_plural = 'Справка'


class Showcase(models.Model):
    """Главная режима (ТЗ §6.2): шапка, факты, кнопка, плитки разделов. Акции и новости — свои модели."""

    venue = models.OneToOneField(Venue, primary_key=True, on_delete=models.CASCADE, related_name='showcase')
    hero_image = models.CharField('Шапка (день)', max_length=500, blank=True)
    hero_image_night = models.CharField('Шапка (ночь)', max_length=500, blank=True)
    facts = models.JSONField('Факты', default=list, blank=True, help_text='[{"ru": "3 000 м", …}]')
    cta = models.JSONField('Кнопка', default=dict, blank=True)
    cta_section = models.CharField('Кнопка ведёт в раздел', max_length=40, blank=True)
    tiles = models.JSONField('Плитки', default=list, blank=True, help_text='[{"section", "icon", "title": {...}}]')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Главная'
        verbose_name_plural = 'Главная'


SHOWCASE_ICONS = ['skipass', 'rental', 'stay', 'transfer', 'cafe', 'trails', 'yurt', 'massage', 'kymyz', 'banya',
                  'horses']


class NewsItem(models.Model):
    """Новость главной (ТЗ §4.1): «Открытие сезона, 20 декабря»."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='news', verbose_name='Режим')
    when = models.JSONField('Когда (текст)', default=dict, blank=True)
    date = models.DateField('Дата', null=True, blank=True)
    title = models.JSONField('Заголовок', default=dict)
    place = models.JSONField('Место', default=dict, blank=True)
    image = models.CharField('Картинка', max_length=500, blank=True)
    article_id = models.CharField('Статья (id)', max_length=60, blank=True)
    publish_from = models.DateTimeField('Показывать с', null=True, blank=True)
    publish_to = models.DateTimeField('Показывать по', null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField('Показывать', default=True)

    class Meta:
        ordering = ['sort_order', 'date', 'id']
        verbose_name = 'Новость главной'
        verbose_name_plural = 'Новости главной'


class EternalNews(models.Model):
    """
    «Вечная новость» (ТЗ §4.1): рассказ о другом сезоне S&K со слайдами и бонусом за раннюю бронь.
    slides — [{image, title: {...}, text: {...}, cta: {label: {...}, action, mode, target} | null}];
    early_bonus — {kind: points|percent, value, text: {...}}.
    """

    about = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='eternal_about',
                              verbose_name='О каком режиме')
    show_in = models.JSONField('Показывать в режимах', default=list, help_text='["ski"]')
    title = models.JSONField('Заголовок', default=dict)
    lead = models.JSONField('Подводка', default=dict, blank=True)
    cover = models.CharField('Обложка', max_length=500, blank=True)
    slides = models.JSONField('Слайды', default=list, blank=True)
    early_bonus = models.JSONField('Бонус за раннюю бронь', null=True, blank=True)
    is_active = models.BooleanField('Показывать', default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '«Вечная новость»'
        verbose_name_plural = '«Вечные новости»'


class AppRelease(models.Model):
    """Настройки приложения S&K (ТЗ §6.1): своя минимальная версия и техработы. Resort — в ProgramSettings."""

    app = models.CharField(primary_key=True, max_length=10, choices=AppChoice.choices)
    min_version_ios = models.CharField(max_length=20, default='0.1.0')
    min_version_android = models.CharField(max_length=20, default='0.1.0')
    maintenance = models.BooleanField('Техработы', default=False)
    maintenance_message = models.JSONField('Текст техработ', default=dict, blank=True)

    class Meta:
        verbose_name = 'Приложение'
        verbose_name_plural = 'Приложения'
