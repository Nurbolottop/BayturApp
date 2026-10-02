"""
Кошелёк и журнал баллов. Все движения — в транзакции с блокировкой кошелька
(select_for_update): balance и reserved не уходят в минус, reserved ≤ balance.
"""
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.errors import ApiError
from apps.common.models import ProgramSettings

from .models import Operation, OperationKind, Tier, Wallet

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- уровни

def tiers_ordered():
    return list(Tier.objects.order_by('from_points'))


def tier_for(lifetime, tiers=None):
    """Уровень = последний tier с from ≤ lifetime."""
    tiers = tiers if tiers is not None else tiers_ordered()
    current = None
    for t in tiers:
        if t.from_points <= lifetime:
            current = t
    return current or (tiers[0] if tiers else None)


def tier_progress(lifetime, tiers=None):
    tiers = tiers if tiers is not None else tiers_ordered()
    current = tier_for(lifetime, tiers)
    if current is None:
        return None, None, 0, 1.0
    idx = tiers.index(current)
    nxt = tiers[idx + 1] if idx + 1 < len(tiers) else None
    if nxt is None:
        return current, None, 0, 1.0
    left = max(0, nxt.from_points - lifetime)
    span = nxt.from_points - current.from_points
    progress = (lifetime - current.from_points) / span if span else 1.0
    return current, nxt, left, round(max(0.0, min(1.0, progress)), 4)


# ---------------------------------------------------------------- кошелёк

def get_wallet(member):
    wallet, _ = Wallet.objects.get_or_create(member=member, defaults={'tier': tier_for(0)})
    return wallet


def lock_wallet(member):
    """Только внутри transaction.atomic()."""
    get_wallet(member)
    return Wallet.objects.select_for_update().get(member=member)


def expires_at(wallet):
    """Дата сгорания: 12 мес. без реального действия (если есть что сжигать)."""
    if wallet.balance <= 0 or not wallet.last_activity_at:
        return None
    months = ProgramSettings.get().expiry_months
    return _add_months(wallet.last_activity_at, months)


def _add_months(dt, months):
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    import calendar
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def pending_cashback(member):
    from apps.cashback.models import ACTIVE_STATUSES
    from django.db.models import Sum
    return member.cashback_requests.filter(status__in=ACTIVE_STATUSES).aggregate(s=Sum('cashback'))['s'] or 0


def wallet_payload(member, wallet=None):
    from apps.common.i18n import iso, tr
    wallet = wallet or get_wallet(member)
    tiers = tiers_ordered()
    current, nxt, left, progress = tier_progress(wallet.lifetime, tiers)
    exp = expires_at(wallet)
    return {
        'balance': wallet.balance,
        'reserved': wallet.reserved,
        'available': wallet.available,
        'lifetime': wallet.lifetime,
        'tier': current.id if current else None,
        'pendingCashback': pending_cashback(member),
        'nextTier': nxt.id if nxt else None,
        'leftToNext': left,
        'progress': progress,
        'expiresAt': iso(exp) if exp else None,
    }


def publish_wallet(member, wallet=None):
    from apps.common.realtime import publish_member
    publish_member(member.pk, 'wallet.updated', wallet_payload(member, wallet))


def _touch_activity(wallet, at=None):
    wallet.last_activity_at = at or timezone.now()
    wallet.expiry_warned = []


def post_operation(wallet, kind, points, *, request=None, item_id=None, category=None, title=None, reason='',
                   related=None, author=None, complaint=None, affects_lifetime=False, activity=True, at=None):
    """
    Пишет операцию в журнал и меняет баланс заблокированного кошелька.
    wallet должен быть получен через lock_wallet() в текущей транзакции.
    """
    at = at or timezone.now()
    new_balance = wallet.balance + points
    if new_balance < 0 or new_balance < wallet.reserved:
        raise ApiError('insufficient_points', 422)
    op = Operation.objects.create(
        member_id=wallet.member_id, kind=kind, points=points, at=at, request=request, item_id=item_id,
        category=category, title=title, reason=reason, related=related, author=author, complaint=complaint,
        affects_lifetime=affects_lifetime,
    )
    wallet.balance = new_balance
    old_tier_id = wallet.tier_id
    if affects_lifetime and points > 0:
        wallet.lifetime += points
        new_tier = tier_for(wallet.lifetime)
        # уровень не понижается никогда
        if new_tier and (wallet.tier is None or new_tier.from_points > wallet.tier.from_points):
            wallet.tier = new_tier
    if activity:
        _touch_activity(wallet, at)
    wallet.save()
    if wallet.tier_id != old_tier_id and old_tier_id is not None:
        from apps.notifications.services import notify_tier_upgraded
        transaction.on_commit(lambda: notify_tier_upgraded(wallet.member_id, wallet.tier_id))
    return op


def change_reserved(wallet, delta):
    new_reserved = wallet.reserved + delta
    if new_reserved < 0:
        log.error('reserved would go negative for member %s', wallet.member_id)
        new_reserved = 0
    if new_reserved > wallet.balance:
        raise ApiError('insufficient_points', 422)
    wallet.reserved = new_reserved
    wallet.save(update_fields=['reserved', 'updated_at'])


# ---------------------------------------------------------------- ручные корректировки (админка)

def manual_adjustment(member, points, reason, author, complaint=None, related=None):
    if not reason or not reason.strip():
        raise ApiError('validation_error', 400, extra={'fields': {'comment': ['обязательно']}})
    if points == 0:
        raise ApiError('validation_error', 400, extra={'fields': {'points': ['не может быть 0']}})
    with transaction.atomic():
        wallet = lock_wallet(member)
        op = post_operation(wallet, OperationKind.ADJUSTMENT, points, reason=reason.strip(), author=author,
                            complaint=complaint, related=related, activity=False)
    publish_wallet(member, wallet)
    from apps.notifications.services import notify_points_adjusted
    transaction.on_commit(lambda: notify_points_adjusted(member.pk, points))
    return op


# ---------------------------------------------------------------- пересчёт уровней после смены порогов

def preview_tier_change(new_thresholds):
    """new_thresholds: {tier_id: from}. Сколько клиентов сменит уровень (только вверх — вниз не понижаем)."""
    from django.db.models import Count
    tiers = sorted(tiers_ordered(), key=lambda t: new_thresholds.get(t.id, t.from_points))
    for t in tiers:
        t.from_points = new_thresholds.get(t.id, t.from_points)
    changes = {}
    for w in Wallet.objects.select_related('tier').only('lifetime', 'tier').iterator():
        new = tier_for(w.lifetime, tiers)
        if new and new.id != w.tier_id and (w.tier is None or new.from_points > _order(w.tier_id, tiers)):
            key = f'{w.tier_id}->{new.id}'
            changes[key] = changes.get(key, 0) + 1
    return {'total': sum(changes.values()), 'changes': changes}


def _order(tier_id, tiers):
    for t in tiers:
        if t.id == tier_id:
            return t.from_points
    return -1


def recalc_all_tiers():
    """После смены порогов: поднять уровень тем, кто теперь выше. Уровень не понижается."""
    tiers = tiers_ordered()
    rank = {t.id: i for i, t in enumerate(tiers)}
    upgraded = 0
    for w in Wallet.objects.all().iterator():
        new = tier_for(w.lifetime, tiers)
        if new and (w.tier_id is None or rank[new.id] > rank.get(w.tier_id, -1)):
            Wallet.objects.filter(pk=w.pk).update(tier=new)
            upgraded += 1
    return upgraded


# ---------------------------------------------------------------- сгорание баллов

def expire_inactive_wallets(now=None):
    """Весь баланс сгорает операцией expire после N мес. без реального действия. Уровень не меняется."""
    now = now or timezone.now()
    months = ProgramSettings.get().expiry_months
    count = 0
    candidates = Wallet.objects.filter(balance__gt=0, last_activity_at__isnull=False,
                                       member__is_test=False)
    for w in candidates.iterator():
        if _add_months(w.last_activity_at, months) > now:
            continue
        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(pk=w.pk)
            burn = wallet.balance - wallet.reserved
            if burn <= 0 or _add_months(wallet.last_activity_at, months) > now:
                continue
            post_operation(wallet, OperationKind.EXPIRE, -burn, activity=False,
                           reason=f'{months} мес. без активности')
        publish_wallet(wallet.member, wallet)
        from apps.notifications.services import notify_points_expired
        transaction.on_commit(lambda m=wallet.member_id, p=burn: notify_points_expired(m, p))
        count += 1
    return count


def warn_expiring_points(now=None):
    """Push за 30 и за 7 дней до сгорания (однократно на каждый порог)."""
    now = now or timezone.now()
    ps = ProgramSettings.get()
    warn_days = sorted(ps.expiry_warn_days or [30, 7], reverse=True)
    sent = 0
    from apps.notifications.services import notify_points_expiring
    for w in Wallet.objects.filter(balance__gt=0, last_activity_at__isnull=False, member__is_test=False).iterator():
        exp = _add_months(w.last_activity_at, ps.expiry_months)
        days_left = (exp - now).days
        if days_left < 0:
            continue
        crossed = [d for d in warn_days if days_left <= d]
        fresh = [d for d in crossed if d not in (w.expiry_warned or [])]
        if not fresh:
            continue
        # пересекли сразу несколько порогов — одно предупреждение, все пороги отмечены
        Wallet.objects.filter(pk=w.pk).update(expiry_warned=sorted(set((w.expiry_warned or []) + crossed)))
        notify_points_expiring(w.member_id, w.balance, days_left)
        sent += 1
    return sent


def ledger_mismatches():
    """Сверка: balance == Σ operations.points для каждого кошелька."""
    from django.db.models import Sum
    bad = []
    sums = dict(Operation.objects.values_list('member_id').annotate(s=Sum('points')))
    for w in Wallet.objects.all():
        if w.balance != sums.get(w.member_id, 0):
            bad.append((w.member_id, w.balance, sums.get(w.member_id, 0)))
    return bad


def since(days):
    return timezone.now() - timedelta(days=days)


# ---------------------------------------------------------------- управление набором уровней

HEX = re.compile(r'^#[0-9A-Fa-f]{6}$')


def thresholds_valid(values):
    """Пороги по порядку уровней: первый — 0, дальше строго возрастают."""
    return bool(values) and values[0] == 0 and all(b > a for a, b in zip(values, values[1:]))


def clean_colors(colors):
    if not isinstance(colors, (list, tuple)) or len(colors) != 3 or not all(HEX.match(str(c)) for c in colors):
        raise ApiError('validation_error', 400, extra={'fields': {'colors': ['три цвета #RRGGBB']}})
    return [c.upper() for c in colors]


def create_tier(name, from_points, colors, medal='', tier_id=None):
    """Новый уровень: порог не совпадает с существующими и > 0; клиентов, дотянувших до порога, повышаем."""
    from apps.common.text import slug_from_title
    from_points = int(from_points)
    existing = sorted(Tier.objects.values_list('from_points', flat=True))
    if not thresholds_valid(sorted(existing + [from_points])) or (existing and from_points == 0):
        raise ApiError('tiers_invalid', 422)
    with transaction.atomic():
        tier = Tier.objects.create(
            id=tier_id or slug_from_title((name or {}).get('ru'), Tier, max_length=30, fallback='tier'),
            name=name, from_points=from_points, colors=clean_colors(colors), medal=medal or '')
        upgraded = recalc_all_tiers()
    return tier, upgraded


def delete_tier_preview(tier):
    """Куда перейдут клиенты удаляемого уровня: на ближайший уровень ниже (уровень по их lifetime)."""
    others = [t for t in tiers_ordered() if t.pk != tier.pk]
    affected = Wallet.objects.filter(tier=tier).count()
    lower = [t for t in others if t.from_points <= tier.from_points]
    return {'members': affected, 'fallback': lower[-1] if lower else None, 'privileges': tier.privileges.count(),
            'others': others}


def delete_tier(tier, privileges_to=None):
    """
    Удаление уровня. Нижний уровень (порог 0) удалить нельзя — у каждого клиента должен быть уровень.
    Привилегии переносятся на privileges_to (Tier) или удаляются. Клиенты удалённого уровня получают уровень
    по своему lifetime среди оставшихся. Из сегментов рассылок уровень убирается.
    """
    from apps.notifications.models import Campaign
    if tier.from_points == 0:
        raise ApiError('tiers_invalid', 422, message='Нижний уровень (порог 0) удалить нельзя')
    if privileges_to is not None and privileges_to.pk == tier.pk:
        raise ApiError('validation_error', 400, extra={'fields': {'privilegesTo': ['другой уровень']}})
    with transaction.atomic():
        moved = deleted = 0
        if privileges_to is not None:
            moved = tier.privileges.update(tier=privileges_to)
        else:
            deleted = tier.privileges.count()
            tier.privileges.all().delete()
        remaining = [t for t in tiers_ordered() if t.pk != tier.pk]
        reassigned = 0
        for w in Wallet.objects.select_for_update().filter(tier=tier):
            w.tier = tier_for(w.lifetime, remaining)
            w.save(update_fields=['tier', 'updated_at'])
            reassigned += 1
        for c in Campaign.objects.filter(segment__tiers__contains=[tier.pk]):
            seg = dict(c.segment)
            seg['tiers'] = [t for t in seg.get('tiers', []) if t != tier.pk]
            c.segment = seg
            c.save(update_fields=['segment'])
        tier.delete()
    return {'reassigned': reassigned, 'privilegesMoved': moved, 'privilegesDeleted': deleted}


def tier_styles():
    """{id: {name, colors, medal, from}} всех уровней — для отрисовки медалей и градиентов (кеш до изменения)."""
    from django.core.cache import cache

    from apps.common.caching import content_version
    from apps.common.media import absolute_media_url
    key = f'tier_styles:{content_version()}'
    data = cache.get(key)
    if data is None:
        data = {t.pk: {'name': t.name, 'colors': t.gradient, 'medal': absolute_media_url(t.medal) if t.medal else None,
                       'from': t.from_points} for t in tiers_ordered()}
        cache.set(key, data, 3600)
    return data
