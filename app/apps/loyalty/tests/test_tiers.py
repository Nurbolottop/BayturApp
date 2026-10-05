from apps.common.errors import ApiError
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Privilege, Tier, Wallet
from apps.loyalty.services import create_tier, delete_tier


class TierManagementTests(BaseAPITestCase):
    def test_create_tier_on_top_and_appears_in_api(self):
        m = self.make_member()
        Wallet.objects.filter(member=m).update(current=5_000_000, tier='ambassador')
        tier, upgraded = create_tier({'ru': 'Изумруд', 'ky': '', 'en': 'Emerald'}, 4_000_000,
                                     ['#0b3d2e', '#1f8a5b', '#7be0b0'])
        self.assertEqual((tier.pk, tier.order), ('izumrud', 6))
        self.assertEqual(upgraded, 0)  # повышение по новому порогу — при следующем начислении (§2.9)
        self.assertEqual(Wallet.objects.get(member=m).tier_id, 'ambassador')
        program = self.api.get('/api/v1/loyalty/program').json()
        t = program['tiers'][-1]
        self.assertEqual((t['id'], t['threshold'], t['style']['gradient'], t['style']['medalUrl']),
                         ('izumrud', 4_000_000, ['#0B3D2E', '#1F8A5B', '#7BE0B0'], None))
        self.assertEqual([x['order'] for x in program['tiers']], sorted(x['order'] for x in program['tiers']))

    def test_create_validation(self):
        with self.assertRaises(ApiError):
            create_tier({'ru': 'Ноль'}, 0, ['#000000', '#111111', '#222222'])
        with self.assertRaises(ApiError):
            create_tier({'ru': 'Цвет'}, 300_000, ['red', '#111111', '#222222'])

    def test_delete_tier_moves_members_and_privileges(self):
        m = self.make_member()
        Wallet.objects.filter(member=m).update(tier='gold', max_reached='gold')
        result = delete_tier(Tier.objects.get(pk='gold'), privileges_to=Tier.objects.get(pk='silver'))
        self.assertEqual((result['reassigned'], result['movedTo']), (1, 'silver'))
        w = Wallet.objects.get(member=m)
        self.assertEqual((w.tier_id, w.max_reached_id), ('silver', 'silver'))
        self.assertEqual(Privilege.objects.filter(tier='silver').count(), 6)
        self.assertFalse(Tier.objects.live().filter(pk='gold').exists())   # мягкое удаление
        self.assertTrue(m.tier_changes.filter(cause='admin', to_tier='silver').exists())
        ids = [t['id'] for t in self.api.get('/api/v1/loyalty/program').json()['tiers']]
        self.assertNotIn('gold', ids)

    def test_delete_with_privileges_and_base_tier_protected(self):
        delete_tier(Tier.objects.get(pk='titanium'))
        self.assertFalse(Privilege.objects.filter(pk__in=['villa', 'events', 'spa-day']).exists())
        with self.assertRaises(ApiError) as e:
            delete_tier(Tier.objects.get(pk='bronze'))
        self.assertEqual(e.exception.code, 'base_tier_protected')

    def test_admin_api_create_delete(self):
        owner = self.staff_client(self.make_staff('manager'))
        r = owner.post('/api/v1/admin/tiers', {'name': {'ru': 'Рубин', 'ky': '', 'en': 'Ruby'}, 'threshold': 3_000_000,
                                               'colors': ['#111111', '#555555', '#999999']}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()['id'], r.json()['threshold']), ('rubin', 3_000_000))
        r = owner.patch('/api/v1/admin/tiers/rubin', {'colors': ['#222222', '#666666', '#AAAAAA']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Tier.objects.get(pk='rubin').colors[0], '#222222')
        self.assertEqual(owner.delete('/api/v1/admin/tiers/rubin').status_code, 200)
        editor = self.staff_client(self.make_staff('editor'))
        self.assertEqual(editor.post('/api/v1/admin/tiers', {'name': {'ru': 'X'}, 'threshold': 5,
                                                             'colors': ['#111111'] * 3}, format='json').status_code, 403)

    def test_panel_create_and_delete(self):
        c = self.client
        c.force_login(self.make_staff('owner'))
        r = c.post('/panel/tiers/new/', {'name_ru': 'Рубин', 'name_ky': '', 'name_en': 'Ruby', 'threshold': 1_500_000,
                                         'color0': '#3a0a14', 'color1': '#9b1b30', 'color2': '#f07a8a', 'medal': ''})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Tier.objects.filter(pk='rubin', threshold=1_500_000).exists())
        page = c.get('/panel/tiers/').content.decode()
        self.assertIn('.tier-rubin{', page)
        self.assertIn('Рубин', page)
        r = c.post('/panel/tiers/level/rubin/delete/', {'privileges_to': 'delete'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Tier.objects.live().filter(pk='rubin').exists())
