from __future__ import annotations

from difflib import SequenceMatcher


SIMILARITY_THRESHOLD = 0.82


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _fallback_idea(profile: dict, seed: str, index: int) -> dict:
    brand = profile.get("brand_name") or "the brand"
    voice = profile.get("brand_voice") or "professional"
    hooks = [
        f"The {seed or brand} mistake people keep making",
        f"Why {seed or brand} works when the usual advice fails",
        f"The unexpected {seed or brand} shift nobody talks about",
        f"What happens when {seed or brand} gets simpler",
        f"The 60-second lesson hiding inside {seed or brand}",
    ]
    content_types = ["educational", "myth-busting", "client-story", "uncomfortable-truth", "viral-shareable"]
    idx = index % len(hooks)
    return {
        "id": f"fallback-{index}",
        "title": hooks[idx],
        "hook": hooks[idx],
        "angle": f"{voice} angle",
        "content_type": content_types[idx],
        "engagement_score": 0.55,
        "slides_suggestion": 5,
    }


def review_ideas(profile: dict, ideas: list[dict], count: int = 5, seed_idea: str = "") -> list[dict]:
    reviewed: list[dict] = []
    for idea in ideas:
        title = idea.get("title", "")
        hook = idea.get("hook", title)
        if any(_similar(title, existing.get("title", "")) > SIMILARITY_THRESHOLD for existing in reviewed):
            continue
        if any(_similar(hook, existing.get("hook", existing.get("title", ""))) > SIMILARITY_THRESHOLD for existing in reviewed):
            continue
        reviewed.append(idea)

    seed = (seed_idea or profile.get("brand_name") or "").strip()
    idx = 0
    while len(reviewed) < count:
        reviewed.append(_fallback_idea(profile, seed, idx))
        idx += 1

    return reviewed[:count]


def _ensure_dynamic_cta(caption: str, profile: dict) -> str:
    caption = (caption or "").strip()
    if not caption:
        return caption
    lowered = caption.lower()
    if any(token in lowered for token in ["comment", "save", "share", "dm", "book", "learn", "visit"]):
        return caption
    tone = profile.get("brand_voice") or "warm"
    return f"{caption}\n\nSave this if it fits your {tone} brand."


def review_plan(profile: dict, plan: dict) -> dict:
    reviewed = dict(plan)
    slides = reviewed.get("slides", [])
    cleaned = []
    seen_texts: list[str] = []
    for slide in slides:
        text = str(slide.get("text", "")).strip()
        if not text:
            continue
        if any(_similar(text, existing) > SIMILARITY_THRESHOLD for existing in seen_texts):
            continue
        seen_texts.append(text)
        cleaned.append(slide)

    reviewed["slides"] = cleaned or slides
    if "caption" in reviewed:
        reviewed["caption"] = _ensure_dynamic_cta(reviewed.get("caption", ""), profile)

    reviewed["brand_harmony_score"] = round(min(0.98, 0.70 + (len(cleaned) / max(len(slides), 1)) * 0.25), 2)
    reviewed["brand_harmony_notes"] = "Aligned to brand context; dynamic CTA enforced." if reviewed.get("caption") else "No caption to review."
    return reviewed
