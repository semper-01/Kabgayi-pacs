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
from studies.models import ViewingSession


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

    def test_user_creation_validates_email_and_duplicate_username(self):
        self.as_admin()
        payload = {
            "username": "email-check",
            "email": "not-an-email",
            "account_type": "staff",
            "password": "temporary-password",
        }
        invalid_email = self.client.post("/api/admin/users/", payload, format="json")
        self.assertEqual(invalid_email.status_code, 400)
        self.assertIn("email", invalid_email.json()["errors"])
        self.assertFalse(get_user_model().objects.filter(username="email-check").exists())

        payload["email"] = "  PERSON@example.invalid "
        created = self.client.post("/api/admin/users/", payload, format="json")
        self.assertEqual(created.status_code, 201)
        saved_user = get_user_model().objects.get(username="email-check")
        self.assertEqual(saved_user.email, "person@example.invalid")
        self.assertTrue(saved_user.check_password("temporary-password"))
        self.client.force_authenticate(user=None)
        self.assertTrue(
            self.client.login(
                username="email-check",
                password="temporary-password",
            )
        )
        self.assertEqual(self.client.get("/api/auth/session/").status_code, 200)

        self.as_admin()
        payload["email"] = "other@example.invalid"
        duplicate = self.client.post("/api/admin/users/", payload, format="json")
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("username", duplicate.json()["errors"])
        self.assertEqual(get_user_model().objects.filter(username="email-check").count(), 1)

    def test_non_unique_email_policy_is_preserved(self):
        self.as_admin()
        for username in ("same-email-one", "same-email-two"):
            response = self.client.post(
                "/api/admin/users/",
                {
                    "username": username,
                    "email": "shared@example.invalid",
                    "account_type": "staff",
                    "password": "temporary-password",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201)
        self.assertEqual(
            get_user_model().objects.filter(email="shared@example.invalid").count(),
            2,
        )

    def test_password_reset_changes_authentication_and_stores_a_hash(self):
        self.as_admin()
        target = get_user_model().objects.create_user(
            username="password-reset-target",
            password="OldControlledPass99!",
            account_type="staff",
        )

        response = self.client.post(
            f"/api/admin/users/{target.pk}/",
            {"new_password": "NewControlledPass99!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.client.force_authenticate(user=None)
        self.assertFalse(
            self.client.login(
                username="password-reset-target",
                password="OldControlledPass99!",
            )
        )
        self.assertTrue(
            self.client.login(
                username="password-reset-target",
                password="NewControlledPass99!",
            )
        )
        self.assertEqual(self.client.get("/api/auth/session/").status_code, 200)
        self.assertNotEqual(target.password, "NewControlledPass99!")

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

    def test_machine_registration_draft_can_be_cancelled_and_retried_safely(self):
        self.as_admin()
        values = {
            "display_name": "CT Room 2",
            "modality": "CT",
            "remote_ae_title": "CT_ROOM_2",
            "ip_address": "192.0.2.16",
            "port": 4242,
            "enabled": True,
        }
        path = "/api/admin/machines/"
        first = self.client.post(
            path,
            {"change_type": "machine_create", "values": values},
            format="json",
        )
        second = self.client.post(
            path,
            {"change_type": "machine_create", "values": values},
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])

        cancelled = self.client.post(
            f"/api/admin/configuration-changes/{first.json()['id']}/cancel/",
            {},
            format="json",
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["state"], "cancelled")
        self.assertFalse(Machine.objects.filter(remote_ae_title="CT_ROOM_2").exists())

    def test_machine_deletion_requires_confirmation_and_preserves_associated_history(self):
        self.as_admin()
        machine = Machine.objects.create(
            display_name="CT Room 3",
            modality="CT",
            remote_ae_title="CT_ROOM_3",
            ip_address="192.0.2.17",
            port=4242,
            enabled=False,
        )
        path = f"/api/admin/machines/{machine.pk}/"
        no_confirmation = self.client.delete(path, {}, format="json")
        self.assertEqual(no_confirmation.status_code, 400)
        self.assertTrue(Machine.objects.filter(pk=machine.pk).exists())

        StudyMachineAssociation.objects.create(
            study_id="orthanc-study-id",
            machine=machine,
            source_ae_title=machine.remote_ae_title,
            source_ip_address=machine.ip_address,
        )
        blocked = self.client.delete(path, {"confirm": True}, format="json")
        self.assertEqual(blocked.status_code, 409)
        self.assertTrue(Machine.objects.filter(pk=machine.pk).exists())
        self.assertTrue(
            StudyMachineAssociation.objects.filter(
                study_id="orthanc-study-id",
                machine=machine,
            ).exists()
        )

    def test_machine_without_dependencies_can_be_deleted_by_administrator(self):
        self.as_admin()
        machine = Machine.objects.create(
            display_name="Unused CT",
            modality="CT",
            remote_ae_title="UNUSED_CT",
            ip_address="192.0.2.18",
            port=4242,
            enabled=False,
        )

        response = self.client.delete(
            f"/api/admin/machines/{machine.pk}/",
            {"confirm": True},
            format="json",
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Machine.objects.filter(pk=machine.pk).exists())

    def test_staff_cannot_cancel_or_delete_machine_registrations(self):
        machine = Machine.objects.create(
            display_name="Staff test CT",
            modality="CT",
            remote_ae_title="STAFF_TEST_CT",
            ip_address="192.0.2.19",
            port=4242,
            enabled=False,
        )
        self.as_staff()

        deleted = self.client.delete(
            f"/api/admin/machines/{machine.pk}/",
            {"confirm": True},
            format="json",
        )
        self.assertEqual(deleted.status_code, 403)
        self.assertTrue(Machine.objects.filter(pk=machine.pk).exists())

    def test_activity_categories_and_csv_export_are_authorized_and_safe(self):
        self.as_admin()
        login = AuditEvent.objects.create(
            event_type=AuditEvent.EventType.LOGIN,
            username='=HYPERLINK("https://example.invalid")',
            outcome="success",
            details={"action": "login", "password": "secret"},
        )
        AuditEvent.objects.create(
            event_type=AuditEvent.EventType.ADMIN_CHANGE,
            username="admin",
            outcome="success",
            details={"action": "user_created"},
        )

        filtered = self.client.get("/api/admin/activity/?category=login")
        self.assertEqual(filtered.status_code, 200)
        self.assertTrue(all(event["event_type"] == "login" for event in filtered.json()["results"]))
        csv_response = self.client.get("/api/admin/activity/export/?category=login")
        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn(',"\'=HYPERLINK', csv_response.content.decode())
        self.assertNotIn("secret", csv_response.content.decode())
        self.assertNotIn(',"=HYPERLINK', csv_response.content.decode())

        self.as_staff()
        denied = self.client.get("/api/admin/activity/export/?category=login")
        self.assertEqual(denied.status_code, 403)

    def test_activity_pagination_is_capped_stable_and_invalid_pages_are_handled(self):
        self.as_admin()
        events = AuditEvent.objects.bulk_create(
            [
                AuditEvent(
                    event_type=AuditEvent.EventType.LOGIN,
                    username=f"staff-{index}",
                )
                for index in range(104)
            ]
        )
        AuditEvent.objects.filter(pk__in=[event.pk for event in events]).update(
            created_at=AuditEvent.objects.order_by("-created_at").first().created_at
        )

        first = self.client.get("/api/admin/activity/?category=login&page=1")
        second = self.client.get("/api/admin/activity/?category=login&page=2")
        third = self.client.get("/api/admin/activity/?category=login&page=3")
        beyond_end = self.client.get("/api/admin/activity/?category=login&page=99")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.json()["results"]), 50)
        self.assertEqual((first.json()["page"], first.json()["total_pages"]), (1, 3))
        self.assertEqual(len(second.json()["results"]), 50)
        self.assertEqual(second.json()["page"], 2)
        self.assertEqual(len(third.json()["results"]), 4)
        self.assertEqual(third.json()["page"], 3)
        self.assertEqual(beyond_end.json()["page"], 3)
        first_ids = {event["id"] for event in first.json()["results"]}
        second_ids = {event["id"] for event in second.json()["results"]}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(
            self.client.get("/api/admin/activity/?page=invalid").status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/admin/activity/?page=0").status_code,
            400,
        )

    def test_activity_all_category_handles_uuid_viewing_session_ids(self):
        self.as_admin()
        AuditEvent.objects.create(
            event_type=AuditEvent.EventType.ADMIN_CHANGE,
            username="admin",
        )
        ViewingSession.objects.create(user=self.admin, study_id="test-study")

        response = self.client.get("/api/admin/activity/?category=all&page=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 2)
        self.assertEqual(
            {event["event_type"] for event in response.json()["results"]},
            {AuditEvent.EventType.ADMIN_CHANGE, AuditEvent.EventType.VIEWING},
        )

    def test_activity_others_filter_includes_non_login_and_non_viewing_types(self):
        self.as_admin()
        for event_type in (
            AuditEvent.EventType.LOGIN,
            AuditEvent.EventType.VIEWING,
            AuditEvent.EventType.PASSWORD_RESET,
            AuditEvent.EventType.MACHINE_CONFIGURATION,
            AuditEvent.EventType.DICOM_IMPORT,
        ):
            AuditEvent.objects.create(event_type=event_type)

        others = self.client.get("/api/admin/activity/?category=others")
        viewing = self.client.get("/api/admin/activity/?category=viewing")
        all_events = self.client.get("/api/admin/activity/?category=all")
        export_events = self.client.get("/api/admin/activity/?category=export")

        self.assertEqual(
            {event["event_type"] for event in others.json()["results"]},
            {
                AuditEvent.EventType.PASSWORD_RESET,
                AuditEvent.EventType.MACHINE_CONFIGURATION,
                AuditEvent.EventType.DICOM_IMPORT,
            },
        )
        self.assertEqual(
            {event["event_type"] for event in viewing.json()["results"]},
            {AuditEvent.EventType.VIEWING},
        )
        self.assertEqual(len(all_events.json()["results"]), 5)
        self.assertEqual(export_events.json()["results"], [])

        self.as_staff()
        self.assertEqual(
            self.client.get("/api/admin/activity/?category=others").status_code,
            403,
        )

    def test_csv_export_keeps_complete_filter_scope_across_pages(self):
        self.as_admin()
        AuditEvent.objects.bulk_create(
            [
                AuditEvent(
                    event_type=AuditEvent.EventType.LOGIN,
                    username=f"login-{index}",
                )
                for index in range(104)
            ]
        )

        visible_page = self.client.get("/api/admin/activity/?category=login&page=2")
        export = self.client.get("/api/admin/activity/export/?category=login")

        self.assertEqual(len(visible_page.json()["results"]), 50)
        self.assertEqual(
            len(export.content.decode("utf-8").splitlines()),
            105,
        )

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

        with patch.object(OrthancService, "find_instances_by_sop_uid") as lookup:
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
            "find_instances_by_sop_uid",
            return_value=["existing-instance"],
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
            patch.object(OrthancService, "find_instances_by_sop_uid", return_value=[]),
            patch.object(
                OrthancService,
                "store_dicom",
                return_value={"ID": "new-instance", "Status": "Success"},
            ) as store,
            patch.object(
                OrthancService,
                "get_instance",
                return_value={"ID": "new-instance", "ParentSeries": "series-1"},
            ),
            patch.object(
                OrthancService,
                "get_series_resource",
                return_value={"ID": "series-1", "ParentStudy": "study-1"},
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
                "find_instances_by_sop_uid",
                return_value=["existing-instance"],
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
        with patch.object(OrthancService, "find_instances_by_sop_uid", return_value=[]):
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
            patch.object(OrthancService, "find_instances_by_sop_uid", return_value=[]),
            patch.object(
                OrthancService,
                "store_dicom",
                return_value={"ID": "new-instance", "Status": "Success"},
            ) as store,
            patch.object(
                OrthancService,
                "get_instance",
                return_value={"ID": "new-instance", "ParentSeries": "series-1"},
            ),
            patch.object(
                OrthancService,
                "get_series_resource",
                return_value={"ID": "series-1", "ParentStudy": "study-1"},
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
        existing = "existing-instance"
        with (
            patch.object(OrthancService, "find_instances_by_sop_uid", return_value=[existing]),
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
                return_value={"ID": "replacement-instance", "ParentSeries": "series-1"},
            ),
            patch.object(
                OrthancService,
                "get_series_resource",
                return_value={"ID": "series-1", "ParentStudy": "study-1"},
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
