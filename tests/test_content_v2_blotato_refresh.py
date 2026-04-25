from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.core.auth import UserContext
from app.routers.content_v2 import schedule_content, ScheduleContentRequest


USER = UserContext(user_id="user-abc", email="test@example.com", role="client", token="tok")


class FakeCRUD:
    def __init__(self, content: dict):
        self.content = content
        self.updates: list[dict] = []

    def get_content(self, content_id: str, user_id: str) -> dict:
        return self.content

    def update_content(self, content_id: str, user_id: str, updates: dict) -> dict:
        self.updates.append(updates)
        self.content = {**self.content, **updates}
        return self.content


class FakeSettings:
    blotato_api_key = "test-api-key"
    blotato_max_retries = 1


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeProfilesTable:
    def __init__(self, profile: dict):
        self.profile = profile
        self.updated_payload: dict | None = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def update(self, payload: dict):
        self.updated_payload = payload
        return self

    def execute(self):
        if self.updated_payload is not None:
            self.profile = {**self.profile, **self.updated_payload}
        return FakeResult(self.profile)


class FakeSupabaseClient:
    def __init__(self, profile: dict):
        self.profile_table = FakeProfilesTable(profile)

    def table(self, name: str):
        assert name == "profiles"
        return self.profile_table


class FakeBlotatoClient:
    async def aclose(self) -> None:
        return None

    async def list_accounts(self):
        return []


@pytest.mark.asyncio
async def test_schedule_refreshes_missing_connections_and_succeeds(monkeypatch):
    fake_crud = FakeCRUD({
        "id": "content-1",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/image.jpg"],
        "reply": "Caption",
        "published": False,
        "publish_status": None,
        "scheduled_date": None,
    })
    fake_client = FakeSupabaseClient({"timezone": "America/New_York", "blotato_connections": None})

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client", lambda: fake_client)
    monkeypatch.setattr(
        "app.routers.content_v2.fetch_blotato_connections",
        AsyncMock(return_value={"instagram": {"accountId": "ig-001"}}),
    )
    monkeypatch.setattr(
        "app.routers.content_v2.validate_connections",
        AsyncMock(return_value=({"instagram": {"accountId": "ig-001"}}, [])),
    )
    monkeypatch.setattr(
        "app.routers.content_v2.BlotatoClient",
        lambda **kwargs: FakeBlotatoClient(),
    )
    monkeypatch.setattr(
        "app.routers.content_v2.blotato_publish",
        AsyncMock(return_value={"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}),
    )
    monkeypatch.setattr(
        "app.routers.content_v2.audit_log_attempt",
        AsyncMock(),
    )

    body = ScheduleContentRequest(scheduled_date="2030-06-15T14:00:00", timezone="America/New_York")
    response = await schedule_content("content-1", body, USER)

    assert response["error"] is None
    assert response["data"]["publish_status"] == "scheduled"
    assert fake_client.profile_table.updated_payload == {"blotato_connections": {"instagram": {"accountId": "ig-001"}}}
    assert fake_crud.updates[-1]["publish_status"] == "scheduled"


@pytest.mark.asyncio
async def test_schedule_forces_refresh_when_existing_connections_are_stale(monkeypatch):
    fake_crud = FakeCRUD({
        "id": "content-2",
        "agent_type": "real-carousel",
        "media_urls": ["https://example.com/image.jpg"],
        "reply": "Caption",
        "published": False,
        "publish_status": None,
        "scheduled_date": None,
    })
    fake_client = FakeSupabaseClient({"timezone": "America/New_York", "blotato_connections": {"instagram": {"accountId": "old-ig"}}})

    monkeypatch.setattr("app.routers.content_v2.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.routers.content_v2.ContentCRUD", lambda: fake_crud)
    monkeypatch.setattr("app.routers.content_v2.get_service_client", lambda: fake_client)
    monkeypatch.setattr(
        "app.routers.content_v2.fetch_blotato_connections",
        AsyncMock(return_value={"instagram": {"accountId": "new-ig"}}),
    )
    monkeypatch.setattr(
        "app.routers.content_v2.validate_connections",
        AsyncMock(side_effect=[({} , ["instagram"]), ({"instagram": {"accountId": "new-ig"}}, [])]),
    )
    monkeypatch.setattr("app.routers.content_v2.BlotatoClient", lambda **kwargs: FakeBlotatoClient())
    monkeypatch.setattr(
        "app.routers.content_v2.blotato_publish",
        AsyncMock(return_value={"instagram": {"id": "sub-1", "status": "scheduled", "error": None}}),
    )
    monkeypatch.setattr("app.routers.content_v2.audit_log_attempt", AsyncMock())

    body = ScheduleContentRequest(scheduled_date="2030-06-15T14:00:00", timezone="America/New_York")
    response = await schedule_content("content-2", body, USER)

    assert response["error"] is None
    assert response["data"]["publish_status"] == "scheduled"
    assert fake_client.profile_table.updated_payload == {"blotato_connections": {"instagram": {"accountId": "new-ig"}}}
