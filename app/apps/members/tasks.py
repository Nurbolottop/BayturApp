import requests
from celery import shared_task


@shared_task(autoretry_for=(requests.RequestException,), retry_backoff=60, max_retries=8)
def revoke_apple_token(client_id, refresh_token):
    from .social import apple_revoke
    return apple_revoke(client_id, refresh_token)
