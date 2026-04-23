import pytest

from app.services.blotato import (
    build_blotato_connections,
    normalize_blotato_connections,
    get_account_for_platform,
)


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


def test_normalize_blotato_connections_maps_platforms():
    accounts = [
        {"id": "ig-1", "platform": "instagram"},
        {"id": "fb-1", "platform": "facebook"},
        {"id": "yt-1", "platform": "youtube"},
        {"id": "yt-playlist-1", "platform": "youtube"},
    ]

    result = normalize_blotato_connections(accounts)

    assert result["instagram"]["accountId"] == "ig-1"
    assert result["facebook"]["accountId"] == "fb-1"
    assert result["youtube"]["accountId"] == "yt-1"


# ---------------------------------------------------------------------------
# get_account_for_platform
# ---------------------------------------------------------------------------

def test_get_account_for_platform_returns_connection_dict():
    connections = {
        "instagram": {"accountId": "ig-001"},
        "facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-99"},
    }

    result = get_account_for_platform(connections, "instagram")

    assert result == {"accountId": "ig-001"}


def test_get_account_for_platform_returns_facebook_with_page_id():
    connections = {
        "facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-99"},
    }

    result = get_account_for_platform(connections, "facebook")

    assert result["accountId"] == "fb-acc-1"
    assert result["pageId"] == "fb-page-99"


def test_get_account_for_platform_raises_key_error_for_missing_platform():
    connections = {"instagram": {"accountId": "ig-001"}}

    with pytest.raises(KeyError, match="twitter"):
        get_account_for_platform(connections, "twitter")
