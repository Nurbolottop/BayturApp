from datetime import timedelta

from django.utils import timezone

from apps.common.caching import cached_public
from apps.common.errors import ApiError
from apps.common.views import PublicAPIView

from .models import Article, Promo, PublishStatus, ResortEvent, Story
from .serializers import article_payload, event_payload, promo_payload, story_payload


def _minute_bucket():
    # периоды показа меняют выдачу — ключ кеша обновляется раз в минуту
    return timezone.now().strftime('%Y%m%d%H%M')


class PromosView(PublicAPIView):
    """Только активные на сегодня."""

    def get(self, request):
        return cached_public('promos', lambda: [promo_payload(p) for p in
                                                Promo.objects.visible().select_related('article')],
                             request, vary=_minute_bucket())


class EventsView(PublicAPIView):
    def get(self, request):
        return cached_public('events', lambda: [event_payload(e) for e in
                                                ResortEvent.objects.visible().select_related('article')],
                             request, vary=_minute_bucket())


class StoriesView(PublicAPIView):
    def get(self, request):
        def build():
            qs = Story.objects.filter(status=PublishStatus.PUBLISHED, category__is_active=True) \
                .prefetch_related('slides')
            return [story_payload(s) for s in qs]
        return cached_public('stories', build, request)


class ArticleView(PublicAPIView):
    def get(self, request, article_id):
        article = Article.objects.filter(pk=article_id, status=PublishStatus.PUBLISHED).first()
        if article is None:
            raise ApiError('not_found', 404)
        return cached_public('article', lambda: article_payload(article), request, vary=article_id)
