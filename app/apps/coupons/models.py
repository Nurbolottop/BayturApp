"""
Купоны клиента. Сейчас один источник — подарок за первую регистрацию (WelcomeOffer): одноразовый купон
с QR, который кассир сканирует и гасит. Что именно дарить (скидка %, сумма, подарок) — задаётся в админке;
по умолчанию механизм выключен.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.ids import new_id


def new_coupon_id():
    return new_id('cpn')


class CouponKind(models.TextChoices):
    PERCENT = 'percent', 'Скидка, %'
    AMOUNT = 'amount', 'Скидка, сом'
    GIFT = 'gift', 'Подарок / услуга'


class CouponStatus(models.TextChoices):
    ACTIVE = 'active', 'Действует'
    REDEEMED = 'redeemed', 'Использован'
    EXPIRED = 'expired', 'Истёк'
    CANCELLED = 'cancelled', 'Отменён'


class WelcomeOffer(models.Model):
    """Подарок за первую регистрацию (одна запись). Выключен, пока заказчик не решит, что дарить."""

    enabled = models.BooleanField('Выдавать при регистрации', default=False)
    kind = models.CharField('Вид', max_length=10, choices=CouponKind.choices, default=CouponKind.PERCENT)
    value = models.PositiveIntegerField('Размер (% или сом)', default=0,
                                        help_text='Для «Скидка, %» — проценты, для «Скидка, сом» — сумма; для подарка не нужен')
    title = models.JSONField('Название', default=dict, help_text='Например: «Скидка 10% на первое проживание»')
    description = models.JSONField('Описание', default=dict, blank=True)
    terms = models.JSONField('Условия', default=dict, blank=True)
    valid_days = models.PositiveSmallIntegerField('Действует, дней с регистрации', default=90)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Подарок за регистрацию'
        verbose_name_plural = 'Подарок за регистрацию'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class CouponGrant(models.Model):
    """Купон за регистрацию — один раз на номер навсегда (повторная регистрация после удаления не получает)."""

    phone_hash = models.CharField(max_length=64, unique=True)
    member = models.ForeignKey('members.Member', null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(default=timezone.now)


class Coupon(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_coupon_id, editable=False)
    member = models.ForeignKey('members.Member', on_delete=models.PROTECT, related_name='coupons')
    source = models.CharField(max_length=20, default='welcome')
    # снимок условий на момент выдачи — правка подарка в админке на выданные купоны не влияет
    kind = models.CharField(max_length=10, choices=CouponKind.choices)
    value = models.PositiveIntegerField(default=0)
    title = models.JSONField(default=dict)
    description = models.JSONField(default=dict, blank=True)
    terms = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=CouponStatus.choices, default=CouponStatus.ACTIVE,
                              db_index=True)
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+')
    note = models.CharField('Комментарий кассира', max_length=300, blank=True)

    class Meta:
        ordering = ['-issued_at']
        verbose_name = 'Купон'
        verbose_name_plural = 'Купоны'

    def __str__(self):
        return self.id

    @property
    def is_usable(self):
        return self.status == CouponStatus.ACTIVE and (self.expires_at is None or self.expires_at > timezone.now())
