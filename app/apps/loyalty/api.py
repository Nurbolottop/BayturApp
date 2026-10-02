from apps.common.caching import cached_public
from apps.common.i18n import iso, tr
from apps.common.pagination import paginate
from apps.common.views import MemberAPIView, PublicAPIView
from rest_framework.response import Response

from .models import Privilege, Tier
from .services import get_wallet, wallet_payload


def build_program():
    return {
        'tiers': [{'id': t.id, 'name': tr(t.name), 'from': t.from_points, 'colors': t.gradient,
                   'medal': absolute_media_url(t.medal) if t.medal else None}
                  for t in Tier.objects.order_by('from_points')],
        'privileges': [{
            'id': p.id, 'tier': p.tier_id, 'icon': p.icon, 'title': tr(p.title), 'short': tr(p.short),
            'description': tr(p.description),
        } for p in Privilege.objects.select_related('tier')],
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


class WalletView(MemberAPIView):
    def get(self, request):
        return Response(wallet_payload(request.user))


class OperationsView(MemberAPIView):
    def get(self, request):
        return Response(paginate(request, request.user.operations.all(),
                                 lambda rows: [operation_payload(o) for o in rows], time_field='at'))


class SummaryView(MemberAPIView):
    def get(self, request):
        wallet = get_wallet(request.user)
        return Response({'available': wallet.available, 'lifetime': wallet.lifetime,
                         'requestsCount': request.user.cashback_requests.count()})
