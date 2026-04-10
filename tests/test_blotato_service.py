from app.services.blotato import build_blotato_connections


def test_build_blotato_connections_prefers_structured_data():
    profile = {
        "blotato_connections": {
            "instagram": {"accountId": "ig-123"},
            "facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-1"},
        },
        "blotato_ig_id": "legacy-ig",
    }

    result = build_blotato_connections(profile)

    assert result["instagram"]["accountId"] == "ig-123"
    assert result["facebook"]["pageId"] == "fb-page-1"


def test_build_blotato_connections_falls_back_to_legacy_ids():
    profile = {
        "blotato_ig_id": "legacy-ig",
        "blotato_fb_account_id": "legacy-fb-acc",
        "blotato_fb_id": "legacy-fb-page",
    }

    result = build_blotato_connections(profile)

    assert result["instagram"]["accountId"] == "legacy-ig"
    assert result["facebook"]["accountId"] == "legacy-fb-acc"
    assert result["facebook"]["pageId"] == "legacy-fb-page"
