"""
Уровни и привилегии. Уровни можно добавлять, удалять и оформлять (градиент, медаль).
Порог (threshold, прежнее имя from) — «Нынешних» за год на предыдущем уровне: у базового 0, у остальных > 0
(tiers_invalid). Смена порога → проверка повышения для всех (никого не понижаем).
"""
from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response

from apps.common.audit import audit, model_snapshot
from apps.common.errors import ApiError
from apps.common.serializers import L10nField
from apps.loyalty.models import Privilege, Tier
from apps.loyalty.services import create_tier, delete_tier, preview_tier_change, recalc_all_tiers

from ..base import AdminAPIView, CollectionView, DetailView, SortView, body, field_error, forbidden, not_found
from ..serializers import PrivilegeSerializer, TierSerializer

TIERS_READ = ['tiers.texts', 'tiers.edit']


def ordered_tiers():
    return list(Tier.objects.live().order_by('order'))


def validate_thresholds(changes):
    """changes: {tier_id: threshold}. У базового уровня — 0, у остальных > 0."""
    current = {t.id: t.threshold for t in ordered_tiers()}
    unknown = [k for k in changes if k not in current]
    if unknown:
        raise field_error('tiers', f'неизвестные уровни: {", ".join(unknown)}')
    merged = {**current, **changes}
    order = [t.id for t in ordered_tiers()]
    values = [merged[t] for t in order]
    if not values or values[0] != 0 or any(v <= 0 for v in values[1:]):
        raise ApiError('tiers_invalid', 422, extra={'thresholds': {t: merged[t] for t in order}})
    return {k: v for k, v in changes.items() if current[k] != v}


class TierInput(serializers.Serializer):
    id = serializers.CharField()
    name = L10nField(required=False)
    # «from» — ключевое слово Python, поле добавляется ниже

    def get_fields(self):
        fields = super().get_fields()
        fields['from'] = serializers.IntegerField(min_value=0, required=False)
        fields['threshold'] = serializers.IntegerField(min_value=0, required=False)
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
    rows = [dict(r) for r in s.validated_data]
    for r in rows:
        if 'threshold' in r:
            r['from'] = r.pop('threshold')
    return rows


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
    tiers = {t.id: t for t in Tier.objects.live()}
    for tid in names:
        if tid not in tiers:
            raise field_error('tiers', f'неизвестный уровень: {tid}')
    before = {t.id: {'name': t.name, 'threshold': t.threshold} for t in tiers.values()}
    upgraded = 0
    with transaction.atomic():
        for tid, value in changed.items():
            tiers[tid].threshold = value
        for tid, name in names.items():
            tiers[tid].name = name
        for tid in set(changed) | set(names):
            tiers[tid].save()
        if changed:
            upgraded = recalc_all_tiers()
        after = {t.id: {'name': t.name, 'threshold': t.threshold} for t in tiers.values()}
        audit(request, 'tiers.update', None, object_type='loyalty.tier', before=before, after=after,
              comment=f'upgraded={upgraded}' if changed else '')
    return upgraded


class TiersView(AdminAPIView):
    """GET — уровни по порядку; PUT/PATCH {tiers: [{id, name?, from?}]} — правка набора целиком."""

    required_perms = {'GET': TIERS_READ, 'PUT': TIERS_READ, 'PATCH': TIERS_READ, 'POST': 'tiers.edit'}

    def get(self, request):
        return Response({'items': tiers_payload(self.ctx())})

    def patch(self, request):
        upgraded = apply_tier_changes(request, parse_tier_input(body(request)))
        return Response({'items': tiers_payload(self.ctx()), 'upgraded': upgraded})

    put = patch

    def post(self, request):
        """Новый уровень наверх лестницы: {name: {ru,ky,en}, threshold (>0), colors: [3 × #RRGGBB], medal?}."""
        if not request.user.can('tiers.edit'):
            raise forbidden(['tier'])
        data = body(request)
        threshold = data.get('threshold', data.get('from')) or 0
        s = TierSerializer(data={**data, 'threshold': threshold}, context=self.ctx())
        s.is_valid(raise_exception=True)
        v = s.validated_data
        if not v.get('colors'):
            raise field_error('colors', 'три цвета #RRGGBB')
        tier, upgraded = create_tier(v['name'], threshold, v['colors'], v.get('medal') or '', data.get('id'))
        audit(request, 'tier.create', tier, after=model_snapshot(tier))
        return Response({**TierSerializer(tier, context=self.ctx()).data, 'upgraded': upgraded}, status=201)


class TierDetailView(AdminAPIView):
    required_perms = {'GET': TIERS_READ, 'PATCH': TIERS_READ, 'PUT': TIERS_READ, 'DELETE': 'tiers.edit'}

    def get_object(self, pk):
        tier = Tier.objects.live().filter(pk=pk).first()
        if tier is None:
            raise not_found()
        return tier

    def get(self, request, pk):
        return Response(TierSerializer(self.get_object(pk), context=self.ctx()).data)

    def patch(self, request, pk):
        tier = self.get_object(pk)
        data = body(request)
        style = {k: data[k] for k in ('colors', 'medal') if k in data}
        if 'threshold' in data:
            data = {**{k: v for k, v in data.items() if k != 'threshold'}, 'from': data['threshold']}
        if style:
            if not request.user.can('tiers.edit'):
                raise forbidden(list(style))
            s = TierSerializer(tier, data=style, partial=True, context=self.ctx())
            s.is_valid(raise_exception=True)
            before = model_snapshot(tier)
            s.save()
            audit(request, 'tier.update', tier, before=before, after=model_snapshot(tier))
        rows = parse_tier_input({'tiers': [{**{k: v for k, v in data.items() if k not in style}, 'id': tier.id}]})
        upgraded = apply_tier_changes(request, rows)
        tier.refresh_from_db()
        return Response({**TierSerializer(tier, context=self.ctx()).data, 'upgraded': upgraded})

    put = patch

    def delete(self, request, pk):
        """?privilegesTo=<id> — перенести привилегии, иначе удалить их. Базовый уровень не удаляется."""
        if not request.user.can('tiers.edit'):
            raise forbidden(['tier'])
        tier = self.get_object(pk)
        target_id = request.query_params.get('privilegesTo') or (request.data or {}).get('privilegesTo')
        target = self.get_object(target_id) if target_id else None
        before = model_snapshot(tier)
        result = delete_tier(tier, privileges_to=target, actor=request.user)
        audit(request, 'tier.delete', None, object_type='loyalty.tier', object_id=pk, before=before, after=result)
        return Response(result)


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
