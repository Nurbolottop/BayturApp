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

    def __init__(self, credentials_file=None):
        from google.oauth2 import service_account  # noqa: import at use — пакет нужен только для fcm
        credentials_file = credentials_file or settings.FCM_CREDENTIALS_FILE
        self.creds = service_account.Credentials.from_service_account_file(credentials_file, scopes=[self.SCOPE])
        with open(credentials_file) as fh:
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
        # токен устройства больше не действителен → устройство удаляется из базы
        invalid = resp.status_code == 404 or 'UNREGISTERED' in resp.text or (
            resp.status_code == 400 and 'registration token' in resp.text.lower())
        log.warning('FCM error %s: %s', resp.status_code, resp.text[:300])
        return False, invalid


_backends = {}


def backend(app='resort'):
    """
    Отправитель для приложения: у Baytur S&K может быть свой проект Firebase (FCM_CREDENTIALS_FILE_SK);
    если не задан — тот же, что у bayturapp (оба приложения в одном проекте Firebase).
    """
    sk_file = getattr(settings, 'FCM_CREDENTIALS_FILE_SK', '')
    key = 'sk' if app == 'sk' and sk_file else 'resort'
    if key not in _backends:
        if settings.PUSH_BACKEND != 'fcm':
            _backends[key] = ConsoleBackend()
        else:
            _backends[key] = FcmBackend(sk_file if key == 'sk' else None)
    return _backends[key]
