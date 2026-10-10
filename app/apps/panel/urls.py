from django.urls import path

from . import views
from .views import (admin, auth, campaigns, catalog, complaints, content, desk, members, modes, money, promotions,
                    reports, season, tiers)

app_name = 'panel'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', auth.login_view, name='login'),
    path('login/2fa/', auth.totp_view, name='login-2fa'),
    path('logout/', auth.logout_view, name='logout'),
    path('password/', auth.password_view, name='password'),

    # отчёты
    path('dashboard/', reports.dashboard, name='dashboard'),
    path('analytics/', reports.analytics, name='analytics'),
    path('analytics/<slug:block>/', reports.analytics, name='analytics-block'),
    path('analytics/<slug:block>/export/', reports.analytics_export, name='analytics-export'),

    # рабочее место
    path('desk/', desk.desk, name='desk'),
    path('desk/r/<str:request_id>/', desk.desk_request, name='desk-request'),
    path('desk/members/', desk.desk_members, name='desk-members'),
    path('desk/scan/', desk.desk_scan, name='desk-scan'),
    path('desk/shift/', desk.desk_shift, name='desk-shift'),
    path('desk/pay/quote/', desk.desk_pay_quote, name='desk-pay-quote'),
    path('desk/pay/charge/', desk.desk_pay_charge, name='desk-pay-charge'),
    path('r/<str:request_id>/preview/', desk.adjust_preview, name='request-preview'),
    path('r/<str:request_id>/<slug:action>/', desk.request_action, name='request-action'),

    # заявки и платежи
    path('requests/', money.requests_list, name='requests'),
    path('requests/<str:request_id>/', money.request_detail, name='request'),
    path('payments/', money.payments_list, name='payments'),
    path('payments/<str:payment_id>/', money.payment_detail, name='payment'),
    path('payments/<str:payment_id>/refund/', money.payment_refund, name='payment-refund'),

    # клиенты
    path('members/', members.members_list, name='members'),
    path('members/<int:pk>/', members.member_detail, name='member'),
    path('members/<int:pk>/export/', members.member_export, name='member-export'),
    path('members/<int:pk>/account/<slug:action>/', members.member_lifecycle, name='member-lifecycle'),
    path('members/<int:pk>/<slug:action>/', members.member_action, name='member-action'),

    # каталог
    path('catalog/', catalog.catalog, name='catalog'),
    path('catalog/category/<str:category_id>/', catalog.category_edit, name='category'),
    path('catalog/venues/<slug:venue_id>/', modes.venue_edit, name='venue'),
    path('mode/<slug:mode>/', modes.mode_switch, name='mode'),
    path('sk-season/', season.sk_season, name='sk-season'),
    path('venue/', modes.venue_current, name='venue-current'),
    path('showcase/', modes.showcase_edit, name='showcase'),
    path('eternal/', modes.eternal_edit, name='eternal'),
    path('catalog/sections/new/', catalog.section_edit, name='section-new'),
    path('catalog/sections/<slug:section_id>/', catalog.section_edit, name='section'),
    path('catalog/items/new/', catalog.item_edit, name='item-new'),
    path('catalog/items/<slug:item_id>/', catalog.item_edit, name='item'),
    path('catalog/items/<slug:item_id>/<slug:action>/', catalog.item_action, name='item-action'),
    path('uploads/', catalog.upload, name='upload'),
    path('promotions/', promotions.promotions, name='promotions'),
    path('promotions/new/', promotions.promotion_edit, name='promotion-new'),
    path('promotions/<int:promotion_id>/', promotions.promotion_edit, name='promotion'),
    path('promotions/<int:promotion_id>/toggle/', promotions.promotion_toggle, name='promotion-toggle'),

    # уровни
    path('tiers/', tiers.tiers, name='tiers'),
    path('tiers/new/', tiers.tier_edit, name='tier-new'),
    path('tiers/level/<slug:tier_id>/', tiers.tier_edit, name='tier'),
    path('tiers/level/<slug:tier_id>/delete/', tiers.tier_delete, name='tier-delete'),
    path('tiers/privileges/new/', tiers.privilege_edit, name='privilege-new'),
    path('tiers/privileges/<slug:privilege_id>/', tiers.privilege_edit, name='privilege'),
    path('tiers/privileges/<slug:privilege_id>/delete/', tiers.privilege_delete, name='privilege-delete'),

    # контент
    path('content/', content.content_list, name='content'),
    path('content/<slug:kind>/', content.content_list, name='content-kind'),
    path('content/<slug:kind>/new/', content.content_edit, name='content-new'),
    path('content/<slug:kind>/<str:pk>/', content.content_edit, name='content-edit'),
    path('content/<slug:kind>/<str:pk>/<slug:action>/', content.content_action, name='content-action'),

    # рассылки
    path('campaigns/', campaigns.campaigns, name='campaigns'),
    path('campaigns/new/', campaigns.campaign_edit, name='campaign-new'),
    path('campaigns/templates/', campaigns.push_templates, name='push-templates'),
    path('campaigns/<int:pk>/', campaigns.campaign_edit, name='campaign'),
    path('campaigns/<int:pk>/<slug:action>/', campaigns.campaign_action, name='campaign-action'),

    # обращения
    path('complaints/', complaints.complaints, name='complaints'),
    path('complaints/categories/', complaints.complaint_categories, name='complaint-categories'),
    path('complaints/categories/<slug:pk>/', complaints.complaint_categories, name='complaint-category'),
    path('complaints/templates/', complaints.reply_templates, name='reply-templates'),
    path('complaints/templates/<int:pk>/', complaints.reply_templates, name='reply-template'),
    path('complaints/<str:pk>/', complaints.complaint_detail, name='complaint'),
    path('complaints/<str:pk>/<slug:action>/', complaints.complaint_action, name='complaint-action'),

    # администрирование
    path('settings/', admin.settings_view, name='settings'),
    path('settings/outlets/new/', admin.outlet_edit, name='outlet-new'),
    path('settings/outlets/<slug:pk>/', admin.outlet_edit, name='outlet'),
    path('settings/<slug:tab>/', admin.settings_view, name='settings-tab'),
    path('staff/', admin.staff_list, name='staff'),
    path('staff/new/', admin.staff_edit, name='staff-new'),
    path('staff/<int:pk>/', admin.staff_edit, name='staff-edit'),
    path('staff/<int:pk>/reset-2fa/', admin.staff_reset_2fa, name='staff-reset-2fa'),
    path('audit/', admin.audit_log, name='audit'),
]
