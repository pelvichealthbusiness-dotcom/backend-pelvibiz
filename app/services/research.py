from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from supabase import Client

from app.dependencies import get_supabase_admin
from app.services.content_intelligence import ContentIntelligenceService


def _normalize_topic(text: str) -> str:
    return re.sub(r'\s+', ' ', text.strip().lower())


class ResearchService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()
        self.content_service = ContentIntelligenceService(self.supabase)

    async def run_research(
        self,
        *,
        user_id: str,
        niche: str,
        sources: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        sources = sources or ['reddit', 'github', 'news']
        collected: list[dict[str, Any]] = []

        if 'reddit' in sources:
            collected.extend(await self._fetch_reddit(niche))
        if 'github' in sources:
            collected.extend(await self._fetch_github(niche))
        if 'news' in sources:
            collected.extend(await self._fetch_news(niche))
        if 'x' in sources:
            collected.extend(await self._fetch_x(niche))

        deduped = self._score_and_dedupe(collected, niche)
        top_topics = deduped[:limit]

        if not top_topics:
            return {
                'ready': False,
                'reason': 'insufficient_signal',
                'run_id': None,
                'niche': niche,
                'topics': [],
                'brief_markdown': 'Not enough trend signal to generate topics yet.',
            }

        run = self.supabase.table('research_runs').insert({
            'user_id': user_id,
            'niche': niche,
            'sources': sources,
        }).execute()
        run_id = run.data[0]['id'] if run.data else ''

        saved_topics: list[dict[str, Any]] = []
        for topic in top_topics:
            payload = {
                'user_id': user_id,
                'run_id': run_id,
                'source': topic['source'],
                'topic': topic['topic'],
                'title': topic['title'],
                'summary': topic.get('summary', ''),
                'tam_score': topic['tam_score'],
                'demo_score': topic['demo_score'],
                'hook_score': topic['hook_score'],
                'total_score': topic['total_score'],
                'raw_data': topic.get('raw_data', {}),
            }
            result = self.supabase.table('research_topics').upsert(payload, on_conflict='user_id,source,title').execute()
            saved_topics.append(result.data[0] if result.data else payload)

        studio_context = await self.content_service.get_optional_studio_context(user_id=user_id)
        brief_markdown = self._build_brief(niche, saved_topics, sources, studio_context)
        return {
            'ready': True,
            'reason': None,
            'run_id': run_id,
            'niche': niche,
            'topics': saved_topics,
            'brief_markdown': brief_markdown,
        }

    async def list_latest_topics(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        result = (
            self.supabase.table('research_topics')
            .select('*')
            .eq('user_id', user_id)
            .order('total_score', desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def _fetch_reddit(self, niche: str) -> list[dict[str, Any]]:
        query = niche.replace(' ', '%20')
        url = f'https://www.reddit.com/search.json?q={query}&sort=hot&t=day&limit=10'
        async with httpx.AsyncClient(timeout=20, headers={'User-Agent': 'PelviBizResearch/1.0'}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json().get('data', {}).get('children', [])
        topics: list[dict[str, Any]] = []
        for item in data:
            post = item.get('data', {})
            title = post.get('title')
            if not title:
                continue
            topics.append({
                'source': 'reddit',
                'topic': _normalize_topic(title),
                'title': title,
                'summary': post.get('subreddit_name_prefixed', ''),
                'raw_data': post,
            })
        return topics

    async def _fetch_github(self, niche: str) -> list[dict[str, Any]]:
        url = 'https://github.com/trending?since=daily'
        async with httpx.AsyncClient(timeout=20, headers={'User-Agent': 'PelviBizResearch/1.0'}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        matches = re.findall(r'href="/([^/]+/[^/]+)"', html)
        topics: list[dict[str, Any]] = []
        for repo in matches[:10]:
            title = repo.replace('/', ' / ')
            topics.append({
                'source': 'github',
                'topic': _normalize_topic(repo.split('/')[-1].replace('-', ' ')),
                'title': title,
                'summary': f'GitHub trending repo: {repo}',
                'raw_data': {'repo': repo},
            })
        return topics

    async def _fetch_news(self, niche: str) -> list[dict[str, Any]]:
        query = niche.replace(' ', '+')
        url = f'https://news.google.com/rss/search?q={query}'
        async with httpx.AsyncClient(timeout=20, headers={'User-Agent': 'PelviBizResearch/1.0'}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        topics: list[dict[str, Any]] = []
        for item in root.findall('.//item')[:10]:
            title_el = item.find('title')
            if title_el is None or not title_el.text:
                continue
            title = unescape(title_el.text)
            topics.append({
                'source': 'news',
                'topic': _normalize_topic(title),
                'title': title,
                'summary': 'Google News result',
                'raw_data': {'title': title},
            })
        return topics

    async def _fetch_x(self, niche: str) -> list[dict[str, Any]]:
        return []

    def _score_and_dedupe(self, items: list[dict[str, Any]], niche: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        scored: list[dict[str, Any]] = []
        for item in items:
            title = item.get('title', '')
            topic = item.get('topic') or _normalize_topic(title)
            key = f"{item.get('source')}:{topic}"
            if key in seen:
                continue
            seen.add(key)
            scored.append({
                **item,
                'topic': topic,
                'tam_score': self._score_tam(title, niche),
                'demo_score': self._score_demo(title),
                'hook_score': self._score_hook(title),
            })

        for item in scored:
            item['total_score'] = round((item['tam_score'] + item['demo_score'] + item['hook_score']) / 3, 2)

        scored.sort(key=lambda row: row['total_score'], reverse=True)
        return scored

    def _score_tam(self, title: str, niche: str) -> float:
        title_lower = title.lower()
        niche_words = len([w for w in _normalize_topic(niche).split(' ') if w])
        base = 0.4 + min(niche_words * 0.05, 0.2)
        boost = 0.2 if any(word in title_lower for word in ['ai', 'tool', 'how to', 'fix', 'build', 'learn']) else 0
        return round(min(base + boost, 1.0), 2)

    def _score_demo(self, title: str) -> float:
        title_lower = title.lower()
        score = 0.3
        if any(token in title_lower for token in ['how to', 'build', 'fix', 'workflow', 'guide', 'tutorial']):
            score += 0.5
        if any(token in title_lower for token in ['demo', 'screenshot', 'video', 'tool']):
            score += 0.2
        return round(min(score, 1.0), 2)

    def _score_hook(self, title: str) -> float:
        title_lower = title.lower()
        score = 0.3
        if any(token in title_lower for token in ['why', 'stop', 'vs', 'secret', 'insane', 'new']):
            score += 0.5
        if '?' in title:
            score += 0.1
        return round(min(score, 1.0), 2)

    def _build_brief(self, niche: str, topics: list[dict[str, Any]], sources: list[str], studio_context: dict[str, Any] | None = None) -> str:
        top = topics[0]
        lines = [
            '# Daily Research Brief',
            '',
            f'- Niche: {niche}',
            f'- Sources: {", ".join(sources)}',
            f'- Top topic: {top["title"]}',
        ]
        if studio_context:
            style_brief = studio_context.get('content_style_brief') or ''
            top_topics = studio_context.get('top_topics') or []
            top_hooks = studio_context.get('top_hooks') or []
            top_content_types = studio_context.get('top_content_types') or []
            if style_brief:
                lines.extend(['', '## Content Studio Context', style_brief])
            if top_topics or top_hooks or top_content_types:
                lines.extend(['', '## Studio Signals'])
                if top_topics:
                    lines.append(f"- Top topics: {', '.join(top_topics)}")
                if top_hooks:
                    lines.append(f"- Hook structures: {', '.join(top_hooks)}")
                if top_content_types:
                    lines.append(f"- Content types: {', '.join(top_content_types)}")
        lines.extend(['', '## Top Topics'])
        for topic in topics[:10]:
            lines.append(f'- {topic["title"]} ({topic["source"]})')
        return '\n'.join(lines)
