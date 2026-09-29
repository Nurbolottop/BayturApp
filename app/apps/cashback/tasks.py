from celery import shared_task


@shared_task
def process_due_requests():
    from .services import process_due
    return process_due()


@shared_task
def credit_request_task(req_id):
    from .services import credit_request
    credit_request(req_id)


@shared_task
def auto_confirm_task(req_id):
    from .models import CashbackRequest, RequestStatus
    from .services import confirm_request
    from django.utils import timezone
    req = CashbackRequest.objects.filter(pk=req_id, status=RequestStatus.PENDING,
                                         auto_confirm_at__lte=timezone.now()).first()
    if req:
        confirm_request(req.pk)
