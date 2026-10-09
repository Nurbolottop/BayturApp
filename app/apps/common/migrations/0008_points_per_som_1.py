"""ТЗ лояльности 08.10.2026: базовая ставка начисления 10/200 = 5 %."""
from decimal import Decimal

from django.db import migrations


def forward(apps, schema_editor):
    # Курс оплаты баллами (points_per_som) здесь больше не трогаем — это настройка курорта (см. 0011)
    apps.get_model('common', 'ProgramSettings').objects.update(base_cashback_rate=Decimal('0.05'))


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0007_tier_cashback_permanent'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
