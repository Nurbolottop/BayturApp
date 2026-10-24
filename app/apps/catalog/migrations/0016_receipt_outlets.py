from django.db import migrations


def mark_food_outlets(apps, schema_editor):
    """Как приложение кассира без поля receiptRequired: точки с услугами раздела «Еда» — по фискальному чеку."""
    Outlet = apps.get_model('catalog', 'Outlet')
    Outlet.objects.filter(items__category_id='food').distinct().update(receipt_required=True)


class Migration(migrations.Migration):
    dependencies = [('catalog', '0015_outlet_receipt_threshold')]

    operations = [migrations.RunPython(mark_food_outlets, migrations.RunPython.noop)]
