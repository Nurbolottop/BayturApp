from django.db import migrations, models
import django.db.models.deletion

import apps.catalog.models


def create_default_venue(apps, schema_editor):
    """Всё, что было до объектов, — курорт на Иссык-Куле."""
    Venue = apps.get_model('catalog', 'Venue')
    Venue.objects.get_or_create(id='baytur', defaults={
        'name': {'ru': 'BAYTUR Иссык-Куль', 'ky': 'BAYTUR Ысык-Көл', 'en': 'BAYTUR Issyk-Kul'}, 'sort_order': 0})


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0002_disable_finik'),
    ]

    operations = [
        migrations.CreateModel(
            name='Venue',
            fields=[
                ('id', models.SlugField(max_length=40, primary_key=True, serialize=False)),
                ('name', models.JSONField(default=dict, verbose_name='Название')),
                ('short', models.JSONField(blank=True, default=dict, verbose_name='Подзаголовок')),
                ('description', models.JSONField(blank=True, default=dict, verbose_name='Описание')),
                ('address', models.JSONField(blank=True, default=dict, verbose_name='Адрес')),
                ('cover', models.CharField(blank=True, max_length=500, verbose_name='Обложка')),
                ('contacts', models.JSONField(blank=True, default=list, verbose_name='Контакты')),
                ('info', models.JSONField(blank=True, default=list, verbose_name='Инфоблоки')),
                ('sort_order', models.IntegerField(default=0)),
                ('is_active', models.BooleanField(default=True, verbose_name='Показывать')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Объект', 'verbose_name_plural': 'Объекты', 'ordering': ['sort_order', 'id']},
        ),
        migrations.RunPython(create_default_venue, migrations.RunPython.noop),
        migrations.AddField(
            model_name='outlet', name='venue',
            field=models.ForeignKey(default=apps.catalog.models.default_venue, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='outlets', to='catalog.venue', verbose_name='Объект'),
        ),
        migrations.CreateModel(
            name='Section',
            fields=[
                ('id', models.SlugField(max_length=60, primary_key=True, serialize=False)),
                ('title', models.JSONField(default=dict, verbose_name='Название')),
                ('note', models.JSONField(blank=True, default=dict, help_text='Мелким шрифтом под названием',
                                          verbose_name='Пояснение')),
                ('sort_order', models.IntegerField(default=0)),
                ('is_active', models.BooleanField(default=True, verbose_name='Показывать')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sections',
                                               to='catalog.category', verbose_name='Раздел программы (правила)')),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                             related_name='children', to='catalog.section',
                                             verbose_name='Внутри раздела')),
                ('venue', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sections',
                                            to='catalog.venue', verbose_name='Объект')),
            ],
            options={'verbose_name': 'Подраздел', 'verbose_name_plural': 'Подразделы',
                     'ordering': ['venue__sort_order', 'sort_order', 'id']},
        ),
        migrations.AddField(
            model_name='item', name='venue',
            field=models.ForeignKey(default=apps.catalog.models.default_venue, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='items', to='catalog.venue', verbose_name='Объект'),
        ),
        migrations.AddField(
            model_name='item', name='section',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='items', to='catalog.section', verbose_name='Подраздел'),
        ),
        migrations.AddField(
            model_name='item', name='price_note',
            field=models.JSONField(blank=True, default=dict,
                                   help_text='«за сутки», «500 сом в час», «от 10 000 до 22 000», «бесплатно»',
                                   verbose_name='Подпись к цене'),
        ),
        migrations.AddField(model_name='item', name='season_from',
                            field=models.DateField(blank=True, null=True, verbose_name='Доступна с')),
        migrations.AddField(model_name='item', name='season_to',
                            field=models.DateField(blank=True, null=True, verbose_name='Доступна по')),
    ]
