"""Tests for authenticated Orthanc-backed study exports."""
import io
import zipfile
from email.message import Message
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from core.services.orthanc import (
    OrthancAuthenticationError,
    OrthancNotFoundError,
    OrthancUnavailableError,
    OrthancService,
)


STUDY = {
    "ID": "study-1",
    "ParentPatient": "patient-1",
    "PatientMainDicomTags": {"PatientName": "Sample^Patient", "PatientID": "P-1"},
    "MainDicomTags": {
        "StudyInstanceUID": "1.2.3.4",
        "AccessionNumber": "A-1",
        "StudyDate": "20261007",
        "StudyDescription": "Chest study",
    },
}


class BinaryResponse:
    def __init__(self, data, content_type):
        self.data = io.BytesIO(data)
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def read(self, size=-1):
        return self.data.read(size)

    def close(self):
        self.data.close()


class FailingBinaryResponse(BinaryResponse):
    def read(self, _size=-1):
        raise OSError("internal transport detail")


class StudyExportApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=get_user_model()(username="staff"))

    def _metadata_mocks(self):
        return (
            patch.object(OrthancService, "get_study", return_value=STUDY),
            patch.object(OrthancService, "get_study_modalities", return_value=["CT"]),
        )

    def test_anonymous_export_is_rejected(self):
        response = APIClient().get("/api/studies/study-1/export/?format=csv")
        self.assertEqual(response.status_code, 401)

    @patch.object(OrthancService, "open_binary")
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_dicom_export_streams_orthanc_archive(self, _mock_study, mock_open_binary):
        mock_open_binary.return_value = BinaryResponse(b"PK\x03\x04dicom", "application/zip")

        response = self.client.get("/api/studies/study-1/export/?format=dicom")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn('attachment; filename="study-study-1.zip"', response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"PK\x03\x04dicom")
        self.assertEqual(
            mock_open_binary.call_args.args[0],
            "/studies/study-1/archive",
        )

    @patch.object(OrthancService, "open_binary")
    @patch.object(OrthancService, "get_study_instances", return_value=["instance-1", "instance-2"])
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_png_export_contains_all_rendered_images(
        self, _mock_study, _mock_instances, mock_open_binary
    ):
        mock_open_binary.side_effect = [
            BinaryResponse(b"\x89PNG\r\n\x1a\none", "image/png"),
            BinaryResponse(b"\x89PNG\r\n\x1a\ntwo", "image/png"),
        ]

        response = self.client.get("/api/studies/study-1/export/?format=png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertEqual(archive.namelist(), ["instance_000001.png", "instance_000002.png"])
            self.assertEqual(archive.read("instance_000001.png"), b"\x89PNG\r\n\x1a\none")
        self.assertEqual(
            mock_open_binary.call_args_list[0].kwargs["headers"],
            {"Accept": "image/png"},
        )

    @patch.object(OrthancService, "open_binary")
    @patch.object(OrthancService, "get_study_instances", return_value=["instance-1"])
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_jpeg_export_requests_jpeg_and_packages_it(
        self, _mock_study, _mock_instances, mock_open_binary
    ):
        mock_open_binary.return_value = BinaryResponse(b"\xff\xd8jpeg", "image/jpeg")

        response = self.client.get("/api/studies/study-1/export/?format=jpeg")

        self.assertEqual(response.status_code, 200)
        self.assertIn("study-study-1-jpeg.zip", response["Content-Disposition"])
        self.assertEqual(mock_open_binary.call_args.kwargs["headers"], {"Accept": "image/jpeg"})
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertEqual(archive.read("instance_000001.jpg"), b"\xff\xd8jpeg")

    @patch.object(OrthancService, "get_study_modalities", return_value=["CT"])
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_csv_export_contains_projected_metadata_and_download_headers(
        self, _mock_study, _mock_modalities
    ):
        response = self.client.get("/api/studies/study-1/export/?format=csv")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn('attachment; filename="study-study-1.csv"', response["Content-Disposition"])
        self.assertIn("study_id,patient_name,patient_id", response.content.decode())
        self.assertIn("study-1,Sample^Patient,P-1", response.content.decode())
        self.assertNotIn("ParentPatient", response.content.decode())

    @patch.object(OrthancService, "get_study_modalities", return_value=[])
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_csv_export_neutralizes_spreadsheet_formulas(self, _mock_study, _mock_modalities):
        malicious_study = dict(STUDY)
        malicious_study["MainDicomTags"] = dict(STUDY["MainDicomTags"], StudyDescription="=1+1")
        with patch.object(OrthancService, "get_study", return_value=malicious_study):
            response = self.client.get("/api/studies/study-1/export/?format=csv")

        self.assertIn("'=1+1", response.content.decode())

    @patch.object(OrthancService, "get_study_modalities", return_value=["CT"])
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_pdf_export_contains_metadata_only(self, _mock_study, _mock_modalities):
        response = self.client.get("/api/studies/study-1/export/?format=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="study-study-1.pdf"', response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"Study information summary", response.content)
        self.assertIn(b"Patient ID: P-1", response.content)
        self.assertIn(b"not a clinical report", response.content.lower())

    def test_unsupported_format_returns_400_without_orthanc_call(self):
        with patch.object(OrthancService, "get_study") as mock_study:
            response = self.client.get("/api/studies/study-1/export/?format=exe")

        self.assertEqual(response.status_code, 400)
        mock_study.assert_not_called()

    def test_export_rejects_path_traversal(self):
        with patch.object(OrthancService, "get_study") as mock_study:
            response = self.client.get("/api/studies/../patients/export/?format=csv")

        self.assertEqual(response.status_code, 404)
        mock_study.assert_not_called()

    @patch.object(OrthancService, "get_study", side_effect=OrthancNotFoundError("secret details"))
    def test_unknown_study_returns_404_without_leaking_error(self, _mock_study):
        response = self.client.get("/api/studies/missing/export/?format=pdf")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("secret", response.content.decode())

    @patch.object(OrthancService, "get_study", side_effect=OrthancUnavailableError("secret"))
    def test_orthanc_unavailable_returns_safe_503(self, _mock_study):
        response = self.client.get("/api/studies/study-1/export/?format=csv")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.content.decode())

    @patch.object(
        OrthancService,
        "get_study",
        side_effect=OrthancAuthenticationError("password=do-not-leak"),
    )
    def test_orthanc_authentication_details_are_never_exposed(self, _mock_study):
        response = self.client.get("/api/studies/study-1/export/?format=pdf")

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("password", response.content.decode().lower())
        self.assertNotIn("do-not-leak", response.content.decode())

    @patch.object(OrthancService, "open_binary")
    @patch.object(OrthancService, "get_study_instances", return_value=["instance-1"])
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_unexpected_render_content_type_returns_safe_502(
        self, _mock_study, _mock_instances, mock_open_binary
    ):
        mock_open_binary.return_value = BinaryResponse(b"not png", "text/html")

        response = self.client.get("/api/studies/study-1/export/?format=png")

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("not png", response.content.decode())

    @patch.object(OrthancService, "open_binary")
    @patch.object(OrthancService, "get_study_instances", return_value=["instance-1"])
    @patch.object(OrthancService, "get_study", return_value=STUDY)
    def test_render_stream_failure_returns_safe_503(
        self, _mock_study, _mock_instances, mock_open_binary
    ):
        mock_open_binary.return_value = FailingBinaryResponse(b"", "image/png")

        response = self.client.get("/api/studies/study-1/export/?format=png")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("internal transport detail", response.content.decode())

    @patch.object(OrthancService, "get_study", return_value=STUDY)
    @patch.object(OrthancService, "get_study_instances", return_value=[])
    def test_render_export_without_instances_returns_404(self, _mock_instances, _mock_study):
        response = self.client.get("/api/studies/study-1/export/?format=png")
        self.assertEqual(response.status_code, 404)
