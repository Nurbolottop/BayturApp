from celery import shared_task
from django.core.cache import cache
from django.utils import timezone


@shared_task
def bump_on_promo_boundaries():
    """Акция началась/закончилась → сбросить кеш каталога (ставка и бейдж снимаются сами)."""
    from apps.common.caching import bump_content_version

    from .models import ItemPromo
    now = timezone.now()
    last = cache.get('promo_boundary_check') or now
    crossed = ItemPromo.objects.filter(starts_at__gt=last, starts_at__lte=now).exists() or \
        ItemPromo.objects.filter(ends_at__gt=last, ends_at__lte=now).exists()
    if not crossed:
        # акции на цену: включились/выключились по датам, дням недели или часам с прошлой проверки
        from .models import Promotion
        from .promotions import is_active_at
        crossed = any(is_active_at(p, last) != is_active_at(p, now) for p in Promotion.objects.filter(is_active=True))
    cache.set('promo_boundary_check', now, None)
    if crossed:
        bump_content_version()
    return crossed
