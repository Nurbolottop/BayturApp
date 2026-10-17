from apps.common.testing import BaseAPITestCase
from apps.staff.models import StaffRole


class ConfigurableRolesTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_staff('owner', email='owner@b.kg')
        self.marketer = self.make_staff('marketing', email='mk@b.kg')

    def panel(self, user):
        from django.test import Client
        c = Client()
        c.force_login(user)
        return c

    def test_marketing_defaults(self):
        c = self.panel(self.marketer)
        for url in ('/panel/promotions/', '/panel/content/', '/panel/campaigns/', '/panel/welcome/'):
            self.assertEqual(c.get(url).status_code, 200, url)
        for url in ('/panel/members/', '/panel/settings/', '/panel/staff/', '/panel/roles/'):
            self.assertEqual(c.get(url).status_code, 403, url)

    def test_marketing_logs_in_to_panel_with_password(self):
        from apps.staff.auth import check_password_step
        self.settings_obj(panel_two_factor=True)
        user, step = check_password_step('mk@b.kg', 'Passw0rd!x', '1.1.1.1')
        self.assertTrue(step['twoFactorRequired'])

    def test_owner_edits_permissions(self):
        owner = self.panel(self.owner)
        perms = ['content.edit', 'campaigns.draft']          # акции убрали
        r = owner.post('/panel/roles/marketing/', {'name': 'Маркетинг', 'kind': 'panel', 'perm': perms})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StaffRole.objects.get(pk='marketing').permissions, sorted(perms))
        self.assertEqual(self.panel(self.marketer).get('/panel/promotions/').status_code, 403)
        self.assertEqual(self.panel(self.marketer).get('/panel/content/').status_code, 200)

    def test_create_custom_role_and_assign(self):
        owner = self.panel(self.owner)
        owner.post('/panel/roles/new/', {'name': 'Бухгалтерия', 'kind': 'panel', 'perm': ['payments.view']})
        role = StaffRole.objects.get(name='Бухгалтерия')
        self.assertEqual(role.pk, 'buhgalteriya')
        acc = self.make_staff(role.pk, email='acc@b.kg')
        self.assertEqual(self.panel(acc).get('/panel/payments/').status_code, 200)
        self.assertEqual(self.panel(acc).get('/panel/promotions/').status_code, 403)
        self.assertTrue(acc.uses_panel)

    def test_owner_always_all_and_guards(self):
        owner = self.panel(self.owner)
        owner.post('/panel/roles/owner/', {'name': 'X', 'kind': 'app', 'perm': []})   # директор не редактируется
        self.assertTrue(self.owner.can('settings.edit'))
        r = owner.post('/panel/roles/new/', {'name': 'Касса+', 'kind': 'app', 'perm': ['staff.manage']})
        self.assertEqual(r.status_code, 200)                  # кассиру нельзя управлять сотрудниками
        self.assertFalse(StaffRole.objects.filter(name='Касса+').exists())
        owner.post('/panel/roles/staff/delete/')
        self.assertTrue(StaffRole.objects.filter(pk='staff').exists())   # системная
        owner.post('/panel/roles/marketing/delete/')
        self.assertTrue(StaffRole.objects.filter(pk='marketing').exists())   # есть сотрудник
        self.assertEqual(self.panel(self.marketer).get('/panel/roles/').status_code, 403)

    def test_marketing_admin_api_promotions(self):
        client = self.staff_client(self.marketer)
        self.assertEqual(client.get('/api/v1/admin/promotions').status_code, 200)
        self.assertEqual(client.get('/api/v1/admin/members').status_code, 403)
