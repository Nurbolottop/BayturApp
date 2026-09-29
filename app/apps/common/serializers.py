from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .i18n import LANGS, tr, validate_l10n
from .media import absolute_media_url


class L10nField(serializers.JSONField):
    """
    Локализуемое поле. Клиентский API: одна строка на языке запроса.
    Админ-API (context['full_l10n']=True): объект {ru, ky, en} на вход и выход.
    """

    def __init__(self, *args, allow_list=False, required_ru=True, **kwargs):
        self.allow_list = allow_list
        self.required_ru = required_ru
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        if self.context.get('full_l10n'):
            value = value or {}
            empty = [] if self.allow_list else ''
            return {lang: value.get(lang, empty) or empty for lang in LANGS}
        return tr(value)

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = {'ru': data}
        try:
            validate_l10n(data, required=self.required_ru and self.required, allow_list=self.allow_list)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return {k: v for k, v in (data or {}).items() if k in LANGS}


class MediaUrlField(serializers.CharField):
    """В БД — путь в хранилище или внешний URL; в API — абсолютный URL."""

    def __init__(self, **kwargs):
        kwargs.setdefault('allow_blank', True)
        kwargs.setdefault('allow_null', True)
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return absolute_media_url(value) if value else None

    def to_internal_value(self, data):
        from django.conf import settings
        data = super().to_internal_value(data) or ''
        # URL, выданный /uploads, храним как относительный путь
        for prefix in (settings.PUBLIC_BASE_URL + settings.MEDIA_URL, settings.MEDIA_URL):
            if data.startswith(prefix):
                return data[len(prefix):]
        return data


def localized(value):
    return tr(value)


def media(value):
    return absolute_media_url(value) if value else None
