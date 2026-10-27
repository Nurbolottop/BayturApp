"""27.10.2026: уровни и привилегии целиком (и тексты, и оформление) редактирует только директор."""
from django.db import migrations


def forward(apps, schema_editor):
    StaffRole = apps.get_model('staff', 'StaffRole')
    for role in StaffRole.objects.exclude(pk='owner'):
        perms = [p for p in (role.permissions or []) if p not in ('tiers.texts', 'tiers.edit')]
        if perms != list(role.permissions or []):
            role.permissions = sorted(perms)
            role.save(update_fields=['permissions'])
    from django.core.cache import cache
    cache.delete('staff_roles:v2')


class Migration(migrations.Migration):
    dependencies = [('staff', '0010_marketing_without_analytics')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
