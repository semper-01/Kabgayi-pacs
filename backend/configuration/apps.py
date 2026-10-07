"""App configuration for the configuration application."""
from django.apps import AppConfig


class ConfigurationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "configuration"
    verbose_name = "Configuration"