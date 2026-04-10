from app.prompts.ideas_generate import build_ideas_system_prompt
from app.services.brand_context import build_brand_context_pack


def test_build_brand_context_pack_includes_visual_and_cta_rules():
    profile = {
        "brand_name": "PelviBiz",
        "brand_voice": "Warm and confident",
        "services_offered": "Pelvic health support",
        "target_audience": "Women 25-45",
        "visual_identity": "Modern and warm",
        "keywords": "pelvic health, recovery",
        "visual_environment_setup": "Warm home office with plants",
        "visual_subject_outfit_face": "Neutral fitted top",
        "visual_subject_outfit_generic": "Neutral fitted top",
        "content_style_brief": "Short, clear captions",
        "cta": "Book now",
    }

    pack = build_brand_context_pack(profile)

    assert pack["brand"]["name"] == "PelviBiz"
    assert pack["visual"]["environment"] == "Warm home office with plants"
    assert pack["content"]["style_brief"] == "Short, clear captions"
    assert pack["cta_rules"]["tone"] == "Warm and confident"
    assert "CTAs must be generated dynamically" in pack["brand_brief"]


def test_ideas_prompt_requires_five_and_seed_expansion():
    prompt = build_ideas_system_prompt(
        brand_brief="## Brand DNA\n- Brand name: PelviBiz",
        learning_section="",
        anti_repetition="",
        count=5,
        wizard_mode="ideas",
    )

    assert "Generate exactly 5 Instagram carousel concepts" in prompt
    assert "seed idea" in prompt.lower()
    assert "distinct angles" in prompt.lower()
