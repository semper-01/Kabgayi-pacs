"""Business logic for study query and search.

Views stay thin: they validate request parameters and delegate to
:class:`StudySearchService`, which orchestrates Orthanc interactions, applies
the modality filter, orders results chronologically, paginates, and produces
the clean serialized representation. No DICOM data is stored by Django.
"""
from core.services.orthanc import OrthancService

from .serializers import serialize_study


def _study_sort_key(study):
    """Return a comparable key for chronological ordering (most recent first).

    Primary: (DICOM) StudyDate; secondary: StudyTime. Missing values sort last
    in a descending (most-recent-first) ordering.
    """
    tags = study.get("MainDicomTags", {}) or {}
    study_date = (tags.get("StudyDate") or "").strip()
    study_time = (tags.get("StudyTime") or "").strip()
    return (study_date, study_time)


class StudySearchService:
    """Retrieves, filters, orders, paginates and serializes Orthanc studies."""

    def __init__(self, orthanc=None):
        # Allow dependency injection (used by tests) with a default to the
        # real Orthanc client configured through settings.
        self.orthanc = orthanc or OrthancService()

    def search(self, filters, limit, offset):
        """Return ordered, paginated studies matching ``filters``.

        ``filters`` is an already-validated dict of API filter names to values.
        Returns ``{"count": int, "results": [serialized study, ...]}``.
        """
        modality_filter = (filters.get("modality") or "").strip().lower()

        # 1) Study-level search is delegated to Orthanc (the source of truth).
        candidates = self.orthanc.find_studies(filters)

        # 2) Modality is a series-level tag, so when it is requested we must
        #    inspect each candidate study's series (still an Orthanc query).
        if modality_filter:
            modalities_by_id = {}
            kept = []
            for study in candidates:
                study_id = study.get("ID", "")
                modalities = self.orthanc.get_study_modalities(study_id)
                modalities_by_id[study_id] = modalities
                if modality_filter in {m.lower() for m in modalities}:
                    kept.append(study)
        else:
            modalities_by_id = {}
            kept = candidates

        # 3) Order chronologically (most recent first) in the serialization
        #    layer because Orthanc's SortBy is unreliable here (verified).
        kept.sort(key=_study_sort_key, reverse=True)

        total = len(kept)
        page = kept[offset: offset + limit]

        # 4) Fetch per-study series modalities only for the page we return
        #    (unless we already computed them for the modality filter).
        if not modality_filter:
            for study in page:
                modalities_by_id[study.get("ID", "")] = self.orthanc.get_study_modalities(
                    study.get("ID", "")
                )

        results = [
            serialize_study(study, modalities=modalities_by_id.get(study.get("ID", "")))
            for study in page
        ]
        return {"count": total, "results": results}