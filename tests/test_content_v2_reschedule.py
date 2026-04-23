"""Tests for reschedule_content warnings and reschedule_error in DB (Phase 3.4/3.6)."""

from __future__ import annotations

import pytest

from app.routers.content_v2 import reschedule_content, RescheduleRequest
from app.core.auth import UserContext
from app.services.blotato_client import BlotatoAPIError


_USER = UserContext(user_id="user-abc", email="test@example.com", role="client", token="tok")


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

class _FakeCRUD:
    def __init__(self, content: dict):
        self._content = content
        self.updates: list[dict] = []

    def get_content(self, content_id: str, user_id: str) -> dict:
        return self._content

    def update_content(self, content_id: str, user_id: str, updates: dict) -> dict:
        self.updates.append(updates)
        updated = {**self._content, **updates}
        self._content = updated
        return updated


class _FakeSettings:
    blotato_api_key = "test-api-key"
    blotato_max_retries = 1


class _FakeSettingsNoKey:
    blotato_api_key = None
    blotato_max_retries = 1


class _FakeSupabaseClient:
    def __init__(self, profile_data: dict):
        self._profile_data = profile_data

    def table(self, name: str):
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _FakeResult(self._profile_data)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeBlotatoClientAllOK:
    def __init__(self):
        self.reschedule_calls: list[dict] = []
        self.closed = False

    async def reschedule_post(self, schedule_id: str, new_scheduled_time: str) -> None:
        self.reschedule_calls.append({"schedule_id": schedule_id, "time": new_scheduled_time})

    async def aclose(self) -> None:
        self.closed = True


class _FakeBlotatoClientOneFails:
    """instagram succeeds; facebook raises BlotatoAPIError."""

    def __init__(self):
        self.reschedule_calls: list[dict] = []
        self.closed = False

    async def reschedule_post(self, schedule_id: str, new_scheduled_time: str) -> None:
        self.reschedule_calls.append({"schedule_id": schedule_id, "time": new_scheduled_time})
        if schedule_id == "sub-fb-456":
            raise BlotatoAPIError("HTTP 422: bad token")

    async def aclose(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# All platforms reschedule OK → no warnings key, reschedule_error = None in DB
# ---------------------------------------------------------------------------

async def test_reschedule_all_ok_no_warnings_key(monkeypatch):
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {
            "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
            "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
        },
    })
    fake_client = _FakeBlotatoClientAllOK()

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    result = await reschedule_content("content-1", body, _USER)

    assert "warnings" not in result
    # DB updated with reschedule_error=None for each platform
    last_update = fake_crud.updates[-1]
    ids = last_update.get("blotato_post_ids", {})
    assert ids.get("instagram", {}).get("reschedule_error") is None
    assert ids.get("facebook", {}).get("reschedule_error") is None


# ---------------------------------------------------------------------------
# One platform fails → warnings list present, reschedule_error set in DB
# ---------------------------------------------------------------------------

async def test_reschedule_one_platform_fails_warnings_present(monkeypatch):
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {
            "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
            "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
        },
    })
    fake_client = _FakeBlotatoClientOneFails()

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    result = await reschedule_content("content-1", body, _USER)

    assert "warnings" in result
    assert len(result["warnings"]) == 1
    assert "facebook" in result["warnings"][0]
    assert "HTTP 422" in result["warnings"][0]


async def test_reschedule_one_platform_fails_reschedule_error_stored(monkeypatch):
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {
            "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
            "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
        },
    })
    fake_client = _FakeBlotatoClientOneFails()

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    await reschedule_content("content-1", body, _USER)

    last_update = fake_crud.updates[-1]
    ids = last_update.get("blotato_post_ids", {})
    # instagram succeeded → reschedule_error = None
    assert ids["instagram"]["reschedule_error"] is None
    # facebook failed → reschedule_error set
    assert ids["facebook"]["reschedule_error"] is not None
    assert "HTTP 422" in ids["facebook"]["reschedule_error"]


# ---------------------------------------------------------------------------
# Empty blotato_post_ids → no warnings, scheduled_date updated
# ---------------------------------------------------------------------------

async def test_reschedule_empty_post_ids_no_warnings(monkeypatch):
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {},
    })
    fake_client = _FakeBlotatoClientAllOK()

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    result = await reschedule_content("content-1", body, _USER)

    assert "warnings" not in result
    assert fake_client.reschedule_calls == []
    last_update = fake_crud.updates[-1]
    assert last_update["scheduled_date"] == "2026-07-01T15:00:00"


# ---------------------------------------------------------------------------
# No API key → no Blotato call, no warnings, DB updated
# ---------------------------------------------------------------------------

async def test_reschedule_no_api_key_no_warnings(monkeypatch):
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {
            "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        },
    })
    fake_client = _FakeBlotatoClientAllOK()

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettingsNoKey())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    result = await reschedule_content("content-1", body, _USER)

    assert "warnings" not in result
    assert fake_client.reschedule_calls == []
    last_update = fake_crud.updates[-1]
    assert last_update["scheduled_date"] == "2026-07-01T15:00:00"
