"""
Прогресс по заданиям (ТЗ лояльности §2.7). measure() → (progress, target); выполнено, когда progress ≥ target.
Считаются только начисленные заявки (credited), без отменённых начислений (reversal).
"""
from django.db.models import Sum
from django.utils import timezone

from .models import AchievementScope, AchievementType, OperationKind


def _int(params, key, default=0):
    try:
        return max(0, int(params.get(key, default) or 0))
    except (TypeError, ValueError):
        return default


def credited_requests(member_id, wallet=None, scope=AchievementScope.LIFETIME, category=None):
    from apps.cashback.models import CashbackRequest, RequestStatus
    qs = CashbackRequest.objects.filter(member_id=member_id, status=RequestStatus.CREDITED) \
        .exclude(operations__kind=OperationKind.REVERSAL)
    if scope == AchievementScope.PERIOD and wallet is not None and wallet.period_start:
        qs = qs.filter(credited_at__gte=wallet.period_start, credited_at__lt=wallet.period_end)
    if category:
        qs = qs.filter(item__category_id=category)
    return qs


def consecutive_years(member_id, min_per_year=1, today=None):
    """Подряд идущие календарные годы с ≥ min_per_year начислений; серия заканчивается в этом или прошлом году."""
    from django.db.models.functions import ExtractYear
    today = today or timezone.localdate()
    rows = credited_requests(member_id).annotate(y=ExtractYear('credited_at')).values_list('y', flat=True)
    counts = {}
    for y in rows:
        counts[y] = counts.get(y, 0) + 1
    years = {y for y, n in counts.items() if n >= max(1, min_per_year)}
    year = today.year if today.year in years else today.year - 1
    streak = 0
    while year in years:
        streak += 1
        year -= 1
    return streak


def full_years(since, today=None):
    today = today or timezone.localdate()
    years = today.year - since.year
    if (today.month, today.day) < (since.month, since.day):
        years -= 1
    return max(0, years)


def measure(ach, wallet, at=None):
    p = ach.params or {}
    t = ach.type
    scope = ach.scope
    today = timezone.localdate(at) if at else timezone.localdate()
    if t == AchievementType.CONSECUTIVE_YEARS:
        return consecutive_years(wallet.member_id, _int(p, 'minPerYear', 1), today), _int(p, 'years', 1) or 1
    if t == AchievementType.MEMBER_YEARS:
        from apps.members.models import Member
        since = Member.objects.filter(pk=wallet.member_id).values_list('member_since', flat=True).first()
        return (full_years(since, today) if since else 0), _int(p, 'years', 1) or 1
    if t == AchievementType.REQUESTS_COUNT:
        return credited_requests(wallet.member_id, wallet, scope, p.get('category')).count(), _int(p, 'count', 1) or 1
    if t == AchievementType.NIGHTS:
        qs = credited_requests(wallet.member_id, wallet, scope, p.get('category') or 'rooms')
        return qs.aggregate(s=Sum('quantity'))['s'] or 0, _int(p, 'nights', 1) or 1
    if t == AchievementType.SPEND_SOM:
        qs = credited_requests(wallet.member_id, wallet, scope, p.get('category'))
        return qs.aggregate(s=Sum('money_som'))['s'] or 0, _int(p, 'amount', 1) or 1
    if t == AchievementType.CATEGORIES_USED:
        wanted = [c for c in (p.get('categories') or []) if c]
        if not wanted:
            return 0, 1
        used = set(credited_requests(wallet.member_id, wallet, scope).filter(item__category_id__in=wanted)
                   .values_list('item__category_id', flat=True))
        return len(used), len(wanted)
    if t == AchievementType.LIFETIME_POINTS:
        return wallet.lifetime, _int(p, 'points', 1) or 1
    return 0, 1  # manual — только вручную


def describe(ach):
    """Условие человеческим языком (для админки): «5 лет подряд», «10 заявок за период»."""
    p = ach.params or {}
    period = ' за период' if ach.scope == AchievementScope.PERIOD else ''
    t = ach.type
    if t == AchievementType.CONSECUTIVE_YEARS:
        return f'{_int(p, "years", 1)} лет подряд, от {_int(p, "minPerYear", 1)} заявки в год'
    if t == AchievementType.MEMBER_YEARS:
        return f'В программе {_int(p, "years", 1)} лет'
    if t == AchievementType.REQUESTS_COUNT:
        cat = f' ({p["category"]})' if p.get('category') else ''
        return f'{_int(p, "count", 1)} заявок{cat}{period}'
    if t == AchievementType.NIGHTS:
        return f'{_int(p, "nights", 1)} ночей{period}'
    if t == AchievementType.SPEND_SOM:
        return f'Потратить {_int(p, "amount", 1):,} сом{period}'.replace(',', ' ')
    if t == AchievementType.CATEGORIES_USED:
        return 'Категории: ' + ', '.join(p.get('categories') or [])
    if t == AchievementType.LIFETIME_POINTS:
        return f'Накопить {_int(p, "points", 1):,} баллов за всё время'.replace(',', ' ')
    return 'Отмечает администратор'
