"""Conversation & message persistence for the unified chat agent.

Implements CHAT-201 through CHAT-204:
- ConversationService: create, get, validate ownership, list
- Message persistence: save user / assistant messages
- History loading with Gemini format conversion
- Auto-title generation (fire-and-forget)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from google.genai import types

from app.core.gemini_client import get_gemini_client
from app.core.supabase_client import get_service_client
from app.core.exceptions import NotFoundError, DatabaseError
from app.config import get_settings

logger = logging.getLogger(__name__)


class ConversationService:
    """CRUD operations for conversations and messages in Supabase."""

    def __init__(self):
        self.client = get_service_client()

    # ------------------------------------------------------------------
    # CHAT-201: Conversation CRUD
    # ------------------------------------------------------------------

    async def create_conversation(self, user_id: str, agent_type: str) -> str:
        """Create a new conversation and return its UUID."""
        now = datetime.now(timezone.utc).isoformat()
        new_conv = {
            "user_id": user_id,
            "agent_type": agent_type,
            "title": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            result = self.client.table("conversations").insert(new_conv).execute()
            return result.data[0]["id"]
        except Exception as exc:
            logger.error("Failed to create conversation: %s", exc)
            raise DatabaseError(f"Failed to create conversation: {exc}")

    async def get_conversation(self, conversation_id: str, user_id: str) -> dict | None:
        """Get conversation by ID with ownership check. Returns None if not found/not owned."""
        try:
            result = (
                self.client.table("conversations")
                .select("*")
                .eq("id", conversation_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            # maybe_single().execute() returns None when no row matches
            if result is None:
                return None
            return result.data
        except Exception as exc:
            logger.error("Failed to get conversation %s: %s", conversation_id, exc)
            raise DatabaseError(f"Failed to get conversation: {exc}")

    async def get_or_create(
        self, user_id: str, agent_type: str, conversation_id: Optional[str] = None
    ) -> dict:
        """Get existing conversation or create a new one.

        Returns the full conversation dict. Raises NotFoundError if
        conversation_id is provided but not found/not owned.
        """
        if conversation_id:
            conv = await self.get_conversation(conversation_id, user_id)
            if conv:
                return conv
            raise NotFoundError("Conversation")

        # Create new conversation and return it
        new_id = await self.create_conversation(user_id, agent_type)
        # Fetch the newly created row to get server-side defaults
        conv = await self.get_conversation(new_id, user_id)
        if conv:
            return conv
        # Fallback: return minimal dict if fetch somehow fails
        return {"id": new_id, "user_id": user_id, "agent_type": agent_type, "title": None}

    async def update_title(self, conversation_id: str, title: str) -> None:
        """Update conversation title."""
        try:
            self.client.table("conversations").update({"title": title}).eq(
                "id", conversation_id
            ).execute()
        except Exception as exc:
            logger.error("Failed to update title for %s: %s", conversation_id, exc)

    async def bump_updated_at(self, conversation_id: str) -> None:
        """Touch updated_at timestamp."""
        try:
            self.client.table("conversations").update(
                {"updated_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", conversation_id).execute()
        except Exception as exc:
            logger.error("Failed to bump updated_at for %s: %s", conversation_id, exc)

    async def list_for_user(
        self,
        user_id: str,
        agent_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list:
        """List conversations for a user, newest first."""
        query = (
            self.client.table("conversations")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if agent_type:
            query = query.eq("agent_type", agent_type)
        try:
            result = query.execute()
            return result.data
        except Exception as exc:
            logger.error("Failed to list conversations for %s: %s", user_id, exc)
            raise DatabaseError(f"Failed to list conversations: {exc}")

    # ------------------------------------------------------------------
    # CHAT-202: Message persistence
    # ------------------------------------------------------------------

    async def save_user_message(
        self,
        user_id: str,
        conversation_id: str,
        agent_type: str,
        content: str,
        file_urls: list[str] | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Save a user message BEFORE the LLM call. Returns message UUID."""
        msg = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "agent_type": agent_type,
            "role": "user",
            "content": content,
            "media_urls": file_urls,
            "metadata": metadata or {},
        }
        try:
            result = self.client.table("messages").insert(msg).execute()
            return result.data[0]["id"]
        except Exception as exc:
            logger.error("Failed to save user message: %s", exc)
            raise DatabaseError(f"Failed to save user message: {exc}")

    async def save_assistant_message(
        self,
        user_id: str,
        conversation_id: str,
        agent_type: str,
        content: str,
        metadata: dict | None = None,
        media_urls: list[str] | None = None,
    ) -> str:
        """Save assistant message AFTER stream completes. Returns message UUID.

        metadata should include tool_calls, model, usage, finish_reason.
        """
        msg = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "agent_type": agent_type,
            "role": "assistant",
            "content": content,
            "media_urls": media_urls,
            "metadata": metadata or {},
        }
        try:
            result = self.client.table("messages").insert(msg).execute()
            return result.data[0]["id"]
        except Exception as exc:
            logger.error("Failed to save assistant message: %s", exc)
            raise DatabaseError(f"Failed to save assistant message: {exc}")

    async def update_message(
        self,
        message_id: str,
        content: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Update a message (e.g., append streaming result)."""
        updates = {}
        if content is not None:
            updates["content"] = content
        if metadata is not None:
            updates["metadata"] = metadata
        if updates:
            try:
                self.client.table("messages").update(updates).eq(
                    "id", message_id
                ).execute()
            except Exception as exc:
                logger.error("Failed to update message %s: %s", message_id, exc)

    # ------------------------------------------------------------------
    # CHAT-203: History loading + Gemini format conversion
    # ------------------------------------------------------------------

    async def get_history(
        self, conversation_id: str, user_id: str, limit: int = 20
    ) -> list[dict]:
        """Load last N messages for a conversation, chronological order.

        Ownership enforced via user_id filter.
        """
        try:
            result = (
                self.client.table("messages")
                .select("id, role, content, media_urls, metadata, created_at")
                .eq("conversation_id", conversation_id)
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            # Reverse to get chronological order (oldest first)
            return list(reversed(result.data)) if result.data else []
        except Exception as exc:
            logger.error("Failed to load history for %s: %s", conversation_id, exc)
            raise DatabaseError(f"Failed to load conversation history: {exc}")

    @staticmethod
    def history_to_gemini_contents(history: list[dict]) -> list[types.Content]:
        """Convert message dicts from Supabase to Gemini Content objects.

        Maps:
        - role "user" -> Gemini role "user"
        - role "assistant" -> Gemini role "model"
        - Reconstructs function_call + function_response Parts from metadata.tool_calls
        """
        contents: list[types.Content] = []
        for msg in history:
            role = "model" if msg["role"] == "assistant" else "user"
            parts: list[types.Part] = [types.Part(text=msg["content"] or "")]

            # Reconstruct tool call/response parts for assistant messages
            metadata = msg.get("metadata") or {}
            if msg["role"] == "assistant" and metadata.get("tool_calls"):
                for tc in metadata["tool_calls"]:
                    tool_name = tc.get("toolName", tc.get("name", ""))
                    # Function call part
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=tool_name,
                                args=tc.get("args", {}),
                            )
                        )
                    )
                    # Function response part
                    parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=tool_name,
                                response=tc.get("result", {}),
                            )
                        )
                    )

            contents.append(types.Content(role=role, parts=parts))
        return contents

    # ------------------------------------------------------------------
    # CHAT-204: Auto-title generation (fire-and-forget)
    # ------------------------------------------------------------------

    async def generate_title(
        self, conversation_id: str, first_message: str, assistant_response: str = ""
    ) -> None:
        """Generate a short title from the first exchange using Gemini.

        Meant to be called as ``asyncio.create_task(cs.generate_title(...))``.
        Fails silently — title generation is non-critical.
        """
        try:
            settings = get_settings()
            client = get_gemini_client()

            user_snippet = first_message[:200]
            assistant_snippet = assistant_response[:200] if assistant_response else ""
            prompt = (
                "Generate a very short title (max 5 words) for a conversation. "
                f"User: {user_snippet}"
            )
            if assistant_snippet:
                prompt += f"\nAssistant: {assistant_snippet}"
            prompt += "\nReply with ONLY the title, nothing else."

            response = client.models.generate_content(
                model=settings.gemini_model_lite,
                contents=prompt,
            )
            title = response.text.strip().strip('"').strip("'")[:100]
            if title:
                await self.update_title(conversation_id, title)
                logger.info("Auto-generated title for %s: %s", conversation_id, title)
        except Exception as exc:
            # Non-critical — fail silently
            logger.warning("Title generation failed for %s: %s", conversation_id, exc)
