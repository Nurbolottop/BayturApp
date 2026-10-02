"""
Схемы OpenAPI 3 (обязательный артефакт — по ним генерируются DTO в Dart).
Сериализаторы здесь только описывают форму запросов/ответов; расчёты делают сервисы.
Имена enum-значений — строго как в Dart (rooms, pending, freedomPay …).
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers as s

from apps.catalog.models import FEATURE_ICONS, CategoryId, PaymentMethod
from apps.loyalty.models import PERK_ICONS, OperationKind


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
    isActive = s.BooleanField()
    cashbackPreview = s.IntegerField(help_text='Баллы за оплату деньгами по цене по умолчанию')


class ServiceCategory(s.Serializer):
    id = s.ChoiceField(choices=CategoryId.choices)
    title = s.CharField()
    cover = s.URLField(allow_null=True)
    sortOrder = s.IntegerField()
    rules = CashbackRules()
    items = ServiceItem(many=True)


# ---------------------------------------------------------------- лояльность

TIER_HELP = 'id уровня из GET /loyalty/program (набор уровней задаётся в админке)'


class Tier(s.Serializer):
    id = s.CharField(help_text='slug, например bronze; новые уровни добавляются в админке')
    name = s.CharField()
    colors = s.ListField(child=s.CharField(), help_text='градиент: 3 цвета #RRGGBB (тёмный → светлый)')
    medal = s.URLField(allow_null=True, help_text='картинка медали; null — рисовать стандартную в цветах colors')
    # 'from' — зарезервированное слово Python
    vars()['from'] = s.IntegerField()


class Privilege(s.Serializer):
    id = s.CharField()
    tier = s.CharField(help_text=TIER_HELP)
    icon = s.ChoiceField(choices=PERK_ICONS)
    title = s.CharField()
    short = s.CharField()
    description = s.CharField()


class Program(s.Serializer):
    tiers = Tier(many=True)
    privileges = Privilege(many=True)


class Wallet(s.Serializer):
    balance = s.IntegerField()
    reserved = s.IntegerField()
    available = s.IntegerField()
    lifetime = s.IntegerField()
    tier = s.CharField(help_text=TIER_HELP)
    pendingCashback = s.IntegerField()
    nextTier = s.CharField(allow_null=True, help_text=TIER_HELP)
    leftToNext = s.IntegerField()
    progress = s.FloatField()
    expiresAt = s.DateTimeField(allow_null=True)


class Operation(s.Serializer):
    id = s.CharField()
    kind = s.ChoiceField(choices=OperationKind.choices)
    points = s.IntegerField()
    at = s.DateTimeField()
    itemId = s.CharField(allow_null=True)
    category = s.ChoiceField(choices=CategoryId.choices, allow_null=True)
    requestId = s.CharField(allow_null=True)
    title = s.CharField(allow_null=True)
    reason = s.CharField(allow_null=True)
    relatedId = s.CharField(allow_null=True)


class Summary(s.Serializer):
    available = s.IntegerField()
    lifetime = s.IntegerField()
    requestsCount = s.IntegerField()


# ---------------------------------------------------------------- заявки

class PaymentSplit(s.Serializer):
    total = s.IntegerField()
    pointsSom = s.IntegerField()
    points = s.IntegerField()
    moneySom = s.IntegerField()
    rate = s.FloatField()
    cashback = s.IntegerField()


class Bonus(s.Serializer):
    kind = s.ChoiceField(choices=['promo', 'birthday'])
    title = s.CharField(required=False, allow_null=True)
    multiplier = s.FloatField(required=False)


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


# ---------------------------------------------------------------- оплата

class PaymentInput(s.Serializer):
    method = s.ChoiceField(choices=['finik', 'freedomPay', 'elqr'])
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
