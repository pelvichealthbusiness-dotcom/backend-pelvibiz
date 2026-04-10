from __future__ import annotations


def _value(profile: dict, field: str, fallback: str = "") -> str:
    value = profile.get(field, "")
    if isinstance(value, dict):
        value = value.get("value", "")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def build_brand_context_pack(profile: dict) -> dict:
    brand_name = _value(profile, "brand_name", "the brand")
    voice = _value(profile, "brand_voice", "professional and approachable")
    audience = _value(profile, "target_audience", "general audience")
    services = _value(profile, "services_offered", "professional services")
    visual_identity = _value(profile, "visual_identity", "clean and modern")
    keywords = _value(profile, "keywords", "")
    env = _value(profile, "visual_environment_setup", "")
    outfit_face = _value(profile, "visual_subject_outfit_face", "")
    outfit_generic = _value(profile, "visual_subject_outfit_generic", "")
    style_brief = _value(profile, "content_style_brief", "")
    cta_tone = _value(profile, "brand_voice", "warm, specific, low-friction, and on-brand")

    brand_brief_lines = [
        f"## Brand DNA — {brand_name}",
        "",
        "### Identity",
        f"- Brand name: {brand_name}",
        f"- Services: {services}",
        f"- Audience: {audience}",
        f"- Voice & tone: {voice}",
    ]
    if keywords:
        brand_brief_lines.append(f"- Keywords: {keywords}")

    brand_brief_lines.extend([
        "",
        "### Visual Language",
        f"- Visual identity: {visual_identity}",
        f"- Environment: {env or 'professional and platform-appropriate'}",
        f"- Subject outfit (client face): {outfit_face or 'consistent with brand personality'}",
        f"- Subject outfit (generic): {outfit_generic or 'consistent with brand personality'}",
        "",
        "### Content Rules",
        f"- Writing DNA: {style_brief or 'short, clear, social-first, and easy to scan'}",
        "- Hooks should be scroll-stopping, specific, and non-generic.",
        "- CTAs must be generated dynamically from the topic and draft.",
        f"- CTA tone/rules: {cta_tone}",
    ])

    return {
        "brand": {
            "name": brand_name,
            "voice": voice,
            "audience": audience,
            "services": services,
        },
        "visual": {
            "identity": visual_identity,
            "environment": env,
            "outfit_face": outfit_face,
            "outfit_generic": outfit_generic,
        },
        "content": {
            "style_brief": style_brief,
            "keywords": keywords,
        },
        "cta_rules": {
            "tone": cta_tone,
            "allowed_verbs": ["save", "share", "comment", "DM", "book", "learn"],
            "avoid": ["generic", "aggressive", "salesy"],
        },
        "brand_brief": "\n".join(brand_brief_lines),
    }
