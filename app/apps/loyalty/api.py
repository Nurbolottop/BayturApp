from rest_framework.response import Response

from apps.common.caching import cached_public
from apps.common.i18n import iso, tr
from apps.common.media import absolute_media_url
from apps.common.pagination import paginate
from apps.common.views import MemberAPIView, PublicAPIView

from .achievements import measure
from .engine import wallet_period_key
from .models import (SERVICE_KINDS, Achievement, AchievementScope, LoyaltySettings, MemberAchievement, PeriodResult,
                     Privilege, Tier, TierChange)
from .services import cumulative_from, get_wallet, refresh_wallet, wallet_payload


def tier_cashback_rate(tier, base):
    """Ставка кешбека уровня: база × (1 + надбавка / 100) — доля (0.0625 = 6,25 %)."""
    from decimal import Decimal
    return (Decimal(base) * (1 + Decimal(tier.cashback_bonus) / 100)).quantize(Decimal('0.0001'))


def percent_text(rate):
    """0.0625 → «6,25»; 0.05 → «5»."""
    value = f'{float(rate) * 100:.2f}'.rstrip('0').rstrip('.')
    return value.replace('.', ',')


def tier_program_payload(t, cumulative, base_rate):
    gradient = t.gradient
    rate = tier_cashback_rate(t, base_rate)
    return {
        'id': t.id,
        'order': t.order,
        'name': tr(t.name),
        'threshold': t.threshold,
        'cashbackBonus': float(t.cashback_bonus),
        'cashbackRate': float(rate),
        'permanent': ({'lifetime': t.permanent_lifetime, 'years': t.permanent_years}
                      if t.permanent_lifetime is not None else None),
        'canBeFloor': t.permanent_lifetime is not None,
        'retention': t.retention,
        'entryRule': {'mode': t.entry_rule, 'n': t.entry_n if t.entry_rule == 'any_n' else None},
        'style': {'gradient': gradient, 'glow': t.glow_color,
                  'medalUrl': absolute_media_url(t.medal) if t.medal else None, 'icon': t.icon or None},
        'achievements': [{'id': link.achievement_id, 'usage': link.usage}
                         for link in t.tier_achievements.all()
                         if link.achievement.deleted_at is None and link.achievement.active
                         and link.achievement.visible],
        # совместимость со старыми версиями: накопленная сумма порогов, плоские цвета и медаль
        'from': cumulative[t.id],
        'colors': gradient,
        'medal': absolute_media_url(t.medal) if t.medal else None,
    }


def build_program():
    from apps.common.models import ProgramSettings
    tiers = list(Tier.objects.active().order_by('order', 'id').prefetch_related('tier_achievements__achievement'))
    cumulative = cumulative_from(tiers)
    ls = LoyaltySettings.get()
    ps = ProgramSettings.get()
    rates = {t.pk: percent_text(tier_cashback_rate(t, ps.base_cashback_rate)) for t in tiers}

    from apps.catalog.models import Venue
    mode_names = {v.pk: tr(v.name) for v in Venue.objects.all()}

    def mode_title(modes):  # единая программа; ограничение по режимам — подпись «Только …» (ТЗ экосистемы §6.9)
        names = [mode_names.get(m) for m in modes or [] if mode_names.get(m)]
        return ('Только ' + ', '.join(names)) if names else None

    def text(value, tier_id):
        return (tr(value) or '').replace('{rate}', rates.get(tier_id, '')) or None

    return {
        'tiers': [tier_program_payload(t, cumulative, ps.base_cashback_rate) for t in tiers],
        'privileges': [{
            'id': p.id, 'tier': p.tier_id, 'group': p.group or None,
            # без названия группы — название привилегии (у таких групп оно одинаково на всех уровнях)
            'groupTitle': (text(p.group_title, p.tier_id) or text(p.title, p.tier_id)) if p.group else None, 'icon': p.icon, 'title': text(p.title, p.tier_id),
            'short': text(p.short, p.tier_id), 'description': text(p.description, p.tier_id),
            'footnote': text(p.footnote, p.tier_id),
            'modes': p.modes or [], 'modeTitle': mode_title(p.modes),
        } for p in Privilege.objects.select_related('tier').filter(tier__deleted_at__isnull=True)],
        'achievements': [{
            'id': a.id, 'title': tr(a.title), 'description': tr(a.description) or None, 'icon': a.icon or None,
            'scope': a.scope, 'modes': a.modes or [], 'modeTitle': mode_title(a.modes),
        } for a in Achievement.objects.active().filter(visible=True)],
        'settings': {'periodType': ls.period_type, 'floorDepth': ls.floor_depth,
                     'baseCashbackRate': float(ps.base_cashback_rate), 'pointsPerSom': ps.points_per_som},
    }


class ProgramView(PublicAPIView):
    def get(self, request):
        return cached_public('program', build_program, request)


def operation_payload(op):
    return {
        'id': op.id,
        'kind': op.kind,
        'points': op.points,
        'at': iso(op.at),
        'itemId': op.item_id,
        'category': op.category,
        'requestId': op.request_id,
        'title': tr(op.title) if op.title else None,
        'reason': op.reason or None,
        'relatedId': op.related_id,
    }


def client_operations(member):
    """Только движения «Доступных»: служебные проводки (резерв, сбросы «Нынешних») клиенту не показываются."""
    return member.operations.exclude(kind__in=SERVICE_KINDS).exclude(points=0)


class WalletView(MemberAPIView):
    def get(self, request):
        return Response(wallet_payload(request.user, refresh_wallet(request.user)))


class OperationsView(MemberAPIView):
    def get(self, request):
        return Response(paginate(request, client_operations(request.user),
                                 lambda rows: [operation_payload(o) for o in rows], time_field='at'))


class SummaryView(MemberAPIView):
    def get(self, request):
        wallet = get_wallet(request.user)
        return Response({'available': wallet.available, 'current': wallet.current, 'lifetime': wallet.lifetime,
                         'requestsCount': request.user.cashback_requests.count()})


class AchievementsView(MemberAPIView):
    """Прогресс клиента по видимым заданиям: сохранённое выполнение или текущий прогресс."""

    def get(self, request):
        wallet = get_wallet(request.user)
        key = wallet_period_key(wallet)
        rows = {(r.achievement_id, r.period_key): r for r in MemberAchievement.objects.filter(member=request.user)}
        items = []
        for ach in Achievement.objects.active().filter(visible=True):
            row_key = '' if ach.scope == AchievementScope.LIFETIME else key
            row = rows.get((ach.id, row_key))
            if row is not None and row.completed_at is not None:
                progress, target, completed = max(row.progress, row.target), row.target, row.completed_at
            else:
                progress, target = measure(ach, wallet) if ach.type != 'manual' else (0, 1)
                completed = None
            items.append({'id': ach.id, 'progress': min(progress, target), 'target': target,
                          'completedAt': iso(completed), 'periodKey': row_key or None})
        return Response({'items': items})


class LoyaltyHistoryView(MemberAPIView):
    """Экран «Баллы за всё время»: итоги по периодам и история уровней."""

    def get(self, request):
        m = request.user
        wallet = get_wallet(m)
        periods = [{'key': r.period_key, 'tierStart': r.tier_start_id, 'tierEnd': r.tier_end_id,
                    'collected': r.current, 'limit': r.limit_before, 'result': r.result}
                   for r in PeriodResult.objects.filter(member=m).order_by('-period_start')]
        changes = [{'from': c.from_tier_id, 'to': c.to_tier_id, 'at': iso(c.at), 'cause': c.cause}
                   for c in TierChange.objects.filter(member=m).order_by('-at', '-id')]
        return Response({'lifetime': wallet.lifetime, 'memberSince': m.member_since.isoformat(),
                         'periods': periods, 'tierChanges': changes})
