"""
Формы панели. Локализуемые поля — {ru, ky, en}: виджет с тремя вкладками (L10nField).
Для роли «Редактор» поля правил/цен/порогов блокируются (disabled) — сервер игнорирует их ввод.
"""
import json
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from apps.catalog.models import FEATURE_ICONS, Category, Item, ItemPromo, Outlet, PaymentMethod
from apps.common.i18n import LANGS
from apps.common.models import ProgramSettings
from apps.complaints.models import ComplaintCategory, ReplyTemplate
from apps.content.models import Article, Promo, ResortEvent, Story
from apps.loyalty.models import PERK_ICONS, Privilege, Tier
from apps.members.models import Language, LegalDocument
from apps.notifications.models import Campaign, PushTemplate
from apps.staff.models import StaffUser
from apps.staff.roles import Role

LANG_LABELS = {'ru': 'RU', 'ky': 'KY', 'en': 'EN'}


# ---------------------------------------------------------------- локализуемые поля

class L10nWidget(forms.MultiWidget):
    template_name = 'panel/widgets/l10n.html'

    def __init__(self, textarea=False, rows=3, paragraphs=False, attrs=None):
        self.textarea = textarea
        self.paragraphs = paragraphs
        widgets = {}
        for lang in LANGS:
            if textarea:
                widgets[lang] = forms.Textarea(attrs={'rows': rows, 'lang': lang})
            else:
                widgets[lang] = forms.TextInput(attrs={'lang': lang})
        super().__init__(widgets, attrs)

    def decompress(self, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = {'ru': value}
        if not isinstance(value, dict):
            return ['' for _ in LANGS]
        out = []
        for lang in LANGS:
            v = value.get(lang) or ''
            if isinstance(v, list):
                v = '\n\n'.join(v)
            out.append(v)
        return out

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        for sub, lang in zip(ctx['widget']['subwidgets'], LANGS):
            sub['lang'] = lang
            sub['lang_label'] = LANG_LABELS[lang]
            sub['empty'] = not (sub.get('value') or '').strip()
        ctx['widget']['field_name'] = name
        return ctx


class L10nField(forms.MultiValueField):
    def __init__(self, required=True, textarea=False, rows=3, paragraphs=False, max_length=None, empty_none=False,
                 **kwargs):
        self.ru_required = required
        self.paragraphs = paragraphs
        self.empty_none = empty_none
        fields = [forms.CharField(required=False, max_length=max_length, strip=True) for _ in LANGS]
        kwargs.setdefault('widget', L10nWidget(textarea=textarea, rows=rows, paragraphs=paragraphs))
        super().__init__(fields=fields, required=False, require_all_fields=False, **kwargs)

    def compress(self, data_list):
        data_list = list(data_list or ['' for _ in LANGS])
        out = {}
        for lang, text in zip(LANGS, data_list):
            text = (text or '').strip()
            if self.paragraphs:
                out[lang] = [p.strip() for p in text.replace('\r\n', '\n').split('\n\n') if p.strip()]
            else:
                out[lang] = text
        if not any(out.values()):
            return None if self.empty_none else {}
        return out

    def clean(self, value):
        result = super().clean(value)
        if self.ru_required and not (result or {}).get('ru'):
            raise ValidationError('Обязателен русский вариант')
        return result


class JSONListField(forms.CharField):
    """Скрытое поле с JSON-массивом (галерея, «что входит», слайды) — редактируется JS-компонентом."""

    widget = forms.HiddenInput

    def prepare_value(self, value):
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return value

    def to_python(self, value):
        if value in (None, ''):
            return []
        if isinstance(value, list):
            return value
        try:
            data = json.loads(value)
        except ValueError:
            raise ValidationError('Неверные данные')
        if not isinstance(data, list):
            raise ValidationError('Ожидается список')
        return data


class CSVListField(forms.CharField):
    def __init__(self, *args, cast=str, **kwargs):
        self.cast = cast
        kwargs.setdefault('required', False)
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, list):
            return ', '.join(str(v) for v in value)
        return value

    def to_python(self, value):
        if not value:
            return []
        if isinstance(value, list):
            return value
        try:
            return [self.cast(v.strip()) for v in str(value).split(',') if v.strip()]
        except ValueError:
            raise ValidationError('Список через запятую')


class DateTimeLocal(forms.DateTimeInput):
    input_type = 'datetime-local'

    def __init__(self, attrs=None):
        super().__init__(attrs, format='%Y-%m-%dT%H:%M')


class DateInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, attrs=None):
        super().__init__(attrs, format='%Y-%m-%d')


class IconGrid(forms.RadioSelect):
    """Выбор иконки из сетки с превью (не выпадающий список)."""

    template_name = 'panel/widgets/icon_grid.html'
    option_template_name = 'panel/widgets/icon_option.html'


def dt_field(label, required=False):
    return forms.DateTimeField(label=label, required=required, widget=DateTimeLocal(),
                               input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'])


class PanelForm:
    """Помощник: заблокировать поля, недоступные роли."""

    def lock(self, names):
        for n in names:
            if n in self.fields:
                self.fields[n].disabled = True
                self.fields[n].widget.attrs['data-locked'] = '1'


# ---------------------------------------------------------------- каталог

class CategoryForm(PanelForm, forms.ModelForm):
    title = L10nField(label='Название')
    methods = forms.MultipleChoiceField(label='Способы доплаты', choices=PaymentMethod.choices,
                                        widget=forms.CheckboxSelectMultiple, required=False)
    rate = forms.DecimalField(label='Кешбек, доля (0.07 = 7 %)', min_value=Decimal('0'), max_value=Decimal('1'),
                              decimal_places=4)
    max_points_share = forms.DecimalField(label='Оплата баллами, доля', min_value=Decimal('0'),
                                          max_value=Decimal('1'), decimal_places=4)

    class Meta:
        model = Category
        fields = ['title', 'cover', 'sort_order', 'is_active', 'rate', 'max_points_share', 'methods']
        widgets = {'cover': forms.HiddenInput}
        labels = {'sort_order': 'Порядок', 'is_active': 'Показывать в приложении'}

    RULE_FIELDS = ['sort_order', 'is_active', 'rate', 'max_points_share', 'methods']


class ItemForm(PanelForm, forms.ModelForm):
    id = forms.SlugField(label='Slug (id)', max_length=60,
                         help_text='Стабильный: на него ссылаются заявки, история и сторис')
    title = L10nField(label='Название', max_length=120)
    meta = L10nField(label='Короткая строка', required=False, max_length=160)
    tag = L10nField(label='Бейдж', required=False, max_length=40)
    description = L10nField(label='Описание', required=False, textarea=True, rows=4)
    gallery = JSONListField(required=False)
    features = JSONListField(required=False)
    pricing_type = forms.ChoiceField(label='Тип цены', choices=[('unit', 'За единицу'), ('check', 'По чеку')],
                                     widget=forms.RadioSelect)
    pricing_unit = forms.ChoiceField(label='Единица', choices=[(u, lbl) for u, lbl in [
        ('night', 'ночь'), ('session', 'сеанс'), ('guest', 'гость'), ('hour', 'час'), ('visit', 'посещение')]],
        required=False)
    pricing_min = forms.IntegerField(label='Мин.', min_value=1, initial=1)
    pricing_max = forms.IntegerField(label='Макс.', min_value=1, initial=10)

    class Meta:
        model = Item
        fields = ['id', 'category', 'outlet', 'title', 'meta', 'image', 'gallery', 'price', 'tag', 'description',
                  'features', 'sort_order', 'is_active']
        widgets = {'image': forms.HiddenInput}
        labels = {'category': 'Раздел', 'outlet': 'Точка обслуживания', 'price': 'Цена, сом',
                  'sort_order': 'Порядок', 'is_active': 'Показывать в приложении'}

    RULE_FIELDS = ['id', 'category', 'outlet', 'price', 'pricing_type', 'pricing_unit', 'pricing_min', 'pricing_max',
                   'sort_order', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst and inst.pk:
            self.fields['id'].disabled = True
            p = inst.pricing or {}
            self.initial.setdefault('pricing_type', p.get('type', 'unit'))
            self.initial.setdefault('pricing_unit', p.get('unit', 'visit'))
            lo, hi = inst.pricing_bounds()
            self.initial.setdefault('pricing_min', lo)
            self.initial.setdefault('pricing_max', hi)
        else:
            self.initial.setdefault('pricing_type', 'unit')
        self.fields['outlet'].required = False

    def clean_id(self):
        v = self.cleaned_data['id']
        if not (self.instance and self.instance.pk) and Item.objects.filter(pk=v).exists():
            raise ValidationError('Такой slug уже есть')
        return v

    def clean_features(self):
        out = []
        for f in self.cleaned_data.get('features') or []:
            if not isinstance(f, dict):
                continue
            icon = f.get('icon')
            if icon not in FEATURE_ICONS:
                raise ValidationError(f'Неизвестная иконка: {icon}')
            text = f.get('text') or {}
            out.append({'icon': icon, 'text': {lang: str(text.get(lang) or '').strip() for lang in LANGS}})
        return out

    def clean_gallery(self):
        return [str(x) for x in (self.cleaned_data.get('gallery') or []) if x]

    def clean(self):
        data = super().clean()
        lo, hi = data.get('pricing_min'), data.get('pricing_max')
        if lo and hi and lo > hi:
            self.add_error('pricing_max', 'Максимум меньше минимума')
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        d = self.cleaned_data
        if not self.fields['pricing_type'].disabled:
            if d['pricing_type'] == 'check':
                obj.pricing = {'type': 'check', 'min': d['pricing_min'], 'max': d['pricing_max']}
            else:
                obj.pricing = {'type': 'unit', 'unit': d.get('pricing_unit') or 'visit', 'min': d['pricing_min'],
                               'max': d['pricing_max']}
        if commit:
            obj.save()
        return obj


class PromoRateForm(forms.ModelForm):
    tag = L10nField(label='Бейдж акции', required=False, max_length=40)
    starts_at = dt_field('Начало')
    ends_at = dt_field('Конец')

    class Meta:
        model = ItemPromo
        fields = ['rate', 'tag', 'starts_at', 'ends_at']
        labels = {'rate': 'Ставка (0.14 = 14 %)'}

    def clean(self):
        d = super().clean()
        if d.get('starts_at') and d.get('ends_at') and d['ends_at'] <= d['starts_at']:
            self.add_error('ends_at', 'Конец раньше начала')
        return d


# ---------------------------------------------------------------- уровни

class TierForm(PanelForm, forms.ModelForm):
    name = L10nField(label='Название', max_length=40)

    class Meta:
        model = Tier
        fields = ['name', 'threshold']
        labels = {'threshold': 'Порог: «Нынешних» за год на предыдущем уровне'}


def tier_choices():
    from apps.common.i18n import tr
    return [(t.pk, tr(t.name, 'ru')) for t in Tier.objects.live().order_by('order')]


COLOR = forms.TextInput(attrs={'type': 'color', 'class': 'color-input'})


class TierStyleForm(PanelForm, forms.Form):
    """Новый уровень или оформление существующего: название, порог (для нового), градиент, медаль."""

    name = L10nField(label='Название', max_length=40)
    threshold = forms.IntegerField(label='Порог: «Нынешних» за год на предыдущем уровне', min_value=1,
                                   required=False)
    color0 = forms.RegexField(label='Цвет 1 (тёмный)', regex=r'^#[0-9A-Fa-f]{6}$', widget=COLOR)
    color1 = forms.RegexField(label='Цвет 2 (средний)', regex=r'^#[0-9A-Fa-f]{6}$', widget=COLOR)
    color2 = forms.RegexField(label='Цвет 3 (светлый)', regex=r'^#[0-9A-Fa-f]{6}$', widget=COLOR)
    medal = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, creating=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['threshold'].required = creating
        if not creating:
            del self.fields['threshold']

    @property
    def colors(self):
        return [self.cleaned_data[f'color{i}'].upper() for i in range(3)]


class PrivilegeForm(PanelForm, forms.ModelForm):
    id = forms.SlugField(label='Id', max_length=40)
    icon = forms.ChoiceField(label='Иконка', choices=[(i, i) for i in PERK_ICONS], widget=IconGrid)
    title = L10nField(label='Название', max_length=80)
    short = L10nField(label='Коротко (1–2 слова)', max_length=30)
    description = L10nField(label='Описание', textarea=True, rows=3)

    class Meta:
        model = Privilege
        fields = ['id', 'tier', 'icon', 'title', 'short', 'description', 'sort_order']
        labels = {'tier': 'Уровень', 'sort_order': 'Порядок'}

    RULE_FIELDS = ['id', 'tier', 'icon', 'sort_order']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['id'].disabled = True

    def clean_id(self):
        v = self.cleaned_data['id']
        if not (self.instance and self.instance.pk) and Privilege.objects.filter(pk=v).exists():
            raise ValidationError('Такой id уже есть')
        return v


# ---------------------------------------------------------------- контент

class PublishableForm(forms.ModelForm):
    pass


from apps.common.text import slug_from_title  # noqa: E402


class ArticleForm(PublishableForm):
    id = forms.SlugField(label='Slug (id)', max_length=80, required=False,
                         help_text='Латиницей, для диплинков. Оставьте пустым — создастся из заголовка')
    tag = L10nField(label='Тег', required=False, max_length=40)
    title = L10nField(label='Заголовок', max_length=160)
    lead = L10nField(label='Подзаголовок', required=False, textarea=True, rows=2)
    body = L10nField(label='Абзацы (разделяйте пустой строкой)', required=False, textarea=True, rows=8,
                     paragraphs=True)
    quote = L10nField(label='Цитата', required=False, textarea=True, rows=2, empty_none=True)

    class Meta:
        model = Article
        fields = ['id', 'image', 'tag', 'title', 'lead', 'body', 'quote', 'date', 'minutes', 'category',
                  'use_ru_fallback']
        widgets = {'image': forms.HiddenInput, 'date': DateInput}
        labels = {'date': 'Дата', 'minutes': 'Время чтения, мин', 'category': 'Кнопка «В каталог»',
                  'use_ru_fallback': 'Использовать ru вместо пустых переводов'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['id'].disabled = True
        self.fields['category'].required = False

    def clean_id(self):
        v = self.cleaned_data['id']
        if self.instance and self.instance.pk:
            return self.instance.pk
        if v and Article.objects.filter(pk=v).exists():
            raise ValidationError('Такой slug уже есть')
        return v

    def clean(self):
        data = super().clean()
        if not (self.instance and self.instance.pk) and not data.get('id'):
            data['id'] = slug_from_title((data.get('title') or {}).get('ru'), Article, fallback='article')
            self.instance.pk = data['id']
        return data


class PromoForm(PublishableForm):
    subtitle = L10nField(label='Подпись', max_length=120)
    cta = L10nField(label='Текст кнопки', max_length=30)
    active_from = dt_field('Показывать с')
    active_to = dt_field('Показывать до')

    class Meta:
        model = Promo
        fields = ['article', 'subtitle', 'cta', 'cutout', 'active_from', 'active_to', 'sort_order', 'use_ru_fallback']
        widgets = {'cutout': forms.HiddenInput}
        labels = {'article': 'Статья', 'sort_order': 'Порядок',
                  'use_ru_fallback': 'Использовать ru вместо пустых переводов'}


class EventForm(PublishableForm):
    when = L10nField(label='Когда', max_length=60)
    place = L10nField(label='Где', max_length=60)
    active_from = dt_field('Показывать с')
    active_to = dt_field('Показывать до')

    class Meta:
        model = ResortEvent
        fields = ['article', 'when', 'place', 'active_from', 'active_to', 'sort_order', 'use_ru_fallback']
        labels = {'article': 'Статья', 'sort_order': 'Порядок',
                  'use_ru_fallback': 'Использовать ru вместо пустых переводов'}


class StoryForm(PublishableForm):
    title = L10nField(label='Заголовок', max_length=60)
    slides = JSONListField(required=False)

    class Meta:
        model = Story
        fields = ['category', 'title', 'cover', 'sort_order', 'use_ru_fallback']
        widgets = {'cover': forms.HiddenInput}
        labels = {'category': 'Раздел каталога', 'sort_order': 'Порядок',
                  'use_ru_fallback': 'Использовать ru вместо пустых переводов'}

    def clean_slides(self):
        from apps.catalog.models import Item as _Item
        out = []
        for s in self.cleaned_data.get('slides') or []:
            if not isinstance(s, dict):
                continue
            item_id = s.get('item') or None
            if item_id and not _Item.objects.filter(pk=item_id).exists():
                raise ValidationError(f'Услуга {item_id} не найдена')
            out.append({
                'image': str(s.get('image') or ''),
                'title': {lang: str((s.get('title') or {}).get(lang) or '').strip() for lang in LANGS},
                'text': {lang: str((s.get('text') or {}).get(lang) or '').strip() for lang in LANGS},
                'item': item_id,
            })
        return out


# ---------------------------------------------------------------- рассылки

class CampaignForm(forms.ModelForm):
    title = L10nField(label='Заголовок', max_length=80)
    body = L10nField(label='Текст', textarea=True, rows=3, max_length=240)
    tiers = forms.MultipleChoiceField(label='Уровни', choices=(), required=False,
                                      widget=forms.CheckboxSelectMultiple)
    languages = forms.MultipleChoiceField(label='Языки', choices=Language.choices, required=False,
                                          widget=forms.CheckboxSelectMultiple)
    scheduled_at = dt_field('Отправить в')

    class Meta:
        model = Campaign
        fields = ['title', 'body', 'article', 'item', 'scheduled_at']
        labels = {'article': 'Ссылка на статью', 'item': 'Ссылка на услугу'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tiers'].choices = tier_choices()
        seg = (self.instance.segment or {}) if self.instance else {}
        self.initial.setdefault('tiers', seg.get('tiers') or [])
        self.initial.setdefault('languages', seg.get('languages') or [])
        self.fields['article'].required = False
        self.fields['item'].required = False

    def clean(self):
        d = super().clean()
        if d.get('article') and d.get('item'):
            raise ValidationError('Укажите либо статью, либо услугу')
        return d

    def save(self, commit=True):
        obj = super().save(commit=False)
        seg = {}
        if self.cleaned_data.get('tiers'):
            seg['tiers'] = self.cleaned_data['tiers']
        if self.cleaned_data.get('languages'):
            seg['languages'] = self.cleaned_data['languages']
        obj.segment = seg
        if commit:
            obj.save()
        return obj


class PushTemplateForm(forms.ModelForm):
    title = L10nField(label='Заголовок', max_length=80)
    body = L10nField(label='Текст', textarea=True, rows=2, max_length=240)

    class Meta:
        model = PushTemplate
        fields = ['title', 'body']


class ReplyTemplateForm(forms.ModelForm):
    text = L10nField(label='Текст', textarea=True, rows=4)

    class Meta:
        model = ReplyTemplate
        fields = ['title', 'category', 'text', 'sort_order']
        labels = {'title': 'Название', 'category': 'Тема', 'sort_order': 'Порядок'}


class ComplaintCategoryForm(forms.ModelForm):
    title = L10nField(label='Название')

    class Meta:
        model = ComplaintCategory
        fields = ['id', 'title', 'sort_order', 'is_active']
        labels = {'id': 'Код (латиница)', 'sort_order': 'Порядок', 'is_active': 'Показывать клиентам'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # код стабилен: на него ссылаются обращения и аналитика
            self.fields['id'].disabled = True


# ---------------------------------------------------------------- настройки

class ProgramSettingsForm(forms.ModelForm):
    complaint_alert_emails = CSVListField(label='Email для уведомлений об обращениях')
    maintenance_message = L10nField(label='Текст о техработах', required=False, textarea=True, rows=2)

    class Meta:
        model = ProgramSettings
        exclude = ['test_enabled', 'test_phone', 'test_code', 'resort_phone', 'resort_whatsapp', 'resort_maps_url']
        widgets = {'quiet_hours_start': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
                   'quiet_hours_end': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')}

    GROUPS = [
        ('Курс и кешбек', ['points_per_som', 'birthday_multiplier', 'birthday_days_before', 'birthday_days_after']),
        ('Жизненный цикл заявки', ['auto_confirm', 'auto_confirm_cash', 'confirm_delay_ms', 'credit_delay_ms',
                                   'pending_ttl_hours', 'staff_adjust_threshold_percent',
                                   'staff_cashback_limit_points']),
        ('Удаление аккаунта', ['purge_days']),
        ('Вход по SMS', ['otp_length', 'otp_ttl_seconds', 'otp_retry_seconds', 'otp_max_attempts',
                         'otp_per_phone_day', 'otp_per_ip_hour', 'min_age']),
        ('Приложение', ['min_version_ios', 'min_version_android', 'maintenance', 'maintenance_message']),
        ('Уведомления', ['promo_push_monthly_limit', 'quiet_hours_start', 'quiet_hours_end',
                         'notification_retention_days']),
        ('Обращения', ['complaint_first_response_hours', 'complaint_daily_limit', 'complaint_alert_emails']),
        ('Прочее', ['member_qr_ttl_seconds', 'analytics_raw_retention_days']),
    ]

    def groups(self):
        return [(title, [self[n] for n in names if n in self.fields]) for title, names in self.GROUPS]


class ContactsForm(forms.ModelForm):
    class Meta:
        model = ProgramSettings
        fields = ['resort_phone', 'resort_whatsapp', 'resort_maps_url']


class StoreTestForm(forms.ModelForm):
    class Meta:
        model = ProgramSettings
        fields = ['test_enabled', 'test_phone', 'test_code']


class OutletForm(forms.ModelForm):
    id = forms.SlugField(label='Id', max_length=40)
    name = L10nField(label='Название', max_length=60)

    class Meta:
        model = Outlet
        fields = ['id', 'name', 'sort_order', 'is_active']
        labels = {'sort_order': 'Порядок', 'is_active': 'Активна'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['id'].disabled = True

    def clean_id(self):
        v = self.cleaned_data['id']
        if not (self.instance and self.instance.pk) and Outlet.objects.filter(pk=v).exists():
            raise ValidationError('Такой id уже есть')
        return v


class LegalForm(forms.ModelForm):
    url = L10nField(label='URL документа')
    published_at = dt_field('Опубликовать с')

    class Meta:
        model = LegalDocument
        fields = ['kind', 'version', 'url', 'requires_acceptance', 'published_at']
        labels = {'kind': 'Документ', 'version': 'Версия', 'requires_acceptance': 'Требует повторного согласия'}


class StaffUserForm(forms.ModelForm):
    password = forms.CharField(label='Пароль', required=False, widget=forms.PasswordInput(render_value=False),
                               help_text='Для нового сотрудника обязателен; для существующего — оставьте пустым')
    outlets = forms.ModelMultipleChoiceField(label='Точки', queryset=Outlet.objects.all(), required=False,
                                             widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = StaffUser
        fields = ['email', 'full_name', 'role', 'phone', 'outlets', 'is_active']
        labels = {'is_active': 'Активен'}

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        qs = StaffUser.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Сотрудник с таким email уже есть')
        return email

    def clean(self):
        d = super().clean()
        if not self.instance.pk and not d.get('password'):
            self.add_error('password', 'Задайте пароль')
        pw = d.get('password')
        if pw:
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(pw, self.instance)
            except ValidationError as e:
                self.add_error('password', e)
        if d.get('role') == Role.STAFF and not d.get('outlets'):
            self.add_error('outlets', 'Сотруднику нужна хотя бы одна точка')
        return d

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('password'):
            user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            self.save_m2m()
        return user


# ---------------------------------------------------------------- клиенты / заявки

class AdjustPointsForm(forms.Form):
    points = forms.IntegerField(label='Баллы (со знаком)')
    comment = forms.CharField(label='Комментарий (клиент увидит)', max_length=500, widget=forms.Textarea(
        attrs={'rows': 2}))

    def clean_points(self):
        v = self.cleaned_data['points']
        if v == 0:
            raise ValidationError('Не может быть 0')
        return v


class BirthdayForm(forms.Form):
    birthday = forms.DateField(label='Дата рождения', widget=DateInput, required=False)


class LoginForm(forms.Form):
    email = forms.EmailField(label='Email', widget=forms.EmailInput(attrs={'autocomplete': 'username',
                                                                          'autofocus': True}))
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))


class TotpForm(forms.Form):
    code = forms.CharField(label='Код из приложения', max_length=8, widget=forms.TextInput(attrs={
        'autocomplete': 'one-time-code', 'inputmode': 'numeric', 'autofocus': True, 'pattern': '[0-9 ]*'}))


class PasswordChangeForm(forms.Form):
    current = forms.CharField(label='Текущий пароль', widget=forms.PasswordInput(attrs={
        'autocomplete': 'current-password', 'autofocus': True}))
    new = forms.CharField(label='Новый пароль', min_length=8, widget=forms.PasswordInput(attrs={
        'autocomplete': 'new-password'}))
    new2 = forms.CharField(label='Повторите новый пароль', widget=forms.PasswordInput(attrs={
        'autocomplete': 'new-password'}))

    def clean(self):
        d = super().clean()
        if d.get('new') and d.get('new2') and d['new'] != d['new2']:
            self.add_error('new2', 'Пароли не совпадают')
        return d
