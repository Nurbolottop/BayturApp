"""
Сериализаторы админ-API: camelCase в JSON, локализуемые поля — {ru, ky, en} (context full_l10n).
TEXT_FIELDS — поля, которые может менять роль «только тексты и фото» (редактор).
"""
import re
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from apps.catalog.models import (ACTIVE_METHOD_CHOICES, FEATURE_ICONS, Category, CategoryId, Item, ItemPromo, Outlet,
                                 PaymentMethod,
                                 PricingUnit)
from apps.catalog.serializers import cashback_preview
from apps.common.i18n import LANGS, iso, validate_l10n
from apps.common.models import ProgramSettings
from apps.common.serializers import L10nField, MediaUrlField
from apps.complaints.models import ComplaintCategory, ReplyTemplate
from apps.content.models import Article, Promo, ResortEvent, Story, StorySlide
from apps.loyalty.models import PERK_ICONS, Privilege, Tier
from apps.members.models import LegalDocument, LegalKind
from apps.notifications.models import Campaign, PushTemplate
from apps.staff.models import StaffUser
from apps.staff.roles import Role


# ---------------------------------------------------------------- общие поля

class IsoDateTimeField(serializers.DateTimeField):
    def to_representation(self, value):
        return iso(value) if value else None


class RateField(serializers.DecimalField):
    """Доля 0…1 (кешбек, оплата баллами); в JSON — число."""

    def __init__(self, **kwargs):
        kwargs.setdefault('max_digits', 5)
        kwargs.setdefault('decimal_places', 4)
        kwargs.setdefault('min_value', Decimal('0'))
        kwargs.setdefault('max_value', Decimal('1'))
        kwargs.setdefault('coerce_to_string', False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if isinstance(data, float):
            data = repr(data)
        return super().to_internal_value(data)

    def to_representation(self, value):
        return float(value) if value is not None else None


def full_l10n(value, allow_list=False):
    value = value or {}
    empty = [] if allow_list else ''
    return {lang: value.get(lang, empty) or empty for lang in LANGS}


def optional_l10n(**kwargs):
    kwargs.setdefault('required', False)
    return L10nField(required_ru=False, **kwargs)


class ImmutableIdMixin:
    """id задаётся при создании и дальше не меняется (на него ссылаются заявки, история, мобилка)."""

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None and 'id' in fields:
            fields['id'].read_only = True
        return fields

    def validate_id(self, value):
        model = self.Meta.model
        if self.instance is None and model.objects.filter(pk=value).exists():
            raise serializers.ValidationError('уже существует')
        return value


# ---------------------------------------------------------------- каталог

class OutletSerializer(ImmutableIdMixin, serializers.ModelSerializer):
    TEXT_FIELDS = {'name'}

    id = serializers.SlugField(max_length=40)
    name = L10nField()
    sortOrder = serializers.IntegerField(source='sort_order', required=False)
    isActive = serializers.BooleanField(source='is_active', required=False)

    class Meta:
        model = Outlet
        fields = ['id', 'name', 'sortOrder', 'isActive']


class RulesField(serializers.Field):
    """CashbackRules категории: {rate, methods} ↔ поля модели. maxPointsShare устарел: всегда 1.0, на запись игнорируется."""

    def __init__(self, **kwargs):
        kwargs['source'] = '*'
        super().__init__(**kwargs)

    def to_representation(self, obj):
        return {'rate': float(obj.rate), 'maxPointsShare': 1.0, 'methods': list(obj.methods)}

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('Ожидается объект {rate, methods}')
        out, errors = {}, {}
        for key, attr in (('rate', 'rate'),):
            if key in data:
                try:
                    out[attr] = RateField().to_internal_value(data[key])
                except serializers.ValidationError as e:
                    errors[key] = e.detail
        if 'methods' in data:
            methods = data['methods']
            allowed = [v for v, _ in ACTIVE_METHOD_CHOICES]
            if not isinstance(methods, list) or any(m not in allowed for m in methods):
                errors['methods'] = [f'допустимо: {", ".join(allowed)}']
            else:
                out['methods'] = list(dict.fromkeys(methods))
        if errors:
            raise serializers.ValidationError(errors)
        return out


class CategorySerializer(ImmutableIdMixin, serializers.ModelSerializer):
    TEXT_FIELDS = {'title', 'cover'}

    id = serializers.ChoiceField(choices=CategoryId.choices)
    title = L10nField()
    cover = MediaUrlField()
    sortOrder = serializers.IntegerField(source='sort_order', required=False)
    isActive = serializers.BooleanField(source='is_active', required=False)
    rules = RulesField()
    itemsCount = serializers.SerializerMethodField()
    updatedAt = IsoDateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'title', 'cover', 'sortOrder', 'isActive', 'rules', 'itemsCount', 'updatedAt']

    def get_itemsCount(self, obj):
        return obj.items.count()

    def validate(self, attrs):
        if self.instance is None:
            if 'rate' not in attrs:
                raise serializers.ValidationError({'rules': ['нужен rate']})
        return attrs


class PricingField(serializers.JSONField):
    """{type: unit, unit, min, max} | {type: check, min, max}."""

    def to_internal_value(self, data):
        if not isinstance(data, dict) or data.get('type') not in ('unit', 'check'):
            raise serializers.ValidationError('type: unit | check')
        try:
            lo = int(data.get('min', 1))
            hi = int(data.get('max', 10 if data['type'] == 'unit' else 10_000_000))
        except (TypeError, ValueError):
            raise serializers.ValidationError('min / max — целые числа')
        if lo < 1 or hi < lo:
            raise serializers.ValidationError('1 ≤ min ≤ max')
        if data['type'] == 'check':
            return {'type': 'check', 'min': lo, 'max': hi}
        unit = data.get('unit', PricingUnit.VISIT)
        if unit not in PricingUnit.values:
            raise serializers.ValidationError(f'unit: {", ".join(PricingUnit.values)}')
        return {'type': 'unit', 'unit': unit, 'min': lo, 'max': hi}


class FeaturesField(serializers.JSONField):
    """Пункты «что входит»: [{icon из FEATURE_ICONS, text {ru, ky, en}}]."""

    def to_representation(self, value):
        return [{'icon': f.get('icon'), 'text': full_l10n(f.get('text'))} for f in (value or [])]

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError('Ожидается список')
        out = []
        for i, f in enumerate(data):
            if not isinstance(f, dict) or f.get('icon') not in FEATURE_ICONS:
                raise serializers.ValidationError(f'[{i}].icon: неизвестная иконка')
            text = f.get('text')
            if isinstance(text, str):
                text = {'ru': text}
            try:
                validate_l10n(text)
            except Exception as e:
                raise serializers.ValidationError(f'[{i}].text: {"; ".join(getattr(e, "messages", [str(e)]))}')
            out.append({'icon': f['icon'], 'text': {k: v for k, v in text.items() if k in LANGS}})
        return out


class ItemPromoSerializer(serializers.ModelSerializer):
    rate = RateField()
    tag = optional_l10n()
    startsAt = IsoDateTimeField(source='starts_at', required=False, allow_null=True)
    endsAt = IsoDateTimeField(source='ends_at', required=False, allow_null=True)
    isActive = serializers.BooleanField(source='is_active', required=False)
    activeNow = serializers.SerializerMethodField()
    createdAt = IsoDateTimeField(source='created_at', read_only=True)

    class Meta:
        model = ItemPromo
        fields = ['id', 'rate', 'tag', 'startsAt', 'endsAt', 'isActive', 'activeNow', 'createdAt']
        read_only_fields = ['id']

    def get_activeNow(self, obj):
        from django.utils import timezone
        return obj.is_active_at(timezone.now())

    def validate(self, attrs):
        start = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        end = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if start and end and end <= start:
            raise serializers.ValidationError({'endsAt': ['позже начала']})
        return attrs


class ItemSerializer(ImmutableIdMixin, serializers.ModelSerializer):
    TEXT_FIELDS = {'title', 'meta', 'image', 'gallery', 'tag', 'description', 'features'}

    id = serializers.SlugField(max_length=60)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    outlet = serializers.PrimaryKeyRelatedField(queryset=Outlet.objects.all(), required=False, allow_null=True)
    title = L10nField()
    meta = optional_l10n()
    image = MediaUrlField()
    gallery = serializers.ListField(child=MediaUrlField(allow_null=False, allow_blank=False), required=False)
    price = serializers.IntegerField(min_value=0)
    pricing = PricingField()
    tag = optional_l10n()
    description = optional_l10n()
    features = FeaturesField(required=False)
    sortOrder = serializers.IntegerField(source='sort_order', required=False)
    isActive = serializers.BooleanField(source='is_active', required=False)
    promos = serializers.SerializerMethodField()
    requestsCount = serializers.SerializerMethodField()
    cashbackPreview = serializers.SerializerMethodField()
    updatedAt = IsoDateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Item
        fields = ['id', 'category', 'outlet', 'title', 'meta', 'image', 'gallery', 'price', 'pricing', 'tag',
                  'description', 'features', 'sortOrder', 'isActive', 'promos', 'requestsCount', 'cashbackPreview',
                  'updatedAt']

    def get_promos(self, obj):
        return ItemPromoSerializer(obj.promos.all(), many=True, context=self.context).data

    def get_requestsCount(self, obj):
        return obj.requests.count()

    def get_cashbackPreview(self, obj):
        return cashback_preview(obj)


# ---------------------------------------------------------------- уровни

def tier_ids():
    return list(Tier.objects.live().order_by('order').values_list('id', flat=True))


class TierSerializer(serializers.ModelSerializer):
    TEXT_FIELDS = {'name'}

    name = L10nField()

    class Meta:
        model = Tier
        fields = ['id', 'order', 'name', 'colors', 'medal']
        read_only_fields = ['id', 'order']

    def get_fields(self):
        fields = super().get_fields()
        # threshold — «Нынешних» за год на предыдущем уровне; from — прежнее имя поля (совместимость)
        fields['threshold'] = serializers.IntegerField(min_value=0, required=False)
        fields['from'] = serializers.IntegerField(source='threshold', min_value=0, required=False)
        fields['medal'] = MediaUrlField(required=False)
        # надбавка к кешбеку и постоянный статус (ТЗ 08.10.2026)
        fields['cashbackBonus'] = serializers.DecimalField(source='cashback_bonus', max_digits=6, decimal_places=2,
                                                           min_value=0, coerce_to_string=False, required=False)
        fields['permanentLifetime'] = serializers.IntegerField(source='permanent_lifetime', min_value=0,
                                                               allow_null=True, required=False)
        fields['permanentYears'] = serializers.IntegerField(source='permanent_years', min_value=0, required=False)
        return fields

    def validate_colors(self, value):
        from apps.loyalty.services import clean_colors
        try:
            return clean_colors(value)
        except ApiError:
            raise serializers.ValidationError('три цвета #RRGGBB')


class PrivilegeSerializer(ImmutableIdMixin, serializers.ModelSerializer):
    TEXT_FIELDS = {'title', 'short', 'description', 'footnote', 'group_title'}

    id = serializers.SlugField(max_length=40)
    tier = serializers.PrimaryKeyRelatedField(queryset=Tier.objects.all())
    group = serializers.SlugField(max_length=40, required=False, allow_blank=True)
    icon = serializers.ChoiceField(choices=PERK_ICONS)
    title = L10nField()
    short = L10nField()
    description = L10nField()
    footnote = L10nField(required=False, required_ru=False)
    groupTitle = L10nField(source='group_title', required=False, required_ru=False)
    sortOrder = serializers.IntegerField(source='sort_order', required=False)

    class Meta:
        model = Privilege
        fields = ['id', 'tier', 'group', 'groupTitle', 'icon', 'title', 'short', 'description', 'footnote', 'sortOrder']


# ---------------------------------------------------------------- контент

class PublishableSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    useRuFallback = serializers.BooleanField(source='use_ru_fallback', required=False)
    publishedAt = IsoDateTimeField(source='published_at', read_only=True)
    updatedAt = IsoDateTimeField(source='updated_at', read_only=True)
    missingTranslations = serializers.SerializerMethodField()

    PUBLISH_FIELDS = ['status', 'useRuFallback', 'publishedAt', 'updatedAt', 'missingTranslations']

    def get_missingTranslations(self, obj):
        return obj.missing_translations()


class ArticleSerializer(ImmutableIdMixin, PublishableSerializer):
    id = serializers.SlugField(max_length=80)
    image = MediaUrlField()
    tag = optional_l10n()
    title = L10nField()
    lead = optional_l10n()
    body = optional_l10n(allow_list=True)
    quote = optional_l10n(allow_null=True)
    date = serializers.DateField(required=False)
    minutes = serializers.IntegerField(min_value=1, max_value=120, required=False)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Article
        fields = ['id', 'image', 'tag', 'title', 'lead', 'body', 'quote', 'date', 'minutes', 'category',
                  *PublishableSerializer.PUBLISH_FIELDS]


class ScheduledMixin(serializers.Serializer):
    activeFrom = IsoDateTimeField(source='active_from', required=False, allow_null=True)
    activeTo = IsoDateTimeField(source='active_to', required=False, allow_null=True)
    sortOrder = serializers.IntegerField(source='sort_order', required=False)

    def validate(self, attrs):
        start = attrs.get('active_from', getattr(self.instance, 'active_from', None))
        end = attrs.get('active_to', getattr(self.instance, 'active_to', None))
        if start and end and end <= start:
            raise serializers.ValidationError({'activeTo': ['позже начала']})
        return attrs


class PromoSerializer(ScheduledMixin, PublishableSerializer):
    articleId = serializers.PrimaryKeyRelatedField(source='article', queryset=Article.objects.all())
    subtitle = L10nField()
    cta = L10nField()
    cutout = MediaUrlField()

    class Meta:
        model = Promo
        fields = ['id', 'articleId', 'subtitle', 'cta', 'cutout', 'activeFrom', 'activeTo', 'sortOrder',
                  *PublishableSerializer.PUBLISH_FIELDS]
        read_only_fields = ['id']


class EventSerializer(ScheduledMixin, PublishableSerializer):
    articleId = serializers.PrimaryKeyRelatedField(source='article', queryset=Article.objects.all())
    when = L10nField()
    place = L10nField()

    class Meta:
        model = ResortEvent
        fields = ['id', 'articleId', 'when', 'place', 'activeFrom', 'activeTo', 'sortOrder',
                  *PublishableSerializer.PUBLISH_FIELDS]
        read_only_fields = ['id']


class SlideSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    image = MediaUrlField()
    title = L10nField()
    text = optional_l10n()
    itemId = serializers.PrimaryKeyRelatedField(source='item', queryset=Item.objects.all(), required=False,
                                                allow_null=True)


def save_slides(story, slides):
    """Слайды сохраняются целиком (порядок = порядок списка); updated_at сторис растёт — мобилка сбрасывает «просмотрено»."""
    with transaction.atomic():
        story.slides.all().delete()
        for i, s in enumerate(slides):
            StorySlide.objects.create(story=story, image=s.get('image') or '', title=s.get('title') or {},
                                      text=s.get('text') or {}, item=s.get('item'), sort_order=(i + 1) * 10)
        story.save()  # auto_now → updated_at
    return story


class StorySerializer(PublishableSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    title = L10nField()
    cover = MediaUrlField()
    sortOrder = serializers.IntegerField(source='sort_order', required=False)
    slides = SlideSerializer(many=True, required=False)

    class Meta:
        model = Story
        fields = ['id', 'category', 'title', 'cover', 'sortOrder', 'slides', *PublishableSerializer.PUBLISH_FIELDS]
        read_only_fields = ['id']

    def validate_category(self, value):
        qs = Story.objects.filter(category=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('у категории уже есть сторис')
        return value

    def create(self, validated_data):
        slides = validated_data.pop('slides', None)
        story = super().create(validated_data)
        if slides is not None:
            save_slides(story, slides)
        return story

    def update(self, instance, validated_data):
        slides = validated_data.pop('slides', None)
        story = super().update(instance, validated_data)
        if slides is not None:
            save_slides(story, slides)
        return story


# ---------------------------------------------------------------- рассылки

class SegmentField(serializers.JSONField):
    def to_internal_value(self, data):
        if data in (None, ''):
            return {}
        if not isinstance(data, dict):
            raise serializers.ValidationError('Ожидается {tiers: [...], languages: [...]}')
        out = {}
        tiers = data.get('tiers') or []
        langs = data.get('languages') or []
        known = tier_ids()
        if not isinstance(tiers, list) or any(t not in known for t in tiers):
            raise serializers.ValidationError(f'tiers: {", ".join(known)}')
        if not isinstance(langs, list) or any(lang not in LANGS for lang in langs):
            raise serializers.ValidationError(f'languages: {", ".join(LANGS)}')
        if tiers:
            out['tiers'] = tiers
        if langs:
            out['languages'] = langs
        return out


class CampaignSerializer(serializers.ModelSerializer):
    title = L10nField()
    body = L10nField()
    articleId = serializers.PrimaryKeyRelatedField(source='article', queryset=Article.objects.all(), required=False,
                                                   allow_null=True)
    itemId = serializers.PrimaryKeyRelatedField(source='item', queryset=Item.objects.all(), required=False,
                                                allow_null=True)
    segment = SegmentField(required=False)
    status = serializers.CharField(read_only=True)
    scheduledAt = IsoDateTimeField(source='scheduled_at', read_only=True)
    sentAt = IsoDateTimeField(source='sent_at', read_only=True)
    createdAt = IsoDateTimeField(source='created_at', read_only=True)
    createdBy = serializers.PrimaryKeyRelatedField(source='created_by', read_only=True)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = ['id', 'title', 'body', 'articleId', 'itemId', 'segment', 'status', 'scheduledAt', 'sentAt',
                  'createdAt', 'createdBy', 'stats']
        read_only_fields = ['id']

    def get_stats(self, obj):
        from apps.notifications.services import campaign_stats
        return campaign_stats(obj) if obj.sent_at else (obj.stats or {})


class PushTemplateSerializer(serializers.ModelSerializer):
    kind = serializers.CharField(read_only=True)
    title = L10nField()
    body = L10nField()

    class Meta:
        model = PushTemplate
        fields = ['kind', 'title', 'body']


# ---------------------------------------------------------------- настройки и документы

def camel(name):
    head, *rest = name.split('_')
    return head + ''.join(p.title() for p in rest)


def snake(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


class ProgramSettingsSerializer(serializers.ModelSerializer):
    """Все поля ProgramSettings в camelCase (pointsPerSom, purgeDays, …)."""

    birthday_multiplier = serializers.DecimalField(max_digits=4, decimal_places=2, min_value=Decimal('1'),
                                                   coerce_to_string=False, required=False)
    complaint_alert_emails = serializers.ListField(child=serializers.EmailField(), required=False)
    maintenance_message = optional_l10n()
    updated_at = IsoDateTimeField(read_only=True)

    class Meta:
        model = ProgramSettings
        exclude = ['id']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        out = {camel(k): v for k, v in data.items()}
        out['birthdayMultiplier'] = float(instance.birthday_multiplier)
        return out

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('Ожидается объект')
        known = {camel(f) for f in self.fields}
        unknown = [k for k in data if k not in known]
        if unknown:
            raise serializers.ValidationError({k: ['неизвестное поле'] for k in unknown})
        return super().to_internal_value({snake(k): v for k, v in data.items()})


class LegalDocumentSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(choices=LegalKind.choices)
    version = serializers.CharField(max_length=20)
    url = L10nField()
    requiresAcceptance = serializers.BooleanField(source='requires_acceptance', required=False)
    publishedAt = IsoDateTimeField(source='published_at', read_only=True)
    createdAt = IsoDateTimeField(source='created_at', read_only=True)
    isCurrent = serializers.SerializerMethodField()

    class Meta:
        model = LegalDocument
        fields = ['id', 'kind', 'version', 'url', 'requiresAcceptance', 'publishedAt', 'createdAt', 'isCurrent']
        read_only_fields = ['id']

    def get_isCurrent(self, obj):
        current = LegalDocument.current(obj.kind)
        return bool(current and current.pk == obj.pk)

    def validate(self, attrs):
        kind = attrs.get('kind', getattr(self.instance, 'kind', None))
        version = attrs.get('version', getattr(self.instance, 'version', None))
        qs = LegalDocument.objects.filter(kind=kind, version=version)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({'version': ['такая версия уже есть']})
        return attrs


# ---------------------------------------------------------------- сотрудники

class StaffSerializer(serializers.ModelSerializer):
    """Директор — email обязателен; администратор кассы — телефон и хотя бы одна точка (PIN — отдельным полем)."""

    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    fullName = serializers.CharField(source='full_name', max_length=150)
    role = serializers.ChoiceField(choices=Role.choices)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    outletIds = serializers.PrimaryKeyRelatedField(source='outlets', queryset=Outlet.objects.all(), many=True,
                                                   required=False)
    isActive = serializers.BooleanField(source='is_active', read_only=True)
    totpEnabled = serializers.BooleanField(source='totp_enabled', read_only=True)
    pinSet = serializers.SerializerMethodField()
    lastLogin = IsoDateTimeField(source='last_login', read_only=True)
    createdAt = IsoDateTimeField(source='created_at', read_only=True)

    class Meta:
        model = StaffUser
        fields = ['id', 'email', 'fullName', 'role', 'phone', 'outletIds', 'isActive', 'totpEnabled', 'pinSet',
                  'lastLogin', 'createdAt']
        read_only_fields = ['id']

    def get_pinSet(self, obj):
        return bool(obj.pin_hash)

    def validate(self, attrs):
        role = attrs.get('role', getattr(self.instance, 'role', None))
        email = attrs.get('email', getattr(self.instance, 'email', None))
        phone = attrs.get('phone', getattr(self.instance, 'phone', ''))
        outlets = attrs['outlets'] if 'outlets' in attrs else (
            list(self.instance.outlets.all()) if self.instance is not None else [])
        if role == Role.STAFF:
            if not phone:
                raise serializers.ValidationError({'phone': ['администратор входит по телефону']})
            if not outlets:
                raise serializers.ValidationError({'outletIds': ['хотя бы одна точка']})
        elif not email:
            raise serializers.ValidationError({'email': ['директор входит по email']})
        return attrs

    def validate_email(self, value):
        value = (value or '').strip().lower()
        if not value:
            return None
        qs = StaffUser.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('уже используется')
        return value

    def validate_phone(self, value):
        if not value:
            return ''
        from apps.common.errors import ApiError
        from apps.members.auth import normalize_phone
        try:
            value = normalize_phone(value)
        except ApiError:
            raise serializers.ValidationError('неверный номер')
        qs = StaffUser.objects.filter(phone=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('уже используется')
        return value


def staff_brief(user):
    return {'id': user.pk, 'fullName': user.full_name, 'role': user.role} if user else None


# ---------------------------------------------------------------- обращения

class ComplaintCategorySerializer(ImmutableIdMixin, serializers.ModelSerializer):
    id = serializers.SlugField(max_length=30)
    title = L10nField()
    sortOrder = serializers.IntegerField(source='sort_order', required=False)
    isActive = serializers.BooleanField(source='is_active', required=False)

    class Meta:
        model = ComplaintCategory
        fields = ['id', 'title', 'sortOrder', 'isActive']


class ReplyTemplateSerializer(serializers.ModelSerializer):
    title = serializers.CharField(max_length=120)
    text = L10nField()
    category = serializers.PrimaryKeyRelatedField(queryset=ComplaintCategory.objects.all(), required=False,
                                                  allow_null=True)
    sortOrder = serializers.IntegerField(source='sort_order', required=False)

    class Meta:
        model = ReplyTemplate
        fields = ['id', 'title', 'text', 'category', 'sortOrder']
        read_only_fields = ['id']
