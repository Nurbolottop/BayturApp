"""Названия режимов в панели и приложении: Baytur Ski и Baytur Kymyz. Переименованные в админке не трогаем."""
from django.db import migrations

OLD = {'ski': {'Тоо-Ашуу'}, 'kymyz': {'Суусамыр', 'Кымызолечение Суусамыр'}}
NEW = {'ski': 'Baytur Ski', 'kymyz': 'Baytur Kymyz'}


def forward(apps, schema_editor):
    Venue = apps.get_model('catalog', 'Venue')
    for venue in Venue.objects.filter(pk__in=NEW):
        if (venue.name or {}).get('ru') in OLD[venue.pk]:
            venue.name = {'ru': NEW[venue.pk], 'ky': NEW[venue.pk], 'en': NEW[venue.pk]}
            venue.save(update_fields=['name'])


class Migration(migrations.Migration):
    dependencies = [('catalog', '0007_modes_data')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
