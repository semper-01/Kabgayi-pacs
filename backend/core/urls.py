"""URL configuration for the core application."""
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("api/health/", views.health, name="health"),
]