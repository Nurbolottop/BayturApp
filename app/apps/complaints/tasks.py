from celery import shared_task


@shared_task
def notify_overdue():
    from .services import notify_overdue as run
    return run()
