"""Отдел роли и три роли админов отделов: номера (ресепшен), рестораны, развлечения."""
from django.db import migrations, models

ROLES = [
    ('admin-rooms', 'Админ номеров (ресепшен)', 'rooms'),
    ('admin-food', 'Админ ресторанов', 'food'),
    ('admin-entertainment', 'Админ развлечений', 'entertainment'),
]


def seed(apps, schema_editor):
    from apps.staff.roles import DEPARTMENT_DEFAULT
    StaffRole = apps.get_model('staff', 'StaffRole')
    for pk, name, dept in ROLES:
        StaffRole.objects.get_or_create(pk=pk, defaults={'name': name, 'kind': 'panel', 'department': dept,
                                                         'permissions': sorted(DEPARTMENT_DEFAULT)})


class Migration(migrations.Migration):

    dependencies = [
        ('staff', '0007_seed_roles'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffrole',
            name='department',
            field=models.CharField(blank=True, default='', help_text='Пусто — все разделы; иначе только разделы отдела (roles.DEPARTMENTS)', max_length=20, verbose_name='Отдел'),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
