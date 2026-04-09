"""CreatomateToolkit — high-level tool functions for agent use.

Wraps CreatomateService with business-logic-aware methods:
- render_template: dispatch + optional polling (10s timeout)
- render_with_tts: merge voiceover modifications + dispatch (60s timeout for TTS)
- get_render_status: single-shot status check (no polling)
- list_available_templates: cached template listing (5-min TTL)
- render_video_with_voice: convenience using RenderScript source
- create_video_from_text: end-to-end text-to-video helper
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Simple in-memory cache for template listing
_templates_cache: list[dict] = []
_cache_ts: float = 0.0
_CACHE_TTL = 300  # 5 minutes


class CreatomateToolkit:
    """Business-logic tool layer over CreatomateService."""

    def __init__(self):
        from app.services.creatomate import CreatomateService
        self._svc = CreatomateService()

    # ── Tool: list_available_templates ──────────────────────────────────

    async def list_available_templates(self) -> list[dict]:
        """List Creatomate templates with 5-minute in-memory cache.

        Returns: [{id, name, tags}]
        """
        global _templates_cache, _cache_ts
        now = time.monotonic()
        if _templates_cache and (now - _cache_ts) < _CACHE_TTL:
            return _templates_cache

        try:
            raw = await self._svc.list_templates()
            _templates_cache = [
                {
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "tags": t.get("tags", []),
                }
                for t in (raw if isinstance(raw, list) else [])
            ]
            _cache_ts = now
            logger.info("Template cache refreshed: %d templates", len(_templates_cache))
            return _templates_cache
        except Exception as e:
            logger.error("list_templates failed: %s", e)
            return _templates_cache or []

    # ── Tool: render_template ────────────────────────────────────────────

    async def render_template(
        self,
        template_id: str,
        modifications: dict[str, Any],
        voice_config: dict[str, Any] | None = None,
        webhook_url: str | None = None,
        metadata: str | None = None,
        poll_timeout: int = 10,
    ) -> dict[str, Any]:
        """Render a Creatomate template with modifications.

        If webhook_url provided: returns immediately with status "planned".
        Otherwise: polls up to poll_timeout seconds.

        voice_config: optional dict of element-name -> TTS properties merged into modifications.

        Returns: {render_id, status, url, snapshot_url, error_message}
        """
        merged: dict[str, Any] = dict(modifications)
        if voice_config:
            merged.update(voice_config)

        extra: dict[str, Any] = {}
        if webhook_url:
            extra["webhook_url"] = webhook_url
        if metadata:
            extra["metadata"] = metadata

        render_id = await self._svc.render(template_id, merged, **extra)

        if webhook_url:
            return {
                "render_id": render_id,
                "status": "planned",
                "message": "Render dispatched; result will be sent to webhook",
            }

        return await self._poll(render_id, poll_timeout)

    # ── Tool: render_with_tts ────────────────────────────────────────────

    async def render_with_tts(
        self,
        template_id: str,
        voiceover_texts: dict[str, Any],
        other_modifications: dict[str, Any] | None = None,
        webhook_url: str | None = None,
        poll_timeout: int = 60,
    ) -> dict[str, Any]:
        """Render a template injecting TTS voiceover text as modifications.

        voiceover_texts: {"Voiceover-1": "text to speak"}
        TTS provider/voice must be configured in the Creatomate template editor.
        Polls for up to 60s (TTS renders take longer than plain renders).

        Returns: {render_id, status, url, snapshot_url, error_message}
        """
        modifications: dict[str, Any] = dict(other_modifications or {})
        modifications.update(voiceover_texts)

        extra: dict[str, Any] = {}
        if webhook_url:
            extra["webhook_url"] = webhook_url

        render_id = await self._svc.render(template_id, modifications, **extra)

        if webhook_url:
            return {
                "render_id": render_id,
                "status": "planned",
                "message": "TTS render dispatched",
            }

        return await self._poll(render_id, poll_timeout)

    # ── Tool: render_video_with_voice ────────────────────────────────────

    async def render_video_with_voice(
        self,
        source_elements: list[dict[str, Any]],
        voice_provider: str,
        voice_id: str,
        webhook_url: str | None = None,
        poll_timeout: int = 60,
    ) -> dict[str, Any]:
        """Render a custom composition with TTS using RenderScript source.

        source_elements: list of element dicts forming the composition.
        voice_provider/voice_id are injected into voiceover/audio elements.

        Returns: {render_id, status, url, snapshot_url, error_message}
        """
        # Inject TTS config into audio/voice elements that lack an explicit provider
        elements = []
        for el in source_elements:
            el_copy = dict(el)
            el_type = el_copy.get("type", "")
            if el_type in ("audio", "voice") or "voice" in el_copy.get("name", "").lower():
                el_copy.setdefault("provider", voice_provider)
                el_copy.setdefault("voice", voice_id)
            elements.append(el_copy)

        source = {"elements": elements}
        extra: dict[str, Any] = {}
        if webhook_url:
            extra["webhook_url"] = webhook_url

        render_id = await self._svc.render_with_source(source, **extra)

        if webhook_url:
            return {
                "render_id": render_id,
                "status": "planned",
                "message": "RenderScript+voice render dispatched",
            }

        return await self._poll(render_id, poll_timeout)

    # ── Tool: get_render_status ──────────────────────────────────────────

    async def get_render_status(self, render_id: str) -> dict[str, Any]:
        """Single-shot render status — no polling.

        Returns: {render_id, status, url, snapshot_url, error_message, duration, width, height}
        """
        try:
            data = await self._svc.get_render(render_id)
            return {
                "render_id": data.get("id", render_id),
                "status": data.get("status", "unknown"),
                "url": data.get("url") or None,
                "snapshot_url": data.get("snapshot_url") or None,
                "error_message": data.get("error_message") or None,
                "duration": data.get("duration"),
                "width": data.get("width"),
                "height": data.get("height"),
            }
        except Exception as e:
            logger.error("get_render_status failed for %s: %s", render_id, e)
            return {
                "render_id": render_id,
                "status": "error",
                "url": None,
                "snapshot_url": None,
                "error_message": str(e),
                "duration": None,
                "width": None,
                "height": None,
            }

    # ── Tool: create_video_from_text ─────────────────────────────────────

    async def create_video_from_text(
        self,
        text: str,
        template_id: str,
        voice_config: dict[str, Any] | None = None,
        text_element_name: str = "Text-1",
        extra_modifications: dict[str, Any] | None = None,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        """End-to-end text-to-video: inject text into a template and render.

        Sets the primary text element content and optionally adds TTS voice config.
        Polls for up to 60s to handle TTS renders.

        Returns: {render_id, status, url, snapshot_url, error_message}
        """
        modifications: dict[str, Any] = {text_element_name: text}
        if extra_modifications:
            modifications.update(extra_modifications)

        return await self.render_template(
            template_id=template_id,
            modifications=modifications,
            voice_config=voice_config,
            webhook_url=webhook_url,
            poll_timeout=60,
        )

    # ── Internal: polling helper ─────────────────────────────────────────

    async def _poll(self, render_id: str, timeout: int) -> dict[str, Any]:
        """Poll render status up to timeout seconds with exponential backoff."""
        elapsed = 0.0
        interval = 5.0

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                data = await self._svc.get_render(render_id)
            except Exception as e:
                logger.warning("Poll error for render %s: %s", render_id, e)
                interval = min(interval * 1.5, 8.0)
                continue

            status = data.get("status", "unknown")

            if status == "succeeded":
                return {
                    "render_id": render_id,
                    "status": "succeeded",
                    "url": data.get("url"),
                    "snapshot_url": data.get("snapshot_url"),
                    "error_message": None,
                }

            if status == "failed":
                return {
                    "render_id": render_id,
                    "status": "failed",
                    "url": None,
                    "snapshot_url": None,
                    "error_message": data.get("error_message", "Unknown render error"),
                }

            logger.debug("Render %s: status=%s elapsed=%.1fs", render_id, status, elapsed)
            interval = min(interval * 1.5, 8.0)

        return {
            "render_id": render_id,
            "status": "pending",
            "url": None,
            "snapshot_url": None,
            "error_message": f"Render still processing after {timeout}s. Use get_render_status to check later.",
        }
