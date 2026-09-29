"""
Жалобы и обращения (ТЗ §9).
Статусы: new → in_progress → answered → closed; ответ клиента в answered возвращает в in_progress.
"""
import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.errors import ApiError
from apps.common.i18n import iso, tr
from apps.common.media import process_upload
from apps.common.models import ProgramSettings, Upload
from apps.common.realtime import ADMIN_GROUP, publish, publish_member, publish_outlets

from .models import (Complaint, ComplaintCategory, ComplaintMessage, ComplaintNote, ComplaintStatus, PointsSubtype,
                     next_complaint_number)

log = logging.getLogger(__name__)

MAX_ATTACHMENTS = 5
MAX_FILE_SIZE = 10 * 1024 * 1024
RESORT_NAME = 'Команда BAYTUR'


# ---------------------------------------------------------------- фото

def upload_photo(member, uploaded_file):
    if uploaded_file is None or uploaded_file.size > MAX_FILE_SIZE:
        raise ApiError('file_invalid', 422)
    processed = process_upload(uploaded_file, strip_exif=True)  # сжатие + без EXIF (геолокации)
    if processed is None:
        raise ApiError('file_invalid', 422)
    content, ext, w, h = processed
    upload = Upload(kind=Upload.KIND_COMPLAINT, member=member, width=w, height=h)
    upload.file.save(f'{upload.id}.{ext}', content, save=False)
    upload.save()
    return upload


def _attachments(member, ids):
    ids = list(dict.fromkeys(ids or []))
    if len(ids) > MAX_ATTACHMENTS:
        raise ApiError('validation_error', 400, extra={'fields': {'attachmentIds': [f'не больше {MAX_ATTACHMENTS}']}})
    uploads = list(Upload.objects.filter(pk__in=ids, member=member, kind=Upload.KIND_COMPLAINT))
    if len(uploads) != len(ids):
        raise ApiError('validation_error', 400, extra={'fields': {'attachmentIds': ['файл не найден']}})
    return uploads


def _validate_text(text):
    text = (text or '').strip()
    if not 10 <= len(text) <= 2000:
        raise ApiError('validation_error', 400, extra={'fields': {'text': ['10–2000 символов']}})
    return text


# ---------------------------------------------------------------- payloads

def message_payload(m, for_client=True):
    data = {
        'id': m.pk,
        'author': m.author,
        'authorName': RESORT_NAME if m.author == ComplaintMessage.AUTHOR_RESORT and for_client else (
            (m.staff.full_name if m.staff else RESORT_NAME) if m.author == ComplaintMessage.AUTHOR_RESORT
            else m.complaint.member.full_name),
        'text': m.text,
        'attachments': [u.url for u in m.attachments.all()],
        'at': iso(m.at),
    }
    return data


def complaint_payload(c, with_messages=True):
    data = {
        'id': c.pk,
        'number': c.number,
        'category': c.category_id,
        'categoryTitle': tr(c.category.title),
        'subtype': c.subtype or None,
        'outletId': c.outlet_id,
        'requestId': c.request_id,
        'operationId': c.operation_id,
        'status': c.status,
        'rating': c.rating,
        'createdAt': iso(c.created_at),
        'updatedAt': iso(c.updated_at),
    }
    if with_messages:
        data['messages'] = [message_payload(m) for m in c.messages.select_related('staff').prefetch_related('attachments')]
    return data


def admin_complaint_payload(c):
    from apps.loyalty.services import get_wallet
    data = complaint_payload(c, with_messages=False)
    m = c.member
    data.update({
        'messages': [message_payload(x, for_client=False) for x in
                     c.messages.select_related('staff', 'complaint__member').prefetch_related('attachments')],
        'priority': c.priority,
        'assigneeId': c.assignee_id,
        'assigneeName': c.assignee.full_name if c.assignee else None,
        'dueAt': iso(c.due_at) if c.due_at else None,
        'firstReplyAt': iso(c.first_reply_at) if c.first_reply_at else None,
        'closedAt': iso(c.closed_at) if c.closed_at else None,
        'overdue': c.is_overdue,
        'tags': c.tags,
        'ratingComment': c.rating_comment or None,
        'internalNotes': [{'id': n.pk, 'author': n.staff.full_name, 'text': n.text, 'at': iso(n.at)}
                          for n in c.notes.select_related('staff')],
        'member': {
            'id': m.pk, 'memberId': m.member_id, 'name': m.full_name, 'language': m.language,
            'tier': get_wallet(m).tier_id, 'complaintsCount': m.complaints.count(),
        },
    })
    return data


def _publish_client(c):
    publish_member(c.member_id, 'complaint.updated', complaint_payload(c))


def _publish_admin(c, event):
    data = {'id': c.pk, 'number': c.number, 'status': c.status, 'outletId': c.outlet_id}
    publish(ADMIN_GROUP, event, data)
    if c.outlet_id:
        publish_outlets([c.outlet_id], event, data, include_admins=False)


# ---------------------------------------------------------------- клиент

def create_complaint(member, data):
    from apps.members.models import MemberStatus
    if member.status != MemberStatus.ACTIVE:
        raise ApiError('account_frozen', 403)
    ps = ProgramSettings.get()
    since = timezone.now() - timedelta(days=1)
    if member.complaints.filter(created_at__gte=since).count() >= ps.complaint_daily_limit:
        raise ApiError('complaints_limit', 429)
    category = ComplaintCategory.objects.filter(pk=data.get('category'), is_active=True).first()
    if category is None:
        raise ApiError('validation_error', 400, extra={'fields': {'category': ['неизвестная тема']}})
    text = _validate_text(data.get('text'))
    uploads = _attachments(member, data.get('attachmentIds'))

    request = None
    if data.get('requestId'):
        request = member.cashback_requests.filter(pk=data['requestId']).first()
        if request is None:
            raise ApiError('validation_error', 400, extra={'fields': {'requestId': ['не найдена']}})
    operation = None
    subtype = ''
    if data.get('operationId'):
        operation = member.operations.filter(pk=data['operationId']).first()
        if operation is None:
            raise ApiError('validation_error', 400, extra={'fields': {'operationId': ['не найдена']}})
        subtype = data.get('subtype') or PointsSubtype.OTHER
        if subtype not in PointsSubtype.values:
            raise ApiError('validation_error', 400, extra={'fields': {'subtype': list(PointsSubtype.values)}})
        if operation.request_id and request is None:
            request = operation.request
    outlet_id = data.get('outletId') or (request.outlet_id if request else None)
    from apps.catalog.models import Outlet
    if outlet_id and not Outlet.objects.filter(pk=outlet_id).exists():
        raise ApiError('validation_error', 400, extra={'fields': {'outletId': ['неизвестная точка']}})

    now = timezone.now()
    for _ in range(5):
        try:
            with transaction.atomic():
                c = Complaint.objects.create(
                    seq=next_complaint_number(), member=member, category=category, subtype=subtype,
                    outlet_id=outlet_id, request=request, operation=operation, created_at=now, updated_at=now,
                    due_at=now + timedelta(hours=ps.complaint_first_response_hours))
                msg = ComplaintMessage.objects.create(complaint=c, author=ComplaintMessage.AUTHOR_CLIENT, text=text,
                                                      at=now)
                msg.attachments.set(uploads)
            break
        except IntegrityError:  # гонка за номер
            continue
    else:
        raise ApiError('server_error', 500)
    _publish_admin(c, 'complaint.created')
    transaction.on_commit(lambda: alert_staff(c, 'new'))
    return c


def client_reply(member, complaint_id, data):
    with transaction.atomic():
        c = Complaint.objects.select_for_update().filter(pk=complaint_id, member=member).first()
        if c is None:
            raise ApiError('not_found', 404)
        if c.status == ComplaintStatus.CLOSED:
            raise ApiError('complaint_closed', 409)
        text = (data.get('text') or '').strip()
        if not text or len(text) > 2000:
            raise ApiError('validation_error', 400, extra={'fields': {'text': ['1–2000 символов']}})
        uploads = _attachments(member, data.get('attachmentIds'))
        msg = ComplaintMessage.objects.create(complaint=c, author=ComplaintMessage.AUTHOR_CLIENT, text=text)
        msg.attachments.set(uploads)
        if c.status == ComplaintStatus.ANSWERED:
            c.status = ComplaintStatus.IN_PROGRESS
        c.updated_at = timezone.now()
        c.save(update_fields=['status', 'updated_at'])
    _publish_admin(c, 'complaint.message')
    return c


def rate(member, complaint_id, rating, comment=''):
    c = Complaint.objects.filter(pk=complaint_id, member=member).first()
    if c is None:
        raise ApiError('not_found', 404)
    if c.status != ComplaintStatus.CLOSED:
        raise ApiError('invalid_status', 409, extra={'status': c.status})
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        rating = 0
    if not 1 <= rating <= 5:
        raise ApiError('validation_error', 400, extra={'fields': {'rating': ['1–5']}})
    c.rating = rating
    c.rating_comment = (comment or '')[:1000]
    c.save(update_fields=['rating', 'rating_comment'])
    return c


# ---------------------------------------------------------------- курорт

def staff_can_see(user, c):
    if not user.can('complaints.view'):
        return False
    if user.is_outlet_bound:
        return c.outlet_id is not None and c.outlet_id in user.outlet_ids
    return True


def resort_reply(complaint_id, staff, text, close=False):
    """Ответ клиенту (вручную или по шаблону). Сотрудник точки не отвечает — только заметки."""
    if not staff.can('complaints.reply'):
        raise ApiError('permission_denied', 403)
    text = (text or '').strip()
    if not text:
        raise ApiError('validation_error', 400, extra={'fields': {'text': ['обязательно']}})
    with transaction.atomic():
        c = Complaint.objects.select_for_update().select_related('member').get(pk=complaint_id)
        if c.status == ComplaintStatus.CLOSED:
            raise ApiError('complaint_closed', 409)
        ComplaintMessage.objects.create(complaint=c, author=ComplaintMessage.AUTHOR_RESORT, staff=staff, text=text)
        now = timezone.now()
        c.first_reply_at = c.first_reply_at or now
        c.status = ComplaintStatus.CLOSED if close else ComplaintStatus.ANSWERED
        if close:
            c.closed_at = now
        if c.assignee_id is None:
            c.assignee = staff
        c.updated_at = now
        c.save()
    _publish_client(c)
    _publish_admin(c, 'complaint.updated')
    from apps.notifications.services import notify_complaint_reply
    transaction.on_commit(lambda: notify_complaint_reply(c))
    return c


def set_status(complaint_id, staff, status):
    if status not in ComplaintStatus.values:
        raise ApiError('validation_error', 400, extra={'fields': {'status': list(ComplaintStatus.values)}})
    with transaction.atomic():
        c = Complaint.objects.select_for_update().get(pk=complaint_id)
        c.status = status
        now = timezone.now()
        c.closed_at = now if status == ComplaintStatus.CLOSED else None
        c.updated_at = now
        c.save()
    _publish_client(c)
    _publish_admin(c, 'complaint.updated')
    return c


def assign(complaint_id, assignee):
    c = Complaint.objects.get(pk=complaint_id)
    c.assignee = assignee
    if c.status == ComplaintStatus.NEW:
        c.status = ComplaintStatus.IN_PROGRESS
    c.updated_at = timezone.now()
    c.save()
    _publish_admin(c, 'complaint.updated')
    if assignee:
        transaction.on_commit(lambda: alert_staff(c, 'assigned', [assignee.email]))
    return c


def add_note(complaint_id, staff, text):
    text = (text or '').strip()
    if not text:
        raise ApiError('validation_error', 400, extra={'fields': {'text': ['обязательно']}})
    return ComplaintNote.objects.create(complaint_id=complaint_id, staff=staff, text=text)


def compensate(complaint, staff, points, comment):
    """Компенсация баллами — ручная корректировка со ссылкой на обращение (владелец и менеджер)."""
    from apps.loyalty.services import manual_adjustment
    if not staff.can('complaints.compensate'):
        raise ApiError('permission_denied', 403)
    return manual_adjustment(complaint.member, int(points), comment or f'Компенсация по обращению {complaint.number}',
                             staff, complaint=complaint, related=complaint.operation)


# ---------------------------------------------------------------- сроки

def alert_staff(c, reason, emails=None):
    ps = ProgramSettings.get()
    recipients = emails or list(ps.complaint_alert_emails or [])
    if c.assignee and c.assignee.email not in recipients:
        recipients.append(c.assignee.email)
    if not recipients:
        return
    subject = {'new': f'Новое обращение {c.number}', 'overdue': f'Просрочен ответ на {c.number}',
               'assigned': f'Вам назначено обращение {c.number}'}.get(reason, c.number)
    try:
        send_mail(subject, f'{subject}. Тема: {tr(c.category.title)}.', None, recipients, fail_silently=True)
    except Exception:
        log.exception('complaint alert failed')


def notify_overdue(now=None):
    now = now or timezone.now()
    overdue = Complaint.objects.filter(first_reply_at__isnull=True, due_at__lt=now, overdue_notified=False) \
        .exclude(status=ComplaintStatus.CLOSED)
    count = 0
    for c in overdue:
        alert_staff(c, 'overdue')
        _publish_admin(c, 'complaint.overdue')
        Complaint.objects.filter(pk=c.pk).update(overdue_notified=True)
        count += 1
    return count
