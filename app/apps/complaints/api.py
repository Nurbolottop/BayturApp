from rest_framework.response import Response

from apps.catalog.models import Outlet
from apps.common.caching import cached_public
from apps.common.errors import ApiError
from apps.common.i18n import tr
from apps.common.pagination import paginate
from apps.common.views import MemberAPIView

from . import services
from .models import ComplaintCategory, PointsSubtype


class CategoriesView(MemberAPIView):
    """Темы на языке клиента + точки обслуживания."""

    def get(self, request):
        def build():
            return {
                'categories': [{'id': c.id, 'title': tr(c.title)} for c in ComplaintCategory.objects.filter(is_active=True)],
                'outlets': [{'id': o.id, 'name': tr(o.name)} for o in Outlet.objects.filter(is_active=True)],
                'pointsSubtypes': list(PointsSubtype.values),
            }
        return cached_public('complaint-categories', build, request)


class UploadPhotoView(MemberAPIView):
    def post(self, request):
        upload = services.upload_photo(request.user, request.FILES.get('file'))
        return Response({'id': upload.pk, 'url': upload.url}, status=201)


class ComplaintsView(MemberAPIView):
    def get(self, request):
        qs = request.user.complaints.select_related('category')
        return Response(paginate(request, qs, lambda rows: [services.complaint_payload(c, with_messages=False)
                                                            for c in rows]))

    def post(self, request):
        c = services.create_complaint(request.user, request.data if isinstance(request.data, dict) else {})
        return Response(services.complaint_payload(c), status=201)


class ComplaintDetailView(MemberAPIView):
    def get(self, request, complaint_id):
        c = request.user.complaints.select_related('category').filter(pk=complaint_id).first()
        if c is None:
            raise ApiError('not_found', 404)
        return Response(services.complaint_payload(c))


class ComplaintMessagesView(MemberAPIView):
    def post(self, request, complaint_id):
        c = services.client_reply(request.user, complaint_id, request.data if isinstance(request.data, dict) else {})
        return Response(services.complaint_payload(c), status=201)


class ComplaintRatingView(MemberAPIView):
    def post(self, request, complaint_id):
        c = services.rate(request.user, complaint_id, request.data.get('rating'), request.data.get('comment'))
        return Response(services.complaint_payload(c))
