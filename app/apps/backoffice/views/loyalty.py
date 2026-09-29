"""
Уровни и привилегии (ТЗ §7.2). Количество уровней фиксировано мобилкой — меняются только названия и пороги.
Пороги строго возрастают, у первого — 0 (tiers_invalid). Смена порога → пересчёт уровней (только вверх).
"""
from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response

from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.common.serializers import L10nField
from apps.loyalty.models import Privilege, Tier
from apps.loyalty.services import preview_tier_change, recalc_all_tiers

from ..base import AdminAPIView, CollectionView, DetailView, SortView, body, field_error, forbidden, not_found
from ..serializers import TIER_ORDER, PrivilegeSerializer, TierSerializer

TIERS_READ = ['tiers.texts', 'tiers.edit']


def ordered_tiers():
    rank = {t: i for i, t in enumerate(TIER_ORDER)}
    return sorted(Tier.objects.all(), key=lambda t: rank.get(t.id, 99))


def validate_thresholds(changes):
    """changes: {tier_id: from}. Проверяет итоговый набор порогов в порядке уровней мобилки."""
    current = {t.id: t.from_points for t in ordered_tiers()}
    unknown = [k for k in changes if k not in current]
    if unknown:
        raise field_error('tiers', f'неизвестные уровни: {", ".join(unknown)}')
    merged = {**current, **changes}
    values = [merged[t] for t in TIER_ORDER if t in merged]
    if not values or values[0] != 0 or any(b <= a for a, b in zip(values, values[1:])):
        raise ApiError('tiers_invalid', 422, extra={'thresholds': {t: merged[t] for t in TIER_ORDER if t in merged}})
    return {k: v for k, v in changes.items() if current[k] != v}


class TierInput(serializers.Serializer):
    id = serializers.CharField()
    name = L10nField(required=False)
    # «from» — ключевое слово Python, поле добавляется ниже

    def get_fields(self):
        fields = super().get_fields()
        fields['from'] = serializers.IntegerField(min_value=0, required=False)
        return fields


def parse_tier_input(data):
    """{tiers: [{id, name?, from?}]} | {thresholds: {id: from}} → [{id, name?, from?}]."""
    if isinstance(data.get('thresholds'), dict):
        rows = [{'id': k, 'from': v} for k, v in data['thresholds'].items()]
    elif isinstance(data.get('tiers'), list):
        rows = data['tiers']
    else:
        raise field_error('tiers', 'ожидается список [{id, name, from}]')
    s = TierInput(data=rows, many=True, context={'full_l10n': True})
    s.is_valid(raise_exception=True)
    return s.validated_data


def tiers_payload(ctx):
    return TierSerializer(ordered_tiers(), many=True, context=ctx).data


def apply_tier_changes(request, rows):
    user = request.user
    thresholds = {r['id']: r['from'] for r in rows if 'from' in r}
    names = {r['id']: r['name'] for r in rows if 'name' in r}
    changed = validate_thresholds(thresholds)
    if changed and not user.can('tiers.edit'):
        raise forbidden(['from'])
    if names and not user.can('tiers.texts'):
        raise forbidden(['name'])
    tiers = {t.id: t for t in Tier.objects.all()}
    for tid in names:
        if tid not in tiers:
            raise field_error('tiers', f'неизвестный уровень: {tid}')
    before = {t.id: {'name': t.name, 'from': t.from_points} for t in tiers.values()}
    upgraded = 0
    with transaction.atomic():
        for tid, value in changed.items():
            tiers[tid].from_points = value
        for tid, name in names.items():
            tiers[tid].name = name
        for tid in set(changed) | set(names):
            tiers[tid].save()
        if changed:
            upgraded = recalc_all_tiers()
        after = {t.id: {'name': t.name, 'from': t.from_points} for t in tiers.values()}
        audit(request, 'tiers.update', None, object_type='loyalty.tier', before=before, after=after,
              comment=f'upgraded={upgraded}' if changed else '')
    return upgraded


class TiersView(AdminAPIView):
    """GET — уровни по порядку; PUT/PATCH {tiers: [{id, name?, from?}]} — правка набора целиком."""

    required_perms = {'GET': TIERS_READ, 'PUT': TIERS_READ, 'PATCH': TIERS_READ}

    def get(self, request):
        return Response({'items': tiers_payload(self.ctx())})

    def patch(self, request):
        upgraded = apply_tier_changes(request, parse_tier_input(body(request)))
        return Response({'items': tiers_payload(self.ctx()), 'upgraded': upgraded})

    put = patch


class TierDetailView(AdminAPIView):
    required_perms = {'GET': TIERS_READ, 'PATCH': TIERS_READ, 'PUT': TIERS_READ}

    def get_object(self, pk):
        tier = Tier.objects.filter(pk=pk).first()
        if tier is None:
            raise not_found()
        return tier

    def get(self, request, pk):
        return Response(TierSerializer(self.get_object(pk), context=self.ctx()).data)

    def patch(self, request, pk):
        tier = self.get_object(pk)
        rows = parse_tier_input({'tiers': [{**body(request), 'id': tier.id}]})
        upgraded = apply_tier_changes(request, rows)
        tier.refresh_from_db()
        return Response({**TierSerializer(tier, context=self.ctx()).data, 'upgraded': upgraded})

    put = patch


class TiersPreviewView(AdminAPIView):
    """POST {tiers: [{id, from}]} | {thresholds: {id: from}} → сколько клиентов сменит уровень (без сохранения)."""

    required_perms = 'tiers.edit'

    def post(self, request):
        rows = parse_tier_input(body(request))
        thresholds = {r['id']: r['from'] for r in rows if 'from' in r}
        validate_thresholds(thresholds)
        return Response(preview_tier_change(thresholds))


# ---------------------------------------------------------------- привилегии

class PrivilegesView(CollectionView):
    """GET ?tier="""

    model = Privilege
    serializer_class = PrivilegeSerializer
    audit_name = 'privilege'
    required_perms = {'GET': TIERS_READ, 'POST': 'tiers.edit'}

    def filter_queryset(self, qs):
        tier = self.request.query_params.get('tier')
        return qs.filter(tier_id=tier) if tier else qs


class PrivilegeDetailView(DetailView):
    model = Privilege
    serializer_class = PrivilegeSerializer
    audit_name = 'privilege'
    required_perms = {'GET': TIERS_READ, 'PATCH': TIERS_READ, 'PUT': TIERS_READ, 'DELETE': 'tiers.edit'}
    full_perm = 'tiers.edit'
    texts_perm = 'tiers.texts'


class PrivilegesSortView(SortView):
    model = Privilege
    audit_name = 'privilege'
    required_perms = 'tiers.edit'
