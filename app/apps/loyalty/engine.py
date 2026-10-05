"""
Балловая система (ТЗ «Новая балловая система BAYTUR», раздел 2).

Три счётчика клиента: «Доступные» (Wallet.balance, тратятся), «Нынешние» (Wallet.current, решают уровень,
обнуляются при повышении и в начале периода), «За всё время» (Wallet.lifetime). Счётчики меняются только
проводками журнала (post_operation) внутри транзакции с заблокированной строкой кошелька (lock_wallet),
поэтому начисления, закрытие периода и ручные действия сериализуются по клиенту.
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.common.errors import ApiError

from .models import (Achievement, AchievementScope, AchievementUsage, EntryRule, LimitSource, LoyaltySettings,
                     MemberAchievement, Operation, OperationKind, PeriodResult, PeriodResultKind, Retention, Tier,
                     TierChange, TierChangeCause, TierLimit, Wallet)

log = logging.getLogger(__name__)

COUNTERS = ('available', 'current', 'lifetime')


# ================================================================ периоды

def _tz(ls):
    try:
        return ZoneInfo(ls.timezone or 'Asia/Bishkek')
    except Exception:
        return ZoneInfo('Asia/Bishkek')


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # 29 февраля
        return dt.replace(year=dt.year + years, day=28)


def calendar_bounds(at, ls):
    """[1 января 00:00, следующее 1 января 00:00) в часовом поясе программы."""
    tz = _tz(ls)
    year = at.astimezone(tz).year
    return datetime(year, 1, 1, tzinfo=tz), datetime(year + 1, 1, 1, tzinfo=tz)


def initial_period(at, ls):
    if ls.period_type == LoyaltySettings.PeriodType.ANNIVERSARY:
        return at, add_years(at, 1)
    return calendar_bounds(at, ls)


def next_period(prev_end, ls):
    """Период после закрытого — по настройкам на момент закрытия (смена типа периода действует отсюда)."""
    if ls.period_type == LoyaltySettings.PeriodType.ANNIVERSARY:
        return prev_end, add_years(prev_end, 1)
    return calendar_bounds(prev_end, ls)


def period_key(start, ls=None):
    """«2027» для календарного года, иначе дата начала («2027-03-15»)."""
    if start is None:
        return ''
    local = start.astimezone(_tz(ls or LoyaltySettings.get()))
    if (local.month, local.day, local.hour, local.minute, local.second) == (1, 1, 0, 0, 0):
        return str(local.year)
    return local.date().isoformat()


def wallet_period_key(wallet, ls=None):
    return period_key(wallet.period_start, ls)


# ================================================================ лестница уровней

class Ladder:
    """Снимок активных уровней снизу вверх (order) — один на операцию, без лишних запросов."""

    def __init__(self, tiers=None):
        if tiers is None:
            tiers = Tier.objects.active().order_by('order', 'id').prefetch_related('tier_achievements__achievement')
        self.tiers = list(tiers)
        self.by_id = {t.pk: t for t in self.tiers}

    def get(self, tier_id):
        return self.by_id.get(tier_id)

    def resolve(self, tier):
        """Свежая копия уровня из снимка (у кошелька может быть устаревший объект)."""
        if tier is None:
            return None
        return self.by_id.get(tier.pk, tier)

    @property
    def base(self):
        return self.tiers[0] if self.tiers else None

    def is_base(self, tier):
        return tier is not None and self.base is not None and tier.order <= self.base.order

    def next(self, tier):
        if tier is None:
            return self.base
        return next((t for t in self.tiers if t.order > tier.order), None)

    def below(self, tier):
        lower = [t for t in self.tiers if t.order < tier.order]
        return lower[-1] if lower else None

    def floor(self, max_reached, depth):
        """
        Пол (§2.5): maxEternal — высший из достигнутых уровней с canBeFloor; пол — на depth ступеней ниже,
        но не ниже базового.
        """
        if not self.tiers:
            return None
        ref = max_reached.order if max_reached is not None else self.tiers[0].order
        eternal = [i for i, t in enumerate(self.tiers) if t.order <= ref and t.can_be_floor]
        if not eternal:
            return self.tiers[0]
        return self.tiers[max(0, eternal[-1] - depth)]

    def drop_target(self, tier, floor):
        """Куда падает уровень: dropTo (только нижестоящий) или на один ниже, но не ниже пола."""
        target = self.get(tier.drop_to_id) if tier.drop_to_id else None
        if target is None or target.order >= tier.order:
            target = self.below(tier) or tier
        if floor is not None and floor.order > target.order:
            target = floor
        return target


def ladder_floor(wallet, ladder, ls):
    return ladder.floor(ladder.resolve(wallet.max_reached), ls.floor_depth)


# ================================================================ кошелёк и журнал

def init_wallet(wallet, now=None, ls=None, ladder=None):
    """Заполняет уровень и период нового кошелька. Возвращает True, если что-то поменялось."""
    now = now or timezone.now()
    ls = ls or LoyaltySettings.get()
    changed = False
    if wallet.tier_id is None:
        ladder = ladder or Ladder()
        wallet.tier = ladder.base
        changed = True
    if wallet.max_reached_id is None and wallet.tier_id is not None:
        wallet.max_reached_id = wallet.tier_id
        changed = True
    if wallet.tier_since is None:
        wallet.tier_since = now
        changed = True
    if wallet.period_start is None:
        wallet.period_start, wallet.period_end = initial_period(now, ls)
        changed = True
    return changed


def post_operation(wallet, kind, points=0, *, d_current=0, d_lifetime=0, d_reserved=0, idempotency_key=None,
                   period_key_=None, request=None, item_id=None, category=None, title=None, reason='', related=None,
                   author=None, complaint=None, activity=True, at=None):
    """
    Проводка журнала: points — изменение «Доступных», d_* — остальных счётчиков. Кошелёк должен быть
    заблокирован (lock_wallet) в текущей транзакции. Повтор с тем же idempotency_key возвращает прежнюю проводку.
    """
    if idempotency_key:
        existing = Operation.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            existing.duplicate = True
            return existing
    at = at or timezone.now()
    balance = wallet.balance + points
    reserved = wallet.reserved + d_reserved
    current = wallet.current + d_current
    lifetime = wallet.lifetime + d_lifetime
    if balance < 0 or reserved < 0 or reserved > balance or current < 0 or lifetime < 0:
        raise ApiError('insufficient_points', 422)
    op = Operation.objects.create(
        member_id=wallet.member_id, kind=kind, points=points, d_current=d_current, d_lifetime=d_lifetime,
        d_reserved=d_reserved, idempotency_key=idempotency_key or None,
        period_key=period_key_ if period_key_ is not None else wallet_period_key(wallet),
        at=at, request=request, item_id=item_id, category=category, title=title, reason=reason, related=related,
        author=author, complaint=complaint)
    wallet.balance, wallet.reserved, wallet.current, wallet.lifetime = balance, reserved, current, lifetime
    if activity:
        wallet.last_activity_at = at
    wallet.save()
    op.duplicate = False
    return op


def _request_fields(request):
    if request is None:
        return {}
    snap = request.item_snapshot or {}
    return {'request': request, 'item_id': request.item_id, 'category': snap.get('category'),
            'title': snap.get('title')}


def change_reserved(wallet, delta, request=None, at=None):
    """Резерв под заявку (+) или его снятие (−) — служебная проводка reserve / release."""
    if not delta:
        return None
    if wallet.reserved + delta < 0:
        log.error('reserved would go negative for member %s', wallet.member_id)
        delta = -wallet.reserved
        if not delta:
            return None
    if wallet.reserved + delta > wallet.balance:
        raise ApiError('insufficient_points', 422)
    kind = OperationKind.RESERVE if delta > 0 else OperationKind.RELEASE
    return post_operation(wallet, kind, 0, d_reserved=delta, activity=False, at=at, **_request_fields(request))


def spend_reserved(wallet, points, request, at=None):
    """Подтверждение оплаты баллами: резерв снимается и «Доступные» уменьшаются одной проводкой (§2.2)."""
    return post_operation(wallet, OperationKind.SPEND, -points, d_reserved=-min(points, wallet.reserved), at=at,
                          **_request_fields(request))


def accrue(wallet, points, *, at=None, request=None, idempotency_key=None, ls=None, ladder=None):
    """
    Начисление кешбека (§2.1): +P во все три счётчика одной проводкой. Если период клиента истёк, а фоновое
    закрытие до него ещё не дошло, он закрывается первым — баллы попадают в период по времени начисления.
    Проверку повышения делает evaluate() (после сохранения заявки — задания считают начисленные заявки).
    """
    at = at or timezone.now()
    ensure_period(wallet, at, ls, ladder)
    return post_operation(wallet, OperationKind.CASHBACK, points, d_current=points, d_lifetime=points, at=at,
                          idempotency_key=idempotency_key, **_request_fields(request))


# ================================================================ задания

def _completed_ids(member_id, period_key_):
    """id выполненных заданий клиента: «за всё время» — когда угодно, «за период» — в этом периоде."""
    rows = MemberAchievement.objects.filter(member_id=member_id, completed_at__isnull=False) \
        .values_list('achievement_id', 'period_key', 'achievement__scope')
    return {aid for aid, key, scope in rows if (scope == AchievementScope.LIFETIME) or key == period_key_}


def tier_links(tier, usage):
    usages = (usage, AchievementUsage.BOTH)
    return [link for link in tier.tier_achievements.all()
            if link.usage in usages and link.achievement.deleted_at is None and link.achievement.active]


def achievement_counts(member_id, tier, usage, period_key_, completed=None):
    """(нужно, выполнено) по заданиям уровня. Для получения — по правилу all / any_n, для подтверждения — все."""
    links = tier_links(tier, usage)
    if not links:
        return 0, 0
    completed = completed if completed is not None else _completed_ids(member_id, period_key_)
    done = sum(1 for link in links if link.achievement_id in completed)
    need = len(links)
    if usage == AchievementUsage.ENTRY and tier.entry_rule == EntryRule.ANY_N and tier.entry_n:
        need = min(len(links), tier.entry_n)
    return need, done


def achievements_met(member_id, tier, usage, period_key_):
    need, done = achievement_counts(member_id, tier, usage, period_key_)
    return done >= need


def recompute_achievements(wallet, at=None, types=None, ls=None):
    """Пересчитывает прогресс по активным заданиям; возвращает задания, выполненные сейчас."""
    from .achievements import measure
    at = at or timezone.now()
    ls = ls or LoyaltySettings.get()
    key = wallet_period_key(wallet, ls)
    qs = Achievement.objects.active().exclude(type='manual')
    if types:
        qs = qs.filter(type__in=types)
    newly = []
    for ach in qs:
        row_key = '' if ach.scope == AchievementScope.LIFETIME else key
        row = MemberAchievement.objects.filter(member_id=wallet.member_id, achievement=ach, period_key=row_key).first()
        if row is not None and row.completed_at is not None:
            continue  # выполненное остаётся выполненным
        progress, target = measure(ach, wallet, at)
        if row is None:
            if progress <= 0 and target > 0:
                continue  # строки без прогресса не храним
            row = MemberAchievement(member_id=wallet.member_id, achievement=ach, period_key=row_key)
        row.progress, row.target = progress, target
        if progress >= target:
            row.completed_at = at
            newly.append(ach)
        row.save()
    for ach in newly:
        _on_commit_notify('notify_achievement_completed', wallet.member_id, ach.pk)
    return newly


def grant_achievement(member, achievement, actor=None, reason='', at=None):
    """Ручная выдача задания (manual или любое другое) + проверка повышения."""
    at = at or timezone.now()
    with transaction.atomic():
        wallet = lock_wallet(member)
        ensure_period(wallet, at)
        key = '' if achievement.scope == AchievementScope.LIFETIME else wallet_period_key(wallet)
        row, _ = MemberAchievement.objects.get_or_create(member=member, achievement=achievement, period_key=key)
        fresh = row.completed_at is None
        row.progress = max(row.progress, row.target or 1)
        row.target = row.target or 1
        row.completed_at = row.completed_at or at
        row.granted_by, row.reason = actor, reason or row.reason
        row.save()
        if fresh:
            _on_commit_notify('notify_achievement_completed', member.pk, achievement.pk)
        promote(wallet, at)
        _on_commit_publish(wallet)
    return row


def revoke_achievement(member, achievement, actor=None, reason=''):
    """Забрать задание. Уровень, уже полученный с ним, не снимается (понижение — только при закрытии периода)."""
    with transaction.atomic():
        wallet = lock_wallet(member)
        key = '' if achievement.scope == AchievementScope.LIFETIME else wallet_period_key(wallet)
        MemberAchievement.objects.filter(member=member, achievement=achievement, period_key=key) \
            .update(completed_at=None, progress=0, granted_by=actor, reason=reason)
    return True


# ================================================================ повышение (§2.3)

def _set_tier(wallet, tier, at, cause, reason='', actor=None):
    TierChange.objects.create(member_id=wallet.member_id, from_tier_id=wallet.tier_id, to_tier=tier, at=at,
                              cause=cause, reason=reason, actor=actor)
    wallet.tier = tier
    wallet.tier_since = at
    if wallet.max_reached is None or tier.order > wallet.max_reached.order:
        wallet.max_reached = tier


def promote(wallet, at=None, ls=None, ladder=None):
    """Повышает, пока «Нынешних» и заданий хватает на следующий уровень (с carryOver возможен прыжок)."""
    at = at or timezone.now()
    ls = ls or LoyaltySettings.get()
    ladder = ladder or Ladder()
    changes = []
    for _ in range(len(ladder.tiers) + 1):
        current_tier = ladder.resolve(wallet.tier)
        nxt = ladder.next(current_tier)
        if nxt is None or wallet.current < nxt.threshold:
            break
        if not achievements_met(wallet.member_id, nxt, AchievementUsage.ENTRY, wallet_period_key(wallet, ls)):
            break
        reset = min(nxt.threshold, wallet.current) if ls.carry_over else wallet.current
        if reset:
            post_operation(wallet, OperationKind.PROMOTION_RESET, 0, d_current=-reset, activity=False, at=at)
        _set_tier(wallet, nxt, at, TierChangeCause.PROMOTION)
        if ls.period_type == LoyaltySettings.PeriodType.ANNIVERSARY:
            wallet.period_start, wallet.period_end = at, add_years(at, 1)
            wallet.risk_warned = {}
        changes.append((current_tier, nxt))
    if changes:
        wallet.save()
        for old, new in changes:
            _on_commit_notify('notify_tier_upgraded', wallet.member_id, new.pk, old.pk if old else None)
    return changes


def evaluate(wallet, at=None, ls=None, ladder=None, types=None):
    """После начисления / корректировки «Нынешних» / ежедневно: задания, затем повышение."""
    at = at or timezone.now()
    ls = ls or LoyaltySettings.get()
    ladder = ladder or Ladder()
    ensure_period(wallet, at, ls, ladder)
    newly = recompute_achievements(wallet, at, types=types, ls=ls)
    return newly, promote(wallet, at, ls, ladder)


# ================================================================ закрытие периода (§2.4)

def current_limit(member_id, tier):
    row = TierLimit.objects.filter(member_id=member_id, tier=tier).first()
    return row.limit if row is not None else None


def decide_close(wallet, ls, ladder, limit_before=None, retention_done=None):
    """
    Решение по закрытию периода без записи (для закрытия и предпросмотра).
    → (result, checked, tier_end, limit_after)
    """
    tier = ladder.resolve(wallet.tier)
    floor = ladder_floor(wallet, ladder, ls)
    current = wallet.current
    checked = False
    if tier is None or ladder.is_base(tier):
        result = PeriodResultKind.NOT_REQUIRED
    elif floor is not None and tier.order <= floor.order:
        result = PeriodResultKind.FLOOR
    elif tier.retention == Retention.NONE:
        result = PeriodResultKind.NOT_REQUIRED
    elif wallet.tier_since and wallet.period_start and wallet.tier_since >= wallet.period_start:
        result = PeriodResultKind.PROMOTED_IN_PERIOD
    else:
        checked = True
        limit = limit_before if limit_before is not None else tier.min_limit
        if retention_done is None:
            retention_done = tier.retention != Retention.POINTS_AND_ACHIEVEMENTS or achievements_met(
                wallet.member_id, tier, AchievementUsage.RETENTION, wallet_period_key(wallet, ls))
        result = PeriodResultKind.RETAINED if current >= limit and retention_done else PeriodResultKind.DROPPED

    tier_end = ladder.drop_target(tier, floor) if result == PeriodResultKind.DROPPED else tier
    limit_after = limit_before
    if (result != PeriodResultKind.DROPPED and tier is not None and not ladder.is_base(tier)
            and tier.retention != Retention.NONE and result != PeriodResultKind.FLOOR):
        candidate = current + tier.limit_bonus
        if tier.limit_only_grows and limit_before is not None:
            candidate = max(limit_before, candidate)
        limit_after = max(candidate, tier.min_limit)
    return result, checked, tier_end, limit_after


def close_period(wallet, ls=None, ladder=None, now=None):
    """Закрывает текущий период кошелька (кошелёк заблокирован). Повтор для того же периода ничего не меняет."""
    now = now or timezone.now()
    ls = ls or LoyaltySettings.get()
    ladder = ladder or Ladder()
    start, end = wallet.period_start, wallet.period_end
    key = period_key(start, ls)
    existing = PeriodResult.objects.filter(member_id=wallet.member_id, period_key=key).first()
    if existing is None:
        tier = ladder.resolve(wallet.tier)
        limit_before = current_limit(wallet.member_id, tier) if tier else None
        result, checked, tier_end, limit_after = decide_close(wallet, ls, ladder, limit_before)
        current = wallet.current
        if tier is not None and limit_after is not None and limit_after != limit_before:
            TierLimit.objects.update_or_create(member_id=wallet.member_id, tier=tier,
                                               defaults={'limit': limit_after, 'source': LimitSource.PERIOD_CLOSE})
        if result == PeriodResultKind.DROPPED and tier_end.pk != tier.pk:
            _set_tier(wallet, tier_end, end, TierChangeCause.PERIOD_DROP,
                      reason=f'{key}: собрано {current} из {limit_before or 0}')
            _on_commit_notify('notify_tier_downgraded', wallet.member_id, tier_end.pk, tier.pk, key, current,
                              limit_before or 0)
        elif result == PeriodResultKind.RETAINED:
            _on_commit_notify('notify_tier_retained', wallet.member_id, tier.pk)
        existing = PeriodResult.objects.create(
            member_id=wallet.member_id, period_key=key, period_start=start, period_end=end,
            tier_start=tier or tier_end, tier_end=wallet.tier or tier_end, current=current,
            limit_before=limit_before, limit_after=limit_after if tier_end == tier else limit_before,
            checked=checked, result=result, settings_version=ls.version, closed_at=now)
        if current:
            post_operation(wallet, OperationKind.PERIOD_RESET, 0, d_current=-current, period_key_=key,
                           activity=False, at=now, idempotency_key=f'period_reset:{wallet.member_id}:{key}')
    wallet.period_start, wallet.period_end = next_period(end, ls)
    wallet.risk_warned = {}
    wallet.settings_version = ls.version
    wallet.save()
    return existing


def ensure_period(wallet, now=None, ls=None, ladder=None):
    """Закрывает все истёкшие периоды кошелька (за каждый пропущенный год — отдельное закрытие)."""
    now = now or timezone.now()
    if wallet.period_end is None:
        if init_wallet(wallet, now, ls, ladder):
            wallet.save()
        return []
    results = []
    ls = ls or LoyaltySettings.get()
    for _ in range(100):
        if wallet.period_end > now:
            break
        ladder = ladder or Ladder()
        results.append(close_period(wallet, ls, ladder, now))
    return results


# ================================================================ отмены и корректировки (§2.8)

def lock_wallet(member):
    """Только внутри transaction.atomic()."""
    from .services import get_wallet
    get_wallet(member)
    return Wallet.objects.select_for_update(of=('self',)).select_related('tier', 'max_reached').get(member=member)


def reverse_cashback(req, actor=None, reason=''):
    """
    Возврат начисления по заявке, отменённой после credited: сумма вычитается из трёх счётчиков (не ниже 0);
    «Нынешние» — только если начисление было в текущем периоде. Уровень автоматически не меняется.
    """
    with transaction.atomic():
        wallet = lock_wallet(req.member)
        now = timezone.now()
        ensure_period(wallet, now)
        orig = Operation.objects.filter(request=req, kind=OperationKind.CASHBACK).first()
        if orig is None:
            raise ApiError('invalid_status', 409, extra={'status': req.status})
        key = f'reversal:{orig.pk}'
        existing = Operation.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return existing
        d_available = -min(orig.points, wallet.balance - wallet.reserved)
        d_lifetime = -min(orig.d_lifetime, wallet.lifetime)
        d_current = -min(orig.d_current, wallet.current) if orig.period_key == wallet_period_key(wallet) else 0
        op = post_operation(wallet, OperationKind.REVERSAL, d_available, d_current=d_current, d_lifetime=d_lifetime,
                            related=orig, author=actor, reason=(reason or '').strip(), idempotency_key=key,
                            activity=False, at=now, **_request_fields(req))
    from .services import publish_wallet
    publish_wallet(req.member, wallet)
    return op


def adjust(member, amount, counters, reason, author=None, idempotency_key=None, complaint=None, related=None):
    """
    Ручная корректировка: знак и сумма, счётчики-галочки (available / current / lifetime), причина обязательна.
    Положительная корректировка «Нынешних» запускает проверку повышения.
    """
    counters = set(counters or ())
    if not reason or not str(reason).strip():
        raise ApiError('validation_error', 400, extra={'fields': {'comment': ['обязательно']}})
    if not amount:
        raise ApiError('validation_error', 400, extra={'fields': {'points': ['не может быть 0']}})
    if not counters or not counters <= set(COUNTERS):
        raise ApiError('validation_error', 400, extra={'fields': {'counters': [f'из {", ".join(COUNTERS)}']}})
    with transaction.atomic():
        wallet = lock_wallet(member)
        now = timezone.now()
        ensure_period(wallet, now)
        op = post_operation(
            wallet, OperationKind.ADJUSTMENT, amount if 'available' in counters else 0,
            d_current=amount if 'current' in counters else 0, d_lifetime=amount if 'lifetime' in counters else 0,
            reason=str(reason).strip(), author=author, complaint=complaint, related=related,
            idempotency_key=idempotency_key, activity=False, at=now)
        if not op.duplicate and amount > 0 and 'current' in counters:
            evaluate(wallet, now)
    from .services import publish_wallet
    publish_wallet(member, wallet)
    if not op.duplicate and 'available' in counters:
        _on_commit_notify('notify_points_adjusted', member.pk, amount)
    return op


def set_tier(member, tier, reason, actor=None, allow_below_floor=False):
    """Ручная смена уровня. Ниже пола — только с allowBelowFloor (право проверяет вызывающий)."""
    if not reason or not str(reason).strip():
        raise ApiError('validation_error', 400, extra={'fields': {'reason': ['обязательно']}})
    with transaction.atomic():
        wallet = lock_wallet(member)
        now = timezone.now()
        ensure_period(wallet, now)
        ladder, ls = Ladder(), LoyaltySettings.get()
        floor = ladder_floor(wallet, ladder, ls)
        if floor is not None and tier.order < floor.order and not allow_below_floor:
            raise ApiError('below_floor', 409, extra={'floor': floor.pk})
        old = wallet.tier
        if old is not None and old.pk == tier.pk:
            return wallet
        _set_tier(wallet, tier, now, TierChangeCause.ADMIN, reason=str(reason).strip(), actor=actor)
        wallet.save()
        if old is None or tier.order > old.order:
            _on_commit_notify('notify_tier_upgraded', member.pk, tier.pk, old.pk if old else None)
    from .services import publish_wallet
    publish_wallet(member, wallet)
    return wallet


def set_limit(member, tier, limit, reason, actor=None):
    if not reason or not str(reason).strip():
        raise ApiError('validation_error', 400, extra={'fields': {'reason': ['обязательно']}})
    if int(limit) < 0:
        raise ApiError('validation_error', 400, extra={'fields': {'limit': ['≥ 0']}})
    with transaction.atomic():
        lock_wallet(member)
        row, _ = TierLimit.objects.update_or_create(member=member, tier=tier,
                                                    defaults={'limit': int(limit), 'source': LimitSource.ADMIN})
    return row


# ================================================================ уведомления

def _on_commit_notify(name, *args):
    def run():
        from apps.notifications import services
        try:
            getattr(services, name)(*args)
        except Exception:
            log.exception('loyalty notification %s failed', name)
    transaction.on_commit(run)


def _on_commit_publish(wallet):
    """wallet.updated после фиксации транзакции (закрытие года, задания)."""
    def run():
        from .services import publish_wallet
        try:
            publish_wallet(wallet.member, Wallet.objects.get(pk=wallet.pk))
        except Exception:
            log.exception('wallet publish failed for member %s', wallet.member_id)
    transaction.on_commit(run)


# ================================================================ фоновые задачи (§3.4)

def close_due_periods(now=None, batch=500):
    """Закрытие периода у всех, чей период истёк. Каждый клиент — своя транзакция; повторный запуск безопасен."""
    from django.core.cache import cache
    now = now or timezone.now()
    ls = LoyaltySettings.get()
    ladder = Ladder()
    ids = list(Wallet.objects.filter(period_end__lte=now).values_list('member_id', flat=True))
    status = {'processed': 0, 'total': len(ids), 'errors': 0, 'startedAt': now.isoformat(), 'running': True}
    cache.set('loyalty:period_close', status, None)
    for i in range(0, len(ids), batch):
        for member_id in ids[i:i + batch]:
            try:
                with transaction.atomic():
                    wallet = Wallet.objects.select_for_update(of=('self',)).select_related('tier', 'max_reached') \
                        .get(member_id=member_id)
                    if ensure_period(wallet, now, ls, ladder):
                        _on_commit_publish(wallet)
            except Exception:
                log.exception('period close failed for member %s', member_id)
                status['errors'] += 1
            status['processed'] += 1
        cache.set('loyalty:period_close', status, None)
    status['running'] = False
    cache.set('loyalty:period_close', status, None)
    return status


def preview_period_close(now=None):
    """Предпросмотр закрытия текущего периода без записи: сколько удержат и потеряют уровень."""
    ls = LoyaltySettings.get()
    ladder = Ladder()
    limits = {(r.member_id, r.tier_id): r.limit for r in TierLimit.objects.all()}
    by_tier = {}
    retained = dropped = 0
    for wallet in Wallet.objects.select_related('tier', 'max_reached').filter(member__is_test=False).iterator():
        tier = ladder.resolve(wallet.tier)
        if tier is None:
            continue
        result, checked, tier_end, limit_after = decide_close(wallet, ls, ladder, limits.get((wallet.member_id,
                                                                                             tier.pk)))
        row = by_tier.setdefault(tier.pk, {'tierId': tier.pk, 'retained': 0, 'dropped': 0, '_limits': []})
        if result == PeriodResultKind.DROPPED:
            row['dropped'] += 1
            dropped += 1
        else:
            row['retained'] += 1
            retained += 1
        if limit_after is not None:
            row['_limits'].append(limit_after)
    for row in by_tier.values():
        lim = row.pop('_limits')
        row['newLimitsAvg'] = round(sum(lim) / len(lim)) if lim else None
    return {'retained': retained, 'dropped': dropped, 'byTier': list(by_tier.values())}


def recalc_promotions():
    """Проверка повышения для всех (после смены порогов). Никого не понижает."""
    ls, ladder = LoyaltySettings.get(), Ladder()
    upgraded = 0
    for member_id in Wallet.objects.values_list('member_id', flat=True):
        with transaction.atomic():
            wallet = Wallet.objects.select_for_update(of=('self',)).select_related('tier', 'max_reached').get(member_id=member_id)
            if promote(wallet, ls=ls, ladder=ladder):
                upgraded += 1
    return upgraded


def daily_achievements(now=None):
    """Задания, зависящие от даты (стаж, годы подряд), + проверка повышения."""
    now = now or timezone.now()
    ls, ladder = LoyaltySettings.get(), Ladder()
    types = ['member_years', 'consecutive_years']
    if not Achievement.objects.active().filter(type__in=types).exists():
        return 0
    completed = 0
    for member_id in Wallet.objects.values_list('member_id', flat=True):
        with transaction.atomic():
            wallet = Wallet.objects.select_for_update(of=('self',)).select_related('tier', 'max_reached').get(member_id=member_id)
            newly, _ = evaluate(wallet, now, ls, ladder, types=types)
            completed += len(newly)
    return completed


def warn_at_risk(now=None):
    """Push tier.at_risk за atRiskDays, 30 и 7 дней до конца периода тем, кто не добирает до лимита."""
    from .services import retention_state
    now = now or timezone.now()
    ls, ladder = LoyaltySettings.get(), Ladder()
    marks = sorted({ls.at_risk_days, 30, 7}, reverse=True)
    sent = 0
    qs = Wallet.objects.select_related('tier', 'max_reached').filter(
        period_end__gt=now, period_end__lte=now + timedelta(days=marks[0] + 1), member__is_test=False)
    for wallet in qs.iterator():
        state = retention_state(wallet, ls, ladder, now)
        if state['reason'] != 'check' or state['collected'] >= state['limit']:
            continue
        days_left = (wallet.period_end - now).days
        crossed = [d for d in marks if days_left <= d]
        key = wallet_period_key(wallet, ls)
        warned = (wallet.risk_warned or {}).get('days', []) if (wallet.risk_warned or {}).get('period') == key else []
        if not [d for d in crossed if d not in warned]:
            continue
        Wallet.objects.filter(pk=wallet.pk).update(risk_warned={'period': key, 'days': sorted(set(warned + crossed))})
        from apps.notifications.services import notify_tier_at_risk
        notify_tier_at_risk(wallet.member_id, wallet.tier_id, state['left'], days_left, state.get('dropTo'))
        sent += 1
    return sent
