from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.ids import new_notification_id


class PushKind(models.TextChoices):
    """Ключи шаблонов push — тексты редактируются в админке."""
    REQUEST_CREDITED = 'request.credited', 'Кешбек начислен'
    REQUEST_REJECTED = 'request.rejected', 'Заявка отклонена'
    REQUEST_PAID = 'request.paid', 'Оплачено баллами'
    TIER_UPGRADED = 'tier.upgraded', 'Новый уровень'
    POINTS_EXPIRING = 'points.expiring', 'Баллы скоро сгорят'
    POINTS_EXPIRED = 'points.expired', 'Баллы сгорели'
    POINTS_ADJUSTED = 'points.adjusted', 'Корректировка баллов'
    COMPLAINT_REPLY = 'complaint.reply', 'Ответ на обращение'
    CAMPAIGN = 'campaign', 'Рассылка'


# Операции с баллами идут и в тихие часы
POINTS_KINDS = {PushKind.REQUEST_CREDITED, PushKind.REQUEST_REJECTED, PushKind.REQUEST_PAID, PushKind.POINTS_ADJUSTED,
                PushKind.POINTS_EXPIRED}


class PushTemplate(models.Model):
    kind = models.CharField(primary_key=True, max_length=40, choices=PushKind.choices)
    title = models.JSONField(default=dict)
    body = models.JSONField(default=dict, help_text='Плейсхолдеры: {points}, {tier}, {number}, {days}, {item}')

    class Meta:
        verbose_name = 'Шаблон push'
        verbose_name_plural = 'Шаблоны push'


class Notification(models.Model):
    """Лента под колокольчиком: хранится 30 дней, с признаком read и deep link."""

    id = models.CharField(primary_key=True, max_length=32, default=new_notification_id, editable=False)
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField()
    data = models.JSONField(default=dict, help_text='type, requestId / articleId / complaintId для диплинка')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # доставка push
    push_status = models.CharField(max_length=20, default='none')  # none | queued | sent | failed | skipped
    push_after = models.DateTimeField(null=True, blank=True, db_index=True, help_text='Отложено из-за тихих часов')
    is_promo = models.BooleanField(default=False)
    campaign = models.ForeignKey('Campaign', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='notifications')
    opened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['member', '-created_at'])]


class CampaignStatus(models.TextChoices):
    DRAFT = 'draft', 'Черновик'
    SCHEDULED = 'scheduled', 'Запланирована'
    SENDING = 'sending', 'Отправляется'
    SENT = 'sent', 'Отправлена'
    CANCELLED = 'cancelled', 'Отменена'


class Campaign(models.Model):
    """Push-рассылка из админки. Уходит только тем, у кого notifyPromos и согласие на рекламу."""

    title = models.JSONField(default=dict)
    body = models.JSONField(default=dict)
    article = models.ForeignKey('content.Article', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    item = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    segment = models.JSONField(default=dict, help_text='{"tiers": [...], "languages": [...]} — пусто = все')
    status = models.CharField(max_length=20, choices=CampaignStatus.choices, default=CampaignStatus.DRAFT)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(default=timezone.now)
    stats = models.JSONField(default=dict, help_text='sent, delivered, opened, skipped')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Push-рассылка'
        verbose_name_plural = 'Push-рассылки'
