from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['at', 'actor_label', 'action', 'object_type', 'object_id', 'ip']
    list_filter = ['action']
    search_fields = ['object_id', 'actor_label']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
