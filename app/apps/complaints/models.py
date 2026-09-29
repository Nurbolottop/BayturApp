from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.ids import new_complaint_id


class ComplaintStatus(models.TextChoices):
    NEW = 'new', 'Новое'
    IN_PROGRESS = 'in_progress', 'В работе'
    ANSWERED = 'answered', 'Отвечено'
    CLOSED = 'closed', 'Закрыто'


class PointsSubtype(models.TextChoices):
    NOT_CREDITED = 'not_credited', 'Не начислили'
    CREDITED_LESS = 'credited_less', 'Начислили меньше'
    OVERCHARGED = 'overcharged', 'Списали лишнее'
    OTHER = 'other', 'Другое'


class ComplaintCategory(models.Model):
    """Темы: service, room, food, spa, pools_sport, points, app, other — ведутся в админке."""

    id = models.SlugField(primary_key=True, max_length=30)
    title = models.JSONField(default=dict)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Тема обращения'
        verbose_name_plural = 'Темы обращений'

    def __str__(self):
        return self.title.get('ru') or self.id


class ReplyTemplate(models.Model):
    title = models.CharField(max_length=120)
    text = models.JSONField(default=dict)
    category = models.ForeignKey(ComplaintCategory, null=True, blank=True, on_delete=models.SET_NULL)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']


def next_complaint_number():
    last = Complaint.objects.order_by('-seq').values_list('seq', flat=True).first() or 0
    return last + 1


class Complaint(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_complaint_id, editable=False)
    seq = models.PositiveIntegerField(unique=True)
    member = models.ForeignKey('members.Member', on_delete=models.PROTECT, related_name='complaints')
    category = models.ForeignKey(ComplaintCategory, on_delete=models.PROTECT, related_name='complaints')
    subtype = models.CharField(max_length=20, choices=PointsSubtype.choices, blank=True)
    outlet = models.ForeignKey('catalog.Outlet', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='complaints')
    request = models.ForeignKey('cashback.CashbackRequest', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='complaints')
    operation = models.ForeignKey('loyalty.Operation', null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='complaints')
    status = models.CharField(max_length=20, choices=ComplaintStatus.choices, default=ComplaintStatus.NEW,
                              db_index=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_comment = models.TextField(blank=True)
    priority = models.CharField(max_length=10, default='normal')  # low | normal | high
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='assigned_complaints')
    tags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField(null=True, blank=True)
    first_reply_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    overdue_notified = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Обращение'
        verbose_name_plural = 'Обращения'

    @property
    def number(self):
        return f'О-{self.seq:06d}'

    def __str__(self):
        return self.number

    @property
    def is_overdue(self):
        return self.first_reply_at is None and self.due_at is not None and timezone.now() > self.due_at \
            and self.status != ComplaintStatus.CLOSED


class ComplaintMessage(models.Model):
    AUTHOR_CLIENT = 'client'
    AUTHOR_RESORT = 'resort'

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='messages')
    author = models.CharField(max_length=10, choices=[(AUTHOR_CLIENT, 'Клиент'), (AUTHOR_RESORT, 'Курорт')])
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+')
    text = models.TextField()
    attachments = models.ManyToManyField('common.Upload', blank=True, related_name='+')
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['at', 'id']


class ComplaintNote(models.Model):
    """Внутренняя заметка — клиенту не отдаётся."""

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='notes')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    text = models.TextField()
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['at', 'id']
