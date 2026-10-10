"""
Перенос данных в режимы — отдельной миграцией: в одной транзакции с изменением схемы Postgres не даёт
создать отложенные индексы после правки строк («pending trigger events»).
"""
from django.db import migrations

RENAMED = {'too-ashuu', 'suusamyr'}  # загружены 11.10 под старыми id; заявок и платежей на них нет


def to_modes(apps, schema_editor):
    """baytur → resort (ТЗ экосистемы: режимы resort / ski / kymyz); прайс ski и kymyz перезагружает load_venues."""
    Venue = apps.get_model('catalog', 'Venue')
    Outlet = apps.get_model('catalog', 'Outlet')
    Item = apps.get_model('catalog', 'Item')
    Section = apps.get_model('catalog', 'Section')
    Promotion = apps.get_model('catalog', 'Promotion')
    resort, _ = Venue.objects.get_or_create(id='resort', defaults={
        'name': {'ru': 'Baytur Resort & Spa', 'ky': 'Baytur Resort & Spa', 'en': 'Baytur Resort & Spa'},
        'short': {'ru': 'Иссык-Куль', 'ky': 'Ысык-Көл', 'en': 'Issyk-Kul'}, 'app': 'resort', 'sort_order': 0})
    for model in (Outlet, Item, Section):
        model.objects.filter(venue_id='baytur').update(venue_id='resort')
    Promotion.objects.all().delete()
    Item.objects.filter(venue_id__in=RENAMED).delete()
    for _ in range(3):  # сначала подразделы, потом разделы
        Section.objects.filter(venue_id__in=RENAMED, children__isnull=True).delete()
    Outlet.objects.filter(venue_id__in=RENAMED).delete()
    Venue.objects.filter(id__in=RENAMED | {'baytur'}).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0006_promotion_showcase'),
    ]

    operations = [
        migrations.RunPython(to_modes, migrations.RunPython.noop),
    ]
