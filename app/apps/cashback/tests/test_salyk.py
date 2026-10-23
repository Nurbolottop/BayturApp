from unittest import mock
from urllib.parse import parse_qs, urlsplit

import requests
from django.core.cache import cache
from django.test import override_settings

from apps.cashback.receipts import parse_receipt
from apps.common.errors import ApiError
from apps.common.testing import BaseAPITestCase

QR = ('https://tax.salyk.kg/tax-web-control/client/api/v1/ticket?date=20261008T030337&type=3&operation_type=1'
      '&fn_number=0000000002300267&fd_number=99340&fm=1643235591740&tin=21804199500937'
      '&regNumber=0000000000182425&sum=24000')

# ответ налоговой на этот QR (реальный чек «Точка Вкуса», 240 сом)
TICKET = {
    'id': 't21804199500937f0000000002300267c0000000000182425d99340e', 'type': 3, 'dataFormatVersion': 2,
    'dateTime': '2026-10-07T21:03:37Z', 'tin': '21804199500937', 'fnSerialNumber': '0000000002300267',
    'crRegisterNumber': '0000000000182425', 'fdNumber': 99340, 'documentFiscalMark': '1643235591740',
    'crData': {'shiftNumber': 1641, 'cashierName': 'x', 'locationName': 'Точка Вкуса',
               'locationAddress': '723500, г. Ош, проспект Абсамата Масалиева, 80 80'},
    'errors': {}, 'ticketTotalSum': 24000, 'ticketTotalCashSum': 24000, 'ticketTotalCashlessSum': 0,
    'ticketNumber': 52, 'operationType': 1, 'items': [
        {'goodName': 'Выполнение работ / оказание услуг', 'goodQuantity': 1, 'goodCost': 24000}],
}


def response(status=200, data=None, content=b'{}'):
    r = mock.Mock(status_code=status, text=content.decode(), content=content)
    r.json = mock.Mock(return_value=data if data is not None else TICKET)
    return r


@override_settings(RECEIPT_VERIFY=True)
class SalykTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_real_receipt_from_tax_service(self):
        with mock.patch('apps.cashback.receipts.requests.get', return_value=response()) as get:
            r = parse_receipt(QR)
        self.assertEqual(r['amount'], 240)
        self.assertEqual(r['key'], 'salyk:21804199500937:0000000002300267:99340')
        d = r['details']
        self.assertTrue(d['verified'])
        self.assertEqual((d['number'], d['shift'], d['seller'], d['total'], d['cash']), (52, 1641, 'Точка Вкуса', 240, 240))
        self.assertTrue(d['dateTime'].startswith('2026-10-08T03:03:37'))  # время Бишкека
        # адрес собран заново: только налоговая и только известные параметры
        url = get.call_args[0][0]
        self.assertTrue(url.startswith('https://tax.salyk.kg/tax-web-control/client/api/v1/ticket?'))
        self.assertEqual(parse_qs(urlsplit(url).query)['regNumber'], ['0000000000182425'])
        # второй скан того же чека — из кеша, без запроса
        with mock.patch('apps.cashback.receipts.requests.get') as get2:
            parse_receipt(QR)
        get2.assert_not_called()

    def test_amount_from_tax_service_not_from_qr(self):
        forged = QR.replace('sum=24000', 'sum=9999900')
        with mock.patch('apps.cashback.receipts.requests.get', return_value=response()):
            self.assertEqual(parse_receipt(forged)['amount'], 240)

    def test_fake_receipt_rejected(self):
        with mock.patch('apps.cashback.receipts.requests.get', return_value=response(400, {})):
            with self.assertRaises(ApiError) as e:
                parse_receipt(QR)
        self.assertEqual(e.exception.code, 'receipt_not_found')

    def test_tax_service_closed_falls_back_to_qr(self):
        # налоговая закрыта от внешних запросов: 400 с пустым телом или 450 на любой чек — не «поддельный»
        for resp in (response(400, content=b''), response(450, content=b'')):
            cache.clear()
            with mock.patch('apps.cashback.receipts.requests.get', return_value=resp):
                r = parse_receipt(QR)
            self.assertEqual(r['amount'], 240)
            self.assertFalse(r['details']['verified'])

    def test_qr_without_sum_needs_amount_when_tax_service_closed(self):
        # JaratmanKassa: в QR нет sum и date
        qr = ('https://tax.salyk.kg/tax-web-control/client/api/v1/ticket?type=3&fn_number=0000000002451406'
              '&fd_number=1698&fm=218212929134284&tin=01604199910194&regNumber=0000000000300409')
        closed = response(400, content=b'')
        with mock.patch('apps.cashback.receipts.requests.get', return_value=closed):
            with self.assertRaises(ApiError) as e:
                parse_receipt(qr)
            self.assertEqual(e.exception.code, 'receipt_amount_required')
            r = parse_receipt(qr, 12500)
        self.assertEqual((r['amount'], r['key']), (12500, 'salyk:01604199910194:0000000002451406:1698'))
        self.assertTrue(r['details']['manual'])
        # налоговая ответила — сумма из неё, введённая кассиром не нужна
        cache.clear()
        with mock.patch('apps.cashback.receipts.requests.get', return_value=response()):
            self.assertEqual(parse_receipt(qr, 99999)['amount'], 240)

    def test_refund_receipt_rejected(self):
        with mock.patch('apps.cashback.receipts.requests.get', return_value=response(data={**TICKET, 'operationType': 2})):
            with self.assertRaises(ApiError) as e:
                parse_receipt(QR)
        self.assertEqual(e.exception.code, 'receipt_not_sale')

    def test_tax_service_down_falls_back_to_qr(self):
        with mock.patch('apps.cashback.receipts.requests.get', side_effect=requests.ConnectionError('down')):
            r = parse_receipt(QR)
        self.assertEqual(r['amount'], 240)
        self.assertFalse(r['details']['verified'])

    def test_non_salyk_host_never_fetched(self):
        with mock.patch('apps.cashback.receipts.requests.get') as get:
            parse_receipt('https://evil.example/tax-web-control/client/api/v1/ticket?tin=1&fn_number=2&fd_number=3&sum=100')
        get.assert_not_called()

    @override_settings(RECEIPT_ALLOWED_TINS=['01604199910194'])
    def test_foreign_seller_rejected(self):
        with mock.patch('apps.cashback.receipts.requests.get') as get:
            with self.assertRaises(ApiError) as e:
                parse_receipt(QR)
        self.assertEqual(e.exception.code, 'receipt_foreign')
        get.assert_not_called()
