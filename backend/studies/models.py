"""
Application boundary for future study-related business logic.

IMPORTANT (Phase 2 scope):
    * No Orthanc study integration is implemented yet.
    * The Orthanc Patient -> Study -> Series -> Instance hierarchy is NOT
      duplicated here. Orthanc remains the source of truth for DICOM data.
    * This app intentionally ships with no models so that DICOM study data is
      never duplicated into Django.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ViewingSession(models.Model):
    """Application viewing state; study_id refers to Orthanc, not a Django model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    study_id = models.CharField(max_length=128, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="viewing_sessions",
    )
    opened_at = models.DateTimeField(default=timezone.now)
    last_heartbeat_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["study_id", "is_active", "last_heartbeat_at"],
                name="studies_view_study_active_hb",
            )
        ]