"""Brand stories loader — used by wizard agents to inject relevant stories."""
from __future__ import annotations
import logging
from app.core.supabase_client import get_service_client

logger = logging.getLogger(__name__)


async def load_user_stories(user_id: str) -> list[dict]:
    """Load all brand stories for a user. Returns [] on error."""
    client = get_service_client()
    try:
        result = (
            client.table("brand_stories")
            .select("id, title, content")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .limit(20)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Failed to load brand stories for %s: %s", user_id, exc)
        return []


def build_stories_prompt_block(stories: list[dict], topic: str = "") -> str:
    """Build the stories injection block for AI prompts.
    
    Instructs the AI to pick the most relevant story for the given topic.
    Returns empty string if no stories.
    """
    if not stories:
        return ""

    topic_hint = f'The content topic is: "{topic[:300]}".\n' if topic.strip() else ""
    stories_text = "\n\n".join(
        f"[{s.get('title', 'Story')}]\n{s['content'][:600]}"
        for s in stories
    )

    return f"""### PATIENT/CLIENT STORIES — select the most relevant
{topic_hint}From the stories below, pick 1-2 that are most relevant to the topic above.
Reference them naturally to make the content authentic and specific.
Do NOT copy verbatim — use as inspiration. Do NOT use all stories, only the most relevant.

{stories_text}"""
