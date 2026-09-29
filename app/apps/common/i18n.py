"""
Язык контента. Всё локализуемое хранится в БД как {"ru": ..., "ky": ..., "en": ...};
клиентский API отдаёт одну строку на языке из Accept-Language, пустой перевод → ru.
"""
import contextvars

from django.conf import settings

LANGS = tuple(settings.CONTENT_LANGUAGES)
DEFAULT = settings.DEFAULT_CONTENT_LANGUAGE

_current = contextvars.ContextVar('content_language', default=DEFAULT)


def parse_accept_language(header):
    """'ky-KG,ru;q=0.8' → 'ky'. Берём первый поддерживаемый язык по порядку q."""
    if not header:
        return DEFAULT
    candidates = []
    for i, part in enumerate(header.split(',')):
        piece = part.strip()
        if not piece:
            continue
        lang, _, params = piece.partition(';')
        q = 1.0
        if params.strip().startswith('q='):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 0
        candidates.append((-q, i, lang.strip().lower().split('-')[0]))
    for _, _, lang in sorted(candidates):
        if lang in LANGS:
            return lang
    return DEFAULT


def set_language(lang):
    return _current.set(lang if lang in LANGS else DEFAULT)


def current_language():
    return _current.get()


def tr(value, lang=None):
    """Перевод поля {ru, ky, en} с fallback на ru. Строки и None возвращаются как есть."""
    if value is None or isinstance(value, str):
        return value
    lang = lang or current_language()
    if isinstance(value, dict):
        text = value.get(lang)
        if text in (None, '', []):
            text = value.get(DEFAULT)
        return text
    return value


def l10n(ru, ky=None, en=None):
    """Удобный конструктор для сидов: l10n('Номера', 'Бөлмөлөр', 'Rooms')."""
    return {'ru': ru, 'ky': ky or '', 'en': en or ''}


def empty_l10n():
    return {lang: '' for lang in LANGS}


def missing_translations(value):
    """Список языков с пустым переводом."""
    if not isinstance(value, dict):
        return list(LANGS)
    return [lang for lang in LANGS if value.get(lang) in (None, '', [])]


def validate_l10n(value, required=True, allow_list=False):
    from django.core.exceptions import ValidationError
    if value in (None, {}) and not required:
        return
    if not isinstance(value, dict):
        raise ValidationError('Ожидается объект {ru, ky, en}')
    unknown = set(value) - set(LANGS)
    if unknown:
        raise ValidationError(f'Неизвестные языки: {", ".join(sorted(unknown))}')
    for lang, text in value.items():
        ok = isinstance(text, str) or (allow_list and isinstance(text, list) and all(isinstance(t, str) for t in text))
        if not ok and text is not None:
            raise ValidationError(f'{lang}: неверный тип')
    if required and value.get(DEFAULT) in (None, '', []):
        raise ValidationError('Обязателен русский вариант')


def iso(dt):
    """Дата-время ISO 8601 в таймзоне курорта: 2026-09-28T18:24:00+06:00."""
    if dt is None:
        return None
    from django.utils import timezone
    return timezone.localtime(dt).isoformat(timespec='seconds')
