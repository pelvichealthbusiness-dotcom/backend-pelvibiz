"""Abstract base class for all streaming chat agents.

Every agent type (General, Carousel P1/P2, Video P3, Wizard Ideas/Draft)
inherits from this class and overrides the abstract properties and the
``execute_tool`` method.

The ``stream`` method orchestrates: Gemini call → SSE emission → inline
tool execution → resume Gemini with tool results.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from app.config import get_settings
from app.core.gemini_client import get_gemini_client
from app.core.gemini_stream import stream_chat_with_retry
from app.core.streaming import (
    text_chunk,
    tool_call_event,
    tool_result_event,
    finish_event,
    error_event,
)

logger = logging.getLogger(__name__)


class BaseStreamingAgent(ABC):
    """Base class for all streaming chat agents.

    Subclasses MUST implement:
        - ``system_prompt`` (property) — the system prompt text
        - ``model`` (property) — Gemini model name
        - ``execute_tool`` — dispatch tool calls to the correct service

    Subclasses MAY override:
        - ``temperature``, ``max_tokens``, ``context_window``
        - ``tools`` — return Gemini tool/function definitions
    """

    def __init__(self, user_id: str, agent_type: str) -> None:
        self.user_id = user_id
        self.agent_type = agent_type
        self.client = get_gemini_client()
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Abstract interface — subclasses MUST implement
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the Gemini model name (e.g. ``gemini-2.5-flash``)."""
        ...

    @abstractmethod
    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Execute a tool call and return its result dict.

        Called inline during streaming when Gemini emits a function_call.
        """
        ...

    # ------------------------------------------------------------------
    # Overridable properties with sensible defaults
    # ------------------------------------------------------------------

    @property
    def temperature(self) -> float:
        return 0.7

    @property
    def max_tokens(self) -> int:
        return 4096

    @property
    def context_window(self) -> int:
        """Number of history messages to include."""
        return 20

    @property
    def tools(self) -> list:
        """Gemini tool/function definitions.  Empty = no tool calling."""
        return []

    # ------------------------------------------------------------------
    # Main streaming method
    # ------------------------------------------------------------------

    async def stream(
        self,
        message: str,
        history: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream a response as Vercel AI SDK protocol lines.

        Parameters
        ----------
        message:
            The current user message text.
        history:
            Previous messages as OpenAI-style dicts
            (``[{"role": "user", "content": "..."}, ...]``).
        **kwargs:
            Extra context passed down from the route handler
            (e.g. ``metadata``, ``files``).

        Yields
        ------
        str
            Vercel AI SDK formatted lines (``0:``, ``9:``, ``a:``, ``d:``, ``e:``).
        """
        try:
            # Build messages list
            messages: list[dict] = []
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": message})

            # Stream from Gemini with retry
            async for chunk in stream_chat_with_retry(
                messages=messages,
                system_prompt=self.system_prompt,
                model=self.model,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
                tools=self.tools if self.tools else None,
            ):
                if chunk["type"] == "text":
                    yield text_chunk(chunk["content"])

                elif chunk["type"] == "tool_call":
                    tc_id = chunk["id"]
                    tc_name = chunk["name"]
                    tc_args = chunk["args"]

                    # Emit tool call event
                    yield tool_call_event(tc_id, tc_name, tc_args)

                    # Execute tool inline
                    try:
                        result = await self.execute_tool(
                            name=tc_name,
                            args=tc_args,
                            user_id=self.user_id,
                            **kwargs,
                        )
                    except Exception as exc:
                        logger.error(
                            "Tool execution failed: %s(%s) — %s",
                            tc_name,
                            tc_args,
                            exc,
                            exc_info=True,
                        )
                        result = {"error": str(exc)}

                    # Emit tool result event
                    yield tool_result_event(tc_id, result)

            # Successful completion
            yield finish_event("stop")

        except Exception as exc:
            logger.error(
                "Agent stream error [%s/%s]: %s",
                self.agent_type,
                self.user_id,
                exc,
                exc_info=True,
            )
            # Map known errors to codes
            exc_str = str(exc).lower()
            if "timeout" in exc_str:
                code = "LLM_TIMEOUT"
                msg = "Gemini API timeout"
            elif "safety" in exc_str or "blocked" in exc_str:
                code = "LLM_BLOCKED"
                msg = "Response blocked by safety filter"
            elif "429" in exc_str or "resourceexhausted" in exc_str:
                code = "LLM_RATE_LIMIT"
                msg = "Rate limit exceeded, please try again"
            elif "503" in exc_str or "unavailable" in exc_str:
                code = "LLM_UNAVAILABLE"
                msg = "Gemini service temporarily unavailable"
            else:
                code = "INTERNAL_ERROR"
                msg = "An unexpected error occurred"

            yield error_event(msg, code)
            # No finish event after error (per spec)
