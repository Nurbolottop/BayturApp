from celery import shared_task


@shared_task
def deliver_delayed():
    from .services import deliver_delayed as run
    return run()


@shared_task
def send_scheduled_campaigns():
    from .services import send_scheduled_campaigns as run
    return run()


@shared_task
def send_campaign_task(campaign_id):
    from .services import send_campaign
    send_campaign(campaign_id)


@shared_task
def deliver_notification(notification_id):
    from .models import Notification
    from .services import deliver
    n = Notification.objects.select_related('member').filter(pk=notification_id, push_status='queued').first()
    if n:
        deliver(n)


@shared_task
def notify_staff_paid_online_task(request_id):
    from .services import notify_staff_paid_online
    return notify_staff_paid_online(request_id)
