"""Отчёты и аналитика админки — монтируется под /api/v1/admin/."""
from django.urls import path, re_path

from . import admin_api as v

urlpatterns = [
    path('reports/dashboard', v.DashboardView.as_view()),
    path('analytics/liability', v.LiabilityView.as_view()),
    path('analytics/complaints', v.ComplaintsReportView.as_view()),
    path('analytics/export', v.ExportCreateView.as_view()),
    path('analytics/exports', v.ExportListView.as_view()),
    path('analytics/exports/<int:pk>/download', v.ExportDownloadView.as_view()),
    re_path(r'^analytics/(?P<block>funnel|members|cohorts|points|money|catalog|content|operations)$',
            v.AnalyticsBlockView.as_view()),
]
