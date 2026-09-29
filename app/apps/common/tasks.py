import logging

from celery import shared_task

log = logging.getLogger(__name__)


@shared_task
def daily_maintenance():
    """Раз в час проверяет суточные работы; каждая сама решает, пора ли ей."""
    from apps.analytics.services import purge_old_events
    from apps.loyalty.services import expire_inactive_wallets, warn_expiring_points
    from apps.members.services import purge_due_members
    from apps.notifications.services import purge_old_notifications

    for job in (purge_due_members, expire_inactive_wallets, warn_expiring_points,
                purge_old_notifications, purge_old_events):
        try:
            job()
        except Exception:
            log.exception('maintenance job failed: %s', job.__name__)
