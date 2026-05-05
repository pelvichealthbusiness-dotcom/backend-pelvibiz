"""Tests for /alerts endpoints — failure alert surface for publishing failures."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from app.routers.alerts import get_alerts, ack_alert
from app.core.auth import UserContext
from app.core.exceptions import DatabaseError


_USER = UserContext(user_id="user-123", email="user@example.com", role="user", token="tok")
_OTHER_USER = UserContext(user_id="other-456", email="other@example.com", role="user", token="tok2")


# ---------------------------------------------------------------------------
# GET /alerts — returns unacked failures
# ---------------------------------------------------------------------------

async def test_get_alerts_returns_failed_and_partial():
    """GET /alerts returns failed and partial items with no failure_notified_at."""
    items = [
        {"id": "c-1", "publish_status": "failed", "failure_notified_at": None},
        {"id": "c-2", "publish_status": "partial", "failure_notified_at": None},
    ]
    with patch("app.routers.alerts.ContentCRUD") as MockCRUD:
        MockCRUD.return_value.get_unacked_failures.return_value = items
        result = await get_alerts(user=_USER)

    assert result["data"] == items
    assert result["error"] is None
    MockCRUD.return_value.get_unacked_failures.assert_called_once_with(user_id="user-123")


async def test_get_alerts_returns_empty_when_none():
    """GET /alerts returns empty list when no unacked failures."""
    with patch("app.routers.alerts.ContentCRUD") as MockCRUD:
        MockCRUD.return_value.get_unacked_failures.return_value = []
        result = await get_alerts(user=_USER)

    assert result["data"] == []


async def test_get_alerts_excludes_acknowledged():
    """GET /alerts only returns items where failure_notified_at IS NULL.

    The filtering is done in the CRUD layer; here we verify the router
    passes user_id correctly and returns whatever CRUD gives back.
    """
    with patch("app.routers.alerts.ContentCRUD") as MockCRUD:
        # CRUD already filtered — returns only unacked items
        MockCRUD.return_value.get_unacked_failures.return_value = []
        result = await get_alerts(user=_USER)

    assert result["data"] == []
    MockCRUD.return_value.get_unacked_failures.assert_called_once_with(user_id="user-123")


async def test_get_alerts_scoped_to_user():
    """GET /alerts passes the correct user_id — other user's alerts not returned."""
    with patch("app.routers.alerts.ContentCRUD") as MockCRUD:
        MockCRUD.return_value.get_unacked_failures.return_value = []
        await get_alerts(user=_OTHER_USER)

    MockCRUD.return_value.get_unacked_failures.assert_called_once_with(user_id="other-456")


# ---------------------------------------------------------------------------
# POST /alerts/{id}/ack — acknowledge a failure
# ---------------------------------------------------------------------------

async def test_ack_alert_calls_ack_failure():
    """POST /alerts/{id}/ack calls ack_failure with correct args."""
    with patch("app.routers.alerts.ContentCRUD") as MockCRUD:
        MockCRUD.return_value.ack_failure.return_value = None
        result = await ack_alert(content_id="c-1", user=_USER)

    assert result["data"] == {"acknowledged": True}
    assert result["error"] is None
    MockCRUD.return_value.ack_failure.assert_called_once_with(
        content_id="c-1", user_id="user-123"
    )


async def test_ack_alert_uses_correct_user_id():
    """POST /alerts/{id}/ack uses the authenticated user's id, not any other."""
    with patch("app.routers.alerts.ContentCRUD") as MockCRUD:
        MockCRUD.return_value.ack_failure.return_value = None
        await ack_alert(content_id="c-99", user=_OTHER_USER)

    MockCRUD.return_value.ack_failure.assert_called_once_with(
        content_id="c-99", user_id="other-456"
    )
