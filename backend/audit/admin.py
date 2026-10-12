"""Read-only Django admin visibility for operational audit entries."""
from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "outcome", "username", "source_ip")
    list_filter = ("event_type", "outcome")
    search_fields = ("username", "source_ip")
    readonly_fields = (
        "created_at",
        "event_type",
        "outcome",
        "user",
        "username",
        "source_ip",
        "details",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False