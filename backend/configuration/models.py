"""Registered modalities and explicitly staged, non-secret PACS settings."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Machine(models.Model):
    display_name = models.CharField(max_length=120)
    modality = models.CharField(max_length=16)
    remote_ae_title = models.CharField(max_length=16, unique=True)
    ip_address = models.GenericIPAddressField()
    port = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(65535)]
    )
    enabled = models.BooleanField(default=True)
    connectivity_status = models.CharField(max_length=16, default="unknown")
    last_connectivity_check = models.DateTimeField(null=True, blank=True)
    ingestion_status = models.CharField(max_length=24, default="unverified")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name", "pk")

    def __str__(self):
        return f"{self.display_name} ({self.remote_ae_title})"


class OperationalConfiguration(models.Model):
    ae_title = models.CharField(max_length=16, default="ORTHANC")
    dicom_port = models.PositiveIntegerField(
        default=4242,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    lan_ip = models.GenericIPAddressField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operational_configuration_updates",
    )

    class Meta:
        verbose_name = "operational configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class ConfigurationChange(models.Model):
    class State(models.TextChoices):
        EDIT = "edit", "Edit"
        VALIDATED = "validated", "Validated"
        REVIEWED = "reviewed", "Reviewed"
        APPLIED = "applied", "Applied"

    change_type = models.CharField(max_length=24)
    proposed_values = models.JSONField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.EDIT)
    validation_errors = models.JSONField(default=list, blank=True)
    restart_required = models.BooleanField(default=False)
    restart_confirmed = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="configuration_changes_created",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="configuration_changes_reviewed",
    )
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="configuration_changes_applied",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")


class StudyMachineAssociation(models.Model):
    """A machine association established only after validating a DICOM sender."""

    study_id = models.CharField(max_length=128, db_index=True)
    machine = models.ForeignKey(
        Machine,
        on_delete=models.PROTECT,
        related_name="study_associations",
    )
    source_ae_title = models.CharField(max_length=16)
    source_ip_address = models.GenericIPAddressField()
    validated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-validated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["study_id", "machine"],
                name="configuration_unique_study_machine",
            )
        ]