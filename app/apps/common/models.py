import datetime
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import timezone

from .ids import new_upload_id


class ProgramSettings(models.Model):
    """
    Глобальные настройки программы (одна строка). Всё, что ТЗ называет «настраивается
    в админке». Изменения действуют только на новые заявки — отправленные хранят снимок.
    """

    CACHE_KEY = 'program_settings'

    # Курс и кешбек
    points_per_som = models.PositiveIntegerField('Оплата баллами: баллов за 1 сом', default=10,
                                                 help_text='Курс списания при оплате баллами. На начисление не влияет')
    base_cashback_rate = models.DecimalField('Начисление: баллов за 1 сом оплаты деньгами (Бронза)', max_digits=6,
                                             decimal_places=4, default=Decimal('0.05'),
                                             help_text='0.05 = 10/200: за 100 000 сом — 5 000 баллов; надбавка '
                                                       'уровня умножает (Уровни → «Надбавка к кешбеку»)')
    birthday_multiplier = models.DecimalField('Множитель дня рождения', max_digits=4, decimal_places=2, default=2)
    birthday_days_before = models.PositiveSmallIntegerField('Окно ДР: дней до', default=3)
    birthday_days_after = models.PositiveSmallIntegerField('Окно ДР: дней после', default=3)

    # Жизненный цикл заявки
    auto_confirm = models.BooleanField('Автоподтверждение заявок', default=False)
    auto_confirm_cash = models.BooleanField('Автоподтверждение и для наличных', default=False)
    confirm_delay_ms = models.PositiveIntegerField('Задержка автоподтверждения, мс', default=5000)
    credit_delay_ms = models.PositiveIntegerField('Задержка начисления после подтверждения, мс', default=2500)
    pending_ttl_hours = models.PositiveIntegerField('Срок жизни заявки в pending, ч', default=72)
    staff_adjust_threshold_percent = models.PositiveSmallIntegerField(
        'Правка суммы администратором без директора, %', default=20)
    staff_cashback_limit_points = models.PositiveIntegerField(
        'Кешбек выше лимита — подтверждает директор, баллов', default=10_000)

    # Удаление аккаунта (баллы не сгорают — ТЗ лояльности §2.2)
    purge_days = models.PositiveSmallIntegerField('Хранение удалённого аккаунта, дней', default=30)

    # Вход по SMS
    otp_length = models.PositiveSmallIntegerField('Длина SMS-кода', default=4)
    otp_ttl_seconds = models.PositiveIntegerField('Срок жизни кода, с', default=120)
    otp_retry_seconds = models.PositiveIntegerField('Повторный запрос кода через, с', default=60)
    otp_max_attempts = models.PositiveSmallIntegerField('Попыток ввода кода', default=5)
    otp_per_phone_day = models.PositiveSmallIntegerField('SMS на номер в сутки', default=10)
    otp_per_ip_hour = models.PositiveSmallIntegerField('SMS с одного IP в час', default=20)
    min_age = models.PositiveSmallIntegerField('Минимальный возраст', default=16)

    # Тестовый аккаунт для сторов
    test_enabled = models.BooleanField('Тестовый аккаунт включён', default=False)
    test_phone = models.CharField('Тестовый номер', max_length=20, blank=True)
    test_code = models.CharField('Фиксированный код', max_length=8, blank=True)

    # Приложение
    min_version_ios = models.CharField('Мин. версия iOS', max_length=20, default='0.0.0')
    min_version_android = models.CharField('Мин. версия Android', max_length=20, default='0.0.0')
    maintenance = models.BooleanField('Техработы', default=False)
    maintenance_message = models.JSONField('Текст о техработах', default=dict, blank=True)

    # Контакты курорта
    resort_phone = models.CharField('Телефон курорта', max_length=30, default='+996312000000')
    resort_whatsapp = models.CharField('WhatsApp (без +)', max_length=30, default='996555000000')
    resort_maps_url = models.URLField('Карта', default='https://maps.app.goo.gl/baytur', blank=True)

    # Уведомления
    promo_push_monthly_limit = models.PositiveSmallIntegerField('Рекламных push в месяц', default=4)
    quiet_hours_start = models.TimeField('Тихие часы с', default=datetime.time(22, 0))
    quiet_hours_end = models.TimeField('Тихие часы до', default=datetime.time(9, 0))
    notification_retention_days = models.PositiveSmallIntegerField('Хранить уведомления, дней', default=30)

    # Обращения
    complaint_first_response_hours = models.PositiveSmallIntegerField('Срок первого ответа, ч', default=4)
    complaint_daily_limit = models.PositiveSmallIntegerField('Новых обращений в сутки на клиента', default=5)
    complaint_alert_emails = models.JSONField('Email для уведомлений об обращениях', default=list, blank=True)

    # QR участника
    member_qr_ttl_seconds = models.PositiveSmallIntegerField('Срок жизни QR участника, с', default=90)

    # Аналитика
    analytics_raw_retention_days = models.PositiveIntegerField('Хранить сырые события, дней', default=395)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Настройки программы'
        verbose_name_plural = 'Настройки программы'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def get(cls):
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, obj, 30)
        return obj


class AuditLog(models.Model):
    """Журнал админ-действий: кто, когда, с какого IP, было / стало. Не редактируется."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='audit_entries')
    actor_label = models.CharField(max_length=200, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=60, blank=True, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ['-at', '-id']
        verbose_name = 'Запись аудита'
        verbose_name_plural = 'Аудит-лог'

    def save(self, *args, **kwargs):
        if self.pk:
            raise RuntimeError('Аудит-лог не редактируется')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError('Аудит-лог не удаляется')


def upload_path(instance, filename):
    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else 'jpg').lower()
    return f'uploads/{instance.kind}/{instance.created_at:%Y/%m}/{instance.id}.{ext}'


class Upload(models.Model):
    """Загруженные изображения (админка, фото к обращениям)."""

    KIND_IMAGE = 'image'
    KIND_COMPLAINT = 'complaint'
    KIND_AVATAR = 'avatar'
    KINDS = [(KIND_IMAGE, 'Изображение'), (KIND_COMPLAINT, 'Фото к обращению'), (KIND_AVATAR, 'Аватар')]

    id = models.CharField(primary_key=True, max_length=32, default=new_upload_id, editable=False)
    kind = models.CharField(max_length=20, choices=KINDS, default=KIND_IMAGE)
    file = models.FileField(upload_to=upload_path, max_length=255)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    member = models.ForeignKey('members.Member', null=True, blank=True, on_delete=models.CASCADE,
                               related_name='uploads')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='uploads')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    @property
    def url(self):
        from .media import absolute_media_url
        return absolute_media_url(self.file.name)
