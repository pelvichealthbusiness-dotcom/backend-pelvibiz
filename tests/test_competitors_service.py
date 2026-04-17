import asyncio
from unittest.mock import MagicMock

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


# ---------------------------------------------------------------------------
# Helpers shared by Phase-2 unit tests
# ---------------------------------------------------------------------------

def _make_service():
    """Instantiate CompetitorService with both Supabase clients fully mocked."""
    mock_admin = MagicMock()
    mock_svc = MagicMock()
    with (
        MagicMock() as _,  # noqa: F841 — just a placeholder context
    ):
        pass
    # Patch the two module-level factory calls so __init__ never hits real infra
    import app.services.competitors as _mod
    original_admin = _mod.get_supabase_admin
    original_svc = _mod.get_service_client
    _mod.get_supabase_admin = lambda: mock_admin
    _mod.get_service_client = lambda: mock_svc
    try:
        service = CompetitorService()
    finally:
        _mod.get_supabase_admin = original_admin
        _mod.get_service_client = original_svc
    # Store mocks for test-level assertions / further configuration
    service._svc = mock_svc
    service.supabase = mock_admin
    return service, mock_admin, mock_svc


# ---------------------------------------------------------------------------
# Task 2.1 — Failing tests for _compute_hook_gaps
# ---------------------------------------------------------------------------

def test_hook_gaps_include_performance_metrics():
    service, _, _ = _make_service()

    competitor_posts = [
        # "Question" hook — 4 posts
        {'hook_structure': 'Question', 'views': 1000, 'likes': 100, 'engagement_rate': 0.10, 'content_type': 'reel', 'topic': 'fitness'},
        {'hook_structure': 'Question', 'views': 800,  'likes': 80,  'engagement_rate': 0.09, 'content_type': 'reel', 'topic': 'fitness'},
        {'hook_structure': 'Question', 'views': 1200, 'likes': 120, 'engagement_rate': 0.11, 'content_type': 'reel', 'topic': 'health'},
        {'hook_structure': 'Question', 'views': 900,  'likes': 90,  'engagement_rate': 0.08, 'content_type': 'reel', 'topic': 'health'},
        # "Story" hook — 3 posts
        {'hook_structure': 'Story', 'views': 500,  'likes': 50,  'engagement_rate': 0.07, 'content_type': 'post', 'topic': 'nutrition'},
        {'hook_structure': 'Story', 'views': 600,  'likes': 60,  'engagement_rate': 0.06, 'content_type': 'post', 'topic': 'nutrition'},
        {'hook_structure': 'Story', 'views': 700,  'likes': 70,  'engagement_rate': 0.05, 'content_type': 'post', 'topic': 'wellness'},
    ]
    own_posts = [
        # Own has fewer uses of both hooks (gaps exist)
        {'hook_structure': 'Question', 'views': 200, 'likes': 20, 'engagement_rate': 0.05, 'content_type': 'reel', 'topic': 'fitness'},
        {'hook_structure': 'Story',    'views': 100, 'likes': 10, 'engagement_rate': 0.04, 'content_type': 'post', 'topic': 'nutrition'},
    ]

    gaps = service._compute_hook_gaps(own_posts, competitor_posts)

    assert len(gaps) > 0, "Expected at least one HookGap"
    at_least_one = any(
        g.avg_views > 0 and g.avg_likes > 0 and g.performance_score is not None
        for g in gaps
    )
    assert at_least_one, (
        "Expected at least one HookGap with avg_views > 0, avg_likes > 0, and performance_score set"
    )


def test_hook_gaps_skips_score_when_fewer_than_two_posts():
    service, _, _ = _make_service()

    competitor_posts = [
        # "Rare hook" has only 1 post — performance_score must be None
        {'hook_structure': 'Rare hook', 'views': 500, 'likes': 50, 'engagement_rate': 0.05, 'content_type': 'reel', 'topic': 'misc'},
        # Pad with another hook so there's a genuine gap to surface
        {'hook_structure': 'Common hook', 'views': 400, 'likes': 40, 'engagement_rate': 0.04, 'content_type': 'reel', 'topic': 'misc'},
        {'hook_structure': 'Common hook', 'views': 420, 'likes': 42, 'engagement_rate': 0.04, 'content_type': 'reel', 'topic': 'misc'},
        {'hook_structure': 'Common hook', 'views': 410, 'likes': 41, 'engagement_rate': 0.04, 'content_type': 'reel', 'topic': 'misc'},
    ]
    own_posts: list[dict] = []

    gaps = service._compute_hook_gaps(own_posts, competitor_posts)

    rare = next((g for g in gaps if g.hook_structure == 'Rare hook'), None)
    assert rare is not None, "'Rare hook' should appear as a gap"
    assert rare.performance_score is None, (
        "HookGap with fewer than 2 competitor posts must have performance_score=None"
    )


# ---------------------------------------------------------------------------
# Task 2.3 — Failing tests for _compute_white_space
# ---------------------------------------------------------------------------

def _make_supabase_research_rows(rows: list[dict]):
    """Return a mock that mimics: svc.table('research_topics').select(...).eq(...).execute()"""
    result_mock = MagicMock()
    result_mock.data = rows

    query_mock = MagicMock()
    query_mock.select.return_value = query_mock
    query_mock.eq.return_value = query_mock
    query_mock.execute.return_value = result_mock
    return query_mock


def test_white_space_includes_demand_score_and_summary():
    service, _, mock_svc = _make_service()

    trending_rows = [
        {'topic': 'pelvic floor basics',  'source': 'google_trends', 'total_score': 0.92, 'summary': 'High demand for intro pelvic content.'},
        {'topic': 'postpartum recovery',   'source': 'google_trends', 'total_score': 0.85, 'summary': 'Rising searches after birth.'},
        {'topic': 'core rehabilitation',   'source': 'reddit',        'total_score': 0.78, 'summary': 'Community interest in rehab exercises.'},
    ]

    mock_svc.table.return_value = _make_supabase_research_rows(trending_rows)

    own_posts = [
        {'topic': 'yoga', 'hook_structure': 'Question', 'views': 100, 'likes': 10, 'engagement_rate': 0.05, 'content_type': 'reel'},
    ]
    competitor_posts = [
        {'topic': 'pilates', 'hook_structure': 'Story', 'views': 200, 'likes': 20, 'engagement_rate': 0.06, 'content_type': 'reel'},
    ]

    entries = service._compute_white_space('user-1', own_posts, competitor_posts)

    trending = [e for e in entries if e.signal_source == 'trending']
    assert len(trending) > 0, "Expected at least one trending WhiteSpaceEntry"
    for entry in trending:
        matched = next((r for r in trending_rows if r['topic'] == entry.topic), None)
        assert matched is not None
        assert entry.demand_score == matched['total_score'], (
            f"demand_score mismatch for '{entry.topic}': expected {matched['total_score']}, got {entry.demand_score}"
        )
        assert entry.summary == matched['summary'], (
            f"summary mismatch for '{entry.topic}'"
        )
        assert entry.recommendation != "", "recommendation must not be empty for trending entries"


def test_white_space_inferred_entries_have_no_demand_score():
    service, _, mock_svc = _make_service()

    # research_topics returns nothing — force inferred path
    mock_svc.table.return_value = _make_supabase_research_rows([])

    own_posts = [
        {'topic': 'yoga',    'hook_structure': 'Question', 'views': 100, 'likes': 10, 'engagement_rate': 0.05, 'content_type': 'reel'},
        {'topic': 'pilates', 'hook_structure': 'Story',    'views': 200, 'likes': 20, 'engagement_rate': 0.06, 'content_type': 'reel'},
    ]
    competitor_posts = [
        {'topic': 'stretching',  'hook_structure': 'Story',    'views': 300, 'likes': 30, 'engagement_rate': 0.07, 'content_type': 'reel'},
        {'topic': 'meditation',  'hook_structure': 'Question', 'views': 150, 'likes': 15, 'engagement_rate': 0.04, 'content_type': 'reel'},
    ]

    entries = service._compute_white_space('user-1', own_posts, competitor_posts)

    assert len(entries) > 0, "Expected inferred entries when research_topics is empty"
    for entry in entries:
        assert entry.signal_source == 'inferred', (
            f"Expected signal_source='inferred', got '{entry.signal_source}'"
        )
        assert entry.demand_score is None, (
            f"Inferred entries must have demand_score=None, got {entry.demand_score}"
        )
