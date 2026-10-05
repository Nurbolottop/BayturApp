"""Две роли: менеджер, редактор, бухгалтер и служба заботы становятся директорами; телефоны — в E.164."""
import re

from django.db import migrations

OLD_OFFICE_ROLES = ['manager', 'editor', 'accountant', 'care']


def forward(apps, schema_editor):
    StaffUser = apps.get_model('staff', 'StaffUser')
    StaffUser.objects.filter(role__in=OLD_OFFICE_ROLES).update(role='owner')
    seen = set()
    for u in StaffUser.objects.exclude(phone='').order_by('pk'):
        phone = re.sub(r'[\s\-()]', '', u.phone)
        if phone.startswith('00'):
            phone = '+' + phone[2:]
        if not phone.startswith('+'):
            phone = '+' + phone
        if not re.match(r'^\+[1-9]\d{7,14}$', phone) or phone in seen:
            phone = ''  # некорректный или повтор — директор задаст заново
        seen.add(phone)
        if phone != u.phone:
            u.phone = phone
            u.save(update_fields=['phone'])


class Migration(migrations.Migration):

    dependencies = [
        ('staff', '0002_staffuser_must_change_password'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
