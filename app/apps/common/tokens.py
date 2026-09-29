"""JWT access (≈15 мин) + непрозрачный refresh (≈30 дней, хранится хешем, ротация)."""
import hashlib
import secrets
import uuid

import jwt
from django.conf import settings
from django.utils import timezone


def issue_access(kind, subject_id, **claims):
    now = timezone.now()
    payload = {
        'typ': kind,  # member | staff
        'sub': str(subject_id),
        'iat': int(now.timestamp()),
        'exp': int((now + settings.JWT_ACCESS_TTL).timestamp()),
        'jti': uuid.uuid4().hex,
        **claims,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access(token, kind):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get('typ') != kind:
        return None
    return payload


def new_refresh_value():
    return secrets.token_urlsafe(48)


def hash_token(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bearer_token(request):
    header = request.headers.get('Authorization', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return None
