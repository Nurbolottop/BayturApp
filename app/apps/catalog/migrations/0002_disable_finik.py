from django.db import migrations


def remove_finik(apps, schema_editor):
    """Finik отключён: убрать из способов оплаты разделов (старые заявки с method=finik не трогаем)."""
    Category = apps.get_model('catalog', 'Category')
    for category in Category.objects.all():
        if 'finik' in (category.methods or []):
            category.methods = [m for m in category.methods if m != 'finik']
            category.save(update_fields=['methods'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(remove_finik, migrations.RunPython.noop),
    ]
