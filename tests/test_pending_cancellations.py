"""Tests for deferred cancel — pending_cancellations table (Phase 3).

Tests the behavior of delete_content_detail when cancel_all_platforms
raises BlotatoAPIError: the content_id must be inserted into pending_cancellations.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.routers.content_v2 import delete_content_detail
from app.core.auth import UserContext
from app.services.blotato_client import BlotatoAPIError


_USER = UserContext(user_id="user-abc", email="test@example.com", role="client", token="tok")


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

class _FakeCRUD:
    def __init__(self, content: dict):
        self._content = content
        self.deleted = False

    def get_content(self, content_id: str, user_id: str) -> dict:
        return self._content

    def update_content(self, content_id: str, user_id: str, updates: dict) -> dict:
        return {**self._content, **updates}

    def delete_content(self, content_id: str, user_id: str) -> bool:
        self.deleted = True
        return True


class _FakeSettings:
    blotato_api_key = "test-api-key"
    blotato_max_retries = 1


class _FakeSupabaseChain:
    """Chainable Supabase fake that records insert() calls."""

    def __init__(self):
        self.inserted: list[dict] = []
        self.deleted: list[str] = []

    def table(self, name: str):
        return self

    def insert(self, data: dict):
        self.inserted.append(data)
        return self

    def delete(self):
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return MagicMock(data=[])


# ---------------------------------------------------------------------------
# 3.3 — test_delete_cancel_success_no_pending_row
# ---------------------------------------------------------------------------

async def test_delete_cancel_success_no_pending_row(monkeypatch):
    """When cancel succeeds, no row is inserted into pending_cancellations."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-06-01T15:00:00",
        "blotato_post_ids": {"instagram": {"id": "sub-ig-del", "status": "scheduled"}},
        "media_urls": [],
    })
    fake_db = _FakeSupabaseChain()

    class _OKClient:
        async def cancel_post(self, schedule_id):
            pass
        async def aclose(self):
            pass

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _OKClient())
    monkeypatch.setattr("app.routers.content_v2.get_service_client", lambda: fake_db)

    await delete_content_detail("content-1", _USER)

    # No pending_cancellations insert
    assert fake_db.inserted == []
    assert fake_crud.deleted is True


# ---------------------------------------------------------------------------
# 3.3 — test_delete_cancel_fails_inserts_pending_row
# ---------------------------------------------------------------------------

async def test_delete_cancel_fails_inserts_pending_row(monkeypatch):
    """When cancel fails with BlotatoAPIError, inserts row into pending_cancellations."""
    blotato_post_ids = {"instagram": {"id": "sub-ig-del", "status": "scheduled"}}
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-06-01T15:00:00",
        "blotato_post_ids": blotato_post_ids,
        "media_urls": [],
    })
    fake_db = _FakeSupabaseChain()

    class _FailingClient:
        async def cancel_post(self, schedule_id):
            raise BlotatoAPIError("network timeout")
        async def aclose(self):
            pass

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FailingClient())
    monkeypatch.setattr("app.routers.content_v2.get_service_client", lambda: fake_db)

    await delete_content_detail("content-1", _USER)

    # Must have inserted a pending_cancellations row
    assert len(fake_db.inserted) == 1
    row = fake_db.inserted[0]
    assert row["content_id"] == "content-1"
    assert row["user_id"] == str(_USER.user_id)
    assert row["blotato_schedule_ids"] == blotato_post_ids


# ---------------------------------------------------------------------------
# 3.3 — test_delete_proceeds_after_cancel_failure
# ---------------------------------------------------------------------------

async def test_delete_proceeds_after_cancel_failure(monkeypatch):
    """DB delete is called even when Blotato cancel raises BlotatoAPIError."""
    fake_crud = _FakeCRUD({
        "id": "content-1",
        "published": True,
        "scheduled_date": "2026-06-01T15:00:00",
        "blotato_post_ids": {"instagram": {"id": "sub-ig-del", "status": "scheduled"}},
        "media_urls": [],
    })
    fake_db = _FakeSupabaseChain()

    class _FailingClient:
        async def cancel_post(self, schedule_id):
            raise BlotatoAPIError("timeout")
        async def aclose(self):
            pass

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: _FailingClient())
    monkeypatch.setattr("app.routers.content_v2.get_service_client", lambda: fake_db)

    await delete_content_detail("content-1", _USER)

    # Deletion must proceed despite cancel failure
    assert fake_crud.deleted is True
