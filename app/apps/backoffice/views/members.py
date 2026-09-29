"""
Клиенты (ТЗ §7.2, §2.5): поиск, карточка, блокировка, корректировки баллов, ДР, телефон, экспорт,
восстановление удалённого аккаунта и удаление без ожидания.
Сотрудник (роль staff) видит клиента без баланса и истории, заявки — только своих точек.
"""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response

from apps.cashback.models import CashbackRequest
from apps.cashback.serializers import mask_phone, request_payload, staff_request_payload
from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.common.i18n import iso
from apps.common.pagination import paginate
from apps.loyalty.api import operation_payload
from apps.loyalty.services import get_wallet, manual_adjustment, wallet_payload
from apps.members import auth as member_auth
from apps.members import services as member_services
from apps.members.models import Member, MemberStatus

from ..base import AdminAPIView, body, field_error, not_found, period_filter

VIEW = 'members.view'
HISTORY = 'members.history'
MANAGE = 'members.manage'


def can_history(user):
    return user.can(HISTORY)


def deletion_marker(m):
    """Пометка «удалён, будет стёрт ДД.ММ» для деактивированных (§2.5)."""
    if m.status == MemberStatus.DEACTIVATED:
        purge_at = timezone.localtime(m.purge_at) if m.purge_at else None
        return {
            'deletedAt': iso(m.deleted_at),
            'purgeAt': iso(m.purge_at),
            'purgeImmediately': m.purge_immediately,
            'note': f'удалён, будет стёрт {purge_at:%d.%m}' if purge_at else 'удалён',
        }
    if m.status == MemberStatus.PURGED:
        return {'purgedAt': iso(m.purged_at), 'note': 'стёрт'}
    return None


def member_row(m, user):
    wallet = get_wallet(m)
    data = {
        'id': m.pk,
        'memberId': m.member_id,
        'name': m.full_name,
        'phone': m.phone if can_history(user) else mask_phone(m.phone),
        'tier': wallet.tier_id,
        'status': m.status,
        'language': m.language,
        'memberSince': m.member_since.isoformat(),
        'createdAt': iso(m.created_at),
        'isTest': m.is_test,
        'deletion': deletion_marker(m),
    }
    if can_history(user):
        data['balance'] = wallet.balance
        data['lifetime'] = wallet.lifetime
    return data


def scoped_requests(user, member):
    qs = CashbackRequest.objects.filter(member=member).select_related('member', 'payment', 'item')
    if user.is_outlet_bound:
        qs = qs.filter(outlet_id__in=user.outlet_ids)
    return qs


def member_card(m, user):
    data = member_row(m, user)
    full = can_history(user)
    data['profile'] = {
        'firstName': m.first_name,
        'lastName': m.last_name,
        'phone': data['phone'],
        'email': (m.email or None) if full else None,
        'birthday': m.birthday.isoformat() if m.birthday else None,
        'gender': m.gender or None,
        'language': m.language,
        'notifyCashback': m.notify_cashback,
        'notifyPromos': m.notify_promos,
        'marketingConsent': m.marketing_consent,
        'blockedReason': m.blocked_reason or None,
        'restoredAt': iso(m.restored_at),
    }
    data['requests'] = [staff_request_payload(r) for r in scoped_requests(user, m).order_by('-created_at')[:20]]
    if full:
        data['wallet'] = wallet_payload(m)
        data['operations'] = [operation_payload(o) for o in m.operations.all()[:20]]
        data['consents'] = [{'kind': c.kind, 'version': c.version or None, 'granted': c.granted, 'at': iso(c.at)}
                            for c in m.consents.all()]
        data['devices'] = [{'platform': d.platform, 'appVersion': d.app_version or None,
                            'token': (d.token[:8] + '…') if d.token else None,
                            'createdAt': iso(d.created_at), 'updatedAt': iso(d.updated_at)}
                           for d in m.devices.all()]
        data['complaintsCount'] = m.complaints.count()
    return data


def get_member(pk):
    m = Member.objects.filter(pk=pk).first()
    if m is None:
        raise not_found()
    return m


class MembersView(AdminAPIView):
    """GET ?q=&tier=&status=&registeredFrom=&registeredTo=&cursor= (стёртые — только status=purged|all)."""

    required_perms = VIEW

    def get(self, request):
        p = request.query_params
        qs = Member.objects.all()
        status = p.get('status')
        if status == 'all':
            pass
        elif status:
            qs = qs.filter(status=status)
        else:
            qs = qs.exclude(status=MemberStatus.PURGED)
        if p.get('tier'):
            qs = qs.filter(wallet__tier_id=p['tier'])
        qs = period_filter(qs, request, 'created_at', 'registeredFrom', 'registeredTo')
        q = (p.get('q') or '').strip()
        if q:
            cond = Q(member_id__iexact=q) | Q(member_id__iexact=f'BT-{q}')
            digits = ''.join(ch for ch in q if ch.isdigit())
            if len(digits) >= 4:
                cond |= Q(phone__contains=digits)
            words = [w for w in q.split() if not any(ch.isdigit() for ch in w)]
            if words:
                name = Q()
                for w in words:
                    name &= Q(first_name__icontains=w) | Q(last_name__icontains=w)
                cond |= name
            qs = qs.filter(cond)
        return Response(paginate(request, qs, lambda rows: [member_row(m, request.user) for m in rows]))


class MemberDetailView(AdminAPIView):
    required_perms = VIEW

    def get(self, request, pk):
        return Response(member_card(get_member(pk), request.user))


class MemberRequestsView(AdminAPIView):
    required_perms = VIEW

    def get(self, request, pk):
        qs = scoped_requests(request.user, get_member(pk))
        return Response(paginate(request, qs, lambda rows: [staff_request_payload(r) for r in rows]))


class MemberOperationsView(AdminAPIView):
    required_perms = HISTORY

    def get(self, request, pk):
        m = get_member(pk)
        return Response(paginate(request, m.operations.all(), lambda rows: [operation_payload(o) for o in rows],
                                 time_field='at'))


# ---------------------------------------------------------------- действия

class MemberActionView(AdminAPIView):
    required_perms = MANAGE

    def respond(self, m):
        m.refresh_from_db()
        return Response(member_card(m, self.request.user))


class BlockView(MemberActionView):
    def post(self, request, pk):
        reason = (body(request).get('reason') or '').strip()
        if not reason:
            raise field_error('reason', 'обязательно')
        with transaction.atomic():
            m = Member.objects.select_for_update().filter(pk=pk).first()
            if m is None:
                raise not_found()
            if m.status != MemberStatus.ACTIVE:
                raise ApiError('invalid_status', 409, extra={'status': m.status})
            m.status = MemberStatus.BLOCKED
            m.blocked_reason = reason
            m.save(update_fields=['status', 'blocked_reason', 'updated_at'])
            member_auth.revoke_all(m)
            audit(request, 'member.block', m, before={'status': MemberStatus.ACTIVE},
                  after={'status': m.status}, comment=reason)
        return self.respond(m)


class UnblockView(MemberActionView):
    def post(self, request, pk):
        with transaction.atomic():
            m = Member.objects.select_for_update().filter(pk=pk).first()
            if m is None:
                raise not_found()
            if m.status != MemberStatus.BLOCKED:
                raise ApiError('invalid_status', 409, extra={'status': m.status})
            before = {'status': m.status, 'blockedReason': m.blocked_reason}
            m.status = MemberStatus.ACTIVE
            m.blocked_reason = ''
            m.save(update_fields=['status', 'blocked_reason', 'updated_at'])
            audit(request, 'member.unblock', m, before=before, after={'status': m.status},
                  comment=(body(request).get('comment') or '').strip())
        return self.respond(m)


class AdjustmentsView(MemberActionView):
    """POST {points: ±N, comment} → операция adjustment (журнал) + аудит."""

    def post(self, request, pk):
        m = get_member(pk)
        if m.status == MemberStatus.PURGED:
            raise ApiError('invalid_status', 409, extra={'status': m.status})
        data = body(request)
        try:
            points = int(data.get('points'))
        except (TypeError, ValueError):
            raise field_error('points', 'целое число со знаком')
        comment = (data.get('comment') or '').strip()
        before = get_wallet(m).balance
        op = manual_adjustment(m, points, comment, request.user)
        wallet = get_wallet(m)
        audit(request, 'member.adjust', m, before={'balance': before},
              after={'balance': wallet.balance, 'points': points, 'operationId': op.pk}, comment=comment)
        return Response({'operation': operation_payload(op), 'wallet': wallet_payload(m, wallet)}, status=201)


class BirthdayView(MemberActionView):
    """PATCH {birthday: YYYY-MM-DD} — клиент ставит ДР один раз, дальше меняет только админ."""

    def patch(self, request, pk):
        m = get_member(pk)
        bd = member_services._parse_birthday(body(request).get('birthday'), required=True)
        before = {'birthday': m.birthday.isoformat() if m.birthday else None}
        m.birthday = bd
        m.save(update_fields=['birthday', 'updated_at'])
        audit(request, 'member.birthday', m, before=before, after={'birthday': bd.isoformat()},
              comment=(body(request).get('comment') or '').strip())
        return self.respond(m)

    put = post = patch


class PhoneView(MemberActionView):
    """PATCH {phone} — смена номера (потерянная SIM и т.п.). Старые сессии отзываются."""

    def patch(self, request, pk):
        m = get_member(pk)
        if m.status == MemberStatus.PURGED:
            raise ApiError('invalid_status', 409, extra={'status': m.status})
        phone = member_auth.normalize_phone(body(request).get('phone'))
        if phone == m.phone:
            return self.respond(m)
        if Member.objects.filter(phone=phone).exclude(pk=m.pk).exists():
            raise ApiError('phone_taken', 409, message='Номер уже привязан к другому участнику')
        before = {'phone': m.phone}
        try:
            with transaction.atomic():
                m.phone = phone
                m.save(update_fields=['phone', 'updated_at'])
                member_auth.revoke_all(m)
                audit(request, 'member.phone', m, before=before, after={'phone': phone},
                      comment=(body(request).get('comment') or '').strip())
        except IntegrityError:
            raise ApiError('phone_taken', 409, message='Номер уже привязан к другому участнику')
        return self.respond(m)

    put = post = patch


def export_payload(m):
    from apps.complaints.services import complaint_payload
    from apps.notifications.services import notification_payload
    from apps.payments.services import payment_payload
    return {
        'exportedAt': iso(timezone.now()),
        'memberId': m.member_id,
        'status': m.status,
        'profile': {
            'firstName': m.first_name, 'lastName': m.last_name, 'phone': m.phone, 'email': m.email or None,
            'birthday': m.birthday.isoformat() if m.birthday else None, 'gender': m.gender or None,
            'language': m.language, 'memberSince': m.member_since.isoformat(), 'createdAt': iso(m.created_at),
            'notifyCashback': m.notify_cashback, 'notifyPromos': m.notify_promos,
            'marketingConsent': m.marketing_consent,
        },
        'wallet': wallet_payload(m),
        'operations': [operation_payload(o) for o in m.operations.all()],
        'requests': [request_payload(r, lang=m.language) for r in
                     m.cashback_requests.select_related('payment').order_by('-created_at')],
        'payments': [payment_payload(p) for p in m.payments.all()],
        'consents': [{'kind': c.kind, 'version': c.version or None, 'granted': c.granted, 'at': iso(c.at),
                      'ip': c.ip} for c in m.consents.all()],
        'devices': [{'platform': d.platform, 'appVersion': d.app_version or None, 'createdAt': iso(d.created_at)}
                    for d in m.devices.all()],
        'complaints': [complaint_payload(c) for c in m.complaints.select_related('category')],
        'notifications': [notification_payload(n) for n in m.notifications.all()],
    }


class ExportView(MemberActionView):
    """GET — все данные клиента одним JSON (запрос клиента на выгрузку своих данных)."""

    def get(self, request, pk):
        m = get_member(pk)
        audit(request, 'member.export', m)
        return Response(export_payload(m),
                        headers={'Content-Disposition': f'attachment; filename="{m.member_id}.json"'})

    post = get


class RestoreView(MemberActionView):
    """POST — вернуть удалённый (deactivated) аккаунт по обращению клиента (§2.5)."""

    required_perms = 'members.restore'

    def post(self, request, pk):
        m = get_member(pk)
        before = {'status': m.status, 'purgeAt': iso(m.purge_at)}
        m = member_services.restore(m)
        audit(request, 'member.restore', m, before=before, after={'status': m.status},
              comment=(body(request).get('comment') or '').strip())
        return self.respond(m)


class PurgeNowView(MemberActionView):
    """
    POST {comment} — клиент явно попросил удалить без ожидания: деактивация (если ещё активен)
    и сразу окончательное стирание. В аудит пишутся только статусы — не ПДн.
    """

    required_perms = ['members.manage', 'members.restore']

    def post(self, request, pk):
        m = get_member(pk)
        comment = (body(request).get('comment') or '').strip()
        if not comment:
            raise field_error('comment', 'обязательно (основание: обращение, заявление)')
        if m.status == MemberStatus.PURGED:
            raise ApiError('invalid_status', 409, extra={'status': m.status})
        before = {'status': m.status}
        if m.status != MemberStatus.DEACTIVATED:
            m = member_services.deactivate(m, actor=request.user, immediately=True)
        m = member_services.purge(m)
        audit(request, 'member.purge', m, before=before, after={'status': m.status}, comment=comment)
        return self.respond(m)
