"""GeneralChatAgent — minimal placeholder for end-to-end testing.

A simple conversational agent with no tools. Will be enhanced in Batch 4
(CHAT-401) with brand profile tools and richer system prompts.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseStreamingAgent
from app.config import get_settings

logger = logging.getLogger(__name__)


class GeneralChatAgent(BaseStreamingAgent):
    """Simple conversational agent for PelviBiz users.

    Uses gemini-2.5-flash with no tool calling. Serves as the default
    agent and a testbed for the streaming pipeline.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are PelviBiz AI, a social media content assistant for health & "
            "wellness professionals. You help users plan content strategies, write "
            "captions, understand social media best practices, and optimize their "
            "online presence. You speak in a warm, professional tone.\n\n"
            "If the user asks to CREATE content (carousel, video, etc.), let them "
            "know they can use the specialized content creation agents for that. "
            "You are the conversational assistant — helpful, knowledgeable, concise."
        )

    @property
    def model(self) -> str:
        return get_settings().gemini_model_default

    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """No tools available in the placeholder agent."""
        return {"error": f"Unknown tool: {name}"}
