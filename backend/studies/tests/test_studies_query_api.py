"""Tests for /api/studies/ filter validation, forwarding and pagination."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from core.services.orthanc import OrthancService

from .test_studies_api import _study


class _FakeFinder:
    """Records find_studies calls and returns canned study resources."""

    def __init__(self, studies):
        self.studies = studies
        self.calls = []

    def __call__(self, filters):
        self.calls.append(filters)
        return list(self.studies)


class StudyQueryApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=get_user_model()(username="staff"))

    def _patch(self, studies=(), modalities=None):
        finder = _FakeFinder(studies)
        patcher_find = patch.object(OrthancService, "find_studies", new=finder)
        patcher_mod = patch.object(
            OrthancService,
            "get_study_modalities",
            side_effect=(lambda sid: modalities.get(sid, []))
            if modalities is not None
            else (lambda sid: []),
        )
        patcher_find.start()
        patcher_mod.start()
        self.addCleanup(patcher_find.stop)
        self.addCleanup(patcher_mod.stop)
        return finder

    # --- filter forwarding ---
    def test_patient_name_filter_forwarded(self):
        finder = self._patch(studies=[])
        self.client.get("/api/studies/?patient_name=John")
        self.assertEqual(finder.calls[-1], {"patient_name": "John"})

    def test_patient_id_filter_forwarded(self):
        finder = self._patch(studies=[])
        self.client.get("/api/studies/?patient_id=P001")
        self.assertEqual(finder.calls[-1], {"patient_id": "P001"})

    def test_accession_number_filter_forwarded(self):
        finder = self._patch(studies=[])
        self.client.get("/api/studies/?accession_number=AC-1")
        self.assertEqual(finder.calls[-1], {"accession_number": "AC-1"})

    def test_study_description_filter_forwarded(self):
        finder = self._patch(studies=[])
        self.client.get("/api/studies/?study_description=Chest")
        self.assertEqual(finder.calls[-1], {"study_description": "Chest"})

    def test_study_date_normalized_and_forwarded(self):
        finder = self._patch(studies=[])
        resp = self.client.get("/api/studies/?study_date=2026-10-07")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(finder.calls[-1], {"study_date": "20261007"})

    def test_combined_filters_forwarded(self):
        finder = self._patch(studies=[])
        self.client.get("/api/studies/?patient_id=P001&modality=CT&study_date=2026-10-07")
        # modality is handled at the series level, not in the find Query, but is
        # still passed through the service filters dict.
        self.assertEqual(
            finder.calls[-1],
            {"patient_id": "P001", "modality": "CT", "study_date": "20261007"},
        )

    def test_modality_filter_uses_series(self):
        self._patch(
            studies=[_study("ct-study"), _study("mr-study")],
            modalities={"ct-study": ["CT"], "mr-study": ["MR"]},
        )
        resp = self.client.get("/api/studies/?modality=CT")

        self.assertEqual(resp.status_code, 200)
        ids = [s["study_id"] for s in resp.json()["results"]]
        self.assertEqual(ids, ["ct-study"])
# --- validation ---
    def test_unknown_parameter_returns_400(self):
        self._patch(studies=[])
        resp = self.client.get("/api/studies/?bogus=1")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("bogus", resp.json()["error"])

    def test_malformed_date_returns_400(self):
        self._patch(studies=[])
        for bad in ("10-07-2026", "2026/10/07", "not-a-date", "20261007"):
            resp = self.client.get(f"/api/studies/?study_date={bad}")
            self.assertEqual(resp.status_code, 400, msg=f"study_date={bad}")
            self.assertIn("study_date", resp.json()["error"])

    def test_invalid_limit_returns_400(self):
        self._patch(studies=[])
        for bad in ("abc", "-1", "0"):
            resp = self.client.get(f"/api/studies/?limit={bad}")
            self.assertEqual(resp.status_code, 400, msg=f"limit={bad}")

    def test_invalid_offset_returns_400(self):
        self._patch(studies=[])
        for bad in ("abc", "-5"):
            resp = self.client.get(f"/api/studies/?offset={bad}")
            self.assertEqual(resp.status_code, 400, msg=f"offset={bad}")

    def test_limit_is_capped(self):
        self._patch(studies=[_study(str(i)) for i in range(3)])
        # limit > MAX_LIMIT (100) is clamped; a huge limit is not a 400.
        resp = self.client.get("/api/studies/?limit=1000")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 3)

    # --- pagination metadata ---
    def test_pagination_metadata(self):
        studies = [_study(f"s{i}") for i in range(5)]
        self._patch(studies=studies, modalities={s["ID"]: ["CT"] for s in studies})

        page1 = self.client.get("/api/studies/?limit=2&offset=0")
        data = page1.json()
        self.assertEqual(data["count"], 5)
        self.assertIsNone(data["previous"])
        self.assertEqual(len(data["results"]), 2)
        self.assertIn("limit=2", data["next"])
        self.assertIn("offset=2", data["next"])

        page2 = self.client.get("/api/studies/?limit=2&offset=2")
        self.assertIsNotNone(page2.json()["previous"])
        self.assertIn("offset=0", page2.json()["previous"])

    def test_empty_results_returns_200(self):
        self._patch(studies=[])
        resp = self.client.get("/api/studies/?patient_id=NOPE")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)
        self.assertEqual(resp.json()["results"], [])