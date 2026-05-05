"""Tests for GET /admin/publish-logs endpoint (Phase 1 — admin-published-view)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.routers.admin import list_publish_logs
from app.core.auth import UserContext


_ADMIN = UserContext(user_id="admin-123", email="admin@example.com", role="admin", token="tok")


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_db_mock(rows=None, count=0, profile_rows=None):
    """Return a MagicMock that satisfies all Supabase chained calls."""
    db = MagicMock()

    main_result = MagicMock()
    main_result.data = rows or []
    main_result.count = count

    count_result = MagicMock()
    count_result.data = []
    count_result.count = count

    profile_result = MagicMock()
    profile_result.data = profile_rows or []

    main_chain = MagicMock()
    main_chain.select.return_value = main_chain
    main_chain.eq.return_value = main_chain
    main_chain.not_ = MagicMock()
    main_chain.not_.is_.return_value = main_chain
    main_chain.in_.return_value = main_chain
    main_chain.order.return_value = main_chain
    main_chain.limit.return_value = main_chain
    main_chain.offset.return_value = main_chain
    main_chain.execute.return_value = main_result

    profile_chain = MagicMock()
    profile_chain.select.return_value = profile_chain
    profile_chain.in_.return_value = profile_chain
    profile_chain.execute.return_value = profile_result

    def table_router(name):
        if name == "profiles":
            return profile_chain
        return main_chain

    db.table.side_effect = table_router
    return db, main_chain, main_result, count_result


_ROW_SCHEDULED = {
    "id": "row-1",
    "user_id": "user-aaa",
    "agent_type": "post",
    "title": "Scheduled post",
    "caption": "Caption A",
    "media_urls": [],
    "scheduled_date": "2026-05-01T10:00:00Z",
    "publish_status": "scheduled",
    "publish_error": None,
    "published_at": None,
    "blotato_post_ids": None,
    "failure_notified_at": None,
    "created_at": "2026-04-30T10:00:00Z",
}

_ROW_PUBLISHED = {
    "id": "row-2",
    "user_id": "user-bbb",
    "agent_type": "reel",
    "title": "Published post",
    "caption": "Caption B",
    "media_urls": ["https://example.com/img.jpg"],
    "scheduled_date": "2026-05-02T10:00:00Z",
    "publish_status": "published",
    "publish_error": None,
    "published_at": "2026-05-02T11:00:00Z",
    "blotato_post_ids": {"instagram": {"id": "ig-1", "status": "published"}},
    "failure_notified_at": None,
    "created_at": "2026-05-01T10:00:00Z",
}

_ROW_FAILED = {
    "id": "row-3",
    "user_id": "user-aaa",
    "agent_type": "post",
    "title": "Failed post",
    "caption": "Caption C",
    "media_urls": [],
    "scheduled_date": "2026-05-03T10:00:00Z",
    "publish_status": "failed",
    "publish_error": "API timeout",
    "published_at": None,
    "blotato_post_ids": None,
    "failure_notified_at": "2026-05-03T12:00:00Z",
    "created_at": "2026-05-02T10:00:00Z",
}

_ROW_PARTIAL = {
    "id": "row-4",
    "user_id": "user-ccc",
    "agent_type": "carousel",
    "title": "Partial post",
    "caption": "Caption D",
    "media_urls": [],
    "scheduled_date": "2026-05-04T10:00:00Z",
    "publish_status": "partial",
    "publish_error": "One platform failed",
    "published_at": "2026-05-04T11:00:00Z",
    "blotato_post_ids": {
        "instagram": {"id": "ig-2", "status": "published"},
        "tiktok": {"id": None, "status": "failed"},
    },
    "failure_notified_at": None,
    "created_at": "2026-05-03T10:00:00Z",
}


# ---------------------------------------------------------------------------
# 1.1 — status=all returns all rows (no filter)
# ---------------------------------------------------------------------------

async def test_status_all_returns_all_rows():
    all_rows = [_ROW_SCHEDULED, _ROW_PUBLISHED, _ROW_FAILED, _ROW_PARTIAL]
    db, chain, result, _ = _make_db_mock(rows=all_rows, count=4)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status="all", user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert response["data"] is not None
    assert len(response["data"]) == 4
    assert response["meta"]["total"] == 4


# ---------------------------------------------------------------------------
# 1.2 — status=scheduled returns only scheduled rows
# ---------------------------------------------------------------------------

async def test_status_scheduled_filters_correctly():
    scheduled_rows = [_ROW_SCHEDULED]
    db, chain, result, _ = _make_db_mock(rows=scheduled_rows, count=1)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status="scheduled", user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert len(response["data"]) == 1
    assert response["data"][0]["publish_status"] == "scheduled"
    # Assert .eq("publish_status", "scheduled") was called on the chain
    chain.eq.assert_any_call("publish_status", "scheduled")


# ---------------------------------------------------------------------------
# 1.3 — status=published applies not_.is_("published_at", "null")
# ---------------------------------------------------------------------------

async def test_status_published_filters_by_published_at():
    published_rows = [_ROW_PUBLISHED, _ROW_PARTIAL]
    db, chain, result, _ = _make_db_mock(rows=published_rows, count=2)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status="published", user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert len(response["data"]) == 2
    # Assert not_.is_("published_at", "null") was called (not eq)
    chain.not_.is_.assert_any_call("published_at", "null")
    # Assert eq("publish_status", ...) was NOT called with "published"
    for call_args in chain.eq.call_args_list:
        args = call_args[0]
        assert not (args[0] == "publish_status" and args[1] == "published"), (
            "status=published should use not_.is_(published_at) not eq(publish_status)"
        )


# ---------------------------------------------------------------------------
# 1.4 — status=partial filters correctly
# ---------------------------------------------------------------------------

async def test_status_partial_filters_correctly():
    partial_rows = [_ROW_PARTIAL]
    db, chain, result, _ = _make_db_mock(rows=partial_rows, count=1)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status="partial", user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert len(response["data"]) == 1
    chain.eq.assert_any_call("publish_status", "partial")


# ---------------------------------------------------------------------------
# 1.5 — status=failed filters correctly
# ---------------------------------------------------------------------------

async def test_status_failed_filters_correctly():
    failed_rows = [_ROW_FAILED]
    db, chain, result, _ = _make_db_mock(rows=failed_rows, count=1)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status="failed", user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert len(response["data"]) == 1
    chain.eq.assert_any_call("publish_status", "failed")


# ---------------------------------------------------------------------------
# 1.6 — Response envelope has correct shape
# ---------------------------------------------------------------------------

async def test_response_envelope_shape():
    db, _, _, _ = _make_db_mock(rows=[_ROW_PUBLISHED], count=1)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status=None, user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert "data" in response
    assert "meta" in response

    meta = response["meta"]
    assert "total" in meta
    assert "page" in meta
    assert "limit" in meta
    assert "total_pages" in meta

    assert isinstance(meta["total"], int)
    assert isinstance(meta["page"], int)
    assert isinstance(meta["limit"], int)
    assert isinstance(meta["total_pages"], int)


# ---------------------------------------------------------------------------
# 1.7 — Items include required fields (even when null)
# ---------------------------------------------------------------------------

async def test_items_include_required_fields():
    db, _, _, _ = _make_db_mock(rows=[_ROW_FAILED], count=1)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status=None, user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert len(response["data"]) == 1
    item = response["data"][0]

    required_fields = [
        "publish_error",
        "published_at",
        "blotato_post_ids",
        "failure_notified_at",
        "display_name",
    ]
    for field in required_fields:
        assert field in item, f"Expected field '{field}' to be present in item"


# ---------------------------------------------------------------------------
# 1.8 — Items ordered by published_at DESC
# ---------------------------------------------------------------------------

async def test_items_ordered_by_published_at_desc():
    db, chain, _, _ = _make_db_mock(
        rows=[_ROW_PUBLISHED, _ROW_SCHEDULED], count=2
    )

    with patch("app.routers.admin.get_service_client", return_value=db):
        await list_publish_logs(
            status=None, user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    chain.order.assert_any_call("published_at", desc=True)


# ---------------------------------------------------------------------------
# 1.9 — Profile join: user with full_name → display_name set
# ---------------------------------------------------------------------------

async def test_profile_join_attaches_display_name():
    rows = [_ROW_PUBLISHED]  # user_id = "user-bbb"
    profile_rows = [{"id": "user-bbb", "full_name": "Jane Doe"}]
    db, _, _, _ = _make_db_mock(rows=rows, count=1, profile_rows=profile_rows)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status=None, user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    item = response["data"][0]
    assert item["display_name"] == "Jane Doe"


# ---------------------------------------------------------------------------
# 1.10 — User with no profile → display_name=None, no 500 error
# ---------------------------------------------------------------------------

async def test_missing_profile_returns_null_display_name():
    rows = [_ROW_SCHEDULED]  # user_id = "user-aaa"
    profile_rows = []  # no profile for user-aaa
    db, _, _, _ = _make_db_mock(rows=rows, count=1, profile_rows=profile_rows)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status=None, user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    # Must not raise, and display_name must be None
    item = response["data"][0]
    assert item["display_name"] is None


# ---------------------------------------------------------------------------
# 1.11 — Pagination: second page computed correctly
# ---------------------------------------------------------------------------

async def test_pagination_second_page():
    # 20 total items, limit=10, offset=10 → page=2
    rows = [_ROW_PUBLISHED] * 10
    db, _, _, _ = _make_db_mock(rows=rows, count=20)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status=None, user_id=None, limit=10, offset=10, admin=_ADMIN
        )

    meta = response["meta"]
    assert meta["page"] == 2
    assert meta["limit"] == 10
    assert meta["total"] == 20
    assert meta["total_pages"] == 2
    assert len(response["data"]) == 10


# ---------------------------------------------------------------------------
# 1.12 — Default pagination params
# ---------------------------------------------------------------------------

async def test_default_pagination_params():
    db, chain, _, _ = _make_db_mock(rows=[], count=0)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status=None, user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    meta = response["meta"]
    assert meta["page"] == 1
    assert meta["limit"] == 50

    # Verify limit and offset were applied to chain
    chain.limit.assert_called_with(50)
    chain.offset.assert_called_with(0)


# ---------------------------------------------------------------------------
# 1.13 — status=None (no filter param) returns all rows
# ---------------------------------------------------------------------------

async def test_status_none_returns_all_rows():
    all_rows = [_ROW_SCHEDULED, _ROW_PUBLISHED, _ROW_FAILED]
    db, chain, _, _ = _make_db_mock(rows=all_rows, count=3)

    with patch("app.routers.admin.get_service_client", return_value=db):
        response = await list_publish_logs(
            status=None, user_id=None, limit=50, offset=0, admin=_ADMIN
        )

    assert len(response["data"]) == 3
    # .eq("publish_status", ...) should NOT be called for status=None
    for call_args in chain.eq.call_args_list:
        args = call_args[0]
        assert args[0] != "publish_status", (
            "status=None should not apply any publish_status filter"
        )
