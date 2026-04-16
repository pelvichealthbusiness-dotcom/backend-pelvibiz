import asyncio

from app.models.analyzer import AnalyzeRequest
from app.routers import analyzer as analyzer_module


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.payload = None
        self._filter = {}

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.payload = payload
        self.client.inserts.append((self.table_name, payload))
        return self

    def update(self, payload):
        self.client.updates.append((self.table_name, payload, self._filter))
        return self

    def delete(self):
        self.client.deletes.append((self.table_name, self._filter))
        return self

    def eq(self, col, val):
        self._filter[col] = val
        return self

    def not_(self):
        return self

    # Support `.not_.is_(...)` chaining
    def is_(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        data = self.client.datasets.get(self.table_name, [])
        if self.payload is not None:
            return _Result([self.payload])
        if data and isinstance(data[0], dict):
            return _Result(data)
        return _Result(data)


class _NotProxy:
    """Proxy to support `.not_.is_(...)` style chaining."""
    def __init__(self, query):
        self._query = query

    def is_(self, *_args, **_kwargs):
        return self._query


class _SupabaseClient:
    def __init__(self, datasets=None):
        self.inserts = []
        self.updates = []
        self.deletes = []
        self.datasets = datasets or {}

    def table(self, table_name):
        q = _Query(self, table_name)
        # Attach not_ proxy
        q.not_ = _NotProxy(q)
        return q


class _FakeScraper:
    async def scrape(self, username, max_posts, user_id=None):
        return (
            {
                'username': username,
                'full_name': 'Creator One',
                'followers': 1234,
                'following': 10,
                'is_verified': True,
                'profile_pic_url': 'https://example.com/pic.jpg',
            },
            [
                {
                    'id': 'post-1',
                    'caption': 'First hook',
                    'likes': 100,
                    'comments': 12,
                    'timestamp': 1712700000,
                    'media_type': 2,
                    'is_carousel': False,
                }
            ],
        )


_FAKE_METRICS = {
    'caption_avg_length': 12,
    'hook_types': {'question': 1.0},
    'hook_second_person_rate': 0.8,
    'cta_types': {'follow': 1.0},
    'emoji_frequency': 0.0,
    'hashtag_avg_count': 0,
    'content_categories': {'educational': 1.0},
    'top_keywords': [{'word': 'hook'}],
    'engagement_rate': 0.05,
}


class _FakeAnalyzer:
    def analyze(self, posts, profile_data):
        return _FAKE_METRICS


class _FakeContentService:
    def __init__(self):
        self.calls = []

    async def store_scrape(self, **kwargs):
        self.calls.append(kwargs)
        return {'account': {'id': 'acc-1'}, 'posts': [{'id': 'content-1'}]}

    async def generate_brief(self, **kwargs):
        return {'ready': True, 'brief_markdown': '## Brief', 'content_rows': [], 'account_stats': [], 'summary': {}}


def test_analyze_instagram_persists_new_pipeline_and_legacy_scrape(monkeypatch):
    supabase = _SupabaseClient()
    fake_content_service = _FakeContentService()

    monkeypatch.setattr(analyzer_module, 'InstagramScraper', _FakeScraper)
    monkeypatch.setattr(analyzer_module, 'StyleAnalyzer', _FakeAnalyzer)
    monkeypatch.setattr(analyzer_module, 'ContentIntelligenceService', lambda: fake_content_service)
    monkeypatch.setattr(analyzer_module, 'get_supabase_admin', lambda: supabase)

    result = asyncio.run(
        analyzer_module.analyze_instagram(
            AnalyzeRequest(username='creator1', max_posts=10, generate_voice_summary=False),
            user={'id': 'user-1'},
        )
    )

    assert result.scrape_id == 'acc-1'
    assert result.username == 'creator1'
    assert fake_content_service.calls[0]['handle'] == 'creator1'
    assert fake_content_service.calls[0]['posts'][0]['id'] == 'post-1'
    assert fake_content_service.calls[0]['posts'][0]['media_type'] == 'reel'

    # Verify metrics are persisted via update
    assert len(supabase.updates) == 1
    table, payload, filters = supabase.updates[0]
    assert table == 'content_accounts'
    assert payload['metadata']['style_metrics'] == _FAKE_METRICS
    assert payload['metadata']['post_count'] == 1
    assert 'analyzed_at' in payload['metadata']
    assert filters.get('id') == 'acc-1'


def test_list_analyzed_accounts_returns_only_style_analyzed(monkeypatch):
    accounts_with_metrics = [
        {
            'id': 'acc-1',
            'handle': 'creator1',
            'display_name': 'Creator One',
            'metadata': {'style_metrics': _FAKE_METRICS, 'followers': 1234, 'analyzed_at': '2026-04-01T00:00:00Z'},
            'created_at': '2026-04-01T00:00:00Z',
        }
    ]
    supabase = _SupabaseClient(datasets={'content_accounts': accounts_with_metrics})
    monkeypatch.setattr(analyzer_module, 'get_supabase_admin', lambda: supabase)

    result = asyncio.run(
        analyzer_module.list_analyzed_accounts(user={'id': 'user-1'})
    )

    assert 'accounts' in result
    assert len(result['accounts']) == 1
    assert result['accounts'][0]['handle'] == 'creator1'


def test_delete_analyzed_account_removes_posts_and_account(monkeypatch):
    supabase = _SupabaseClient(
        datasets={
            'content_accounts': [{'id': 'acc-1', 'user_id': 'user-1'}],
        }
    )
    monkeypatch.setattr(analyzer_module, 'get_supabase_admin', lambda: supabase)

    result = asyncio.run(
        analyzer_module.delete_analyzed_account('acc-1', user={'id': 'user-1'})
    )

    assert result['deleted'] is True
    assert result['id'] == 'acc-1'
    deleted_tables = [t for t, _ in supabase.deletes]
    assert 'content_posts' in deleted_tables
    assert 'content_accounts' in deleted_tables
