from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError
from app.services.blotato_admin_service import assign_account


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeProfilesTable:
    def __init__(self, profiles: list[dict]):
        self.profiles = profiles
        self._eq_id: str | None = None
        self.updated_payload: dict | None = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, field: str, value):
        if field == "id":
            self._eq_id = value
        return self

    def update(self, payload: dict):
        self.updated_payload = payload
        return self

    def execute(self):
        if self.updated_payload is not None:
            target = next((p for p in self.profiles if p["id"] == self._eq_id), None)
            if target is not None:
                target.update(self.updated_payload)
            return _FakeResult([target] if target else [])

        if self._eq_id is None:
            return _FakeResult(self.profiles)

        target = next((p for p in self.profiles if p["id"] == self._eq_id), None)
        return _FakeResult([target] if target else [])


class _FakeDB:
    def __init__(self, profiles: list[dict]):
        self.profiles = profiles
        self.profiles_table = _FakeProfilesTable(self.profiles)

    def table(self, name: str):
        assert name == "profiles"
        return self.profiles_table


@pytest.mark.asyncio
async def test_assign_account_rejects_duplicate_account(monkeypatch):
    fake_db = _FakeDB([
        {
            "id": "u-1",
            "full_name": "Alice",
            "blotato_connections": {"instagram": {"accountId": "ig-123"}},
        },
        {
            "id": "u-2",
            "full_name": "Bob",
            "blotato_connections": {},
        },
    ])

    monkeypatch.setattr("app.services.blotato_admin_service.get_service_client", lambda: fake_db)

    with pytest.raises(ConflictError, match="already assigned to Alice"):
        await assign_account(user_id="u-2", platform="instagram", account_id="ig-123")


@pytest.mark.asyncio
async def test_assign_account_updates_unique_assignment(monkeypatch):
    fake_db = _FakeDB([
        {
            "id": "u-1",
            "full_name": "Alice",
            "blotato_connections": {},
        },
        {
            "id": "u-2",
            "full_name": "Bob",
            "blotato_connections": {},
        },
    ])

    monkeypatch.setattr("app.services.blotato_admin_service.get_service_client", lambda: fake_db)

    result = await assign_account(user_id="u-2", platform="facebook", account_id="fb-123", page_id="page-1")

    assert result["user_id"] == "u-2"
    assert result["blotato_connections"]["facebook"]["accountId"] == "fb-123"
    assert result["blotato_connections"]["facebook"]["pageId"] == "page-1"
