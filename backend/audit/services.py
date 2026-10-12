"""Helpers for writing privacy-conscious operational audit records."""
from audit.models import AuditEvent


def record_event(event_type, *, user=None, request=None, outcome="success", details=None):
    source_ip = None
    if request is not None:
        source_ip = request.META.get("REMOTE_ADDR")
    return AuditEvent.objects.create(
        event_type=event_type,
        outcome=outcome,
        user=user,
        username=getattr(user, "get_username", lambda: "")(),
        source_ip=source_ip or None,
        details=details or {},
    )
