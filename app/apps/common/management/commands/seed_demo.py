from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = ('Демо-сид для staging (ТЗ §6): профиль BT-048219, баланс 845 000, lifetime 845 000 (Золото), '
            'три операции; тестовый аккаунт для сторов.')

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Разрешить вне dev/staging')
        parser.add_argument('--test-phone', default='+996700000000')
        parser.add_argument('--test-code', default='1234')

    @transaction.atomic
    def handle(self, *args, **opts):
        if settings.APP_ENV == 'production' and not opts['force']:
            raise CommandError('Демо-сид не запускается в production')
        from apps.common.models import ProgramSettings
        from apps.loyalty.models import Operation, OperationKind, Tier, Wallet
        from apps.members.models import Member

        member, created = Member.objects.get_or_create(member_id='BT-048219', defaults={
            'phone': '+996555123456', 'first_name': 'Урмат', 'last_name': 'Асанов',
            'email': 'urmat@example.com', 'birthday': date(1994, 5, 14), 'member_since': date(2023, 6, 1),
            'marketing_consent': True})
        if created or not member.operations.exists():
            now = timezone.now()
            ops = [
                (OperationKind.CASHBACK, 483_000, 'room-deluxe', 'rooms', 20),
                (OperationKind.SPEND, -150_000, 'food-davinci', 'food', 10),
                (OperationKind.CASHBACK, 24_500, 'spa-stone', 'spa', 3),
            ]
            for kind, points, item, cat, days in ops:
                Operation.objects.create(member=member, kind=kind, points=points, item_id=item, category=cat,
                                         at=now - timedelta(days=days), affects_lifetime=points > 0)
            # Итог по ТЗ: баланс 845 000, lifetime 845 000. Операций в сиде три, поэтому остаток
            # до 845 000 оформлен начальной корректировкой (перенос баланса демо-профиля).
            balance = sum(p for _, p, *_ in ops)
            Operation.objects.create(member=member, kind=OperationKind.ADJUSTMENT, points=845_000 - balance,
                                     reason='Перенос баланса демо-профиля', at=now - timedelta(days=30))
            Wallet.objects.update_or_create(member=member, defaults={
                'balance': 845_000, 'reserved': 0, 'lifetime': 845_000, 'tier': Tier.objects.get(pk='gold'),
                'last_activity_at': now - timedelta(days=3)})

        ps = ProgramSettings.get()
        ps.test_enabled = True
        ps.test_phone = opts['test_phone']
        ps.test_code = opts['test_code']
        ps.save()
        self._store_account(opts['test_phone'])
        self.stdout.write(self.style.SUCCESS(
            f'Демо: {member.member_id} {member.phone}. Тестовый номер для сторов: {ps.test_phone} / код {ps.test_code}'))

    def _store_account(self, phone):
        """Тестовый аккаунт для проверяющих: баллы, история и заявки во всех статусах; не попадает в отчёты."""
        from apps.cashback import services as cs
        from apps.cashback.models import RejectReason
        from apps.loyalty.models import OperationKind
        from apps.loyalty.services import lock_wallet, post_operation
        from apps.members.models import Member

        member, created = Member.objects.get_or_create(phone=phone, defaults={
            'first_name': 'App', 'last_name': 'Review', 'birthday': date(1990, 1, 1), 'is_test': True})
        if not created:
            return
        wallet = lock_wallet(member)
        post_operation(wallet, OperationKind.ADJUSTMENT, 300_000, reason='Тестовый баланс для проверки сторов')
        make = lambda item, qty=1, pts=0, method='cash': cs.create_request(  # noqa: E731
            member, {'itemId': item, 'quantity': qty, 'pointsSom': pts, 'method': method})[0]
        pending = make('spa-stone')                              # pending — оставляем без автоподтверждения
        type(pending).objects.filter(pk=pending.pk).update(auto_confirm_at=None)
        cs.confirm_request(make('sport-gym').pk)                 # confirmed
        r = cs.confirm_request(make('spa-bochka', 2, 1000).pk)   # credited
        cs.credit_request(r.pk)
        cs.reject_request(make('pools-thermal').pk, code=RejectReason.NOT_PROVIDED)  # rejected
        cs.cancel_request(member, make('sport-tennis').pk)      # cancelled
