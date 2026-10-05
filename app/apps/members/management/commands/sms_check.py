"""Проверка SMS-провайдера: доступ, состояние аккаунта и баланс (без отправки); --send — тестовая SMS."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.members.sms import SmsError, backend


class Command(BaseCommand):
    help = 'Проверить SMS-провайдера: баланс и доступ; --send +996XXXXXXXXX — отправить тестовую SMS'

    def add_arguments(self, parser):
        parser.add_argument('--send', metavar='PHONE', help='номер для тестовой SMS (E.164)')

    def handle(self, *args, **opts):
        sms = backend()
        self.stdout.write(f'SMS_BACKEND={settings.SMS_BACKEND}')
        if hasattr(sms, 'info'):
            data = sms.info()
            if data.get('status') != '0':
                raise CommandError(f'Nikita отказала: status={data.get("status")} '
                                   '(2 — неверный логин/пароль, 3 — IP сервера не разрешён в кабинете)')
            state = 'активен' if data.get('state') == '0' else 'НЕ активен или заблокирован'
            self.stdout.write(f'Аккаунт {state}; баланс {data.get("account")}; цена SMS {data.get("smsprice")}; '
                              f'отправитель {settings.NIKITA_SENDER or "—"}; тестовый режим {settings.NIKITA_TEST}')
        if opts['send']:
            try:
                sms.send(opts['send'], 'BAYTUR: проверка SMS')
            except SmsError as e:
                raise CommandError(f'SMS не принята: {e}')
            self.stdout.write(self.style.SUCCESS(f'SMS принята к отправке на {opts["send"]}'))
