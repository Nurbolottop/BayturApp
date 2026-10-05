"""
Админ-API /api/v1/admin/* (ТЗ §7.3, §9.5). Вход (/auth/*, /me) — apps.staff.api;
аналитика и отчёты (/analytics/*, /reports/*) — apps.analytics.
"""
from django.urls import path

from .views import campaigns, catalog, complaints, content, loyalty, members, operations, system


def content_routes(prefix, views, pk='int'):
    routes = [
        path(f'{prefix}', views['list'].as_view()),
        path(f'{prefix}/<{pk}:pk>', views['detail'].as_view()),
        path(f'{prefix}/<{pk}:pk>/publish', views['publish'].as_view()),
        path(f'{prefix}/<{pk}:pk>/unpublish', views['unpublish'].as_view()),
        path(f'{prefix}/<{pk}:pk>/preview', views['preview'].as_view()),
    ]
    if 'sort' in views:
        routes.insert(1, path(f'{prefix}/sort', views['sort'].as_view()))
    return routes


urlpatterns = [
    # каталог
    path('outlets', catalog.OutletsView.as_view()),
    path('outlets/sort', catalog.OutletsSortView.as_view()),
    path('outlets/<slug:pk>', catalog.OutletDetailView.as_view()),
    path('categories', catalog.CategoriesView.as_view()),
    path('categories/sort', catalog.CategoriesSortView.as_view()),
    path('categories/<slug:pk>', catalog.CategoryDetailView.as_view()),
    path('items', catalog.ItemsView.as_view()),
    path('items/sort', catalog.ItemsSortView.as_view()),
    path('items/<slug:pk>', catalog.ItemDetailView.as_view()),
    path('items/<slug:pk>/hide', catalog.ItemVisibilityView.as_view(visible=False)),
    path('items/<slug:pk>/show', catalog.ItemVisibilityView.as_view(visible=True)),
    path('items/<slug:item_id>/promos', catalog.ItemPromosView.as_view()),
    path('items/<slug:item_id>/promos/<int:pk>', catalog.ItemPromoDetailView.as_view()),

    # уровни и привилегии
    path('tiers', loyalty.TiersView.as_view()),
    path('tiers/preview', loyalty.TiersPreviewView.as_view()),
    path('tiers/<slug:pk>', loyalty.TierDetailView.as_view()),
    path('privileges', loyalty.PrivilegesView.as_view()),
    path('privileges/sort', loyalty.PrivilegesSortView.as_view()),
    path('privileges/<slug:pk>', loyalty.PrivilegeDetailView.as_view()),

    # контент
    *content_routes('articles', content.articles, pk='slug'),
    *content_routes('promos', content.promos),
    *content_routes('events', content.events),
    *content_routes('stories', content.stories),
    path('stories/<int:pk>/slides', content.StorySlidesView.as_view()),

    # клиенты
    path('members', members.MembersView.as_view()),
    path('members/<int:pk>', members.MemberDetailView.as_view()),
    path('members/<int:pk>/requests', members.MemberRequestsView.as_view()),
    path('members/<int:pk>/operations', members.MemberOperationsView.as_view()),
    path('members/<int:pk>/block', members.BlockView.as_view()),
    path('members/<int:pk>/unblock', members.UnblockView.as_view()),
    path('members/<int:pk>/adjustments', members.AdjustmentsView.as_view()),
    path('members/<int:pk>/birthday', members.BirthdayView.as_view()),
    path('members/<int:pk>/phone', members.PhoneView.as_view()),
    path('members/<int:pk>/export', members.ExportView.as_view()),
    path('members/<int:pk>/restore', members.RestoreView.as_view()),
    path('members/<int:pk>/purge-now', members.PurgeNowView.as_view()),

    # заявки и платежи
    path('cashback-requests', operations.RequestsView.as_view()),
    path('cashback-requests/<str:request_id>', operations.RequestDetailView.as_view()),
    path('cashback-requests/<str:request_id>/confirm', operations.ConfirmView.as_view()),
    path('cashback-requests/<str:request_id>/reject', operations.RejectView.as_view()),
    path('cashback-requests/<str:request_id>/adjust/preview', operations.AdjustPreviewView.as_view()),
    path('cashback-requests/<str:request_id>/adjust', operations.AdjustView.as_view()),
    path('cashback-requests/<str:request_id>/approve-escalation', operations.ApproveEscalationView.as_view()),
    path('cashback-requests/<str:request_id>/decline-escalation', operations.DeclineEscalationView.as_view()),
    path('payments', operations.PaymentsView.as_view()),
    path('payments/reconciliation', operations.ReconciliationView.as_view()),
    path('payments/<str:payment_id>', operations.PaymentDetailView.as_view()),
    path('payments/<str:payment_id>/refund', operations.RefundView.as_view()),

    # рассылки
    path('campaigns', campaigns.CampaignsView.as_view()),
    path('campaigns/<int:pk>', campaigns.CampaignDetailView.as_view()),
    path('campaigns/<int:pk>/send', campaigns.CampaignSendView.as_view()),
    path('campaigns/<int:pk>/cancel', campaigns.CampaignCancelView.as_view()),
    path('campaigns/<int:pk>/test', campaigns.CampaignTestView.as_view()),
    path('push-templates', campaigns.PushTemplatesView.as_view()),
    path('push-templates/<str:kind>', campaigns.PushTemplateDetailView.as_view()),

    # администрирование
    path('settings', system.SettingsView.as_view()),
    path('legal', system.LegalView.as_view()),
    path('legal/<int:pk>', system.LegalDetailView.as_view()),
    path('legal/<int:pk>/publish', system.LegalPublishView.as_view()),
    path('staff', system.StaffListView.as_view()),
    path('staff/roles', system.RolesView.as_view()),
    path('staff/directory', system.StaffDirectoryView.as_view()),
    path('staff/<int:pk>', system.StaffDetailView.as_view()),
    path('staff/<int:pk>/activate', system.StaffActionView.as_view(action='activate')),
    path('staff/<int:pk>/deactivate', system.StaffActionView.as_view(action='deactivate')),
    path('staff/<int:pk>/reset-2fa', system.StaffActionView.as_view(action='reset-2fa')),
    path('staff/<int:pk>/reset-password', system.StaffActionView.as_view(action='reset-password')),
    path('staff/<int:pk>/set-pin', system.StaffActionView.as_view(action='set-pin')),
    path('uploads', system.UploadView.as_view()),
    path('audit', system.AuditView.as_view()),

    # обращения
    path('complaints', complaints.ComplaintsView.as_view()),
    path('complaints/counters', complaints.CountersView.as_view()),
    path('complaints/<str:pk>', complaints.ComplaintDetailView.as_view()),
    path('complaints/<str:pk>/assign', complaints.AssignView.as_view()),
    path('complaints/<str:pk>/reply', complaints.ReplyView.as_view()),
    path('complaints/<str:pk>/notes', complaints.NotesView.as_view()),
    path('complaints/<str:pk>/status', complaints.StatusView.as_view()),
    path('complaints/<str:pk>/compensate', complaints.CompensateView.as_view()),
    path('complaint-categories', complaints.CategoriesView.as_view()),
    path('complaint-categories/sort', complaints.CategoriesSortView.as_view()),
    path('complaint-categories/<slug:pk>', complaints.CategoryDetailView.as_view()),
    path('reply-templates', complaints.TemplatesView.as_view()),
    path('reply-templates/sort', complaints.TemplatesSortView.as_view()),
    path('reply-templates/<int:pk>', complaints.TemplateDetailView.as_view()),
]
