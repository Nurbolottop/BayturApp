from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('loyalty', '0005_balance_system_data'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tier',
            name='from_points',
        ),
    ]
