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
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)


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
        return self._get_json("/patients")

    def get_studies(self):
        """Return the list of Orthanc study resource IDs."""
        return self._get_json("/studies")

    def get_study(self, study_id):
        """Return the full Orthanc study resource for a study ID."""
        return self._get_json(f"/studies/{study_id}")

    def get_series(self, study_id):
        """Return the Orthanc series resources belonging to a study ID.

        Orthanc exposes series as ``/studies/{study_id}/series``; any given
        study resource also lists ``Series`` references. We rely on the
        dedicated series endpoint (present in the installed Orthanc 1.13).
        """
        return self._get_json(f"/studies/{study_id}/series")

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def _get_json(self, path):
        """Perform a GET request and return the decoded JSON payload."""
        url = self.base_url + path
        headers = {}
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

        request = Request(url, headers=headers, method="GET")
        logger.debug("Orthanc request: %s", path)

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