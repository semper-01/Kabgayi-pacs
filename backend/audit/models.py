"""Append-only operational audit events visible to administrators."""
from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    class EventType(models.TextChoices):
        LOGIN = "login", "Login"
        VIEWING = "viewing", "Viewing"
        PASSWORD_RESET = "password_reset", "Password reset"
        ADMIN_CHANGE = "admin_change", "Administrative change"
        MACHINE_CONFIGURATION = "machine_configuration", "Machine configuration"
        UNKNOWN_MACHINE = "unknown_machine", "Unknown machine"
        DICOM_IMPORT = "dicom_import", "DICOM import"
        NETWORK_CONFIGURATION = "network_configuration", "Network configuration"
        RESTART = "restart", "Restart confirmation"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    outcome = models.CharField(max_length=16, default="success")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    username = models.CharField(max_length=150, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"{self.get_event_type_display()} ({self.outcome}) at {self.created_at}"