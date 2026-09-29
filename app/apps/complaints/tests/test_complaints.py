import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.common.errors import ApiError
from apps.common.testing import BaseAPITestCase
from apps.complaints import services
from apps.complaints.models import Complaint


def jpeg_with_gps():
    img = Image.new('RGB', (40, 30), 'red')
    exif = Image.Exif()
    exif[0x010F] = 'PhoneMaker'
    exif[0x8825] = {1: 'N', 2: (42.0, 30.0, 0.0)}  # GPSInfo
    buf = io.BytesIO()
    img.save(buf, 'JPEG', exif=exif)
    return SimpleUploadedFile('p.jpg', buf.getvalue(), content_type='image/jpeg')


class ComplaintTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=1000)
        self.auth(self.member)

    def create(self, **extra):
        data = {'category': 'service', 'text': 'Долго ждали официанта у бассейна', **extra}
        return self.api.post('/api/v1/complaints', data, format='json')

    def test_create_with_photo_without_exif(self):
        up = self.api.post('/api/v1/uploads/complaint-photo', {'file': jpeg_with_gps()}, format='multipart')
        self.assertEqual(up.status_code, 201, up.content)
        from apps.common.models import Upload
        upload = Upload.objects.get(pk=up.json()['id'])
        with upload.file.open('rb') as fh:
            exif = Image.open(fh).getexif()
            self.assertNotIn(0x8825, exif)
            self.assertNotIn(0x010F, exif)
        r = self.create(outletId='davinci', attachmentIds=[up.json()['id']])
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertRegex(d['number'], r'^О-\d{6}$')
        self.assertEqual(d['status'], 'new')
        self.assertEqual(len(d['messages'][0]['attachments']), 1)

    def test_text_length_and_daily_limit(self):
        self.assertEqual(self.create(text='коротко').json()['error']['code'], 'validation_error')
        for _ in range(5):
            self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().json()['error']['code'], 'complaints_limit')

    def test_points_complaint_from_operation(self):
        op = self.member.operations.first()
        r = self.create(category='points', operationId=op.pk, subtype='credited_less')
        self.assertEqual((r.json()['operationId'], r.json()['subtype']), (op.pk, 'credited_less'))

    def test_conversation_statuses_and_rating(self):
        c = Complaint.objects.get(pk=self.create(outletId='davinci').json()['id'])
        care = self.make_staff('care')
        waiter = self.make_staff('staff', outlets=['davinci'])
        with self.assertRaises(ApiError):
            services.resort_reply(c.pk, waiter, 'Мы разберёмся')   # сотрудник точки не отвечает
        services.add_note(c.pk, waiter, 'Был аншлаг')
        with self.captureOnCommitCallbacks(execute=True):
            services.resort_reply(c.pk, care, 'Извините, разберёмся')
        d = self.api.get(f'/api/v1/complaints/{c.pk}').json()
        self.assertEqual(d['status'], 'answered')
        self.assertEqual(d['messages'][1]['authorName'], 'Команда BAYTUR')
        self.assertNotIn('internalNotes', d)
        self.assertTrue(self.member.notifications.filter(kind='complaint.reply').exists())
        self.api.post(f'/api/v1/complaints/{c.pk}/messages', {'text': 'Спасибо'}, format='json')
        c.refresh_from_db()
        self.assertEqual(c.status, 'in_progress')
        self.assertEqual(self.api.post(f'/api/v1/complaints/{c.pk}/rating', {'rating': 5}, format='json')
                         .json()['error']['code'], 'invalid_status')
        services.set_status(c.pk, care, 'closed')
        self.assertEqual(self.api.post(f'/api/v1/complaints/{c.pk}/rating', {'rating': 5}, format='json')
                         .json()['rating'], 5)
        self.assertEqual(self.api.post(f'/api/v1/complaints/{c.pk}/messages', {'text': 'ещё'}, format='json')
                         .json()['error']['code'], 'complaint_closed')

    def test_categories_endpoint(self):
        d = self.api.get('/api/v1/complaints/categories', HTTP_ACCEPT_LANGUAGE='en').json()
        self.assertEqual(len(d['categories']), 8)
        self.assertIn({'id': 'points', 'title': 'Points & requests'}, d['categories'])
