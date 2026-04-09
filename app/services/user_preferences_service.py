"""Service for user preferences and learning brief generation."""

from __future__ import annotations

import asyncio
import logging
import json
from typing import Any

from app.core.supabase_client import get_service_client
from app.core.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)


class UserPreferencesService:
    """Manages user preferences and learning brief generation."""

    def __init__(self):
        self.supabase = get_service_client()

    async def get_preferences(self, user_id: str) -> dict | None:
        """Get user preferences. Returns None if no record exists."""
        result = (
            self.supabase.table("user_preferences")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    async def upsert_preferences(self, user_id: str, data: dict) -> dict:
        """Create or update user preferences."""
        # Remove fields that should not be set by the client
        safe_data = {k: v for k, v in data.items() if k not in ("id", "user_id", "updated_at")}
        safe_data["user_id"] = user_id

        result = (
            self.supabase.table("user_preferences")
            .upsert(safe_data, on_conflict="user_id")
            .execute()
        )
        return result.data[0] if result.data else safe_data

    async def track_learning_event(self, user_id: str, event_type: str, event_data: dict) -> str:
        """Insert a learning event (fire-and-forget style)."""
        result = (
            self.supabase.table("user_learning_events")
            .insert({
                "user_id": user_id,
                "event_type": event_type,
                "event_data": event_data,
            })
            .execute()
        )
        row_id = result.data[0]["id"] if result.data else ""
        logger.info("Tracked learning event %s for user %s", event_type, user_id)
        return row_id

    async def get_learning_events(self, user_id: str, limit: int = 50) -> list[dict]:
        """Get recent learning events for a user."""
        result = (
            self.supabase.table("user_learning_events")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def generate_learning_brief(self, user_id: str) -> dict:
        """
        Generate a learning brief using Gemini based on the user's
        learning events and current preferences. Saves the brief to
        user_preferences and returns it.
        """
        # Load data in parallel-ish fashion
        events = await self.get_learning_events(user_id, limit=100)
        preferences = await self.get_preferences(user_id)

        if not events:
            return {
                "brief": "",
                "event_count": 0,
                "message": "No learning events found. Interact with content to build your learning brief.",
            }

        # Build prompt for Gemini
        events_summary = []
        for ev in events[:50]:  # Cap at 50 for prompt size
            events_summary.append(
                f"- Type: {ev.get('event_type', 'unknown')}, Data: {json.dumps(ev.get('event_data', {}), default=str)[:200]}"
            )

        current_prefs = ""
        if preferences:
            current_prefs = f"""
Current preferences:
- Preferred topics: {preferences.get('preferred_topics', [])}
- Preferred slide count: {preferences.get('preferred_slide_count', 'not set')}
- Caption edit style: {preferences.get('caption_edit_style', 'not set')}
- Total carousels created: {preferences.get('total_carousels', 0)}
- Draft approval rate: {preferences.get('draft_approval_rate', 'not set')}
"""

        prompt = f"""Analyze the following user learning events and preferences to generate a concise learning brief.
The brief should summarize the user's content creation patterns, preferences, and growth areas.
Keep it under 500 words. Be specific and actionable.

{current_prefs}

Recent learning events ({len(events)} total):
{chr(10).join(events_summary)}

Generate a learning brief that covers:
1. Content creation patterns and preferences
2. Strengths identified from their interactions
3. Areas for improvement or exploration
4. Recommended next steps

Return ONLY the brief text, no JSON or markdown headers."""

        try:
            client = get_gemini_client()
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            brief_text = response.text.strip() if response.text else ""
        except Exception as e:
            logger.error("Gemini learning brief generation failed: %s", e)
            brief_text = f"Brief generation temporarily unavailable. You have {len(events)} learning events recorded."

        # Save the brief to user_preferences
        await self.upsert_preferences(user_id, {"learning_brief": brief_text})

        return {
            "brief": brief_text,
            "event_count": len(events),
            "message": "Learning brief generated successfully.",
        }
