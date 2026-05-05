"""Tests for POST /admin/sync-post-status endpoint (Phase 5)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.admin import sync_post_status
from app.core.auth import UserContext
from app.core.exceptions import ExternalServiceError
from app.services.blotato_client import BlotatoAPIError


_ADMIN = UserContext(user_id="admin-123", email="admin@example.com", role="admin", token="tok")


class _FakeSettings:
    blotato_api_key = "test-key"


class _FakeSettingsNoKey:
    blotato_api_key = ""


# ---------------------------------------------------------------------------
# Auth — no key → 503
# ---------------------------------------------------------------------------

async def test_sync_post_status_no_api_key_raises():
    with patch("app.routers.admin.get_settings", return_value=_FakeSettingsNoKey()):
        with pytest.raises(ExternalServiceError):
            await sync_post_status(admin=_ADMIN)


# ---------------------------------------------------------------------------
# Happy path — scheduled → failed transition
# ---------------------------------------------------------------------------

async def test_sync_finds_failed_post_updates_db():
    """sync finds a scheduled post that Blotato now reports as failed → updates DB."""
    rows = [
        {
            "id": "content-1",
            "blotato_post_ids": {
                "instagram": {"id": "post-ig-1", "status": "scheduled", "error": None},
            },
            "publish_status": "scheduled",
        }
    ]

    class _FakeClient:
        async def get_post_status(self, post_id: str) -> str:
            return "failed"
        async def aclose(self):
            pass

    mock_crud = MagicMock()
    mock_crud.get_scheduled_content_since.return_value = rows
    mock_crud.admin_update_content.return_value = None

    with patch("app.routers.admin.get_settings", return_value=_FakeSettings()), \
         patch("app.routers.admin.ContentCRUD", return_value=mock_crud), \
         patch("app.routers.admin.BlotatoClient", return_value=_FakeClient()):
        result = await sync_post_status(admin=_ADMIN)

    assert result["data"]["synced"] == 1
    assert result["data"]["updated"] == 1
    mock_crud.admin_update_content.assert_called_once()
    call_args = mock_crud.admin_update_content.call_args
    assert call_args[0][0] == "content-1"
    updates = call_args[0][1]
    assert updates["publish_status"] == "failed"
    assert updates["blotato_post_ids"]["instagram"]["status"] == "failed"
    assert updates["failure_notified_at"] is None


# ---------------------------------------------------------------------------
# Blotato API error for one platform — skips, others processed
# ---------------------------------------------------------------------------

async def test_sync_blotato_error_skips_platform():
    """When Blotato raises for one platform, that platform is skipped; no DB update."""
    rows = [
        {
            "id": "content-2",
            "blotato_post_ids": {
                "instagram": {"id": "post-ig-2", "status": "scheduled", "error": None},
            },
            "publish_status": "scheduled",
        }
    ]

    class _ErrorClient:
        async def get_post_status(self, post_id: str) -> str:
            raise BlotatoAPIError("network timeout")
        async def aclose(self):
            pass

    mock_crud = MagicMock()
    mock_crud.get_scheduled_content_since.return_value = rows
    mock_crud.admin_update_content.return_value = None

    with patch("app.routers.admin.get_settings", return_value=_FakeSettings()), \
         patch("app.routers.admin.ContentCRUD", return_value=mock_crud), \
         patch("app.routers.admin.BlotatoClient", return_value=_ErrorClient()):
        result = await sync_post_status(admin=_ADMIN)

    assert result["data"]["synced"] == 1
    assert result["data"]["updated"] == 0
    mock_crud.admin_update_content.assert_not_called()


# ---------------------------------------------------------------------------
# Status still "scheduled" — no DB update
# ---------------------------------------------------------------------------

async def test_sync_scheduled_status_no_update():
    """When Blotato still reports 'scheduled', no DB update happens."""
    rows = [
        {
            "id": "content-3",
            "blotato_post_ids": {
                "facebook": {"id": "post-fb-3", "status": "scheduled", "error": None},
            },
            "publish_status": "scheduled",
        }
    ]

    class _ScheduledClient:
        async def get_post_status(self, post_id: str) -> str:
            return "scheduled"
        async def aclose(self):
            pass

    mock_crud = MagicMock()
    mock_crud.get_scheduled_content_since.return_value = rows
    mock_crud.admin_update_content.return_value = None

    with patch("app.routers.admin.get_settings", return_value=_FakeSettings()), \
         patch("app.routers.admin.ContentCRUD", return_value=mock_crud), \
         patch("app.routers.admin.BlotatoClient", return_value=_ScheduledClient()):
        result = await sync_post_status(admin=_ADMIN)

    assert result["data"]["synced"] == 1
    assert result["data"]["updated"] == 0
    mock_crud.admin_update_content.assert_not_called()


# ---------------------------------------------------------------------------
# Empty rows — nothing to do
# ---------------------------------------------------------------------------

async def test_sync_no_rows_returns_zeros():
    """When no scheduled content in the window, returns synced=0 updated=0."""
    mock_crud = MagicMock()
    mock_crud.get_scheduled_content_since.return_value = []

    class _NeverCalledClient:
        async def get_post_status(self, post_id: str) -> str:
            raise AssertionError("Should not be called")
        async def aclose(self):
            pass

    with patch("app.routers.admin.get_settings", return_value=_FakeSettings()), \
         patch("app.routers.admin.ContentCRUD", return_value=mock_crud), \
         patch("app.routers.admin.BlotatoClient", return_value=_NeverCalledClient()):
        result = await sync_post_status(admin=_ADMIN)

    assert result["data"] == {"synced": 0, "updated": 0}
