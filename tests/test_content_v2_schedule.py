"""Tests for idempotency check and validation in POST /content/{id}/schedule."""

from __future__ import annotations

import json
import pytest

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
from unittest.mock import AsyncMock

from app.routers.content_v2 import schedule_content, ScheduleContentRequest
from app.core.auth import UserContext


_USER = UserContext(user_id="user-abc", email="test@example.com", role="client", token="tok")
_BG = BackgroundTasks()


# ---------------------------------------------------------------------------
# Shared fakes (same pattern as test_calendar_sync.py)
# ---------------------------------------------------------------------------

class _FakeBlotatoClient:
    def __init__(self):
        self.create_calls: list[dict] = []
        self.closed = False

    async def create_post(self, *, platform, account_id, text, media_urls,
                          scheduled_time, page_id=None, playlist_ids=None, media_type=None):
        self.create_calls.append({"platform": platform})
        return f"sub-{platform}-new"

    async def list_accounts(self):
        return [{"id": "ig-001"}, {"id": "fb-001"}]

    async def aclose(self) -> None:
        self.closed = True


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


# ---------------------------------------------------------------------------
# Idempotency: same content_id + same scheduled_date + publish_status=scheduled
# → returns 200 JSONResponse with idempotent=True
# ---------------------------------------------------------------------------

async def test_schedule_is_idempotent_for_same_date_and_scheduled_status(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "publish_status": "scheduled",
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {"instagram": {"id": "sub-ig-1", "status": "scheduled", "error": None}},
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = ScheduleContentRequest(scheduled_date="2026-05-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["idempotent"] is True
    assert fake_client.create_calls == []


async def test_schedule_idempotent_response_has_no_blotato_update(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "publish_status": "scheduled",
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {"instagram": {"id": "sub-ig-1", "status": "scheduled", "error": None}},
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = ScheduleContentRequest(scheduled_date="2026-05-01T15:00:00", timezone="UTC")
    await schedule_content("content-1", body, _USER)

    # No DB update was made (no new schedule)
    assert fake_crud.updates == []


# ---------------------------------------------------------------------------
# Different scheduled_date → dispatches background task (202), not idempotent
# ---------------------------------------------------------------------------

async def test_schedule_proceeds_for_different_date(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "publish_status": "scheduled",
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {"instagram": {"id": "sub-ig-1", "status": "scheduled", "error": None}},
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr(
        "app.routers.content_v2.get_service_client",
        lambda: _FakeSupabaseClient({
            "blotato_connections": {"instagram": {"accountId": "ig-001"}},
            "timezone": "UTC",
        }),
    )
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))

    # Different date — should proceed and return 202
    body = ScheduleContentRequest(scheduled_date="2026-07-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["publish_status"] == "scheduled"
    assert result["data"].get("idempotent") is not True


# ---------------------------------------------------------------------------
# publish_status=failed → dispatches background task (202)
# ---------------------------------------------------------------------------

async def test_schedule_proceeds_when_publish_status_is_failed(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "publish_status": "failed",
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {},
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr(
        "app.routers.content_v2.get_service_client",
        lambda: _FakeSupabaseClient({
            "blotato_connections": {"instagram": {"accountId": "ig-001"}},
            "timezone": "UTC",
        }),
    )
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))

    body = ScheduleContentRequest(scheduled_date="2026-05-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["publish_status"] == "scheduled"


# ---------------------------------------------------------------------------
# publish_status=partial → dispatches background task (202)
# ---------------------------------------------------------------------------

async def test_schedule_proceeds_when_publish_status_is_partial(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "publish_status": "partial",
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {
            "instagram": {"id": "sub-ig-1", "status": "scheduled", "error": None},
            "facebook": {"id": None, "status": "failed", "error": "boom"},
        },
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr(
        "app.routers.content_v2.get_service_client",
        lambda: _FakeSupabaseClient({
            "blotato_connections": {
                "instagram": {"accountId": "ig-001"},
                "facebook": {"accountId": "fb-001"},
            },
            "timezone": "UTC",
        }),
    )
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=(
                            {"instagram": {"accountId": "ig-001"}, "facebook": {"accountId": "fb-001"}},
                            [],
                        )))

    body = ScheduleContentRequest(scheduled_date="2026-05-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["publish_status"] == "scheduled"
