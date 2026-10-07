"""API views for the core application (system health)."""
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def health(request):
    """Minimal liveness check confirming the Django API is alive.

    Intentionally returns a static payload; it does not touch Orthanc or the
    database. The full PACS API is out of scope for Phase 2.
    """
    return Response({"status": "ok"})