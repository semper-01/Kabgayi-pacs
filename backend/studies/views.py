"""API views for the studies application (Orthanc-backed study listing)."""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.services.orthanc import (
    OrthancAuthenticationError,
    OrthancHttpError,
    OrthancNotFoundError,
    OrthancProtocolError,
    OrthancService,
    OrthancUnavailableError,
)

from .serializers import serialize_study


@api_view(["GET"])
def study_list(request):
    """Return the available studies as read from Orthanc.

    The browser never talks to Orthanc directly: this view calls the Orthanc
    service, which in turn calls the Orthanc REST API, and the result is
    projected into a clean JSON representation.
    """
    service = OrthancService()
    try:
        study_ids = service.get_studies()
        studies = [serialize_study(service.get_study(study_id)) for study_id in study_ids]
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
    return Response(studies)