"""
SMS-провайдер не выбран (ТЗ §11). SMS_BACKEND=console пишет код в лог; реальный провайдер —
класс с методом send(phone, text) и строка в BACKENDS.
"""
import logging

from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)


class ConsoleSms:
    def send(self, phone, text):
        log.info('SMS → %s: %s', phone, text)
        cache.set(f'sms:last:{phone}', text, 600)  # для тестов и staging
        return True


BACKENDS = {'console': ConsoleSms}


def send_sms(phone, text):
    return BACKENDS[settings.SMS_BACKEND]().send(phone, text)
