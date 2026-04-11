import asyncio

from app.services.content_intelligence import ContentIntelligenceService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.payload = None
        self.on_conflict = None

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        self.on_conflict = on_conflict
        self.client.calls.append((self.table_name, payload, on_conflict))
        return self

    def execute(self):
        if self.table_name == 'content_accounts':
            return _Result([{'id': 'acc-1', **(self.payload or {})}])
        if self.table_name == 'content':
            return _Result([{'id': 'content-1', **(self.payload or {})}])
        if self.table_name == 'content_snapshots':
            return _Result([{'id': 'snapshot-1', **(self.payload or {})}])
        return _Result([])


class _Client:
    def __init__(self):
        self.calls = []

    def table(self, table_name):
        return _Query(self, table_name)


def test_store_scrape_writes_account_content_and_snapshot():
    client = _Client()
    service = ContentIntelligenceService(client)

    result = asyncio.run(
        service.store_scrape(
            user_id='user-1',
            handle='creator1',
            posts=[
                {
                    'id': 'post-1',
                    'caption': 'Hook first.',
                    'views': 100,
                    'likes': 10,
                    'comments': 2,
                }
            ],
        )
    )

    assert result['account']['handle'] == 'creator1'
    assert result['posts'][0]['source_post_id'] == 'post-1'
    assert [call[0] for call in client.calls] == ['content_accounts', 'content', 'content_snapshots']


def test_upsert_content_defaults_to_pending_analysis():
    client = _Client()
    service = ContentIntelligenceService(client)

    result = asyncio.run(
        service.upsert_content(
            user_id='user-1',
            account_id='acc-1',
            source_post_id='post-1',
        )
    )

    assert result['analysis_status'] == 'pending'
    assert client.calls[0][0] == 'content'
