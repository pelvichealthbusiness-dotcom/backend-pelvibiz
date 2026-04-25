"""Integration tests for calendar-blotato-sync endpoints.

Tests the three modified endpoints in content_v2:
- POST /{content_id}/schedule  — saves blotato_post_ids after publishing
- PATCH /{content_id}/reschedule — calls Blotato reschedule + updates DB
- DELETE /detail/{content_id}   — cancels Blotato post before deleting

Uses the fake-client pattern from test_blotato_publisher.py.
Bypasses HTTP layer — calls endpoint functions directly with faked dependencies.
"""

from __future__ import annotations

import json
import pytest

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
from unittest.mock import AsyncMock

from app.routers.content_v2 import (
    schedule_content,
    reschedule_content,
    delete_content_detail,
    ScheduleContentRequest,
    RescheduleRequest,
)
from app.core.auth import UserContext


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

class _FakeUser:
    user_id = "user-abc"
    email = "test@example.com"
    role = "client"
    token = "tok"


_USER = UserContext(user_id="user-abc", email="test@example.com", role="client", token="tok")


class _FakeBlotatoClient:
    def __init__(self, post_ids: dict[str, str] | None = None):
        self._post_ids = post_ids or {}
        self.reschedule_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self.closed = False

    async def create_post(self, *, platform, account_id, text, media_urls,
                          scheduled_time, page_id=None, playlist_ids=None, media_type=None):
        return self._post_ids.get(platform, f"sub-{platform}-default")

    async def reschedule_post(self, schedule_id: str, new_scheduled_time: str) -> None:
        self.reschedule_calls.append({"schedule_id": schedule_id, "time": new_scheduled_time})

    async def cancel_post(self, schedule_id: str) -> None:
        self.cancel_calls.append(schedule_id)

    async def aclose(self) -> None:
        self.closed = True


class _FakeCRUD:
    def __init__(self, content: dict):
        self._content = content
        self.updates: list[dict] = []
        self.deleted = False

    def get_content(self, content_id: str, user_id: str) -> dict:
        return self._content

    def update_content(self, content_id: str, user_id: str, updates: dict) -> dict:
        self.updates.append(updates)
        updated = {**self._content, **updates}
        self._content = updated
        return updated

    def delete_content(self, content_id: str, user_id: str) -> bool:
        self.deleted = True
        return True


class _FakeSettings:
    blotato_api_key = "test-api-key"
    blotato_max_retries = 1


# ---------------------------------------------------------------------------
# schedule_content — returns 202 queued (DB update happens in background task)
# ---------------------------------------------------------------------------

async def test_schedule_content_returns_202_queued(monkeypatch):
    """Endpoint returns 202 with status=queued; DB update happens in background task."""
    fake_client = _FakeBlotatoClient({"instagram": "sub-ig-111", "facebook": "sub-fb-222"})
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/img.jpg"],
        "reply": "Original caption",
        "published": False,
        "publish_status": None,
        "scheduled_date": None,
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr(
        "app.routers.content_v2.get_service_client",
        lambda: _FakeSupabaseClient({"blotato_connections": {
            "instagram": {"accountId": "ig-001"},
            "facebook": {"accountId": "fb-001", "pageId": "pg-001"},
        }}),
    )
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({
                            "instagram": {"accountId": "ig-001"},
                            "facebook": {"accountId": "fb-001", "pageId": "pg-001"},
                        }, [])))

    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["publish_status"] == "scheduled"


async def test_schedule_content_dispatches_background_task(monkeypatch):
    """Endpoint adds _do_schedule_background to background_tasks."""
    fake_client = _FakeBlotatoClient({"instagram": "sub-ig-111"})
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/img.jpg"],
        "reply": "",
        "published": False,
        "publish_status": None,
        "scheduled_date": None,
    })
    added_tasks: list = []

    class _SpyBG:
        def add_task(self, func, *args, **kwargs):
            added_tasks.append(func.__name__)

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr(
        "app.routers.content_v2.get_service_client",
        lambda: _FakeSupabaseClient({"blotato_connections": {"instagram": {"accountId": "ig-001"}}}),
    )
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))

    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["publish_status"] == "scheduled"
    assert added_tasks == []


# ---------------------------------------------------------------------------
# reschedule_content — calls Blotato + updates DB
# ---------------------------------------------------------------------------

async def test_reschedule_content_calls_blotato_reschedule(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {"instagram": "sub-ig-old", "facebook": "sub-fb-old"},
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    await reschedule_content("content-1", body, _USER)

    assert len(fake_client.reschedule_calls) == 2
    rescheduled_ids = {c["schedule_id"] for c in fake_client.reschedule_calls}
    assert rescheduled_ids == {"sub-ig-old", "sub-fb-old"}


async def test_reschedule_content_updates_db_even_if_blotato_fails(monkeypatch):
    from app.services.blotato_client import BlotatoAPIError

    class _FailingClient:
        async def reschedule_post(self, *args, **kwargs):
            raise BlotatoAPIError("network failure")
        async def aclose(self):
            pass

    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {"instagram": "sub-ig-old"},
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FailingClient())

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    # Should NOT raise — Blotato failure is soft
    await reschedule_content("content-1", body, _USER)

    assert fake_crud.updates[-1]["scheduled_date"] == "2026-07-01T15:00:00"


async def test_reschedule_content_skips_blotato_when_no_post_ids(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {},
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client",
                        lambda: _FakeSupabaseClient({"timezone": "UTC"}))
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    body = RescheduleRequest(scheduled_date="2026-07-01T15:00:00")
    await reschedule_content("content-1", body, _USER)

    assert fake_client.reschedule_calls == []
    assert fake_crud.updates[-1]["scheduled_date"] == "2026-07-01T15:00:00"


# ---------------------------------------------------------------------------
# delete_content_detail — cancels Blotato before deleting
# ---------------------------------------------------------------------------

async def test_delete_cancels_blotato_posts_for_scheduled_content(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-06-01T15:00:00",
        "blotato_post_ids": {"instagram": "sub-ig-del", "facebook": "sub-fb-del"},
        "media_urls": [],
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    await delete_content_detail("content-1", _USER)

    assert set(fake_client.cancel_calls) == {"sub-ig-del", "sub-fb-del"}
    assert fake_crud.deleted is True


async def test_delete_proceeds_even_if_blotato_cancel_fails(monkeypatch):
    from app.services.blotato_client import BlotatoAPIError

    class _FailingClient:
        async def cancel_post(self, *args, **kwargs):
            raise BlotatoAPIError("cancel failed")
        async def aclose(self):
            pass

    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-06-01T15:00:00",
        "blotato_post_ids": {"instagram": "sub-ig-del"},
        "media_urls": [],
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FailingClient())

    await delete_content_detail("content-1", _USER)

    assert fake_crud.deleted is True


async def test_delete_skips_cancel_for_draft_content(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": False,
        "scheduled_date": None,
        "blotato_post_ids": {"instagram": "sub-ig-123"},
        "media_urls": [],
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    await delete_content_detail("content-1", _USER)

    assert fake_client.cancel_calls == []
    assert fake_crud.deleted is True


async def test_delete_skips_cancel_when_no_post_ids(monkeypatch):
    fake_client = _FakeBlotatoClient()
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-06-01T15:00:00",
        "blotato_post_ids": {},
        "media_urls": [],
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)

    await delete_content_detail("content-1", _USER)

    assert fake_client.cancel_calls == []
    assert fake_crud.deleted is True


# ---------------------------------------------------------------------------
# Shared Supabase fake for schedule_content
# ---------------------------------------------------------------------------

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
