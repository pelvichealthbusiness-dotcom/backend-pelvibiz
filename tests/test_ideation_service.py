import asyncio

from app.services.ideation import IdeationService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.payload = None
        self.filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
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
        if self.table_name == 'research_topics':
            return _Result(self.client.datasets.get('research_topics', []))
        if self.table_name == 'ideation_runs':
            return _Result([{'id': 'run-1', **(self.payload or {})}])
        if self.table_name == 'idea_variations':
            return _Result([{'id': f'idea-{len(self.client.calls)}', **(self.payload or {})}])
        return _Result([])


class _Client:
    def __init__(self, datasets):
        self.datasets = datasets
        self.calls = []

    def table(self, table_name):
        return _Query(self, table_name)


def test_generate_from_research_creates_variations():
    client = _Client({
        'research_topics': [
            {'id': 'topic-1', 'title': 'How creators are using AI tools', 'topic': 'ai tools', 'total_score': 0.92},
            {'id': 'topic-2', 'title': 'Hook frameworks that stop scrolls', 'topic': 'hooks', 'total_score': 0.88},
        ]
    })
    service = IdeationService(client)

    result = asyncio.run(service.generate_from_research(user_id='user-1', niche='instagram content', topic_limit=2, variations_per_topic=5))

    assert result['ready'] is True
    assert result['run_id'] == 'run-1'
    assert len(result['variations']) == 10
    assert client.calls[0][0] == 'ideation_runs'
    assert client.calls[1][0] == 'idea_variations'


def test_generate_from_research_handles_empty_topics():
    service = IdeationService(_Client({'research_topics': []}))
    result = asyncio.run(service.generate_from_research(user_id='user-1', niche='instagram content'))

    assert result['ready'] is False
    assert result['reason'] == 'insufficient_research'


def test_generate_from_research_includes_content_studio_context_when_available():
    client = _Client({
        'profiles': [{'content_style_brief': 'You write with a direct, educational, punchy tone.'}],
        'research_topics': [
            {'id': 'topic-1', 'title': 'How creators are using AI tools', 'topic': 'ai tools', 'total_score': 0.92},
        ],
        'account_stats': [{'handle': 'creator1', 'avg_views': 120.0, 'post_count': 3}],
        'content_with_scores': [
            {'views': 300, 'topic': 'hooks', 'hook_structure': 'Contrarian', 'content_type': 'tutorial', 'outlier_category': 'viral', 'source_post_id': 'p1'},
        ],
    })
    service = IdeationService(client)

    result = asyncio.run(service.generate_from_research(user_id='user-1', niche='instagram content', topic_limit=1, variations_per_topic=1))

    assert result['ready'] is True
    assert 'Content Studio Context' in result['brief_markdown']
    assert 'Studio Signals' in result['brief_markdown']
