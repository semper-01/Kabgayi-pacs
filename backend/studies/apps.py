"""App configuration for the studies application."""
from django.apps import AppConfig


class StudiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "studies"
    verbose_name = "Studies"