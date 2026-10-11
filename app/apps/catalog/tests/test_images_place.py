import io
from io import StringIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import Client
from PIL import Image

from apps.catalog.models import Item, Section, Showcase
from apps.common.media import image_payload
from apps.common.testing import BaseAPITestCase
from apps.members.models import Device

SK = {'HTTP_X_BAYTUR_APP': 'sk'}


def save_image(name, size=(2000, 1500), color=(111, 143, 63)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'JPEG')
    return default_storage.save(f'uploads/test/{name}.jpg', ContentFile(buf.getvalue()))


class ImagesAndPlaceTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        call_command('load_venues', stdout=StringIO())

    def test_image_payload(self):
        path = save_image('a')
        img = image_payload(path)
        self.assertEqual((img['width'], img['height']), (1600, 1200))
        r, g, b = (int(img['color'][i:i + 2], 16) for i in (1, 3, 5))         # JPEG чуть сдвигает цвет
        self.assertTrue(abs(r - 111) <= 3 and abs(g - 143) <= 3 and abs(b - 63) <= 3, img['color'])
        self.assertTrue(img['url'].endswith('?w=1600') and img['thumb'].endswith('?w=400'))
        r = self.client.get('/img/' + img['thumb'].split('/img/', 1)[1].split('?')[0], {'w': 400})
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/webp'))
        self.assertIsNone(image_payload(''))
        self.assertEqual(image_payload('https://cdn.example/x.jpg')['url'], 'https://cdn.example/x.jpg')

    def test_services_and_showcase_images(self):
        cover, photo, hero = save_image('cover'), save_image('photo'), save_image('hero', (1280, 1600))
        group = Section.objects.filter(venue_id='kymyz', parent__isnull=False).first()
        group.cover = cover
        group.save()
        item = Item.objects.filter(section=group, is_active=True).first()
        item.image, item.gallery = photo, [cover]
        item.save()
        Showcase.objects.filter(venue_id='kymyz').update(hero_image=hero)
        d = self.api.get('/api/v1/services', **SK, HTTP_X_BAYTUR_MODE='kymyz').json()
        self.assertEqual(d['place'], 'Суусамыр')
        groups = [g for s in d['sections'] for g in s['groups']]
        g = next(g for g in groups if g['id'] == group.key)
        self.assertEqual(g['cover']['width'], 1600)
        it = next(i for i in g['items'] if i['id'] == item.id)
        self.assertEqual(len(it['photos']), 2)
        self.assertIn(photo.rsplit('.', 1)[0], it['photos'][0]['url'])               # первое — главное
        hero_img = self.api.get('/api/v1/showcase', **SK, HTTP_X_BAYTUR_MODE='kymyz').json()['heroImage']
        self.assertEqual((hero_img['width'], hero_img['height']), (1280, 1600))
        self.assertEqual(self.api.get('/api/v1/services', **SK, HTTP_X_BAYTUR_MODE='ski').json()['place'], 'Тоо-Ашуу')

    def test_data_fixes(self):
        from apps.catalog import venues_data as D
        text = repr(D.ITEMS) + repr(D.SECTIONS) + repr(D.VENUES)
        self.assertNotIn('↔', text)
        self.assertNotIn('20–250', text)

    def test_panel_section_cover_and_promotion_image(self):
        c = Client()
        c.force_login(self.make_staff('owner'))
        group = Section.objects.filter(venue_id='kymyz', parent__isnull=False).first()
        r = c.get(f'/panel/catalog/sections/{group.pk}/')
        self.assertContains(r, 'id_cover')
        self.assertContains(c.get('/panel/promotions/new/'), 'Показать на главной')

    def test_device_app(self):
        member = self.make_member('+996555909090')
        self.auth(member)
        r = self.api.post('/api/v1/me/devices', {'token': 't-sk', 'platform': 'ios'}, format='json', **SK)
        self.assertEqual(r.status_code, 204, r.content)
        self.api.post('/api/v1/me/devices', {'token': 't-resort', 'platform': 'android'}, format='json')
        self.assertEqual(dict(Device.objects.values_list('token', 'app')), {'t-sk': 'sk', 't-resort': 'resort'})
