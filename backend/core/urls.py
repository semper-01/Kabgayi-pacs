"""URL configuration for the core application."""
from django.urls import path

from . import views
from . import viewer_access

app_name = "core"

urlpatterns = [
    path("api/health/", views.health, name="health"),
    path(
        "api/viewer-access/grant/",
        viewer_access.issue_viewer_grant,
        name="viewer-access-grant",
    ),
    path(
        "api/viewer-access/revoke/",
        viewer_access.revoke_viewer_grant,
        name="viewer-access-revoke",
    ),
    path(
        "api/viewer-access/authorize/",
        viewer_access.authorize_dicomweb_request,
        name="viewer-access-authorize",
    ),
]