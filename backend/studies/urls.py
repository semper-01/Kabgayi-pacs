"""URL configuration for the studies application."""
from django.urls import path

from . import views
from . import export_views, status_views

app_name = "studies"

urlpatterns = [
    path("api/studies/", views.study_list, name="study-list"),
    path(
        "api/studies/<str:study_id>/export/",
        export_views.study_export,
        name="study-export",
    ),
    path("api/status/open/", status_views.status_open, name="status-open"),
    path("api/status/heartbeat/", status_views.status_heartbeat, name="status-heartbeat"),
    path("api/status/close/", status_views.status_close, name="status-close"),
    path("api/status/", status_views.status_list, name="status-list"),
]