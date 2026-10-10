from django.db.models import Prefetch
from django.utils import timezone

from apps.common.caching import cached_public
from apps.common.errors import ApiError
from apps.common.models import ProgramSettings
from apps.common.views import PublicAPIView

from .models import DEFAULT_VENUE, Category, Item, Section, Venue
from .serializers import category_payload, item_payload, section_payload, venue_payload


def build_catalog():
    now = timezone.now()
    ps = ProgramSettings.get()
    # старое приложение курорта — только услуги курорта на Иссык-Куле; у других объектов свой /venues/{id}/catalog
    items_qs = Item.objects.filter(is_active=True, venue_id=DEFAULT_VENUE).prefetch_related('promos') \
        .select_related('category').order_by('sort_order', 'id')
    cats = Category.objects.filter(is_active=True).prefetch_related(Prefetch('items', queryset=items_qs))
    return [category_payload(c, c.items.all(), now, ps) for c in cats]


class CatalogView(PublicAPIView):
    def get(self, request):
        return cached_public('catalog', build_catalog, request)


class CatalogItemView(PublicAPIView):
    """В т.ч. неактивная услуга — для истории."""

    def get(self, request, item_id):
        def build():
            item = Item.objects.select_related('category').prefetch_related('promos').filter(pk=item_id).first()
            if item is None:
                return None
            return item_payload(item)
        if not Item.objects.filter(pk=item_id).exists():
            raise ApiError('item_not_found', 404)
        return cached_public('item', build, request, vary=item_id)


class VenuesView(PublicAPIView):
    """Объекты экосистемы BAYTUR: у каждого своё приложение, аккаунт и баллы общие."""

    def get(self, request):
        return cached_public('venues', lambda: [venue_payload(v) for v in Venue.objects.filter(is_active=True)],
                             request)


class VenueDetailView(PublicAPIView):
    def get(self, request, venue_id):
        venue = Venue.objects.filter(pk=venue_id, is_active=True).first()
        if venue is None:
            raise ApiError('not_found', 404)
        return cached_public('venue', lambda: venue_payload(venue), request, vary=venue_id)


def build_venue_catalog(venue):
    now = timezone.now()
    ps = ProgramSettings.get()
    sections = list(Section.objects.filter(venue=venue, is_active=True, category__is_active=True)
                    .select_related('category').order_by('sort_order', 'id'))
    children_of, roots = {}, []
    for s in sections:
        (children_of.setdefault(s.parent_id, []) if s.parent_id else roots).append(s)
    items_of = {}
    for item in Item.objects.active().filter(venue=venue, section__isnull=False) \
            .select_related('category').prefetch_related('promos').order_by('sort_order', 'id'):
        items_of.setdefault(item.section_id, []).append(item)
    tree = [section_payload(s, children_of, items_of, now, ps) for s in roots]
    return {'venue': venue_payload(venue), 'sections': [t for t in tree if t['items'] or t['sections']]}


class VenueCatalogView(PublicAPIView):
    """Прайс объекта: подразделы (с вложенными) и услуги; правила оплаты — по разделу программы подраздела."""

    def get(self, request, venue_id):
        venue = Venue.objects.filter(pk=venue_id, is_active=True).first()
        if venue is None:
            raise ApiError('not_found', 404)
        return cached_public('venue-catalog', lambda: build_venue_catalog(venue), request, vary=venue_id)
