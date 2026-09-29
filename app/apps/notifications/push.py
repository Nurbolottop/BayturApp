"""
Отправка push. PUSH_BACKEND=console — пишет в лог (dev/staging), fcm — FCM HTTP v1
(нужен JSON сервисного аккаунта Firebase в FCM_CREDENTIALS_FILE и пакет google-auth).
"""
import json
import logging

from django.conf import settings

log = logging.getLogger(__name__)


class ConsoleBackend:
    def send(self, token, platform, title, body, data):
        log.info('PUSH → %s…: %s | %s | %s', token[:12], title, body, data)
        return True, False  # (ok, token_invalid)


class FcmBackend:
    SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'

    def __init__(self):
        from google.oauth2 import service_account  # noqa: import at use — пакет нужен только для fcm
        self.creds = service_account.Credentials.from_service_account_file(settings.FCM_CREDENTIALS_FILE,
                                                                           scopes=[self.SCOPE])
        with open(settings.FCM_CREDENTIALS_FILE) as fh:
            self.project_id = json.load(fh)['project_id']

    def _token(self):
        from google.auth.transport.requests import Request
        if not self.creds.valid:
            self.creds.refresh(Request())
        return self.creds.token

    def send(self, token, platform, title, body, data):
        import requests
        message = {
            'message': {
                'token': token,
                'notification': {'title': title, 'body': body},
                'data': {k: str(v) for k, v in (data or {}).items() if v is not None},
                'apns': {'payload': {'aps': {'sound': 'default'}}},
                'android': {'priority': 'high'},
            }
        }
        resp = requests.post(f'https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send',
                             json=message, headers={'Authorization': f'Bearer {self._token()}'}, timeout=10)
        if resp.status_code == 200:
            return True, False
        invalid = resp.status_code == 404 or 'UNREGISTERED' in resp.text
        log.warning('FCM error %s: %s', resp.status_code, resp.text[:300])
        return False, invalid


_backend = None


def backend():
    global _backend
    if _backend is None:
        _backend = FcmBackend() if settings.PUSH_BACKEND == 'fcm' else ConsoleBackend()
    return _backend
