from datetime import datetime, time, timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.catalog.models import Item, Promotion, Section, Venue
from apps.catalog.promotions import active_promotions, best_price
from apps.common.testing import BaseAPITestCase


def L(ru):
    return {'ru': ru, 'ky': ru, 'en': ru}


class PromotionEngineTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.venue = Venue.objects.create(id='too-ashuu', name=L('Тоо-Ашуу'))
        self.rental = Section.objects.create(id='ta-rental', venue=self.venue, category_id='sport', title=L('Прокат'))
        self.skis = Section.objects.create(id='ta-rental-skis', venue=self.venue, parent=self.rental,
                                           category_id='sport', title=L('Лыжи'))
        self.stay = Section.objects.create(id='ta-stay', venue=self.venue, category_id='rooms', title=L('Проживание'))
        self.ski = Item.objects.create(id='ta-ski-set', venue=self.venue, section=self.skis, category_id='sport',
                                       title=L('Лыжный комплект'), price=1100,
                                       pricing={'type': 'unit', 'unit': 'visit', 'min': 1, 'max': 20})
        self.cottage = Item.objects.create(id='ta-cottage', venue=self.venue, section=self.stay, category_id='rooms',
                                           title=L('Коттедж'), price=8000,
                                           pricing={'type': 'unit', 'unit': 'night', 'min': 1, 'max': 30})
        self.skipass = Item.objects.create(id='ta-skipass', venue=self.venue, section=self.rental,
                                           category_id='sport', title=L('Скипасс'), price=1500,
                                           pricing={'type': 'unit', 'unit': 'guest', 'min': 1, 'max': 20})

    def promo(self, **kw):
        items = kw.pop('items', None)
        sections = kw.pop('sections', None)
        venues = kw.pop('venues', None)
        p = Promotion.objects.create(title=L(kw.pop('title', 'Акция')), **kw)
        if items:
            p.items.set(items)
        if sections:
            p.sections.set(sections)
        if venues:
            p.venues.set(venues)
        return p

    def price(self, item, q=1, member=None, at=None):
        return best_price(item, q, member, at)

    def test_kinds(self):
        self.promo(kind='percent', value=20, scope='items', items=[self.ski])
        self.assertEqual(self.price(self.ski, 2)[0], 1760)          # 2200 − 20 %
        Promotion.objects.all().delete()
        self.promo(kind='amount', value=500, scope='items', items=[self.cottage])
        self.assertEqual(self.price(self.cottage, 2)[0], 15500)     # −500 с заказа
        Promotion.objects.all().delete()
        self.promo(kind='specialPrice', value=800, scope='items', items=[self.ski])
        self.assertEqual(self.price(self.ski, 3)[0], 2400)
        Promotion.objects.all().delete()
        self.promo(kind='nPlusOne', value=2, scope='items', items=[self.cottage])  # третья ночь бесплатно
        self.assertEqual(self.price(self.cottage, 3)[0], 16000)
        self.assertEqual(self.price(self.cottage, 7)[0], 40000)     # 7 ночей → 2 бесплатно
        self.assertEqual(self.price(self.cottage, 2)[0], 16000)
        Promotion.objects.all().delete()
        self.promo(kind='gift', scope='items', items=[self.cottage], gift_item=self.skipass)
        total, snap = self.price(self.cottage, 1)
        self.assertEqual((total, snap['gift']['itemId']), (8000, 'ta-skipass'))

    def test_scope_section_with_children_venue_and_all(self):
        self.promo(kind='percent', value=10, scope='sections', sections=[self.rental])
        self.assertEqual(self.price(self.ski)[0], 990)              # вложенный подраздел «Лыжи»
        self.assertIsNone(self.price(self.cottage)[1])
        Promotion.objects.all().delete()
        self.promo(kind='percent', value=10, scope='venues', venues=[self.venue])
        self.assertEqual(self.price(self.cottage)[0], 7200)
        self.assertIsNone(self.price(Item.objects.filter(venue_id='baytur').first())[1])
        Promotion.objects.all().delete()
        self.promo(kind='percent', value=10, scope='all')
        baytur = Item.objects.filter(venue_id='baytur', pricing__type='unit').first() or \
            Item.objects.filter(venue_id='baytur').exclude(pricing__type='check').first()
        self.assertIsNotNone(self.price(baytur)[1])

    def test_period_weekdays_hours(self):
        tz = timezone.get_current_timezone()
        monday_noon = timezone.make_aware(datetime(2026, 10, 12, 12, 0), tz)  # понедельник
        p = self.promo(kind='percent', value=20, scope='items', items=[self.ski], weekdays=[0, 1, 2, 3, 4],
                       time_from=time(10), time_to=time(18))
        self.assertIsNotNone(self.price(self.ski, at=monday_noon)[1])
        self.assertIsNone(self.price(self.ski, at=monday_noon + timedelta(days=5))[1])   # суббота
        self.assertIsNone(self.price(self.ski, at=monday_noon + timedelta(hours=7))[1])  # 19:00
        p.starts_at = monday_noon + timedelta(days=1)
        p.save()
        self.assertIsNone(self.price(self.ski, at=monday_noon)[1])

    def test_conditions_audience_limit(self):
        self.promo(kind='percent', value=10, scope='items', items=[self.cottage], min_quantity=3)
        self.assertIsNone(self.price(self.cottage, 2)[1])
        self.assertEqual(self.price(self.cottage, 3)[0], 21600)
        Promotion.objects.all().delete()
        self.promo(kind='amount', value=1000, scope='items', items=[self.ski], min_amount=5000)
        self.assertIsNone(self.price(self.ski, 4)[1])
        self.assertEqual(self.price(self.ski, 5)[0], 4500)
        Promotion.objects.all().delete()
        self.promo(kind='percent', value=15, scope='items', items=[self.skipass], audience='groups', group_min=10)
        self.assertIsNone(self.price(self.skipass, 9)[1])
        self.assertEqual(self.price(self.skipass, 10)[0], 12750)
        Promotion.objects.all().delete()
        member = self.make_member('+996555404040')
        self.promo(kind='percent', value=10, scope='items', items=[self.ski], audience='members')
        self.assertIsNone(self.price(self.ski)[1])
        self.assertEqual(self.price(self.ski, member=member)[0], 990)
        Promotion.objects.all().delete()
        self.promo(kind='percent', value=10, scope='items', items=[self.ski], audience='tiers', tiers=['gold'])
        self.assertIsNone(self.price(self.ski, member=member)[1])  # новый клиент — не золото

    def test_stacking(self):
        self.promo(kind='percent', value=10, scope='items', items=[self.ski], stackable=True)
        self.promo(kind='amount', value=100, scope='items', items=[self.ski], stackable=True)
        self.assertEqual(self.price(self.ski)[0], 890)              # 1100 −10 % = 990 −100 = 890
        self.promo(kind='specialPrice', value=950, scope='items', items=[self.ski])  # несовместимая, хуже
        self.assertEqual(self.price(self.ski)[0], 890)
        self.promo(kind='specialPrice', value=800, scope='items', items=[self.ski])  # несовместимая, лучше
        total, snap = self.price(self.ski)
        self.assertEqual((total, len(snap['ids'])), (800, 1))

    def test_quote_payment_and_request_use_promo_price(self):
        self.promo(title='−20 % на прокат', kind='percent', value=20, scope='sections', sections=[self.rental],
                   usage_limit=1)
        member = self.make_member('+996555505050', points=0)
        self.auth(member)
        r = self.api.post('/api/v1/cashback-requests/quote', {'itemId': 'ta-ski-set', 'quantity': 1}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d['total'], d['promotion']['basePrice'], d['promotion']['discount']), (880, 1100, 220))
        r = self.api.post('/api/v1/cashback-requests', {'itemId': 'ta-ski-set', 'quantity': 1, 'method': 'cash'},
                          format='json', HTTP_IDEMPOTENCY_KEY='p-1')
        self.assertEqual(r.status_code, 201, r.content)
        from apps.cashback.models import CashbackRequest
        req = CashbackRequest.objects.get(pk=r.json()['id'])
        self.assertEqual((req.total, req.money_som, req.promotion['basePrice']), (880, 880, 1100))
        # лимит 1 исчерпан — следующий клиент платит полную цену
        other = self.make_member('+996555606060')
        self.auth(other)
        r = self.api.post('/api/v1/cashback-requests/quote', {'itemId': 'ta-ski-set', 'quantity': 1}, format='json')
        self.assertEqual((r.json()['total'], r.json()['promotion']), (1100, None))

    def test_catalog_shows_base_and_promo_price(self):
        self.promo(title='−20 % на прокат', kind='percent', value=20, scope='sections', sections=[self.rental],
                   tag=L('−20%'))
        self.promo(title='Для золота', kind='percent', value=30, scope='items', items=[self.ski], audience='tiers',
                   tiers=['gold'])
        d = self.api.get('/api/v1/venues/too-ashuu/catalog').json()
        rental = [s for s in d['sections'] if s['id'] == 'ta-rental'][0]
        ski = rental['sections'][0]['items'][0]
        self.assertEqual(ski['promo'], {'basePrice': 1100, 'price': 880, 'promotionId': ski['promo']['promotionId']})
        self.assertEqual(ski['price'], 1100)                         # базовая цена не меняется
        self.assertEqual(sorted(o['title'] for o in ski['promotions']), ['Для золота', '−20 % на прокат'])
        promos = self.api.get('/api/v1/venues/too-ashuu/promotions').json()
        self.assertEqual(len(promos), 2)
        self.assertIn('ta-ski-set', promos[0]['itemIds'])

    def test_cash_receipt_amount_not_discounted(self):
        from apps.cashback.desk import _cash_input  # noqa: F401 — наличные: сумма = чек, акция не применяется
        self.promo(kind='percent', value=50, scope='all')
        from apps.cashback import services
        member = self.make_member('+996555707070')
        req, _ = services.create_request(member, {'itemId': 'ta-ski-set', 'quantity': 1, 'method': 'cash',
                                                  'pointsSom': 0, '_noPromotions': True})
        self.assertEqual((req.total, req.promotion), (1100, None))

    def test_panel_and_admin_api(self):
        p = self.promo(kind='percent', value=20, scope='items', items=[self.ski])
        c = Client()
        c.force_login(self.make_staff('owner'))
        for url in ('/panel/promotions/', '/panel/promotions/?venue=too-ashuu', '/panel/promotions/new/',
                    f'/panel/promotions/{p.pk}/'):
            self.assertEqual(c.get(url).status_code, 200, url)
        r = c.post('/panel/promotions/new/', {
            'title_ru': 'Пакет', 'kind': 'bundle', 'value': '0', 'scope': 'items', 'bundle_items': ['ta-ski-set',
                                                                                               'ta-skipass'],
            'bundle_price': '2200', 'audience': 'all', 'sort_order': '0', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302, r.content.decode()[:2000])
        api = self.staff_client(self.make_staff('owner'))
        r = api.get('/api/v1/admin/promotions?venue=too-ashuu')
        self.assertEqual(r.status_code, 200, r.content)
        r = api.patch(f'/api/v1/admin/promotions/{p.pk}', {'value': 150}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_load_venues_creates_existing_promotions_once(self):
        call_command('load_venues', stdout=StringIO())
        call_command('load_venues', stdout=StringIO())
        self.assertEqual(Promotion.objects.filter(title__ru__startswith='Завтрак и скипасс').count(), 1)
        cottage = Item.objects.get(pk='ta-cottage-2')
        total, snap = best_price(cottage, 1, None, None, active_promotions())
        self.assertEqual((total, snap['gift']['itemId']), (8000, 'ta-skipass-adult'))
        self.assertEqual(Decimal(Promotion.objects.get(title__ru='Трансфер по суперцене').value), Decimal('1000'))
