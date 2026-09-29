from apps.common.i18n import iso, tr
from apps.common.media import absolute_media_url

from .models import RejectReason

REJECT_LABELS = {
    RejectReason.NOT_PROVIDED: {'ru': 'Услуга не оказана', 'ky': 'Кызмат көрсөтүлгөн эмес', 'en': 'Service was not provided'},
    RejectReason.WRONG_AMOUNT: {'ru': 'Неверная сумма', 'ky': 'Сумма туура эмес', 'en': 'Wrong amount'},
    RejectReason.DUPLICATE: {'ru': 'Повторная заявка', 'ky': 'Кайталанган өтүнмө', 'en': 'Duplicate request'},
    RejectReason.EXPIRED: {'ru': 'Истёк срок подтверждения', 'ky': 'Ырастоо мөөнөтү бүттү', 'en': 'Confirmation time expired'},
    RejectReason.PAYMENT_FAILED: {'ru': 'Оплата не прошла', 'ky': 'Төлөм өткөн жок', 'en': 'Payment failed'},
    RejectReason.OTHER: {'ru': 'Другое', 'ky': 'Башка', 'en': 'Other'},
}


def reject_reason_text(req, lang=None):
    if req.status != 'rejected':
        return None
    label = tr(REJECT_LABELS.get(req.reject_code), lang) if req.reject_code else None
    if req.reject_reason:
        return f'{label}: {req.reject_reason}' if label and req.reject_code != RejectReason.OTHER else req.reject_reason
    return label


def rules_payload(snapshot):
    return {
        'rate': float(snapshot['rate']),
        'maxPointsShare': float(snapshot['maxPointsShare']),
        'methods': snapshot['methods'],
    }


def split_payload(req):
    return {
        'total': req.total,
        'pointsSom': req.points_som,
        'points': req.points,
        'moneySom': req.money_som,
        'rate': float(req.rate),
        'cashback': req.cashback,
    }


def receipt_payload(req):
    payment = getattr(req, 'payment', None)
    if payment is None or payment.paid_at is None:
        return None
    return {'id': payment.pk, 'method': payment.method, 'amount': payment.amount, 'at': iso(payment.paid_at)}


def request_payload(req, lang=None):
    """CashbackRequest в формате мобилки (lib/features/cashback/domain)."""
    snap = req.item_snapshot or {}
    return {
        'id': req.pk,
        'status': req.status,
        'createdAt': iso(req.created_at),
        'timeline': req.timeline,
        'item': {
            'id': snap.get('id'),
            'category': snap.get('category'),
            'title': tr(snap.get('title'), lang),
            'image': absolute_media_url(snap.get('image')),
        },
        'quantity': req.quantity,
        'checkAmount': req.check_amount,
        'rules': rules_payload(req.rules),
        'split': split_payload(req),
        'method': req.method,
        'receipt': receipt_payload(req),
        'originalTotal': req.original_total,
        'rejectReason': reject_reason_text(req, lang),
        'adjustReason': req.adjust_reason or None,
        'bonuses': req.bonuses or [],
    }


def mask_phone(phone):
    if not phone:
        return None
    return phone[:4] + '•' * max(0, len(phone) - 7) + phone[-3:]


def staff_request_payload(req, lang='ru'):
    """Карточка заявки для сотрудника (§8.2): без баланса клиента, телефон со скрытыми цифрами."""
    from apps.loyalty.services import get_wallet
    member = req.member
    wallet = get_wallet(member)
    data = request_payload(req, lang)
    data.update({
        'outlet': req.outlet_id,
        'member': {
            'id': member.pk,
            'memberId': member.member_id,
            'name': member.full_name,
            'phone': mask_phone(member.phone),
            'tier': wallet.tier_id,
            'status': member.status,
        },
        'paidOnline': bool(data['receipt']),
        'cashToCollect': req.money_som if req.method == 'cash' else 0,
        'cashReceived': req.cash_received,
        'escalated': req.escalated,
        'escalationReason': req.escalation_reason or None,
        'proposedTotal': req.proposed_total,
        'confirmedBy': req.confirmed_by_id,
        'rejectedBy': req.rejected_by_id,
        'adjustedBy': req.adjusted_by_id,
        'isTest': req.is_test,
    })
    return data
