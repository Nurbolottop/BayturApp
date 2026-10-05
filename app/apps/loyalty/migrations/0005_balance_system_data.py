"""Перенос данных на новую балловую систему (ТЗ лояльности §3.5)."""
from django.db import migrations, models


# ---------------------------------------------------------------- перенос данных (ТЗ лояльности §3.5)
# Идемпотентно: повторный запуск ничего не меняет. Никого не понижаем; «Нынешние» = 0; tierSince = дата запуска
# (в первый год проверки удержания нет); лимитов нет до ближайшего закрытия года; на каждого клиента —
# проводка adjustment (reason=migration), чтобы журнал сошёлся со счётчиками, и запись истории уровней.

KNOWN_THRESHOLDS = {'bronze': 0, 'silver': 200_000, 'gold': 300_000, 'platinum': 900_000,
                    'titanium': 2_000_000, 'diamond': 2_000_000, 'ambassador': 3_000_000}
NOT_FLOOR = {'titanium', 'diamond', 'ambassador'}
TITANIUM_NAME = {'ru': 'Титан', 'ky': 'Титан', 'en': 'Titanium'}
AMBASSADOR_NAME = {'ru': 'Амбассадор', 'ky': 'Амбассадор', 'en': 'Ambassador'}


def migrate_to_balance_system(apps, schema_editor):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from django.db.models import Max, Sum
    from django.utils import timezone

    Tier = apps.get_model('loyalty', 'Tier')
    Wallet = apps.get_model('loyalty', 'Wallet')
    Operation = apps.get_model('loyalty', 'Operation')
    Privilege = apps.get_model('loyalty', 'Privilege')
    TierChange = apps.get_model('loyalty', 'TierChange')
    LoyaltySettings = apps.get_model('loyalty', 'LoyaltySettings')
    Campaign = apps.get_model('notifications', 'Campaign')
    LoyaltySettings.objects.get_or_create(pk=1)

    # 1. Порядок и пороги: порядок — по старым порогам lifetime; новый порог — «Нынешних» за год
    tiers = list(Tier.objects.order_by('from_points', 'id'))
    prev = 0
    for i, t in enumerate(tiers):
        t.order = i
        t.threshold = KNOWN_THRESHOLDS.get(t.id, max(1, t.from_points - prev) if i else 0)
        if i == 0:
            t.threshold = 0
        t.can_be_floor = t.id not in NOT_FLOOR
        t.retention = 'none' if i == 0 else ('points_and_achievements' if t.id in NOT_FLOOR else 'points')
        prev = t.from_points
        t.save()

    # 2. diamond → titanium (мобилка больше не подменяет id)
    diamond = Tier.objects.filter(pk='diamond').first()
    if diamond is not None and not Tier.objects.filter(pk='titanium').exists():
        name = diamond.name if (diamond.name or {}).get('ru') not in ('Бриллиант', '', None) else TITANIUM_NAME
        Tier.objects.create(
            id='titanium', order=diamond.order, name=name, threshold=diamond.threshold,
            from_points=diamond.from_points, colors=diamond.colors, medal=diamond.medal, can_be_floor=False,
            retention='points_and_achievements')
        Privilege.objects.filter(tier_id='diamond').update(tier_id='titanium')
        Wallet.objects.filter(tier_id='diamond').update(tier_id='titanium')
        for c in Campaign.objects.all():
            tiers_seg = (c.segment or {}).get('tiers') or []
            if 'diamond' in tiers_seg:
                c.segment = {**c.segment, 'tiers': ['titanium' if x == 'diamond' else x for x in tiers_seg]}
                c.save(update_fields=['segment'])
        diamond.delete()

    # 3. Амбассадор — новый верхний уровень (порог задаёт курорт в админке)
    if Tier.objects.exists() and not Tier.objects.filter(pk='ambassador').exists():  # только на рабочей базе
        top = Tier.objects.aggregate(m=Max('order'))['m'] or 0
        top_from = Tier.objects.aggregate(m=Max('from_points'))['m'] or 0
        Tier.objects.create(id='ambassador', order=top + 1, name=AMBASSADOR_NAME, threshold=3_000_000,
                            from_points=top_from + 1, colors=['#1A1A1A', '#4A4A4A', '#D4AF37'], can_be_floor=False,
                            retention='points_and_achievements')

    # 4. Журнал: «За всё время» прежних начислений
    Operation.objects.filter(affects_lifetime=True, points__gt=0, d_lifetime=0).update(d_lifetime=models.F('points'))

    # 5. Состояние клиентов
    base = Tier.objects.order_by('order').first()
    now = timezone.now()
    tz = ZoneInfo('Asia/Bishkek')
    year = now.astimezone(tz).year
    start, end = datetime(year, 1, 1, tzinfo=tz), datetime(year + 1, 1, 1, tzinfo=tz)
    sums = {r['member_id']: r for r in Operation.objects.values('member_id').annotate(
        a=Sum('points'), c=Sum('d_current'), l=Sum('d_lifetime'), r=Sum('d_reserved'))}
    for w in Wallet.objects.all():
        if w.tier_since is not None:
            continue
        w.tier_id = w.tier_id or (base.pk if base else None)
        w.max_reached_id = w.tier_id
        w.tier_since = now
        w.current = 0
        w.period_start, w.period_end = start, end
        w.save()
        s = sums.get(w.member_id) or {}
        diff = (w.balance - (s.get('a') or 0), w.current - (s.get('c') or 0), w.lifetime - (s.get('l') or 0),
                w.reserved - (s.get('r') or 0))
        key = f'migration:{w.member_id}'
        if any(diff) and not Operation.objects.filter(idempotency_key=key).exists():
            Operation.objects.create(member_id=w.member_id, kind='adjustment', points=diff[0], d_current=diff[1],
                                     d_lifetime=diff[2], d_reserved=diff[3], reason='migration',
                                     idempotency_key=key, at=now, period_key=str(year),
                                     affects_lifetime=bool(diff[2]))
        if w.tier_id and not TierChange.objects.filter(member_id=w.member_id).exists():
            TierChange.objects.create(member_id=w.member_id, from_tier_id=None, to_tier_id=w.tier_id, at=now,
                                      cause='migration', reason='Переход на новую балловую систему')



class Migration(migrations.Migration):

    dependencies = [
        ('loyalty', '0004_balance_system'),
        ('notifications', '0003_alter_pushtemplate_kind'),
    ]

    operations = [
        migrations.RunPython(migrate_to_balance_system, migrations.RunPython.noop),
    ]
