"""
Обращения в админке (ТЗ §9.3, §9.5). Владелец, менеджер, служба заботы — все обращения;
сотрудник — только своей точки: читает и пишет внутренние заметки, но не отвечает клиенту.
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response

from apps.cashback.serializers import staff_request_payload
from apps.common.audit import audit
from apps.common.i18n import iso, tr
from apps.common.pagination import paginate
from apps.complaints import services
from apps.complaints.models import Complaint, ComplaintCategory, ComplaintStatus, ReplyTemplate
from apps.loyalty.api import operation_payload
from apps.loyalty.services import wallet_payload
from apps.staff.models import StaffUser

from ..base import AdminAPIView, CollectionView, DetailView, SortView, body, field_error, not_found, truthy
from ..serializers import ComplaintCategorySerializer, ReplyTemplateSerializer

VIEW = 'complaints.view'
REPLY = 'complaints.reply'
NOTES = 'complaints.notes'
SETTINGS = 'complaints.settings'
PRIORITIES = ('low', 'normal', 'high')


def scoped(user):
    qs = Complaint.objects.select_related('category', 'member', 'assignee')
    if user.is_outlet_bound:
        qs = qs.filter(outlet_id__in=user.outlet_ids)
    return qs


def overdue_q(now=None):
    return Q(first_reply_at__isnull=True, due_at__lt=now or timezone.now()) & ~Q(status=ComplaintStatus.CLOSED)


def get_complaint(user, pk):
    c = scoped(user).filter(pk=pk).first()
    if c is None or not services.staff_can_see(user, c):
        raise not_found()
    return c


def complaint_row(c):
    data = services.complaint_payload(c, with_messages=False)
    last = c.messages.order_by('-at', '-id').first()
    data.update({
        'priority': c.priority,
        'assigneeId': c.assignee_id,
        'assigneeName': c.assignee.full_name if c.assignee else None,
        'dueAt': iso(c.due_at),
        'firstReplyAt': iso(c.first_reply_at),
        'closedAt': iso(c.closed_at),
        'overdue': c.is_overdue,
        'tags': c.tags,
        'member': {'id': c.member_id, 'memberId': c.member.member_id, 'name': c.member.full_name},
        'lastMessage': {'author': last.author, 'text': last.text[:200], 'at': iso(last.at)} if last else None,
    })
    return data


def complaint_card(c, user):
    data = services.admin_complaint_payload(c)
    data['request'] = staff_request_payload(c.request) if c.request_id else None
    data['operation'] = operation_payload(c.operation) if c.operation_id and user.can('members.history') else None
    if user.can('members.history'):
        data['member']['wallet'] = wallet_payload(c.member)
    data['compensations'] = [operation_payload(o) for o in c.compensations.all()]
    data['canReply'] = user.can(REPLY)
    return data


class ComplaintsView(AdminAPIView):
    """GET ?status=&category=&outlet=&assignee=<id|me|none>&overdue=1&priority=&q=&cursor="""

    required_perms = VIEW

    def get(self, request):
        p = request.query_params
        qs = scoped(request.user)
        if p.get('status'):
            qs = qs.filter(status__in=p['status'].split(','))
        if p.get('category'):
            qs = qs.filter(category_id=p['category'])
        if p.get('outlet'):
            qs = qs.filter(outlet_id=p['outlet'])
        if p.get('priority'):
            qs = qs.filter(priority=p['priority'])
        assignee = p.get('assignee')
        if assignee == 'me':
            qs = qs.filter(assignee=request.user)
        elif assignee == 'none':
            qs = qs.filter(assignee__isnull=True)
        elif assignee:
            qs = qs.filter(assignee_id=assignee)
        if truthy(p.get('overdue')):
            qs = qs.filter(overdue_q())
        q = (p.get('q') or '').strip()
        if q:
            digits = ''.join(ch for ch in q if ch.isdigit())
            cond = Q(pk=q) | Q(member__member_id__iexact=q)
            if digits:
                cond |= Q(seq=int(digits))
            qs = qs.filter(cond)
        return Response(paginate(request, qs, lambda rows: [complaint_row(c) for c in rows]))


class CountersView(AdminAPIView):
    """Счётчики для меню: новые, просроченные, мои открытые."""

    required_perms = VIEW

    def get(self, request):
        qs = scoped(request.user)
        return Response({
            'new': qs.filter(status=ComplaintStatus.NEW).count(),
            'overdue': qs.filter(overdue_q()).count(),
            'mine': qs.filter(assignee=request.user).exclude(status=ComplaintStatus.CLOSED).count(),
        })


class ComplaintDetailView(AdminAPIView):
    """GET — карточка; PATCH {priority?, tags?}."""

    required_perms = {'GET': VIEW, 'PATCH': REPLY}

    def get(self, request, pk):
        return Response(complaint_card(get_complaint(request.user, pk), request.user))

    def patch(self, request, pk):
        c = get_complaint(request.user, pk)
        data = body(request)
        before = {'priority': c.priority, 'tags': c.tags}
        if 'priority' in data:
            if data['priority'] not in PRIORITIES:
                raise field_error('priority', ' | '.join(PRIORITIES))
            c.priority = data['priority']
        if 'tags' in data:
            tags = data['tags']
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                raise field_error('tags', 'список строк')
            c.tags = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        with transaction.atomic():
            c.save(update_fields=['priority', 'tags'])
            audit(request, 'complaint.update', c, before=before, after={'priority': c.priority, 'tags': c.tags})
        return Response(complaint_card(c, request.user))


class AssignView(AdminAPIView):
    """POST {assigneeId | null}."""

    required_perms = REPLY

    def post(self, request, pk):
        c = get_complaint(request.user, pk)
        assignee_id = body(request).get('assigneeId')
        assignee = None
        if assignee_id not in (None, ''):
            assignee = StaffUser.objects.filter(pk=assignee_id, is_active=True).first()
            if assignee is None or not services.staff_can_see(assignee, c):
                raise field_error('assigneeId', 'сотрудник не найден или не видит это обращение')
        before = {'assigneeId': c.assignee_id, 'status': c.status}
        with transaction.atomic():
            c = services.assign(c.pk, assignee)
            audit(request, 'complaint.assign', c, before=before, after={'assigneeId': c.assignee_id, 'status': c.status})
        return Response(complaint_card(get_complaint(request.user, c.pk), request.user))


def render_template(template, complaint):
    """Шаблон ответа на языке клиента; плейсхолдеры {name}, {number}."""
    member = complaint.member
    text = tr(template.text, member.language) or ''
    return text.replace('{name}', member.first_name or '').replace('{number}', complaint.number)


class ReplyView(AdminAPIView):
    """POST {text?, templateId?, close?} — ответ клиенту (вручную или по шаблону на его языке)."""

    required_perms = REPLY

    def post(self, request, pk):
        c = get_complaint(request.user, pk)
        data = body(request)
        text = (data.get('text') or '').strip()
        template_id = data.get('templateId')
        if not text and template_id:
            template = ReplyTemplate.objects.filter(pk=template_id).first()
            if template is None:
                raise field_error('templateId', 'шаблон не найден')
            text = render_template(template, c)
        before = {'status': c.status}
        c = services.resort_reply(c.pk, request.user, text, close=truthy(data.get('close')))
        audit(request, 'complaint.reply', c, before=before, after={'status': c.status, 'templateId': template_id},
              comment=text[:500])
        return Response(complaint_card(get_complaint(request.user, c.pk), request.user), status=201)


class NotesView(AdminAPIView):
    """POST {text} — внутренняя заметка (клиенту не видна). Сотрудник точки — тоже может."""

    required_perms = NOTES

    def post(self, request, pk):
        c = get_complaint(request.user, pk)
        note = services.add_note(c.pk, request.user, body(request).get('text'))
        audit(request, 'complaint.note', c, after={'noteId': note.pk}, comment=note.text[:500])
        return Response(complaint_card(c, request.user), status=201)


class StatusView(AdminAPIView):
    """POST {status: new | in_progress | answered | closed}."""

    required_perms = REPLY

    def post(self, request, pk):
        c = get_complaint(request.user, pk)
        before = {'status': c.status}
        c = services.set_status(c.pk, request.user, body(request).get('status'))
        audit(request, 'complaint.status', c, before=before, after={'status': c.status})
        return Response(complaint_card(get_complaint(request.user, c.pk), request.user))


class CompensateView(AdminAPIView):
    """POST {points, comment} — компенсация баллами (операция adjustment со ссылкой на обращение)."""

    required_perms = 'complaints.compensate'

    def post(self, request, pk):
        c = get_complaint(request.user, pk)
        data = body(request)
        try:
            points = int(data.get('points'))
        except (TypeError, ValueError):
            raise field_error('points', 'целое число')
        if points <= 0:
            raise field_error('points', 'больше 0')
        op = services.compensate(c, request.user, points, (data.get('comment') or '').strip())
        audit(request, 'complaint.compensate', c, after={'points': points, 'operationId': op.pk},
              comment=op.reason)
        return Response(complaint_card(c, request.user), status=201)


# ---------------------------------------------------------------- темы и шаблоны ответов

class CategoriesView(CollectionView):
    model = ComplaintCategory
    serializer_class = ComplaintCategorySerializer
    audit_name = 'complaint_category'
    required_perms = {'GET': VIEW, 'POST': SETTINGS}


class CategoryDetailView(DetailView):
    model = ComplaintCategory
    serializer_class = ComplaintCategorySerializer
    audit_name = 'complaint_category'
    required_perms = {'GET': VIEW, 'PATCH': SETTINGS, 'PUT': SETTINGS, 'DELETE': SETTINGS}


class CategoriesSortView(SortView):
    model = ComplaintCategory
    audit_name = 'complaint_category'
    required_perms = SETTINGS


class TemplatesView(CollectionView):
    """GET ?category="""

    model = ReplyTemplate
    serializer_class = ReplyTemplateSerializer
    audit_name = 'reply_template'
    required_perms = {'GET': REPLY, 'POST': SETTINGS}

    def filter_queryset(self, qs):
        cat = self.request.query_params.get('category')
        return qs.filter(Q(category_id=cat) | Q(category__isnull=True)) if cat else qs


class TemplateDetailView(DetailView):
    model = ReplyTemplate
    serializer_class = ReplyTemplateSerializer
    audit_name = 'reply_template'
    required_perms = {'GET': REPLY, 'PATCH': SETTINGS, 'PUT': SETTINGS, 'DELETE': SETTINGS}


class TemplatesSortView(SortView):
    model = ReplyTemplate
    audit_name = 'reply_template'
    required_perms = SETTINGS
