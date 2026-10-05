import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)

PREVIEW_KEY = 'loyalty:period_close_preview'


@shared_task
def close_periods():
    """Закрытие периода у клиентов с истёкшим периодом; продолжает с места остановки (каждый — своя транзакция)."""
    from .engine import close_due_periods
    from .models import Wallet
    if not Wallet.objects.filter(period_end__lte=timezone.now()).exists():
        return None
    return close_due_periods()


@shared_task
def daily_achievements():
    from .engine import daily_achievements as run
    return run()


@shared_task
def reconcile():
    from .services import reconcile as run
    result = run()
    return {'ledger': len(result['ledger']), 'tiers': len(result['tiers'])}


@shared_task
def warn_at_risk():
    from .engine import warn_at_risk as run
    return run()


@shared_task
def preview_close(force=False):
    """С 1 декабря раз в сутки — предпросмотр закрытия года для админки."""
    from .engine import preview_period_close
    now = timezone.localtime()
    if not force and now.month != 12:
        return None
    data = {**preview_period_close(), 'at': now.isoformat()}
    cache.set(PREVIEW_KEY, data, None)
    return data
