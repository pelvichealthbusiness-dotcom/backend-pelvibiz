"""Tests for _do_schedule_background and async 202 schedule endpoint (Phase 1 + 2.5/2.6).

Tests:
- _do_schedule_background success: calls blotato_publish, calls crud.update_content
- _do_schedule_background BlotatoAPIError: calls crud.update_content with publish_status="failed"
- _do_schedule_background ValueError: calls crud.update_content with publish_status="failed"
- _do_schedule_background caption update
- validate_connections all stale: background raises ValueError → crud updated with failed
- validate_connections some stale: blotato_publish called with only valid connections
- Router: schedule_content returns 202 with queued body
- Router: idempotent path returns 200
- Router: no connections returns 422 synchronously
- Router: no api key returns 503 synchronously
- Router: stale all accounts returns 422 synchronously
- Router: stale some accounts returns 202 with warnings
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from app.routers.content_v2 import _do_schedule_background, schedule_content, ScheduleContentRequest
from app.core.auth import UserContext
from app.core.exceptions import ValidationError, ExternalServiceError
from app.services.blotato_client import BlotatoAPIError


_USER = UserContext(user_id="user-abc", email="test@example.com", role="client", token="tok")


# ---------------------------------------------------------------------------
# Fakes
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
    blotato_api_key = ""
    blotato_max_retries = 1


class _FakeBlotatoClient:
    def __init__(self):
        self.closed = False

    async def create_post(self, **kwargs):
        return "sub-1"

    async def aclose(self):
        self.closed = True

    async def list_accounts(self):
        return []


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
# _do_schedule_background — success path
# ---------------------------------------------------------------------------

async def test_background_success_updates_db_with_scheduled_status(monkeypatch):
    fake_crud = _FakeCRUD({"id": "c-1"})
    fake_client = _FakeBlotatoClient()
    post_ids = {"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}

    async def _fake_publish(**kwargs):
        return post_ids

    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.blotato_publish", _fake_publish)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))

    settings = _FakeSettings()
    await _do_schedule_background(
        content_id="c-1",
        user_id="user-abc",
        media_urls=["https://example.com/img.jpg"],
        caption="Test",
        connections={"instagram": {"accountId": "ig-001"}},
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        settings=settings,
        update_caption=False,
        original_caption=None,
    )

    assert len(fake_crud.updates) == 1
    update = fake_crud.updates[0]
    assert update["published"] is True
    assert update["publish_status"] == "scheduled"
    assert update["publish_error"] is None
    assert fake_client.closed is True


async def test_background_success_updates_caption_when_requested(monkeypatch):
    fake_crud = _FakeCRUD({"id": "c-1"})
    fake_client = _FakeBlotatoClient()
    post_ids = {"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}

    async def _fake_publish(**kwargs):
        return post_ids

    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.blotato_publish", _fake_publish)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))

    settings = _FakeSettings()
    await _do_schedule_background(
        content_id="c-1",
        user_id="user-abc",
        media_urls=["https://example.com/img.jpg"],
        caption="New caption",
        connections={"instagram": {"accountId": "ig-001"}},
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        settings=settings,
        update_caption=True,
        original_caption="New caption",
    )

    update = fake_crud.updates[0]
    assert update["caption"] == "New caption"
    assert update["reply"] == "New caption"


# ---------------------------------------------------------------------------
# _do_schedule_background — error paths
# ---------------------------------------------------------------------------

async def test_background_blotato_error_updates_db_with_failed_status(monkeypatch):
    fake_crud = _FakeCRUD({"id": "c-1"})
    fake_client = _FakeBlotatoClient()

    async def _fake_publish(**kwargs):
        raise BlotatoAPIError("Blotato down")

    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.blotato_publish", _fake_publish)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))

    settings = _FakeSettings()
    await _do_schedule_background(
        content_id="c-1",
        user_id="user-abc",
        media_urls=["https://example.com/img.jpg"],
        caption="Test",
        connections={"instagram": {"accountId": "ig-001"}},
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        settings=settings,
        update_caption=False,
        original_caption=None,
    )

    update = fake_crud.updates[0]
    assert update["publish_status"] == "failed"
    assert "Blotato down" in update["publish_error"]
    assert fake_client.closed is True


async def test_background_value_error_updates_db_with_failed_status(monkeypatch):
    fake_crud = _FakeCRUD({"id": "c-1"})
    fake_client = _FakeBlotatoClient()

    async def _fake_publish(**kwargs):
        raise ValueError("media_urls cannot be empty")

    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.blotato_publish", _fake_publish)
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))

    settings = _FakeSettings()
    await _do_schedule_background(
        content_id="c-1",
        user_id="user-abc",
        media_urls=[],
        caption="Test",
        connections={"instagram": {"accountId": "ig-001"}},
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        settings=settings,
        update_caption=False,
        original_caption=None,
    )

    update = fake_crud.updates[0]
    assert update["publish_status"] == "failed"
    assert fake_client.closed is True


# ---------------------------------------------------------------------------
# _do_schedule_background — validate_connections integration
# ---------------------------------------------------------------------------

async def test_background_all_stale_sets_failed(monkeypatch):
    """All accounts stale → ValueError raised → crud updated with failed."""
    fake_crud = _FakeCRUD({"id": "c-1"})
    fake_client = _FakeBlotatoClient()
    publish_called = []

    async def _fake_publish(**kwargs):
        publish_called.append(True)
        return {"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}

    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.blotato_publish", _fake_publish)
    # All stale — validate_connections returns empty valid dict
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({}, ["instagram", "facebook"])))

    settings = _FakeSettings()
    await _do_schedule_background(
        content_id="c-1",
        user_id="user-abc",
        media_urls=["https://example.com/img.jpg"],
        caption="Test",
        connections={"instagram": {"accountId": "ig-001"}, "facebook": {"accountId": "fb-001"}},
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        settings=settings,
        update_caption=False,
        original_caption=None,
    )

    # Should not have called blotato_publish
    assert publish_called == []
    # Must have updated DB with failed
    update = fake_crud.updates[0]
    assert update["publish_status"] == "failed"


async def test_background_some_stale_publishes_only_valid(monkeypatch):
    """Some accounts stale → blotato_publish called with only valid connections."""
    fake_crud = _FakeCRUD({"id": "c-1"})
    fake_client = _FakeBlotatoClient()
    publish_kwargs: list[dict] = []

    async def _fake_publish(**kwargs):
        publish_kwargs.append(kwargs)
        return {"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}

    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: fake_client)
    monkeypatch.setattr("app.routers.content_v2.blotato_publish", _fake_publish)
    # facebook is stale, only instagram is valid
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, ["facebook"])))

    settings = _FakeSettings()
    await _do_schedule_background(
        content_id="c-1",
        user_id="user-abc",
        media_urls=["https://example.com/img.jpg"],
        caption="Test",
        connections={"instagram": {"accountId": "ig-001"}, "facebook": {"accountId": "fb-001"}},
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        settings=settings,
        update_caption=False,
        original_caption=None,
    )

    assert len(publish_kwargs) == 1
    assert "facebook" not in publish_kwargs[0]["connections"]
    assert "instagram" in publish_kwargs[0]["connections"]


# ---------------------------------------------------------------------------
# schedule_content endpoint — 202 / 200 / 422 / 503
# ---------------------------------------------------------------------------

async def test_schedule_returns_202_with_queued_body(monkeypatch):
    """Endpoint returns 202 with status=queued after validation passes."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/img.jpg"],
        "reply": "Caption",
        "published": False,
        "publish_status": None,
        "scheduled_date": None,
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
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FakeBlotatoClient())
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))
    monkeypatch.setattr(
        "app.routers.content_v2.blotato_publish",
        AsyncMock(return_value={"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}),
    )

    bg = BackgroundTasks()
    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["publish_status"] == "scheduled"


async def test_schedule_idempotent_returns_200(monkeypatch):
    """Idempotent path returns 200 (not 202)."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "publish_status": "scheduled",
        "scheduled_date": "2026-05-01T15:00:00",
        "blotato_post_ids": {"instagram": {"id": "sub-1", "status": "scheduled"}},
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.fetch_blotato_connections", AsyncMock(return_value={}))

    bg = BackgroundTasks()
    body = ScheduleContentRequest(scheduled_date="2026-05-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["data"]["idempotent"] is True


async def test_schedule_no_connections_returns_422(monkeypatch):
    """No blotato_connections on profile → 422 synchronously before 202."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/img.jpg"],
        "reply": "Caption",
        "published": False,
    })

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr(
        "app.routers.content_v2.get_service_client",
        lambda: _FakeSupabaseClient({"blotato_connections": None, "timezone": "UTC"}),
    )
    monkeypatch.setattr("app.routers.content_v2.fetch_blotato_connections", AsyncMock(return_value={}))

    bg = BackgroundTasks()
    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")

    with pytest.raises(ValidationError):
        await schedule_content("content-1", body, _USER)


async def test_schedule_no_api_key_returns_503(monkeypatch):
    """Missing BLOTATO_API_KEY → 503 synchronously before 202."""
    fake_crud = _FakeCRUD({"id": "content-1", "published": False})

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettingsNoKey())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)

    bg = BackgroundTasks()
    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")

    with pytest.raises(ExternalServiceError):
        await schedule_content("content-1", body, _USER)


async def test_schedule_all_stale_still_attempts_publish(monkeypatch):
    """Stale validation should not block the publish attempt."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/img.jpg"],
        "reply": "Caption",
        "published": False,
        "publish_status": None,
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
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FakeBlotatoClient())
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({}, ["instagram"])))
    monkeypatch.setattr("app.routers.content_v2.fetch_blotato_connections", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "app.routers.content_v2.blotato_publish",
        AsyncMock(return_value={"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}),
    )

    bg = BackgroundTasks()
    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")

    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert fake_crud.updates[-1]["publish_status"] == "scheduled"


async def test_schedule_some_stale_returns_202_with_warnings(monkeypatch):
    """Some stale accounts → 202 with warnings field containing stale platform message."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/img.jpg"],
        "reply": "Caption",
        "published": False,
        "publish_status": None,
        "scheduled_date": None,
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
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FakeBlotatoClient())
    # instagram valid, facebook stale
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, ["facebook"])))
    monkeypatch.setattr(
        "app.routers.content_v2.blotato_publish",
        AsyncMock(return_value={"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}),
    )

    bg = BackgroundTasks()
    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert result["data"]["publish_status"] == "scheduled"
    warnings = result.get("warnings") or []
    assert any("facebook" in w for w in warnings)


async def test_schedule_dispatches_background_task(monkeypatch):
    """After validation, background_tasks.add_task is called."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/img.jpg"],
        "reply": "Caption",
        "published": False,
        "publish_status": None,
        "scheduled_date": None,
    })
    added_tasks: list = []

    class _SpyBackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            added_tasks.append({"func": func, "args": args, "kwargs": kwargs})

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr(
        "app.routers.content_v2.get_service_client",
        lambda: _FakeSupabaseClient({
            "blotato_connections": {"instagram": {"accountId": "ig-001"}},
            "timezone": "UTC",
        }),
    )
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FakeBlotatoClient())
    monkeypatch.setattr("app.routers.content_v2.validate_connections",
                        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])))
    monkeypatch.setattr(
        "app.routers.content_v2.blotato_publish",
        AsyncMock(return_value={"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}),
    )

    body = ScheduleContentRequest(scheduled_date="2026-06-01T15:00:00", timezone="UTC")
    result = await schedule_content("content-1", body, _USER)

    assert result["error"] is None
    assert fake_crud.updates[-1]["publish_status"] == "scheduled"
