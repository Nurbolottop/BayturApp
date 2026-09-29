from celery import shared_task


@shared_task
def expire_payments():
    from .services import expire_payments as run
    return run()


@shared_task
def resolve_orphan_payments():
    from .services import resolve_orphan_payments as run
    return run()
