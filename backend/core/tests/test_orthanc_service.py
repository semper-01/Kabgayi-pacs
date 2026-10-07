"""Tests for the Orthanc integration service."""
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase

from core.services.orthanc import (
    OrthancAuthenticationError,
    OrthancHttpError,
    OrthancNotFoundError,
    OrthancProtocolError,
    OrthancService,
    OrthancUnavailableError,
)


class FakeResponse:
    """Minimal stand-in for urllib's HTTPResponse used with a context manager."""

    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._data


def http_error(code, url="http://orthanc:8042/"):
    return HTTPError(url, code, "error", {}, None)


class OrthancServiceTests(SimpleTestCase):
    def make_service(self, **overrides):
        settings = {"base_url": "http://orthanc:8042", "username": "user", "password": "pass"}
        settings.update(overrides)
        return OrthancService(**settings)

    @patch("core.services.orthanc.urlopen")
    def test_get_studies_returns_ids_and_sends_auth(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(json.dumps(["sid-1", "sid-2"]).encode())
        service = self.make_service()

        self.assertEqual(service.get_studies(), ["sid-1", "sid-2"])
        request = mock_urlopen.call_args.args[0]
        auth = request.get_header("Authorization")
        self.assertTrue(isinstance(auth, str) and auth.startswith("Basic "))

    @patch("core.services.orthanc.urlopen")
    def test_no_auth_header_when_credentials_empty(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(b"[]")
        service = self.make_service(username="", password="")

        service.get_studies()
        request = mock_urlopen.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))

    @patch("core.services.orthanc.urlopen")
    def test_get_patients_returns_ids(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(json.dumps(["pat-1"]).encode())
        self.assertEqual(self.make_service().get_patients(), ["pat-1"])
        self.assertEqual(mock_urlopen.call_args.args[0].full_url, "http://orthanc:8042/patients")

    @patch("core.services.orthanc.urlopen")
    def test_get_study_returns_resource(self, mock_urlopen):
        resource = {"ID": "abc", "MainDicomTags": {"StudyDate": "20200101"}}
        mock_urlopen.return_value = FakeResponse(json.dumps(resource).encode())

        self.assertEqual(self.make_service().get_study("abc"), resource)
        self.assertEqual(
            mock_urlopen.call_args.args[0].full_url,
            "http://orthanc:8042/studies/abc",
        )

    @patch("core.services.orthanc.urlopen")
    def test_get_series_uses_study_series_endpoint(self, mock_urlopen):
        series = [{"ID": "s1", "ParentStudy": "abc"}]
        mock_urlopen.return_value = FakeResponse(json.dumps(series).encode())

        self.assertEqual(self.make_service().get_series("abc"), series)
        self.assertEqual(
            mock_urlopen.call_args.args[0].full_url,
            "http://orthanc:8042/studies/abc/series",
        )

    @patch("core.services.orthanc.urlopen")
    def test_connection_failure_raises_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("connection refused")
        with self.assertRaises(OrthancUnavailableError):
            self.make_service().get_studies()

    @patch("core.services.orthanc.urlopen")
    def test_timeout_raises_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError("timed out")
        with self.assertRaises(OrthancUnavailableError):
            self.make_service().get_studies()

    @patch("core.services.orthanc.urlopen")
    def test_auth_failure_raises_authentication_error(self, mock_urlopen):
        mock_urlopen.side_effect = http_error(401)
        with self.assertRaises(OrthancAuthenticationError):
            self.make_service().get_studies()

    @patch("core.services.orthanc.urlopen")
    def test_forbidden_raises_authentication_error(self, mock_urlopen):
        mock_urlopen.side_effect = http_error(403)
        with self.assertRaises(OrthancAuthenticationError):
            self.make_service().get_studies()

    @patch("core.services.orthanc.urlopen")
    def test_not_found_raises_not_found_error(self, mock_urlopen):
        mock_urlopen.side_effect = http_error(404)
        with self.assertRaises(OrthancNotFoundError):
            self.make_service().get_study("missing")

    @patch("core.services.orthanc.urlopen")
    def test_server_error_raises_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = http_error(500)
        with self.assertRaises(OrthancHttpError):
            self.make_service().get_studies()

    @patch("core.services.orthanc.urlopen")
    def test_malformed_json_raises_protocol_error(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(b"not-json")
        with self.assertRaises(OrthancProtocolError):
            self.make_service().get_studies()

    @patch("core.services.orthanc.urlopen")
    def test_find_studies_posts_to_tools_find(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(json.dumps([{"ID": "s1"}, {"ID": "s2"}]).encode())
        service = self.make_service()

        result = service.find_studies({"patient_name": "John"})

        self.assertEqual([s["ID"] for s in result], ["s1", "s2"])
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://orthanc:8042/tools/find")
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data)
        self.assertEqual(body["Level"], "Study")
        self.assertEqual(body["Expand"], True)
        self.assertEqual(body["Query"], {"PatientName": "John"})

    @patch("core.services.orthanc.urlopen")
    def test_find_studies_maps_filters_to_dicom_tags(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(b"[]")
        service = self.make_service()

        service.find_studies(
            {
                "patient_name": "John",
                "patient_id": "P1",
                "accession_number": "A1",
                "study_date": "20260509",
                "study_description": "Chest",
            }
        )
        body = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(
            body["Query"],
            {
                "PatientName": "John",
                "PatientID": "P1",
                "AccessionNumber": "A1",
                "StudyDate": "20260509",
                "StudyDescription": "Chest",
            },
        )

    @patch("core.services.orthanc.urlopen")
    def test_find_studies_excludes_modality_from_query(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(b"[]")
        service = self.make_service()

        service.find_studies({"patient_id": "P1", "modality": "CT"})
        body = json.loads(mock_urlopen.call_args.args[0].data)
        # Modality is a series tag; it must not be sent in the study-level Query.
        self.assertEqual(body["Query"], {"PatientID": "P1"})

    @patch("core.services.orthanc.urlopen")
    def test_get_study_modalities_aggregates_series(self, mock_urlopen):
        series = [
            {"MainDicomTags": {"Modality": "CT"}},
            {"MainDicomTags": {"Modality": "CT"}},
            {"MainDicomTags": {"Modality": "MR"}},
            {"MainDicomTags": {}},
        ]
        mock_urlopen.return_value = FakeResponse(json.dumps(series).encode())
        service = self.make_service()

        self.assertEqual(service.get_study_modalities("abc"), ["CT", "MR"])
        self.assertEqual(
            mock_urlopen.call_args.args[0].full_url,
            "http://orthanc:8042/studies/abc/series",
        )