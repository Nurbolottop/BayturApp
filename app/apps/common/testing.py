"""Общие фикстуры для тестов."""
from datetime import date

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.models import ProgramSettings


class BaseAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        import io
        call_command('seed', stdout=io.StringIO())
        # акция из сида ограничена датой («до 30 сентября») — в тестах она должна действовать всегда
        from apps.catalog.models import ItemPromo
        ItemPromo.objects.update(starts_at=None, ends_at=None)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.api = APIClient()

    # ---------------------------------------------------------------- участники

    def make_member(self, phone='+996555000001', points=0, birthday=date(1990, 6, 15), **extra):
        from apps.loyalty.models import OperationKind
        from apps.loyalty.services import get_wallet, lock_wallet, post_operation
        from apps.members.models import Member
        m = Member.objects.create(phone=phone, first_name='Тест', last_name='Клиент', birthday=birthday, **extra)
        get_wallet(m)
        if points:
            from django.db import transaction
            with transaction.atomic():
                post_operation(lock_wallet(m), OperationKind.ADJUSTMENT, points, reason='test')
        return m

    def auth(self, member, client=None):
        from apps.members.auth import issue_tokens
        client = client or self.api
        tokens = issue_tokens(member)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {tokens["accessToken"]}')
        return tokens

    def wallet(self, member):
        from apps.loyalty.models import Wallet
        return Wallet.objects.get(member=member)

    # ---------------------------------------------------------------- сотрудники

    def make_staff(self, role='staff', outlets=(), email=None, phone=''):
        from apps.staff.models import StaffUser
        user = StaffUser.objects.create_user(email or f'{role}{StaffUser.objects.count()}@baytur.kg', 'Passw0rd!x',
                                             full_name=f'{role} user', role=role, phone=phone)
        if outlets:
            user.outlets.set(outlets)
        return user

    def staff_client(self, user):
        from apps.staff.auth import issue_tokens
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {issue_tokens(user)["accessToken"]}')
        return client

    def settings_obj(self, **fields):
        ps = ProgramSettings.get()
        for k, v in fields.items():
            setattr(ps, k, v)
        ps.save()
        return ps
