from datetime import date
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.catalog.models import Category, Item, Outlet
from apps.common.i18n import l10n
from apps.common.tokens import issue_access
from apps.loyalty.models import Tier
from apps.loyalty.services import get_wallet
from apps.members.models import Member
from apps.staff.models import StaffUser
from apps.staff.roles import Role

API = '/api/v1/admin'

TIERS = [('bronze', 0), ('silver', 1000), ('gold', 5000), ('platinum', 20000), ('diamond', 50000)]


class AdminTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reception = Outlet.objects.create(id='reception', name=l10n('Ресепшен', 'Ресепшн', 'Reception'))
        cls.spa_outlet = Outlet.objects.create(id='spa', name=l10n('SPA', 'SPA', 'SPA'))
        cls.category = Category.objects.create(id='spa', title=l10n('SPA', 'SPA', 'SPA'), rate=Decimal('0.05'),
                                               max_points_share=Decimal('0.5'), methods=['cash', 'finik'])
        cls.item = Item.objects.create(id='massage', category=cls.category, outlet=cls.reception,
                                       title=l10n('Массаж', 'Массаж', 'Massage'), price=1000,
                                       pricing={'type': 'unit', 'unit': 'session', 'min': 1, 'max': 5})
        for tid, threshold in TIERS:
            Tier.objects.create(id=tid, name=l10n(tid.title(), tid.title(), tid.title()), from_points=threshold)
        cls.owner = cls.make_staff(Role.OWNER)
        cls.manager = cls.make_staff(Role.MANAGER)
        cls.editor = cls.make_staff(Role.EDITOR)
        cls.accountant = cls.make_staff(Role.ACCOUNTANT)
        cls.care = cls.make_staff(Role.CARE)
        cls.staff = cls.make_staff(Role.STAFF, outlets=[cls.reception])
        cls.spa_staff = cls.make_staff(Role.STAFF, outlets=[cls.spa_outlet])
        cls.member = Member.objects.create(phone='+996700000001', first_name='Айбек', last_name='Токтогулов',
                                           birthday=date(1990, 5, 1), language='ky')
        get_wallet(cls.member)

    @classmethod
    def make_staff(cls, role, outlets=(), phone=''):
        n = StaffUser.objects.count() + 1
        user = StaffUser.objects.create_user(f'{role}{n}@baytur.kg', 'pass-12345', full_name=f'{role} {n}',
                                             role=role, phone=phone, totp_enabled=True)
        user.outlets.set(outlets)
        return user

    def as_(self, user):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_access('staff', user.pk))
        return self.client

    def get(self, user, url, **params):
        return self.as_(user).get(API + url, params)

    def post(self, user, url, data=None):
        return self.as_(user).post(API + url, data or {}, format='json')

    def patch(self, user, url, data=None):
        return self.as_(user).patch(API + url, data or {}, format='json')

    def put(self, user, url, data=None):
        return self.as_(user).put(API + url, data, format='json')

    def delete(self, user, url):
        return self.as_(user).delete(API + url)

    def assertStatus(self, response, code):
        self.assertEqual(response.status_code, code, getattr(response, 'data', response.content))

    def assertError(self, response, status, code):
        self.assertStatus(response, status)
        self.assertEqual(response.data['error']['code'], code, response.data)
