from __future__ import annotations

import asyncio

from app.services.social_intelligence import SocialIntelligenceService


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.payload = None
        self._single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def insert(self, payload):
        self.payload = payload
        self.client.calls.append((self.table_name, payload))
        return self

    def execute(self):
        counter = self.client.counters.get(self.table_name, 0) + 1
        self.client.counters[self.table_name] = counter
        row_id = f"{self.table_name}-{counter}"
        if self.payload is None:
            data = self.client.datasets.get(self.table_name, [])
            if self._single:
                return _Result(data[0] if data else None)
            return _Result(data)
        return _Result([{"id": row_id, **self.payload}])


class _Client:
    def __init__(self, datasets=None):
        self.calls = []
        self.counters = {}
        self.datasets = datasets or {}

    def table(self, table_name):
        return _Query(self, table_name)


class _Service(SocialIntelligenceService):
    async def _collect_platform(self, topic: str, platform: str, limit: int, language: str):
        return [
            {
                "platform": platform,
                "source_kind": "google_search",
                "title": f"{platform} angle for {topic}",
                "url": f"https://example.com/{platform}/{topic}",
                "author": platform,
                "summary": f"{topic} summary",
                "published_at": None,
                "rank": 1,
                "query": topic,
                "viral_score": 0.9,
                "engagement": {"views": 1200},
                "raw_data": {},
            }
        ]

    async def _collect_google_news(self, topic: str, limit: int, language: str):
        return [
            {
                "platform": "google",
                "source_kind": "google_news",
                "title": f"News about {topic}",
                "url": f"https://news.example.com/{topic}",
                "author": "news",
                "summary": "Trending now",
                "published_at": None,
                "rank": 1,
                "query": topic,
                "viral_score": 0.7,
                "engagement": {"views": 500},
                "raw_data": {},
            }
        ]


def test_social_research_saves_runs_and_items():
    service = _Service(_Client())

    result = asyncio.run(service.run_research(user_id="user-1", topic="embarazadas", platforms=["instagram", "google"], limit=3))

    assert result["ready"] is True
    assert result["run_id"] == "social_research_runs-1"
    assert len(result["items"]) == 3
    assert service.supabase.calls[0][0] == "social_research_runs"
    assert service.supabase.calls[1][0] == "social_research_items"


def test_social_ideation_falls_back_to_templates_when_llm_unavailable():
    client = _Client({
        "social_research_items": [
            {"id": "item-1", "title": "Pregnancy safety tips", "summary": "high engagement", "platform": "instagram", "viral_score": 0.9, "created_at": "2026-04-15T00:00:00Z"},
        ]
    })
    service = _Service(client)

    async def load_items(**_kwargs):
        return client.datasets["social_research_items"]

    service._load_research_items = load_items  # type: ignore[method-assign]

    async def load_brand(_user_id):
        return {"brand_voice": "warm", "cta": "Book now"}

    service._load_brand_profile = load_brand  # type: ignore[method-assign]

    async def llm_fail(**_kwargs):
        raise RuntimeError("No LLM in test environment")

    service._generate_ideas_llm = llm_fail  # type: ignore[method-assign]

    result = asyncio.run(service.generate_ideas(user_id="user-1", topic="embarazadas", variations=6))

    assert result["ready"] is True
    assert len(result["variations"]) == 6
    # Fallback titles keep the old "topic - Label" format
    assert any("embarazadas" in v["title"] for v in result["variations"])
    assert client.calls[0][0] == "social_idea_runs"
    assert client.calls[1][0] == "social_idea_variations"


def test_social_ideation_uses_llm_ideas_when_available():
    client = _Client({
        "social_research_items": [
            {"id": "item-1", "title": "Pelvic floor exercises going viral", "summary": "trending", "platform": "instagram", "viral_score": 0.95, "created_at": "2026-04-15T00:00:00Z"},
        ]
    })
    service = _Service(client)

    async def load_items(**_kwargs):
        return client.datasets["social_research_items"]

    service._load_research_items = load_items  # type: ignore[method-assign]

    async def load_brand(_user_id):
        return {
            "brand_name": "PelviBiz",
            "niche": "pelvic health",
            "target_audience": "women postpartum",
            "brand_voice": "warm and educational",
        }

    service._load_brand_profile = load_brand  # type: ignore[method-assign]

    llm_ideas = [
        {
            "title": "The pelvic floor mistake every new mom makes after birth",
            "hook": "Nobody tells you this in the hospital discharge paper",
            "angle": "contrarian",
            "content_type": "reel",
            "score": 0.93,
            "why_it_works": "Addresses a fear-based pain point specific to postpartum women",
            "best_hooks": [
                "Nobody tells you this in the hospital discharge paper",
                "What your OB forgot to mention about recovery",
                "The one thing postpartum docs skip",
            ],
        },
        {
            "title": "5 signs your core still isn't healed 6 months postpartum",
            "hook": "If any of these feel familiar, keep watching",
            "angle": "checklist",
            "content_type": "carousel",
            "score": 0.89,
            "why_it_works": "Checklist format drives saves; specific timeline creates urgency",
            "best_hooks": [
                "If any of these feel familiar, keep watching",
                "Still leaking at 6 months? Here's why",
                "Your body is telling you something — learn what",
            ],
        },
    ]

    async def llm_succeed(**_kwargs):
        return llm_ideas

    service._generate_ideas_llm = llm_succeed  # type: ignore[method-assign]

    result = asyncio.run(service.generate_ideas(user_id="user-1", variations=2))

    assert result["ready"] is True
    assert len(result["variations"]) == 2
    assert result["variations"][0]["title"] == "The pelvic floor mistake every new mom makes after birth"
    assert result["variations"][0]["raw_data"]["llm_generated"] is True
    assert result["variations"][1]["title"] == "5 signs your core still isn't healed 6 months postpartum"
    assert result["variations"][1]["slides_suggestion"] == 6  # carousel → 6


def test_social_script_builds_hook_pack_and_script():
    client = _Client({
        "social_idea_variations": [
            {
                "id": "idea-1",
                "source_topic": "embarazadas",
                "hook": "What nobody tells you about pregnancy",
                "content_type": "carousel",
                "created_at": "2026-04-15T00:00:00Z",
            }
        ],
        "social_research_items": [
            {"id": "item-1", "title": "Pregnancy safety tips", "summary": "high engagement", "platform": "instagram", "viral_score": 0.9, "created_at": "2026-04-15T00:00:00Z"},
        ],
    })
    service = _Service(client)

    async def load_items(**_kwargs):
        return client.datasets["social_research_items"]

    service._load_research_items = load_items  # type: ignore[method-assign]

    async def load_brand(_user_id):
        return {"brand_voice": "warm", "cta": "Book now"}

    service._load_brand_profile = load_brand  # type: ignore[method-assign]

    result = asyncio.run(service.generate_script(user_id="user-1", idea_variation_id="idea-1", selected_hook="Special hook"))

    assert result["ready"] is True
    assert result["selected_hook"] == "Special hook"
    assert len(result["hook_pack"]) == 5
    assert client.calls[0][0] == "social_script_runs"
    assert client.calls[1][0] == "social_scripts"
