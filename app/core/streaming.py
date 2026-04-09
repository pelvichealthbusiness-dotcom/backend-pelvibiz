"""Vercel AI SDK data-stream protocol helpers.

The Vercel AI SDK uses a *non-standard* SSE format where each line
starts with a single-character prefix that indicates the event type:

    0: — text delta
    2: — metadata / progress
    9: — tool call
    a: — tool result
    d: — finish
    e: — error

Lines are plain text (not SSE "data:" frames), terminated by "\n".
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from fastapi.responses import StreamingResponse


# ---------------------------------------------------------------------------
# Emitters — each returns a single protocol line
# ---------------------------------------------------------------------------

def text_chunk(text: str) -> str:
    """Vercel AI SDK text prefix: 0:"""
    return f'0:{json.dumps(text)}\n'


def metadata_event(data: dict) -> str:
    """Vercel AI SDK metadata prefix: 2:"""
    return f'2:{json.dumps(data)}\n'


def tool_call_event(tool_call_id: str, tool_name: str, args: dict) -> str:
    """Vercel AI SDK tool call prefix: 9:"""
    payload = {"toolCallId": tool_call_id, "toolName": tool_name, "args": args}
    return f"9:{json.dumps(payload)}\n"


def tool_result_event(tool_call_id: str, result: Any) -> str:
    """Vercel AI SDK tool result prefix: a:"""
    payload = {"toolCallId": tool_call_id, "result": result}
    return f"a:{json.dumps(payload)}\n"


def finish_event(reason: str = "stop") -> str:
    """Vercel AI SDK finish prefix: d:"""
    payload = {"finishReason": reason}
    return f"d:{json.dumps(payload)}\n"


def error_event(message: str, code: str = "INTERNAL_ERROR") -> str:
    """Vercel AI SDK error prefix: e:"""
    payload = {"error": message, "code": code}
    return f"e:{json.dumps(payload)}\n"


def heartbeat() -> str:
    """SSE comment for keepalive — ignored by Vercel AI SDK parser."""
    return ": heartbeat\n\n"


# ---------------------------------------------------------------------------
# Response wrapper
# ---------------------------------------------------------------------------

def sse_response(generator: AsyncGenerator) -> StreamingResponse:
    """Wrap an async generator as an SSE StreamingResponse."""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# Error mapping — Gemini exceptions → user-friendly SSE error events
# ---------------------------------------------------------------------------

_ERROR_MAP: list[tuple[list[str], str, str]] = [
    # (keywords_in_exception, error_code, user_message)
    (
        ["429", "resourceexhausted", "rate_limit", "rate limit"],
        "LLM_RATE_LIMIT",
        "Rate limit exceeded — please wait a moment and try again",
    ),
    (
        ["context_length", "context length", "too many tokens", "too long", "max_tokens"],
        "CONTEXT_TOO_LONG",
        "Conversation is too long — try starting a new chat",
    ),
    (
        ["safety", "blocked", "harm_category", "finish_reason: safety"],
        "LLM_BLOCKED",
        "Response blocked by safety filter — try rephrasing",
    ),
    (
        ["timeout", "deadline", "timed out"],
        "LLM_TIMEOUT",
        "Request timed out — please try again",
    ),
    (
        ["503", "unavailable", "overloaded"],
        "LLM_UNAVAILABLE",
        "AI service temporarily unavailable — please retry",
    ),
    (
        ["permission", "403", "api_key", "authentication"],
        "LLM_AUTH_ERROR",
        "AI service configuration error — contact support",
    ),
]


def map_error_to_events(exc: Exception) -> str:
    """Map a Gemini/LLM exception to a Vercel AI SDK error event string.

    Always returns an error event. The caller should yield this as the
    final output of the stream (no finish event after error per spec).

    Returns
    -------
    str
        A Vercel AI SDK ``e:`` error line.
    """
    exc_str = str(exc).lower()

    for keywords, code, message in _ERROR_MAP:
        if any(kw in exc_str for kw in keywords):
            return error_event(message, code)

    # Fallback — generic error
    return error_event("An unexpected error occurred", "INTERNAL_ERROR")
