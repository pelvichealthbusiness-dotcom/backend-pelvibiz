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

    def insert(self, payload):
        self.payload = payload
        self.client.inserts.append((self.table_name, payload))
        return self

    def execute(self):
        return _Result([self.payload] if self.payload else [])


class _SupabaseClient:
    def __init__(self):
        self.inserts = []

    def table(self, table_name):
        return _Query(self, table_name)


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


class _FakeAnalyzer:
    def analyze(self, posts, profile_data):
        return {
            'caption_avg_length': 12,
            'hook_types': {'question': 1.0},
            'hook_second_person_rate': 0.8,
            'cta_types': {'follow': 1.0},
            'emoji_frequency': 0.0,
            'hashtag_avg_count': 0,
            'content_categories': {'educational': 1.0},
            'top_keywords': [{'word': 'hook'}],
        }


class _FakeContentService:
    def __init__(self):
        self.calls = []

    async def store_scrape(self, **kwargs):
        self.calls.append(kwargs)
        return {'account': {'id': 'acc-1'}, 'posts': [{'id': 'content-1'}]}


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

    assert result.scrape_id
    assert result.username == 'creator1'
    assert fake_content_service.calls[0]['handle'] == 'creator1'
    assert fake_content_service.calls[0]['posts'][0]['id'] == 'post-1'
    assert fake_content_service.calls[0]['posts'][0]['media_type'] == 'reel'
    assert supabase.inserts == []
