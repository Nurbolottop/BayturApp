"""Каталог: точки обслуживания, категории с правилами кешбека, услуги и их акции (ТЗ §7.2)."""
from rest_framework.response import Response

from apps.catalog.models import Category, Item, ItemPromo, Outlet, Promotion, Section, Venue
from apps.common.audit import audit
from apps.common.errors import ApiError

from ..base import ANY_STAFF, CollectionView, DetailView, ObjectView, SortView, not_found
from ..serializers import (CategorySerializer, ItemPromoSerializer, ItemSerializer, OutletSerializer,
                           PromotionSerializer, SectionSerializer, VenueSerializer)

CATALOG_READ = ['catalog.texts', 'catalog.edit']
CATALOG_WRITE = {'GET': CATALOG_READ, 'PATCH': CATALOG_READ, 'PUT': CATALOG_READ,
                 'POST': 'catalog.edit', 'DELETE': 'catalog.edit'}


# ---------------------------------------------------------------- точки обслуживания

class OutletsView(CollectionView):
    """Список точек нужен всем ролям (фильтры, привязка сотрудников); меняет — владелец."""

    model = Outlet
    serializer_class = OutletSerializer
    audit_name = 'outlet'
    required_perms = {'GET': ANY_STAFF, 'POST': 'settings.edit'}


class OutletDetailView(DetailView):
    model = Outlet
    serializer_class = OutletSerializer
    audit_name = 'outlet'
    required_perms = {'GET': 'settings.edit', 'PATCH': 'settings.edit', 'PUT': 'settings.edit',
                      'DELETE': 'settings.edit'}


class OutletsSortView(SortView):
    model = Outlet
    audit_name = 'outlet'
    required_perms = 'settings.edit'


# ---------------------------------------------------------------- объекты и подразделы

class VenuesView(CollectionView):
    """Объекты экосистемы (у каждого своё приложение). Создаёт — владелец."""

    model = Venue
    serializer_class = VenueSerializer
    audit_name = 'venue'
    required_perms = {'GET': ANY_STAFF, 'POST': 'settings.edit'}


class VenueDetailView(DetailView):
    model = Venue
    serializer_class = VenueSerializer
    audit_name = 'venue'
    required_perms = CATALOG_WRITE
    full_perm = 'catalog.edit'
    texts_perm = 'catalog.texts'


class SectionsView(CollectionView):
    """GET ?venue=&parent= (parent=root — только верхние)."""

    model = Section
    serializer_class = SectionSerializer
    audit_name = 'section'
    required_perms = {'GET': CATALOG_READ, 'POST': 'catalog.edit'}

    def get_queryset(self):
        return Section.objects.select_related('venue', 'parent', 'category')

    def filter_queryset(self, qs):
        p = self.request.query_params
        if p.get('venue'):
            qs = qs.filter(venue_id=p['venue'])
        if p.get('parent') == 'root':
            qs = qs.filter(parent__isnull=True)
        elif p.get('parent'):
            qs = qs.filter(parent_id=p['parent'])
        return qs


class SectionDetailView(DetailView):
    model = Section
    serializer_class = SectionSerializer
    audit_name = 'section'
    required_perms = CATALOG_WRITE
    full_perm = 'catalog.edit'
    texts_perm = 'catalog.texts'


# ---------------------------------------------------------------- категории

class CategoriesView(CollectionView):
    model = Category
    serializer_class = CategorySerializer
    audit_name = 'category'
    required_perms = {'GET': CATALOG_READ, 'POST': 'catalog.edit'}

    def get_queryset(self):
        return Category.objects.prefetch_related('items')


class CategoryDetailView(DetailView):
    model = Category
    serializer_class = CategorySerializer
    audit_name = 'category'
    required_perms = CATALOG_WRITE
    full_perm = 'catalog.edit'
    texts_perm = 'catalog.texts'


class CategoriesSortView(SortView):
    model = Category
    audit_name = 'category'
    required_perms = 'catalog.edit'


# ---------------------------------------------------------------- услуги

class ItemsView(CollectionView):
    """GET ?venue=&section=&category=&outlet=&active=1|0&q="""

    model = Item
    serializer_class = ItemSerializer
    audit_name = 'item'
    required_perms = {'GET': CATALOG_READ, 'POST': 'catalog.edit'}

    def get_queryset(self):
        return Item.objects.select_related('category', 'outlet').prefetch_related('promos')

    def filter_queryset(self, qs):
        p = self.request.query_params
        if p.get('venue'):
            qs = qs.filter(venue_id=p['venue'])
        if p.get('section'):
            qs = qs.filter(section_id=p['section'])
        if p.get('category'):
            qs = qs.filter(category_id=p['category'])
        if p.get('outlet'):
            qs = qs.filter(outlet_id=p['outlet'])
        if p.get('active') in ('1', 'true'):
            qs = qs.filter(is_active=True)
        elif p.get('active') in ('0', 'false'):
            qs = qs.filter(is_active=False)
        if p.get('q'):
            q = p['q'].strip()
            qs = qs.filter(id__icontains=q) | qs.filter(title__ru__icontains=q)
        return qs


class ItemDetailView(DetailView):
    model = Item
    serializer_class = ItemSerializer
    audit_name = 'item'
    required_perms = CATALOG_WRITE
    full_perm = 'catalog.edit'
    texts_perm = 'catalog.texts'

    def get_queryset(self):
        return Item.objects.select_related('category', 'outlet').prefetch_related('promos')

    def check_delete(self, obj):
        # на услугу ссылаются заявки и история — только скрыть
        if obj.requests.exists():
            raise ApiError('item_in_use', 409)


class ItemsSortView(SortView):
    model = Item
    audit_name = 'item'
    required_perms = 'catalog.edit'


class ItemVisibilityView(ObjectView):
    """POST /items/{id}/hide | /show — скрыть услугу, не удаляя."""

    model = Item
    serializer_class = ItemSerializer
    audit_name = 'item'
    required_perms = {'POST': 'catalog.edit'}
    visible = False

    def post(self, request, pk):
        item = self.get_object()
        before = {'isActive': item.is_active}
        item.is_active = self.visible
        item.save(update_fields=['is_active', 'updated_at'])
        audit(request, 'item.show' if self.visible else 'item.hide', item, before=before,
              after={'isActive': item.is_active})
        return Response(self.serialize(item))


# ---------------------------------------------------------------- акции на услугу

class ItemPromosView(CollectionView):
    model = ItemPromo
    serializer_class = ItemPromoSerializer
    audit_name = 'item_promo'
    required_perms = {'GET': CATALOG_READ, 'POST': 'catalog.edit'}

    def item(self):
        item = Item.objects.filter(pk=self.kwargs['item_id']).first()
        if item is None:
            raise not_found()
        return item

    def get_queryset(self):
        return ItemPromo.objects.filter(item=self.item())

    def get(self, request, item_id):
        return super().get(request)

    def perform_create(self, serializer):
        return serializer.save(item=self.item())

    def post(self, request, item_id):
        return super().post(request)


class ItemPromoDetailView(DetailView):
    model = ItemPromo
    serializer_class = ItemPromoSerializer
    audit_name = 'item_promo'
    required_perms = {'GET': CATALOG_READ, 'PATCH': 'catalog.edit', 'PUT': 'catalog.edit',
                      'DELETE': 'catalog.edit'}

    def get_queryset(self):
        return ItemPromo.objects.filter(item_id=self.kwargs['item_id'])


# ---------------------------------------------------------------- акции на цену

class PromotionsView(CollectionView):
    """GET ?venue=&active=1|0"""

    model = Promotion
    serializer_class = PromotionSerializer
    audit_name = 'promotion'
    required_perms = {'GET': CATALOG_READ, 'POST': 'catalog.edit'}

    def get_queryset(self):
        return Promotion.objects.prefetch_related('venues', 'sections', 'items', 'bundle_items')

    def filter_queryset(self, qs):
        p = self.request.query_params
        if p.get('venue'):
            v = p['venue']
            qs = (qs.filter(venues__pk=v) | qs.filter(sections__venue_id=v) | qs.filter(items__venue_id=v)
                  | qs.filter(scope='all') | qs.filter(bundle_items__venue_id=v)).distinct()
        if p.get('active') in ('1', 'true'):
            qs = qs.filter(is_active=True)
        elif p.get('active') in ('0', 'false'):
            qs = qs.filter(is_active=False)
        return qs


class PromotionDetailView(DetailView):
    model = Promotion
    serializer_class = PromotionSerializer
    audit_name = 'promotion'
    required_perms = {'GET': CATALOG_READ, 'PATCH': 'catalog.edit', 'PUT': 'catalog.edit', 'DELETE': 'catalog.edit'}
