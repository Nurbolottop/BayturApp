"""
25.10.2026: директор больше не ведёт услуги и контент. Маркетологу — тексты и фото услуг, уровней и привилегий
(вместе с контентом, акциями, push и подарком новичку); кураторам отделов — без акций (их ведёт маркетолог).
"""
from django.db import migrations

MARKETING_ADD = {'catalog.texts', 'tiers.texts', 'content.edit', 'promotions.edit', 'coupons.manage',
                 'campaigns.draft', 'campaigns.send'}
DEPARTMENT_REMOVE = {'promotions.edit'}


def forward(apps, schema_editor):
    StaffRole = apps.get_model('staff', 'StaffRole')
    for role in StaffRole.objects.filter(pk='marketing'):
        role.permissions = sorted(set(role.permissions or []) | MARKETING_ADD)
        role.save(update_fields=['permissions'])
    for role in StaffRole.objects.exclude(department=''):
        role.permissions = sorted(set(role.permissions or []) - DEPARTMENT_REMOVE)
        role.save(update_fields=['permissions'])
    from django.core.cache import cache
    cache.delete('staff_roles:v2')


class Migration(migrations.Migration):
    dependencies = [('staff', '0008_role_department')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
