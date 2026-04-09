"""CRUD service for conversations and messages — used by the REST API router.

Separate from conversation_service.py (which is used by chat agents internally).
Uses core infrastructure: auth, responses, pagination, exceptions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.supabase_client import get_service_client
from app.core.exceptions import NotFoundError, DatabaseError, ForbiddenError

logger = logging.getLogger(__name__)


class ConversationsCRUD:
    """CRUD for the /api/v1/conversations REST endpoints."""

    def __init__(self):
        self.client = get_service_client()

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def list_conversations(
        self,
        user_id: str,
        agent_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "updated_at",
        order: str = "desc",
    ) -> tuple[list[dict], int]:
        """Return (items, total) for user conversations."""
        try:
            query = (
                self.client.table("conversations")
                .select("*", count="exact")
                .eq("user_id", user_id)
            )
            if agent_type:
                query = query.eq("agent_type", agent_type)

            desc = order == "desc"
            query = query.order(sort_by, desc=desc).range(offset, offset + limit - 1)
            result = query.execute()
            return result.data or [], result.count or 0
        except Exception as exc:
            logger.error("Failed to list conversations: %s", exc)
            raise DatabaseError(f"Failed to list conversations: {exc}")

    def get_conversation(self, conversation_id: str, user_id: str) -> dict:
        """Get single conversation with ownership check. Raises NotFoundError."""
        try:
            result = (
                self.client.table("conversations")
                .select("*")
                .eq("id", conversation_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if not result or not result.data:
                raise NotFoundError("Conversation")
            return result.data
        except NotFoundError:
            raise
        except Exception as exc:
            logger.error("Failed to get conversation %s: %s", conversation_id, exc)
            raise DatabaseError(f"Failed to get conversation: {exc}")

    def create_conversation(self, user_id: str, agent_type: str, title: str | None = None) -> dict:
        """Create a new conversation and return the full row."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "user_id": user_id,
            "agent_type": agent_type,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        try:
            result = self.client.table("conversations").insert(payload).execute()
            return result.data[0]
        except Exception as exc:
            logger.error("Failed to create conversation: %s", exc)
            raise DatabaseError(f"Failed to create conversation: {exc}")

    def update_conversation(self, conversation_id: str, user_id: str, updates: dict) -> dict:
        """Update conversation fields. Always bumps updated_at."""
        # Verify ownership
        self.get_conversation(conversation_id, user_id)

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            result = (
                self.client.table("conversations")
                .update(updates)
                .eq("id", conversation_id)
                .eq("user_id", user_id)
                .execute()
            )
            return result.data[0] if result.data else updates
        except Exception as exc:
            logger.error("Failed to update conversation %s: %s", conversation_id, exc)
            raise DatabaseError(f"Failed to update conversation: {exc}")

    def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        """Delete conversation and all its messages."""
        # Verify ownership
        self.get_conversation(conversation_id, user_id)

        try:
            # Delete messages first (child rows)
            self.client.table("messages").delete().eq(
                "conversation_id", conversation_id
            ).execute()
            # Delete conversation
            self.client.table("conversations").delete().eq(
                "id", conversation_id
            ).eq("user_id", user_id).execute()
            return True
        except Exception as exc:
            logger.error("Failed to delete conversation %s: %s", conversation_id, exc)
            raise DatabaseError(f"Failed to delete conversation: {exc}")

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def list_messages(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Return (items, total) messages for a conversation, newest first."""
        # Verify conversation ownership
        self.get_conversation(conversation_id, user_id)

        try:
            result = (
                self.client.table("messages")
                .select("*", count="exact")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            return result.data or [], result.count or 0
        except Exception as exc:
            logger.error("Failed to list messages for %s: %s", conversation_id, exc)
            raise DatabaseError(f"Failed to list messages: {exc}")

    def create_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        agent_type: str | None = None,
        media_urls: list[str] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Save a message to a conversation. Returns the created row."""
        # Verify conversation ownership
        conv = self.get_conversation(conversation_id, user_id)

        payload = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "agent_type": agent_type or conv.get("agent_type"),
            "role": role,
            "content": content,
            "media_urls": media_urls,
            "metadata": metadata,
        }
        try:
            result = self.client.table("messages").insert(payload).execute()
            # Bump conversation updated_at
            self.client.table("conversations").update(
                {"updated_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", conversation_id).execute()
            return result.data[0]
        except Exception as exc:
            logger.error("Failed to create message: %s", exc)
            raise DatabaseError(f"Failed to create message: {exc}")
