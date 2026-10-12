"""API views for the core application (system health)."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import api_view
from rest_framework.decorators import authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.models import AuditEvent
from audit.services import record_event
from studies.models import ViewingSession


@api_view(["GET"])
def health(request):
    """Minimal liveness check confirming the Django API is alive.

    Intentionally returns a static payload; it does not touch Orthanc or the
    database. The full PACS API is out of scope for Phase 2.
    """
    return Response({"status": "ok"})


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def auth_session(request):
    """Confirm a Basic-authenticated session and record an explicit login."""
    if not request.user.is_active:
        return Response({"error": "This account is inactive."}, status=status.HTTP_403_FORBIDDEN)
    record_event(AuditEvent.EventType.LOGIN, user=request.user, request=request)
    return Response(
        {
            "id": request.user.pk,
            "username": request.user.get_username(),
            "email": request.user.email,
            "account_type": request.user.account_type,
            "is_active": request.user.is_active,
        }
    )


def overview_counts():
    User = get_user_model()
    now = timezone.now()
    active_sessions = ViewingSession.objects.filter(
        is_active=True,
        last_heartbeat_at__gte=now - timedelta(
            seconds=settings.VIEWING_SESSION_TIMEOUT_SECONDS
        ),
    ).count()
    return {
        "users": {
            "total": User.objects.count(),
            "staff": User.objects.filter(account_type="staff").count(),
            "administrators": User.objects.filter(account_type="administrator").count(),
            "active": User.objects.filter(is_active=True).count(),
            "inactive": User.objects.filter(is_active=False).count(),
        },
        "active_viewing_sessions": active_sessions,
    }