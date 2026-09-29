"""
Контент: статьи, акции-баннеры, события недели, сторис категорий (ТЗ §7.2).
Публикация невозможна без всех трёх переводов или явного «использовать ru» (translations_missing).
"""
from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response

from apps.common import i18n
from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.content import serializers as client_payloads
from apps.content.models import Article, Promo, PublishStatus, ResortEvent, Story

from ..base import CollectionView, DetailView, ObjectView, SortView, body
from ..serializers import (ArticleSerializer, EventSerializer, PromoSerializer, SlideSerializer, StorySerializer,
                           save_slides)

PERM = 'content.edit'


def check_translations(obj):
    missing = obj.missing_translations()
    if missing and not obj.use_ru_fallback:
        raise ApiError('translations_missing', 422, extra={'missing': missing})


class ContentCollection(CollectionView):
    required_perms = PERM

    def filter_queryset(self, qs):
        status = self.request.query_params.get('status')
        return qs.filter(status=status) if status else qs


class ContentDetail(DetailView):
    required_perms = PERM

    def perform_update(self, serializer):
        obj = serializer.save()
        # опубликованное нельзя «сломать» правкой: те же требования, что при публикации
        if obj.status == PublishStatus.PUBLISHED:
            check_translations(obj)
        return obj


class PublishView(ObjectView):
    """POST /{resource}/{id}/publish | /unpublish."""

    required_perms = PERM
    publish = True

    def post(self, request, pk):
        obj = self.get_object()
        before = {'status': obj.status, 'publishedAt': i18n.iso(obj.published_at)}
        if self.publish:
            check_translations(obj)
            obj.status = PublishStatus.PUBLISHED
            obj.published_at = obj.published_at or timezone.now()
        else:
            obj.status = PublishStatus.DRAFT
        with transaction.atomic():
            obj.save()
            audit(request, f'{self.audit_name}.{"publish" if self.publish else "unpublish"}', obj, before=before,
                  after={'status': obj.status, 'publishedAt': i18n.iso(obj.published_at)})
        return Response(self.serialize(obj))


class PreviewView(ObjectView):
    """GET /{resource}/{id}/preview?lang=ky — как увидит мобилка на этом языке (пустой перевод → ru)."""

    required_perms = PERM
    payload = None

    def get(self, request, pk):
        obj = self.get_object()
        lang = request.query_params.get('lang')
        lang = lang if lang in i18n.LANGS else i18n.DEFAULT
        token = i18n.set_language(lang)
        try:
            data = self.payload(obj)
        finally:
            i18n._current.reset(token)
        return Response({'lang': lang, 'data': data, 'missingTranslations': obj.missing_translations()})


def resource(model, serializer, name, payload, queryset=None, sortable=True):
    """Набор view для ресурса контента: список, карточка, publish/unpublish, preview, sort."""
    qs = queryset or (lambda: model.objects.all())
    attrs = {'model': model, 'serializer_class': serializer, 'audit_name': name,
             'get_queryset': lambda self: qs()}
    views = {
        'list': type(f'{model.__name__}ListView', (ContentCollection,), attrs),
        'detail': type(f'{model.__name__}DetailView', (ContentDetail,), attrs),
        'publish': type(f'{model.__name__}PublishView', (PublishView,), {**attrs, 'publish': True}),
        'unpublish': type(f'{model.__name__}UnpublishView', (PublishView,), {**attrs, 'publish': False}),
        'preview': type(f'{model.__name__}PreviewView', (PreviewView,), {**attrs, 'payload': staticmethod(payload)}),
    }
    if sortable:
        views['sort'] = type(f'{model.__name__}SortView', (SortView,),
                             {'model': model, 'audit_name': name, 'required_perms': PERM})
    return views


articles = resource(Article, ArticleSerializer, 'article', client_payloads.article_payload, sortable=False)
promos = resource(Promo, PromoSerializer, 'promo', client_payloads.promo_payload,
                  queryset=lambda: Promo.objects.select_related('article'))
events = resource(ResortEvent, EventSerializer, 'event', client_payloads.event_payload,
                  queryset=lambda: ResortEvent.objects.select_related('article'))
stories = resource(Story, StorySerializer, 'story', client_payloads.story_payload,
                   queryset=lambda: Story.objects.prefetch_related('slides'))


class StorySlidesView(ObjectView):
    """PUT /stories/{id}/slides [{image, title, text, itemId}] — слайды целиком; updatedAt сторис растёт."""

    model = Story
    serializer_class = StorySerializer
    audit_name = 'story'
    required_perms = PERM

    def put(self, request, pk):
        story = self.get_object()
        data = request.data if isinstance(request.data, list) else body(request).get('slides')
        s = SlideSerializer(data=data, many=True, context=self.ctx())
        s.is_valid(raise_exception=True)
        before = [SlideSerializer(x, context=self.ctx()).data for x in story.slides.all()]
        with transaction.atomic():
            save_slides(story, s.validated_data)
            if story.status == PublishStatus.PUBLISHED:
                check_translations(story)
            audit(request, 'story.slides', story, before={'slides': before},
                  after={'slides': SlideSerializer(story.slides.all(), many=True, context=self.ctx()).data})
        return Response(self.serialize(story))

    post = put
    patch = put
