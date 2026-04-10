from app.services.brand_harmony import review_ideas, review_plan


def test_review_ideas_pads_to_five_and_removes_duplicates():
    profile = {"brand_name": "PelviBiz", "brand_voice": "Warm and confident"}
    ideas = [
        {"title": "Stop the leak", "hook": "Stop the leak", "content_type": "educational"},
        {"title": "Stop the leak", "hook": "Stop the leak", "content_type": "educational"},
    ]

    reviewed = review_ideas(profile, ideas, count=5, seed_idea="Leak confidence")

    assert len(reviewed) == 5
    assert len({idea["title"] for idea in reviewed}) == 5
    assert any("Leak confidence" in idea["title"] for idea in reviewed)


def test_review_plan_appends_dynamic_cta():
    profile = {"brand_voice": "Warm and confident"}
    plan = {
        "slides": [
            {"number": 1, "text": "Your body is not broken"},
            {"number": 2, "text": "You deserve better care"},
        ],
        "caption": "A clear explanation of why this matters.",
    }

    reviewed = review_plan(profile, plan)

    assert "save" in reviewed["caption"].lower()
    assert reviewed["brand_harmony_score"] >= 0.7
