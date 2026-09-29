from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.common import seed_data as D


class Command(BaseCommand):
    help = 'Сид справочников из хардкода мобилки (идемпотентно: повторный запуск обновляет записи).'

    @transaction.atomic
    def handle(self, *args, **opts):
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
            Outlet.objects.update_or_create(id=oid, defaults={'name': name, 'sort_order': sort})

        for cid, title, sort, rate, share, methods in D.CATEGORIES:
            Category.objects.update_or_create(id=cid, defaults={
                'title': title, 'sort_order': sort, 'rate': Decimal(rate), 'max_points_share': Decimal(share),
                'methods': methods, 'cover': f'seed/categories/{cid}.jpg'})

        promo_end = datetime(2026, 10, 1, tzinfo=ZoneInfo('Asia/Bishkek'))  # «до 30 сентября»
        for i, (iid, cat, outlet, title, meta, price, pricing, promo, tag, desc, features) in enumerate(D.ITEMS):
            item, _ = Item.objects.update_or_create(id=iid, defaults={
                'category_id': cat, 'outlet_id': outlet, 'title': title, 'meta': meta, 'price': price,
                'pricing': pricing, 'tag': tag or {}, 'description': desc, 'features': features, 'sort_order': i,
                'image': f'seed/items/{iid}.jpg', 'gallery': [f'seed/items/{iid}-2.jpg']})
            if promo and not item.promos.exists():
                ItemPromo.objects.create(item=item, rate=Decimal(promo[0]), tag=promo[1], ends_at=promo_end)

        for tid, name, frm in D.TIERS:
            Tier.objects.update_or_create(id=tid, defaults={'name': name, 'from_points': frm})
        for i, (pid, tier, icon, title, short, desc) in enumerate(D.PRIVILEGES):
            Privilege.objects.update_or_create(id=pid, defaults={
                'tier_id': tier, 'icon': icon, 'title': title, 'short': short, 'description': desc, 'sort_order': i})

        today = timezone.localdate()
        now = timezone.now()
        for a in D.ARTICLES:
            Article.objects.update_or_create(id=a['id'], defaults={
                'category_id': a['category'], 'tag': a['tag'], 'title': a['title'], 'lead': a['lead'],
                'body': a['body'], 'quote': a['quote'], 'minutes': a['minutes'], 'image': a['image'],
                'date': today - timedelta(days=a['days_ago']), 'status': PublishStatus.PUBLISHED,
                'use_ru_fallback': True, 'published_at': now})
        for i, (aid, subtitle, cta) in enumerate(D.PROMOS):
            Promo.objects.update_or_create(article_id=aid, defaults={
                'subtitle': subtitle, 'cta': cta, 'sort_order': i, 'status': PublishStatus.PUBLISHED,
                'use_ru_fallback': True, 'published_at': now, 'cutout': f'seed/promos/{aid}.png'})
        for i, (aid, when, place) in enumerate(D.EVENTS):
            ResortEvent.objects.update_or_create(article_id=aid, defaults={
                'when': when, 'place': place, 'sort_order': i, 'status': PublishStatus.PUBLISHED,
                'use_ru_fallback': True, 'published_at': now})
        for i, (cat, (title, slides)) in enumerate(D.STORIES.items()):
            story, _ = Story.objects.update_or_create(category_id=cat, defaults={
                'title': title, 'cover': f'seed/stories/{cat}.jpg', 'sort_order': i,
                'status': PublishStatus.PUBLISHED, 'use_ru_fallback': True, 'published_at': now})
            story.slides.all().delete()
            for j, (st, text, item_id) in enumerate(slides):
                StorySlide.objects.create(story=story, title=st, text=text, item_id=item_id, sort_order=j,
                                          image=f'seed/stories/{cat}-{j + 1}.jpg')

        for i, (cid, title) in enumerate(D.COMPLAINT_CATEGORIES):
            ComplaintCategory.objects.update_or_create(id=cid, defaults={'title': title, 'sort_order': i})

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
        LegalDocument.objects.update_or_create(kind=LegalKind.DELETION, version='1.0', defaults={
            'url': l10n(f'{page}?lang=ru', f'{page}?lang=ky', f'{page}?lang=en'),
            'requires_acceptance': False, 'published_at': now})

        self.stdout.write(self.style.SUCCESS(
            f'Сид: {Category.objects.count()} категорий, {Item.objects.count()} услуг, {Tier.objects.count()} уровней, '
            f'{Privilege.objects.count()} привилегий, {Article.objects.count()} статей.'))
