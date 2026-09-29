from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.storage import private_storage

# Фиксированный список; неизвестные события бек отбрасывает (§7.5)
EVENT_NAMES = {
    'app_open', 'screen_view', 'login_prompt_shown', 'login_prompt_accepted', 'otp_requested',
    'registration_completed', 'service_view', 'story_view', 'article_view', 'promo_click',
    'cashback_flow_started', 'cashback_flow_step', 'cashback_flow_submitted', 'cashback_flow_abandoned',
    'push_opened',
}

# В props запрещены персональные данные — разрешаем только эти ключи
ALLOWED_PROPS = {
    'screen', 'category', 'itemId', 'slide', 'articleId', 'promoId', 'step', 'source', 'requestId',
    'campaignId', 'kind', 'method', 'from', 'duration',
}


class AppEvent(models.Model):
    """Сырые события от мобилки; хранятся 13 месяцев."""

    device_id = models.CharField(max_length=36, db_index=True)
    member = models.ForeignKey('members.Member', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    platform = models.CharField(max_length=10, blank=True)
    app_version = models.CharField(max_length=20, blank=True)
    language = models.CharField(max_length=2, blank=True)
    name = models.CharField(max_length=40, db_index=True)
    at = models.DateTimeField(db_index=True)
    props = models.JSONField(default=dict)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=['name', 'at'])]


class DeviceLink(models.Model):
    """Связь анонимного X-Device-Id с участником (для воронки гость → регистрация)."""

    device_id = models.CharField(max_length=36, unique=True)
    member = models.ForeignKey('members.Member', null=True, on_delete=models.SET_NULL, related_name='+')
    first_seen_at = models.DateTimeField(default=timezone.now)
    platform = models.CharField(max_length=10, blank=True)


class ExportJob(models.Model):
    """Фоновая выгрузка отчёта: ссылка появляется в админке по готовности."""

    report = models.CharField(max_length=40)
    params = models.JSONField(default=dict)
    fmt = models.CharField(max_length=5, default='xlsx')
    status = models.CharField(max_length=20, default='pending')  # pending | done | failed
    file = models.FileField(upload_to='exports/%Y/%m/', blank=True, storage=private_storage)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
