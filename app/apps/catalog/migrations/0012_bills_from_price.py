"""
Решение заказчика (письмо мобильщиков 13.10): кафе и бар Тоо-Ашуу и кымыз в Суусамыре оплачиваются в приложении
«Счётом» — сумма по чеку, кассир подтверждает. «От» у проживания — только по номерам (без доп. мест, детей,
завтраков). Отдельно от изменений схемы (Postgres: pending trigger events).
"""
from django.db import migrations

L = lambda ru, ky, en: {'ru': ru, 'ky': ky, 'en': en}  # noqa: E731

BILLS = [  # id, раздел, точка
    ('ski-cafe-bill', 'ski-cafe', 'ski-cafe', L('Счёт кафе', 'Кафенин эсеби', 'Café bill')),
    ('ski-bar-bill', 'ski-bar', 'ski-bar', L('Счёт бара', 'Бардын эсеби', 'Bar bill')),
    ('kymyz-kymyz-bill', 'kymyz-kymyz', 'kymyz-kymyz', L('Счёт', 'Эсеп', 'Bill')),
]
NOT_FROM = ('extra-bed', 'kids', 'breakfast', 'adults-kids')


def forward(apps, schema_editor):
    Item = apps.get_model('catalog', 'Item')
    Section = apps.get_model('catalog', 'Section')
    Outlet = apps.get_model('catalog', 'Outlet')
    for item_id, section_id, outlet_id, title in BILLS:
        section = Section.objects.filter(pk=section_id).first()
        if section is None or Item.objects.filter(pk=item_id).exists():
            continue
        Item.objects.create(
            id=item_id, venue_id=section.venue_id, section=section, category_id=section.category_id,
            outlet_id=outlet_id if Outlet.objects.filter(pk=outlet_id).exists() else None, title=title,
            meta=L('Сумма по чеку', 'Чек боюнча сумма', 'Amount from the receipt'),
            price=0, price_on_request=True, pricing={'type': 'check', 'min': 100, 'max': 200000},
            price_note=L('введите сумму по чеку', 'чектеги сумманы жазыңыз', 'enter the receipt amount'),
            unit='none', action='pay_cashier', sort_order=-100, in_from_price=False)
    for item in Item.objects.filter(section__kind='stay'):
        if any(part in item.id for part in NOT_FROM) or item.unit != 'night':
            item.in_from_price = False
            item.save(update_fields=['in_from_price'])


class Migration(migrations.Migration):
    dependencies = [('catalog', '0011_live_from_price')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
