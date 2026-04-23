"""Tests for publish_audit.log_attempt (Phase 1.2/1.3)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helper: build a chain mock for db.table(...).insert(...).execute()
# ---------------------------------------------------------------------------

def _make_db_mock(raise_on_execute: Exception | None = None):
    """Return a mock that chains table → insert → execute."""
    db = MagicMock()
    table_mock = MagicMock()
    insert_mock = MagicMock()
    execute_mock = MagicMock()

    db.table.return_value = table_mock
    table_mock.insert.return_value = insert_mock
    if raise_on_execute:
        execute_mock.side_effect = raise_on_execute
    insert_mock.execute = execute_mock
    return db, table_mock, insert_mock, execute_mock


# ---------------------------------------------------------------------------
# Happy path: insert called with correct minimal payload
# ---------------------------------------------------------------------------

async def test_log_attempt_happy_path_inserts_correct_payload():
    db, table_mock, insert_mock, execute_mock = _make_db_mock()

    with patch("app.services.publish_audit.get_service_client", return_value=db):
        from app.services.publish_audit import log_attempt
        await log_attempt(
            content_id="content-abc",
            user_id="user-xyz",
            action="schedule",
            platform="instagram",
            status="success",
        )

    db.table.assert_called_once_with("publish_attempts")
    payload = table_mock.insert.call_args[0][0]
    assert payload["content_id"] == "content-abc"
    assert payload["user_id"] == "user-xyz"
    assert payload["action"] == "schedule"
    assert payload["platform"] == "instagram"
    assert payload["status"] == "success"
    assert "error" not in payload
    assert "blotato_post_id" not in payload
    assert "duration_ms" not in payload
    execute_mock.assert_called_once()


# ---------------------------------------------------------------------------
# With error field: error included in payload
# ---------------------------------------------------------------------------

async def test_log_attempt_with_error_field():
    db, table_mock, insert_mock, execute_mock = _make_db_mock()

    with patch("app.services.publish_audit.get_service_client", return_value=db):
        from app.services.publish_audit import log_attempt
        await log_attempt(
            content_id="content-abc",
            user_id="user-xyz",
            action="schedule",
            platform="instagram",
            status="failed",
            error="HTTP 422: bad account",
        )

    payload = table_mock.insert.call_args[0][0]
    assert payload["status"] == "failed"
    assert payload["error"] == "HTTP 422: bad account"


# ---------------------------------------------------------------------------
# With blotato_post_id and duration_ms: optional fields included
# ---------------------------------------------------------------------------

async def test_log_attempt_with_optional_fields():
    db, table_mock, insert_mock, execute_mock = _make_db_mock()

    with patch("app.services.publish_audit.get_service_client", return_value=db):
        from app.services.publish_audit import log_attempt
        await log_attempt(
            content_id="content-abc",
            user_id="user-xyz",
            action="republish",
            platform="facebook",
            status="success",
            blotato_post_id="sched-999",
            duration_ms=450,
        )

    payload = table_mock.insert.call_args[0][0]
    assert payload["blotato_post_id"] == "sched-999"
    assert payload["duration_ms"] == 450


# ---------------------------------------------------------------------------
# DB raises: no exception propagates, WARNING logged
# ---------------------------------------------------------------------------

async def test_log_attempt_db_failure_no_exception_propagates(caplog):
    db, table_mock, insert_mock, execute_mock = _make_db_mock(
        raise_on_execute=RuntimeError("connection refused")
    )

    with patch("app.services.publish_audit.get_service_client", return_value=db):
        from app.services import publish_audit
        # Reload to avoid module-level import caching issues
        import importlib
        importlib.reload(publish_audit)
        with caplog.at_level(logging.WARNING, logger="app.services.publish_audit"):
            # Must NOT raise
            await publish_audit.log_attempt(
                content_id="content-abc",
                user_id="user-xyz",
                action="schedule",
                platform="instagram",
                status="failed",
                error="boom",
            )

    # WARNING was logged
    assert any("publish_audit" in r.name or "log_attempt" in r.message.lower()
               or "connection refused" in r.message.lower()
               for r in caplog.records), f"Expected WARNING, got: {caplog.records}"
