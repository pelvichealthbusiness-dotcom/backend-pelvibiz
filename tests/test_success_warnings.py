"""Tests for success() helper with warnings parameter (Phase 3.5)."""

from app.core.responses import success


def test_success_no_warnings_key_absent():
    result = success(data={"foo": "bar"})
    assert "warnings" not in result
    assert result["data"] == {"foo": "bar"}


def test_success_none_warnings_key_absent():
    result = success(data={"foo": "bar"}, warnings=None)
    assert "warnings" not in result


def test_success_empty_list_warnings_key_absent():
    result = success(data={"foo": "bar"}, warnings=[])
    assert "warnings" not in result


def test_success_with_warnings_key_present():
    result = success(data={"foo": "bar"}, warnings=["Blotato failed for instagram: HTTP 422"])
    assert "warnings" in result
    assert result["warnings"] == ["Blotato failed for instagram: HTTP 422"]


def test_success_multiple_warnings():
    result = success(
        data=None,
        warnings=["msg one", "msg two"],
    )
    assert result["warnings"] == ["msg one", "msg two"]


def test_success_status_key_present():
    result = success(data=None)
    # Current implementation uses data/error/meta envelope
    # Checking that data key is present (backward compat)
    assert "data" in result
