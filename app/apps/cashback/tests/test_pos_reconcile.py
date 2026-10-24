import io
from datetime import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.cashback.models import CashbackRequest, PosReconciliation
from apps.catalog.models import Outlet
from apps.common.testing import BaseAPITestCase

S = '/api/v1/staff'


class PosReconcileTests(BaseAPITestCase):
    """Оплаты «Баллы BAYTUR» из выгрузки R-Keeper сверяются со списаниями по коду из 6 цифр."""

    def setUp(self):
        super().setUp()
        Outlet.objects.filter(pk='davinci').update(receipt_required=True)
        self.member = self.make_member(points=50_000)               # 5 000 сом
        self.desk = self.staff_client(self.make_staff('staff', outlets=['davinci']))
        self.owner = Client()
        self.owner.force_login(self.make_staff('owner', email='boss@b.kg'))

    def charge(self, amount):
        self.auth(self.member)
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        token = self.desk.post(f'{S}/scan', {'token': qr}, format='json').json()['payToken']
        with self.captureOnCommitCallbacks(execute=True):
            r = self.desk.post(f'{S}/points/charge', {'payToken': token, 'itemId': 'food-davinci',
                                                      'checkAmount': amount}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def xlsx(self, rows):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(['Отчёт по оплатам', None, None, None, None])
        ws.append(['Дата', 'Чек', 'Кассир', 'Сумма', 'Комментарий'])
        for r in rows:
            ws.append(r)
        ws.append(['Итого', None, None, sum(r[3] for r in rows), None])
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile('rkeeper.xlsx', buf.getvalue())

    def test_points_payment_has_pos_code(self):
        d = self.charge(1000)
        self.assertRegex(d['posCode'], r'^\d{6}$')
        self.assertEqual(CashbackRequest.objects.get(pk=d['id']).pos_code, d['posCode'])

    def test_reconcile(self):
        ok = self.charge(1000)
        big = self.charge(800)
        missing = self.charge(500)
        now = datetime.now()
        f = self.xlsx([
            [now, '101', 'Айбек', 1000, f'BAYTUR {ok["posCode"]}'],           # совпало
            [now, '102', 'Айбек', 1200, ''],                                   # без кода — подозрительно
            [now, '103', 'Нурлан', 900, big['posCode']],                       # больше списанного
            [now, '104', 'Нурлан', 300, '999999'],                             # кода нет у нас
        ])
        r = self.owner.post('/panel/pos/', {'file': f})
        self.assertEqual(r.status_code, 302, r.content)
        rec = PosReconciliation.objects.get()
        self.assertEqual((rec.summary['ok'], rec.summary['red'], rec.summary['yellow'], rec.summary['orange']),
                         (1, 2, 1, 1))
        self.assertEqual(rec.summary['redSum'], 1500)
        self.assertEqual([m['id'] for m in rec.result['missing']], [missing['id']])
        page = self.owner.get(f'/panel/pos/{rec.pk}/')
        self.assertContains(page, 'Нет кода BAYTUR')
        self.assertContains(page, 'Айбек')
        self.assertEqual(self.owner.get('/panel/pos/').status_code, 200)

    def test_csv_cp1251(self):
        ok = self.charge(1000)
        text = f'Дата;Сумма;Комментарий;Кассир\n{datetime.now():%d.%m.%Y %H:%M};1 000,00;{ok["posCode"]};Айбек\n'
        f = SimpleUploadedFile('rkeeper.csv', text.encode('cp1251'))
        self.owner.post('/panel/pos/', {'file': f})
        self.assertEqual(PosReconciliation.objects.get().summary['ok'], 1)

    def test_bad_file(self):
        r = self.owner.post('/panel/pos/', {'file': SimpleUploadedFile('x.csv', 'a;b\n1;2\n'.encode())}, follow=True)
        self.assertContains(r, 'Сумма')
        self.assertFalse(PosReconciliation.objects.exists())
