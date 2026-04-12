import asyncio

from app.services.research import ResearchService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def insert(self, payload):
        self.payload = payload
        self.client.calls.append((self.table_name, payload))
        return self

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        self.client.calls.append((self.table_name, payload, on_conflict))
        return self

    def execute(self):
        if self.table_name == 'profiles':
            return _Result(self.client.datasets.get('profiles', []))
        if self.table_name == 'account_stats':
            return _Result(self.client.datasets.get('account_stats', []))
        if self.table_name == 'content_with_scores':
            return _Result(self.client.datasets.get('content_with_scores', []))
        if self.table_name == 'research_runs':
            return _Result([{'id': 'run-1', **(self.payload or {})}])
        if self.table_name == 'research_topics':
            return _Result([{'id': 'topic-1', **(self.payload or {})}])
        return _Result([])


class _Client:
    def __init__(self, datasets=None):
        self.calls = []
        self.datasets = datasets or {}

    def table(self, table_name):
        return _Query(self, table_name)


class _ResearchService(ResearchService):
    async def _fetch_reddit(self, niche):
        return [{'source': 'reddit', 'title': 'How to build better hooks', 'topic': 'hooks', 'summary': 'reddit'}]

    async def _fetch_github(self, niche):
        return [{'source': 'github', 'title': 'ai-tools / trend-app', 'topic': 'ai tools', 'summary': 'github'}]

    async def _fetch_news(self, niche):
        return [{'source': 'news', 'title': 'Why creators are changing formats', 'topic': 'creator formats', 'summary': 'news'}]


def test_run_research_saves_run_and_topics():
    client = _Client()
    service = _ResearchService(client)

    result = asyncio.run(service.run_research(user_id='user-1', niche='instagram content', sources=['reddit', 'github', 'news'], limit=3))

    assert result['ready'] is True
    assert result['run_id'] == 'run-1'
    assert len(result['topics']) == 3
    assert client.calls[0][0] == 'research_runs'
    assert client.calls[1][0] == 'research_topics'


def test_run_research_returns_insufficient_signal_when_empty():
    class EmptyResearchService(ResearchService):
        async def _fetch_reddit(self, niche): return []
        async def _fetch_github(self, niche): return []
        async def _fetch_news(self, niche): return []

    service = EmptyResearchService(_Client())
    result = asyncio.run(service.run_research(user_id='user-1', niche='instagram content', sources=['reddit', 'github', 'news']))

    assert result['ready'] is False
    assert result['reason'] == 'insufficient_signal'


def test_run_research_includes_content_studio_context_when_available():
    client = _Client({
        'profiles': [{'content_style_brief': 'Short, direct, educational.'}],
        'account_stats': [{'handle': 'creator1', 'avg_views': 120.0, 'post_count': 3}],
        'content_with_scores': [
            {'views': 300, 'topic': 'hooks', 'hook_structure': 'Contrarian', 'content_type': 'tutorial', 'outlier_category': 'viral', 'source_post_id': 'p1'},
        ],
    })
    service = _ResearchService(client)

    result = asyncio.run(service.run_research(user_id='user-1', niche='instagram content', sources=['reddit'], limit=1))

    assert result['ready'] is True
    assert 'Content Studio Context' in result['brief_markdown']
    assert 'Studio Signals' in result['brief_markdown']
