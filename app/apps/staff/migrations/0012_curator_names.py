"""27.10.2026: роли отделов называются «Куратор …» (как их называют на курорте)."""
from django.db import migrations

NAMES = {'admin-rooms': ('Админ номеров (ресепшен)', 'Куратор номеров (ресепшен)'),
         'admin-food': ('Админ ресторанов', 'Куратор ресторанов'),
         'admin-entertainment': ('Админ развлечений', 'Куратор развлечений')}


def forward(apps, schema_editor):
    StaffRole = apps.get_model('staff', 'StaffRole')
    for pk, (old, new) in NAMES.items():
        StaffRole.objects.filter(pk=pk, name=old).update(name=new)  # переименованные вручную — не трогаем
    from django.core.cache import cache
    cache.delete('staff_roles:v2')


class Migration(migrations.Migration):
    dependencies = [('staff', '0011_tiers_only_director')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
