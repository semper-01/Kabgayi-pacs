"""Tests for the StudySearchService business layer (Orthanc faked)."""
from django.test import SimpleTestCase

from studies.services import StudySearchService


def _study(rid, study_date="20160330", accession="", description="", name="Anonymized^^"):
    return {
        "ID": rid,
        "PatientMainDicomTags": {"PatientName": name, "PatientID": "0"},
        "MainDicomTags": {
            "AccessionNumber": accession,
            "StudyInstanceUID": "1.2.3." + rid,
            "StudyDate": study_date,
            "StudyDescription": description,
        },
    }


class FakeOrthanc:
    """Stand-in Orthanc client capturing calls and serving canned studies."""

    def __init__(self, studies, modalities=None, series=None):
        self.studies = studies
        self.modalities = modalities or {}
        self.find_filters = []
        self.modality_calls = []

    def find_studies(self, filters):
        self.find_filters.append(filters)
        return list(self.studies)

    def get_study_modalities(self, study_id):
        self.modality_calls.append(study_id)
        return list(self.modalities.get(study_id, []))


class StudySearchServiceTests(SimpleTestCase):
    def test_no_filter_orders_most_recent_first(self):
        orthanc = FakeOrthanc(
            [
                _study("old", study_date="20160101"),
                _study("recent", study_date="20210120"),
                _study("nodate", study_date=""),
            ]
        )
        payload = StudySearchService(orthanc=orthanc).search({}, limit=20, offset=0)

        self.assertEqual(payload["count"], 3)
        ids = [s["study_id"] for s in payload["results"]]
        self.assertEqual(ids, ["recent", "old", "nodate"])

    def test_pagination_slices_results(self):
        studies = [_study(f"s{i:02d}", study_date=f"20200101") for i in range(5)]
        orthanc = FakeOrthanc(studies, modalities={s["ID"]: ["CT"] for s in studies})

        page1 = StudySearchService(orthanc=orthanc).search({}, limit=2, offset=0)
        self.assertEqual(page1["count"], 5)
        self.assertEqual([s["study_id"] for s in page1["results"]], ["s00", "s01"])

        page2 = StudySearchService(orthanc=orthanc).search({}, limit=2, offset=2)
        self.assertEqual([s["study_id"] for s in page2["results"]], ["s02", "s03"])
        self.assertEqual(page2["count"], 5)

    def test_modality_filter_narrows_by_series(self):
        orthanc = FakeOrthanc(
            [_study("a"), _study("b")],
            modalities={"a": ["CT"], "b": ["MR"]},
        )
        payload = StudySearchService(orthanc=orthanc).search(
            {"modality": "ct"}, limit=20, offset=0
        )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["study_id"], "a")
        # The modality must have been read from the series of both candidates.
        self.assertEqual(set(orthanc.modality_calls), {"a", "b"})

    def test_modality_in_output_when_no_filter(self):
        orthanc = FakeOrthanc(
            [_study("a")],
            modalities={"a": ["CT", "MR"]},
        )
        payload = StudySearchService(orthanc=orthanc).search({}, limit=20, offset=0)

        self.assertEqual(payload["results"][0]["modality"], "CT, MR")

    def test_filters_forwarded_to_orthanc_find(self):
        orthanc = FakeOrthanc([_study("a")])
        filters = {
            "patient_name": "John",
            "patient_id": "P001",
            "accession_number": "A1",
            "study_description": "Chest",
            "study_date": "20260101",
        }
        StudySearchService(orthanc=orthanc).search(filters, limit=20, offset=0)

        self.assertEqual(orthanc.find_filters[-1], filters)

    def test_empty_results(self):
        payload = StudySearchService(orthanc=FakeOrthanc([])).search({}, limit=20, offset=0)

        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["results"], [])