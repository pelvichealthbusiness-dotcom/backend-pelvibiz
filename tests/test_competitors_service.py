import asyncio

from app.services.competitors import CompetitorService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def upsert(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        datasets = self.client.datasets
        if self.table_name == 'content_accounts' and self.filters.get('handle'):
            return _Result(datasets.get('competitor_account'))
        if self.table_name == 'content_accounts' and self.filters.get('account_type') == 'competitor':
            return _Result(datasets.get('competitors', []))
        if self.table_name == 'content_with_scores':
            return _Result(datasets.get('competitor_feed', []))
        return _Result([])


class _Client:
    def __init__(self, datasets):
        self.datasets = datasets

    def table(self, table_name):
        return _Query(self, table_name)


def test_add_competitor_uses_content_accounts():
    datasets = {}
    client = _Client(datasets)
    service = CompetitorService(client)

    async def run():
        return await service.add_competitor(user_id='user-1', handle='rival1', display_name='Rival One')

    result = asyncio.run(run())

    assert result['handle'] == 'rival1'
    assert result['account_type'] == 'competitor'


def test_compare_competitor_reports_gaps():
    datasets = {
        'competitor_account': {'id': 'acc-1', 'handle': 'rival1', 'account_type': 'competitor'},
        'competitor_feed': [
            {'views': 250, 'topic': 'hooks', 'hook_structure': 'Contrarian', 'content_type': 'tutorial'},
            {'views': 120, 'topic': 'hooks', 'hook_structure': 'Educational', 'content_type': 'tutorial'},
            {'views': 90, 'topic': 'ai tools', 'hook_structure': 'Contrarian', 'content_type': 'demo'},
        ],
    }
    client = _Client(datasets)
    service = CompetitorService(client)

    async def run():
        return await service.compare_user_vs_competitor(user_id='user-1', handle='rival1')

    result = asyncio.run(run())

    assert result['competitor_summary']['total_posts'] == 3
    assert isinstance(result['shared_topics'], list)
    assert isinstance(result['gaps'], list)
