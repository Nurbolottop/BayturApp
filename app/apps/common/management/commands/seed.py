import io
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.common import seed_data as D


class Command(BaseCommand):
    help = ('Сид справочников из хардкода мобилки. Повторный запуск только добавляет недостающее и НЕ меняет '
            'записи, отредактированные в админке. --reset — вернуть данные сида (перезаписывает правки!).')

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Перезаписать существующие записи данными сида (правки из админки пропадут)')
        parser.add_argument('--redraw-placeholders', action='store_true',
                            help='Перерисовать сгенерированные заглушки seed/… (загруженные фото не трогает)')

    @transaction.atomic
    def handle(self, *args, **opts):
        self.redraw = opts.get('redraw_placeholders', False)
        reset = opts.get('reset', False)

        def upsert(model, lookup, defaults):
            """Без --reset существующая запись не трогается — правки из админки сохраняются."""
            if reset:
                return model.objects.update_or_create(**lookup, defaults=defaults)
            return model.objects.get_or_create(**lookup, defaults=defaults)
        from apps.catalog.models import Category, Item, ItemPromo, Outlet
        from apps.common.i18n import l10n
        from apps.common.models import ProgramSettings
        from apps.complaints.models import ComplaintCategory
        from apps.content.models import Article, Promo, PublishStatus, ResortEvent, Story, StorySlide
        from apps.loyalty.models import Privilege, Tier
        from apps.members.models import LegalDocument, LegalKind
        from apps.notifications.models import PushTemplate
        from apps.notifications.services import DEFAULT_TEMPLATES

        ProgramSettings.get().save()

        for oid, name, sort in D.OUTLETS:
            upsert(Outlet, {'id': oid}, {'name': name, 'sort_order': sort})

        for cid, title, sort, rate, share, methods in D.CATEGORIES:
            upsert(Category, {'id': cid}, {
                'title': title, 'sort_order': sort, 'rate': Decimal(rate), 'max_points_share': Decimal(share),
                'methods': methods, 'cover': f'seed/categories/{cid}.jpg'})

        promo_end = datetime(2026, 10, 1, tzinfo=ZoneInfo('Asia/Bishkek'))  # «до 30 сентября»
        for i, (iid, cat, outlet, title, meta, price, pricing, promo, tag, desc, features) in enumerate(D.ITEMS):
            item, created = upsert(Item, {'id': iid}, {
                'category_id': cat, 'outlet_id': outlet, 'title': title, 'meta': meta, 'price': price,
                'pricing': pricing, 'tag': tag or {}, 'description': desc, 'features': features, 'sort_order': i,
                'image': f'seed/items/{iid}.jpg', 'gallery': [f'seed/items/{iid}-2.jpg']})
            if promo and created and not item.promos.exists():
                ItemPromo.objects.create(item=item, rate=Decimal(promo[0]), tag=promo[1], ends_at=promo_end)

        for tid, name, frm in D.TIERS:
            upsert(Tier, {'id': tid}, {'name': name, 'from_points': frm})
        for i, (pid, tier, icon, title, short, desc) in enumerate(D.PRIVILEGES):
            upsert(Privilege, {'id': pid}, {
                'tier_id': tier, 'icon': icon, 'title': title, 'short': short, 'description': desc, 'sort_order': i})

        today = timezone.localdate()
        now = timezone.now()
        for a in D.ARTICLES:
            upsert(Article, {'id': a['id']}, {
                'category_id': a['category'], 'tag': a['tag'], 'title': a['title'], 'lead': a['lead'],
                'body': a['body'], 'quote': a['quote'], 'minutes': a['minutes'], 'image': a['image'],
                'date': today - timedelta(days=a['days_ago']), 'status': PublishStatus.PUBLISHED,
                'use_ru_fallback': True, 'published_at': now})
        for i, (aid, subtitle, cta) in enumerate(D.PROMOS):
            upsert(Promo, {'article_id': aid}, {
                'subtitle': subtitle, 'cta': cta, 'sort_order': i, 'status': PublishStatus.PUBLISHED,
                'use_ru_fallback': True, 'published_at': now, 'cutout': f'seed/promos/{aid}.png'})
        for i, (aid, when, place) in enumerate(D.EVENTS):
            upsert(ResortEvent, {'article_id': aid}, {
                'when': when, 'place': place, 'sort_order': i, 'status': PublishStatus.PUBLISHED,
                'use_ru_fallback': True, 'published_at': now})
        for i, (cat, (title, slides)) in enumerate(D.STORIES.items()):
            story, created = upsert(Story, {'category_id': cat}, {
                'title': title, 'cover': f'seed/stories/{cat}.jpg', 'sort_order': i,
                'status': PublishStatus.PUBLISHED, 'use_ru_fallback': True, 'published_at': now})
            if not (created or reset):
                continue
            story.slides.all().delete()
            for j, (st, text, item_id) in enumerate(slides):
                StorySlide.objects.create(story=story, title=st, text=text, item_id=item_id, sort_order=j,
                                          image=f'seed/stories/{cat}-{j + 1}.jpg')

        for i, (cid, title) in enumerate(D.COMPLAINT_CATEGORIES):
            upsert(ComplaintCategory, {'id': cid}, {'title': title, 'sort_order': i})

        for kind, (title, body) in DEFAULT_TEMPLATES.items():
            PushTemplate.objects.get_or_create(kind=kind, defaults={'title': title, 'body': body})

        base = 'https://baytur.kg'
        # Условия и политика — заглушки на сайте курорта: заменить в админке на реальные версии
        for kind, path in ((LegalKind.TERMS, 'terms'), (LegalKind.PRIVACY, 'privacy')):
            LegalDocument.objects.get_or_create(kind=kind, version='1.0', defaults={
                'url': l10n(f'{base}/ru/{path}', f'{base}/ky/{path}', f'{base}/en/{path}'),
                'requires_acceptance': True, 'published_at': now})
        # Страница удаления аккаунта без приложения — наша /account/delete (Google Play)
        from django.conf import settings
        page = f'{settings.PUBLIC_BASE_URL}/account/delete'
        upsert(LegalDocument, {'kind': LegalKind.DELETION, 'version': '1.0'}, {
            'url': l10n(f'{page}?lang=ru', f'{page}?lang=ky', f'{page}?lang=en'),
            'requires_acceptance': False, 'published_at': now})

        made = self._placeholders()

        self.stdout.write(self.style.SUCCESS(
            f'Заглушек картинок создано: {made}. '
            f'Сид: {Category.objects.count()} категорий, {Item.objects.count()} услуг, {Tier.objects.count()} уровней, '
            f'{Privilege.objects.count()} привилегий, {Article.objects.count()} статей.'))

    # ---------------------------------------------------------------- заглушки картинок

    COLORS = {  # цвета разделов: градиент сверху вниз
        'rooms': ('#3F4A56', '#C3CCD6'), 'spa': ('#2A3314', '#C6F24E'), 'food': ('#5E4206', '#E6BF58'),
        'pools': ('#1C3A5E', '#8FD8FF'), 'sport': ('#4A220F', '#D9976A'), None: ('#232C38', '#B4C2D3'),
    }

    def _placeholders(self):
        """
        Фото мобилки (assets/images/) в бек ещё не переданы. Чтобы API и админка не отдавали битые ссылки,
        для каждого пути seed/… без файла рисуется градиентная заглушка в цвете раздела.
        Загруженные позже настоящие фото заменяют ссылку — заглушка просто перестаёт использоваться.
        """
        from apps.catalog.models import Category, Item
        from apps.content.models import Article, Promo, Story

        wanted = {}  # path → (category, png)
        for c in Category.objects.all():
            wanted[c.cover] = (c.id, False)
        for i in Item.objects.all():
            for path in [i.image, *(i.gallery or [])]:
                wanted[path] = (i.category_id, False)
        for a in Article.objects.all():
            wanted[a.image] = (a.category_id, False)
        for p in Promo.objects.select_related('article'):
            wanted[p.cutout] = (p.article.category_id, True)
        for st in Story.objects.prefetch_related('slides'):
            wanted[st.cover] = (st.category_id, False)
            for sl in st.slides.all():
                wanted[sl.image] = (st.category_id, False)
        made = 0
        for path, (cat, png) in wanted.items():
            if not path or not path.startswith('seed/'):
                continue
            if default_storage.exists(path):
                if not self.redraw:
                    continue
                default_storage.delete(path)
            default_storage.save(path, ContentFile(self._draw(cat, png, variant=made)))
            made += 1
        return made

    def _draw(self, category, png, variant=0, size=(1200, 800)):
        from PIL import Image, ImageDraw
        top, bottom = (tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in self.COLORS.get(category, self.COLORS[None]))
        w, h = size
        if png:  # вырезка для баннера: круг с прозрачным фоном
            img = Image.new('RGBA', (600, 600), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((40, 40, 560, 560), fill=bottom + (255,))
            d.ellipse((140, 140, 460, 460), fill=top + (255,))
            buf = io.BytesIO()
            img.save(buf, 'PNG')
            return buf.getvalue()
        img = Image.new('RGB', size)
        d = ImageDraw.Draw(img)
        for y in range(h):
            t = y / (h - 1)
            d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
        # мягкие «холмы» в тонах раздела — чтобы заглушки различались между собой
        def mix(t):
            return tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        shift = (variant * 137) % w
        for k, tone in ((0, 0.55), (1, 0.35)):
            y0 = int(h * (0.58 + 0.12 * k))
            cx = shift + k * 380 - w // 3
            d.ellipse((cx - w * 0.7, y0, cx + w * 0.7, y0 + h * 0.9), fill=mix(tone))
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=82)
        return buf.getvalue()
