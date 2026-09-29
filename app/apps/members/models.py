import secrets

from django.db import models
from django.db.models import Q
from django.utils import timezone


class MemberStatus(models.TextChoices):
    ACTIVE = 'active', 'Активен'
    DEACTIVATED = 'deactivated', 'Удалён (хранится)'
    PURGED = 'purged', 'Стёрт'
    BLOCKED = 'blocked', 'Заблокирован'


class Language(models.TextChoices):
    RU = 'ru', 'Русский'
    KY = 'ky', 'Кыргызча'
    EN = 'en', 'English'


def generate_member_id():
    """BT- + 6 цифр, уникальный, не меняется."""
    for _ in range(50):
        candidate = f'BT-{secrets.randbelow(900000) + 100000:06d}'
        if not Member.objects.filter(member_id=candidate).exists():
            return candidate
    raise RuntimeError('Не удалось сгенерировать memberId')


class Member(models.Model):
    """Участник программы (клиент мобильного приложения)."""

    member_id = models.CharField('Номер участника', max_length=12, unique=True)
    phone = models.CharField('Телефон (E.164)', max_length=20, null=True, blank=True)
    first_name = models.CharField('Имя', max_length=50, blank=True)
    last_name = models.CharField('Фамилия', max_length=50, blank=True)
    email = models.EmailField('Email', blank=True)
    birthday = models.DateField('Дата рождения', null=True, blank=True)
    gender = models.CharField('Пол', max_length=10, blank=True)
    avatar = models.ForeignKey('common.Upload', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                               verbose_name='Аватар')
    member_since = models.DateField('Участник с', default=timezone.localdate)
    status = models.CharField('Статус', max_length=20, choices=MemberStatus.choices, default=MemberStatus.ACTIVE)
    blocked_reason = models.TextField(blank=True)

    # Настройки (тема/звуки — только в приложении)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.RU)
    notify_cashback = models.BooleanField(default=True)
    notify_promos = models.BooleanField(default=True)
    marketing_consent = models.BooleanField(default=False)

    # Удаление аккаунта (§2.5)
    deleted_at = models.DateTimeField(null=True, blank=True)
    purge_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    restored_at = models.DateTimeField(null=True, blank=True)
    purge_immediately = models.BooleanField(default=False)

    is_test = models.BooleanField('Тестовый аккаунт для сторов', default=False)
    first_device_id = models.CharField(max_length=36, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    is_member = True
    is_staff_user = False
    is_authenticated = True
    is_anonymous = False

    class Meta:
        verbose_name = 'Участник'
        verbose_name_plural = 'Участники'
        ordering = ['-created_at']
        constraints = [
            # Номер освобождается после окончательного удаления (phone = NULL)
            models.UniqueConstraint(fields=['phone'], condition=Q(phone__isnull=False), name='member_phone_unique'),
        ]

    def __str__(self):
        return f'{self.member_id} {self.full_name}'.strip()

    @property
    def full_name(self):
        if self.status == MemberStatus.PURGED:
            return 'Удалённый участник'
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def is_frozen(self):
        return self.status != MemberStatus.ACTIVE

    def save(self, *args, **kwargs):
        if not self.member_id:
            self.member_id = generate_member_id()
        super().save(*args, **kwargs)


class OtpPurpose(models.TextChoices):
    LOGIN = 'login'
    DELETION = 'deletion'


class OtpChallenge(models.Model):
    phone = models.CharField(max_length=20, db_index=True)
    purpose = models.CharField(max_length=20, choices=OtpPurpose.choices, default=OtpPurpose.LOGIN)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    burned = models.BooleanField(default=False)
    ip = models.GenericIPAddressField(null=True, blank=True)
    device_id = models.CharField(max_length=36, blank=True)

    class Meta:
        ordering = ['-created_at']


class MemberRefreshToken(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='refresh_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    family = models.CharField(max_length=32, db_index=True)
    device_id = models.CharField(max_length=36, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)


class Platform(models.TextChoices):
    IOS = 'ios'
    ANDROID = 'android'


class Device(models.Model):
    """Push-токен устройства (FCM)."""

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='devices')
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=10, choices=Platform.choices)
    app_version = models.CharField(max_length=20, blank=True)
    device_id = models.CharField(max_length=36, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class LegalKind(models.TextChoices):
    TERMS = 'terms', 'Условия программы'
    PRIVACY = 'privacy', 'Политика конфиденциальности'
    DELETION = 'deletion', 'Страница удаления аккаунта'


class LegalDocument(models.Model):
    """Версии документов. Публикация новой версии terms/privacy → pendingConsents у всех."""

    kind = models.CharField(max_length=20, choices=LegalKind.choices)
    version = models.CharField(max_length=20)
    url = models.JSONField('URL на 3 языках', default=dict)
    requires_acceptance = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['kind', '-published_at']
        constraints = [models.UniqueConstraint(fields=['kind', 'version'], name='legal_kind_version_unique')]
        verbose_name = 'Документ'
        verbose_name_plural = 'Документы'

    def __str__(self):
        return f'{self.get_kind_display()} v{self.version}'

    @classmethod
    def current(cls, kind):
        return cls.objects.filter(kind=kind, published_at__isnull=False,
                                  published_at__lte=timezone.now()).order_by('-published_at').first()


class ConsentKind(models.TextChoices):
    TERMS = 'terms'
    PRIVACY = 'privacy'
    MARKETING = 'marketing'


class Consent(models.Model):
    """Кто, когда и какую версию принял (требование сторов)."""

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='consents')
    kind = models.CharField(max_length=20, choices=ConsentKind.choices)
    version = models.CharField(max_length=20, blank=True)
    granted = models.BooleanField(default=True)
    at = models.DateTimeField(default=timezone.now)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-at']
