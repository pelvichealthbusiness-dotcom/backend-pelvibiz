"""Agent router — maps agent_type + wizard_mode to the correct handler class.

Implements CHAT-302: routing logic with wizard_mode override.
Updated in Batch 4 with WizardIdeasAgent and WizardDraftAgent.
Updated: Added wizard_mode "generate" → WizardGenerateAgent.
"""

from __future__ import annotations

import logging
from typing import Optional, Type, Union

from app.agents.base import BaseStreamingAgent
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def get_agent(
    agent_type: str,
    wizard_mode: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Union[BaseStreamingAgent, "WizardGenerateAgent"]:
    """Route to the correct agent based on type and mode.

    Parameters
    ----------
    agent_type:
        One of: general, real-carousel, ai-carousel, reels-edited-by-ai
    wizard_mode:
        Optional override: "ideas", "draft", or "generate".
        Takes priority over agent_type.
    user_id:
        Authenticated user ID, passed to agent constructor.

    Returns
    -------
    BaseStreamingAgent | WizardGenerateAgent
        An instantiated agent ready to stream.

    Raises
    ------
    ValidationError
        If agent_type or wizard_mode is unknown.
    """
    # Wizard mode overrides agent_type
    if wizard_mode:
        return _resolve_wizard(wizard_mode, agent_type, user_id or "")
    else:
        agent_class = _resolve_agent_type(agent_type)
        return agent_class(user_id=user_id or "", agent_type=agent_type)


# ---------------------------------------------------------------------------
# Internal resolution helpers
# ---------------------------------------------------------------------------

_AGENT_MAP: dict[str, str] = {
    "general": "GeneralChatAgent",
    "real-carousel": "CarouselP1Agent",
    "ai-carousel": "CarouselP2Agent",
    "reels-edited-by-ai": "VideoP3Agent",
    "pelvibiz-ai": "PelvibizAiAgent",
}

_WIZARD_MAP: dict[str, str] = {
    "ideas": "WizardIdeasAgent",
    "draft": "WizardDraftAgent",
    "generate": "WizardGenerateAgent",
    "fix": "WizardFixAgent",
}


def _resolve_wizard(
    wizard_mode: str,
    agent_type: str,
    user_id: str,
) -> Union[BaseStreamingAgent, "WizardGenerateAgent"]:
    if wizard_mode not in _WIZARD_MAP:
        raise ValidationError(f"Unknown wizard mode: {wizard_mode}")

    if wizard_mode == "ideas":
        from app.agents.wizard_ideas import WizardIdeasAgent
        return WizardIdeasAgent(user_id=user_id, agent_type=agent_type)
    elif wizard_mode == "draft":
        from app.agents.wizard_draft import WizardDraftAgent
        return WizardDraftAgent(user_id=user_id, agent_type=agent_type)
    elif wizard_mode == "generate":
        from app.agents.wizard_generate import WizardGenerateAgent
        return WizardGenerateAgent(user_id=user_id, agent_type=agent_type)
    elif wizard_mode == "fix":
        from app.agents.wizard_fix import WizardFixAgent
        return WizardFixAgent(user_id=user_id, agent_type=agent_type)

    # Fallback (should not reach here due to validation above)
    from app.agents.general_chat import GeneralChatAgent
    return GeneralChatAgent(user_id=user_id, agent_type=agent_type)


def _resolve_agent_type(agent_type: str) -> Type[BaseStreamingAgent]:
    if agent_type not in _AGENT_MAP:
        raise ValidationError(f"Unknown agent type: {agent_type}")

    class_name = _AGENT_MAP[agent_type]

    if class_name == "GeneralChatAgent":
        from app.agents.general_chat import GeneralChatAgent
        return GeneralChatAgent
    elif class_name == "CarouselP1Agent":
        from app.agents.carousel_p1 import CarouselP1Agent
        return CarouselP1Agent
    elif class_name == "CarouselP2Agent":
        from app.agents.carousel_p2 import CarouselP2Agent
        return CarouselP2Agent
    elif class_name == "VideoP3Agent":
        from app.agents.video_p3 import VideoP3Agent
        return VideoP3Agent
    elif class_name == "PelvibizAiAgent":
        from app.agents.pelvibiz_ai_agent import PelvibizAiAgent
        return PelvibizAiAgent
    else:
        from app.agents.general_chat import GeneralChatAgent
        return GeneralChatAgent
