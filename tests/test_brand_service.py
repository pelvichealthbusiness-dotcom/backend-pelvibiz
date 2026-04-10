import asyncio

from app.services.brand import BrandService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def single(self):
        return self

    def execute(self):
        return _Result(self._data)


class _Client:
    def __init__(self, data):
        self._data = data

    def table(self, *_args, **_kwargs):
        return _Query(self._data)


def test_load_profile_includes_blotato_fields():
    client = _Client(
        {
            "id": "u1",
            "brand_name": "PelviBiz",
            "blotato_connections": {
                "instagram": {"accountId": "ig-123"},
                "facebook": {"accountId": "fb-acc-1", "pageId": "fb-page-1"},
            },
        }
    )

    result = asyncio.run(BrandService(client).load_profile("u1"))

    assert result["blotato_connections"]["instagram"]["accountId"] == "ig-123"
    assert result["blotato_connections"]["facebook"]["pageId"] == "fb-page-1"
