"""Blotato v2 API client — HTTP wrapper for post scheduling."""

from __future__ import annotations

import asyncio
import httpx


BLOTATO_BASE_URL = "https://backend.blotato.com/v2"


class BlotatoAPIError(Exception):
    """Non-2xx response from Blotato API (not retried for 4xx)."""


class BlotatoScheduleNotFound(BlotatoAPIError):
    """404 from GET /schedules/{id} — post already published or expired."""


class BlotatoClient:
    """Async HTTP client for the Blotato v2 REST API.

    Inject `transport` for testing (fake transport with canned responses).
    In production, leave `transport=None` and the client creates real connections.
    """

    def __init__(
        self,
        api_key: str,
        max_retries: int = 3,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._max_retries = max_retries
        self._http = httpx.AsyncClient(
            base_url=BLOTATO_BASE_URL,
            headers={"blotato-api-key": api_key},
            timeout=timeout,
            transport=transport,
        )

    async def create_post(
        self,
        *,
        platform: str,
        account_id: str,
        text: str,
        media_urls: list[str],
        scheduled_time: str,
        page_id: str | None = None,
        playlist_ids: list[str] | None = None,
        media_type: str | None = None,
    ) -> str:
        """Schedule a post on Blotato. Returns the post submission ID.

        For scheduled posts, Blotato returns immediately — no polling required.
        """
        post: dict = {
            "accountId": account_id,
            "platform": platform,
            "text": text,
            "mediaUrls": media_urls,
            "scheduledTime": scheduled_time,
        }
        if page_id is not None:
            post["pageId"] = page_id
        if playlist_ids:
            post["playlistIds"] = playlist_ids
        if media_type is not None:
            post["mediaType"] = media_type

        resp = await self._post_with_retry("/posts", {"post": post})
        data = resp.json()
        return str(data.get("id") or data.get("postSubmissionId") or "")

    async def reschedule_post(self, schedule_id: str, new_scheduled_time: str) -> None:
        """Update the scheduled time of an existing Blotato post.

        PATCH /schedules/{schedule_id} — retries on 5xx, raises BlotatoAPIError on 4xx.
        """
        await self._patch_with_retry(f"/schedules/{schedule_id}", {"scheduledTime": new_scheduled_time})

    async def cancel_post(self, schedule_id: str) -> None:
        """Cancel a scheduled Blotato post.

        DELETE /schedules/{schedule_id} — silences 404 (already gone), retries on 5xx.
        """
        await self._delete_with_retry(f"/schedules/{schedule_id}")

    async def _post_with_retry(self, path: str, payload: dict) -> httpx.Response:
        last_error: BlotatoAPIError | None = None

        for attempt in range(self._max_retries):
            try:
                resp = await self._http.post(path, json=payload)
            except httpx.TransportError as exc:
                last_error = BlotatoAPIError(f"Transport error: {exc}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code >= 400 and resp.status_code < 500:
                raise BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")

            if resp.status_code >= 500:
                last_error = BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            return resp

        raise last_error or BlotatoAPIError("Max retries exceeded")

    async def _patch_with_retry(self, path: str, payload: dict) -> httpx.Response:
        last_error: BlotatoAPIError | None = None

        for attempt in range(self._max_retries):
            try:
                resp = await self._http.patch(path, json=payload)
            except httpx.TransportError as exc:
                last_error = BlotatoAPIError(f"Transport error: {exc}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code >= 400 and resp.status_code < 500:
                raise BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")

            if resp.status_code >= 500:
                last_error = BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            return resp

        raise last_error or BlotatoAPIError("Max retries exceeded")

    async def _delete_with_retry(self, path: str) -> None:
        last_error: BlotatoAPIError | None = None

        for attempt in range(self._max_retries):
            try:
                resp = await self._http.delete(path)
            except httpx.TransportError as exc:
                last_error = BlotatoAPIError(f"Transport error: {exc}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 404:
                return

            if resp.status_code >= 400 and resp.status_code < 500:
                raise BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")

            if resp.status_code >= 500:
                last_error = BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            return

        raise last_error or BlotatoAPIError("Max retries exceeded")

    async def get_schedule(self, schedule_id: str) -> dict:
        """GET /schedules/{schedule_id}. Returns parsed JSON dict.

        Raises BlotatoScheduleNotFound on 404.
        Raises BlotatoAPIError on other non-2xx.
        Retries on 5xx using the same backoff pattern as other methods.
        """
        resp = await self._get_with_retry(f"/schedules/{schedule_id}")
        return resp.json()

    async def list_accounts(self) -> list[dict]:
        """GET /users/me/accounts — returns all connected Blotato accounts."""
        resp = await self._get_with_retry("/users/me/accounts")
        data = resp.json()
        return data if isinstance(data, list) else data.get("accounts", [])

    async def list_subaccounts(self, account_id: str) -> list[dict]:
        """GET /users/me/accounts/{account_id}/subaccounts — returns account-specific subaccounts."""
        resp = await self._get_with_retry(f"/users/me/accounts/{account_id}/subaccounts")
        data = resp.json() or {}
        items = data.get("items") if isinstance(data, dict) else []
        return list(items or [])

    async def _get_with_retry(self, path: str) -> httpx.Response:
        last_error: BlotatoAPIError | None = None

        for attempt in range(self._max_retries):
            try:
                resp = await self._http.get(path)
            except httpx.TransportError as exc:
                last_error = BlotatoAPIError(f"Transport error: {exc}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 404:
                raise BlotatoScheduleNotFound(f"HTTP 404: {resp.text[:300]}")

            if resp.status_code >= 400 and resp.status_code < 500:
                raise BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")

            if resp.status_code >= 500:
                last_error = BlotatoAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            return resp

        raise last_error or BlotatoAPIError("Max retries exceeded")

    async def aclose(self) -> None:
        await self._http.aclose()
