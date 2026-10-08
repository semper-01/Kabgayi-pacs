"""Viewing-session lifecycle and stale-session handling."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import ViewingSession


HEARTBEAT_INTERVAL_SECONDS = 30


def close_stale_sessions(now=None):
    """Mark sessions inactive after the configured heartbeat timeout."""
    now = now or timezone.now()
    timeout_seconds = max(1, settings.VIEWING_SESSION_TIMEOUT_SECONDS)
    cutoff = now - timedelta(seconds=timeout_seconds)
    ViewingSession.objects.filter(
        is_active=True,
        last_heartbeat_at__lt=cutoff,
    ).update(is_active=False, closed_at=now)
    return cutoff
