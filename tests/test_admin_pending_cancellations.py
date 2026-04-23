"""Tests for admin pending-cancellations endpoints (Phase 3, tasks 3.4–3.6).

Tests:
- GET /admin/pending-cancellations
- POST /admin/pending-cancellations/retry
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from app.routers.admin import list_pending_cancellations, retry_pending_cancellations
from app.core.auth import UserContext
from app.core.exceptions import ExternalServiceError
from app.services.blotato_client import BlotatoAPIError


_ADMIN = UserContext(user_id="admin-123", email="admin@example.com", role="admin", token="tok")


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

class _FakeSettings:
    blotato_api_key = "test-key"
    blotato_max_retries = 1


class _FakeSettingsNoKey:
    blotato_api_key = ""
    blotato_max_retries = 1


class _FakeDBChain:
    """Chainable Supabase fake for pending_cancellations queries."""

    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows or []
        self.deleted_ids: list[str] = []
        self.updated: list[dict] = []

    def table(self, name: str):
        return self

    def select(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def offset(self, *args, **kwargs):
        return self

    def delete(self):
        return self

    def update(self, data: dict):
        self._pending_update = data
        return self

    def insert(self, data: dict):
        return self

    def eq(self, field: str, value):
        if field == "id" and hasattr(self, "_pending_update"):
            self.updated.append({"id": value, **self._pending_update})
            del self._pending_update
        elif field == "id":
            self.deleted_ids.append(value)
        return self

    def execute(self):
        return MagicMock(data=self._rows)


# ---------------------------------------------------------------------------
# GET /admin/pending-cancellations
# ---------------------------------------------------------------------------

async def test_list_pending_cancellations_returns_rows(monkeypatch):
    rows = [
        {"id": "row-1", "content_id": "c-1", "user_id": "u-1", "retry_count": 0},
        {"id": "row-2", "content_id": "c-2", "user_id": "u-2", "retry_count": 1},
    ]
    fake_db = _FakeDBChain(rows)
    monkeypatch.setattr("app.routers.admin.get_service_client", lambda: fake_db)

    result = await list_pending_cancellations(admin=_ADMIN)

    assert result["data"] == rows
    assert result["error"] is None


async def test_list_pending_cancellations_empty(monkeypatch):
    fake_db = _FakeDBChain([])
    monkeypatch.setattr("app.routers.admin.get_service_client", lambda: fake_db)

    result = await list_pending_cancellations(admin=_ADMIN)

    assert result["data"] == []


# ---------------------------------------------------------------------------
# POST /admin/pending-cancellations/retry — success path
# ---------------------------------------------------------------------------

async def test_retry_success_deletes_rows(monkeypatch):
    rows = [
        {"id": "row-1", "content_id": "c-1", "blotato_schedule_ids": {"instagram": {"id": "s1"}}, "retry_count": 0},
    ]
    fake_db = _FakeDBChain(rows)

    class _OKClient:
        async def cancel_post(self, schedule_id):
            pass
        async def aclose(self):
            pass

    monkeypatch.setattr("app.routers.admin.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.admin.get_service_client", lambda: fake_db)
    monkeypatch.setattr("app.routers.admin.BlotatoClient", lambda **kwargs: _OKClient())

    result = await retry_pending_cancellations(admin=_ADMIN)

    assert "c-1" in result["data"]["succeeded"]
    assert result["data"]["failed"] == []
    # Row should have been deleted
    assert "row-1" in fake_db.deleted_ids


# ---------------------------------------------------------------------------
# POST /admin/pending-cancellations/retry — failure path
# ---------------------------------------------------------------------------

async def test_retry_failure_increments_retry_count(monkeypatch):
    rows = [
        {"id": "row-1", "content_id": "c-1", "blotato_schedule_ids": {"instagram": {"id": "s1"}}, "retry_count": 2},
    ]
    fake_db = _FakeDBChain(rows)

    class _FailClient:
        async def cancel_post(self, schedule_id):
            raise BlotatoAPIError("timeout")
        async def aclose(self):
            pass

    monkeypatch.setattr("app.routers.admin.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.admin.get_service_client", lambda: fake_db)
    monkeypatch.setattr("app.routers.admin.BlotatoClient", lambda **kwargs: _FailClient())

    result = await retry_pending_cancellations(admin=_ADMIN)

    assert result["data"]["succeeded"] == []
    assert len(result["data"]["failed"]) == 1
    assert result["data"]["failed"][0]["id"] == "row-1"
    # Check update happened with retry_count = 3
    assert len(fake_db.updated) == 1
    assert fake_db.updated[0]["retry_count"] == 3


# ---------------------------------------------------------------------------
# POST /admin/pending-cancellations/retry — mixed results
# ---------------------------------------------------------------------------

async def test_retry_mixed_results(monkeypatch):
    rows = [
        {"id": "row-1", "content_id": "c-1", "blotato_schedule_ids": {"instagram": {"id": "s1"}}, "retry_count": 0},
        {"id": "row-2", "content_id": "c-2", "blotato_schedule_ids": {"facebook": {"id": "s2"}}, "retry_count": 1},
    ]
    fake_db = _FakeDBChain(rows)
    cancel_calls: list[str] = []

    class _MixedClient:
        async def cancel_post(self, schedule_id):
            cancel_calls.append(schedule_id)
            if schedule_id == "s2":
                raise BlotatoAPIError("fail")
        async def aclose(self):
            pass

    monkeypatch.setattr("app.routers.admin.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.admin.get_service_client", lambda: fake_db)
    monkeypatch.setattr("app.routers.admin.BlotatoClient", lambda **kwargs: _MixedClient())

    result = await retry_pending_cancellations(admin=_ADMIN)

    assert "c-1" in result["data"]["succeeded"]
    assert len(result["data"]["failed"]) == 1
    assert result["data"]["failed"][0]["id"] == "row-2"


# ---------------------------------------------------------------------------
# POST /admin/pending-cancellations/retry — no API key
# ---------------------------------------------------------------------------

async def test_retry_no_api_key_raises_503(monkeypatch):
    monkeypatch.setattr("app.routers.admin.get_settings", lambda: _FakeSettingsNoKey())

    with pytest.raises(ExternalServiceError):
        await retry_pending_cancellations(admin=_ADMIN)
