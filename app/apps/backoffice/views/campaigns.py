"""
Push-рассылки (ТЗ §7.2): редактор — только черновики; отправка (сразу или по времени) — владелец и менеджер.
Уходят только клиентам с notifyPromos и согласием на рекламу (notifications.services.campaign_audience).
"""
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response

from apps.common.audit import audit, model_snapshot
from apps.common.errors import ApiError
from apps.notifications.models import Campaign, CampaignStatus, PushKind, PushTemplate
from apps.notifications.services import campaign_audience, send_campaign_test

from ..base import AdminAPIView, CollectionView, DetailView, ObjectView, body, not_found, parse_moment
from ..serializers import CampaignSerializer, PushTemplateSerializer

log = logging.getLogger(__name__)

DRAFT = 'campaigns.draft'
SEND = 'campaigns.send'
READ = [DRAFT, SEND]


class CampaignsView(CollectionView):
    """GET ?status=&cursor= ; POST — черновик."""

    model = Campaign
    serializer_class = CampaignSerializer
    audit_name = 'campaign'
    required_perms = {'GET': READ, 'POST': DRAFT}
    paginated = True

    def filter_queryset(self, qs):
        status = self.request.query_params.get('status')
        return qs.filter(status=status) if status else qs

    def perform_create(self, serializer):
        return serializer.save(created_by=self.request.user, status=CampaignStatus.DRAFT)


class CampaignDetailView(DetailView):
    model = Campaign
    serializer_class = CampaignSerializer
    audit_name = 'campaign'
    required_perms = {'GET': READ, 'PATCH': READ, 'PUT': READ, 'DELETE': READ}

    def get(self, request, pk):
        c = self.get_object()
        return Response({**self.serialize(c), 'audience': campaign_audience(c).count()})

    def check_editable(self, c):
        # запланированную может менять только тот, кто вправе отправлять; отправленную — никто
        if c.status == CampaignStatus.DRAFT:
            return
        if c.status == CampaignStatus.SCHEDULED and self.request.user.can(SEND):
            return
        raise ApiError('invalid_status', 409, extra={'status': c.status})

    def patch(self, request, pk):
        self.check_editable(self.get_object())
        return super().patch(request, pk=pk)

    put = patch

    def check_delete(self, c):
        self.check_editable(c)


class CampaignSendView(ObjectView):
    """
    POST {scheduledAt?} — будущая дата → scheduled; иначе отправка сейчас (через очередь).
    Если брокер недоступен, рассылку подхватит периодическая задача send_scheduled_campaigns.
    """

    model = Campaign
    serializer_class = CampaignSerializer
    audit_name = 'campaign'
    required_perms = SEND

    def post(self, request, pk):
        now = timezone.now()
        at = parse_moment(body(request).get('scheduledAt'), 'scheduledAt')
        with transaction.atomic():
            c = Campaign.objects.select_for_update().filter(pk=pk).first()
            if c is None:
                raise not_found()
            if c.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED):
                raise ApiError('invalid_status', 409, extra={'status': c.status})
            before = {'status': c.status, 'scheduledAt': c.scheduled_at}
            c.status = CampaignStatus.SCHEDULED
            c.scheduled_at = at if at and at > now else now
            c.save(update_fields=['status', 'scheduled_at'])
            audit(request, 'campaign.send' if c.scheduled_at <= now else 'campaign.schedule', c, before=before,
                  after={'status': c.status, 'scheduledAt': c.scheduled_at})
        if c.scheduled_at <= now:
            transaction.on_commit(lambda: _enqueue_send(c.pk))
        return Response(self.serialize(c))


def _enqueue_send(campaign_id):
    from apps.notifications.tasks import send_campaign_task
    try:
        send_campaign_task.delay(campaign_id)
    except Exception:  # брокер недоступен — отправит периодическая задача
        log.warning('campaign %s: enqueue failed, periodic job will send it', campaign_id)


class CampaignCancelView(ObjectView):
    """POST — отменить запланированную рассылку."""

    model = Campaign
    serializer_class = CampaignSerializer
    audit_name = 'campaign'
    required_perms = SEND

    def post(self, request, pk):
        c = self.get_object()
        if c.status != CampaignStatus.SCHEDULED:
            raise ApiError('invalid_status', 409, extra={'status': c.status})
        before = model_snapshot(c)
        c.status = CampaignStatus.CANCELLED
        c.save(update_fields=['status'])
        audit(request, 'campaign.cancel', c, before=before, after=model_snapshot(c))
        return Response(self.serialize(c))


class CampaignTestView(ObjectView):
    """POST — тестовая отправка себе: на клиентский аккаунт с телефоном сотрудника."""

    model = Campaign
    serializer_class = CampaignSerializer
    audit_name = 'campaign'
    required_perms = READ

    def post(self, request, pk):
        c = self.get_object()
        n = send_campaign_test(c, request.user)
        if n is None:
            raise ApiError('validation_error', 422, message='Укажите в профиле сотрудника телефон, привязанный к '
                                                            'клиентскому аккаунту в приложении',
                           extra={'fields': {'phone': ['нет клиентского аккаунта с этим номером']}})
        audit(request, 'campaign.test', c)
        return Response({'sent': True})


# ---------------------------------------------------------------- шаблоны push

class PushTemplatesView(AdminAPIView):
    """Все ключи PushKind; незаполненные — пустыми {ru, ky, en}."""

    required_perms = 'content.edit'

    def get(self, request):
        existing = {t.kind: t for t in PushTemplate.objects.all()}
        items = []
        for kind, label in PushKind.choices:
            t = existing.get(kind) or PushTemplate(kind=kind)
            items.append({**PushTemplateSerializer(t, context=self.ctx()).data, 'label': label,
                          'isDefault': kind not in existing})
        return Response({'items': items})


class PushTemplateDetailView(AdminAPIView):
    """PUT/PATCH /push-templates/{kind} {title, body}. Плейсхолдеры: {points}, {tier}, {number}, {days}, {item}."""

    required_perms = 'content.edit'

    def get_object(self, kind):
        if kind not in PushKind.values:
            raise not_found()
        return PushTemplate.objects.filter(kind=kind).first() or PushTemplate(kind=kind)

    def get(self, request, kind):
        return Response(PushTemplateSerializer(self.get_object(kind), context=self.ctx()).data)

    def patch(self, request, kind):
        t = self.get_object(kind)
        before = model_snapshot(t) if t.pk and PushTemplate.objects.filter(pk=t.pk).exists() else None
        s = PushTemplateSerializer(t, data=body(request), partial=before is not None, context=self.ctx())
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            t = s.save()
            audit(request, 'push_template.update', t, before=before, after=model_snapshot(t))
        return Response(PushTemplateSerializer(t, context=self.ctx()).data)

    put = patch
