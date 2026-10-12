"""Focused tests for Phase 9 administrator APIs and operational safeguards."""
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from audit.models import AuditEvent
from configuration.models import (
    Machine,
    OperationalConfiguration,
    StudyMachineAssociation,
)
from core.services.orthanc import OrthancService, OrthancUnavailableError


def _dicom_instance():
    sop_instance_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(
        None,
        {},
        file_meta=file_meta,
        preamble=b"\0" * 128,
    )
    dataset.SOPClassUID = CTImageStorage
    dataset.SOPInstanceUID = sop_instance_uid
    dataset.StudyInstanceUID = generate_uid()
    content = BytesIO()
    dataset.save_as(content, enforce_file_format=True)
    return content.getvalue()


@override_settings(AUTH_PASSWORD_VALIDATORS=[])
class AdministrationApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="admin",
            password="admin-password",
            account_type="administrator",
        )
        self.staff = user_model.objects.create_user(
            username="staff",
            password="staff-password",
            account_type="staff",
        )
        self.client = APIClient()

    def as_admin(self):
        self.client.force_authenticate(user=self.admin)

    def as_staff(self):
        self.client.force_authenticate(user=self.staff)

    def test_staff_cannot_access_administration_api(self):
        self.as_staff()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, 403)

    def test_administrator_can_create_user_without_returning_credentials(self):
        self.as_admin()

        response = self.client.post(
            "/api/admin/users/",
            {
                "username": "new-staff",
                "email": "new-staff@example.invalid",
                "account_type": "staff",
                "password": "temporary-password",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.json())
        self.assertTrue(
            get_user_model().objects.get(username="new-staff").check_password(
                "temporary-password"
            )
        )

    def test_only_the_two_existing_account_types_are_accepted(self):
        self.as_admin()

        response = self.client.post(
            "/api/admin/users/",
            {
                "username": "new-role",
                "account_type": "operator",
                "password": "temporary-password",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(username="new-role").exists())

    def test_cannot_deactivate_last_active_administrator(self):
        self.as_admin()

        response = self.client.patch(
            f"/api/admin/users/{self.admin.pk}/",
            {"is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_machine_registration_requires_edit_validate_review_apply(self):
        self.as_admin()
        values = {
            "display_name": "CT Room 1",
            "modality": "CT",
            "remote_ae_title": "CT_ROOM_1",
            "ip_address": "192.0.2.15",
            "port": 4242,
            "enabled": True,
        }
        created = self.client.post(
            "/api/admin/machines/",
            {"change_type": "machine_create", "values": values},
            format="json",
        )
        change_id = created.json()["id"]
        self.assertEqual(created.status_code, 201)
        self.assertFalse(Machine.objects.filter(remote_ae_title="CT_ROOM_1").exists())

        validated = self.client.post(
            f"/api/admin/configuration-changes/{change_id}/validate/",
            {},
            format="json",
        )
        self.assertEqual(validated.json()["state"], "validated")
        self.client.post(
            f"/api/admin/configuration-changes/{change_id}/review/",
            {},
            format="json",
        )
        applied = self.client.post(
            f"/api/admin/configuration-changes/{change_id}/apply/",
            {},
            format="json",
        )

        self.assertEqual(applied.status_code, 200)
        self.assertTrue(Machine.objects.get(remote_ae_title="CT_ROOM_1").enabled)

    def test_network_apply_requires_explicit_restart_confirmation_and_never_restarts(self):
        self.as_admin()
        staged = self.client.post(
            "/api/admin/configuration-changes/",
            {
                "change_type": "network",
                "values": {
                    "ae_title": "KABGAYI_PACS",
                    "dicom_port": 4243,
                    "lan_ip": "192.0.2.2",
                },
            },
            format="json",
        )
        change_id = staged.json()["id"]
        self.client.post(
            f"/api/admin/configuration-changes/{change_id}/validate/",
            {},
            format="json",
        )
        self.client.post(
            f"/api/admin/configuration-changes/{change_id}/review/",
            {},
            format="json",
        )

        requires_confirmation = self.client.post(
            f"/api/admin/configuration-changes/{change_id}/apply/",
            {},
            format="json",
        )
        self.assertEqual(requires_confirmation.status_code, 409)
        self.assertFalse(OperationalConfiguration.objects.filter(pk=1).exists())

        applied = self.client.post(
            f"/api/admin/configuration-changes/{change_id}/apply/",
            {"confirm_restart": True},
            format="json",
        )
        self.assertEqual(applied.status_code, 200)
        self.assertFalse(applied.json()["restart_performed"])
        self.assertEqual(OperationalConfiguration.objects.get(pk=1).dicom_port, 4243)
        self.assertTrue(
            AuditEvent.objects.filter(event_type=AuditEvent.EventType.RESTART).exists()
        )

    def test_zip_import_is_rejected_before_orthanc_access(self):
        self.as_admin()
        archive = SimpleUploadedFile("historic.zip", b"PK\x03\x04")

        with patch.object(OrthancService, "lookup_dicom") as lookup:
            response = self.client.post(
                "/api/admin/dicom-import/validate/",
                {"files": archive},
                format="multipart",
            )

        self.assertEqual(response.status_code, 415)
        lookup.assert_not_called()

    def test_duplicate_import_requires_explicit_choice(self):
        self.as_admin()
        dicom = SimpleUploadedFile("scan.dcm", _dicom_instance())
        with patch.object(
            OrthancService,
            "lookup_dicom",
            return_value=[{"Type": "Instance", "ID": "existing-instance"}],
        ):
            response = self.client.post(
                "/api/admin/dicom-import/import/",
                {"files": dicom},
                format="multipart",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["choices"], ["skip", "overwrite"])

    def test_validated_unique_dicom_import_is_stored_and_verified(self):
        self.as_admin()
        content = _dicom_instance()
        dicom = SimpleUploadedFile("scan.dcm", content)
        with (
            patch.object(OrthancService, "lookup_dicom", return_value=[]),
            patch.object(
                OrthancService,
                "store_dicom",
                return_value={"ID": "new-instance", "Status": "Success"},
            ) as store,
            patch.object(
                OrthancService,
                "get_instance",
                return_value={"ID": "new-instance", "ParentStudy": "study-1"},
            ),
        ):
            response = self.client.post(
                "/api/admin/dicom-import/import/",
                {"files": dicom},
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["verification"]["verified_count"], 1)
        self.assertEqual(response.json()["summary"][0]["study_id"], "study-1")
        store.assert_called_once_with(content)
        self.assertTrue(
            AuditEvent.objects.filter(event_type=AuditEvent.EventType.DICOM_IMPORT).exists()
        )

    def test_skip_policy_does_not_send_duplicate_instance_to_orthanc(self):
        self.as_admin()
        dicom = SimpleUploadedFile("scan.dcm", _dicom_instance())
        with (
            patch.object(
                OrthancService,
                "lookup_dicom",
                return_value=[{"Type": "Instance", "ID": "existing-instance"}],
            ),
            patch.object(OrthancService, "store_dicom") as store,
        ):
            response = self.client.post(
                "/api/admin/dicom-import/import/",
                {"files": dicom, "duplicate_policy": "skip"},
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"][0]["result"], "skipped_duplicate")
        store.assert_not_called()

    def test_duplicate_instances_within_one_upload_are_presented_and_skipped(self):
        self.as_admin()
        content = _dicom_instance()
        validation_files = [
            SimpleUploadedFile("one.dcm", content),
            SimpleUploadedFile("copy.dcm", content),
        ]
        with patch.object(OrthancService, "lookup_dicom", return_value=[]):
            validation = self.client.post(
                "/api/admin/dicom-import/validate/",
                {"files": validation_files},
                format="multipart",
            )

        self.assertEqual(validation.status_code, 200)
        self.assertEqual(validation.json()["duplicate_count"], 1)
        self.assertEqual(
            validation.json()["files"][1]["duplicates"][0]["type"],
            "BatchDuplicate",
        )

        import_files = [
            SimpleUploadedFile("one.dcm", content),
            SimpleUploadedFile("copy.dcm", content),
        ]
        with (
            patch.object(OrthancService, "lookup_dicom", return_value=[]),
            patch.object(
                OrthancService,
                "store_dicom",
                return_value={"ID": "new-instance", "Status": "Success"},
            ) as store,
            patch.object(
                OrthancService,
                "get_instance",
                return_value={"ID": "new-instance", "ParentStudy": "study-1"},
            ),
        ):
            imported = self.client.post(
                "/api/admin/dicom-import/import/",
                {"files": import_files, "duplicate_policy": "skip"},
                format="multipart",
            )

        self.assertEqual(imported.status_code, 200)
        self.assertEqual(
            [item["result"] for item in imported.json()["summary"]],
            ["imported", "skipped_duplicate"],
        )
        store.assert_called_once_with(content)

    def test_overwrite_policy_replaces_only_matching_instance(self):
        self.as_admin()
        replacement = _dicom_instance()
        dicom = SimpleUploadedFile("scan.dcm", replacement)
        existing = {"Type": "Instance", "ID": "existing-instance"}
        with (
            patch.object(OrthancService, "lookup_dicom", return_value=[existing]),
            patch.object(
                OrthancService,
                "get_instance_file",
                return_value=BytesIO(b"original-dicom"),
            ),
            patch.object(OrthancService, "delete_instance") as delete,
            patch.object(
                OrthancService,
                "store_dicom",
                return_value={"ID": "replacement-instance", "Status": "Success"},
            ) as store,
            patch.object(
                OrthancService,
                "get_instance",
                return_value={"ID": "replacement-instance", "ParentStudy": "study-1"},
            ),
        ):
            response = self.client.post(
                "/api/admin/dicom-import/import/",
                {"files": dicom, "duplicate_policy": "overwrite"},
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        delete.assert_called_once_with("existing-instance")
        store.assert_called_once_with(replacement)

    def test_login_endpoint_records_successful_login(self):
        self.client.force_authenticate(user=self.staff)

        response = self.client.get("/api/auth/session/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["account_type"], "staff")
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.EventType.LOGIN,
                username="staff",
            ).exists()
        )

    def test_machine_identity_mismatch_is_rejected_and_audited(self):
        self.as_admin()
        Machine.objects.create(
            display_name="CT Room 1",
            modality="CT",
            remote_ae_title="CT_ROOM_1",
            ip_address="192.0.2.15",
            port=4242,
            enabled=True,
        )

        response = self.client.post(
            "/api/admin/machines/ingestion-check/",
            {"remote_ae_title": "UNKNOWN", "ip_address": "192.0.2.16"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.EventType.UNKNOWN_MACHINE,
                outcome="rejected",
            ).exists()
        )

    def test_machine_study_association_requires_exact_orthanc_origin(self):
        self.as_admin()
        machine = Machine.objects.create(
            display_name="CT Room 1",
            modality="CT",
            remote_ae_title="CT_ROOM_1",
            ip_address="192.0.2.15",
            port=4242,
            enabled=True,
        )
        with (
            patch.object(
                OrthancService,
                "get_study",
                return_value={"ID": "study-1", "Series": ["series-1"]},
            ),
            patch.object(
                OrthancService,
                "get_study_instances",
                return_value=["instance-1"],
            ),
            patch.object(
                OrthancService,
                "get_instance",
                return_value={
                    "ID": "instance-1",
                    "Origin": {
                        "RemoteAet": "CT_ROOM_1",
                        "RemoteIp": "192.0.2.15",
                    },
                },
            ),
        ):
            response = self.client.post(
                f"/api/admin/machines/{machine.pk}/verify-studies/",
                {"study_ids": ["study-1"]},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["associated_studies"], ["study-1"])
        self.assertTrue(
            StudyMachineAssociation.objects.filter(
                study_id="study-1",
                machine=machine,
                source_ae_title="CT_ROOM_1",
                source_ip_address="192.0.2.15",
            ).exists()
        )

    def test_service_health_reports_each_dependency_status(self):
        self.as_admin()
        ohif_response = MagicMock()
        ohif_response.__enter__.return_value = ohif_response
        ohif_response.status = 200
        with (
            patch("configuration.views.connection.ensure_connection"),
            patch.object(OrthancService, "get_system", return_value={}),
            patch("configuration.views.urlopen", return_value=ohif_response),
        ):
            healthy = self.client.get("/api/admin/service-health/")
        self.assertEqual(healthy.status_code, 200)
        self.assertEqual(healthy.json()["overall"], "healthy")
        self.assertEqual(
            [service["status"] for service in healthy.json()["services"]],
            ["healthy", "healthy", "healthy", "healthy"],
        )

        with (
            patch(
                "configuration.views.connection.ensure_connection",
                side_effect=OperationalError("database unavailable"),
            ),
            patch.object(
                OrthancService,
                "get_system",
                side_effect=OrthancUnavailableError("unavailable"),
            ),
            patch(
                "configuration.views.urlopen",
                side_effect=URLError("unavailable"),
            ),
        ):
            offline = self.client.get("/api/admin/service-health/")
        self.assertEqual(offline.json()["overall"], "offline")
        self.assertEqual(
            [service["status"] for service in offline.json()["services"]],
            ["healthy", "offline", "offline", "offline"],
        )
