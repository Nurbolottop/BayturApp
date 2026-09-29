from celery import shared_task


@shared_task
def run_export(job_id):
    """Фоновая выгрузка отчёта (ExportJob) в XLSX / CSV."""
    from .exports import run_job
    job = run_job(job_id)
    return job.status if job else None
