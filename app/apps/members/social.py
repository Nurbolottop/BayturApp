"""
Проверка id_token Google и identityToken Apple: подпись по JWKS провайдера, iss, aud, срок.
Ключи провайдеров кешируются PyJWKClient на 1 час.

Apple: authorizationCode обменивается на refresh-токен, чтобы при удалении аккаунта отозвать доступ
(App Store 5.1.1(v)). Для этого нужен ключ .p8 (APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY_FILE).
"""
import hashlib
import logging
import os
import time

import jwt
import requests
from django.conf import settings

from apps.common.errors import ApiError

from .models import SocialProvider

log = logging.getLogger(__name__)
APPLE_URL = 'https://appleid.apple.com'

PROVIDERS = {
    SocialProvider.GOOGLE: {
        'jwks': 'https://www.googleapis.com/oauth2/v3/certs',
        'issuers': ['https://accounts.google.com', 'accounts.google.com'],
        'audience': 'GOOGLE_CLIENT_IDS',
    },
    SocialProvider.APPLE: {
        'jwks': 'https://appleid.apple.com/auth/keys',
        'issuers': ['https://appleid.apple.com'],
        'audience': 'APPLE_CLIENT_IDS',
    },
}

_clients = {}


def _jwks_client(provider):
    if provider not in _clients:
        _clients[provider] = jwt.PyJWKClient(PROVIDERS[provider]['jwks'], lifespan=3600, timeout=10)
    return _clients[provider]


def verify_token(provider, token, nonce=None):
    """→ {'subject', 'email'}; ApiError('social_invalid') на любой непрошедшей проверке."""
    conf = PROVIDERS[provider]
    audience = getattr(settings, conf['audience'])
    if not audience:
        raise ApiError('social_unavailable', 503)
    try:
        key = _jwks_client(provider).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'], audience=audience, issuer=conf['issuers'],
                            options={'require': ['iss', 'aud', 'exp', 'sub']}, leeway=60)
    except jwt.PyJWKClientConnectionError:
        raise ApiError('social_unavailable', 503)
    except jwt.PyJWTError:
        raise ApiError('social_invalid', 401)
    if nonce and claims.get('nonce') not in (nonce, hashlib.sha256(nonce.encode()).hexdigest()):
        raise ApiError('social_invalid', 401)
    email = claims.get('email') or ''
    # Google отдаёт и неподтверждённые email; Apple — только подтверждённые (или relay)
    if str(claims.get('email_verified', 'true')).lower() != 'true':
        email = ''
    aud = claims['aud']
    return {'subject': str(claims['sub']), 'email': email, 'audience': aud[0] if isinstance(aud, list) else aud}


# ---------------------------------------------------------------- Apple: обмен кода и отзыв

def apple_revocation_enabled():
    return bool(settings.APPLE_TEAM_ID and settings.APPLE_KEY_ID and settings.APPLE_PRIVATE_KEY_FILE
                and os.path.isfile(settings.APPLE_PRIVATE_KEY_FILE))


def _apple_client_secret(client_id):
    """JWT ES256, подписанный ключом .p8; Apple принимает срок до 6 месяцев, берём 5 минут."""
    with open(settings.APPLE_PRIVATE_KEY_FILE) as f:
        key = f.read()
    now = int(time.time())
    return jwt.encode({'iss': settings.APPLE_TEAM_ID, 'iat': now, 'exp': now + 300, 'aud': APPLE_URL,
                       'sub': client_id}, key, algorithm='ES256', headers={'kid': settings.APPLE_KEY_ID})


def apple_exchange_code(code, client_id):
    """authorizationCode → refresh-токен Apple. Ошибка не мешает входу: вернётся '' и отзыва не будет."""
    if not (code and apple_revocation_enabled()):
        return ''
    try:
        resp = requests.post(f'{APPLE_URL}/auth/token', timeout=10, data={
            'client_id': client_id, 'client_secret': _apple_client_secret(client_id),
            'code': code, 'grant_type': 'authorization_code'})
        if resp.status_code != 200:
            log.warning('apple code exchange failed: %s %s', resp.status_code, resp.text[:200])
            return ''
        return resp.json().get('refresh_token') or ''
    except (requests.RequestException, OSError, ValueError):
        log.exception('apple code exchange failed')
        return ''


def apple_revoke(client_id, refresh_token):
    """True — отозван (или уже недействителен). Сетевые ошибки пробрасываются — задача повторит."""
    if not apple_revocation_enabled():
        log.warning('apple revoke skipped: key not configured')
        return False
    resp = requests.post(f'{APPLE_URL}/auth/revoke', timeout=10, data={
        'client_id': client_id, 'client_secret': _apple_client_secret(client_id),
        'token': refresh_token, 'token_type_hint': 'refresh_token'})
    if resp.status_code == 200:
        return True
    if resp.status_code == 400 and 'invalid_grant' in resp.text:
        return True
    resp.raise_for_status()
    return False
