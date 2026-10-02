from apps.common.errors import ApiError
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Privilege, Tier, Wallet
from apps.loyalty.services import create_tier, delete_tier


class TierManagementTests(BaseAPITestCase):
    def set_lifetime(self, member, lifetime, tier):
        Wallet.objects.filter(member=member).update(lifetime=lifetime, tier=tier)

    def test_create_tier_upgrades_members_and_appears_in_api(self):
        m = self.make_member()
        self.set_lifetime(m, 700_000, 'gold')
        tier, upgraded = create_tier({'ru': 'Изумруд', 'ky': '', 'en': 'Emerald'}, 650_000,
                                     ['#0b3d2e', '#1f8a5b', '#7be0b0'])
        self.assertEqual(tier.pk, 'izumrud')
        self.assertEqual(upgraded, 1)
        self.assertEqual(Wallet.objects.get(member=m).tier_id, 'izumrud')
        program = self.api.get('/api/v1/loyalty/program').json()
        t = next(x for x in program['tiers'] if x['id'] == 'izumrud')
        self.assertEqual((t['from'], t['colors'], t['medal']), (650_000, ['#0B3D2E', '#1F8A5B', '#7BE0B0'], None))
        self.assertEqual([x['from'] for x in program['tiers']], sorted(x['from'] for x in program['tiers']))

    def test_create_validation(self):
        with self.assertRaises(ApiError):
            create_tier({'ru': 'Дубль'}, 500_000, ['#000000', '#111111', '#222222'])   # порог занят
        with self.assertRaises(ApiError):
            create_tier({'ru': 'Ноль'}, 0, ['#000000', '#111111', '#222222'])
        with self.assertRaises(ApiError):
            create_tier({'ru': 'Цвет'}, 300_000, ['red', '#111111', '#222222'])

    def test_delete_tier_moves_members_and_privileges(self):
        m = self.make_member()
        self.set_lifetime(m, 600_000, 'gold')
        result = delete_tier(Tier.objects.get(pk='gold'), privileges_to=Tier.objects.get(pk='silver'))
        self.assertEqual(result['reassigned'], 1)
        self.assertEqual(Wallet.objects.get(member=m).tier_id, 'silver')
        self.assertEqual(Privilege.objects.filter(tier='silver').count(), 6)
        self.assertFalse(Tier.objects.filter(pk='gold').exists())

    def test_delete_with_privileges_and_base_tier_protected(self):
        delete_tier(Tier.objects.get(pk='diamond'))
        self.assertFalse(Privilege.objects.filter(pk__in=['villa', 'events', 'spa-day']).exists())
        with self.assertRaises(ApiError):
            delete_tier(Tier.objects.get(pk='bronze'))

    def test_admin_api_create_delete(self):
        owner = self.staff_client(self.make_staff('manager'))
        r = owner.post('/api/v1/admin/tiers', {'name': {'ru': 'Титан', 'ky': '', 'en': 'Titan'}, 'from': 3_000_000,
                                               'colors': ['#111111', '#555555', '#999999']}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['id'], 'titan')
        r = owner.patch('/api/v1/admin/tiers/titan', {'colors': ['#222222', '#666666', '#AAAAAA']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Tier.objects.get(pk='titan').colors[0], '#222222')
        self.assertEqual(owner.delete('/api/v1/admin/tiers/titan').status_code, 200)
        editor = self.staff_client(self.make_staff('editor'))
        self.assertEqual(editor.post('/api/v1/admin/tiers', {'name': {'ru': 'X'}, 'from': 5,
                                                             'colors': ['#111111'] * 3}, format='json').status_code, 403)

    def test_panel_create_and_delete(self):
        c = self.client
        c.force_login(self.make_staff('owner'))
        r = c.post('/panel/tiers/new/', {'name_ru': 'Рубин', 'name_ky': '', 'name_en': 'Ruby', 'from_points': 1_500_000,
                                         'color0': '#3a0a14', 'color1': '#9b1b30', 'color2': '#f07a8a', 'medal': ''})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Tier.objects.filter(pk='rubin', from_points=1_500_000).exists())
        page = c.get('/panel/tiers/').content.decode()
        self.assertIn('.tier-rubin{', page)
        self.assertIn('Рубин', page)
        r = c.post('/panel/tiers/level/rubin/delete/', {'privileges_to': 'delete'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Tier.objects.filter(pk='rubin').exists())
