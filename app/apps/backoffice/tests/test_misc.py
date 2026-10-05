"""Загрузки, рассылки, документы, возвраты."""
import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.common.models import AuditLog
from apps.members.models import LegalDocument
from apps.members.services import pending_consents
from apps.notifications.models import Campaign
from apps.payments.models import Payment, PaymentStatus

from .base import API, AdminTestCase

FULL = {'ru': 'Текст', 'ky': 'Текст', 'en': 'Text'}


class UploadTests(AdminTestCase):
    def upload(self, user, content, name):
        return self.as_(user).post(API + '/uploads', {'file': SimpleUploadedFile(name, content)}, format='multipart')

    def test_png_keeps_transparency(self):
        buf = io.BytesIO()
        Image.new('RGBA', (20, 10), (255, 0, 0, 0)).save(buf, 'PNG')
        r = self.upload(self.editor, buf.getvalue(), 'cutout.png')
        self.assertStatus(r, 201)
        self.assertTrue(r.data['url'].endswith('.png'))
        self.assertEqual((r.data['width'], r.data['height']), (20, 10))

    def test_rejects_non_image_and_foreign_roles(self):
        self.assertError(self.upload(self.editor, b'not an image', 'x.png'), 422, 'file_invalid')
        self.assertStatus(self.upload(self.accountant, b'x', 'x.png'), 403)


class CampaignTests(AdminTestCase):
    def create(self, user):
        r = self.post(user, '/campaigns', {'title': FULL, 'body': FULL, 'segment': {'tiers': ['gold']}})
        self.assertStatus(r, 201)
        return r.data['id']

    def test_schedule_and_send(self):
        cid = self.create(self.manager)
        at = (timezone.now() + timedelta(days=1)).isoformat()
        r = self.post(self.manager, f'/campaigns/{cid}/send', {'scheduledAt': at})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['status'], 'scheduled')
        # редактор не трогает запланированную
        self.assertError(self.patch(self.editor, f'/campaigns/{cid}', {'title': FULL}), 409, 'invalid_status')
        self.assertStatus(self.post(self.manager, f'/campaigns/{cid}/cancel'), 200)

        cid = self.create(self.editor)
        r = self.post(self.manager, f'/campaigns/{cid}/send')
        self.assertStatus(r, 200)
        c = Campaign.objects.get(pk=cid)
        self.assertLessEqual(c.scheduled_at, timezone.now())
        self.assertTrue(AuditLog.objects.filter(action='campaign.send', object_id=str(cid)).exists())

    def test_test_send_needs_member_account(self):
        # ProgramSettings.get() на только что созданной строке отдаёт время тихих часов строкой ('22:00') —
        # заранее создаём строку и сбрасываем кеш (см. отчёт: баг в common.models.ProgramSettings.get)
        from django.core.cache import cache
        from apps.common.models import ProgramSettings
        ProgramSettings.objects.get_or_create(pk=1)
        cache.delete(ProgramSettings.CACHE_KEY)
        cid = self.create(self.editor)
        self.assertStatus(self.post(self.editor, f'/campaigns/{cid}/test'), 422)
        self.editor.phone = self.member.phone
        self.editor.save()
        self.assertStatus(self.post(self.editor, f'/campaigns/{cid}/test'), 200)

    def test_bad_segment(self):
        r = self.post(self.manager, '/campaigns', {'title': FULL, 'body': FULL, 'segment': {'tiers': ['iron']}})
        self.assertStatus(r, 400)


class LegalTests(AdminTestCase):
    def test_publish_new_terms_creates_pending_consents(self):
        r = self.post(self.owner, '/legal', {'kind': 'terms', 'version': '2.0', 'url': {'ru': 'https://b.kg/t'}})
        self.assertStatus(r, 201)
        doc_id = r.data['id']
        self.assertEqual(pending_consents(self.member), [])
        r = self.post(self.owner, f'/legal/{doc_id}/publish')
        self.assertStatus(r, 200)
        self.assertTrue(r.data['isCurrent'])
        self.assertEqual([p['version'] for p in pending_consents(self.member)], ['2.0'])
        self.assertError(self.patch(self.owner, f'/legal/{doc_id}', {'version': '2.1'}), 409, 'invalid_status')
        self.assertStatus(self.post(self.owner, '/legal', {'kind': 'terms', 'version': '2.0',
                                                           'url': {'ru': 'x'}}), 400)
        self.assertTrue(LegalDocument.objects.filter(version='2.0').exists())


class RefundTests(AdminTestCase):
    def test_accountant_refunds(self):
        p = Payment.objects.create(member=self.member, method='finik', amount=1000, status=PaymentStatus.PAID,
                                   paid_at=timezone.now())
        r = self.get(self.accountant, '/payments/reconciliation')
        self.assertEqual([x['id'] for x in r.data['items']], [p.pk])
        self.assertError(self.post(self.accountant, f'/payments/{p.pk}/refund', {}), 400, 'validation_error')
        r = self.post(self.accountant, f'/payments/{p.pk}/refund', {'amount': 400, 'reason': 'Частичный'})
        self.assertStatus(r, 200)
        self.assertEqual((r.data['refundedAmount'], r.data['status']), (400, 'paid'))
        r = self.post(self.owner, f'/payments/{p.pk}/refund', {'reason': 'Остаток'})
        self.assertEqual((r.data['refundedAmount'], r.data['status']), (1000, 'refunded'))
        self.assertError(self.post(self.owner, f'/payments/{p.pk}/refund', {'reason': 'x'}), 409, 'invalid_status')
        self.assertEqual(AuditLog.objects.filter(action='payment.refund').count(), 2)


from apps.common.testing import BaseAPITestCase  # noqa: E402


class TemporaryPasswordTests(BaseAPITestCase):
    def test_temp_password_must_be_changed(self):
        owner = self.staff_client(self.make_staff('owner'))
        r = owner.post('/api/v1/admin/staff', {'email': 'new@baytur.kg', 'fullName': 'Новый', 'role': 'manager'},
                       format='json')
        self.assertEqual(r.status_code, 201, r.content)
        from apps.staff.models import StaffUser
        user = StaffUser.objects.get(email='new@baytur.kg')
        self.assertTrue(user.must_change_password)
        c = self.staff_client(user)
        self.assertEqual(c.get('/api/v1/admin/members').json()['error']['code'], 'password_change_required')
        self.assertTrue(c.get('/api/v1/admin/me').json()['mustChangePassword'])
        r = c.post('/api/v1/admin/me/password', {'currentPassword': r.json()['temporaryPassword'],
                                                 'newPassword': 'Nov1y-Parol-2026'}, format='json')
        self.assertFalse(r.json()['mustChangePassword'])
        self.assertEqual(c.get('/api/v1/admin/members').status_code, 200)
