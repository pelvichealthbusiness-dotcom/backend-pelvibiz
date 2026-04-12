from app.services.content_crud import ContentCRUD


class _Result:
    def __init__(self, data=None):
        self.data = data or []


class _InsertBuilder:
    def __init__(self, client, payload):
        self.client = client
        self.payload = payload

    def execute(self):
        self.client.payloads.append(self.payload)
        return _Result([{"id": self.payload.get("id", "generated-id"), **self.payload}])


class _Table:
    def __init__(self, client):
        self.client = client

    def insert(self, payload):
        return _InsertBuilder(self.client, payload)


class _Client:
    def __init__(self):
        self.payloads = []

    def table(self, _name):
        return _Table(self)


def test_create_content_does_not_send_metadata_column():
    crud = ContentCRUD.__new__(ContentCRUD)
    crud.client = _Client()

    result = crud.create_content(
        user_id='user-1',
        content_id='content-1',
        agent_type='reels-edited-by-ai',
        title='Test',
        caption='Caption',
        reply='Reply',
        media_urls=['https://example.com/video.mp4'],
        reel_category='myth-buster',
        metadata={'kind': 'video_generation_attempt'},
    )

    assert crud.client.payloads[0]['user_id'] == 'user-1'
    assert 'metadata' not in crud.client.payloads[0]
    assert result['id'] == 'content-1'
