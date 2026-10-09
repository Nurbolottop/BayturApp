"""
Курс оплаты баллами — настройка курорта (Настройки → Программа). Миграция 0008 ошибочно сбросила его на 1;
возвращаем значение, выставленное в админке 02.10.2026: 10 баллов = 1 сом. Дальше миграции его не трогают.
"""
from django.db import migrations


def forward(apps, schema_editor):
    apps.get_model('common', 'ProgramSettings').objects.filter(points_per_som=1).update(points_per_som=10)


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0010_points_rate_labels'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
