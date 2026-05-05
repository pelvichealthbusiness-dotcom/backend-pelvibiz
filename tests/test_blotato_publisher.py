"""Tests for blotato_publisher — orchestrates Blotato post scheduling per platform."""

import pytest

from app.services.blotato_publisher import (
    publish_content,
    reschedule_all_platforms,
    cancel_all_platforms,
    validate_connections,
    to_utc_iso,
    media_type_for_platform,
    derive_publish_status,
)
from app.services.blotato_client import BlotatoAPIError


# ---------------------------------------------------------------------------
# Fake BlotatoClient — records calls, returns canned IDs or raises
# ---------------------------------------------------------------------------

class _FakeClient:
    """Fake BlotatoClient.

    Two construction modes:
    - _FakeClient("sub-1", "sub-2")          — sequential IDs (legacy)
    - _FakeClient({"instagram": "sub-1", "facebook": BlotatoAPIError("boom")})
      — per-platform responses; Exception values are raised

    Optional keyword arg:
    - status_responses: list of strings returned sequentially by get_post_status().
      Defaults to "scheduled" when the list is exhausted.
    """

    def __init__(self, *args, status_responses=None):
        if len(args) == 1 and isinstance(args[0], dict):
            self._by_platform = args[0]
            self._sequential = None
        else:
            self._by_platform = None
            self._sequential = list(args)
        self.calls: list[dict] = []
        self._status_iter = iter(status_responses or [])
        self.status_calls: list[str] = []

    async def create_post(self, *, platform, account_id, text, media_urls,
                          scheduled_time, page_id=None, playlist_ids=None, media_type=None,
                          tiktok_privacy_level=None, disable_comment=False,
                          disable_duet=False, disable_stitch=False):
        self.calls.append({
            "platform": platform,
            "account_id": account_id,
            "text": text,
            "media_urls": media_urls,
            "scheduled_time": scheduled_time,
            "page_id": page_id,
            "playlist_ids": playlist_ids,
            "media_type": media_type,
            "tiktok_privacy_level": tiktok_privacy_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
        })
        if self._by_platform is not None:
            r = self._by_platform.get(platform, "sub-default")
            if isinstance(r, Exception):
                raise r
            return r
        return self._sequential.pop(0) if self._sequential else "sub-default"

    async def get_post_status(self, post_id: str) -> str:
        self.status_calls.append(post_id)
        try:
            return next(self._status_iter)
        except StopIteration:
            return "scheduled"


# ---------------------------------------------------------------------------
# to_utc_iso — timezone conversion
# ---------------------------------------------------------------------------

def test_to_utc_iso_converts_eastern_to_utc():
    result = to_utc_iso("2026-05-01T15:00:00", "America/New_York")
    assert result == "2026-05-01T19:00:00Z"


def test_to_utc_iso_converts_los_angeles_to_utc():
    result = to_utc_iso("2026-05-01T15:00:00", "America/Los_Angeles")
    assert result == "2026-05-01T22:00:00Z"


def test_to_utc_iso_falls_back_to_utc_on_unknown_timezone():
    result = to_utc_iso("2026-05-01T12:00:00", "Invalid/Timezone")
    assert result == "2026-05-01T12:00:00Z"


# ---------------------------------------------------------------------------
# media_type_for_platform — mapping
# ---------------------------------------------------------------------------

def test_reel_maps_to_reel_string_for_instagram():
    assert media_type_for_platform("instagram", "REEL") == "reel"


def test_reel_maps_to_reel_string_for_facebook():
    assert media_type_for_platform("facebook", "REEL") == "reel"


def test_image_returns_none_for_instagram():
    assert media_type_for_platform("instagram", "IMAGE") is None


def test_reel_returns_none_for_unsupported_platform():
    assert media_type_for_platform("twitter", "REEL") is None


# ---------------------------------------------------------------------------
# publish_content — orchestrator
# ---------------------------------------------------------------------------

async def test_publish_content_calls_create_post_for_each_platform():
    client = _FakeClient("sub-ig-1", "sub-fb-1")
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-99"},
    }

    ids = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Test caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert len(ids) == 2
    assert ids["instagram"]["id"] == "sub-ig-1"
    assert ids["facebook"]["id"] == "sub-fb-1"


async def test_publish_content_skips_unsupported_platforms():
    client = _FakeClient("sub-ig-1")
    connections = {
        "instagram": {"accountId": "ig-001"},
        "snapchat": {"accountId": "snap-001"},  # not in SUPPORTED_BLOTATO_PLATFORMS
    }

    ids = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Test caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert "instagram" in ids
    assert "snapchat" not in ids
    assert len(client.calls) == 1


async def test_publish_content_passes_page_id_for_facebook():
    client = _FakeClient("sub-fb-1")
    connections = {"facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-99"}}

    await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    call = client.calls[0]
    assert call["page_id"] == "fb-page-99"
    assert call["platform"] == "facebook"


async def test_publish_content_maps_reel_media_type():
    client = _FakeClient("sub-ig-reel")
    connections = {"instagram": {"accountId": "ig-001"}}

    await publish_content(
        client=client,
        media_urls=["https://example.com/video.mp4"],
        caption="Reel caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="REEL",
    )

    assert client.calls[0]["media_type"] == "reel"


async def test_publish_content_converts_timezone_in_scheduled_time():
    client = _FakeClient("sub-1")
    connections = {"instagram": {"accountId": "ig-001"}}

    await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="America/New_York",
        media_type="IMAGE",
    )

    # 15:00 ET = 19:00 UTC
    assert client.calls[0]["scheduled_time"] == "2026-05-01T19:00:00Z"


async def test_publish_content_raises_on_empty_media_urls():
    client = _FakeClient()
    with pytest.raises(ValueError, match="media_urls"):
        await publish_content(
            client=client,
            media_urls=[],
            caption="Caption",
            connections={"instagram": {"accountId": "ig-001"}},
            scheduled_date="2026-05-01T15:00:00",
            timezone="UTC",
            media_type="IMAGE",
        )


async def test_publish_content_raises_on_empty_connections():
    client = _FakeClient()
    with pytest.raises(ValueError, match="connections"):
        await publish_content(
            client=client,
            media_urls=["https://example.com/img.jpg"],
            caption="Caption",
            connections={},
            scheduled_date="2026-05-01T15:00:00",
            timezone="UTC",
            media_type="IMAGE",
        )


async def test_publish_content_skips_platform_without_account_id():
    client = _FakeClient("sub-ig-1")
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": ""},  # empty accountId — skip
    }

    ids = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert len(ids) == 1
    assert len(client.calls) == 1
    assert client.calls[0]["platform"] == "instagram"
    assert ids["instagram"]["id"] == "sub-ig-1"


# ---------------------------------------------------------------------------
# publish_content — returns dict[str, PlatformEntry] (platform → rich dict)
# ---------------------------------------------------------------------------

async def test_publish_content_returns_dict_keyed_by_platform():
    client = _FakeClient("sub-ig-1", "sub-fb-1")
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-99"},
    }

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert isinstance(result, dict)
    assert result["instagram"]["id"] == "sub-ig-1"
    assert result["facebook"]["id"] == "sub-fb-1"


async def test_publish_content_single_platform_returns_dict():
    client = _FakeClient("sub-ig-only")
    connections = {"instagram": {"accountId": "ig-001"}}

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert result == {"instagram": {"id": "sub-ig-only", "status": "scheduled", "error": None}}


# ---------------------------------------------------------------------------
# reschedule_all_platforms
# ---------------------------------------------------------------------------

class _FakeClientWithReschedule:
    def __init__(self):
        self.reschedule_calls: list[dict] = []

    async def reschedule_post(self, schedule_id: str, new_scheduled_time: str) -> None:
        self.reschedule_calls.append({
            "schedule_id": schedule_id,
            "new_scheduled_time": new_scheduled_time,
        })


async def test_reschedule_all_platforms_calls_reschedule_for_each_id():
    client = _FakeClientWithReschedule()
    blotato_post_ids = {"instagram": "sub-ig-123", "facebook": "sub-fb-456"}

    await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert len(client.reschedule_calls) == 2
    ids_called = {c["schedule_id"] for c in client.reschedule_calls}
    assert ids_called == {"sub-ig-123", "sub-fb-456"}


async def test_reschedule_all_platforms_converts_timezone():
    client = _FakeClientWithReschedule()
    blotato_post_ids = {"instagram": "sub-ig-123"}

    await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="America/New_York",
    )

    # 15:00 ET = 19:00 UTC
    assert client.reschedule_calls[0]["new_scheduled_time"] == "2026-06-01T19:00:00Z"


async def test_reschedule_all_platforms_skips_empty_ids():
    client = _FakeClientWithReschedule()
    blotato_post_ids = {"instagram": "sub-ig-123", "facebook": ""}

    await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert len(client.reschedule_calls) == 1
    assert client.reschedule_calls[0]["schedule_id"] == "sub-ig-123"


async def test_reschedule_all_platforms_empty_dict_does_nothing():
    client = _FakeClientWithReschedule()

    await reschedule_all_platforms(
        client=client,
        blotato_post_ids={},
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert client.reschedule_calls == []


# ---------------------------------------------------------------------------
# cancel_all_platforms
# ---------------------------------------------------------------------------

class _FakeClientWithCancel:
    def __init__(self):
        self.cancel_calls: list[str] = []

    async def cancel_post(self, schedule_id: str) -> None:
        self.cancel_calls.append(schedule_id)


async def test_cancel_all_platforms_calls_cancel_for_each_id():
    client = _FakeClientWithCancel()
    blotato_post_ids = {"instagram": "sub-ig-123", "facebook": "sub-fb-456"}

    await cancel_all_platforms(client=client, blotato_post_ids=blotato_post_ids)

    assert set(client.cancel_calls) == {"sub-ig-123", "sub-fb-456"}


async def test_cancel_all_platforms_skips_empty_ids():
    client = _FakeClientWithCancel()
    blotato_post_ids = {"instagram": "sub-ig-123", "facebook": ""}

    await cancel_all_platforms(client=client, blotato_post_ids=blotato_post_ids)

    assert client.cancel_calls == ["sub-ig-123"]


async def test_cancel_all_platforms_empty_dict_does_nothing():
    client = _FakeClientWithCancel()

    await cancel_all_platforms(client=client, blotato_post_ids={})

    assert client.cancel_calls == []


# ---------------------------------------------------------------------------
# derive_publish_status — pure function (Phase 1)
# ---------------------------------------------------------------------------

def test_derive_publish_status_all_scheduled():
    results = {
        "instagram": {"id": "sub-1", "status": "scheduled", "error": None},
        "facebook": {"id": "sub-2", "status": "scheduled", "error": None},
    }
    assert derive_publish_status(results) == "scheduled"


def test_derive_publish_status_all_failed():
    results = {
        "instagram": {"id": None, "status": "failed", "error": "boom"},
        "facebook": {"id": None, "status": "failed", "error": "also boom"},
    }
    assert derive_publish_status(results) == "failed"


def test_derive_publish_status_mixed_returns_partial():
    results = {
        "instagram": {"id": "sub-1", "status": "scheduled", "error": None},
        "facebook": {"id": None, "status": "failed", "error": "boom"},
    }
    assert derive_publish_status(results) == "partial"


def test_derive_publish_status_single_scheduled():
    results = {"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}
    assert derive_publish_status(results) == "scheduled"


def test_derive_publish_status_single_failed():
    results = {"instagram": {"id": None, "status": "failed", "error": "boom"}}
    assert derive_publish_status(results) == "failed"


# ---------------------------------------------------------------------------
# publish_content — per-platform failure handling (Phase 2)
# ---------------------------------------------------------------------------

async def test_publish_content_returns_rich_dict_on_success():
    client = _FakeClient({"instagram": "sub-ig-1", "facebook": "sub-fb-1"})
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-99"},
    }

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert result["instagram"] == {"id": "sub-ig-1", "status": "scheduled", "error": None}
    assert result["facebook"] == {"id": "sub-fb-1", "status": "scheduled", "error": None}


async def test_publish_content_partial_failure_does_not_raise():
    client = _FakeClient({
        "instagram": "sub-ig-1",
        "facebook": BlotatoAPIError("API 422: bad account"),
    })
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-acc-1"},
    }

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert result["instagram"] == {"id": "sub-ig-1", "status": "scheduled", "error": None}
    assert result["facebook"]["id"] is None
    assert result["facebook"]["status"] == "failed"
    assert "API 422: bad account" in result["facebook"]["error"]


async def test_publish_content_partial_failure_saves_successful_id():
    client = _FakeClient({
        "instagram": "sub-ig-1",
        "facebook": BlotatoAPIError("boom"),
    })
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-acc-1"},
    }

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
    )

    assert result["instagram"]["id"] == "sub-ig-1"
    assert result["instagram"]["status"] == "scheduled"


async def test_publish_content_all_failed_raises():
    client = _FakeClient({
        "instagram": BlotatoAPIError("ig down"),
        "facebook": BlotatoAPIError("fb down"),
    })
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-acc-1"},
    }

    with pytest.raises(BlotatoAPIError, match="All platforms failed"):
        await publish_content(
            client=client,
            media_urls=["https://example.com/img.jpg"],
            caption="Caption",
            connections=connections,
            scheduled_date="2026-05-01T15:00:00",
            timezone="UTC",
            media_type="IMAGE",
        )


# ---------------------------------------------------------------------------
# reschedule_all_platforms — rich dict shape (Phase 2.3)
# ---------------------------------------------------------------------------

async def test_reschedule_all_platforms_handles_rich_dict():
    client = _FakeClientWithReschedule()
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
    }

    await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    ids_called = {c["schedule_id"] for c in client.reschedule_calls}
    assert ids_called == {"sub-ig-123", "sub-fb-456"}


async def test_reschedule_all_platforms_skips_failed_rich_entry():
    client = _FakeClientWithReschedule()
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": None, "status": "failed", "error": "boom"},
    }

    await reschedule_all_platforms(
        client=client,
        blotato_post_ids=blotato_post_ids,
        new_scheduled_date="2026-06-01T15:00:00",
        timezone="UTC",
    )

    assert len(client.reschedule_calls) == 1
    assert client.reschedule_calls[0]["schedule_id"] == "sub-ig-123"


# ---------------------------------------------------------------------------
# cancel_all_platforms — rich dict shape (Phase 2.4)
# ---------------------------------------------------------------------------

async def test_cancel_all_platforms_handles_rich_dict():
    client = _FakeClientWithCancel()
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": "sub-fb-456", "status": "scheduled", "error": None},
    }

    await cancel_all_platforms(client=client, blotato_post_ids=blotato_post_ids)

    assert set(client.cancel_calls) == {"sub-ig-123", "sub-fb-456"}


async def test_cancel_all_platforms_skips_failed_rich_entry():
    client = _FakeClientWithCancel()
    blotato_post_ids = {
        "instagram": {"id": "sub-ig-123", "status": "scheduled", "error": None},
        "facebook": {"id": None, "status": "failed", "error": "boom"},
    }

    await cancel_all_platforms(client=client, blotato_post_ids=blotato_post_ids)

    assert client.cancel_calls == ["sub-ig-123"]


# ---------------------------------------------------------------------------
# validate_connections — Phase 2.3 / 2.4
# ---------------------------------------------------------------------------

class _FakeClientForValidation:
    def __init__(self, accounts: list[dict] | Exception):
        self._accounts = accounts

    async def list_accounts(self) -> list[dict]:
        if isinstance(self._accounts, Exception):
            raise self._accounts
        return self._accounts


async def test_validate_all_valid_returns_full_connections():
    accounts = [{"id": "ig-001"}, {"id": "fb-001"}]
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-001"},
    }
    client = _FakeClientForValidation(accounts)

    valid, stale = await validate_connections(client, connections)

    assert valid == connections
    assert stale == []


async def test_validate_some_stale_filters_correctly():
    accounts = [{"id": "ig-001"}]  # fb-001 not present
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-001"},
    }
    client = _FakeClientForValidation(accounts)

    valid, stale = await validate_connections(client, connections)

    assert "instagram" in valid
    assert "facebook" not in valid
    assert "facebook" in stale
    assert "instagram" not in stale


async def test_validate_all_stale_returns_empty_valid():
    accounts = [{"id": "other-id"}]
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-001"},
    }
    client = _FakeClientForValidation(accounts)

    valid, stale = await validate_connections(client, connections)

    assert valid == {}
    assert set(stale) == {"instagram", "facebook"}


async def test_validate_api_error_returns_all_connections_best_effort():
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-001"},
    }
    client = _FakeClientForValidation(BlotatoAPIError("network failure"))

    valid, stale = await validate_connections(client, connections)

    assert valid == connections
    assert stale == []


# ---------------------------------------------------------------------------
# Bug 3 fix — publish_content polls get_post_status after create_post
# ---------------------------------------------------------------------------

async def test_publish_content_calls_get_post_status_after_create():
    """Bug 3: After create_post, publisher must verify schedule via GET /posts/:id."""
    client = _FakeClient("sub-ig-1", status_responses=["scheduled"])
    connections = {"instagram": {"accountId": "ig-001"}}

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        _poll_interval=0,
        _poll_timeout=999,
    )

    assert result["instagram"]["status"] == "scheduled"
    assert "sub-ig-1" in client.status_calls


async def test_publish_content_treats_failed_blotato_status_as_platform_error():
    """Bug 3: A 'failed' status from GET /posts/:id must propagate as per-platform error.

    Uses two platforms so instagram's verify-failure is a partial failure (no raise).
    """
    client = _FakeClient(
        {"instagram": "sub-ig-1", "facebook": "sub-fb-1"},
        status_responses=["failed", "scheduled"],
    )
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-001"},
    }

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        _poll_interval=0,
        _poll_timeout=999,
    )

    assert result["instagram"]["status"] == "failed"
    # Phase 1: post_id is preserved even when verify fails (was None before)
    assert result["instagram"]["id"] == "sub-ig-1"
    assert "failed" in result["instagram"]["error"].lower()
    assert result["facebook"]["status"] == "scheduled"


async def test_publish_content_polling_timeout_is_optimistic_success():
    """Bug 3: If Blotato keeps returning 'in-progress' past timeout, treat as success."""
    client = _FakeClient("sub-ig-1", status_responses=["in-progress", "in-progress", "in-progress"])
    connections = {"instagram": {"accountId": "ig-001"}}

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        _poll_interval=0,
        _poll_timeout=0,
    )

    assert result["instagram"]["status"] == "scheduled"
    assert result["instagram"]["id"] == "sub-ig-1"


async def test_publish_content_polling_retries_until_scheduled():
    """Bug 3: Publisher polls until status exits 'in-progress'."""
    client = _FakeClient("sub-ig-1", status_responses=["in-progress", "in-progress", "scheduled"])
    connections = {"instagram": {"accountId": "ig-001"}}

    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        _poll_interval=0,
        _poll_timeout=999,
    )

    assert result["instagram"]["status"] == "scheduled"
    assert len(client.status_calls) == 3


# ---------------------------------------------------------------------------
# Phase 1 — Preserve post_id on verify failure
# ---------------------------------------------------------------------------

async def test_publish_content_preserves_post_id_on_verify_failure():
    """When verify fails, the post_id from create_post must be preserved in the failed entry."""
    client = _FakeClient(
        {"instagram": "sub-ig-1", "facebook": "sub-fb-1"},
        status_responses=["failed", "scheduled"],
    )
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-001"},
    }
    result = await publish_content(
        client=client,
        media_urls=["https://example.com/img.jpg"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="IMAGE",
        _poll_interval=0,
        _poll_timeout=999,
    )
    # instagram verify failed — but sub_id must be preserved
    assert result["instagram"]["id"] == "sub-ig-1"
    assert result["instagram"]["status"] == "failed"
    # facebook succeeded normally
    assert result["facebook"]["status"] == "scheduled"


# ---------------------------------------------------------------------------
# Phase 4 — TikTok Required Fields (publisher side)
# ---------------------------------------------------------------------------

async def test_publish_content_passes_tiktok_privacy_level():
    client = _FakeClient({"tiktok": "sub-tk-1"})
    connections = {"tiktok": {"accountId": "tk-001", "tiktokPrivacyLevel": "SELF_ONLY"}}
    await publish_content(
        client=client,
        media_urls=["https://example.com/video.mp4"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="VIDEO",
        _poll_interval=0, _poll_timeout=999,
    )
    call = client.calls[0]
    assert call["tiktok_privacy_level"] == "SELF_ONLY"


async def test_publish_content_tiktok_default_privacy_when_not_set():
    client = _FakeClient({"tiktok": "sub-tk-1"})
    connections = {"tiktok": {"accountId": "tk-001"}}
    await publish_content(
        client=client,
        media_urls=["https://example.com/video.mp4"],
        caption="Caption",
        connections=connections,
        scheduled_date="2026-05-01T15:00:00",
        timezone="UTC",
        media_type="VIDEO",
        _poll_interval=0, _poll_timeout=999,
    )
    call = client.calls[0]
    assert call["tiktok_privacy_level"] is None  # publisher passes None; client defaults it
