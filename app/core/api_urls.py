"""Маршруты /api/v1 — клиентский API (§4.1), рабочее место сотрудника (§8.5), вход в админку (§7.3)."""
from django.urls import include, path, re_path

from apps.analytics import api as analytics
from apps.cashback import api as cashback
from apps.cashback import staff_api as staffdesk
from apps.catalog import api as catalog
from apps.complaints import api as complaints
from apps.content import api as content
from apps.loyalty import api as loyalty
from apps.members import api as members
from apps.payments import api as payments
from apps.staff import api as staff_auth
from core import api_schema

api_schema.apply()

client = [
    # вход и профиль (§2)
    path('auth/otp/request', members.OtpRequestView.as_view()),
    path('auth/otp/verify', members.OtpVerifyView.as_view()),
    path('auth/google', members.GoogleLoginView.as_view()),
    path('auth/apple', members.AppleLoginView.as_view()),
    path('auth/register', members.RegisterView.as_view()),
    path('auth/refresh', members.RefreshView.as_view()),
    path('auth/logout', members.LogoutView.as_view()),
    path('auth/restore', members.RestoreView.as_view()),
    path('auth/restart', members.StartOverView.as_view()),
    path('me', members.MeView.as_view()),
    path('me/settings', members.MeSettingsView.as_view()),
    path('me/avatar', members.MeAvatarView.as_view()),
    re_path(r'^me/social/(?P<provider>google|apple)$', members.MeSocialView.as_view()),
    path('me/consents', members.ConsentsView.as_view()),
    path('me/devices', members.DevicesView.as_view()),
    path('me/devices/<path:token>', members.DeviceDeleteView.as_view()),
    path('me/deletion/request', members.DeletionRequestView.as_view()),
    path('me/deletion/confirm', members.DeletionConfirmView.as_view()),
    path('me/summary', loyalty.SummaryView.as_view()),
    path('me/achievements', loyalty.AchievementsView.as_view()),
    path('me/loyalty/history', loyalty.LoyaltyHistoryView.as_view()),
    path('me/member-qr', members.MemberQrView.as_view()),
    path('me/notifications', members.NotificationsView.as_view()),
    path('me/notifications/read', members.NotificationsReadView.as_view()),
    path('legal', members.LegalView.as_view()),
    path('app/config', members.AppConfigView.as_view()),
    path('resort/contacts', members.ResortContactsView.as_view()),
    # справочники (публичные)
    path('catalog', catalog.CatalogView.as_view()),
    path('catalog/items/<slug:item_id>', catalog.CatalogItemView.as_view()),
    path('loyalty/program', loyalty.ProgramView.as_view()),
    path('content/promos', content.PromosView.as_view()),
    path('content/events', content.EventsView.as_view()),
    path('content/stories', content.StoriesView.as_view()),
    path('content/articles/<slug:article_id>', content.ArticleView.as_view()),
    # кошелёк и заявки
    path('wallet', loyalty.WalletView.as_view()),
    path('wallet/operations', loyalty.OperationsView.as_view()),
    path('cashback-requests', cashback.RequestsView.as_view()),
    path('cashback-requests/quote', cashback.QuoteView.as_view()),
    path('cashback-requests/<str:request_id>', cashback.RequestDetailView.as_view()),
    path('cashback-requests/<str:request_id>/cancel', cashback.RequestCancelView.as_view()),
    # оплата
    path('payments', payments.PaymentsView.as_view()),
    path('payments/webhooks/<slug:provider>', payments.WebhookView.as_view()),
    path('payments/fake/<str:payment_id>/checkout', payments.fake_checkout),
    path('payments/<str:payment_id>', payments.PaymentDetailView.as_view()),
    path('payments/<str:payment_id>/check', payments.PaymentCheckView.as_view()),
    path('payments/<str:payment_id>/return', payments.payment_return),
    # обращения (§9)
    path('complaints/categories', complaints.CategoriesView.as_view()),
    path('uploads/complaint-photo', complaints.UploadPhotoView.as_view()),
    path('complaints', complaints.ComplaintsView.as_view()),
    path('complaints/<str:complaint_id>', complaints.ComplaintDetailView.as_view()),
    path('complaints/<str:complaint_id>/messages', complaints.ComplaintMessagesView.as_view()),
    path('complaints/<str:complaint_id>/rating', complaints.ComplaintRatingView.as_view()),
    # аналитика (§7.5)
    path('events', analytics.EventsIngestView.as_view()),
]

staff = [
    path('staff/queue', staffdesk.QueueView.as_view()),
    path('staff/requests/<str:request_id>', staffdesk.StaffRequestView.as_view()),
    path('staff/requests/<str:request_id>/confirm', staffdesk.ConfirmView.as_view()),
    path('staff/requests/<str:request_id>/adjust/preview', staffdesk.AdjustPreviewView.as_view()),
    path('staff/requests/<str:request_id>/adjust', staffdesk.AdjustView.as_view()),
    path('staff/requests/<str:request_id>/reject', staffdesk.RejectView.as_view()),
    path('staff/members', staffdesk.MemberSearchView.as_view()),
    path('staff/scan', staffdesk.ScanView.as_view()),
    path('staff/shift', staffdesk.ShiftView.as_view()),
    path('staff/points/items', staffdesk.PayItemsView.as_view()),
    path('staff/points/quote', staffdesk.PayQuoteView.as_view()),
    path('staff/points/charge', staffdesk.PayChargeView.as_view()),
]

admin_auth = [
    path('admin/auth/login', staff_auth.LoginView.as_view()),
    path('admin/auth/2fa', staff_auth.TwoFactorView.as_view()),
    path('admin/auth/refresh', staff_auth.RefreshView.as_view()),
    path('admin/auth/logout', staff_auth.LogoutView.as_view()),
    path('admin/me', staff_auth.MeView.as_view()),
    path('admin/me/password', staff_auth.PasswordView.as_view()),
]

urlpatterns = client + staff + admin_auth + [
    path('admin/', include('apps.analytics.admin_urls')),
    path('admin/', include('apps.backoffice.urls')),
]
