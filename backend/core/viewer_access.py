"""Short-lived authorization grants for the nginx DICOMweb gateway."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import HttpResponse
from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

VIEWER_GRANT_COOKIE = "pacs_viewer_grant"
VIEWER_GRANT_SALT = "kabgayi-pacs.dicomweb-viewer.v1"
VIEWER_GRANT_PURPOSE = "dicomweb-viewer"
VIEWER_GRANT_MAX_AGE_SECONDS = 300


@api_view(["POST"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def issue_viewer_grant(request):
    grant = signing.dumps(
        {
            "purpose": VIEWER_GRANT_PURPOSE,
            "user_id": str(request.user.pk),
        },
        salt=VIEWER_GRANT_SALT,
        compress=True,
    )
    response = Response({"expires_in": VIEWER_GRANT_MAX_AGE_SECONDS})
    response.set_cookie(
        VIEWER_GRANT_COOKIE,
        grant,
        max_age=VIEWER_GRANT_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.VIEWER_GRANT_COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["POST"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def revoke_viewer_grant(request):
    response = Response({"revoked": True})
    response.delete_cookie(
        VIEWER_GRANT_COOKIE,
        path="/",
        samesite="Lax",
    )
    response["Cache-Control"] = "private, no-store"
    return response


def authorize_dicomweb_request(request):
    grant = request.COOKIES.get(VIEWER_GRANT_COOKIE)
    if not grant:
        return HttpResponse(status=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = signing.loads(
            grant,
            salt=VIEWER_GRANT_SALT,
            max_age=VIEWER_GRANT_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return HttpResponse(status=status.HTTP_401_UNAUTHORIZED)

    if (
        not isinstance(payload, dict)
        or payload.get("purpose") != VIEWER_GRANT_PURPOSE
        or not payload.get("user_id")
    ):
        return HttpResponse(status=status.HTTP_401_UNAUTHORIZED)

    user_is_active = get_user_model().objects.filter(
        pk=payload["user_id"],
        is_active=True,
    ).exists()
    if not user_is_active:
        return HttpResponse(status=status.HTTP_401_UNAUTHORIZED)

    response = HttpResponse(status=status.HTTP_204_NO_CONTENT)
    response["Cache-Control"] = "private, no-store"
    return response
