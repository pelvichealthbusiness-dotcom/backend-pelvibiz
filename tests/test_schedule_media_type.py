"""Tests for agent_type → media_type mapping used in Blotato scheduling.

RED phase: these tests MUST fail before the implementation is added to blotato.py.
"""
import pytest
from app.services.blotato import agent_type_to_media_type


@pytest.mark.parametrize("agent_type,expected", [
    # Carousel types → IMAGE
    ("real-carousel", "IMAGE"),
    ("ai-carousel", "IMAGE"),
    # Reel types → REEL
    ("reels-edited-by-ai", "REEL"),
    ("ai-video-reels", "REEL"),
    # Post generator → IMAGE
    ("ai-post-generator", "IMAGE"),
])
def test_agent_type_to_media_type_known_types(agent_type: str, expected: str) -> None:
    """Known agent types must map to the correct Blotato media_type."""
    result = agent_type_to_media_type(agent_type)
    assert result == expected, f"Expected {expected!r} for {agent_type!r}, got {result!r}"


def test_agent_type_to_media_type_unknown_returns_image_default() -> None:
    """Unknown or future agent types must default to IMAGE (safe fallback, not 400)."""
    result = agent_type_to_media_type("some-future-agent")
    assert result == "IMAGE"


def test_agent_type_to_media_type_empty_string_returns_image_default() -> None:
    """Empty string agent_type must also default to IMAGE."""
    result = agent_type_to_media_type("")
    assert result == "IMAGE"


def test_agent_type_to_media_type_none_returns_image_default() -> None:
    """None agent_type must also default to IMAGE."""
    result = agent_type_to_media_type(None)
    assert result == "IMAGE"
