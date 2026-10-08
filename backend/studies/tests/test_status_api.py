"""Tests for authenticated study viewing sessions."""
from datetime import timedelta
from uuid import UUID
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.services.orthanc import OrthancNotFoundError, OrthancService
from studies.models import ViewingSession


class ViewingStatusApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="staff")
        self.other_user = user_model.objects.create_user(username="other")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_anonymous_user_cannot_access_status_endpoints(self):
        client = APIClient()
        requests = (
            ("post", "/api/status/open/", {"study_id": "study-1"}),
            ("post", "/api/status/heartbeat/", {"session_id": "00000000-0000-0000-0000-000000000000"}),
            ("post", "/api/status/close/", {"session_id": "00000000-0000-0000-0000-000000000000"}),
            ("get", "/api/status/?study_ids=study-1", None),
        )
        for method, url, data in requests:
            response = getattr(client, method)(url, data, format="json") if data else client.get(url)
            self.assertEqual(response.status_code, 401, url)

    @patch.object(OrthancService, "get_study", return_value={"ID": "study-1"})
    def test_open_creates_session_and_returns_uuid_and_interval(self, _mock_get_study):
        before = timezone.now()
        response = self.client.post("/api/status/open/", {"study_id": "study-1"}, format="json")
        after = timezone.now()

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["study_id"], "study-1")
        self.assertEqual(payload["heartbeat_interval_seconds"], 30)
        session_id = UUID(payload["session_id"])
        session = ViewingSession.objects.get(pk=session_id)
        self.assertEqual(session.user, self.user)
        self.assertTrue(session.is_active)
        self.assertIsNone(session.closed_at)
        self.assertTrue(before <= session.opened_at <= after)
        self.assertEqual(session.opened_at, session.last_heartbeat_at)
        self.assertTrue(timezone.is_aware(session.opened_at))

    @patch.object(
        OrthancService,
        "get_study",
        side_effect=OrthancNotFoundError("Orthanc details must not reach clients"),
    )
    def test_open_does_not_create_session_for_unknown_study(self, _mock_get_study):
        response = self.client.post("/api/status/open/", {"study_id": "missing"}, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ViewingSession.objects.count(), 0)
        self.assertNotIn("Orthanc details", response.content.decode())

    @patch.object(OrthancService, "get_study", return_value={"ID": "study-1"})
    def test_open_rejects_path_traversal_study_id(self, _mock_get_study):
        response = self.client.post(
            "/api/status/open/",
            {"study_id": "../patients"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        _mock_get_study.assert_not_called()

    def _session(self, **values):
        defaults = {
            "study_id": "study-1",
            "user": self.user,
        }
        defaults.update(values)
        return ViewingSession.objects.create(**defaults)

    def test_heartbeat_updates_last_heartbeat(self):
        session = self._session(last_heartbeat_at=timezone.now() - timedelta(minutes=1))

        response = self.client.post(
            "/api/status/heartbeat/",
            {"session_id": str(session.id)},
            format="json",
        )

        session.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertGreater(session.last_heartbeat_at, timezone.now() - timedelta(seconds=10))
        self.assertEqual(response.json()["session_id"], str(session.id))

    def test_heartbeat_rejects_missing_or_invalid_session_id(self):
        for payload in ({}, {"session_id": "not-a-uuid"}):
            response = self.client.post("/api/status/heartbeat/", payload, format="json")
            self.assertEqual(response.status_code, 400)

    def test_heartbeat_rejects_unknown_session(self):
        response = self.client.post(
            "/api/status/heartbeat/",
            {"session_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_heartbeat_rejects_a_stale_session(self):
        session = self._session(last_heartbeat_at=timezone.now() - timedelta(seconds=120))

        response = self.client.post(
            "/api/status/heartbeat/",
            {"session_id": str(session.id)},
            format="json",
        )

        session.refresh_from_db()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(session.is_active)

    def test_user_cannot_heartbeat_or_close_another_users_session(self):
        session = ViewingSession.objects.create(
            study_id="study-1",
            user=self.other_user,
        )
        last_heartbeat = session.last_heartbeat_at

        heartbeat = self.client.post(
            "/api/status/heartbeat/",
            {"session_id": str(session.id)},
            format="json",
        )
        close = self.client.post(
            "/api/status/close/",
            {"session_id": str(session.id)},
            format="json",
        )

        self.assertEqual(heartbeat.status_code, 404)
        self.assertEqual(close.status_code, 404)
        session.refresh_from_db()
        self.assertEqual(session.last_heartbeat_at, last_heartbeat)
        self.assertTrue(session.is_active)

    def test_close_marks_session_closed(self):
        session = self._session()

        response = self.client.post(
            "/api/status/close/",
            {"session_id": str(session.id)},
            format="json",
        )

        session.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(session.is_active)
        self.assertIsNotNone(session.closed_at)
        self.assertTrue(timezone.is_aware(session.closed_at))

    def test_closing_already_closed_session_is_idempotent(self):
        closed_at = timezone.now() - timedelta(minutes=2)
        session = self._session(is_active=False, closed_at=closed_at)

        response = self.client.post(
            "/api/status/close/",
            {"session_id": str(session.id)},
            format="json",
        )

        session.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(session.is_active)
        self.assertEqual(session.closed_at, closed_at)

    def test_stale_sessions_are_closed_and_not_reported_active(self):
        stale = self._session(last_heartbeat_at=timezone.now() - timedelta(seconds=120))

        response = self.client.get("/api/status/?study_ids=study-1")

        stale.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(stale.is_active)
        self.assertIsNotNone(stale.closed_at)
        self.assertFalse(response.json()["results"][0]["being_viewed"])

    def test_multiple_sessions_and_study_ids_are_reported(self):
        self._session()
        ViewingSession.objects.create(study_id="study-1", user=self.other_user)
        self._session(study_id="study-2")

        response = self.client.get("/api/status/?study_ids=study-1,study-2,study-3")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [
                {"study_id": "study-1", "being_viewed": True},
                {"study_id": "study-2", "being_viewed": True},
                {"study_id": "study-3", "being_viewed": False},
            ],
        )

    def test_status_rejects_invalid_study_id_list(self):
        for query in ("", "study-1,", "../unsafe", ",".join(f"s{i}" for i in range(101))):
            response = self.client.get(f"/api/status/?study_ids={query}")
            self.assertEqual(response.status_code, 400)
