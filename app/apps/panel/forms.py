"""
Формы панели. Локализуемые поля — {ru, ky, en}: виджет с тремя вкладками (L10nField).
Для роли «Редактор» поля правил/цен/порогов блокируются (disabled) — сервер игнорирует их ввод.
"""
import json
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from apps.catalog.models import (ACTIVE_METHOD_CHOICES, DEFAULT_VENUE, FEATURE_ICONS, AppRelease, Category, EternalNews,
                                 Item, ItemPromo, NewsItem, Outlet, PaymentMethod, Season, Showcase, Promotion, PromotionAudience, PromotionKind, PromotionScope, Section,
                                 Venue)
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


def modes_field(label, help_text=''):
    return forms.MultipleChoiceField(label=label, required=False, help_text=help_text,
                                     widget=forms.CheckboxSelectMultiple,
                                     choices=[(v.pk, str(v)) for v in Venue.objects.all()])


class ModesFormMixin:
    """Поле «Режимы» (ТЗ экосистемы): в каких приложениях / режимах показывать запись."""

    modes_label = 'Показывать в режимах'
    modes_help = ''
    modes_default = None

    def add_modes_field(self):
        self.fields['modes'] = modes_field(self.modes_label, self.modes_help)
        current = getattr(self.instance, 'modes', None)
        self.initial['modes'] = current if self.instance.pk else (self.modes_default or current or [])

    def apply_modes(self):
        if 'modes' in self.cleaned_data and not self.fields['modes'].disabled:
            self.instance.modes = self.cleaned_data['modes'] or list(self.modes_default or [])



# ---------------------------------------------------------------- каталог

class CategoryForm(PanelForm, forms.ModelForm):
    title = L10nField(label='Название')
    methods = forms.MultipleChoiceField(label='Способы доплаты', choices=ACTIVE_METHOD_CHOICES,
                                        widget=forms.CheckboxSelectMultiple, required=False)

    class Meta:
        model = Category
        fields = ['title', 'cover', 'sort_order', 'is_active', 'methods']
        widgets = {'cover': forms.HiddenInput}
        labels = {'sort_order': 'Порядок', 'is_active': 'Показывать в приложении'}

    RULE_FIELDS = ['sort_order', 'is_active', 'methods']


class VenueForm(PanelForm, forms.ModelForm):
    """Объект экосистемы: тексты, контакты и инфоблоки (трассы, как добраться, сезон…)."""

    name = L10nField(label='Название', max_length=80)
    short = L10nField(label='Подзаголовок', required=False, max_length=160)
    description = L10nField(label='Описание', required=False, textarea=True, rows=4)
    address = L10nField(label='Адрес', required=False, max_length=300)
    contacts = forms.JSONField(label='Контакты (JSON)', required=False, widget=forms.Textarea(attrs={'rows': 8}),
                               help_text='[{"label": {"ru": "Ресепшен"}, "phone": "+996 …", "whatsapp": true, "email": ""}]')
    info = forms.JSONField(label='Инфоблоки (JSON)', required=False, widget=forms.Textarea(attrs={'rows': 12}),
                           help_text='[{"title": {"ru": "Как добраться"}, "text": {"ru": "…"}}] или '
                                     '{"title": …, "rows": [{"label": {"ru": …}, "value": {"ru": …}}]}')

    class Meta:
        model = Venue
        fields = ['name', 'short', 'description', 'address', 'cover', 'phone', 'whatsapp', 'email', 'maps_url',
                  'two_gis_url', 'is_open', 'early_booking_enabled', 'accent', 'contacts', 'info', 'sort_order',
                  'is_active']
        widgets = {'cover': forms.HiddenInput, 'accent': forms.TextInput(attrs={'type': 'color'})}
        labels = {'sort_order': 'Порядок', 'is_active': 'Показывать'}

    def clean_contacts(self):
        v = self.cleaned_data.get('contacts') or []
        if not isinstance(v, list) or not all(isinstance(c, dict) for c in v):
            raise ValidationError('Нужен список объектов')
        return v

    def clean_info(self):
        v = self.cleaned_data.get('info') or []
        if not isinstance(v, list) or not all(isinstance(b, dict) and b.get('title') for b in v):
            raise ValidationError('Нужен список блоков с title')
        return v


class SeasonForm(forms.ModelForm):
    """Сезон S&K: по датам сервер переключает приложение между Ski и Kymyz (ТЗ экосистемы §4.1)."""

    class Meta:
        model = Season
        fields = ['year', 'starts_at', 'ends_at', 'early_booking_from', 'off_season_mode']
        widgets = {'starts_at': DateInput(), 'ends_at': DateInput(), 'early_booking_from': DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['off_season_mode'].queryset = Venue.objects.filter(app='sk')
        self.fields['off_season_mode'].required = False

    def clean(self):
        data = super().clean()
        if data.get('starts_at') and data.get('ends_at') and data['ends_at'] < data['starts_at']:
            raise ValidationError('Конец сезона раньше начала')
        return data


SeasonFormSet = forms.inlineformset_factory(Venue, Season, form=SeasonForm, fk_name='venue', extra=1, can_delete=True)


def _json_list(value, need=None):
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise ValidationError('Нужен список объектов')
    for x in value:
        for key in need or ():
            if not x.get(key):
                raise ValidationError(f'У каждого элемента нужно поле {key}')
    return value


class ShowcaseForm(PanelForm, forms.ModelForm):
    """Главная режима (ТЗ §7.2): шапка, факты, кнопка, плитки разделов."""

    cta = L10nField(label='Текст кнопки', required=False, max_length=40)
    facts = forms.JSONField(label='Факты (JSON)', required=False, widget=forms.Textarea(attrs={'rows': 4}),
                            help_text='[{"ru": "3 000 м", "ky": "…", "en": "…"}, …] — в порядке показа')
    tiles = forms.JSONField(label='Плитки (JSON)', required=False, widget=forms.Textarea(attrs={'rows': 8}),
                            help_text='[{"section": "skipass", "icon": "skipass", "title": {"ru": "Скипасс"}}] — '
                                      'порядок в списке = порядок в приложении')

    class Meta:
        model = Showcase
        fields = ['hero_image', 'hero_image_night', 'facts', 'cta', 'cta_section', 'tiles']
        widgets = {'hero_image': forms.HiddenInput, 'hero_image_night': forms.HiddenInput}

    def __init__(self, *args, sections=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.section_keys = [k for k, _ in sections]
        self.fields['cta_section'] = forms.ChoiceField(label='Кнопка ведёт в раздел', required=False,
                                                       choices=[('', '—')] + list(sections))

    def clean_facts(self):
        v = self.cleaned_data.get('facts') or []
        if not isinstance(v, list) or not all(isinstance(f, dict) and f.get('ru') for f in v):
            raise ValidationError('Нужен список вида [{"ru": "…"}]')
        return v

    def clean_tiles(self):
        from apps.catalog.models import SHOWCASE_ICONS
        v = _json_list(self.cleaned_data.get('tiles') or [], need=('section', 'title'))
        for t in v:
            if t['section'] not in self.section_keys:
                raise ValidationError(f'Нет раздела {t["section"]}')
            if t.get('icon') and t['icon'] not in SHOWCASE_ICONS:
                raise ValidationError(f'Иконка {t["icon"]} не из справочника: {", ".join(SHOWCASE_ICONS)}')
        return v


class NewsItemForm(forms.ModelForm):
    title = L10nField(label='Заголовок', required=False, max_length=120)
    when = L10nField(label='Когда (текст)', required=False, max_length=60)
    place = L10nField(label='Место', required=False, max_length=80)

    class Meta:
        model = NewsItem
        fields = ['title', 'when', 'date', 'place', 'image', 'article_id', 'sort_order', 'is_active']
        widgets = {'date': DateInput(), 'image': forms.HiddenInput}
        labels = {'sort_order': 'Порядок', 'article_id': 'Статья (id)'}

    def clean(self):
        data = super().clean()
        if not self.cleaned_data.get('DELETE') and self.has_changed() and not (data.get('title') or {}).get('ru'):
            self.add_error('title', 'Обязателен русский вариант')
        return data


NewsFormSet = forms.inlineformset_factory(Venue, NewsItem, form=NewsItemForm, extra=1, can_delete=True)


class EternalNewsForm(PanelForm, forms.ModelForm):
    """«Вечная новость» (ТЗ §7.2): рассказ о другом сезоне S&K со слайдами и бонусом за раннюю бронь."""

    title = L10nField(label='Заголовок', max_length=120)
    lead = L10nField(label='Подводка', required=False, textarea=True, rows=3)
    show_in = forms.MultipleChoiceField(label='Показывать в режимах', widget=forms.CheckboxSelectMultiple)
    slides = forms.JSONField(label='Слайды (JSON)', required=False, widget=forms.Textarea(attrs={'rows': 12}),
                             help_text='[{"image": "…", "title": {"ru": …}, "text": {"ru": …}, "cta": {"label": '
                                       '{"ru": "Забронировать"}, "action": "openSection", "mode": "kymyz", '
                                       '"target": "stay"} или null}] — порядок = порядок слайдов')
    early_bonus = forms.JSONField(label='Бонус за раннюю бронь (JSON)', required=False,
                                  widget=forms.Textarea(attrs={'rows': 3}),
                                  help_text='{"kind": "points", "value": 500, "text": {"ru": "+500 баллов"}} '
                                            'или пусто')

    class Meta:
        model = EternalNews
        fields = ['about', 'show_in', 'title', 'lead', 'cover', 'slides', 'early_bonus', 'is_active']
        widgets = {'cover': forms.HiddenInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sk = Venue.objects.filter(app='sk')
        self.fields['about'].queryset = sk
        self.fields['show_in'].choices = [(v.pk, str(v)) for v in sk]

    def clean_slides(self):
        return _json_list(self.cleaned_data.get('slides') or [])

    def clean_early_bonus(self):
        v = self.cleaned_data.get('early_bonus')
        if not v:
            return None
        if not isinstance(v, dict) or v.get('kind') not in ('points', 'percent') or not v.get('value'):
            raise ValidationError('Нужно {"kind": "points" | "percent", "value": число, "text": {...}}')
        return v


class AppReleaseForm(forms.ModelForm):
    maintenance_message = L10nField(label='Текст техработ', required=False, textarea=True, rows=2)

    class Meta:
        model = AppRelease
        fields = ['min_version_ios', 'min_version_android', 'maintenance', 'maintenance_message']
        labels = {'min_version_ios': 'Минимальная версия iOS', 'min_version_android': 'Минимальная версия Android'}


WEEKDAYS = [(0, 'Пн'), (1, 'Вт'), (2, 'Ср'), (3, 'Чт'), (4, 'Пт'), (5, 'Сб'), (6, 'Вс')]


class PromotionForm(PanelForm, forms.ModelForm):
    """Акция на цену: вид и размер, охват, период, условия, аудитория, совместимость, лимит."""

    title = L10nField(label='Название', max_length=120)
    description = L10nField(label='Описание', required=False, textarea=True, rows=3)
    tag = L10nField(label='Бейдж', required=False, max_length=30)
    weekdays = forms.TypedMultipleChoiceField(label='Дни недели', choices=WEEKDAYS, coerce=int, required=False,
                                              widget=forms.CheckboxSelectMultiple)
    tiers = forms.MultipleChoiceField(label='Уровни', required=False, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Promotion
        fields = ['title', 'description', 'tag', 'kind', 'value', 'scope', 'venues', 'sections', 'items',
                  'gift_item', 'bundle_items', 'bundle_price', 'starts_at', 'ends_at', 'weekdays', 'time_from',
                  'time_to', 'min_quantity', 'min_amount', 'audience', 'tiers', 'group_min', 'stackable',
                  'usage_limit', 'sort_order', 'is_active']
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'time_from': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'time_to': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'venues': forms.CheckboxSelectMultiple, 'sections': forms.SelectMultiple(attrs={'size': 10}),
            'items': forms.SelectMultiple(attrs={'size': 12}), 'bundle_items': forms.SelectMultiple(attrs={'size': 8}),
        }
        labels = {'kind': 'Вид', 'value': 'Размер', 'scope': 'Охват', 'venues': 'Объекты', 'sections': 'Разделы',
                  'items': 'Услуги', 'gift_item': 'Услуга в подарок', 'bundle_items': 'Состав пакета',
                  'bundle_price': 'Цена пакета, сом', 'starts_at': 'Начало', 'ends_at': 'Конец',
                  'time_from': 'Часы: с', 'time_to': 'Часы: до', 'min_quantity': 'Минимум ночей / гостей / единиц',
                  'min_amount': 'Минимальная сумма заказа, сом', 'audience': 'Для кого',
                  'group_min': 'Группа от, человек', 'stackable': 'Суммируется с другими акциями',
                  'usage_limit': 'Лимит использований', 'sort_order': 'Порядок', 'is_active': 'Включена'}
        help_texts = {'value': '% — для скидки в процентах; сом — для скидки суммой и спеццены (за единицу); '
                               'N — для «N+1» (каждая N+1-я бесплатно)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.loyalty.models import Tier
        self.fields['tiers'].choices = [(t.pk, t.name.get('ru') or t.pk) for t in Tier.objects.order_by('order')]
        self.fields['sections'].queryset = Section.objects.select_related('venue', 'parent')
        self.fields['sections'].label_from_instance = lambda s: f'{s.venue} · {s.parent} → {s}' if s.parent \
            else f'{s.venue} · {s}'
        items = Item.objects.select_related('venue').order_by('venue__sort_order', 'sort_order', 'id')
        for name in ('items', 'bundle_items', 'gift_item'):
            self.fields[name].queryset = items
            self.fields[name].label_from_instance = lambda i: f'{i.venue} · {i} — {i.price} сом'
            self.fields[name].required = False
        for name in ('venues', 'sections', 'bundle_items'):
            self.fields[name].required = False

    def clean(self):
        data = super().clean()
        kind, value = data.get('kind'), data.get('value') or 0
        if kind == PromotionKind.PERCENT and not (0 < value <= 100):
            self.add_error('value', 'Процент — от 1 до 100')
        if kind in (PromotionKind.AMOUNT, PromotionKind.N_PLUS_ONE) and value <= 0:
            self.add_error('value', 'Укажите размер больше нуля')
        if kind == PromotionKind.SPECIAL_PRICE and value < 0:
            self.add_error('value', 'Цена не может быть отрицательной')
        if kind == PromotionKind.GIFT and not data.get('gift_item'):
            self.add_error('gift_item', 'Выберите услугу в подарок')
        if kind == PromotionKind.BUNDLE:
            if not data.get('bundle_items'):
                self.add_error('bundle_items', 'Выберите услуги пакета')
            if not data.get('bundle_price'):
                self.add_error('bundle_price', 'Укажите цену пакета')
        scope = data.get('scope')
        need = {PromotionScope.VENUES: 'venues', PromotionScope.SECTIONS: 'sections', PromotionScope.ITEMS: 'items'}
        if kind != PromotionKind.BUNDLE and scope in need and not data.get(need[scope]):
            self.add_error(need[scope], 'Выберите, на что действует акция')
        if data.get('audience') == PromotionAudience.TIERS and not data.get('tiers'):
            self.add_error('tiers', 'Выберите уровни')
        if data.get('audience') == PromotionAudience.GROUPS and not data.get('group_min'):
            self.add_error('group_min', 'Укажите, от скольких человек группа')
        s, e = data.get('starts_at'), data.get('ends_at')
        if s and e and e <= s:
            self.add_error('ends_at', 'Конец раньше начала')
        return data


class SectionForm(PanelForm, forms.ModelForm):
    id = forms.SlugField(label='Slug (id)', max_length=60)
    title = L10nField(label='Название', max_length=80)
    note = L10nField(label='Пояснение', required=False, max_length=300)

    class Meta:
        model = Section
        fields = ['id', 'venue', 'parent', 'category', 'title', 'note', 'sort_order', 'is_active']
        labels = {'venue': 'Объект', 'parent': 'Внутри раздела', 'category': 'Раздел программы (способы оплаты)',
                  'sort_order': 'Порядок', 'is_active': 'Показывать'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['id'].disabled = True
            self.fields['venue'].disabled = True
        self.fields['parent'].required = False
        venue = self.instance.venue_id if self.instance and self.instance.pk else self.initial.get('venue')
        qs = Section.objects.filter(parent__isnull=True)
        if venue:
            qs = qs.filter(venue_id=venue)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields['parent'].queryset = qs

    def clean_id(self):
        v = self.cleaned_data['id']
        if not (self.instance and self.instance.pk) and Section.objects.filter(pk=v).exists():
            raise ValidationError('Такой slug уже есть')
        return v

    def clean(self):
        data = super().clean()
        parent = data.get('parent')
        if parent and data.get('venue') and parent.venue_id != data['venue'].pk:
            self.add_error('parent', 'Раздел другого объекта')
        return data


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
    price_note = L10nField(label='Подпись к цене', required=False, max_length=80)

    class Meta:
        model = Item
        fields = ['id', 'venue', 'section', 'category', 'outlet', 'title', 'meta', 'image', 'gallery', 'price',
                  'price_note', 'season_from', 'season_to', 'tag', 'description', 'features', 'sort_order',
                  'is_active']
        widgets = {'image': forms.HiddenInput, 'season_from': forms.DateInput(attrs={'type': 'date'}),
                   'season_to': forms.DateInput(attrs={'type': 'date'})}
        labels = {'venue': 'Объект', 'section': 'Подраздел', 'category': 'Раздел', 'outlet': 'Точка обслуживания',
                  'price': 'Цена, сом', 'season_from': 'Доступна с', 'season_to': 'Доступна по',
                  'sort_order': 'Порядок', 'is_active': 'Показывать в приложении'}

    RULE_FIELDS = ['id', 'venue', 'section', 'category', 'outlet', 'price', 'pricing_type', 'pricing_unit',
                   'pricing_min', 'pricing_max', 'season_from', 'season_to', 'sort_order', 'is_active']

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
        self.fields['section'].required = False
        self.fields['section'].queryset = Section.objects.filter(children__isnull=True).select_related('venue')
        self.fields['section'].label_from_instance = lambda s: f'{s.venue} · {s}'

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
        section, venue = data.get('section'), data.get('venue')
        if section and venue and section.venue_id != venue.pk:
            self.add_error('section', 'Подраздел другого объекта')
        if venue and venue.pk != DEFAULT_VENUE and not section:
            self.add_error('section', 'Для этого объекта выберите подраздел — без него услуга не видна в приложении')
        sf, st = data.get('season_from'), data.get('season_to')
        if sf and st and sf > st:
            self.add_error('season_to', 'Конец раньше начала')
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
        fields = ['name', 'threshold', 'cashback_bonus', 'permanent_lifetime', 'permanent_years']
        labels = {'threshold': 'Порог: «Нынешних» за год на предыдущем уровне',
                  'cashback_bonus': 'Надбавка к кешбеку, % (Баллы = Сумма × 5 % × (1 + надбавка/100))',
                  'permanent_lifetime': 'Навсегда: баллов за всё время (пусто — не бывает постоянным)',
                  'permanent_years': 'Навсегда: лет в программе'}


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


class PrivilegeForm(ModesFormMixin, PanelForm, forms.ModelForm):
    id = forms.SlugField(label='Id', max_length=40)
    icon = forms.ChoiceField(label='Иконка', choices=[(i, i) for i in PERK_ICONS], widget=IconGrid)
    title = L10nField(label='Название', max_length=80)
    short = L10nField(label='Коротко (1–2 слова)', max_length=30)
    description = L10nField(label='Описание', textarea=True, rows=3)
    footnote = L10nField(label='Сноска мелким шрифтом', required=False, max_length=200)
    group_title = L10nField(label='Название группы (заголовок в «Апгрейдере», напр. «Поздний выезд»)',
                            required=False, max_length=40)

    class Meta:
        model = Privilege
        fields = ['id', 'tier', 'group', 'group_title', 'icon', 'title', 'short', 'description', 'footnote', 'sort_order']
        labels = {'tier': 'Уровень', 'sort_order': 'Порядок',
                  'group': 'Группа «Апгрейдер» (одна привилегия на разных уровнях, напр. late-checkout)'}
        help_texts = {'group': '{rate} в текстах подставляет ставку кешбека уровня, %'}

    RULE_FIELDS = ['id', 'tier', 'group', 'icon', 'sort_order', 'modes']
    modes_label = 'Где действует'
    modes_help = 'Пусто — во всех режимах; иначе в приложении подпись «Только …»'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_modes_field()
        if self.instance and self.instance.pk:
            self.fields['id'].disabled = True

    def save(self, commit=True):
        self.apply_modes()
        return super().save(commit)

    def clean_id(self):
        v = self.cleaned_data['id']
        if not (self.instance and self.instance.pk) and Privilege.objects.filter(pk=v).exists():
            raise ValidationError('Такой id уже есть')
        return v


# ---------------------------------------------------------------- контент

class PublishableForm(ModesFormMixin, forms.ModelForm):
    modes_default = [DEFAULT_VENUE]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_modes_field()

    def save(self, commit=True):
        self.apply_modes()
        return super().save(commit)


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
        ('Курс и кешбек', ['points_per_som', 'base_cashback_rate', 'birthday_multiplier', 'birthday_days_before',
                           'birthday_days_after']),
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
    url = L10nField(label='URL документа', required=False,
                    help_text='Пусто — страница на нашем сервере /legal/<документ>?lang=… с текстом ниже')
    body = L10nField(label='Текст документа', required=False, textarea=True, rows=14)
    published_at = dt_field('Опубликовать с')

    class Meta:
        model = LegalDocument
        fields = ['kind', 'version', 'body', 'url', 'requires_acceptance', 'published_at']

    def clean(self):
        d = super().clean()
        url, body = d.get('url') or {}, d.get('body') or {}
        if not any((url or {}).values()):
            if not any((body or {}).values()) and d.get('kind') != 'deletion':
                self.add_error('body', 'Нужен текст документа или внешний URL')
            from django.conf import settings
            page = f"{settings.PUBLIC_BASE_URL}/legal/{d.get('kind')}"
            d['url'] = {lang: f'{page}?lang={lang}' for lang in ('ru', 'ky', 'en')}
        return d
        labels = {'kind': 'Документ', 'version': 'Версия', 'requires_acceptance': 'Требует повторного согласия'}


class StaffUserForm(forms.ModelForm):
    """
    Директор: email + пароль (+ 2FA при входе) — веб-панель.
    Администратор кассы: телефон + 6-значный PIN + точки — приложение кассира.
    """

    password = forms.CharField(label='Пароль', required=False, widget=forms.PasswordInput(render_value=False),
                               help_text='Директору: для нового обязателен; для существующего — оставьте пустым')
    pin = forms.CharField(label='PIN-код (6 цифр)', required=False, max_length=6,
                          widget=forms.PasswordInput(render_value=False, attrs={
                              'inputmode': 'numeric', 'autocomplete': 'new-password', 'maxlength': '6'}),
                          help_text='Администратору: для нового обязателен; заполните, чтобы сменить PIN')
    outlets = forms.ModelMultipleChoiceField(label='Точки (кассы)', queryset=Outlet.objects.all(), required=False,
                                             widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = StaffUser
        fields = ['full_name', 'role', 'phone', 'email', 'outlets', 'is_active']
        labels = {'is_active': 'Активен', 'phone': 'Телефон', 'role': 'Роль'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = False
        self.fields['phone'].widget.attrs.update({'placeholder': '+996 555 000 000', 'inputmode': 'tel'})

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            return None
        qs = StaffUser.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Сотрудник с таким email уже есть')
        return email

    def clean_phone(self):
        from apps.common.errors import ApiError
        from apps.members.auth import normalize_phone
        phone = (self.cleaned_data.get('phone') or '').strip()
        if not phone:
            return ''
        try:
            phone = normalize_phone(phone)
        except ApiError:
            raise ValidationError('Номер в формате +996…')
        qs = StaffUser.objects.filter(phone=phone)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Сотрудник с таким телефоном уже есть')
        return phone

    def clean(self):
        from apps.common.errors import ApiError
        from apps.staff.auth import validate_pin
        d = super().clean()
        creating = not self.instance.pk
        if d.get('role') == Role.STAFF:
            if not d.get('phone') and 'phone' not in self.errors:
                self.add_error('phone', 'Администратор входит по номеру телефона')
            if not d.get('outlets'):
                self.add_error('outlets', 'Выберите точку (кассу) администратора')
            if creating and not d.get('pin'):
                self.add_error('pin', 'Задайте PIN')
            if d.get('pin'):
                try:
                    d['pin'] = validate_pin(d['pin'])
                except ApiError as e:
                    self.add_error('pin', '; '.join((e.extra or {}).get('fields', {}).get('pin', [])) or 'неверный PIN')
        else:
            if not d.get('email') and 'email' not in self.errors:
                self.add_error('email', 'Директор входит в панель по email')
            no_password = creating or not self.instance.has_usable_password()
            if no_password and not d.get('password'):
                self.add_error('password', 'Задайте пароль')
            pw = d.get('password')
            if pw:
                from django.contrib.auth.password_validation import validate_password
                try:
                    validate_password(pw, self.instance)
                except ValidationError as e:
                    self.add_error('password', e)
        return d

    def save(self, commit=True):
        user = super().save(commit=False)
        d = self.cleaned_data
        if d.get('role') == Role.STAFF:
            if not self.instance.pk or user.has_usable_password():
                user.set_unusable_password()  # в веб-панель администратор не входит
            user.totp_enabled, user.totp_secret = False, ''
            if d.get('pin'):
                user.set_pin(d['pin'])
        else:
            user.pin_hash = ''
            if d.get('password'):
                user.set_password(d['password'])
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
