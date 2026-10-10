from django.db.models import Prefetch
from django.utils import timezone

from apps.common.caching import cached_public
from apps.common.errors import ApiError
from apps.common.models import ProgramSettings
from apps.common.views import PublicAPIView

from .models import DEFAULT_VENUE, Category, Item, Section, Venue
from .promotions import active_promotions
from .serializers import category_payload, item_payload, section_payload, venue_payload


def build_catalog():
    now = timezone.now()
    ps = ProgramSettings.get()
    # старое приложение курорта — только услуги курорта на Иссык-Куле; у других объектов свой /venues/{id}/catalog
    items_qs = Item.objects.filter(is_active=True, venue_id=DEFAULT_VENUE).prefetch_related('promos') \
        .select_related('category', 'section__parent').order_by('sort_order', 'id')
    cats = Category.objects.filter(is_active=True).prefetch_related(Prefetch('items', queryset=items_qs))
    promotions = active_promotions(now)
    return [category_payload(c, c.items.all(), now, ps, promotions) for c in cats]


class CatalogView(PublicAPIView):
    def get(self, request):
        return cached_public('catalog', build_catalog, request)


class CatalogItemView(PublicAPIView):
    """В т.ч. неактивная услуга — для истории."""

    def get(self, request, item_id):
        def build():
            item = Item.objects.select_related('category', 'section__parent').prefetch_related('promos') \
                .filter(pk=item_id).first()
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
            .select_related('category', 'section__parent').prefetch_related('promos').order_by('sort_order', 'id'):
        items_of.setdefault(item.section_id, []).append(item)
    promotions = active_promotions(now)
    tree = [section_payload(s, children_of, items_of, now, ps, promotions) for s in roots]
    return {'venue': venue_payload(venue), 'sections': [t for t in tree if t['items'] or t['sections']]}


class VenueCatalogView(PublicAPIView):
    """Прайс объекта: подразделы (с вложенными) и услуги; правила оплаты — по разделу программы подраздела."""

    def get(self, request, venue_id):
        venue = Venue.objects.filter(pk=venue_id, is_active=True).first()
        if venue is None:
            raise ApiError('not_found', 404)
        return cached_public('venue-catalog', lambda: build_venue_catalog(venue), request, vary=venue_id)


def build_venue_promotions(venue):
    from .promotions import covers
    from .serializers import promotion_payload
    now = timezone.now()
    items = list(Item.objects.active().filter(venue=venue).select_related('section__parent'))
    out = []
    for p in active_promotions(now):
        if p.kind == 'bundle':
            in_venue = [i.pk for i in p.bundle_items.all() if i.venue_id == venue.pk]
        else:
            in_venue = [i.pk for i in items if covers(p, i)]
        if in_venue:
            out.append(promotion_payload(p, in_venue))
    return out


class VenuePromotionsView(PublicAPIView):
    """Действующие сейчас акции объекта (в т.ч. на все объекты): условия, услуги, подарок, пакет."""

    def get(self, request, venue_id):
        venue = Venue.objects.filter(pk=venue_id, is_active=True).first()
        if venue is None:
            raise ApiError('not_found', 404)
        return cached_public('venue-promotions', lambda: build_venue_promotions(venue), request, vary=venue_id)


# ---------------------------------------------------------------- ТЗ экосистемы: режимы, витрина, услуги

def _mode_venue(request):
    from .modes import resolve_mode
    mode = resolve_mode(request)
    venue = Venue.objects.filter(pk=mode).first()
    if venue is None:
        raise ApiError('not_found', 404)
    return mode, venue


class ModesView(PublicAPIView):
    """Все объекты экосистемы — для пометок в истории, привилегиях и переходов между приложениями."""

    def get(self, request):
        from .serializers import mode_payload
        return cached_public('modes', lambda: [mode_payload(v) for v in Venue.objects.filter(is_active=True)],
                             request)


def _eternal_payload(e, mode=None):
    from apps.common.i18n import tr
    from apps.common.media import absolute_media_url

    from .modes import SEASON_NAMES
    slides = []
    for s in e.slides or []:
        cta = s.get('cta')
        slides.append({'image': absolute_media_url(s.get('image')), 'title': tr(s.get('title')) or '',
                       'text': tr(s.get('text')) or '',
                       'cta': {'label': tr(cta.get('label')), 'action': cta.get('action'), 'mode': cta.get('mode'),
                               'target': cta.get('target')} if cta else None})
    bonus = e.early_bonus or None
    return {'id': e.pk, 'about': e.about_id, 'aboutSeason': SEASON_NAMES.get(e.about_id),
            'title': tr(e.title), 'lead': tr(e.lead) or '', 'cover': absolute_media_url(e.cover),
            'earlyBonus': {'kind': bonus.get('kind'), 'value': bonus.get('value'), 'text': tr(bonus.get('text'))}
            if bonus else None,
            'slides': slides}


def _eternal_for(mode):
    from .models import EternalNews
    for e in EternalNews.objects.filter(is_active=True).select_related('about').order_by('-updated_at'):
        if mode in (e.show_in or []) and e.about_id != mode:
            return e
    return None


def build_showcase(mode, venue):
    from apps.common.i18n import tr
    from apps.common.media import absolute_media_url

    from .models import NewsItem, Showcase
    from .modes import SEASON_NAMES
    from .promotions import covers
    now = timezone.now()
    sc = Showcase.objects.filter(venue=venue).first()
    promotions = active_promotions(now)
    items = list(Item.objects.active().filter(venue=venue).select_related('section__parent'))
    offers = []
    for p in promotions:
        if not p.show_on_home:
            continue
        covered = [i for i in items if covers(p, i)]
        if not covered:
            continue
        item = covered[0]
        from .promotions import best_price
        total, snap = best_price(item, 1, None, now, [p])
        section = item.section.parent if item.section and item.section.parent else item.section
        offers.append({'id': p.pk, 'section': section.key if section else None, 'serviceId': item.pk,
                       'icon': section.icon if section else None, 'badge': tr(p.tag) or None,
                       'title': tr(p.title), 'note': tr(p.note) or None,
                       'price': total if snap and snap['discount'] > 0 else None,
                       'oldPrice': item.price if snap and snap['discount'] > 0 else None,
                       'image': absolute_media_url(p.image)})
    news = []
    for n in NewsItem.objects.filter(venue=venue, is_active=True):
        if (n.publish_from and n.publish_from > now) or (n.publish_to and n.publish_to < now):
            continue
        news.append({'id': n.pk, 'when': tr(n.when) or None, 'date': n.date.isoformat() if n.date else None,
                     'title': tr(n.title), 'place': tr(n.place) or None, 'image': absolute_media_url(n.image),
                     'articleId': n.article_id or None})
    eternal = _eternal_for(mode)
    return {
        'mode': mode, 'season': SEASON_NAMES.get(mode),
        'title': tr(venue.name), 'subtitle': tr(venue.short) or '',
        'heroImage': absolute_media_url(sc.hero_image) if sc else None,
        'heroImageNight': absolute_media_url(sc.hero_image_night) if sc else None,
        'facts': [tr(f) for f in (sc.facts if sc else [])],
        'cta': tr(sc.cta) if sc and sc.cta else None,
        'ctaSection': sc.cta_section if sc and sc.cta_section else None,
        'tiles': [{'section': t.get('section'), 'icon': t.get('icon'), 'title': tr(t.get('title'))}
                  for t in (sc.tiles if sc else [])],
        'offers': offers,
        'news': news,
        'eternal': _eternal_payload(eternal) if eternal else None,
    }


class ShowcaseView(PublicAPIView):
    """Главная режима одним запросом (ТЗ §6.2)."""

    def get(self, request):
        mode, venue = _mode_venue(request)
        return cached_public('showcase', lambda: build_showcase(mode, venue), request, mode=mode)


class EternalView(PublicAPIView):
    """«Вечная новость» для текущего режима целиком; нет — 404."""

    def get(self, request):
        from .modes import resolve_mode
        mode = resolve_mode(request)
        eternal = _eternal_for(mode)
        if eternal is None:
            raise ApiError('not_found', 404)
        return cached_public('eternal', lambda: _eternal_payload(eternal), request, mode=mode)


def build_services(mode, venue):
    from apps.common.i18n import tr

    from .serializers import services_section_payload
    now = timezone.now()
    ps = ProgramSettings.get()
    sections = list(Section.objects.filter(venue=venue, is_active=True, category__is_active=True)
                    .select_related('category', 'parent').prefetch_related('info_blocks').order_by('sort_order', 'id'))
    children_of, roots = {}, []
    for s in sections:
        (children_of.setdefault(s.parent_id, []) if s.parent_id else roots).append(s)
    items_of = {}
    for item in Item.objects.active().filter(venue=venue, section__isnull=False) \
            .select_related('category', 'section__parent', 'section__category').prefetch_related('promos') \
            .order_by('sort_order', 'id'):
        items_of.setdefault(item.section_id, []).append(item)
    promotions = active_promotions(now)
    out = []
    for s in roots:
        payload = services_section_payload(s, children_of.get(s.id, []), items_of, promotions, now, ps)
        if payload['groups'] or payload['info']:
            out.append(payload)
    return {'mode': mode, 'place': tr(venue.short) if venue.id == 'resort' else tr(venue.name),
            'contacts': {'phone': venue.phone or None, 'whatsapp': venue.whatsapp or None},
            'sections': out}


class ServicesView(PublicAPIView):
    """Весь каталог режима (ТЗ §6.3): разделы → подразделы → позиции, справка."""

    def get(self, request):
        mode, venue = _mode_venue(request)
        return cached_public('services', lambda: build_services(mode, venue), request, mode=mode)


class ServiceDetailView(PublicAPIView):
    """Одна позиция, в т.ч. скрытая (для ссылок из push и истории) — из любого режима."""

    def get(self, request, service_id):
        from .serializers import service_payload
        item = Item.objects.select_related('category', 'section__parent', 'section__category') \
            .prefetch_related('promos').filter(pk=service_id).first()
        if item is None:
            raise ApiError('item_not_found', 404)
        kind = (item.section.parent.kind if item.section and item.section.parent else
                (item.section.kind if item.section else '')) or ''
        return cached_public('service', lambda: service_payload(item, kind), request, vary=service_id)
