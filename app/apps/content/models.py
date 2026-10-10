from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.i18n import missing_translations


class PublishStatus(models.TextChoices):
    DRAFT = 'draft', 'Черновик'
    PUBLISHED = 'published', 'Опубликовано'


def default_modes():
    return ['resort']


class Publishable(models.Model):
    status = models.CharField(max_length=20, choices=PublishStatus.choices, default=PublishStatus.DRAFT)
    # в каких режимах показывать (ТЗ экосистемы §6.10): resort, ski, kymyz
    modes = models.JSONField('Режимы', default=default_modes, blank=True)
    use_ru_fallback = models.BooleanField('Использовать ru вместо пустых переводов', default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    # поля, переводы которых обязательны для публикации
    L10N_REQUIRED = ()

    class Meta:
        abstract = True

    def missing_translations(self):
        missing = {}
        for name in self.L10N_REQUIRED:
            value = getattr(self, name)
            if value in (None, {}):
                continue
            langs = missing_translations(value)
            if langs:
                missing[name] = langs
        return missing


class Article(Publishable):
    id = models.SlugField(primary_key=True, max_length=80)
    image = models.CharField(max_length=500, blank=True)
    tag = models.JSONField(default=dict, blank=True)
    title = models.JSONField(default=dict)
    lead = models.JSONField(default=dict, blank=True)
    body = models.JSONField('Абзацы {ru: [...], ky: [...], en: [...]}', default=dict, blank=True)
    quote = models.JSONField(null=True, blank=True)
    date = models.DateField('Дата публикации', default=timezone.localdate)
    minutes = models.PositiveSmallIntegerField('Время чтения, мин', default=3)
    category = models.ForeignKey('catalog.Category', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='articles', help_text='Куда ведёт «Открыть в каталоге»')

    L10N_REQUIRED = ('tag', 'title', 'lead', 'body', 'quote')

    class Meta:
        ordering = ['-date', 'id']
        verbose_name = 'Статья'
        verbose_name_plural = 'Статьи'

    def __str__(self):
        return self.title.get('ru') or self.id


class ScheduledQuerySet(models.QuerySet):
    def visible(self, at=None):
        at = at or timezone.now()
        return self.filter(status=PublishStatus.PUBLISHED, article__status=PublishStatus.PUBLISHED).filter(
            Q(active_from__isnull=True) | Q(active_from__lte=at),
            Q(active_to__isnull=True) | Q(active_to__gt=at),
        )


class Promo(Publishable):
    """Баннер на главной."""

    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name='promos')
    subtitle = models.JSONField(default=dict)
    cta = models.JSONField('Текст кнопки', default=dict)
    cutout = models.CharField('PNG без фона', max_length=500, blank=True)
    active_from = models.DateTimeField(null=True, blank=True)
    active_to = models.DateTimeField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    L10N_REQUIRED = ('subtitle', 'cta')
    objects = ScheduledQuerySet.as_manager()

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Акция-баннер'
        verbose_name_plural = 'Акции-баннеры'


class ResortEvent(Publishable):
    """Событие недели."""

    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name='events')
    when = models.JSONField('Когда (свободный текст)', default=dict)
    place = models.JSONField('Где', default=dict)
    active_from = models.DateTimeField(null=True, blank=True)
    active_to = models.DateTimeField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    L10N_REQUIRED = ('when', 'place')
    objects = ScheduledQuerySet.as_manager()

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Событие'
        verbose_name_plural = 'События'


class Story(Publishable):
    """Сторис раздела каталога — одна на категорию."""

    category = models.OneToOneField('catalog.Category', on_delete=models.CASCADE, related_name='story')
    title = models.JSONField(default=dict)
    cover = models.CharField(max_length=500, blank=True)
    sort_order = models.IntegerField(default=0)

    L10N_REQUIRED = ('title',)

    class Meta:
        ordering = ['sort_order', 'category__sort_order']
        verbose_name = 'Сторис'
        verbose_name_plural = 'Сторис'

    def missing_translations(self):
        missing = super().missing_translations()
        for i, slide in enumerate(self.slides.all()):
            for name in ('title', 'text'):
                langs = missing_translations(getattr(slide, name))
                if langs and getattr(slide, name):
                    missing[f'slides[{i}].{name}'] = langs
        return missing


class StorySlide(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='slides')
    image = models.CharField(max_length=500, blank=True)
    title = models.JSONField(default=dict)
    text = models.JSONField(default=dict, blank=True)
    item = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                             help_text='Услуга для кнопки «Получить кешбек»')
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
