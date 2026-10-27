"""27.10.2026: аналитика маркетингу не нужна — у роли «Маркетинг» убираются права analytics.*."""
from django.db import migrations


def forward(apps, schema_editor):
    StaffRole = apps.get_model('staff', 'StaffRole')
    for role in StaffRole.objects.filter(pk='marketing'):
        role.permissions = sorted(p for p in (role.permissions or []) if not p.startswith('analytics.'))
        role.save(update_fields=['permissions'])
    from django.core.cache import cache
    cache.delete('staff_roles:v2')


class Migration(migrations.Migration):
    dependencies = [('staff', '0009_owner_without_content')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
