"""Creatomate render engine client — dispatch, poll, download."""

import asyncio
import logging

import httpx

from app.config import Settings, get_settings
from app.models.video import CreatomateRenderStatus
from app.services.exceptions import AgentAPIError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class RenderError(AgentAPIError):
    """Creatomate render error."""

    def __init__(self, code: str, message: str):
        super().__init__(message=message, code=code, status_code=500)


class RenderTimeoutError(AgentAPIError):
    """Render did not complete within max_wait."""

    def __init__(self, message: str = "Render timed out"):
        super().__init__(message=message, code="RENDER_TIMEOUT", status_code=504)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CreatomateService:
    """Creatomate API client — render dispatch, polling, and download."""

    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        self._api_key = s.creatomate_api_key
        self._base_url = s.creatomate_base_url
        self._poll_interval = s.creatomate_poll_interval
        self._max_wait = s.creatomate_max_wait
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=60.0),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # render()
    # ------------------------------------------------------------------

    async def render(self, template_id: str, modifications: dict, **extra) -> str:
        """
        Dispatch a render to Creatomate.

        Args:
            template_id: Creatomate template UUID.
            modifications: Dict of element modifications.
            **extra: Additional top-level keys (output_format, width, height,
                     duration, snapshot_time).

        Returns:
            render_id (str) — UUID of the dispatched render.
        """
        payload: dict = {
            "template_id": template_id,
            "modifications": modifications,
        }
        # Merge optional top-level keys
        for key in ("output_format", "width", "height", "duration", "snapshot_time",
                     "webhook_url", "metadata", "tags", "render_scale", "max_width", "max_height"):
            if key in extra and extra[key] is not None:
                payload[key] = extra[key]

        try:
            response = await self._client.post(
                f"{self._base_url}/renders", json=payload,
            )
        except httpx.TimeoutException:
            raise RenderError("CREATOMATE_UNAVAILABLE", "Creatomate API timed out")

        if response.status_code == 401:
            raise RenderError(
                "CREATOMATE_AUTH", "Creatomate API key is invalid or expired",
            )

        if response.status_code == 400:
            detail = response.json().get("message", response.text[:300])
            raise RenderError(
                "INVALID_TEMPLATE", f"Creatomate rejected render: {detail}",
            )

        if response.status_code >= 500:
            # Retry once after 3 s
            await asyncio.sleep(3)
            response = await self._client.post(
                f"{self._base_url}/renders", json=payload,
            )
            if response.status_code >= 500:
                raise RenderError("CREATOMATE_UNAVAILABLE", "Creatomate API is down")

        data = response.json()
        # Creatomate returns a list of renders
        render_id: str = data[0]["id"] if isinstance(data, list) else data["id"]
        logger.info("Render dispatched: %s (template: %s)", render_id, template_id)
        return render_id

    # ------------------------------------------------------------------
    # render_with_source()
    # ------------------------------------------------------------------

    async def render_with_source(self, source: dict, **extra) -> str:
        """
        Submit a RenderScript source dict to Creatomate.
        Returns the render ID string.
        Uses same base URL and auth headers as render().
        """
        payload: dict = {"source": source}
        payload.update(extra)
        response = await self._client.post(
            f"{self._base_url}/renders",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data[0]["id"]
        return data["id"]

    # ------------------------------------------------------------------
    # poll_status()
    # ------------------------------------------------------------------

    async def poll_status(
        self, render_id: str, max_wait: int | None = None,
    ) -> CreatomateRenderStatus:
        """Poll until succeeded / failed / timeout."""
        max_wait = max_wait or self._max_wait
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

            try:
                response = await self._client.get(
                    f"{self._base_url}/renders/{render_id}",
                )
            except httpx.TimeoutException:
                logger.warning("Poll timeout for render %s, retrying...", render_id)
                continue

            if response.status_code != 200:
                logger.warning(
                    "Poll returned %s for %s", response.status_code, render_id,
                )
                continue

            data = response.json()
            status = data.get("status", "unknown")

            if status == "succeeded":
                return CreatomateRenderStatus(
                    id=render_id,
                    status="succeeded",
                    url=data.get("url"),
                    render_time=data.get("render_time"),
                )

            if status == "failed":
                error_msg = data.get("error_message", "Unknown render error")
                raise RenderError("RENDER_FAILED", f"Render failed: {error_msg}")

            logger.debug("Render %s: status=%s, elapsed=%ss", render_id, status, elapsed)

        raise RenderTimeoutError(
            f"Render {render_id} did not complete within {max_wait}s",
        )

    # ------------------------------------------------------------------
    # download_video()
    # ------------------------------------------------------------------

    async def download_video(self, url: str) -> bytes:
        """Download rendered video from Creatomate URL."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content


    # ------------------------------------------------------------------
    # get_render()
    # ------------------------------------------------------------------

    async def get_render(self, render_id: str) -> dict:
        """GET /v1/renders/{id} - fetch a single render by ID (no polling)."""
        response = await self._client.get(
            f"{self._base_url}/renders/{render_id}",
        )
        if response.status_code == 404:
            raise RenderError("RENDER_NOT_FOUND", f"Render {render_id} not found")
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # list_renders()
    # ------------------------------------------------------------------

    async def list_renders(
        self, status=None, tags=None, limit=20, offset=0,
    ):
        """GET /v1/renders - list renders with optional filters."""
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if tags:
            params["tags"] = ",".join(tags)
        response = await self._client.get(
            f"{self._base_url}/renders", params=params,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # list_templates()
    # ------------------------------------------------------------------

    async def list_templates(self):
        """GET /v1/templates - list all templates (metadata only, no source)."""
        response = await self._client.get(
            f"{self._base_url}/templates",
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # get_template()
    # ------------------------------------------------------------------

    async def get_template(self, template_id: str) -> dict:
        """GET /v1/templates/{id} - fetch a single template with full RenderScript source."""
        response = await self._client.get(
            f"{self._base_url}/templates/{template_id}",
        )
        if response.status_code == 404:
            raise RenderError("TEMPLATE_NOT_FOUND", f"Template {template_id} not found")
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
