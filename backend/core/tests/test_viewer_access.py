"""Tests for signed, purpose-limited DICOMweb viewer grants."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.viewer_access import (
    VIEWER_GRANT_COOKIE,
    VIEWER_GRANT_MAX_AGE_SECONDS,
    VIEWER_GRANT_PURPOSE,
    VIEWER_GRANT_SALT,
)


@override_settings(VIEWER_GRANT_COOKIE_SECURE=False)
class ViewerAccessGrantTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="viewer-staff",
            password="test-only-password",
        )
        self.client = APIClient()

    def test_grant_requires_an_authenticated_user(self):
        response = self.client.post("/api/viewer-access/grant/", {}, format="json")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn(VIEWER_GRANT_COOKIE, response.cookies)

    def test_authenticated_user_receives_http_only_scoped_grant_cookie(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post("/api/viewer-access/grant/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"expires_in": VIEWER_GRANT_MAX_AGE_SECONDS})
        cookie = response.cookies[VIEWER_GRANT_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        payload = signing.loads(cookie.value, salt=VIEWER_GRANT_SALT)
        self.assertEqual(payload["purpose"], VIEWER_GRANT_PURPOSE)
        self.assertEqual(payload["user_id"], str(self.user.pk))
        self.assertNotIn("password", payload)

    def test_authorizer_accepts_a_valid_grant_cookie_without_django_auth(self):
        self.client.force_authenticate(user=self.user)
        grant_response = self.client.post(
            "/api/viewer-access/grant/",
            {},
            format="json",
        )
        token = grant_response.cookies[VIEWER_GRANT_COOKIE].value
        self.client.force_authenticate(user=None)

        response = self.client.get(
            "/api/viewer-access/authorize/",
            HTTP_COOKIE=f"{VIEWER_GRANT_COOKIE}={token}",
            HTTP_ACCEPT="application/dicom+json",
        )

        self.assertEqual(response.status_code, 204)

    def test_authorizer_rejects_missing_and_tampered_grants(self):
        missing = self.client.get(
            "/api/viewer-access/authorize/",
            HTTP_ACCEPT="application/dicom+json",
        )
        self.assertEqual(missing.status_code, 401)

        self.client.cookies[VIEWER_GRANT_COOKIE] = "tampered"
        tampered = self.client.get("/api/viewer-access/authorize/")
        self.assertEqual(tampered.status_code, 401)

    def test_authorizer_rejects_expired_grants(self):
        token = signing.dumps(
            {"purpose": VIEWER_GRANT_PURPOSE, "user_id": str(self.user.pk)},
            salt=VIEWER_GRANT_SALT,
        )
        with patch("django.core.signing.time.time", return_value=1_000_000):
            token = signing.dumps(
                {"purpose": VIEWER_GRANT_PURPOSE, "user_id": str(self.user.pk)},
                salt=VIEWER_GRANT_SALT,
            )
        with patch(
            "django.core.signing.time.time",
            return_value=1_000_000 + VIEWER_GRANT_MAX_AGE_SECONDS + 1,
        ):
            response = self.client.get(
                "/api/viewer-access/authorize/",
                HTTP_COOKIE=f"{VIEWER_GRANT_COOKIE}={token}",
            )

        self.assertEqual(response.status_code, 401)

    def test_revoke_clears_grant_cookie_for_authenticated_user(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post("/api/viewer-access/revoke/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies[VIEWER_GRANT_COOKIE].value, "")

    def test_authorizer_rejects_inactive_users(self):
        token = signing.dumps(
            {"purpose": VIEWER_GRANT_PURPOSE, "user_id": str(self.user.pk)},
            salt=VIEWER_GRANT_SALT,
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.get(
            "/api/viewer-access/authorize/",
            HTTP_COOKIE=f"{VIEWER_GRANT_COOKIE}={token}",
        )

        self.assertEqual(response.status_code, 401)
