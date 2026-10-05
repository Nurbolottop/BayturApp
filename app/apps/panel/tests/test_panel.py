import pyotp
from django.core.management import call_command
from django.test import Client

from apps.cashback import services as cs
from apps.cashback.models import CashbackRequest, RequestStatus
from apps.common.models import AuditLog
from apps.common.testing import BaseAPITestCase
from apps.content.models import Article, PublishStatus
from apps.loyalty.models import Operation, OperationKind


class PanelBase(BaseAPITestCase):
    def login(self, user):
        c = Client()
        c.force_login(user)
        return c

    def make_request(self, member, item='spa-bochka', **data):
        req, _ = cs.create_request(member, {'itemId': item, 'quantity': 1, 'method': 'cash', **data})
        CashbackRequest.objects.filter(pk=req.pk).update(auto_confirm_at=None)
        return req


class LoginTests(PanelBase):
    def test_two_step_login_with_totp_setup(self):
        user = self.make_staff('owner', email='boss@baytur.kg')
        c = Client()
        r = c.post('/panel/login/', {'email': 'boss@baytur.kg', 'password': 'wrong'})
        self.assertContains(r, 'Неверные данные для входа')

        r = c.post('/panel/login/', {'email': 'boss@baytur.kg', 'password': 'Passw0rd!x'})
        self.assertRedirects(r, '/panel/login/2fa/')
        # первый вход: QR для приложения-аутентификатора (инлайн SVG)
        r = c.get('/panel/login/2fa/')
        self.assertContains(r, '<svg')
        self.assertNotIn('_auth_user_id', c.session)

        r = c.post('/panel/login/2fa/', {'code': '000000'})
        self.assertContains(r, 'Введите код')
        user.refresh_from_db()
        code = pyotp.TOTP(user.totp_secret).now()
        r = c.post('/panel/login/2fa/', {'code': code})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.session['_auth_user_id'], str(user.pk))
        user.refresh_from_db()
        self.assertTrue(user.totp_enabled)
        self.assertEqual(c.get('/panel/dashboard/').status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='staff.login', actor=user).exists())

    def test_second_login_asks_code_without_qr(self):
        user = self.make_staff('owner', email='m@baytur.kg')
        user.ensure_totp_secret()
        user.totp_enabled = True
        user.save()
        c = Client()
        c.post('/panel/login/', {'email': 'm@baytur.kg', 'password': 'Passw0rd!x'})
        r = c.get('/panel/login/2fa/')
        self.assertNotContains(r, '<svg viewBox')
        self.assertNotContains(r, 'Настройте 2FA')
        c.post('/panel/login/2fa/', {'code': pyotp.TOTP(user.totp_secret).now()})
        self.assertEqual(c.session['_auth_user_id'], str(user.pk))

    def test_cashier_administrator_cannot_sign_in_to_web(self):
        self.make_staff('staff', email='cash@baytur.kg', outlets=['spa'])
        r = Client().post('/panel/login/', {'email': 'cash@baytur.kg', 'password': 'Passw0rd!x'})
        self.assertContains(r, 'входят в приложение кассира')

    def test_director_creates_cashier_with_phone_and_pin(self):
        from apps.staff.models import StaffUser
        c = self.login(self.make_staff('owner'))
        data = {'full_name': 'Касса бассейна', 'role': 'staff', 'phone': '0700 123 456', 'pin': '123456',
                'outlets': ['spa'], 'is_active': 'on', 'email': '', 'password': ''}
        r = c.post('/panel/staff/new/', data)
        self.assertContains(r, 'слишком простой PIN')
        r = c.post('/panel/staff/new/', {**data, 'phone': '+996700123456', 'pin': '480215'})
        self.assertEqual(r.status_code, 302)
        u = StaffUser.objects.get(phone='+996700123456')
        self.assertEqual((u.role, u.email, u.has_usable_password()), ('staff', None, False))
        self.assertTrue(u.check_pin('480215'))
        self.assertEqual(list(u.outlets.values_list('pk', flat=True)), ['spa'])
        r = c.post('/panel/staff/new/', {**data, 'phone': '+996700123456', 'pin': '480215'})
        self.assertContains(r, 'таким телефоном уже есть')
        r = c.post('/panel/staff/new/', {**data, 'phone': '+996700123499', 'pin': '480215', 'outlets': []})
        self.assertContains(r, 'Выберите точку')

    def test_anonymous_redirected_to_login(self):
        r = Client().get('/panel/members/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/panel/login/', r['Location'])

    def test_temporary_password_must_be_changed(self):
        user = self.make_staff('owner', email='temp@baytur.kg')
        user.must_change_password = True
        user.save()
        c = self.login(user)
        r = c.get('/panel/members/')
        self.assertRedirects(r, '/panel/password/')
        r = c.post('/panel/password/', {'current': 'Passw0rd!x', 'new': 'N3w-strong-pass', 'new2': 'N3w-strong-pass'})
        self.assertEqual(r.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
        self.assertEqual(c.get('/panel/members/').status_code, 200)


class PermissionTests(PanelBase):
    def test_role_gated_pages_return_403(self):
        staff = self.make_staff('staff', outlets=['spa'])
        cases = [
            (staff, ['/panel/dashboard/', '/panel/settings/', '/panel/staff/', '/panel/catalog/', '/panel/requests/',
                     '/panel/payments/', '/panel/campaigns/', '/panel/audit/', '/panel/analytics/money/']),
        ]
        for user, urls in cases:
            c = self.login(user)
            for url in urls:
                r = c.get(url)
                self.assertEqual(r.status_code, 403, f'{user.role} {url}')
                self.assertContains(r, 'Нет доступа', status_code=403)

    def test_menu_shows_only_permitted_sections(self):
        c = self.login(self.make_staff('staff', outlets=['spa']))
        html = c.get('/panel/desk/').content.decode()
        self.assertIn('data-nav="desk"', html)
        self.assertNotIn('data-nav="settings"', html)
        self.assertNotIn('data-nav="dashboard"', html)

    def test_all_pages_render_for_owner(self):
        c = self.login(self.make_staff('owner'))
        member = self.make_member(points=100_000)
        req = self.make_request(member)
        for url in ['/panel/dashboard/', '/panel/analytics/', '/panel/desk/', f'/panel/desk/r/{req.pk}/',
                    '/panel/desk/shift/', '/panel/requests/', f'/panel/requests/{req.pk}/', '/panel/payments/',
                    '/panel/members/', f'/panel/members/{member.pk}/', '/panel/catalog/',
                    '/panel/catalog/items/spa-bochka/', '/panel/catalog/items/new/', '/panel/catalog/category/spa/',
                    '/panel/tiers/', '/panel/tiers/privileges/new/', '/panel/content/articles/',
                    '/panel/content/stories/new/', '/panel/campaigns/new/', '/panel/campaigns/templates/',
                    '/panel/complaints/', '/panel/settings/', '/panel/settings/legal/', '/panel/staff/new/',
                    '/panel/audit/']:
            r = c.get(url, follow=True)
            self.assertEqual(r.status_code, 200, url)


class DeskTests(PanelBase):
    def test_queue_shows_only_own_outlet(self):
        member = self.make_member(points=0)
        spa = self.make_request(member, 'spa-bochka')
        room = self.make_request(member, 'room-standard')
        self.assertEqual(spa.outlet_id, 'spa')
        self.assertEqual(room.outlet_id, 'reception')
        c = self.login(self.make_staff('staff', outlets=['spa']))
        html = c.get('/panel/desk/').content.decode()
        self.assertIn(spa.pk, html)
        self.assertNotIn(room.pk, html)
        # чужую заявку не открыть и не подтвердить
        self.assertEqual(c.get(f'/panel/desk/r/{room.pk}/').status_code, 404)
        c.post(f'/panel/r/{room.pk}/confirm/', {'cash_received': '1'})
        room.refresh_from_db()
        self.assertEqual(room.status, RequestStatus.PENDING)

    def test_confirm_creates_ledger_operations(self):
        member = self.make_member(points=300_000)
        req = self.make_request(member, 'spa-bochka', pointsSom=500)
        self.assertGreater(req.points, 0)
        staff = self.make_staff('staff', outlets=['spa'])
        c = self.login(staff)
        # наличные без отметки «деньги приняты» — отказ
        c.post(f'/panel/r/{req.pk}/confirm/')
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PENDING)

        r = c.post(f'/panel/r/{req.pk}/confirm/', {'cash_received': '1', 'next': '/panel/desk/'})
        self.assertRedirects(r, '/panel/desk/', fetch_redirect_response=False)
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.CONFIRMED)
        self.assertEqual(req.confirmed_by, staff)
        spend = Operation.objects.get(request=req, kind=OperationKind.SPEND)
        self.assertEqual(spend.points, -req.points)
        cs.credit_request(req.pk)
        self.assertEqual(Operation.objects.get(request=req, kind=OperationKind.CASHBACK).points, req.cashback)
        self.assertTrue(AuditLog.objects.filter(action='request.confirm', object_id=req.pk, actor=staff).exists())
        # повторная обработка → «уже обработана»
        r = c.post(f'/panel/r/{req.pk}/confirm/', {'cash_received': '1'}, follow=True)
        self.assertContains(r, 'уже обработана')

    def test_adjust_preview_and_escalation(self):
        member = self.make_member()
        req = self.make_request(member, 'spa-bochka')
        c = self.login(self.make_staff('staff', outlets=['spa']))
        r = c.post(f'/panel/r/{req.pk}/preview/', {'total': req.total * 2})
        self.assertTrue(r.json()['needsManager'])
        c.post(f'/panel/r/{req.pk}/adjust/', {'total': req.total * 2, 'reason': 'чек'})
        req.refresh_from_db()
        self.assertTrue(req.escalated)
        self.assertEqual(req.proposed_total, req.total * 2)
        manager = self.login(self.make_staff('owner'))
        manager.post(f'/panel/r/{req.pk}/approve/')
        req.refresh_from_db()
        self.assertFalse(req.escalated)
        self.assertEqual(req.total, req.proposed_total or req.total)

    def test_reject_requires_reason(self):
        req = self.make_request(self.make_member())
        c = self.login(self.make_staff('staff', outlets=['spa']))
        c.post(f'/panel/r/{req.pk}/reject/', {'reason_code': 'other'})
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PENDING)
        c.post(f'/panel/r/{req.pk}/reject/', {'reason_code': 'not_provided'})
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.REJECTED)

    def test_member_search_hides_balance(self):
        member = self.make_member(points=777_777)
        c = self.login(self.make_staff('staff', outlets=['spa']))
        r = c.get('/panel/desk/members/', {'q': member.member_id})
        self.assertContains(r, member.member_id)
        r = c.get(f'/panel/members/{member.pk}/')
        self.assertNotContains(r, '777')


class MemberActionTests(PanelBase):
    def test_manual_adjustment_requires_comment_and_is_audited(self):
        member = self.make_member(points=1000)
        c = self.login(self.make_staff('owner'))
        c.post(f'/panel/members/{member.pk}/adjust/', {'points': 500, 'comment': ''})
        self.assertEqual(self.wallet(member).balance, 1000)
        c.post(f'/panel/members/{member.pk}/adjust/', {'points': 500, 'comment': 'Компенсация'})
        self.assertEqual(self.wallet(member).balance, 1500)
        self.assertTrue(AuditLog.objects.filter(action='member.adjust', object_id=str(member.pk)).exists())

    def test_block_unblock(self):
        member = self.make_member()
        c = self.login(self.make_staff('owner'))
        c.post(f'/panel/members/{member.pk}/block/', {'reason': 'спам'})
        member.refresh_from_db()
        self.assertEqual(member.status, 'blocked')
        c.post(f'/panel/members/{member.pk}/unblock/')
        member.refresh_from_db()
        self.assertEqual(member.status, 'active')


class ContentTests(PanelBase):
    def test_publish_blocked_without_translations(self):
        c = self.login(self.make_staff('owner'))
        data = {'id': 'new-article', 'title_ru': 'Заголовок', 'title_ky': '', 'title_en': '', 'date': '2026-09-01',
                'minutes': 3, 'then': 'publish'}
        r = c.post('/panel/content/articles/new/', data, follow=True)
        self.assertEqual(r.status_code, 200)
        a = Article.objects.get(pk='new-article')
        self.assertEqual(a.status, PublishStatus.DRAFT)
        self.assertContains(r, 'Заполните все переводы')

        # с «использовать ru» — публикуется
        c.post('/panel/content/articles/new-article/', {**data, 'id': 'new-article', 'use_ru_fallback': 'on'})
        a.refresh_from_db()
        self.assertEqual(a.status, PublishStatus.PUBLISHED)

    def test_publish_with_all_translations(self):
        c = self.login(self.make_staff('owner'))
        c.post('/panel/content/articles/new/', {'id': 'full', 'title_ru': 'А', 'title_ky': 'Б', 'title_en': 'C',
                                                'date': '2026-09-01', 'minutes': 3})
        c.post('/panel/content/articles/full/publish/')
        self.assertEqual(Article.objects.get(pk='full').status, PublishStatus.PUBLISHED)


class TierTests(PanelBase):
    def test_thresholds_validated_and_previewed(self):
        from apps.loyalty.models import Tier
        c = self.login(self.make_staff('owner'))
        tiers = list(Tier.objects.live().order_by('order'))

        def payload(values):
            d = {}
            for t, v in zip(tiers, values):
                d[f'{t.pk}-name_ru'] = t.name.get('ru') or t.pk
                d[f'{t.pk}-threshold'] = v
            return d
        r = c.post('/panel/tiers/', payload([0, 0, 200, 900, 1000, 2000]))
        self.assertContains(r, 'у остальных — больше 0')
        r = c.post('/panel/tiers/', payload([0, 300, 200, 300, 400, 500]))
        self.assertContains(r, 'клиентов получат новый уровень')
        self.assertEqual(Tier.objects.get(pk=tiers[1].pk).threshold, tiers[1].threshold)
        c.post('/panel/tiers/', {**payload([0, 300, 200, 300, 400, 500]), 'confirm': '1'})
        self.assertEqual(Tier.objects.get(pk=tiers[1].pk).threshold, 300)


class TokensTests(PanelBase):
    def test_generated_tokens_are_up_to_date(self):
        call_command('build_tokens', '--check', verbosity=0)


class MemberExportAndCategoriesTests(PanelBase):
    def test_member_export_audited_and_permissioned(self):
        from apps.common.models import AuditLog
        member = self.make_member(points=1000)
        manager = self.login(self.make_staff('owner'))
        r = manager.get(f'/panel/members/{member.pk}/export/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(member.member_id, r['Content-Disposition'])
        self.assertIn(member.phone, r.content.decode())
        self.assertTrue(AuditLog.objects.filter(action='member.export').exists())
        cashier = self.login(self.make_staff('staff', outlets=['spa']))
        self.assertEqual(cashier.get(f'/panel/members/{member.pk}/export/').status_code, 403)

    def test_complaint_categories_crud(self):
        from apps.complaints.models import ComplaintCategory
        c = self.login(self.make_staff('owner'))
        self.assertEqual(c.get('/panel/complaints/categories/').status_code, 200)
        r = c.post('/panel/complaints/categories/', {'id': 'parking', 'title_ru': 'Парковка', 'title_ky': '',
                                                     'title_en': 'Parking', 'sort_order': 9, 'is_active': 'on'})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        self.assertEqual(ComplaintCategory.objects.get(pk='parking').title['en'], 'Parking')
        self.assertEqual(self.login(self.make_staff('staff')).get('/panel/complaints/categories/').status_code, 403)
