"""Tests for POST /content/{id}/republish endpoint (Phase 3)."""

from __future__ import annotations

import pytest

from app.routers.content_v2 import republish_content
from app.core.auth import UserContext
from app.core.exceptions import ValidationError


_USER = UserContext(user_id="user-abc", email="test@example.com", role="client", token="tok")


# ---------------------------------------------------------------------------
# Shared fakes (same pattern as test_calendar_sync.py)
# ---------------------------------------------------------------------------

class _FakeBlotatoClient:
    def __init__(self, responses: dict | None = None):
        self._responses = responses or {}
        self.create_calls: list[dict] = []
        self.closed = False

    async def create_post(self, *, platform, account_id, text, media_urls,
                          scheduled_time, page_id=None, playlist_ids=None, media_type=None,
                          tiktok_privacy_level=None, disable_comment=False,
                          disable_duet=False, disable_stitch=False):
        self.create_calls.append({"platform": platform})
        r = self._responses.get(platform, f"sub-{platform}-retry")
        if isinstance(r, Exception):
            raise r
        return r

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
# 422 guard cases
# ---------------------------------------------------------------------------

async def test_republish_raises_422_when_already_scheduled(monkeypatch):
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "publish_status": "scheduled",
        "blotato_post_ids": {"instagram": {"id": "sub-1", "status": "scheduled", "error": None}},
        "scheduled_date": "2026-06-01T15:00:00",
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })
    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)

    with pytest.raises(ValidationError, match="already scheduled"):
        await republish_content("content-1", _USER)


async def test_republish_raises_422_when_never_scheduled(monkeypatch):
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "publish_status": None,
        "blotato_post_ids": {},
        "scheduled_date": None,
        "reply": "Caption",
        "media_urls": ["https://example.com/img.jpg"],
        "agent_type": "real-carousel",
    })
    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)

    with pytest.raises(ValidationError):
        await republish_content("content-1", _USER)


# ---------------------------------------------------------------------------
# 200 — full retry (all platforms failed)
# ---------------------------------------------------------------------------

async def test_republish_retries_all_platforms_when_all_failed(monkeypatch):
    fake_client = _FakeBlotatoClient({"instagram": "sub-ig-retry", "facebook": "sub-fb-retry"})
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "publish_status": "failed",
        "blotato_post_ids": {
            "instagram": {"id": None, "status": "failed", "error": "boom"},
            "facebook": {"id": None, "status": "failed", "error": "boom"},
        },
        "scheduled_date": "2026-06-01T15:00:00",
        "reply": "My caption",
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

    result = await republish_content("content-1", _USER)

    assert result["data"]["publish_status"] == "scheduled"
    platforms_called = {c["platform"] for c in fake_client.create_calls}
    assert platforms_called == {"instagram", "facebook"}


# ---------------------------------------------------------------------------
# 200 — partial retry (only failed platforms retried)
# ---------------------------------------------------------------------------

async def test_republish_retries_only_failed_platforms_when_partial(monkeypatch):
    fake_client = _FakeBlotatoClient({"facebook": "sub-fb-retry"})
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "publish_status": "partial",
        "blotato_post_ids": {
            "instagram": {"id": "sub-ig-old", "status": "scheduled", "error": None},
            "facebook": {"id": None, "status": "failed", "error": "boom"},
        },
        "scheduled_date": "2026-06-01T15:00:00",
        "reply": "My caption",
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

    result = await republish_content("content-1", _USER)

    # Only facebook was retried — instagram was already scheduled
    platforms_called = {c["platform"] for c in fake_client.create_calls}
    assert platforms_called == {"facebook"}
    assert result["data"]["publish_status"] == "scheduled"


async def test_republish_does_not_duplicate_already_scheduled_platform(monkeypatch):
    fake_client = _FakeBlotatoClient({"facebook": "sub-fb-retry"})
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "publish_status": "partial",
        "blotato_post_ids": {
            "instagram": {"id": "sub-ig-old", "status": "scheduled", "error": None},
            "facebook": {"id": None, "status": "failed", "error": "boom"},
        },
        "scheduled_date": "2026-06-01T15:00:00",
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

    await republish_content("content-1", _USER)

    ig_calls = [c for c in fake_client.create_calls if c["platform"] == "instagram"]
    assert ig_calls == []


# ---------------------------------------------------------------------------
# publish_status derivation after retry
# ---------------------------------------------------------------------------

async def test_republish_sets_scheduled_when_all_succeed(monkeypatch):
    fake_client = _FakeBlotatoClient({"instagram": "sub-ig-new", "facebook": "sub-fb-new"})
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "publish_status": "failed",
        "blotato_post_ids": {
            "instagram": {"id": None, "status": "failed", "error": "e1"},
            "facebook": {"id": None, "status": "failed", "error": "e2"},
        },
        "scheduled_date": "2026-06-01T15:00:00",
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

    result = await republish_content("content-1", _USER)

    saved = fake_crud.updates[-1]
    assert saved["publish_status"] == "scheduled"
    assert result["data"]["publish_status"] == "scheduled"
