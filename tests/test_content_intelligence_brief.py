import asyncio

from app.services.content_intelligence import ContentIntelligenceService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table_name, datasets):
        self.table_name = table_name
        self.datasets = datasets
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

    def execute(self):
        if self.table_name == 'account_stats':
            return _Result(self.datasets['account_stats'])
        if self.table_name == 'content_with_scores':
            return _Result(self.datasets['content_with_scores'])
        return _Result([])


class _Client:
    def __init__(self, datasets):
        self.datasets = datasets

    def table(self, table_name):
        return _Query(table_name, self.datasets)


def test_generate_brief_builds_markdown_summary():
    client = _Client(
        {
            'account_stats': [
                {'handle': 'creator1', 'avg_views': 120.0, 'post_count': 3},
                {'handle': 'creator2', 'avg_views': 80.0, 'post_count': 2},
            ],
            'content_with_scores': [
                {'views': 300, 'topic': 'hooks', 'hook_structure': 'Contrarian', 'content_type': 'tutorial', 'outlier_category': 'viral', 'source_post_id': 'p1'},
                {'views': 120, 'topic': 'hooks', 'hook_structure': 'Educational', 'content_type': 'tutorial', 'outlier_category': 'average', 'source_post_id': 'p2'},
                {'views': 60, 'topic': 'briefs', 'hook_structure': 'Question', 'content_type': 'demo', 'outlier_category': 'below_average', 'source_post_id': 'p3'},
            ],
        }
    )
    service = ContentIntelligenceService(client)

    result = asyncio.run(service.generate_brief(user_id='user-1'))

    assert result['ready'] is True
    assert result['summary']['total_posts'] == 3
    assert result['summary']['avg_views'] == 160.0
    assert 'Performance Brief' in result['brief_markdown']
    assert 'viral: 1' in result['brief_markdown']
    assert 'hooks: 2' in result['brief_markdown']


def test_generate_brief_returns_insufficient_data_message():
    client = _Client({'account_stats': [], 'content_with_scores': []})
    service = ContentIntelligenceService(client)

    result = asyncio.run(service.generate_brief(user_id='user-1'))

    assert result['ready'] is False
    assert result['reason'] == 'insufficient_data'
    assert 'Not enough analyzed content' in result['brief_markdown']
