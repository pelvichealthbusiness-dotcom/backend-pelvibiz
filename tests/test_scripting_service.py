import asyncio

from app.services.scripting import ScriptingService


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
        datasets = self.client.datasets
        if self.table_name == 'idea_variations' and self.filters.get('id'):
            return _Result(datasets.get('idea_variation'))
        if self.table_name == 'research_topics' and self.filters.get('id'):
            return _Result(datasets.get('research_topic'))
        if self.table_name == 'scripting_runs':
            return _Result([{'id': 'run-1', **(self.payload or {})}])
        if self.table_name == 'hook_packs':
            return _Result([{'id': f'hook-{len(self.client.calls)}', **(self.payload or {})}])
        if self.table_name == 'content_scripts':
            return _Result([{'id': 'script-1', **(self.payload or {})}])
        return _Result([])


class _Client:
    def __init__(self, datasets):
        self.datasets = datasets
        self.calls = []

    def table(self, table_name):
        return _Query(self, table_name)


def test_generate_hook_pack_creates_six_hooks():
    client = _Client({'idea_variation': {'id': 'idea-1', 'source_topic': 'hooks', 'hook': 'Stop doing hooks the usual way', 'content_type': 'tutorial'}})
    service = ScriptingService(client)

    result = asyncio.run(service.generate_hook_pack(user_id='user-1', idea_variation_id='idea-1', count=6))

    assert result['ready'] is True
    assert result['run_id'] == 'run-1'
    assert len(result['hooks']) == 6
    assert client.calls[0][0] == 'scripting_runs'
    assert client.calls[1][0] == 'hook_packs'


def test_generate_script_uses_selected_hook_and_saves():
    client = _Client({'idea_variation': {'id': 'idea-1', 'source_topic': 'hooks', 'hook': 'Stop doing hooks the usual way', 'content_type': 'tutorial'}})
    service = ScriptingService(client)

    result = asyncio.run(service.generate_script(user_id='user-1', idea_variation_id='idea-1', selected_hook='Stop doing hooks the usual way'))

    assert result['ready'] is True
    assert result['run_id'] == 'run-1'
    assert result['selected_hook'] == 'Stop doing hooks the usual way'
    assert 'script_body' in result
    assert client.calls[0][0] == 'scripting_runs'
    assert client.calls[1][0] == 'content_scripts'
