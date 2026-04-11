from __future__ import annotations

from collections import Counter
from typing import Any

from supabase import Client

from app.dependencies import get_supabase_admin


class IdeationService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()

    async def generate_from_research(
        self,
        *,
        user_id: str,
        niche: str,
        research_topic_id: str | None = None,
        research_run_id: str | None = None,
        topic_limit: int = 3,
        variations_per_topic: int = 5,
    ) -> dict[str, Any]:
        topics = await self._load_topics(user_id=user_id, research_topic_id=research_topic_id, research_run_id=research_run_id, limit=topic_limit)
        if not topics:
            return {
                'ready': False,
                'reason': 'insufficient_research',
                'run_id': None,
                'niche': niche,
                'variations': [],
                'brief_markdown': 'No research topics available to multiply into ideas yet.',
            }

        run = self.supabase.table('ideation_runs').insert({
            'user_id': user_id,
            'research_run_id': research_run_id,
            'source_topic': topics[0]['title'],
            'variations_per_topic': variations_per_topic,
        }).execute()
        run_id = run.data[0]['id'] if run.data else ''

        saved: list[dict[str, Any]] = []
        for topic in topics:
            for variation in self._build_variations(topic, variations_per_topic):
                payload = {
                    'user_id': user_id,
                    'run_id': run_id,
                    'research_topic_id': topic.get('id'),
                    'source_topic': topic['title'],
                    'title': variation['title'],
                    'hook': variation['hook'],
                    'angle': variation['angle'],
                    'content_type': variation['content_type'],
                    'slides_suggestion': variation['slides_suggestion'],
                    'score': variation['score'],
                    'why_it_works': variation['why_it_works'],
                    'raw_data': variation.get('raw_data', {}),
                }
                result = self.supabase.table('idea_variations').upsert(payload, on_conflict='user_id,source_topic,angle').execute()
                saved.append(result.data[0] if result.data else payload)

        brief_markdown = self._build_brief(niche, topics, saved)
        return {
            'ready': True,
            'reason': None,
            'run_id': run_id,
            'niche': niche,
            'variations': saved,
            'brief_markdown': brief_markdown,
        }

    async def list_latest_variations(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        result = (
            self.supabase.table('idea_variations')
            .select('*')
            .eq('user_id', user_id)
            .order('score', desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def _load_topics(self, *, user_id: str, research_topic_id: str | None, research_run_id: str | None, limit: int) -> list[dict[str, Any]]:
        query = self.supabase.table('research_topics').select('*').eq('user_id', user_id).order('total_score', desc=True)
        if research_topic_id:
            query = query.eq('id', research_topic_id)
        if research_run_id:
            query = query.eq('run_id', research_run_id)
        result = query.limit(limit).execute()
        return result.data or []

    def _build_variations(self, topic: dict[str, Any], variations_per_topic: int) -> list[dict[str, Any]]:
        title = topic.get('title', topic.get('topic', 'topic'))
        base_topic = topic.get('topic', title)
        variation_specs = [
            ('Contrarian', 'contrarian', 'myth-busting', 'This flips the common assumption and creates immediate tension.'),
            ('How-To', 'how-to', 'tutorial', 'Clear steps make this easy to execute and save.'),
            ('Demo', 'demo', 'demo', 'Shows the thing working, which reduces skepticism fast.'),
            ('Checklist', 'checklist', 'educational', 'A list format makes the idea scannable and practical.'),
            ('Hot Take', 'hot-take', 'opinion', 'The opinion angle is fast to hook and easy to debate.'),
        ]
        variations: list[dict[str, Any]] = []
        for idx, (angle, slug, content_type, why) in enumerate(variation_specs[:variations_per_topic]):
            hook = self._build_hook(base_topic, angle)
            variations.append({
                'title': f'{title} - {angle}',
                'hook': hook,
                'angle': angle,
                'content_type': content_type,
                'slides_suggestion': 5 if content_type != 'demo' else 4,
                'score': round(0.92 - idx * 0.05, 2),
                'why_it_works': why,
                'raw_data': {'source_topic': base_topic, 'variation_type': slug},
            })
        return variations

    def _build_hook(self, topic: str, angle: str) -> str:
        if angle == 'contrarian':
            return f"Stop doing {topic} the usual way"
        if angle == 'how-to':
            return f"How to win with {topic} in 3 steps"
        if angle == 'demo':
            return f"Watch me turn {topic} into something useful"
        if angle == 'checklist':
            return f"5 things to check before posting {topic}"
        return f"My honest take on {topic}"

    def _build_brief(self, niche: str, topics: list[dict[str, Any]], variations: list[dict[str, Any]]) -> str:
        counts = Counter(v.get('content_type') for v in variations if v.get('content_type'))
        lines = [
            '# Ideation Brief',
            '',
            f'- Niche: {niche}',
            f'- Topics used: {len(topics)}',
            f'- Variations generated: {len(variations)}',
            '',
            '## Content Types',
        ]
        for label, count in counts.most_common():
            lines.append(f'- {label}: {count}')
        lines.append('')
        lines.append('## Example Ideas')
        for item in variations[:10]:
            lines.append(f'- {item["title"]}: {item["hook"]}')
        return '\n'.join(lines)
