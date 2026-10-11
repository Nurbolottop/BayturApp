"""
Место режима (поле place в /services, ТЗ §6.3: «Суусамыр») и правки прайса из письма мобильщиков:
«↔» iOS рисует эмодзи — заменяем на «—»; «1 кружка (20–250 г)» — опечатка исходного прайса, 200–250 г.
Отдельно от изменений схемы (Postgres: pending trigger events).
"""
import json

from django.db import migrations

PLACES = {
    'resort': {'ru': 'Иссык-Куль', 'ky': 'Ысык-Көл', 'en': 'Issyk-Kul'},
    'ski': {'ru': 'Тоо-Ашуу', 'ky': 'Тоо-Ашуу', 'en': 'Too-Ashuu'},
    'kymyz': {'ru': 'Суусамыр', 'ky': 'Суусамыр', 'en': 'Suusamyr'},
}
REPLACE = (('↔', '—'), ('20–250 г', '200–250 г'), ('20–250 g', '200–250 g'))


def fix(value):
    raw = json.dumps(value, ensure_ascii=False)
    new = raw
    for a, b in REPLACE:
        new = new.replace(a, b)
    return (json.loads(new), True) if new != raw else (value, False)


def forward(apps, schema_editor):
    Venue = apps.get_model('catalog', 'Venue')
    for venue in Venue.objects.filter(pk__in=PLACES):
        if not (venue.place or {}).get('ru'):
            venue.place = PLACES[venue.pk]
            venue.save(update_fields=['place'])
    for model, fields in (('Venue', ('name', 'short', 'description', 'address', 'contacts', 'info')),
                          ('Section', ('title', 'subtitle', 'note')),
                          ('Item', ('title', 'meta', 'price_note', 'description', 'features', 'tag')),
                          ('InfoBlock', ('title', 'lines')),
                          ('Promotion', ('title', 'description', 'note'))):
        Model = apps.get_model('catalog', model)
        for obj in Model.objects.all():
            changed = []
            for f in fields:
                value, ok = fix(getattr(obj, f))
                if ok:
                    setattr(obj, f, value)
                    changed.append(f)
            if changed:
                obj.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [('catalog', '0009_venue_place')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
