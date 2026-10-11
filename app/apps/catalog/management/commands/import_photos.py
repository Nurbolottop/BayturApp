"""
Массовая загрузка фото по карте JSON: позиции, разделы, разделы программы, главная, объекты, «вечная новость».

    manage.py import_photos карта.json папка_с_файлами [--replace]

Карта: {"items": {"id": {"image": "a.jpg", "gallery": ["b.jpg", …]}}, "sections": {"id": {"cover": "c.jpg"}},
        "categories": {"rooms": {"cover": …}}, "venues": {"ski": {"cover": …}},
        "showcases": {"ski": {"hero_image": …, "hero_image_night": …}}, "eternal": {"ski": {"cover": …, "slides": […]}}}
Файл проходит ту же обработку, что загрузка из админки (без EXIF, ≤2560 px), и сохраняется под именем по
содержимому — повторный запуск не плодит копии. Заполненные поля не трогаются (--replace — заменить),
галерея дополняется без повторов.
"""
import hashlib
import json
import os

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Загрузить фото услуг, разделов и главной по карте JSON'

    def add_arguments(self, parser):
        parser.add_argument('mapping')
        parser.add_argument('folder')
        parser.add_argument('--replace', action='store_true', help='заменять уже заполненные поля')

    def handle(self, mapping, folder, replace=False, **opts):
        from apps.catalog.models import Category, EternalNews, Item, Section, Showcase, Venue
        from apps.common.caching import bump_content_version
        from apps.common.media import process_upload

        with open(mapping, encoding='utf-8') as fh:
            data = json.load(fh)
        stored = {}
        stats = {'files': 0, 'fields': 0, 'gallery': 0, 'missing': 0}

        def store(name):
            if name in stored:
                return stored[name]
            path = os.path.join(folder, name)
            if not os.path.exists(path):
                raise CommandError(f'Нет файла {path}')
            with open(path, 'rb') as fh:
                raw = fh.read()
            digest = hashlib.sha1(raw).hexdigest()[:20]
            for ext in ('jpg', 'png'):
                target = f'uploads/import/{digest}.{ext}'
                if default_storage.exists(target):
                    stored[name] = target
                    return target
            with open(path, 'rb') as fh:
                result = process_upload(fh)
            if result is None:
                raise CommandError(f'{name}: не изображение')
            content, ext = result[0], result[1]
            stored[name] = default_storage.save(f'uploads/import/{digest}.{ext}', content)
            stats['files'] += 1
            return stored[name]

        def set_fields(obj, values, single):
            changed = []
            for field in single:
                if values.get(field) and (replace or not getattr(obj, field)):
                    setattr(obj, field, store(values[field]))
                    changed.append(field)
            if values.get('gallery'):
                current = list(getattr(obj, 'gallery') or [])
                for name in values['gallery']:
                    path = store(name)
                    if path not in current and path != getattr(obj, 'image', None):
                        current.append(path)
                        stats['gallery'] += 1
                obj.gallery = current
                changed.append('gallery')
            if values.get('slides'):
                slides = list(obj.slides or [])
                for i, name in enumerate(values['slides']):
                    if i < len(slides) and (replace or not slides[i].get('image')):
                        slides[i] = {**slides[i], 'image': store(name)}
                obj.slides = slides
                changed.append('slides')
            if changed:
                obj.save(update_fields=changed)
                stats['fields'] += len(changed)

        groups = (
            ('items', Item, ('image',)), ('sections', Section, ('cover',)), ('categories', Category, ('cover',)),
            ('venues', Venue, ('cover', 'icon')),
        )
        for key, model, single in groups:
            for pk, values in (data.get(key) or {}).items():
                obj = model.objects.filter(pk=pk).first()
                if obj is None:
                    self.stderr.write(f'{key}: нет {pk}')
                    stats['missing'] += 1
                    continue
                set_fields(obj, values, single)
        for venue_id, values in (data.get('showcases') or {}).items():
            obj, _ = Showcase.objects.get_or_create(venue_id=venue_id)
            set_fields(obj, values, ('hero_image', 'hero_image_night'))
        for venue_id, values in (data.get('eternal') or {}).items():
            obj = EternalNews.objects.filter(show_in__contains=[venue_id]).first()
            if obj is None:
                self.stderr.write(f'eternal: нет новости для {venue_id}')
                stats['missing'] += 1
                continue
            set_fields(obj, values, ('cover',))
        bump_content_version()
        self.stdout.write(self.style.SUCCESS(
            f"Файлов загружено: {stats['files']}, полей: {stats['fields']}, в галереи: {stats['gallery']}, "
            f"не найдено: {stats['missing']}"))
