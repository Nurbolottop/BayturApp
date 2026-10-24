from apps.catalog.models import Item, Promotion
from apps.staff.models import StaffRole

from .test_panel import PanelBase


class DepartmentAdminTests(PanelBase):
    """Админ отдела (роль с отделом) видит в панели только свои разделы каталога."""

    def setUp(self):
        super().setUp()
        self.food_admin = self.make_staff('admin-food', email='food@b.kg')
        self.member = self.make_member()
        self.food_item = Item.objects.active().filter(category_id='food').first()
        self.spa_item = Item.objects.active().filter(category_id='spa').first()
        self.food_req = self.make_request(self.member, item=self.food_item.pk, checkAmount=self.food_item.price)
        self.spa_req = self.make_request(self.member, item=self.spa_item.pk, checkAmount=self.spa_item.price)

    def test_roles_seeded(self):
        self.assertEqual({r.pk: r.department for r in StaffRole.objects.filter(pk__startswith='admin-')},
                         {'admin-rooms': 'rooms', 'admin-food': 'food', 'admin-entertainment': 'entertainment'})
        self.assertEqual(self.food_admin.category_ids, {'food'})
        self.assertIsNone(self.make_staff('owner', email='o@b.kg').category_ids)

    def test_requests_only_own_department(self):
        c = self.login(self.food_admin)
        r = c.get('/panel/requests/')
        self.assertContains(r, self.food_req.pk)
        self.assertNotContains(r, self.spa_req.pk)
        self.assertEqual(c.get(f'/panel/requests/{self.food_req.pk}/').status_code, 200)
        self.assertEqual(c.get(f'/panel/requests/{self.spa_req.pk}/').status_code, 404)
        desk = c.get('/panel/desk/')
        self.assertContains(desk, self.food_req.pk)
        self.assertNotContains(desk, self.spa_req.pk)
        # подтвердить чужую заявку нельзя
        c.post(f'/panel/r/{self.spa_req.pk}/confirm/', {'cash_received': '1'})
        self.spa_req.refresh_from_db()
        self.assertEqual(self.spa_req.status, 'pending')

    def test_catalog_only_own_items(self):
        c = self.login(self.food_admin)
        self.assertEqual(c.get(f'/panel/catalog/items/{self.food_item.pk}/').status_code, 200)
        self.assertEqual(c.get(f'/panel/catalog/items/{self.spa_item.pk}/').status_code, 404)
        r = c.get('/panel/catalog/?mode=resort')
        self.assertContains(r, self.food_item.title['ru'])
        self.assertNotContains(r, self.spa_item.title['ru'])
        self.assertEqual(c.get('/panel/catalog/category/food/').status_code, 403)
        self.assertEqual(c.get('/panel/showcase/').status_code, 403)

    def test_promotions_only_own(self):
        # акции по умолчанию ведёт маркетолог; если директор выдаст их куратору — только своего отдела
        role = StaffRole.objects.get(pk='admin-food')
        role.permissions = sorted(set(role.permissions) | {'promotions.edit'})
        role.save()
        own = Promotion.objects.create(title={'ru': 'Еда −10%'}, kind='percent', value=10, scope='items')
        own.items.set([self.food_item])
        other = Promotion.objects.create(title={'ru': 'SPA −10%'}, kind='percent', value=10, scope='items')
        other.items.set([self.spa_item])
        everywhere = Promotion.objects.create(title={'ru': 'Всё −5%'}, kind='percent', value=5, scope='all')
        c = self.login(self.food_admin)
        r = c.get('/panel/promotions/?all=1')
        self.assertContains(r, 'Еда −10%')
        self.assertNotContains(r, 'SPA −10%')
        self.assertNotContains(r, 'Всё −5%')
        self.assertEqual(c.get(f'/panel/promotions/{own.pk}/').status_code, 200)
        self.assertEqual(c.get(f'/panel/promotions/{other.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/panel/promotions/{everywhere.pk}/toggle/').status_code, 404)

    def test_role_department_set_in_editor(self):
        owner = self.login(self.make_staff('owner', email='o2@b.kg'))
        r = owner.post('/panel/roles/new/', {'name': 'Пляж', 'kind': 'panel', 'department': 'entertainment',
                                             'perm': ['requests.view_all']})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StaffRole.objects.get(name='Пляж').department, 'entertainment')
        r = owner.post('/panel/roles/new/', {'name': 'Плохая', 'kind': 'panel', 'department': 'food',
                                             'perm': ['staff.manage']})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(StaffRole.objects.filter(name='Плохая').exists())


class RestaurantMenuTests(PanelBase):
    """Куратор ресторанов загружает меню PDF — приложение получает ссылку menuPdf."""

    def test_upload_menu(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = self.login(self.make_staff('admin-food', email='food2@b.kg'))
        bad = SimpleUploadedFile('menu.pdf', b'not a pdf')
        c.post('/panel/catalog/items/food-davinci/menu/', {'menu': bad})
        self.assertEqual(Item.objects.get(pk='food-davinci').menu_pdf, '')
        pdf = SimpleUploadedFile('menu.pdf', b'%PDF-1.4\n%test\n', content_type='application/pdf')
        r = c.post('/panel/catalog/items/food-davinci/menu/', {'menu': pdf})
        self.assertEqual(r.status_code, 302)
        path = Item.objects.get(pk='food-davinci').menu_pdf
        self.assertTrue(path.startswith('uploads/pdf/') and path.endswith('.pdf'), path)
        food = next(cat for cat in self.api.get('/api/v1/catalog').json() if cat['id'] == 'food')
        item = next(i for i in food['items'] if i['id'] == 'food-davinci')
        self.assertTrue(item['menuPdf'].endswith('.pdf'))
        # чужой отдел не может
        spa = self.login(self.make_staff('admin-entertainment', email='ent@b.kg'))
        self.assertEqual(spa.post('/panel/catalog/items/food-davinci/menu-off/').status_code, 404)
        c.post('/panel/catalog/items/food-davinci/menu-off/')
        self.assertEqual(Item.objects.get(pk='food-davinci').menu_pdf, '')
