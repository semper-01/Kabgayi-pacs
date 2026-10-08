"""Authenticated API views for study viewing-session status."""
import re
from collections.abc import Mapping
from uuid import UUID

from django.utils import timezone
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
    OrthancService,
    OrthancUnavailableError,
)

from .models import ViewingSession
from .status import HEARTBEAT_INTERVAL_SECONDS, close_stale_sessions

RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_STATUS_STUDY_IDS = 100


@api_view(["POST"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def status_open(request):
    study_id = request.data.get("study_id") if isinstance(request.data, Mapping) else None
    if not isinstance(study_id, str) or not RESOURCE_ID_PATTERN.fullmatch(study_id):
        return Response(
            {"error": "A valid study_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        study = OrthancService().get_study(study_id)
    except OrthancNotFoundError:
        return Response(
            {"error": "The requested study was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except OrthancUnavailableError:
        return _orthanc_error(status.HTTP_503_SERVICE_UNAVAILABLE)
    except (
        OrthancAuthenticationError,
        OrthancHttpError,
        OrthancProtocolError,
    ):
        return _orthanc_error(status.HTTP_502_BAD_GATEWAY)
    if not isinstance(study, dict) or study.get("ID") != study_id:
        return _orthanc_error(status.HTTP_502_BAD_GATEWAY)

    now = timezone.now()
    close_stale_sessions(now)
    session = ViewingSession.objects.create(
        study_id=study_id,
        user=request.user,
        opened_at=now,
        last_heartbeat_at=now,
    )
    return Response(
        {
            "session_id": str(session.id),
            "study_id": session.study_id,
            "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def status_heartbeat(request):
    session_id = _parse_session_id(
        request.data.get("session_id") if isinstance(request.data, Mapping) else None
    )
    if session_id is None:
        return Response(
            {"error": "A valid session_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    now = timezone.now()
    close_stale_sessions(now)
    viewing_session = ViewingSession.objects.filter(
        id=session_id,
        user=request.user,
    ).first()
    if viewing_session is None:
        return Response(
            {"error": "The viewing session was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if not viewing_session.is_active:
        return Response(
            {"error": "The viewing session is no longer active."},
            status=status.HTTP_409_CONFLICT,
        )

    viewing_session.last_heartbeat_at = now
    viewing_session.save(update_fields=["last_heartbeat_at"])
    return Response(
        {
            "session_id": str(viewing_session.id),
            "last_heartbeat_at": now.isoformat(),
        }
    )


@api_view(["POST"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def status_close(request):
    session_id = _parse_session_id(
        request.data.get("session_id") if isinstance(request.data, Mapping) else None
    )
    if session_id is None:
        return Response(
            {"error": "A valid session_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    now = timezone.now()
    close_stale_sessions(now)
    viewing_session = ViewingSession.objects.filter(
        id=session_id,
        user=request.user,
    ).first()
    if viewing_session is None:
        return Response(
            {"error": "The viewing session was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if viewing_session.is_active:
        viewing_session.is_active = False
        viewing_session.closed_at = now
        viewing_session.save(update_fields=["is_active", "closed_at"])
    return Response(
        {
            "session_id": str(viewing_session.id),
            "active": False,
        }
    )


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def status_list(request):
    raw_ids = request.query_params.get("study_ids", "")
    study_ids = raw_ids.split(",") if raw_ids else []
    if (
        not study_ids
        or len(study_ids) > MAX_STATUS_STUDY_IDS
        or any(not RESOURCE_ID_PATTERN.fullmatch(study_id) for study_id in study_ids)
    ):
        return Response(
            {"error": "Provide between 1 and 100 valid comma-separated study_ids."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    now = timezone.now()
    cutoff = close_stale_sessions(now)
    being_viewed = set(
        ViewingSession.objects.filter(
            study_id__in=study_ids,
            is_active=True,
            last_heartbeat_at__gte=cutoff,
        ).values_list("study_id", flat=True)
    )
    return Response(
        {
            "results": [
                {"study_id": study_id, "being_viewed": study_id in being_viewed}
                for study_id in dict.fromkeys(study_ids)
            ]
        }
    )


def _parse_session_id(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _orthanc_error(http_status):
    return Response(
        {"error": "The image archive could not process the request."},
        status=http_status,
    )
