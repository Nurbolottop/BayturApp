from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Сверка: balance кошелька == Σ операций журнала; reserved == Σ баллов заявок в pending.'

    def handle(self, *args, **opts):
        from django.db.models import Sum

        from apps.cashback.models import CashbackRequest, RequestStatus
        from apps.loyalty.models import Wallet
        from apps.loyalty.services import ledger_mismatches

        bad = ledger_mismatches()
        reserved = dict(CashbackRequest.objects.filter(status=RequestStatus.PENDING).values_list('member_id')
                        .annotate(s=Sum('points')))
        bad_reserved = [(w.member_id, w.reserved, reserved.get(w.member_id, 0)) for w in Wallet.objects.all()
                        if w.reserved != reserved.get(w.member_id, 0)]
        for m, bal, total in bad:
            self.stdout.write(self.style.ERROR(f'member {m}: balance {bal} != ledger {total}'))
        for m, res, total in bad_reserved:
            self.stdout.write(self.style.ERROR(f'member {m}: reserved {res} != pending {total}'))
        if not bad and not bad_reserved:
            self.stdout.write(self.style.SUCCESS(f'OK: {Wallet.objects.count()} кошельков сходятся с журналом'))
