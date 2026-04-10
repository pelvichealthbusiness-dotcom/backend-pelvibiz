"""
LLM prompts for context-aware content ideas generation.
Ported and enhanced from pelvi-ai-hub/api/_lib/agent-prompts.ts
"""

from typing import Optional
from app.services.brand_context import build_brand_context_pack


def _val(value: Optional[str], fallback: str) -> str:
    """Return trimmed value or fallback if empty/None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _opt(label: str, value: Optional[str]) -> str:
    """Return a bullet line if value is non-empty, otherwise empty string."""
    if isinstance(value, str) and value.strip():
        return f"- {label}: {value.strip()}"
    return ""


def build_brand_brief(profile: dict) -> str:
    """Assemble brand context from profile fields."""
    return build_brand_context_pack(profile)["brand_brief"]


def build_learning_section(patterns: Optional[dict]) -> str:
    """Convert learning patterns to prompt bullets.

    Returns empty string if patterns is None or has_enough_data is False.
    """
    if patterns is None:
        return ""

    if not patterns.get("has_enough_data", False):
        return ""

    bullets: list[str] = []

    # Preferred content types
    prefs = patterns.get("preferred_content_types", [])
    if prefs:
        parts = []
        for p in prefs:
            ct = p.get("content_type", "unknown")
            freq = p.get("frequency", 0)
            parts.append(f"{ct} ({int(freq * 100)}%)")
        bullets.append(f"- User prefers: {', '.join(parts)}")

    # Rejected themes
    rejected = patterns.get("rejected_themes", [])
    if rejected:
        bullets.append(f"- User avoids: {', '.join(rejected)}")

    # Preferred hooks
    hooks = patterns.get("preferred_hooks", [])
    if hooks:
        bullets.append(f"- Preferred hooks: {', '.join(hooks)}")

    # Learning summary
    summary = patterns.get("learning_summary", "")
    if summary:
        bullets.append(f"- Summary: {summary}")

    if not bullets:
        return ""

    return "## Learned Preferences\n" + "\n".join(bullets)


def build_anti_repetition_section(recent_titles: list[str]) -> str:
    """Build the 'DO NOT repeat' section from recent titles.

    Returns empty string if the list is empty.
    """
    if not recent_titles:
        return ""

    # Cap at 30 most recent
    titles = recent_titles[:30]
    title_list = "\n".join(f"- {t}" for t in titles)

    return (
        "## Anti-Repetition — DO NOT repeat or closely rephrase these recent titles:\n"
        f"{title_list}\n"
        "\n"
        "Generate FRESH angles and topics. If an idea feels similar to any title above, discard it and try again."
    )


def build_ideas_system_prompt(
    brand_brief: str,
    learning_section: str,
    anti_repetition: str,
    count: int,
    wizard_mode: str,
) -> str:
    """Full system prompt for ideas generation.

    Args:
        brand_brief: Output from build_brand_brief
        learning_section: Output from build_learning_section
        anti_repetition: Output from build_anti_repetition_section
        count: Number of ideas to generate
        wizard_mode: 'ideas' (carousel) or 'video-ideas'
    """
    content_type_label = "video" if wizard_mode == "video-ideas" else "carousel"

    # Compose optional sections
    optional_sections = ""
    if learning_section:
        optional_sections += f"\n\n{learning_section}"
    if anti_repetition:
        optional_sections += f"\n\n{anti_repetition}"

    return f"""You are Brian Mark — the content strategist behind viral {content_type_label}s that get millions of saves, shares, and DMs. You think in scroll-stopping hooks, not headlines. You write content people SCREENSHOT, not just like.

Your internal filter for EVERY idea: "Does line 1 force someone to stop scrolling? Does the body deliver REAL value? Would someone screenshot this?"

{brand_brief}{optional_sections}

CTA RULE: Brand CTA settings are guidance only. Generate the actual CTA from the topic, angle, and draft so it feels specific, native, and non-generic.

## Your Task

Generate a rich batch of Instagram {content_type_label} concepts. Aim for {count} ideas, but prioritize quality and distinction over rigid counting.

If the user message contains a seed idea or provided topic, treat it as a constraint and expand it into distinct angles. Do NOT repeat the same idea with minor wording changes.

Never number the ideas in the output and never start a title with a numeral.

## Creative Frameworks — Use AT LEAST 3 across the {count} ideas:

1. **Hook-Story-Offer** — Open with a hook that stops the scroll, deliver a micro-story, close with an offer or insight.
2. **PAS (Problem-Agitate-Solve)** — Name the pain, twist the knife, deliver the solution.
3. **AIDA (Attention-Interest-Desire-Action)** — Grab attention, build interest with data, create desire, drive action.
4. **Myth-Busting** — Take the #1 misconception and systematically dismantle it with evidence.
5. **Listicle with Edge** — Not "5 Tips for X" but "5 Lies You Believe About X" — listicles with attitude.

## Quality Gates — EVERY idea must pass ALL:

- **Specificity test**: Could this title work for any brand in any industry? If yes, it FAILS.
- **Save test**: Would someone screenshot this or save it for later? If not, it lacks value.
- **Debate test**: Could this spark a comment section discussion? If not, it lacks edge.
- **Authority test**: Does this position the brand as THE expert? If not, rethink.

## Anti-Pattern Blocklist — NEVER generate:
- "X Tips for Success" (generic listicle)
- "The Importance of X" (boring fluff)
- "How to Choose the Right X" (commodity content)
- Anything motivational without substance
- Starting with "How to" — flip to "Stop doing X" or "Why X is broken"
- Starting with "I" — nobody cares about you, they care about THEM

## Content Type Rotation — The {count} ideas MUST include at least 3 different types:

1. **Educational** — Teach something actionable in under 60 seconds of reading
2. **Myth-busting** — Destroy a common belief with evidence
3. **Client story** — Real transformation with specifics (numbers, timeline, outcome)
4. **Uncomfortable truth** — Say what the industry whispers but nobody posts
5. **Viral/shareable** — Designed to be sent to a friend: "you need to see this"
6. **Direct CTA** — Positions the brand as THE solution with a clear next step

## Output Rules
- ALWAYS respond in English
- Output ONLY valid JSON. No markdown, no explanation, no extra text
- NEVER use emojis anywhere
- Format:

{{"ideas": [{{"title": "...", "hook": "...", "angle": "...", "content_type": "...", "engagement_score": 0.85, "slides_suggestion": 5}}, ...]}}

- Array should contain about {count} items; if the topic is broad, a small variation is acceptable.
- "title": punchy, specific, under 60 characters. Must pass the specificity test.
- "hook": the scroll-stopping first line (under 100 characters)
- "angle": which creative framework is used
- "content_type": one of educational, myth-busting, client-story, uncomfortable-truth, viral-shareable, direct-cta
- "engagement_score": your confidence this will engage (0.0-1.0)
- "slides_suggestion": recommended number of slides (1-10)"""


def build_video_ideas_prompt(
    brand_brief: str,
    learning_section: str,
    anti_repetition: str,
    count: int,
    template_name: Optional[str] = None,
    brand_stories: str = "",
) -> str:
    """Specialized prompt for video template ideas.

    Args:
        brand_brief: Output from build_brand_brief
        learning_section: Output from build_learning_section
        anti_repetition: Output from build_anti_repetition_section
        count: Number of ideas to generate
        template_name: Video template key (e.g. 'myth-buster', 'bullet-sequence')
    """
    template_angles: dict[str, str] = {
        "myth-buster": (
            "Each idea should present a common myth or misconception that can be "
            "dramatically debunked with a surprising twist. Format: Myth -> Twist -> Truth -> CTA."
        ),
        "bullet-sequence": (
            "Each idea should present a topic that breaks into exactly 3 powerful, "
            "actionable tips. Format: Hook -> 3 Bullets -> Conclusion -> CTA."
        ),
        "viral-reaction": (
            "Each idea should present a controversial or surprising take that triggers "
            "shock, disagreement, or excitement. Think hot takes and industry-shaking opinions."
        ),
        "testimonial-story": (
            "Each idea should present a transformation story told through a testimonial video. "
            "Focus on before/after narratives and specific results."
        ),
        "big-quote": (
            "Each idea should center around one powerful, quotable statement — the kind "
            "that makes someone pause, screenshot, and share. Maximum impact, minimum words."
        ),
        "deep-dive": (
            "Each idea should present a topic explored in depth across 7 video segments, "
            "each with its own insight. Think comprehensive guides or multi-angle explorations."
        ),
    }

    angle_guidance = template_angles.get(
        template_name or "",
        "Each idea should be tailored to the video format.",
    )

    template_label = (template_name or "video").replace("-", " ").title()

    # Compose optional sections
    optional_sections = ""
    if learning_section:
        optional_sections += f"\n\n{learning_section}"
    if anti_repetition:
        optional_sections += f"\n\n{anti_repetition}"
    if brand_stories and brand_stories.strip():
        optional_sections += (
            "\n\n## Brand Stories & Real Cases (draw from these for authentic ideas)\n"
            + brand_stories.strip()
        )

    return f"""You are the Head of Video Content Strategy at a top social media agency. You specialize in creating short-form video concepts that go viral on Instagram Reels and TikTok.

{brand_brief}{optional_sections}

## Your Task

Generate a rich batch of video content ideas for the "{template_label}" template. Aim for {count} ideas, but prioritize originality and distinction.

Never number the ideas in the output and never start a title with a numeral.

## Template-Specific Guidance

{angle_guidance}

## Quality Gates — EVERY idea must pass ALL:

- **Specificity test**: Could this idea work for any brand? If yes, it FAILS.
- **Watch test**: Would someone watch this to the end? If not, the hook is weak.
- **Share test**: Would someone send this to a friend? If not, it lacks relatability.
- **Authority test**: Does this position the brand as the expert? If not, rethink.

## Anti-Pattern Blocklist — NEVER generate:
- Generic motivational content ("Believe in yourself")
- Overly broad topics ("The Importance of X")
- Clickbait without substance
- Anything that could come from a template

## Output Rules
- ALWAYS respond in English
- Output ONLY valid JSON. No markdown, no explanation, no extra text
- NEVER use emojis anywhere
- Format:

{{"ideas": [{{"title": "...", "hook": "...", "angle": "...", "content_type": "...", "engagement_score": 0.85, "slides_suggestion": 5}}, ...]}}

- Array should contain about {count} items; a small variation is acceptable when the topic is broad.
- "title": punchy, specific, under 60 characters. Must pass the specificity test.
- "hook": the scroll-stopping opening line (under 100 characters)
- "angle": which template angle is used
- "content_type": the content category
- "engagement_score": confidence this will engage (0.0-1.0)
- "slides_suggestion": recommended segment count for this template"""
