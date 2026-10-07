"""
ТЗ лояльности 08.10.2026: 1 балл = 1 сом, базовая ставка кешбека 10/200 = 5 %. Балансы клиентов не пересчитываются.
Лимит кешбека, выше которого заявку подтверждает директор, переводится в новые баллы (÷100), чтобы порог в сомах
остался прежним.
"""
from decimal import Decimal

from django.db import migrations


def forward(apps, schema_editor):
    ProgramSettings = apps.get_model('common', 'ProgramSettings')
    for ps in ProgramSettings.objects.all():
        if ps.points_per_som == 100:
            ps.staff_cashback_limit_points = max(1, ps.staff_cashback_limit_points // 100)
        ps.points_per_som, ps.base_cashback_rate = 1, Decimal('0.05')
        ps.save(update_fields=['points_per_som', 'base_cashback_rate', 'staff_cashback_limit_points'])


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0007_tier_cashback_permanent'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
