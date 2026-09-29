"""
Заявки на кешбек и онлайн-платежи в админке (ТЗ §7.2 «Заявки и платежи»).
Действия с заявками — те же, что у сотрудника (§8), плюс подтверждение эскалаций менеджером.
"""
from django.db.models import Q
from rest_framework.response import Response

from apps.cashback import desk, staff_api
from apps.cashback.models import CashbackRequest, RejectReason
from apps.cashback.serializers import staff_request_payload
from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.common.i18n import iso
from apps.common.pagination import paginate
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import payment_payload, refund_payment

from ..base import AdminAPIView, body, field_error, not_found, period_filter, truthy
from ..serializers import staff_brief

REQUESTS_READ = ['requests.view_all', 'requests.process']


def request_row(req):
    data = staff_request_payload(req)
    data.update({
        'confirmedAt': iso(req.confirmed_at),
        'rejectedAt': iso(req.rejected_at),
        'creditedAt': iso(req.credited_at),
        'confirmedByName': req.confirmed_by.full_name if req.confirmed_by else None,
        'rejectedByName': req.rejected_by.full_name if req.rejected_by else None,
        'adjustedByName': req.adjusted_by.full_name if req.adjusted_by else None,
        'proposedBy': staff_brief(req.proposed_by),
    })
    return data


def scoped(user):
    qs = CashbackRequest.objects.select_related('member', 'payment', 'item', 'confirmed_by', 'rejected_by',
                                                'adjusted_by', 'proposed_by')
    if user.is_outlet_bound or not user.can('requests.view_all'):
        qs = qs.filter(outlet_id__in=user.outlet_ids)
    return qs


def get_request(user, pk):
    req = scoped(user).filter(pk=pk).first()
    if req is None:
        raise not_found()
    return req


class RequestsView(AdminAPIView):
    """GET ?status=&category=&outlet=&staff=&member=&method=&escalated=1&from=&to=&cursor="""

    required_perms = REQUESTS_READ

    def get(self, request):
        p = request.query_params
        qs = scoped(request.user)
        if p.get('status'):
            qs = qs.filter(status__in=p['status'].split(','))
        if p.get('category'):
            qs = qs.filter(item__category_id=p['category'])
        if p.get('outlet'):
            qs = qs.filter(outlet_id=p['outlet'])
        if p.get('method'):
            qs = qs.filter(method=p['method'])
        if p.get('staff'):
            sid = p['staff']
            qs = qs.filter(Q(confirmed_by_id=sid) | Q(rejected_by_id=sid) | Q(adjusted_by_id=sid))
        if p.get('member'):
            v = p['member']
            qs = qs.filter(Q(member__member_id__iexact=v) | (Q(member__pk=v) if v.isdigit() else Q()))
        if p.get('escalated') is not None and p.get('escalated') != '':
            qs = qs.filter(escalated=truthy(p['escalated']))
        qs = period_filter(qs, request, 'created_at')
        return Response(paginate(request, qs, lambda rows: [request_row(r) for r in rows]))


class RequestDetailView(AdminAPIView):
    required_perms = REQUESTS_READ

    def get(self, request, request_id):
        req = get_request(request.user, request_id)
        data = request_row(req)
        data['complaints'] = [{'id': c.pk, 'number': c.number, 'status': c.status} for c in req.complaints.all()]
        return Response(data)


# Те же действия, что на рабочем месте сотрудника: область точек, «не свой аккаунт», эскалация для роли staff

class ConfirmView(staff_api.ConfirmView):
    """POST {cashReceived}."""


class AdjustPreviewView(staff_api.AdjustPreviewView):
    """POST {total} → новый расчёт без сохранения."""


class AdjustView(staff_api.AdjustView):
    """POST {total, reason}."""


class RejectView(staff_api.StaffAPIView):
    """POST {reason, reasonCode?} — причину видит клиент; reasonCode по умолчанию other."""

    def post(self, request, request_id):
        data = body(request)
        req = desk.reject(request, request_id, data.get('reasonCode') or RejectReason.OTHER,
                          data.get('reason') or data.get('comment'))
        return Response(staff_api.payload(req))


class ApproveEscalationView(AdminAPIView):
    """
    POST {confirm?, cashReceived?} — менеджер/владелец одобряет эскалацию:
    - adjust_threshold: применяется предложенная сотрудником сумма (confirm=true — сразу и подтвердить);
    - cashback_limit: заявка подтверждается.
    """

    required_perms = 'requests.approve_escalated'

    def post(self, request, request_id):
        data = body(request)
        req = desk.approve_escalation(request, request_id, confirm_after_adjust=truthy(data.get('confirm')),
                                      cash_received=truthy(data.get('cashReceived')))
        return Response(request_row(get_request(request.user, req.pk)))


class DeclineEscalationView(AdminAPIView):
    """POST {comment} — отклонить предложение сотрудника: заявка остаётся pending с прежней суммой."""

    required_perms = 'requests.approve_escalated'

    def post(self, request, request_id):
        req = desk.decline_escalation(request, request_id, body(request).get('comment'))
        return Response(request_row(get_request(request.user, req.pk)))


# ---------------------------------------------------------------- платежи

def admin_payment_payload(p):
    m = p.member
    data = payment_payload(p)
    data.update({
        'status': p.status,
        'member': {'id': m.pk, 'memberId': m.member_id, 'name': m.full_name},
        'providerRef': p.provider_ref or None,
        'refundedAmount': p.refunded_amount,
        'isTest': p.is_test,
        'createdAt': iso(p.created_at),
        'refunds': [{'id': r.pk, 'amount': r.amount, 'reason': r.reason, 'status': r.status,
                     'authorId': r.author_id, 'createdAt': iso(r.created_at)} for r in p.refunds.all()],
    })
    return data


def payments_qs():
    return Payment.objects.select_related('member').prefetch_related('refunds')


class PaymentsView(AdminAPIView):
    """GET ?status=&method=&member=&orphan=1&from=&to=&cursor="""

    required_perms = 'payments.view'

    def get(self, request):
        p = request.query_params
        qs = payments_qs()
        if p.get('status'):
            qs = qs.filter(status__in=p['status'].split(','))
        if p.get('method'):
            qs = qs.filter(method=p['method'])
        if p.get('member'):
            qs = qs.filter(member__member_id__iexact=p['member'])
        if truthy(p.get('orphan')):
            qs = qs.filter(status=PaymentStatus.PAID, request__isnull=True)
        if p.get('q'):
            qs = qs.filter(Q(pk=p['q']) | Q(provider_ref=p['q']))
        qs = period_filter(qs, request, 'created_at')
        return Response(paginate(request, qs, lambda rows: [admin_payment_payload(x) for x in rows]))


class ReconciliationView(AdminAPIView):
    """Сверка «оплачено, но без заявки» (фоновая задача создаёт заявку или делает возврат)."""

    required_perms = 'payments.view'

    def get(self, request):
        qs = payments_qs().filter(status=PaymentStatus.PAID, request__isnull=True)
        return Response(paginate(request, qs, lambda rows: [admin_payment_payload(x) for x in rows]))


class PaymentDetailView(AdminAPIView):
    required_perms = 'payments.view'

    def get(self, request, payment_id):
        p = payments_qs().filter(pk=payment_id).first()
        if p is None:
            raise not_found()
        return Response(admin_payment_payload(p))


class RefundView(AdminAPIView):
    """POST {amount?, reason} — полный (по умолчанию) или частичный возврат у провайдера."""

    required_perms = 'payments.refund'

    def post(self, request, payment_id):
        p = Payment.objects.filter(pk=payment_id).first()
        if p is None:
            raise not_found()
        data = body(request)
        reason = (data.get('reason') or '').strip()
        if not reason:
            raise field_error('reason', 'обязательно')
        left = p.amount - p.refunded_amount
        if p.status != PaymentStatus.PAID or left <= 0:
            raise ApiError('invalid_status', 409, extra={'status': p.status})
        try:
            amount = int(data.get('amount') or left)
        except (TypeError, ValueError):
            raise field_error('amount', 'целое число')
        if not 1 <= amount <= left:
            raise field_error('amount', f'1…{left}')
        before = {'status': p.status, 'refundedAmount': p.refunded_amount}
        refund = refund_payment(p.pk, amount, reason, author=request.user)
        if refund is None:
            raise ApiError('invalid_status', 409, extra={'status': p.status})
        p = payments_qs().get(pk=p.pk)
        audit(request, 'payment.refund', p, before=before,
              after={'status': p.status, 'refundedAmount': p.refunded_amount, 'refundStatus': refund.status,
                     'amount': amount}, comment=reason)
        return Response(admin_payment_payload(p))
