"""
Публичные справочники (/catalog, /content/*, /loyalty/program, …): один кеш для гостей и
вошедших, ETag + Cache-Control: max-age=300. Любое изменение каталога/контента
увеличивает версию — кеш всех языков сбрасывается.
"""
import hashlib
import json

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from rest_framework.response import Response

from .i18n import current_language

VERSION_KEY = 'public_content_version'
MAX_AGE = 300


def content_version():
    v = cache.get(VERSION_KEY)
    if v is None:
        v = 1
        cache.set(VERSION_KEY, v, None)
    return v


def bump_content_version(*args, **kwargs):
    try:
        cache.incr(VERSION_KEY)
    except ValueError:
        cache.set(VERSION_KEY, 2, None)


def cached_public(name, builder, request, vary=''):
    """Строит ответ builder() один раз на (name, язык, версию); отвечает 304 по If-None-Match."""
    lang = current_language()
    key = f'pub:{name}:{vary}:{lang}:{content_version()}'
    entry = cache.get(key)
    if entry is None:
        data = builder()
        body = json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True)
        etag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'
        entry = {'data': data, 'etag': etag}
        cache.set(key, entry, 3600)
    headers = {
        'ETag': entry['etag'],
        'Cache-Control': f'public, max-age={MAX_AGE}',
        'Vary': 'Accept-Language',
        'Content-Language': lang,
    }
    inm = request.headers.get('If-None-Match', '')
    if entry['etag'] in [t.strip() for t in inm.split(',')]:
        return Response(status=304, headers=headers)
    return Response(entry['data'], headers=headers)
