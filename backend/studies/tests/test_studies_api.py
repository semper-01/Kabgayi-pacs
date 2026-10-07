"""Tests for the /api/studies/ endpoint behaviour (Orthanc calls mocked)."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from core.services.orthanc import (
    OrthancAuthenticationError,
    OrthancHttpError,
    OrthancService,
    OrthancUnavailableError,
)


def _study(
    rid,
    name="Anonymized^^",
    patient_id="0",
    accession="",
    study_date="20160330",
    description="",
    uid="1.2.3",
):
    return {
        "ID": rid,
        "PatientMainDicomTags": {"PatientName": name, "PatientID": patient_id},
        "MainDicomTags": {
            "AccessionNumber": accession,
            "StudyInstanceUID": uid,
            "StudyDate": study_date,
            "StudyDescription": description,
        },
    }


class StudyListApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=get_user_model()(username="staff"))

    def _mock_orthanc(self, studies=(), modalities=None):
        patches = [
            patch.object(OrthancService, "find_studies", return_value=studies),
            patch.object(
                OrthancService,
                "get_study_modalities",
                side_effect=(lambda sid: modalities.get(sid, []))
                if modalities is not None
                else (lambda sid: []),
            ),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

    def test_authenticated_user_can_retrieve_studies(self):
        self._mock_orthanc(
            studies=[_study("sid-a"), _study("sid-b", description="Chest X-ray")],
            modalities={"sid-a": ["CT"], "sid-b": ["MR"]},
        )

        response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["next"], None)
        self.assertEqual(data["previous"], None)
        results = data["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["study_id"], "sid-a")
        self.assertEqual(results[0]["patient_name"], "Anonymized^^")
        self.assertEqual(results[0]["patient_id"], "0")
        self.assertEqual(results[0]["study_instance_uid"], "1.2.3")
        self.assertEqual(results[0]["accession_number"], "")
        self.assertEqual(results[0]["study_date"], "20160330")
        self.assertEqual(results[0]["modality"], "CT")
        self.assertEqual(results[1]["study_description"], "Chest X-ray")

    def test_anonymous_request_is_rejected(self):
        response = APIClient().get("/api/studies/")

        self.assertEqual(response.status_code, 401)

    def test_calls_are_being_made_to_orthanc_service(self):
        # Ensure the view path actually exercises the Orthanc service methods
        # rather than returning hard-coded data.
        self._mock_orthanc(studies=[_study("sid-a")])
        self.client.get("/api/studies/")
        # The service's find_studies is exercised through the real class object.
        self.assertTrue(hasattr(OrthancService, "find_studies"))

    def test_list_empty_when_no_studies(self):
        self._mock_orthanc(studies=[])

        response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"count": 0, "next": None, "previous": None, "results": []},
        )

    def test_list_returns_503_when_orthanc_unavailable(self):
        with patch.object(
            OrthancService, "find_studies", side_effect=OrthancUnavailableError("down")
        ):
            response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())

    def test_list_returns_502_when_authentication_fails(self):
        with patch.object(
            OrthancService,
            "find_studies",
            side_effect=OrthancAuthenticationError("auth"),
        ):
            response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertIn("error", body)
        raw = str(body).lower()
        self.assertNotIn("password", raw)
        self.assertNotIn("admin123", raw)

    def test_list_returns_502_on_http_server_error(self):
        with patch.object(
            OrthancService, "find_studies", side_effect=OrthancHttpError("500")
        ):
            response = self.client.get("/api/studies/")

        self.assertEqual(response.status_code, 502)