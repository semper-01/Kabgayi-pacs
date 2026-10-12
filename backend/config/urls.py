"""Root URL configuration for the Kabgayi PACS backend."""
from django.contrib import admin
from django.urls import include, path
from configuration import views as configuration_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("studies.urls")),
    path("api/admin/overview/", configuration_views.overview, name="admin-overview"),
    path("api/admin/users/", configuration_views.users, name="admin-users"),
    path(
        "api/admin/users/<int:user_id>/",
        configuration_views.user_action,
        name="admin-user-action",
    ),
    path("api/admin/activity/", configuration_views.activity, name="admin-activity"),
    path(
        "api/admin/service-health/",
        configuration_views.service_health,
        name="admin-service-health",
    ),
    path("api/admin/machines/", configuration_views.machines, name="admin-machines"),
    path(
        "api/admin/machines/<int:machine_id>/connectivity/",
        configuration_views.machine_connectivity,
        name="admin-machine-connectivity",
    ),
    path(
        "api/admin/machines/ingestion-check/",
        configuration_views.machine_ingestion_check,
        name="admin-machine-ingestion-check",
    ),
    path(
        "api/admin/machines/<int:machine_id>/studies/",
        configuration_views.machine_studies,
        name="admin-machine-studies",
    ),
    path(
        "api/admin/machines/<int:machine_id>/verify-studies/",
        configuration_views.sync_machine_studies,
        name="admin-machine-verify-studies",
    ),
    path(
        "api/admin/network-configuration/",
        configuration_views.operational_configuration,
        name="admin-network-configuration",
    ),
    path(
        "api/admin/configuration-changes/",
        configuration_views.configuration_changes,
        name="admin-configuration-changes",
    ),
    path(
        "api/admin/configuration-changes/<int:change_id>/validate/",
        configuration_views.validate_configuration_change,
        name="admin-configuration-validate",
    ),
    path(
        "api/admin/configuration-changes/<int:change_id>/review/",
        configuration_views.review_configuration_change,
        name="admin-configuration-review",
    ),
    path(
        "api/admin/configuration-changes/<int:change_id>/apply/",
        configuration_views.apply_configuration_change,
        name="admin-configuration-apply",
    ),
    path(
        "api/admin/dicom-import/validate/",
        configuration_views.validate_dicom_import,
        name="admin-dicom-import-validate",
    ),
    path(
        "api/admin/dicom-import/import/",
        configuration_views.import_dicom,
        name="admin-dicom-import",
    ),
]