"""Системные роли (Директор, Администратор кассы) и роль «Маркетинг» с правами по умолчанию."""
from django.db import migrations


def seed(apps, schema_editor):
    from apps.staff.roles import MARKETING_DEFAULT, PERMISSIONS, default_permissions
    StaffRole = apps.get_model('staff', 'StaffRole')
    rows = [
        ('owner', 'Директор', 'panel', sorted(PERMISSIONS), True),
        ('staff', 'Администратор кассы', 'app', default_permissions('staff'), True),
        ('marketing', 'Маркетинг', 'panel', sorted(MARKETING_DEFAULT), False),
    ]
    for pk, name, kind, perms, system in rows:
        StaffRole.objects.get_or_create(pk=pk, defaults={'name': name, 'kind': kind, 'permissions': perms,
                                                         'is_system': system})


class Migration(migrations.Migration):
    dependencies = [('staff', '0006_staff_roles')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
