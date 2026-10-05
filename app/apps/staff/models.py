import pyotp
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .roles import Role, role_has


class StaffManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email=None, password=None, **extra):
        if not email and not extra.get('phone'):
            raise ValueError('нужен email (директор) или телефон (администратор)')
        user = self.model(email=self.normalize_email(email).lower() if email else None, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('role', Role.OWNER)
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra)


class StaffUser(AbstractBaseUser, PermissionsMixin):
    """
    Сотрудник. Директор входит в веб-панель (email + пароль + TOTP), администратор кассы —
    в приложение кассира (телефон + 6-значный PIN). Отдельно от клиентов.
    """

    email = models.EmailField('Email', unique=True, null=True, blank=True)
    full_name = models.CharField('Имя', max_length=150)
    role = models.CharField('Роль', max_length=20, choices=Role.choices, default=Role.STAFF)
    phone = models.CharField('Телефон', max_length=20, blank=True,
                             help_text='Вход администратора в приложение; сотрудник не подтверждает заявки '
                                       'своего клиентского аккаунта')
    pin_hash = models.CharField(max_length=128, blank=True)
    pin_failed = models.PositiveSmallIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)
    outlets = models.ManyToManyField('catalog.Outlet', blank=True, related_name='staff', verbose_name='Точки')
    is_active = models.BooleanField('Активен', default=True)
    is_staff = models.BooleanField('Доступ к техническому Django admin', default=False)
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_enabled = models.BooleanField('2FA включена', default=False)
    must_change_password = models.BooleanField('Сменить временный пароль при входе', default=False)
    created_at = models.DateTimeField(default=timezone.now)

    objects = StaffManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    is_staff_user = True
    is_member = False

    class Meta:
        verbose_name = 'Сотрудник'
        verbose_name_plural = 'Сотрудники'
        constraints = [
            models.UniqueConstraint(Lower('email'), name='staff_email_ci_unique'),
            models.UniqueConstraint(fields=['phone'], condition=~models.Q(phone=''), name='staff_phone_unique'),
        ]

    def __str__(self):
        return f'{self.full_name} <{self.email or self.phone}>'

    @property
    def is_director(self):
        return self.role == Role.OWNER or self.is_superuser

    # PIN (приложение кассира)
    def set_pin(self, pin):
        from django.contrib.auth.hashers import make_password
        self.pin_hash = make_password(pin)
        self.pin_failed = 0
        self.pin_locked_until = None

    def check_pin(self, pin):
        from django.contrib.auth.hashers import check_password
        return bool(self.pin_hash) and check_password(pin or '', self.pin_hash)

    # Права
    def can(self, perm):
        return self.is_active and (self.is_superuser or role_has(self.role, perm))

    @property
    def outlet_ids(self):
        if not hasattr(self, '_outlet_ids'):
            self._outlet_ids = set(self.outlets.values_list('id', flat=True))
        return self._outlet_ids

    @property
    def is_outlet_bound(self):
        """Сотрудник видит только свои точки; остальные роли — все."""
        return self.role == Role.STAFF and not self.is_superuser

    def sees_outlet(self, outlet_id):
        return not self.is_outlet_bound or outlet_id in self.outlet_ids

    # TOTP
    def ensure_totp_secret(self):
        if not self.totp_secret:
            self.totp_secret = pyotp.random_base32()
            self.save(update_fields=['totp_secret'])
        return self.totp_secret

    def totp_uri(self):
        return pyotp.TOTP(self.ensure_totp_secret()).provisioning_uri(name=self.email, issuer_name='BAYTUR Admin')

    def verify_totp(self, code):
        if not self.totp_secret or not code:
            return False
        return pyotp.TOTP(self.totp_secret).verify(str(code).strip(), valid_window=1)


class StaffRefreshToken(models.Model):
    staff = models.ForeignKey(StaffUser, on_delete=models.CASCADE, related_name='refresh_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    family = models.CharField(max_length=32, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
