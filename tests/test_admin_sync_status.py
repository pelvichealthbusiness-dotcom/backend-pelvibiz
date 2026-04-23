"""Tests for POST /admin/publish-logs/{content_id}/sync-status (Phase 2.3/2.4)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.routers.admin import sync_publish_status
from app.core.auth import UserContext


_ADMIN = UserContext(user_id="admin-abc", email="admin@example.com", role="admin", token="tok")


class _FakeSettings:
    blotato_api_key = "test-blotato-key"


class _FakeSettingsNoKey:
    blotato_api_key = None


# ---------------------------------------------------------------------------
# Success: 200 with synced_platforms
# ---------------------------------------------------------------------------

async def test_sync_status_success_returns_synced_platforms(monkeypatch):
    fake_result = {
        "content_id": "content-abc",
        "synced_platforms": ["instagram", "facebook"],
        "errors": {},
        "updated_blotato_post_ids": {
            "instagram": {"id": "sched-1", "status": "published"},
            "facebook": {"id": "sched-2", "status": "scheduled"},
        },
    }

    monkeypatch.setattr("app.routers.admin.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        "app.routers.admin.blotato_admin_service.sync_content_publish_status",
        AsyncMock(return_value=fake_result),
    )

    result = await sync_publish_status("content-abc", admin=_ADMIN)

    assert result["data"]["content_id"] == "content-abc"
    assert "instagram" in result["data"]["synced_platforms"]
    assert "facebook" in result["data"]["synced_platforms"]


# ---------------------------------------------------------------------------
# Content not found (KeyError) → 404
# ---------------------------------------------------------------------------

async def test_sync_status_content_not_found_raises_not_found(monkeypatch):
    from app.core.exceptions import NotFoundError

    monkeypatch.setattr("app.routers.admin.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        "app.routers.admin.blotato_admin_service.sync_content_publish_status",
        AsyncMock(side_effect=KeyError("Content content-bad not found")),
    )

    with pytest.raises(NotFoundError):
        await sync_publish_status("content-bad", admin=_ADMIN)


# ---------------------------------------------------------------------------
# No API key → 502 ExternalServiceError
# ---------------------------------------------------------------------------

async def test_sync_status_no_api_key_raises_external_service_error(monkeypatch):
    from app.core.exceptions import ExternalServiceError

    monkeypatch.setattr("app.routers.admin.get_settings", lambda: _FakeSettingsNoKey())

    with pytest.raises(ExternalServiceError):
        await sync_publish_status("content-abc", admin=_ADMIN)
