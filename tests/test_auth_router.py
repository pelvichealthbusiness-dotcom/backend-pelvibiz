from app.routers.auth_router import _build_full_profile


def test_build_full_profile_includes_visual_fields_and_secondary_font():
    user = type("User", (), {"user_id": "u1", "email": "test@example.com", "role": "client"})()
    profile = {
        "full_name": "Test User",
        "brand_name": "PelviBiz",
        "onboarding_completed": True,
        "credits_used": 3,
        "credits_limit": 40,
        "timezone": "America/New_York",
        "logo_url": "https://example.com/logo.png",
        "brand_voice": "Warm and confident",
        "brand_color_primary": "#111111",
        "brand_color_secondary": "#222222",
        "brand_color_background": "#ffffff",
        "font_style": "minimalist-sans",
        "font_size": "38px",
        "font_prompt": "Hook font prompt",
        "font_style_secondary": "editorial-serif",
        "font_prompt_secondary": "Body font prompt",
        "services_offered": "Pelvic health support",
        "target_audience": "Women 25-45",
        "visual_identity": "Modern, warm, clinical",
        "keywords": "pelvic health, recovery",
        "cta": "Book now",
        "content_style_brief": "Use short clear captions",
        "brand_playbook": "Synthesized playbook",
        "visual_environment_setup": "Warm home office with plants",
        "visual_subject_outfit_face": "Neutral fitted top, soft tones",
        "visual_subject_outfit_generic": "Neutral fitted top, soft tones",
    }

    result = _build_full_profile(user, profile)

    assert result.visual_environment_setup == "Warm home office with plants"
    assert result.visual_subject_outfit_face == "Neutral fitted top, soft tones"
    assert result.visual_subject_outfit_generic == "Neutral fitted top, soft tones"
    assert result.font_style_secondary == "editorial-serif"
    assert result.font_prompt_secondary == "Body font prompt"
    assert result.content_style_brief == "Use short clear captions"
    assert result.brand_playbook == "Use short clear captions"
