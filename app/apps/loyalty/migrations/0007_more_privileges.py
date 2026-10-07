"""11 новых привилегий (Wi‑Fi, кофе, фитнес, велосипеды, завтрак, йога, детский клуб, прачечная, ночной бассейн,
экскурсия, фотосессия). Создаются только отсутствующие и только для существующих уровней — правки из админки не трогаем."""
from django.db import migrations
from django.db.models import Max

NEW_IDS = ['wifi', 'coffee', 'gym', 'bike', 'breakfast', 'yoga', 'kids', 'laundry', 'night-pool', 'excursion', 'photo']


def forward(apps, schema_editor):
    from apps.common.seed_data import PRIVILEGES
    Tier = apps.get_model('loyalty', 'Tier')
    Privilege = apps.get_model('loyalty', 'Privilege')
    if not Tier.objects.exists():
        return  # пустая база — привилегии создаст сид
    order = (Privilege.objects.aggregate(m=Max('sort_order'))['m'] or 0) + 1
    for pid, tier, icon, title, short, desc in PRIVILEGES:
        if pid not in NEW_IDS or Privilege.objects.filter(pk=pid).exists():
            continue
        if not Tier.objects.filter(pk=tier, deleted_at__isnull=True).exists():
            continue
        Privilege.objects.create(id=pid, tier_id=tier, icon=icon, title=title, short=short, description=desc,
                                 sort_order=order)
        order += 1


class Migration(migrations.Migration):

    dependencies = [
        ('loyalty', '0006_remove_tier_from_points'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
