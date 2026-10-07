"""Tests for the /api/studies/ endpoint behaviour (HTTP calls mocked)."""
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase
from rest_framework.test import APIClient


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._data


class StudyListApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    def _study_resource(self, sid, description="", date="20160330", uid="1.2.3"):
        return {
            "ID": sid,
            "PatientMainDicomTags": {
                "PatientName": "Anonymized^^",
                "PatientID": "PAT-0",
            },
            "MainDicomTags": {
                "StudyInstanceUID": uid,
                "StudyDate": date,
                "StudyDescription": description,
            },
        }

    @patch("core.services.orthanc.urlopen")
    def test_list_returns_clean_representations(self, mock_urlopen):
        ids = json.dumps(["sid-a", "sid-b"]).encode()
        study_a = json.dumps(self._study_resource("sid-a")).encode()
        study_b = json.dumps(self._study_resource("sid-b", description="Chest X-ray")).encode()
        mock_urlopen.side_effect = [FakeResponse(ids), FakeResponse(study_a), FakeResponse(study_b)]

        response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["study_id"], "sid-a")
        self.assertEqual(data[0]["patient_name"], "Anonymized^^")
        self.assertEqual(data[0]["patient_id"], "PAT-0")
        self.assertEqual(data[0]["study_instance_uid"], "1.2.3")
        self.assertEqual(data[0]["study_date"], "20160330")
        self.assertEqual(data[1]["study_description"], "Chest X-ray")

    @patch("core.services.orthanc.urlopen")
    def test_list_empty_when_no_studies(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(b"[]")

        response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    @patch("core.services.orthanc.urlopen")
    def test_list_returns_503_when_orthanc_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("connection refused")

        response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())

    @patch("core.services.orthanc.urlopen")
    def test_list_returns_502_when_authentication_fails(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError("http://orthanc:8042", 401, "Unauthorized", {}, None)

        response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertIn("error", body)
        self.assertNotIn("password", json.dumps(body).lower())
        self.assertNotIn("orthanc:admin", json.dumps(body).lower())

    @patch("core.services.orthanc.urlopen")
    def test_list_returns_502_on_http_server_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError("http://orthanc:8042", 500, "Error", {}, None)

        response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 502)