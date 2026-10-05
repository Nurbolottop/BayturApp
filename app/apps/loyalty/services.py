"""
Кошелёк клиента и ответы API. Правила балловой системы — в engine.py, здесь — чтение состояния,
ответ GET /wallet (ТЗ лояльности §4.1), управление набором уровней и совместимые обёртки.
"""
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.errors import ApiError

from . import engine
from .engine import (Ladder, accrue, change_reserved, ladder_floor, lock_wallet, post_operation,  # noqa: F401
                     spend_reserved, wallet_period_key)
from .models import (AchievementUsage, LoyaltySettings, Operation, Retention, Tier, TierChange, TierChangeCause,
                     TierLimit, Wallet)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- уровни

def tiers_ordered():
    """Все не удалённые уровни снизу вверх (для админки)."""
    return list(Tier.objects.live().order_by('order', 'id'))


def cumulative_from(tiers):
    """Совместимость: старое поле from = накопленная сумма порогов."""
    total, out = 0, {}
    for t in tiers:
        total += t.threshold
        out[t.pk] = total
    return out


# ---------------------------------------------------------------- кошелёк

def get_wallet(member):
    wallet, created = Wallet.objects.get_or_create(member=member)
    if wallet.tier_id is None or wallet.period_start is None or wallet.tier_since is None:
        if engine.init_wallet(wallet):
            wallet.save()
    return wallet


def pending_cashback(member):
    from django.db.models import Sum

    from apps.cashback.models import ACTIVE_STATUSES
    return member.cashback_requests.filter(status__in=ACTIVE_STATUSES).aggregate(s=Sum('cashback'))['s'] or 0


def _ratio(value, total):
    return round(min(1.0, value / total), 4) if total else 1.0


def _iso_end(end):
    from apps.common.i18n import iso
    return iso(end - timedelta(seconds=1)) if end else None


def retention_state(wallet, ls=None, ladder=None, now=None):
    """
    Блок удержания текущего уровня. reason: check — в конце периода проверка; floor — уровень вечный;
    new_this_period — получен в этом периоде; not_required — уровень без подтверждения.
    """
    ls = ls or LoyaltySettings.get()
    ladder = ladder or Ladder()
    now = now or timezone.now()
    tier = ladder.resolve(wallet.tier)
    floor = ladder_floor(wallet, ladder, ls)
    if tier is None or ladder.is_base(tier) or tier.retention == Retention.NONE:
        reason = 'not_required'
    elif floor is not None and tier.order <= floor.order:
        reason = 'floor'
    elif wallet.tier_since and wallet.period_start and wallet.tier_since >= wallet.period_start:
        reason = 'new_this_period'
    else:
        reason = 'check'
    state = {'required': reason == 'check', 'reason': reason, 'periodEnd': _iso_end(wallet.period_end)}
    if reason != 'check':
        return state
    limit = engine.current_limit(wallet.member_id, tier)
    limit = limit if limit is not None else tier.min_limit
    need, done = engine.achievement_counts(wallet.member_id, tier, AchievementUsage.RETENTION,
                                           wallet_period_key(wallet, ls))
    days_left = (wallet.period_end - now).days if wallet.period_end else None
    collected = wallet.current
    state.update({
        'limit': limit,
        'collected': collected,
        'left': max(0, limit - collected),
        'progress': _ratio(collected, limit),
        'atRisk': days_left is not None and days_left < ls.at_risk_days and (
            collected < limit or done < need),
        'dropTo': ladder.drop_target(tier, floor).pk,
        'achievements': {'required': need, 'done': min(done, need)},
    })
    return state


def tier_state(wallet, ls=None, ladder=None, now=None):
    from apps.common.i18n import iso
    ls = ls or LoyaltySettings.get()
    ladder = ladder or Ladder()
    tier = ladder.resolve(wallet.tier)
    if tier is None:
        return None
    floor = ladder_floor(wallet, ladder, ls)
    nxt = ladder.next(tier)
    next_state = None
    if nxt is not None:
        need, done = engine.achievement_counts(wallet.member_id, nxt, AchievementUsage.ENTRY,
                                               wallet_period_key(wallet, ls))
        next_state = {
            'id': nxt.pk,
            'threshold': nxt.threshold,
            'left': max(0, nxt.threshold - wallet.current),
            'progress': _ratio(wallet.current, nxt.threshold),
            'achievements': {'required': need, 'done': min(done, need)},
        }
    return {
        'id': tier.pk,
        'since': iso(wallet.tier_since),
        'floor': floor.pk if floor else None,
        'isFloor': floor is not None and tier.order <= floor.order,
        'maxReached': wallet.max_reached_id or tier.pk,
        'next': next_state,
        'retention': retention_state(wallet, ls, ladder, now),
    }


def wallet_payload(member, wallet=None):
    from apps.common.i18n import iso
    wallet = wallet or get_wallet(member)
    ls = LoyaltySettings.get()
    ladder = Ladder()
    tier = tier_state(wallet, ls, ladder)
    nxt = (tier or {}).get('next')
    return {
        'available': wallet.available,
        'reserved': wallet.reserved,
        'current': wallet.current,
        'lifetime': wallet.lifetime,
        'pendingCashback': pending_cashback(member),
        'tier': tier,
        'period': {'key': wallet_period_key(wallet, ls), 'start': iso(wallet.period_start),
                   'end': _iso_end(wallet.period_end)},
        # совместимость со старыми версиями приложения (до minVersion с новой системой)
        'balance': wallet.balance,
        'nextTier': nxt['id'] if nxt else None,
        'leftToNext': nxt['left'] if nxt else 0,
        'progress': nxt['progress'] if nxt else 1.0,
    }


def refresh_wallet(member):
    """Перед показом: если период истёк, а фоновое закрытие ещё не дошло до клиента — закрыть сейчас."""
    wallet = get_wallet(member)
    if wallet.period_end and wallet.period_end <= timezone.now():
        with transaction.atomic():
            wallet = lock_wallet(member)
            engine.ensure_period(wallet)
    return wallet


def publish_wallet(member, wallet=None):
    from apps.common.realtime import publish_member
    publish_member(member.pk, 'wallet.updated', wallet_payload(member, wallet))


# ---------------------------------------------------------------- ручные корректировки (админка)

def manual_adjustment(member, points, reason, author, complaint=None, related=None, counters=('available',),
                      idempotency_key=None):
    """Корректировка: по умолчанию только «Доступные» (как компенсации по обращениям)."""
    return engine.adjust(member, points, counters, reason, author=author, idempotency_key=idempotency_key,
                         complaint=complaint, related=related)


# ---------------------------------------------------------------- пересчёт повышений после смены порогов

def preview_tier_change(new_thresholds):
    """
    new_thresholds: {tier_id: threshold}. Сколько клиентов повысится при «Пересчитать сейчас» (вниз не понижаем).
    Задания не учитываются — это оценка.
    """
    ladder = Ladder()
    for t in ladder.tiers:
        if t.pk in new_thresholds:
            t.threshold = int(new_thresholds[t.pk])
    changes = {}
    for w in Wallet.objects.select_related('tier').only('current', 'tier').iterator():
        tier = ladder.resolve(w.tier)
        nxt = ladder.next(tier)
        if nxt is not None and w.current >= nxt.threshold:
            key = f'{w.tier_id}->{nxt.pk}'
            changes[key] = changes.get(key, 0) + 1
    return {'total': sum(changes.values()), 'changes': changes}


def recalc_all_tiers():
    """Проверка повышения для всех клиентов. Уровень не понижается."""
    return engine.recalc_promotions()


# ---------------------------------------------------------------- сверка журнала (§3.3)

def ledger_mismatches():
    """Каждый счётчик кошелька равен сумме своей колонки в журнале; 0 ≤ reserved ≤ balance; пол ≤ уровень ≤ max."""
    from django.db.models import Sum
    sums = {r['member_id']: r for r in Operation.objects.values('member_id').annotate(
        a=Sum('points'), c=Sum('d_current'), l=Sum('d_lifetime'), r=Sum('d_reserved'))}
    bad = []
    for w in Wallet.objects.all():
        s = sums.get(w.member_id) or {}
        expected = (s.get('a') or 0, s.get('c') or 0, s.get('l') or 0, s.get('r') or 0)
        actual = (w.balance, w.current, w.lifetime, w.reserved)
        if expected != actual:
            bad.append((w.member_id, actual, expected))
    return bad


def invariant_violations():
    """Нарушения порядка уровней: пол ≤ уровень ≤ наивысший достигнутый."""
    ls, ladder = LoyaltySettings.get(), Ladder()
    bad = []
    for w in Wallet.objects.select_related('tier', 'max_reached'):
        if w.tier is None:
            continue
        floor = ladder_floor(w, ladder, ls)
        if (floor and w.tier.order < floor.order) or (w.max_reached and w.tier.order > w.max_reached.order):
            bad.append((w.member_id, w.tier_id, floor.pk if floor else None, w.max_reached_id))
    return bad


def reconcile():
    """Ночная сверка: расхождения — в лог (алерт), автоматически ничего не исправляем."""
    from apps.common.audit import audit_system
    mismatches = ledger_mismatches()
    violations = invariant_violations()
    if mismatches or violations:
        log.error('loyalty reconcile: %s ledger mismatches, %s tier violations', len(mismatches), len(violations))
        audit_system('loyalty.reconcile', after={'ledger': [list(map(str, m)) for m in mismatches[:100]],
                                                 'tiers': [list(map(str, v)) for v in violations[:100]]})
    return {'ledger': mismatches, 'tiers': violations}


# ---------------------------------------------------------------- управление набором уровней

HEX = re.compile(r'^#[0-9A-Fa-f]{6}$')


def clean_colors(colors):
    if not isinstance(colors, (list, tuple)) or len(colors) != 3 or not all(HEX.match(str(c)) for c in colors):
        raise ApiError('validation_error', 400, extra={'fields': {'colors': ['три цвета #RRGGBB']}})
    return [c.upper() for c in colors]


def create_tier(name, threshold, colors, medal='', tier_id=None, **fields):
    """Новый уровень — наверх лестницы. Порог > 0; повышение по нему — при следующем начислении (§2.9)."""
    from django.db.models import Max

    from apps.common.text import slug_from_title
    threshold = int(threshold or 0)
    if threshold <= 0:
        raise ApiError('validation_error', 400, extra={'fields': {'threshold': ['целое > 0']}})
    top = Tier.objects.live().aggregate(m=Max('order'))['m']
    tier = Tier.objects.create(
        id=tier_id or slug_from_title((name or {}).get('ru'), Tier, max_length=30, fallback='tier'),
        order=(top + 1) if top is not None else 0, name=name, threshold=threshold, colors=clean_colors(colors),
        medal=medal or '', **fields)
    return tier, 0


def delete_tier_preview(tier):
    others = [t for t in tiers_ordered() if t.pk != tier.pk]
    affected = Wallet.objects.filter(tier=tier).count()
    lower = [t for t in others if t.order < tier.order]
    return {'members': affected, 'fallback': lower[-1] if lower else None, 'privileges': tier.privileges.count(),
            'others': others}


def delete_tier(tier, privileges_to=None, move_clients_to=None, actor=None):
    """
    Мягкое удаление уровня. Базовый уровень удалить нельзя. Клиенты переводятся на move_clients_to
    (по умолчанию — ближайший уровень ниже), привилегии переносятся на privileges_to или удаляются,
    уровень убирается из сегментов рассылок.
    """
    from apps.notifications.models import Campaign
    base = Ladder().base
    if base is not None and tier.pk == base.pk:
        raise ApiError('base_tier_protected', 422)
    if privileges_to is not None and privileges_to.pk == tier.pk:
        raise ApiError('validation_error', 400, extra={'fields': {'privilegesTo': ['другой уровень']}})
    if move_clients_to is not None and move_clients_to.pk == tier.pk:
        raise ApiError('validation_error', 400, extra={'fields': {'moveClientsTo': ['другой уровень']}})
    target = move_clients_to or delete_tier_preview(tier)['fallback'] or base
    now = timezone.now()
    with transaction.atomic():
        moved = deleted = 0
        if privileges_to is not None:
            moved = tier.privileges.update(tier=privileges_to)
        else:
            deleted = tier.privileges.count()
            tier.privileges.all().delete()
        reassigned = 0
        for w in Wallet.objects.select_for_update().filter(tier=tier):
            TierChange.objects.create(member_id=w.member_id, from_tier=tier, to_tier=target, at=now,
                                      cause=TierChangeCause.ADMIN, reason=f'Уровень «{tier}» удалён', actor=actor)
            w.tier, w.tier_since = target, now
            w.save(update_fields=['tier', 'tier_since', 'updated_at'])
            reassigned += 1
        Wallet.objects.filter(max_reached=tier).update(max_reached=target)
        for c in Campaign.objects.filter(segment__tiers__contains=[tier.pk]):
            seg = dict(c.segment)
            seg['tiers'] = [t for t in seg.get('tiers', []) if t != tier.pk]
            c.segment = seg
            c.save(update_fields=['segment'])
        Tier.objects.filter(drop_to=tier).update(drop_to=None)
        tier.deleted_at, tier.active = now, False
        tier.save(update_fields=['deleted_at', 'active'])
    return {'reassigned': reassigned, 'privilegesMoved': moved, 'privilegesDeleted': deleted,
            'movedTo': target.pk if target else None}


def tier_styles():
    """{id: {name, colors, medal, threshold}} всех уровней — для медалей и градиентов (кеш до изменения)."""
    from django.core.cache import cache

    from apps.common.caching import content_version
    from apps.common.media import absolute_media_url
    key = f'tier_styles:{content_version()}'
    data = cache.get(key)
    if data is None:
        data = {t.pk: {'name': t.name, 'colors': t.gradient, 'medal': absolute_media_url(t.medal) if t.medal else None,
                       'threshold': t.threshold} for t in Tier.objects.order_by('order', 'id')}
        cache.set(key, data, 3600)
    return data


def member_limits(member):
    return {r.tier_id: r.limit for r in TierLimit.objects.filter(member=member)}
