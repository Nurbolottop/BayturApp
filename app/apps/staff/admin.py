"""Технический Django admin (/django-admin/) — для разработчиков. Рабочая админка — /panel/."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import StaffUser


@admin.register(StaffUser)
class StaffUserAdmin(UserAdmin):
    ordering = ['email']
    list_display = ['email', 'full_name', 'role', 'is_active', 'totp_enabled']
    list_filter = ['role', 'is_active']
    search_fields = ['email', 'full_name']
    filter_horizontal = ['outlets']
    fieldsets = [
        (None, {'fields': ['email', 'password', 'full_name', 'phone']}),
        ('Роль', {'fields': ['role', 'outlets', 'is_active', 'is_staff', 'is_superuser']}),
        ('2FA', {'fields': ['totp_enabled']}),
    ]
    add_fieldsets = [(None, {'fields': ['email', 'full_name', 'role', 'password1', 'password2']})]
    readonly_fields = ['totp_enabled']
