from django.db.models import Prefetch
from django.utils import timezone

from apps.common.caching import cached_public
from apps.common.errors import ApiError
from apps.common.models import ProgramSettings
from apps.common.views import PublicAPIView

from .models import Category, Item
from .serializers import category_payload, item_payload


def build_catalog():
    now = timezone.now()
    ps = ProgramSettings.get()
    items_qs = Item.objects.filter(is_active=True).prefetch_related('promos').select_related('category') \
        .order_by('sort_order', 'id')
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
