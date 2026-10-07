"""
ТЗ лояльности 08.10.2026:
- надбавка к кешбеку по уровням 0 / 10 / 25 / 50 / 75 / 100 %;
- постоянный статус: баллы за всё время + лет в программе (Серебро 50 000 + 1 год … Амбассадор 250 000 + 5 лет);
- привилегии заменены списком «Апгрейдер» (21 шт.).
"""
from django.db import migrations

BONUS = {'bronze': 0, 'silver': 10, 'gold': 25, 'platinum': 50, 'titanium': 75, 'ambassador': 100}
PERMANENT = {'silver': (50_000, 1), 'gold': (100_000, 2), 'platinum': (175_000, 3), 'titanium': (200_000, 4),
             'ambassador': (250_000, 5)}


def forward(apps, schema_editor):
    from apps.common.seed_data import PRIVILEGES
    Tier = apps.get_model('loyalty', 'Tier')
    Privilege = apps.get_model('loyalty', 'Privilege')
    if not Tier.objects.exists():
        return  # пустая база — всё создаст сид
    for tier_id, bonus in BONUS.items():
        lifetime, years = PERMANENT.get(tier_id, (None, 0))
        Tier.objects.filter(pk=tier_id).update(cashback_bonus=bonus, permanent_lifetime=lifetime,
                                               permanent_years=years)
    Privilege.objects.all().delete()
    live = set(Tier.objects.filter(deleted_at__isnull=True).values_list('pk', flat=True))
    for i, p in enumerate(PRIVILEGES):
        if p['tier'] in live:
            Privilege.objects.create(id=p['id'], tier_id=p['tier'], group=p['group'], icon=p['icon'], title=p['title'],
                                     short=p['short'], description=p['description'], footnote=p['footnote'],
                                     sort_order=i)


class Migration(migrations.Migration):

    dependencies = [
        ('loyalty', '0009_tier_cashback_permanent'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
