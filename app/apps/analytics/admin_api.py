"""
Админ-API отчётов и аналитики (§7.2 «Отчёты», §7.5 «Аналитика», §9.3 «Отчёт»).
Монтируется под /api/v1/admin/. Права — по блокам из apps/staff/roles.py.
"""
from django.http import FileResponse
from django.utils.encoding import escape_uri_path
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import ApiError
from apps.common.i18n import iso
from apps.staff.auth import HasPerm, StaffAuthentication
from apps.staff.roles import Role

from . import exports, reports
from .models import ExportJob

ANALYTICS_BLOCKS = ('funnel', 'members', 'cohorts', 'points', 'money', 'catalog', 'content', 'operations')


class StaffReportView(APIView):
    authentication_classes = [StaffAuthentication]
    permission_classes = [HasPerm]


class DashboardView(StaffReportView):
    """GET /reports/dashboard?from=&to=&groupBy=&category=&outlet=&tier=&platform=&language=&compare="""
    required_perms = 'reports.view'

    def get(self, request):
        return Response(reports.dashboard(reports.ReportParams.from_query(request.query_params)))


class AnalyticsBlockView(StaffReportView):
    """GET /analytics/{funnel|members|cohorts|points|money|catalog|content|operations}"""

    @property
    def required_perms(self):
        entry = reports.REPORTS.get(self.kwargs.get('block'))
        return list(entry[1]) if entry else None

    def get(self, request, block):
        if block not in ANALYTICS_BLOCKS:
            raise ApiError('not_found', 404)
        return Response(reports.run(block, reports.ReportParams.from_query(request.query_params)))


class LiabilityView(StaffReportView):
    """GET /analytics/liability?date=YYYY-MM-DD — обязательство в баллах и сомах на конец дня."""
    required_perms = ['analytics.points', 'reports.view']

    def get(self, request):
        raw = request.query_params.get('date')
        on_date = reports._parse_date(raw)
        if raw and on_date is None:
            raise ApiError('validation_error', 400, extra={'fields': {'date': ['YYYY-MM-DD']}})
        return Response(reports.liability(on_date))


class ComplaintsReportView(StaffReportView):
    """GET /analytics/complaints — §9.3."""
    required_perms = 'analytics.operations'

    def get(self, request):
        return Response(reports.complaints_report(reports.ReportParams.from_query(request.query_params)))


def job_payload(job):
    return {
        'id': job.pk, 'report': job.report, 'title': reports.REPORT_TITLES.get(job.report, job.report),
        'params': job.params, 'format': job.fmt, 'status': job.status, 'error': job.error or None,
        'createdAt': iso(job.created_at), 'finishedAt': iso(job.finished_at) if job.finished_at else None,
        'downloadUrl': f'/api/v1/admin/analytics/exports/{job.pk}/download' if job.status == 'done' and job.file
        else None,
    }


class ExportCreateView(StaffReportView):
    """POST /analytics/export {report, params, format: xlsx|csv} → ExportJob (фоновая выгрузка)."""
    required_perms = 'analytics.export'

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        report = data.get('report')
        fmt = (data.get('format') or 'xlsx').lower()
        params = data.get('params') or {}
        errors = {}
        if report not in reports.REPORTS:
            errors['report'] = [f'одно из: {", ".join(reports.REPORTS)}']
        if fmt not in exports.FORMATS:
            errors['format'] = ['xlsx | csv']
        if not isinstance(params, dict):
            errors['params'] = ['объект']
        if errors:
            raise ApiError('validation_error', 400, extra={'fields': errors})
        if not reports.can_view(request.user, report):
            raise ApiError('permission_denied', 403)
        # нормализуем параметры (даты по умолчанию фиксируются в момент запроса)
        if report == 'liability':
            norm = {'date': (reports._parse_date(params.get('date') or params.get('to'))
                             or reports.ReportParams.from_query({}).date_to).isoformat()}
        else:
            norm = reports.ReportParams.from_query(params).to_query()
        job = exports.create_job(request.user, report, norm, fmt)
        return Response(job_payload(job), status=202)


class ExportListView(StaffReportView):
    """GET /analytics/exports — выгрузки текущего сотрудника."""
    required_perms = 'analytics.export'

    def get(self, request):
        jobs = ExportJob.objects.filter(created_by=request.user).order_by('-created_at')[:100]
        return Response({'items': [job_payload(j) for j in jobs]})


class ExportDownloadView(StaffReportView):
    """GET /analytics/exports/{id}/download — файл из приватного хранилища после проверки прав."""
    required_perms = 'analytics.export'

    def get(self, request, pk):
        job = ExportJob.objects.filter(pk=pk).first()
        if job is None:
            raise ApiError('not_found', 404)
        own = job.created_by_id == request.user.pk
        if not (own or request.user.is_superuser or request.user.role == Role.OWNER):
            raise ApiError('not_found', 404)
        if not reports.can_view(request.user, job.report):
            raise ApiError('permission_denied', 403)
        if job.status != 'done' or not job.file:
            raise ApiError('not_found', 404)
        name = job.file.name.rsplit('/', 1)[-1]
        resp = FileResponse(job.file.open('rb'), content_type=exports.CONTENT_TYPES.get(job.fmt,
                                                                                       'application/octet-stream'))
        resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{escape_uri_path(name)}"
        resp['Cache-Control'] = 'private, no-store'
        return resp
