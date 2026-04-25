"""Tests for BlotatoClient — HTTP wrapper over the Blotato v2 API."""

import json
import httpx
import pytest

from app.services.blotato_client import BlotatoClient, BlotatoAPIError


# ---------------------------------------------------------------------------
# Fake HTTP transport — returns canned responses from a queue
# ---------------------------------------------------------------------------

class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, *responses: httpx.Response):
        self._queue = list(responses)
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append({
            "method": request.method,
            "url": str(request.url),
            "body": json.loads(request.content) if request.content else {},
            "headers": dict(request.headers),
        })
        if not self._queue:
            return httpx.Response(500, json={"error": "no more responses queued"})
        return self._queue.pop(0)


def _response(status: int, data: dict) -> httpx.Response:
    return httpx.Response(status, json=data)


def _make_client(max_retries: int, *responses: httpx.Response) -> tuple[BlotatoClient, _FakeTransport]:
    transport = _FakeTransport(*responses)
    client = BlotatoClient(
        api_key="test-key",
        max_retries=max_retries,
        transport=transport,
    )
    return client, transport


# ---------------------------------------------------------------------------
# create_post — happy path
# ---------------------------------------------------------------------------

async def test_create_post_returns_submission_id():
    client, transport = _make_client(
        1,
        _response(200, {"id": "sub-abc123"}),
    )

    post_id = await client.create_post(
        platform="instagram",
        account_id="ig-001",
        text="Hello world",
        media_urls=["https://example.com/img.jpg"],
        scheduled_time="2026-05-01T20:00:00Z",
    )

    assert post_id == "sub-abc123"


async def test_create_post_sends_correct_payload():
    client, transport = _make_client(
        1,
        _response(200, {"id": "sub-xyz"}),
    )

    await client.create_post(
        platform="instagram",
        account_id="ig-001",
        text="Caption here",
        media_urls=["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg"],
        scheduled_time="2026-05-01T20:00:00Z",
        media_type="reel",
    )

    sent = transport.requests[0]["body"]
    assert sent["accountId"] == "ig-001"
    assert sent["platform"] == "instagram"
    assert sent["text"] == "Caption here"
    assert sent["mediaUrls"] == ["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg"]
    assert sent["scheduledTime"] == "2026-05-01T20:00:00Z"
    assert sent["mediaType"] == "reel"


async def test_create_post_includes_page_id_for_facebook():
    client, transport = _make_client(
        1,
        _response(200, {"id": "sub-fb-1"}),
    )

    await client.create_post(
        platform="facebook",
        account_id="fb-acc-1",
        text="Facebook post",
        media_urls=["https://example.com/img.jpg"],
        scheduled_time="2026-05-01T20:00:00Z",
        page_id="fb-page-99",
    )

    sent = transport.requests[0]["body"]
    assert sent["pageId"] == "fb-page-99"
    assert sent["accountId"] == "fb-acc-1"


async def test_create_post_includes_playlist_ids_for_youtube():
    client, transport = _make_client(
        1,
        _response(200, {"id": "sub-yt-1"}),
    )

    await client.create_post(
        platform="youtube",
        account_id="yt-acc-1",
        text="YouTube post",
        media_urls=["https://example.com/video.mp4"],
        scheduled_time="2026-05-01T20:00:00Z",
        playlist_ids=["pl-1", "pl-2"],
    )

    sent = transport.requests[0]["body"]
    assert sent["playlistIds"] == ["pl-1", "pl-2"]


async def test_create_post_omits_optional_fields_when_not_provided():
    client, transport = _make_client(
        1,
        _response(200, {"id": "sub-minimal"}),
    )

    await client.create_post(
        platform="instagram",
        account_id="ig-001",
        text="Minimal",
        media_urls=["https://example.com/img.jpg"],
        scheduled_time="2026-05-01T20:00:00Z",
    )

    sent = transport.requests[0]["body"]
    assert "pageId" not in sent
    assert "mediaType" not in sent


# ---------------------------------------------------------------------------
# create_post — error handling
# ---------------------------------------------------------------------------

async def test_create_post_raises_on_4xx_without_retry():
    client, transport = _make_client(
        3,
        _response(422, {"error": "invalid account"}),
    )

    with pytest.raises(BlotatoAPIError, match="422"):
        await client.create_post(
            platform="instagram",
            account_id="bad-id",
            text="Test",
            media_urls=["https://example.com/img.jpg"],
            scheduled_time="2026-05-01T20:00:00Z",
        )

    # 4xx should NOT retry — only one request sent
    assert len(transport.requests) == 1


async def test_create_post_retries_on_5xx_then_succeeds():
    client, transport = _make_client(
        3,
        _response(503, {"error": "service unavailable"}),
        _response(200, {"id": "sub-retry-ok"}),
    )

    post_id = await client.create_post(
        platform="instagram",
        account_id="ig-001",
        text="Retry test",
        media_urls=["https://example.com/img.jpg"],
        scheduled_time="2026-05-01T20:00:00Z",
    )

    assert post_id == "sub-retry-ok"
    assert len(transport.requests) == 2


async def test_create_post_raises_after_max_retries_on_5xx():
    client, transport = _make_client(
        2,
        _response(500, {"error": "internal error"}),
        _response(500, {"error": "still broken"}),
    )

    with pytest.raises(BlotatoAPIError):
        await client.create_post(
            platform="instagram",
            account_id="ig-001",
            text="Will fail",
            media_urls=["https://example.com/img.jpg"],
            scheduled_time="2026-05-01T20:00:00Z",
        )

    assert len(transport.requests) == 2


async def test_create_post_sends_blotato_api_key_header():
    client, transport = _make_client(
        1,
        _response(200, {"id": "sub-header-check"}),
    )

    await client.create_post(
        platform="instagram",
        account_id="ig-001",
        text="Header check",
        media_urls=["https://example.com/img.jpg"],
        scheduled_time="2026-05-01T20:00:00Z",
    )

    headers = transport.requests[0]["headers"]
    assert headers.get("blotato-api-key") == "test-key"


# ---------------------------------------------------------------------------
# reschedule_post — happy path
# ---------------------------------------------------------------------------

async def test_reschedule_post_sends_patch_request():
    client, transport = _make_client(
        1,
        _response(200, {}),
    )

    await client.reschedule_post("sched-123", "2026-06-01T10:00:00Z")

    req = transport.requests[0]
    assert req["method"] == "PATCH"
    assert req["url"].endswith("/schedules/sched-123")
    assert req["body"] == {"scheduledTime": "2026-06-01T10:00:00Z"}


async def test_reschedule_post_sends_api_key_header():
    client, transport = _make_client(
        1,
        _response(200, {}),
    )

    await client.reschedule_post("sched-abc", "2026-06-01T10:00:00Z")

    assert transport.requests[0]["headers"].get("blotato-api-key") == "test-key"


async def test_reschedule_post_raises_on_4xx_without_retry():
    client, transport = _make_client(
        3,
        _response(404, {"error": "not found"}),
    )

    with pytest.raises(BlotatoAPIError, match="404"):
        await client.reschedule_post("bad-id", "2026-06-01T10:00:00Z")

    assert len(transport.requests) == 1


async def test_reschedule_post_retries_on_5xx_then_succeeds():
    client, transport = _make_client(
        3,
        _response(503, {"error": "unavailable"}),
        _response(200, {}),
    )

    await client.reschedule_post("sched-123", "2026-06-01T10:00:00Z")

    assert len(transport.requests) == 2


async def test_reschedule_post_raises_after_max_retries_on_5xx():
    client, transport = _make_client(
        2,
        _response(500, {"error": "error"}),
        _response(500, {"error": "still error"}),
    )

    with pytest.raises(BlotatoAPIError):
        await client.reschedule_post("sched-123", "2026-06-01T10:00:00Z")

    assert len(transport.requests) == 2


# ---------------------------------------------------------------------------
# cancel_post — happy path
# ---------------------------------------------------------------------------

async def test_cancel_post_sends_delete_request():
    client, transport = _make_client(
        1,
        _response(200, {}),
    )

    await client.cancel_post("sched-del-123")

    req = transport.requests[0]
    assert req["method"] == "DELETE"
    assert req["url"].endswith("/schedules/sched-del-123")


async def test_cancel_post_silences_404():
    client, transport = _make_client(
        1,
        _response(404, {"error": "already gone"}),
    )

    # Should not raise
    await client.cancel_post("sched-gone")

    assert len(transport.requests) == 1


async def test_cancel_post_raises_on_other_4xx():
    client, transport = _make_client(
        3,
        _response(403, {"error": "forbidden"}),
    )

    with pytest.raises(BlotatoAPIError, match="403"):
        await client.cancel_post("sched-forbidden")

    assert len(transport.requests) == 1


async def test_cancel_post_retries_on_5xx_then_succeeds():
    client, transport = _make_client(
        3,
        _response(500, {"error": "error"}),
        _response(200, {}),
    )

    await client.cancel_post("sched-retry")

    assert len(transport.requests) == 2


async def test_cancel_post_raises_after_max_retries_on_5xx():
    client, transport = _make_client(
        2,
        _response(503, {"error": "unavailable"}),
        _response(503, {"error": "still unavailable"}),
    )

    with pytest.raises(BlotatoAPIError):
        await client.cancel_post("sched-fail")

    assert len(transport.requests) == 2


# ---------------------------------------------------------------------------
# get_schedule — Phase 2.1 / 2.2
# ---------------------------------------------------------------------------

async def test_get_schedule_returns_dict_on_200():
    client, transport = _make_client(
        1,
        _response(200, {"id": "sched-abc", "status": "scheduled"}),
    )

    result = await client.get_schedule("sched-abc")

    assert result["id"] == "sched-abc"
    assert result["status"] == "scheduled"
    req = transport.requests[0]
    assert req["method"] == "GET"
    assert req["url"].endswith("/schedules/sched-abc")


async def test_get_schedule_raises_schedule_not_found_on_404():
    from app.services.blotato_client import BlotatoScheduleNotFound

    client, transport = _make_client(
        1,
        _response(404, {"error": "not found"}),
    )

    with pytest.raises(BlotatoScheduleNotFound):
        await client.get_schedule("sched-gone")

    assert len(transport.requests) == 1


async def test_get_schedule_raises_api_error_on_422_not_schedule_not_found():
    from app.services.blotato_client import BlotatoScheduleNotFound

    client, transport = _make_client(
        3,
        _response(422, {"error": "bad request"}),
    )

    with pytest.raises(BlotatoAPIError) as exc_info:
        await client.get_schedule("sched-bad")

    # Must be BlotatoAPIError but NOT BlotatoScheduleNotFound
    assert not isinstance(exc_info.value, BlotatoScheduleNotFound)
    assert len(transport.requests) == 1


async def test_get_schedule_retries_on_500_then_returns():
    client, transport = _make_client(
        3,
        _response(500, {"error": "server error"}),
        _response(200, {"id": "sched-retry", "status": "published"}),
    )

    result = await client.get_schedule("sched-retry")

    assert result["status"] == "published"
    assert len(transport.requests) == 2


async def test_get_schedule_raises_after_max_retries_on_500():
    client, transport = _make_client(
        2,
        _response(500, {"error": "error"}),
        _response(500, {"error": "still error"}),
    )

    with pytest.raises(BlotatoAPIError):
        await client.get_schedule("sched-fail")

    assert len(transport.requests) == 2


# ---------------------------------------------------------------------------
# list_accounts — Phase 2.1 / 2.2
# ---------------------------------------------------------------------------

async def test_list_accounts_returns_list_on_200():
    accounts = [{"id": "acc-1", "platform": "instagram"}]
    client, transport = _make_client(
        1,
        _response(200, accounts),
    )

    result = await client.list_accounts()

    assert result == accounts
    req = transport.requests[0]
    assert req["method"] == "GET"
    assert req["url"].endswith("/users/me/accounts")


async def test_list_accounts_returns_inner_list_when_accounts_key():
    accounts = [{"id": "acc-1"}, {"id": "acc-2"}]
    client, transport = _make_client(
        1,
        _response(200, {"accounts": accounts}),
    )

    result = await client.list_accounts()

    assert result == accounts


async def test_list_accounts_retries_on_500_then_succeeds():
    accounts = [{"id": "acc-1"}]
    client, transport = _make_client(
        3,
        _response(500, {"error": "server error"}),
        _response(200, accounts),
    )

    result = await client.list_accounts()

    assert result == accounts
    assert len(transport.requests) == 2


async def test_list_accounts_raises_on_401():
    client, transport = _make_client(
        3,
        _response(401, {"error": "unauthorized"}),
    )

    with pytest.raises(BlotatoAPIError, match="401"):
        await client.list_accounts()

    # 4xx should not retry
    assert len(transport.requests) == 1
