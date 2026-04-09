"""Temporary test endpoint for SSE streaming infrastructure.

Validates that heartbeat, streaming, and finish events all work correctly.
Can be removed once real chat endpoints are wired up.

Usage:
    curl -N http://localhost:8100/api/v1/chat/test-stream
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Request

from app.core.streaming import text_chunk, finish_event, heartbeat
from app.core.sse_middleware import sse_stream_with_heartbeat

router = APIRouter(prefix="/chat", tags=["chat-test"])


async def _test_generator() -> AsyncGenerator[str, None]:
    """Simulate a streaming response with 5 text chunks."""
    test_chunks = [
        "Hello! ",
        "This is a test ",
        "of the SSE streaming ",
        "infrastructure. ",
        "Everything works!",
    ]

    for chunk in test_chunks:
        yield text_chunk(chunk)
        await asyncio.sleep(0.5)

    yield finish_event("stop")


@router.get("/test-stream")
async def test_stream(request: Request):
    """Test SSE streaming with heartbeat and proper headers.

    Streams 5 text chunks with 500ms delay, then a finish event.
    Heartbeat is sent by the SSE middleware every 15s (or sooner
    if you wait long enough).
    """
    return await sse_stream_with_heartbeat(
        request=request,
        generator=_test_generator(),
        heartbeat_interval=5,  # Short interval for testing
    )
