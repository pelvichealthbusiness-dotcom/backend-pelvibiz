"""Low-level Gemini streaming helper.

Wraps ``google-genai`` synchronous streaming into an async generator that
yields normalised dicts::

    {"type": "text", "content": "Hello"}
    {"type": "tool_call", "id": "get_brand_profile", "name": "get_brand_profile", "args": {...}}

The caller (``BaseStreamingAgent``) is responsible for converting these
into Vercel AI SDK protocol lines.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import AsyncGenerator, Any, Iterator

from google import genai
from google.genai import types

from app.core.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message format conversion (OpenAI-style → Gemini Content)
# ---------------------------------------------------------------------------

def _convert_messages(messages: list[dict]) -> list[types.Content]:
    """Convert OpenAI-style message dicts to Gemini ``Content`` objects.

    Supported message formats:

    Normal user message::

        {"role": "user", "content": "text"}

    Multimodal user message::

        {"role": "user", "content": "text", "attachments": [{"mime_type": "image/jpeg", "data": "<base64>"}]}

    Model message with function calls (multi-turn)::

        {"role": "assistant", "content": "", "function_calls": [{"id": "...", "name": "...", "args": {...}}]}

    Tool results (multi-turn)::

        {"role": "tool", "function_results": [{"id": "...", "name": "...", "result": {...}}]}
    """
    contents: list[types.Content] = []
    for msg in messages:
        role = msg.get("role", "user")
        if role == "system":
            continue  # handled via systemInstruction

        # ── Model's function_calls (from multi-turn agentic loop) ──────────
        if role == "assistant" and msg.get("function_calls"):
            parts: list[types.Part] = []
            text = msg.get("content", "")
            if text:
                parts.append(types.Part(text=text))
            for fc in msg["function_calls"]:
                try:
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=fc["name"],
                                args=fc.get("args", {}),
                                id=fc.get("id", fc["name"]),
                            )
                        )
                    )
                except Exception:
                    pass
            if parts:
                contents.append(types.Content(role="model", parts=parts))
            continue

        # ── Tool results (FunctionResponse) ───────────────────────────────
        if role == "tool" and msg.get("function_results"):
            parts = []
            for fr in msg["function_results"]:
                try:
                    response_payload = fr.get("result", {})
                    if not isinstance(response_payload, dict):
                        response_payload = {"value": response_payload}
                    parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=fr["name"],
                                id=fr.get("id", fr["name"]),
                                response=response_payload,
                            )
                        )
                    )
                except Exception:
                    pass
            if parts:
                contents.append(types.Content(role="user", parts=parts))
            continue

        # ── Regular text message (user or assistant) ──────────────────────
        gemini_role = "model" if role == "assistant" else "user"
        text = msg.get("content", "")
        attachments = msg.get("attachments") or []

        if attachments:
            parts = []
            if text:
                parts.append(types.Part(text=text))
            for att in attachments:
                try:
                    raw = base64.b64decode(att["data"])
                    parts.append(
                        types.Part(
                            inline_data=types.Blob(
                                mime_type=att.get("mime_type", "image/jpeg"),
                                data=raw,
                            )
                        )
                    )
                except Exception:
                    pass  # skip malformed attachment
            if parts:
                contents.append(types.Content(role=gemini_role, parts=parts))
        else:
            if not text:
                continue
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part(text=text)],
                )
            )
    return contents


# ---------------------------------------------------------------------------
# Core streaming generator
# ---------------------------------------------------------------------------

async def stream_chat(
    messages: list[dict],
    system_prompt: str,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_output_tokens: int = 4096,
    tools: list | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream a chat completion from Gemini.

    Runs the synchronous ``generate_content_stream`` in a thread to avoid
    blocking the event loop.

    Yields dicts with keys:
        - ``{"type": "text", "content": "..."}``
        - ``{"type": "tool_call", "id": "...", "name": "...", "args": {...}}``
    """
    client = get_gemini_client()
    contents = _convert_messages(messages)

    config = types.GenerateContentConfig(
        systemInstruction=system_prompt,
        temperature=temperature,
        maxOutputTokens=max_output_tokens,
    )
    if tools:
        config.tools = tools

    # Run sync iterator in a thread
    loop = asyncio.get_event_loop()
    response_iter: Iterator[types.GenerateContentResponse] = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ),
    )

    # Iterate chunks — each __next__ may block, so we run them in executor too
    while True:
        try:
            chunk: types.GenerateContentResponse = await loop.run_in_executor(
                None, next, response_iter, None
            )
        except StopIteration:
            break

        if chunk is None:
            break

        # Text content
        if chunk.text:
            yield {"type": "text", "content": chunk.text}

        # Function calls
        if chunk.candidates:
            for candidate in chunk.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.function_call:
                            fc = part.function_call
                            yield {
                                "type": "tool_call",
                                "id": fc.id or fc.name,
                                "name": fc.name,
                                "args": dict(fc.args) if fc.args else {},
                            }


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {429, 503}
_MAX_RETRIES = 3


async def stream_chat_with_retry(
    messages: list[dict],
    system_prompt: str,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_output_tokens: int = 4096,
    tools: list | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Like :func:`stream_chat` but with exponential back-off for rate limits.

    Retries up to 3 times on ``429 ResourceExhausted`` and
    ``503 ServiceUnavailable``.  Non-retryable errors raise immediately.
    """
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            async for chunk in stream_chat(
                messages=messages,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                tools=tools,
            ):
                yield chunk
            return  # success — generator exhausted normally
        except Exception as exc:
            last_exc = exc
            # Check if retryable
            exc_str = str(exc).lower()
            is_retryable = (
                "429" in exc_str
                or "resourceexhausted" in exc_str
                or "503" in exc_str
                or "serviceunavailable" in exc_str
            )
            if not is_retryable or attempt >= _MAX_RETRIES:
                raise

            wait = 2**attempt  # 1s, 2s, 4s
            logger.warning(
                "Gemini API error (attempt %d/%d), retrying in %ds: %s",
                attempt + 1,
                _MAX_RETRIES,
                wait,
                exc,
            )
            await asyncio.sleep(wait)

    # Should never reach here, but just in case
    if last_exc:
        raise last_exc
