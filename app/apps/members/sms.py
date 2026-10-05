"""
Отправка SMS. SMS_BACKEND:
  console — код пишется в лог и кеш (dev, тесты);
  nikita  — smspro.nikita.kg, XML-протокол /api/message (логин, пароль, подтверждённое имя отправителя).
Код, срок жизни и попытки — наши (auth.request_otp/check_otp); провайдер только доставляет текст.
"""
import logging
import secrets
import time
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)


class SmsError(Exception):
    """SMS не принято провайдером — код клиенту не придёт."""


class ConsoleSms:
    def send(self, phone, text):
        log.info('SMS → %s: %s', phone, text)
        cache.set(f'sms:last:{phone}', text, 600)  # для тестов и staging
        return True


class NikitaSms:
    """https://smspro.nikita.kg/kg/documents/smspro.nikita.kg-XML-api.pdf"""

    URL = 'https://smspro.nikita.kg/api'
    STATUS = {
        1: 'ошибка в формате запроса', 2: 'неверный логин или пароль', 3: 'IP сервера не разрешён в кабинете',
        4: 'недостаточно средств', 5: 'имя отправителя не подтверждено', 6: 'текст заблокирован по стоп-словам',
        7: 'некорректный номер', 8: 'неверный формат времени', 9: 'шлюз перегружен',
        10: 'повтор id сообщения',
    }

    def _post(self, path, xml):
        resp = requests.post(f'{self.URL}/{path}', data=xml.encode('utf-8'), timeout=15,
                             headers={'Content-Type': 'application/xml; charset=utf-8'})
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
        # ответы /api/info и /api/def — в пространстве имён Giper.mobi; ищем поля без учёта namespace
        return {el.tag.rsplit('}', 1)[-1]: (el.text or '').strip() for el in root}

    def _auth(self):
        return (f'<login>{escape(settings.NIKITA_LOGIN)}</login>'
                f'<pwd>{escape(settings.NIKITA_PASSWORD)}</pwd>')

    def send(self, phone, text):
        msg_id = secrets.token_hex(6)  # ≤ 12 латинских букв и цифр, уникален на каждую отправку
        xml = ('<?xml version="1.0" encoding="UTF-8"?><message>' + self._auth() +
               f'<id>{msg_id}</id><sender>{escape(settings.NIKITA_SENDER)}</sender>'
               f'<text>{escape(text)}</text><phones><phone>{escape(phone.lstrip("+"))}</phone></phones>' +
               ('<test>1</test>' if settings.NIKITA_TEST else '') + '</message>')
        for attempt in range(2):
            try:
                data = self._post('message', xml)
            except (requests.RequestException, ElementTree.ParseError) as e:
                log.error('nikita sms %s: сеть/ответ: %s', msg_id, e)
                raise SmsError(str(e)) from e
            status = int(data.get('status') or -1)
            if status == 9 and attempt == 0:  # шлюз просит повторить с тем же id через 5–10 с
                time.sleep(5)
                continue
            break
        if status in (0, 11):  # 11 — тестовый режим: принято без отправки и списания
            log.info('nikita sms %s → %s принято (status=%s, частей=%s)', msg_id, phone, status, data.get('smscnt'))
            return True
        reason = self.STATUS.get(status, data.get('message') or 'неизвестная ошибка')
        log.error('nikita sms %s → %s отклонено: status=%s %s', msg_id, phone, status, reason)
        raise SmsError(f'status {status}: {reason}')

    def info(self):
        """Баланс и состояние аккаунта (запрос не тарифицируется) — для проверки настроек."""
        xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<info xmlns="http://Giper.mobi/schema/Info">' + self._auth() + '</info>')
        return self._post('info', xml)


BACKENDS = {'console': ConsoleSms, 'nikita': NikitaSms}


def backend():
    return BACKENDS[settings.SMS_BACKEND]()


def send_sms(phone, text):
    """SmsError, если провайдер не принял сообщение."""
    return backend().send(phone, text)
