"""
Service layer for communicating with the Orthanc PACS REST API.

Django must interact with Orthanc (the source of truth for DICOM data) through
this service -- never directly with Orthanc's on-disk storage and never by
duplicating the DICOM hierarchy into Django models. HTTP requests are
centralised here so that API views stay unaware of the transport details.

This service issues requests to Orthanc's REST API (e.g. ``/patients``,
``/studies``, ``/studies/{id}``, ``/studies/{id}/series``). Connection settings
come from Django settings, which read them from the environment.
"""
import base64
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

# Maps the API-facing study filter names to the DICOM tags sent to Orthanc's
# advanced-find ``Query``. Modality is intentionally excluded: it is a
# series-level tag and cannot be matched at the study level via /tools/find.
STUDY_FIND_QUERY_TAGS = {
    "patient_name": "PatientName",
    "patient_id": "PatientID",
    "accession_number": "AccessionNumber",
    "study_date": "StudyDate",
    "study_description": "StudyDescription",
}


class OrthancError(Exception):
    """Base class for all Orthanc integration errors."""


class OrthancUnavailableError(OrthancError):
    """Orthanc could not be reached (down, unreachable, or timed out)."""


class OrthancAuthenticationError(OrthancError):
    """Orthanc rejected our credentials (HTTP 401/403)."""


class OrthancNotFoundError(OrthancError):
    """The requested Orthanc resource does not exist (HTTP 404)."""


class OrthancHttpError(OrthancError):
    """Orthanc returned a non-success HTTP status code."""


class OrthancProtocolError(OrthancError):
    """Orthanc returned an unexpected/malformed payload."""


class OrthancService:
    """Focused client for the Orthanc REST API."""

    def __init__(self, base_url=None, username=None, password=None, timeout=None):
        # Allow overriding connection settings per-instance (used by tests),
        # falling back to the values configured in Django settings.
        self.base_url = (base_url or settings.ORTHANC_URL).rstrip("/")
        self.username = settings.ORTHANC_USERNAME if username is None else username
        self.password = settings.ORTHANC_PASSWORD if password is None else password
        self.timeout = settings.ORTHANC_TIMEOUT if timeout is None else timeout

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get_patients(self):
        """Return the list of Orthanc patient resource IDs."""
        return self._request_json("/patients", method="GET")

    def get_studies(self):
        """Return the list of Orthanc study resource IDs."""
        return self._request_json("/studies", method="GET")

    def get_study(self, study_id):
        """Return the full Orthanc study resource for a study ID."""
        return self._request_json(f"/studies/{quote(study_id, safe='')}", method="GET")

    def get_patient(self, patient_id):
        """Return the Orthanc patient resource for a patient ID."""
        return self._request_json(f"/patients/{quote(patient_id, safe='')}", method="GET")

    def get_series(self, study_id):
        """Return the Orthanc series resources belonging to a study ID.

        Orthanc exposes series as ``/studies/{study_id}/series``; any given
        study resource also lists ``Series`` references. We rely on the
        dedicated series endpoint (present in the installed Orthanc 1.13).
        """
        return self._request_json(
            f"/studies/{quote(study_id, safe='')}/series", method="GET"
        )

    def get_study_instances(self, study_id):
        """Return instance IDs listed in the study's Orthanc series resources."""
        series_resources = self.get_series(study_id)
        if not isinstance(series_resources, list):
            raise OrthancProtocolError("Orthanc returned an unexpected response.")
        instances = []
        for series in series_resources:
            if not isinstance(series, dict) or not isinstance(series.get("Instances"), list):
                raise OrthancProtocolError("Orthanc returned an unexpected response.")
            instances.extend(series["Instances"])
        if any(not isinstance(instance_id, str) for instance_id in instances):
            raise OrthancProtocolError("Orthanc returned an unexpected response.")
        return instances

    def find_studies(self, filters=None):
        """Find studies matching study-level DICOM filters (Orthanc advanced find).

        ``filters`` maps the API filter names to values. Only study-level DICOM
        tags are sent in the Orthanc ``Query`` (e.g. ``PatientName``,
        ``PatientID``, ``AccessionNumber``, ``StudyDate``, ``StudyDescription``).
        Matching is performed by Orthanc, not by Django.

        NOTE: ``Modality`` is a series-level tag and cannot be matched at the
        study level via ``/tools/find`` (confirmed against the running Orthanc);
        callers that need modality filtering/projection must inspect each
        study's series via :meth:`get_study_modalities`.

        Returns the list of expanded study resources (as returned by Orthanc).
        """
        filters = filters or {}
        query = {}
        for api_key in (
            "patient_name",
            "patient_id",
            "accession_number",
            "study_date",
            "study_description",
        ):
            value = (filters.get(api_key) or "").strip()
            if value:
                query[STUDY_FIND_QUERY_TAGS[api_key]] = value

        payload = {
            "Level": "Study",
            "Query": query,
            "Expand": True,
        }
        result = self._request_json("/tools/find", method="POST", body=payload)
        # Orthanc returns a plain JSON array here; tolerate a {value:[...]} wrap.
        if isinstance(result, dict) and isinstance(result.get("value"), list):
            return result["value"]
        if isinstance(result, list):
            return result
        return []

    def get_study_modalities(self, study_id):
        """Return the sorted unique modality tags across a study's series."""
        modalities = set()
        for series in self.get_series(study_id):
            tags = series.get("MainDicomTags", {}) or {}
            modal = (tags.get("Modality") or "").strip()
            if modal:
                modalities.add(modal)
        return sorted(modalities)

    def open_binary(self, path, headers=None):
        """Open a binary Orthanc response for streaming to an API client."""
        request_headers = dict(headers or {})
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode("utf-8")
            ).decode("ascii")
            request_headers["Authorization"] = f"Basic {token}"

        request = Request(self.base_url + path, headers=request_headers, method="GET")
        logger.debug("Orthanc GET request: %s", path)
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except (URLError, OSError) as exc:
            logger.warning("Orthanc unreachable: %s", exc)
            raise OrthancUnavailableError(
                "Unable to reach the Orthanc server."
            ) from exc

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def _request_json(self, path, method="GET", body=None):
        """Perform an HTTP request and return the decoded JSON payload."""
        url = self.base_url + path
        headers = {}
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

        data = json.dumps(body).encode("utf-8") if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, headers=headers, data=data, method=method)
        logger.debug("Orthanc %s request: %s", method, path)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except (URLError, OSError) as exc:
            # Covers refused connections, unknown hosts and timeouts.
            logger.warning("Orthanc unreachable: %s", exc)
            raise OrthancUnavailableError(
                "Unable to reach the Orthanc server."
            ) from exc

        try:
            return json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise OrthancProtocolError(
                "Orthanc returned an unexpected response."
            ) from exc

    @staticmethod
    def _map_http_error(exc):
        """Translate an Orthanc HTTPError into a domain-specific error."""
        code = exc.code
        if code in (401, 403):
            logger.warning("Orthanc authentication failed (HTTP %s)", code)
            return OrthancAuthenticationError(
                "Orthanc rejected the configured credentials."
            )
        if code == 404:
            return OrthancNotFoundError("The requested Orthanc resource was not found.")
        logger.warning("Orthanc returned HTTP %s", code)
        return OrthancHttpError(f"Orthanc returned HTTP {code}.")