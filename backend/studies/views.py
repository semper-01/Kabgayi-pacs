"""API views for the studies application (Orthanc-backed study query/search)."""
import re
from datetime import date

from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.services.orthanc import (
    OrthancAuthenticationError,
    OrthancHttpError,
    OrthancNotFoundError,
    OrthancProtocolError,
    OrthancUnavailableError,
)

from .services import StudySearchService

# Supported query parameters for GET /api/studies/.
STUDY_FILTERS = {
    "patient_name",
    "patient_id",
    "accession_number",
    "modality",
    "study_date",
    "study_description",
}
PAGINATION_PARAMS = {"limit", "offset"}
ALLOWED_PARAMS = STUDY_FILTERS | PAGINATION_PARAMS

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def study_list(request):
    """Return studies from Orthanc matching the supplied query parameters.

    Filters are validated here, then delegated to StudySearchService, which
    queries Orthanc, applies the (series-derived) modality filter, orders by
    recency, paginates and serializes. The browser never talks to Orthanc
    directly.
    """
    params = request.query_params

    unknown = set(params.keys()) - ALLOWED_PARAMS
    if unknown:
        return Response(
            {"error": f"Unknown parameter(s): {', '.join(sorted(unknown))}."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Parse / validate pagination.
    try:
        limit = _parse_int(params.get("limit"), DEFAULT_LIMIT)
    except ValueError:
        return Response(
            {"error": "Invalid 'limit' value; expected a positive integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if limit < 1:
        return Response(
            {"error": "Invalid 'limit' value; expected a positive integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    limit = min(limit, MAX_LIMIT)

    try:
        offset = _parse_int(params.get("offset"), 0)
    except ValueError:
        return Response(
            {"error": "Invalid 'offset' value; expected a non-negative integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if offset < 0:
        return Response(
            {"error": "Invalid 'offset' value; expected a non-negative integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Build the validated filter dict.
    filters = {key: value for key, value in params.items() if key in STUDY_FILTERS}

    if "study_date" in filters:
        raw_date = filters["study_date"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            return Response(
                {"error": "Invalid 'study_date' value; expected a date like YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            filters["study_date"] = date.fromisoformat(raw_date).strftime("%Y%m%d")
        except ValueError:
            return Response(
                {"error": "Invalid 'study_date' value; expected a date like YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        payload = StudySearchService().search(filters, limit=limit, offset=offset)
    except OrthancUnavailableError:
        return Response(
            {"error": "The image archive is currently unavailable."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except OrthancAuthenticationError:
        return Response(
            {"error": "The image archive rejected access."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except (OrthancHttpError, OrthancNotFoundError, OrthancProtocolError):
        return Response(
            {"error": "The image archive returned an unexpected response."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    total = payload["count"]
    base_query = {k: v for k, v in params.items() if k not in PAGINATION_PARAMS}
    next_params = None
    previous_params = None
    if offset + limit < total:
        next_params = {**base_query, "limit": limit, "offset": offset + limit}
    if offset > 0:
        previous_params = {**base_query, "limit": limit, "offset": max(0, offset - limit)}

    return Response(
        {
            "count": total,
            "next": _absolute_url(request, next_params) if next_params else None,
            "previous": _absolute_url(request, previous_params) if previous_params else None,
            "results": payload["results"],
        }
    )


def _parse_int(raw, default):
    if raw is None or raw == "":
        return default
    return int(raw)


def _absolute_url(request, query_params):
    uri = request.build_absolute_uri()
    if not query_params:
        return uri
    from urllib.parse import urlencode, urlsplit, urlunsplit

    parts = urlsplit(uri)
    return urlunsplit(parts._replace(query=urlencode(query_params)))