"""
Схемы OpenAPI 3 (обязательный артефакт — по ним генерируются DTO в Dart).
Сериализаторы здесь только описывают форму запросов/ответов; расчёты делают сервисы.
Имена enum-значений — строго как в Dart (rooms, pending, freedomPay …).
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers as s

from apps.catalog.models import FEATURE_ICONS, CategoryId, PaymentMethod
from apps.loyalty.models import PERK_ICONS


class MemberBearer(OpenApiAuthenticationExtension):
    target_class = 'apps.members.auth.MemberAuthentication'
    name = 'memberBearer'

    def get_security_definition(self, auto_schema):
        return {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}


class OptionalMemberBearer(MemberBearer):
    target_class = 'apps.members.auth.OptionalMemberAuthentication'
    name = 'memberBearerOptional'


class StaffBearer(OpenApiAuthenticationExtension):
    target_class = 'apps.staff.auth.StaffAuthentication'
    name = 'staffBearer'

    def get_security_definition(self, auto_schema):
        return {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}


LANG_HEADER = OpenApiParameter('Accept-Language', str, OpenApiParameter.HEADER, required=False,
                               enum=['ru', 'ky', 'en'], description='Язык контента, fallback ru')
DEVICE_HEADER = OpenApiParameter('X-Device-Id', str, OpenApiParameter.HEADER, required=False,
                                 description='Анонимный UUID установки (для аналитики и rate limit)')
IDEMPOTENCY_HEADER = OpenApiParameter('Idempotency-Key', str, OpenApiParameter.HEADER, required=False,
                                      description='Повтор с тем же ключом не создаёт вторую заявку')
CURSOR = OpenApiParameter('cursor', str, required=False)
LIMIT = OpenApiParameter('limit', int, required=False, description='По умолчанию 20')


# ---------------------------------------------------------------- общие

class ErrorBody(s.Serializer):
    code = s.CharField()
    message = s.CharField()


class Error(s.Serializer):
    error = ErrorBody()


ERRORS = {400: Error, 401: Error, 403: Error, 404: Error, 409: Error, 422: Error, 426: Error, 429: Error}


def page_of(name, item):
    return inline_serializer(name, {'items': item(many=True), 'nextCursor': s.CharField(allow_null=True)})


# ---------------------------------------------------------------- каталог

class Feature(s.Serializer):
    icon = s.ChoiceField(choices=FEATURE_ICONS)
    text = s.CharField()


class Pricing(s.Serializer):
    type = s.ChoiceField(choices=['unit', 'check'])
    unit = s.ChoiceField(choices=['night', 'session', 'guest', 'hour', 'visit'], required=False)
    min = s.IntegerField()
    max = s.IntegerField()


class CashbackRules(s.Serializer):
    rate = s.FloatField()
    maxPointsShare = s.FloatField()
    methods = s.ListField(child=s.ChoiceField(choices=PaymentMethod.choices))


class SeasonRange(s.Serializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    from_ = s.DateField(allow_null=True)
    to = s.DateField(allow_null=True)

    def get_fields(self):
        fields = super().get_fields()
        fields['from'] = fields.pop('from_')
        return fields


class ServiceItem(s.Serializer):
    id = s.CharField()
    category = s.ChoiceField(choices=CategoryId.choices)
    title = s.CharField()
    meta = s.CharField()
    image = s.URLField(allow_null=True)
    gallery = s.ListField(child=s.URLField())
    price = s.IntegerField()
    pricing = Pricing()
    promoRate = s.FloatField(allow_null=True)
    tag = s.CharField(allow_null=True)
    description = s.CharField()
    features = Feature(many=True)
    outlet = s.CharField(allow_null=True)
    venue = s.CharField(help_text='Объект: baytur, too-ashuu, suusamyr…')
    section = s.CharField(allow_null=True, help_text='Подраздел прайса объекта')
    priceNote = s.CharField(allow_null=True, help_text='«за сутки», «в час», «от 10 000 до 22 000», «бесплатно»')
    season = SeasonRange(allow_null=True, help_text='Услуга доступна только в эти даты')
    isActive = s.BooleanField()
    cashbackPreview = s.IntegerField(help_text='Баллы за оплату деньгами по цене по умолчанию')


class ServiceCategory(s.Serializer):
    id = s.ChoiceField(choices=CategoryId.choices)
    title = s.CharField()
    cover = s.URLField(allow_null=True)
    sortOrder = s.IntegerField()
    rules = CashbackRules()
    items = ServiceItem(many=True)


class VenueContact(s.Serializer):
    label = s.CharField()
    phone = s.CharField(allow_null=True)
    whatsapp = s.BooleanField()
    email = s.CharField(allow_null=True)


class VenueInfoRow(s.Serializer):
    label = s.CharField()
    value = s.CharField()


class VenueInfo(s.Serializer):
    title = s.CharField()
    text = s.CharField(required=False, help_text='Либо text, либо rows')
    rows = VenueInfoRow(many=True, required=False)


class Venue(s.Serializer):
    id = s.CharField()
    name = s.CharField()
    short = s.CharField()
    description = s.CharField()
    address = s.CharField()
    cover = s.URLField(allow_null=True)
    contacts = VenueContact(many=True)
    info = VenueInfo(many=True)
    sortOrder = s.IntegerField()


class VenueSection(s.Serializer):
    id = s.CharField()
    title = s.CharField()
    note = s.CharField(allow_null=True)
    category = s.ChoiceField(choices=CategoryId.choices, help_text='Раздел программы: способы оплаты')
    rules = CashbackRules()
    sections = s.ListField(child=s.DictField(), help_text='Вложенные подразделы (та же структура)')
    items = ServiceItem(many=True)


class VenueCatalog(s.Serializer):
    venue = Venue()
    sections = VenueSection(many=True)


# ---------------------------------------------------------------- лояльность

TIER_HELP = 'id уровня из GET /loyalty/program (набор уровней задаётся в админке)'


class TierStyle(s.Serializer):
    gradient = s.ListField(child=s.CharField(), help_text='3 цвета #RRGGBB (тёмный → светлый)')
    glow = s.CharField(help_text='цвет свечения #RRGGBB')
    medalUrl = s.URLField(allow_null=True, help_text='null — рисовать стандартную медаль в цветах gradient')
    icon = s.CharField(allow_null=True)


class EntryRule(s.Serializer):
    mode = s.ChoiceField(choices=['all', 'any_n'], help_text='как считаются задания «для получения»')
    n = s.IntegerField(allow_null=True, help_text='для any_n — сколько заданий из привязанных')


class TierAchievementLink(s.Serializer):
    id = s.CharField(help_text='id задания из achievements[]')
    usage = s.ChoiceField(choices=['entry', 'retention', 'both'])


class PermanentRule(s.Serializer):
    lifetime = s.IntegerField(help_text='баллов за всё время не меньше')
    years = s.IntegerField(help_text='лет в программе не меньше')


class Tier(s.Serializer):
    id = s.CharField(help_text='slug: bronze, silver, gold, platinum, titanium, ambassador или новый из админки')
    order = s.IntegerField(help_text='порядок снизу вверх, у базового 0')
    name = s.CharField()
    threshold = s.IntegerField(help_text='сколько «Нынешних» собрать за год на предыдущем уровне; у базового 0')
    canBeFloor = s.BooleanField(help_text='у уровня есть постоянный статус (см. permanent)')
    cashbackBonus = s.FloatField(help_text='надбавка к кешбеку, %: Баллы = Сумма × базовая ставка × (1 + надбавка/100)')
    cashbackRate = s.FloatField(help_text='итоговая ставка кешбека уровня, доля (0.0625 = 6,25 %)')
    permanent = PermanentRule(allow_null=True, help_text='условия «навсегда»; null — уровень не бывает постоянным')
    retention = s.ChoiceField(choices=['none', 'points', 'points_and_achievements'],
                              help_text='как удерживать уровень каждый год')
    entryRule = EntryRule()
    style = TierStyle()
    achievements = TierAchievementLink(many=True)
    colors = s.ListField(child=s.CharField(), help_text='устарело: = style.gradient')
    medal = s.URLField(allow_null=True, help_text='устарело: = style.medalUrl')
    # 'from' — зарезервированное слово Python
    vars()['from'] = s.IntegerField(help_text='устарело: накопленная сумма порогов (для старых версий)')


class Privilege(s.Serializer):
    id = s.CharField()
    tier = s.CharField(help_text=TIER_HELP)
    group = s.CharField(allow_null=True, help_text='«Апгрейдер»: одна привилегия на разных уровнях '
                                                   '(points-rate, late-checkout, room-upgrade, bai-club, welcome-gift)')
    groupTitle = s.CharField(allow_null=True, help_text='Название группы для «Апгрейдера» («Поздний выезд»); '
                                                        'null, если group не задан')
    footnote = s.CharField(allow_null=True, help_text='сноска мелким шрифтом')
    icon = s.ChoiceField(choices=PERK_ICONS)
    title = s.CharField()
    short = s.CharField()
    description = s.CharField()


class Achievement(s.Serializer):
    id = s.CharField()
    title = s.CharField()
    description = s.CharField(allow_null=True)
    icon = s.CharField(allow_null=True)
    scope = s.ChoiceField(choices=['lifetime', 'period'], help_text='за всё время / за текущий период (год)')


class ProgramSettings(s.Serializer):
    periodType = s.ChoiceField(choices=['calendar_year', 'anniversary'])
    floorDepth = s.IntegerField(help_text='устарело: пол теперь — постоянный статус уровня (tiers[].permanent)')
    baseCashbackRate = s.FloatField(help_text='базовая ставка кешбека, доля (0.05 = 5 % = 10/200)')
    pointsPerSom = s.IntegerField(help_text='курс: баллов за 1 сом (1)')


class Program(s.Serializer):
    tiers = Tier(many=True)
    privileges = Privilege(many=True)
    achievements = Achievement(many=True)
    settings = ProgramSettings()


class AchievementCount(s.Serializer):
    required = s.IntegerField()
    done = s.IntegerField()


class TierNext(s.Serializer):
    id = s.CharField(help_text=TIER_HELP)
    threshold = s.IntegerField()
    left = s.IntegerField()
    progress = s.FloatField(help_text='min(1, current / threshold)')
    achievements = AchievementCount()


class TierRetention(s.Serializer):
    required = s.BooleanField(help_text='true только при reason = check')
    reason = s.ChoiceField(choices=['check', 'floor', 'new_this_period', 'not_required'],
                           help_text='check — в конце года проверка; floor — уровень вечный; new_this_period — '
                                     'получен в этом году, проверки не будет; not_required — без подтверждения')
    periodEnd = s.DateTimeField(allow_null=True)
    limit = s.IntegerField(required=False, help_text='только при reason = check')
    collected = s.IntegerField(required=False)
    left = s.IntegerField(required=False)
    progress = s.FloatField(required=False)
    atRisk = s.BooleanField(required=False, help_text='до конца периода меньше atRiskDays и лимит не собран')
    dropTo = s.CharField(required=False, help_text='на какой уровень упадёт, если не подтвердить')
    achievements = AchievementCount(required=False)


class TierState(s.Serializer):
    id = s.CharField(help_text=TIER_HELP)
    since = s.DateTimeField()
    floor = s.CharField(allow_null=True, help_text='вечный уровень: ниже него клиент не упадёт')
    isFloor = s.BooleanField()
    maxReached = s.CharField()
    next = TierNext(allow_null=True, help_text='null на высшем уровне')
    retention = TierRetention()


class Period(s.Serializer):
    key = s.CharField(help_text='например 2027')
    start = s.DateTimeField()
    end = s.DateTimeField()


class Wallet(s.Serializer):
    available = s.IntegerField(help_text='можно потратить сейчас (резерв уже вычтен) — крупно на карте баланса')
    reserved = s.IntegerField()
    current = s.IntegerField(help_text='«Нынешние»: решают уровень, обнуляются при повышении и 1 января')
    lifetime = s.IntegerField(help_text='«За всё время»: только в Профиль → Настройки')
    pendingCashback = s.IntegerField()
    tier = TierState()
    period = Period()
    balance = s.IntegerField(help_text='устарело: available + reserved')
    nextTier = s.CharField(allow_null=True, help_text='устарело: = tier.next.id')
    leftToNext = s.IntegerField(help_text='устарело: = tier.next.left')
    progress = s.FloatField(help_text='устарело: = tier.next.progress')


class Operation(s.Serializer):
    id = s.CharField()
    kind = s.ChoiceField(choices=['cashback', 'spend', 'refund', 'reversal', 'adjustment', 'forfeit', 'expire'],
                         help_text='только движения «Доступных»; expire — лишь в старых записях')
    points = s.IntegerField(help_text='изменение «Доступных»')
    at = s.DateTimeField()
    itemId = s.CharField(allow_null=True)
    category = s.ChoiceField(choices=CategoryId.choices, allow_null=True)
    requestId = s.CharField(allow_null=True)
    title = s.CharField(allow_null=True)
    reason = s.CharField(allow_null=True)
    relatedId = s.CharField(allow_null=True)


class Summary(s.Serializer):
    available = s.IntegerField()
    current = s.IntegerField()
    lifetime = s.IntegerField(help_text='на главных экранах не показывается')
    requestsCount = s.IntegerField()


class AchievementProgress(s.Serializer):
    id = s.CharField()
    progress = s.IntegerField()
    target = s.IntegerField()
    completedAt = s.DateTimeField(allow_null=True)
    periodKey = s.CharField(allow_null=True, help_text='для заданий «за период»')


class Achievements(s.Serializer):
    items = AchievementProgress(many=True)


class PeriodSummary(s.Serializer):
    key = s.CharField()
    tierStart = s.CharField()
    tierEnd = s.CharField()
    collected = s.IntegerField()
    limit = s.IntegerField(allow_null=True)
    result = s.ChoiceField(choices=['retained', 'dropped', 'promoted_in_period', 'floor', 'not_required'])


class TierChangeItem(s.Serializer):
    to = s.CharField()
    at = s.DateTimeField()
    cause = s.ChoiceField(choices=['promotion', 'period_drop', 'admin', 'migration'])
    vars()['from'] = s.CharField(allow_null=True)


class LoyaltyHistory(s.Serializer):
    lifetime = s.IntegerField()
    memberSince = s.DateField()
    periods = PeriodSummary(many=True, help_text='новые сверху')
    tierChanges = TierChangeItem(many=True, help_text='новые сверху')


# ---------------------------------------------------------------- заявки

class PaymentSplit(s.Serializer):
    total = s.IntegerField()
    pointsSom = s.IntegerField()
    points = s.IntegerField()
    moneySom = s.IntegerField()
    rate = s.FloatField()
    cashback = s.IntegerField()


class Bonus(s.Serializer):
    kind = s.ChoiceField(choices=['promo', 'birthday', 'tier'], help_text='tier — надбавка уровня клиента')
    title = s.CharField(required=False, allow_null=True)
    multiplier = s.FloatField(required=False)
    tierId = s.CharField(required=False, help_text='для kind = tier')
    percent = s.FloatField(required=False, help_text='для kind = tier: надбавка, %')


class Quote(PaymentSplit):
    maxPointsSom = s.IntegerField()
    availablePoints = s.IntegerField()
    methods = s.ListField(child=s.ChoiceField(choices=PaymentMethod.choices))
    bonuses = Bonus(many=True)


class RequestInput(s.Serializer):
    itemId = s.CharField()
    quantity = s.IntegerField(required=False, allow_null=True)
    checkAmount = s.IntegerField(required=False, allow_null=True)
    pointsSom = s.IntegerField(required=False)
    method = s.ChoiceField(choices=PaymentMethod.choices, required=False, allow_null=True)
    paymentId = s.CharField(required=False, allow_null=True)


class ItemSnapshot(s.Serializer):
    id = s.CharField()
    category = s.ChoiceField(choices=CategoryId.choices)
    title = s.CharField()
    image = s.URLField(allow_null=True)


class Receipt(s.Serializer):
    id = s.CharField()
    method = s.ChoiceField(choices=PaymentMethod.choices)
    amount = s.IntegerField()
    at = s.DateTimeField()


STATUSES = ['pending', 'confirmed', 'credited', 'rejected', 'cancelled']


class CashbackRequest(s.Serializer):
    id = s.CharField()
    status = s.ChoiceField(choices=STATUSES)
    createdAt = s.DateTimeField()
    timeline = s.DictField(child=s.DateTimeField(), help_text='status → datetime (+ adjusted)')
    item = ItemSnapshot()
    quantity = s.IntegerField()
    checkAmount = s.IntegerField(allow_null=True)
    rules = CashbackRules()
    split = PaymentSplit()
    method = s.ChoiceField(choices=PaymentMethod.choices, allow_null=True)
    receipt = Receipt(allow_null=True)
    originalTotal = s.IntegerField(allow_null=True)
    rejectReason = s.CharField(allow_null=True)
    adjustReason = s.CharField(allow_null=True)
    bonuses = Bonus(many=True)


class StaffMemberBrief(s.Serializer):
    id = s.IntegerField()
    memberId = s.CharField()
    name = s.CharField()
    phone = s.CharField(allow_null=True, help_text='Со скрытыми цифрами')
    tier = s.CharField(help_text=TIER_HELP)
    status = s.CharField()


class FiscalReceipt(s.Serializer):
    number = s.CharField(help_text='Реквизиты чека из QR')
    amount = s.IntegerField()
    acceptedAt = s.DateTimeField()
    acceptedBy = s.IntegerField(allow_null=True, help_text='id кассира')
    acceptedByName = s.CharField(allow_null=True, help_text='Имя кассира')
    outlet = s.CharField(allow_null=True)


class StaffRequest(CashbackRequest):
    outlet = s.CharField(allow_null=True)
    member = StaffMemberBrief()
    paidOnline = s.BooleanField()
    cashToCollect = s.IntegerField()
    cashReceived = s.BooleanField()
    escalated = s.BooleanField()
    escalationReason = s.CharField(allow_null=True)
    proposedTotal = s.IntegerField(allow_null=True)
    confirmedBy = s.IntegerField(allow_null=True)
    rejectedBy = s.IntegerField(allow_null=True)
    adjustedBy = s.IntegerField(allow_null=True)
    isTest = s.BooleanField()
    fiscalReceipt = FiscalReceipt(allow_null=True, help_text='Чек, по которому принята наличная оплата')


# ---------------------------------------------------------------- оплата

class PaymentInput(s.Serializer):
    method = s.ChoiceField(choices=['freedomPay', 'elqr'])
    amountSom = s.IntegerField()
    itemId = s.CharField()
    quantity = s.IntegerField(required=False, allow_null=True)
    checkAmount = s.IntegerField(required=False, allow_null=True)
    pointsSom = s.IntegerField(required=False)


class Payment(s.Serializer):
    id = s.CharField()
    method = s.ChoiceField(choices=PaymentMethod.choices)
    amount = s.IntegerField()
    status = s.ChoiceField(choices=['created', 'pending', 'paid', 'failed', 'expired', 'refunded'])
    redirectUrl = s.URLField(allow_null=True)
    qrPayload = s.CharField(allow_null=True)
    expiresAt = s.DateTimeField(allow_null=True)
    paidAt = s.DateTimeField(allow_null=True)
    requestId = s.CharField(allow_null=True)


# ---------------------------------------------------------------- вход и профиль

class Tokens(s.Serializer):
    accessToken = s.CharField()
    refreshToken = s.CharField()
    expiresIn = s.IntegerField()


class Settings(s.Serializer):
    language = s.ChoiceField(choices=['ru', 'ky', 'en'])
    notifyCashback = s.BooleanField()
    notifyPromos = s.BooleanField()


class PendingConsent(s.Serializer):
    kind = s.ChoiceField(choices=['terms', 'privacy'])
    version = s.CharField()
    url = s.URLField()


class Profile(s.Serializer):
    avatar = s.URLField(allow_null=True, help_text='Квадрат 512×512; null — не задан')
    firstName = s.CharField()
    lastName = s.CharField()
    phone = s.CharField()
    email = s.EmailField(allow_null=True)
    birthday = s.DateField(allow_null=True)
    memberId = s.CharField()
    memberSince = s.DateField()
    settings = Settings()
    marketingConsent = s.BooleanField()
    pendingConsents = PendingConsent(many=True)
    socialAccounts = s.ListField(child=s.ChoiceField(choices=['google', 'apple']),
                                 help_text='Привязанные способы входа')
    hasPin = s.BooleanField(help_text='false — предложить задать PIN (POST /me/pin)')


class TokensWithProfile(Tokens):
    profile = Profile()


class OtpRequest(s.Serializer):
    phone = s.CharField(help_text='E.164')


class OtpRequested(s.Serializer):
    expiresIn = s.IntegerField()
    retryIn = s.IntegerField()


class OtpVerify(s.Serializer):
    phone = s.CharField()
    code = s.CharField()
    socialToken = s.CharField(required=False, help_text='Из /auth/google | /auth/apple — привязать аккаунт к номеру')


class OtpVerified(s.Serializer):
    """Одна из трёх форм: токены | {isNew, registrationToken} | {deactivated, restoreToken, purgeAt, balance}."""
    accessToken = s.CharField(required=False)
    refreshToken = s.CharField(required=False)
    expiresIn = s.IntegerField(required=False)
    isNew = s.BooleanField(required=False)
    registrationToken = s.CharField(required=False)
    deactivated = s.BooleanField(required=False)
    restoreToken = s.CharField(required=False)
    purgeAt = s.DateTimeField(required=False)
    balance = s.IntegerField(required=False)


class SocialPrefill(s.Serializer):
    firstName = s.CharField(allow_null=True)
    lastName = s.CharField(allow_null=True)
    email = s.EmailField(allow_null=True)


class SocialLoginResult(OtpVerified):
    """Аккаунт привязан → как /auth/otp/verify (токены | восстановление). Нет → {needPhone, socialToken, prefill}."""
    isNew = None
    registrationToken = None
    needPhone = s.BooleanField(required=False)
    socialToken = s.CharField(required=False, help_text='15 мин; передать в /auth/otp/verify')
    prefill = SocialPrefill(required=False, help_text='Подставить в форму регистрации')


class GoogleLogin(s.Serializer):
    idToken = s.CharField(help_text='id_token из Google Sign-In')


class AppleLogin(s.Serializer):
    identityToken = s.CharField(help_text='identityToken из Sign in with Apple')
    authorizationCode = s.CharField(required=False, help_text='Нужен, чтобы отозвать доступ при удалении аккаунта')
    nonce = s.CharField(required=False, help_text='Исходный nonce, если передавался в запрос к Apple')
    firstName = s.CharField(required=False, help_text='Apple отдаёт имя только при первом входе')
    lastName = s.CharField(required=False)


class Register(s.Serializer):
    registrationToken = s.CharField()
    firstName = s.CharField(max_length=50)
    lastName = s.CharField(max_length=50)
    birthday = s.DateField()
    email = s.EmailField(required=False, allow_blank=True)
    acceptTerms = s.BooleanField()
    marketingConsent = s.BooleanField(required=False)
    language = s.ChoiceField(choices=['ru', 'ky', 'en'], required=False)
    avatar = s.ImageField(required=False, help_text='Необязательно; только multipart/form-data')
    pin = s.RegexField(r'^\d{6}$', required=False, help_text='6 цифр для входа без SMS; можно задать позже')


class ProfilePatch(s.Serializer):
    firstName = s.CharField(required=False)
    lastName = s.CharField(required=False)
    email = s.EmailField(required=False, allow_blank=True)
    birthday = s.DateField(required=False, help_text='Только если ещё не задана')


class SettingsPatch(s.Serializer):
    language = s.ChoiceField(choices=['ru', 'ky', 'en'], required=False)
    notifyCashback = s.BooleanField(required=False)
    notifyPromos = s.BooleanField(required=False)


class Notification(s.Serializer):
    id = s.CharField()
    type = s.CharField()
    title = s.CharField()
    body = s.CharField()
    data = s.DictField()
    createdAt = s.DateTimeField()
    read = s.BooleanField()


class DeletionInfo(s.Serializer):
    balance = s.IntegerField()
    tier = s.CharField(help_text=TIER_HELP)
    purgeDays = s.IntegerField()
    purgeAt = s.DateTimeField()
    keeps = s.ListField(child=s.DictField(), help_text='Брони и заявки, которые сохранятся')


# ---------------------------------------------------------------- контент

class Article(s.Serializer):
    id = s.CharField()
    image = s.URLField(allow_null=True)
    tag = s.CharField()
    title = s.CharField()
    lead = s.CharField()
    body = s.ListField(child=s.CharField())
    quote = s.CharField(allow_null=True)
    date = s.DateField()
    minutes = s.IntegerField()
    category = s.ChoiceField(choices=CategoryId.choices, allow_null=True)


class Promo(s.Serializer):
    id = s.IntegerField()
    subtitle = s.CharField()
    cta = s.CharField()
    cutout = s.URLField(allow_null=True)
    article = Article()


class ResortEvent(s.Serializer):
    id = s.IntegerField()
    when = s.CharField()
    place = s.CharField()
    article = Article()


class StorySlide(s.Serializer):
    image = s.URLField(allow_null=True)
    title = s.CharField()
    text = s.CharField()
    itemId = s.CharField(allow_null=True)


class Story(s.Serializer):
    category = s.ChoiceField(choices=CategoryId.choices)
    title = s.CharField()
    cover = s.URLField(allow_null=True)
    updatedAt = s.DateTimeField()
    slides = StorySlide(many=True)


class ResortContacts(s.Serializer):
    phone = s.CharField()
    whatsapp = s.CharField()
    mapsUrl = s.URLField(allow_null=True)
    termsUrl = s.URLField(allow_null=True)
    privacyUrl = s.URLField(allow_null=True)
    deletionUrl = s.URLField(allow_null=True)


class AppConfig(s.Serializer):
    minVersion = s.DictField(child=s.CharField())
    updateRequired = s.BooleanField()
    maintenance = s.BooleanField()
    maintenanceMessage = s.CharField(allow_null=True)


# ---------------------------------------------------------------- обращения

class ComplaintMessage(s.Serializer):
    id = s.IntegerField()
    author = s.ChoiceField(choices=['client', 'resort'])
    authorName = s.CharField()
    text = s.CharField()
    attachments = s.ListField(child=s.URLField())
    at = s.DateTimeField()


class Complaint(s.Serializer):
    id = s.CharField()
    number = s.CharField()
    category = s.CharField()
    categoryTitle = s.CharField()
    subtype = s.ChoiceField(choices=['not_credited', 'credited_less', 'overcharged', 'other'], allow_null=True)
    outletId = s.CharField(allow_null=True)
    requestId = s.CharField(allow_null=True)
    operationId = s.CharField(allow_null=True)
    status = s.ChoiceField(choices=['new', 'in_progress', 'answered', 'closed'])
    rating = s.IntegerField(allow_null=True)
    createdAt = s.DateTimeField()
    updatedAt = s.DateTimeField()
    messages = ComplaintMessage(many=True, required=False)


class ComplaintInput(s.Serializer):
    category = s.CharField()
    outletId = s.CharField(required=False, allow_null=True)
    requestId = s.CharField(required=False, allow_null=True)
    operationId = s.CharField(required=False, allow_null=True)
    subtype = s.ChoiceField(choices=['not_credited', 'credited_less', 'overcharged', 'other'], required=False)
    text = s.CharField(min_length=10, max_length=2000)
    attachmentIds = s.ListField(child=s.CharField(), required=False, max_length=5)


class EventsBatch(s.Serializer):
    deviceId = s.CharField()
    platform = s.ChoiceField(choices=['ios', 'android'])
    appVersion = s.CharField()
    language = s.ChoiceField(choices=['ru', 'ky', 'en'])
    events = s.ListField(child=inline_serializer('AppEventInput', {
        'name': s.CharField(), 'at': s.DateTimeField(), 'props': s.DictField(required=False)}))
