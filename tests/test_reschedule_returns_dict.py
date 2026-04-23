"""Tests for reschedule_all_platforms returning dict[str, str | None] (Phase 3.2/3.3)."""

import pytest

from app.services.blotato_publisher import reschedule_all_platforms
from app.services.blotato_client import BlotatoAPIError


# ---------------------------------------------------------------------------
# Fake client with optional per-platform failures
# ---------------------------------------------------------------------------

class _FakeClientWithReschedule:
    """Fake BlotatoClient supporting per-platform reschedule failures.

    Pass failures={"facebook": BlotatoAPIError("...")} to simulate errors.
    """

    def __init__(self, failures: dict | None = None):
        self.failures = failures or {}
        self.reschedule_calls: list[dict] = []

    async def reschedule_post(self, schedule_id: str, new_scheduled_time: str) -> None:
        # Determine which platform this schedule_id belongs to by reverse-looking
        # — we store the schedule_id in the call record first, then check failures
        # The failures dict is keyed by platform, so we need a lookup approach.
        # For simplicity: failures keyed by schedule_id directly in these tests.
        self.reschedule_calls.append({
            "schedule_id": schedule_id,
            "new_scheduled_time": new_scheduled_time,
        })
        if schedule_id in self.failures:
            raise self.failures[schedule_id]


# ---------------------------------------------------------------------------
# All platforms succeed → dict with None values
# ---------------------------------------------------------------------------

async def test_reschedule_all_platforms_returns_dict_all_success():
    client = _FakeClientWithReschedule()
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
    }

    result = await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert isinstance(result, dict)
    assert result == {"instagram": None, "facebook": None}


# ---------------------------------------------------------------------------
# One platform fails → returns error string for that platform
# ---------------------------------------------------------------------------

async def test_reschedule_all_platforms_one_fails_returns_error():
    client = _FakeClientWithReschedule(
        failures={"sub-fb-456": BlotatoAPIError("HTTP 422: bad request")}
    )
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
    }

    result = await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert result["instagram"] is None
    assert "HTTP 422" in result["facebook"]


# ---------------------------------------------------------------------------
# All platforms fail → all entries have error strings, no exception raised
# ---------------------------------------------------------------------------

async def test_reschedule_all_platforms_all_fail_no_exception():
    client = _FakeClientWithReschedule(
        failures={
            "sub-ig-123": BlotatoAPIError("HTTP 503: ig down"),
            "sub-fb-456": BlotatoAPIError("HTTP 503: fb down"),
        }
    )
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
    }

    # Must NOT raise — errors are returned, not raised
    result = await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert "HTTP 503: ig down" in result["instagram"]
    assert "HTTP 503: fb down" in result["facebook"]


# ---------------------------------------------------------------------------
# Platform with no schedule_id is skipped (not in result dict)
# ---------------------------------------------------------------------------

async def test_reschedule_all_platforms_skips_entry_without_id():
    client = _FakeClientWithReschedule()
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": None, "status": "failed", "error": "original error"},
    }

    result = await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    # facebook has no id → should not appear in result dict
    assert "instagram" in result
    assert "facebook" not in result
    assert result["instagram"] is None


# ---------------------------------------------------------------------------
# Empty blotato_post_ids → returns empty dict
# ---------------------------------------------------------------------------

async def test_reschedule_all_platforms_empty_returns_empty_dict():
    client = _FakeClientWithReschedule()

    result = await reschedule_all_platforms(
        client=client,
        blotato_post_ids={},
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert result == {}
    assert client.reschedule_calls == []
