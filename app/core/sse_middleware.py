"""SSE middleware with heartbeat, disconnect detection, and cleanup.

Wraps any async generator into a proper SSE response that:
- Sends heartbeat comments every N seconds to keep the connection alive
- Detects client disconnects and cancels the generator
- Ensures proper cleanup on disconnect or completion
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncGenerator

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.core.streaming import heartbeat

logger = logging.getLogger(__name__)


async def sse_stream_with_heartbeat(
    request: Request,
    generator: AsyncGenerator[str, None],
    heartbeat_interval: int = 15,
) -> StreamingResponse:
    """Wrap an async generator with heartbeat and disconnect detection.

    Parameters
    ----------
    request:
        The incoming FastAPI request — used for disconnect detection.
    generator:
        An async generator that yields SSE-formatted strings
        (e.g. Vercel AI SDK protocol lines).
    heartbeat_interval:
        Seconds between heartbeat comments (default 15).

    Returns
    -------
    StreamingResponse
        A FastAPI StreamingResponse with proper SSE headers.
    """

    async def _stream_with_heartbeat():
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        producer_done = False

        async def _producer():
            """Read from the original generator and push to queue."""
            nonlocal producer_done
            try:
                async for chunk in generator:
                    await queue.put(chunk)
            except asyncio.CancelledError:
                logger.debug("SSE producer cancelled")
            except Exception as exc:
                logger.error("SSE producer error: %s", exc, exc_info=True)
            finally:
                producer_done = True
                await queue.put(None)  # sentinel

        async def _heartbeat_producer():
            """Push heartbeat comments into the queue periodically."""
            try:
                while not producer_done:
                    await asyncio.sleep(heartbeat_interval)
                    if not producer_done:
                        await queue.put(heartbeat())
            except asyncio.CancelledError:
                pass

        producer_task = asyncio.create_task(_producer())
        heartbeat_task = asyncio.create_task(_heartbeat_producer())

        try:
            while True:
                # Check disconnect periodically with a timeout on queue.get
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # No data yet — check if client disconnected
                    if await request.is_disconnected():
                        logger.info("Client disconnected, cancelling stream")
                        break
                    continue

                if item is None:
                    # Producer finished
                    break

                # Check disconnect before yielding
                if await request.is_disconnected():
                    logger.info("Client disconnected, cancelling stream")
                    break

                yield item
        finally:
            # Cleanup: cancel both tasks
            heartbeat_task.cancel()
            producer_task.cancel()
            # Wait for tasks to finish cancellation
            for task in (producer_task, heartbeat_task):
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            # Close the original generator
            try:
                await generator.aclose()
            except Exception:
                pass
            logger.debug("SSE stream cleaned up")

    return StreamingResponse(
        _stream_with_heartbeat(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
