from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from supabase import Client

from app.dependencies import get_supabase_admin
from app.services.content_intelligence import ContentIntelligenceService
from app.services.brand import BrandService
from app.core.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)


class ScriptingService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()
        self.brand_service = BrandService(self.supabase)
        self.content_service = ContentIntelligenceService(self.supabase)

    def _row(self, data: Any) -> dict[str, Any]:
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    async def generate_hook_pack(
        self,
        *,
        user_id: str,
        topic: str | None = None,
        research_topic_id: str | None = None,
        idea_variation_id: str | None = None,
        count: int = 6,
        competitor_handle: str | None = None,
    ) -> dict[str, Any]:
        source = await self._resolve_source(user_id=user_id, topic=topic, research_topic_id=research_topic_id, idea_variation_id=idea_variation_id)
        run = self.supabase.table('scripting_runs').insert({
            'user_id': user_id,
            'source_type': source['source_type'],
            'source_id': source.get('source_id'),
            'source_topic': source['source_topic'],
            'hook_count': count,
        }).execute()
        run_id = run.data[0]['id'] if run.data else ''

        competitor_gaps = (
            self.content_service.get_competitor_gaps(user_id, competitor_handle)
            if competitor_handle else {}
        )
        try:
            hooks = await self._build_hooks_llm(
                source['source_topic'],
                source.get('hook_seed', ''),
                source.get('content_type', 'educational'),
                count,
                competitor_gaps,
            )
        except Exception as exc:
            logger.warning('[Scripting] Gemini hook generation failed, falling back to templates: %s', exc)
            hooks = self._build_hooks(source['source_topic'], source.get('hook_seed', ''), source.get('content_type', 'educational'), count)
        saved: list[dict[str, Any]] = []
        for hook in hooks:
            payload = {
                'user_id': user_id,
                'run_id': run_id,
                'source_id': source.get('source_id'),
                'source_topic': source['source_topic'],
                'hook_text': hook['hook_text'],
                'hook_framework': hook['hook_framework'],
                'hook_type': hook['hook_type'],
                'content_type': hook['content_type'],
                'score': hook['score'],
                'why_it_works': hook['why_it_works'],
                'raw_data': hook.get('raw_data', {}),
            }
            result = self.supabase.table('hook_packs').upsert(payload, on_conflict='user_id,source_topic,hook_framework').execute()
            saved.append(result.data[0] if result.data else payload)

        brief_markdown = self._build_hook_brief(source['source_topic'], saved)
        competitor_block = self.content_service.get_competitor_context_block(user_id, competitor_handle)
        if competitor_block:
            brief_markdown += '\n\n' + competitor_block
        return {
            'ready': True,
            'run_id': run_id,
            'source_topic': source['source_topic'],
            'hooks': saved,
            'brief_markdown': brief_markdown,
            'used_competitor_handle': competitor_handle if competitor_block else None,
        }

    async def generate_script(
        self,
        *,
        user_id: str,
        topic: str | None = None,
        research_topic_id: str | None = None,
        idea_variation_id: str | None = None,
        selected_hook: str | None = None,
        competitor_handle: str | None = None,
    ) -> dict[str, Any]:
        source = await self._resolve_source(user_id=user_id, topic=topic, research_topic_id=research_topic_id, idea_variation_id=idea_variation_id)
        if selected_hook:
            hook = selected_hook
        else:
            try:
                fallback_hooks = await self._build_hooks_llm(source['source_topic'], source.get('hook_seed', ''), source.get('content_type', 'educational'), 1, {})
                hook = fallback_hooks[0]['hook_text']
            except Exception:
                hook = self._build_hooks(source['source_topic'], source.get('hook_seed', ''), source.get('content_type', 'educational'), 1)[0]['hook_text']

        run = self.supabase.table('scripting_runs').insert({
            'user_id': user_id,
            'source_type': source['source_type'],
            'source_id': source.get('source_id'),
            'source_topic': source['source_topic'],
            'hook_count': 1,
        }).execute()
        run_id = run.data[0]['id'] if run.data else ''

        try:
            script = await self._build_script_llm(source['source_topic'], hook, source.get('hook_seed', ''), source.get('content_type', 'educational'))
        except Exception as exc:
            logger.warning('[Scripting] Gemini script generation failed, falling back to template: %s', exc)
            script = self._build_script(source['source_topic'], hook, source.get('hook_seed', ''), source.get('content_type', 'educational'))
        payload = {
            'user_id': user_id,
            'run_id': run_id,
            'source_id': source.get('source_id'),
            'source_topic': source['source_topic'],
            'selected_hook': hook,
            'hook_framework': script['hook_framework'],
            'hook_type': script['hook_type'],
            'content_type': script['content_type'],
            'hook': script['hook'],
            'script_body': script['script_body'],
            'filming_card': script['filming_card'],
            'caption': script['caption'],
            'cta': script['cta'],
            'recording_instructions': script['recording_instructions'],
            'raw_data': script.get('raw_data', {}),
        }
        result = self.supabase.table('content_scripts').insert(payload).execute()
        saved = result.data[0] if result.data else payload

        competitor_block = self.content_service.get_competitor_context_block(user_id, competitor_handle)
        used_competitor_handle = competitor_handle if competitor_block else None
        return {
            'ready': True,
            'run_id': run_id,
            'source_topic': source['source_topic'],
            'used_competitor_handle': used_competitor_handle,
            **saved,
        }

    async def list_latest_hooks(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        result = (
            self.supabase.table('hook_packs')
            .select('*')
            .eq('user_id', user_id)
            .order('score', desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def list_latest_scripts(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        result = (
            self.supabase.table('content_scripts')
            .select('*')
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def _resolve_source(
        self,
        *,
        user_id: str,
        topic: str | None,
        research_topic_id: str | None,
        idea_variation_id: str | None,
    ) -> dict[str, Any]:
        source: dict[str, Any] | None = None
        if idea_variation_id:
            result = self.supabase.table('idea_variations').select('*').eq('user_id', user_id).eq('id', idea_variation_id).maybe_single().execute()
            row = self._row(result.data)
            if row:
                source = {'source_type': 'idea_variation', 'source_id': row.get('id'), 'source_topic': row.get('source_topic') or row.get('title') or 'topic', 'hook_seed': row.get('hook', ''), 'content_type': row.get('content_type', 'educational')}
                studio_context = await self.content_service.get_optional_studio_context(user_id=user_id)
                return self._apply_studio_context(source, studio_context)

        if source is None and research_topic_id:
            result = self.supabase.table('research_topics').select('*').eq('user_id', user_id).eq('id', research_topic_id).maybe_single().execute()
            row = self._row(result.data)
            if row:
                source = {'source_type': 'research_topic', 'source_id': row.get('id'), 'source_topic': row.get('title') or row.get('topic') or 'topic', 'hook_seed': row.get('title', ''), 'content_type': 'educational'}
                studio_context = await self.content_service.get_optional_studio_context(user_id=user_id)
                return self._apply_studio_context(source, studio_context)

        if source is None:
            source = {'source_type': 'manual', 'source_id': None, 'source_topic': topic or 'topic', 'hook_seed': topic or '', 'content_type': 'educational'}

        studio_context = await self.content_service.get_optional_studio_context(user_id=user_id)
        return self._apply_studio_context(source, studio_context)

    def _apply_studio_context(self, source: dict[str, Any], studio_context: dict[str, Any] | None) -> dict[str, Any]:
        if not studio_context:
            return source

        context_parts: list[str] = [source.get('hook_seed', '')]
        style_brief = studio_context.get('content_style_brief') or ''
        if style_brief:
            context_parts.append(style_brief[:180])
        top_topics = studio_context.get('top_topics') or []
        if top_topics:
            context_parts.append(f"Top topics: {', '.join(top_topics[:3])}")
        top_hooks = studio_context.get('top_hooks') or []
        if top_hooks:
            context_parts.append(f"Hook structures: {', '.join(top_hooks[:3])}")
        top_content_types = studio_context.get('top_content_types') or []
        if top_content_types:
            context_parts.append(f"Content types: {', '.join(top_content_types[:3])}")

        source['studio_context'] = studio_context
        source['hook_seed'] = '\n'.join(part for part in context_parts if part)
        return source

    async def _build_hooks_llm(
        self,
        topic: str,
        seed: str,
        content_type: str,
        count: int,
        competitor_gaps: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Generate hooks using Gemini 2.5-flash. Raises on failure so caller can fallback."""
        hook_gap_lines = ''
        if competitor_gaps.get('hook_gaps'):
            hook_gap_lines = '\nCompetitor hook gaps (angles your competitor uses that you can hijack or counter):\n' + '\n'.join(f'- {h}' for h in competitor_gaps['hook_gaps'][:5])

        topic_gap_lines = ''
        if competitor_gaps.get('topic_gaps'):
            topic_gap_lines = '\nCompetitor topic gaps (subjects they own, find a fresh angle):\n' + '\n'.join(f'- {t}' for t in competitor_gaps['topic_gaps'][:3])

        prompt = f"""You are an expert social media content strategist specializing in short-form video hooks for health and wellness creators.

Generate {count} distinct, high-converting video hooks for the following topic.

Topic: {topic}
Content type: {content_type}
Seed context: {seed[:300] if seed else 'none'}{hook_gap_lines}{topic_gap_lines}

Rules:
- Each hook must be a single punchy sentence (max 15 words) a creator would say on camera
- Vary the frameworks: secret reveal, contrarian, question, experiment, comparison, educational
- Make hooks specific to the topic — no generic filler
- Score each hook from 0.0 to 1.0 based on virality potential

Respond ONLY with a valid JSON array. No markdown, no explanation. Schema:
[
  {{
    "hook_text": "string",
    "hook_framework": "string (e.g. Secret Reveal, Contrarian Snapback, Question Hook)",
    "hook_type": "string (e.g. secret_reveal, contrarian, question)",
    "why_it_works": "string (one sentence)",
    "score": float
  }}
]"""

        client = get_gemini_client()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json'},
        )
        raw = response.text.strip()
        hooks = json.loads(raw)
        if not isinstance(hooks, list) or not hooks:
            raise ValueError(f'Gemini returned unexpected structure: {raw[:200]}')

        result: list[dict[str, Any]] = []
        for h in hooks[:count]:
            result.append({
                'hook_framework': str(h.get('hook_framework', 'Custom')),
                'hook_type': str(h.get('hook_type', 'custom')),
                'content_type': content_type,
                'score': max(0.0, min(1.0, float(h.get('score', 0.75)))),
                'hook_text': str(h.get('hook_text', '')),
                'why_it_works': str(h.get('why_it_works', '')),
                'raw_data': {'source': 'gemini', 'topic': topic},
            })
        return result

    async def _build_script_llm(
        self,
        topic: str,
        hook: str,
        seed: str,
        content_type: str,
    ) -> dict[str, Any]:
        """Generate a full script using Gemini 2.5-flash. Raises on failure so caller can fallback."""
        prompt = f"""You are an expert short-form video scriptwriter for health and wellness creators.

Write a complete, ready-to-film video script using the hook provided.

Topic: {topic}
Hook (opening line): {hook}
Content type: {content_type}
Context: {seed[:300] if seed else 'none'}

Structure the script as 4 beats:
1. Hook beat — the opening hook line + 1 follow-up sentence to hold attention
2. Story/Problem beat — 2-3 sentences establishing the problem or story
3. Value beat — the core insight, tip, or transformation (2-4 sentences)
4. CTA beat — a specific, direct call to action (1 sentence)

Also provide:
- filming_card: a compact director's note (what to show on camera, setting, energy)
- caption: Instagram caption with hook, value, and hashtags
- cta: the standalone CTA sentence

Respond ONLY with a valid JSON object. No markdown, no explanation. Schema:
{{
  "hook_beat": "string",
  "story_beat": "string",
  "value_beat": "string",
  "cta_beat": "string",
  "script_body": "string (full concatenated script, numbered beats)",
  "filming_card": "string",
  "caption": "string",
  "cta": "string",
  "hook_framework": "string",
  "hook_type": "string",
  "recording_instructions": "string"
}}"""

        client = get_gemini_client()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json'},
        )
        raw = response.text.strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f'Gemini returned unexpected structure: {raw[:200]}')

        return {
            'hook_framework': str(data.get('hook_framework', 'Hook-Story-Value-CTA')),
            'hook_type': str(data.get('hook_type', 'Scripted Hook')),
            'content_type': content_type,
            'hook': hook,
            'hook_beat': str(data.get('hook_beat', '')),
            'story_beat': str(data.get('story_beat', '')),
            'value_beat': str(data.get('value_beat', '')),
            'cta_beat': str(data.get('cta_beat', '')),
            'script_body': str(data.get('script_body', '')),
            'filming_card': str(data.get('filming_card', '')),
            'caption': str(data.get('caption', '')),
            'cta': str(data.get('cta', '')),
            'recording_instructions': str(data.get('recording_instructions', '')),
            'raw_data': {'source': 'gemini', 'topic': topic},
        }

    def _build_hooks(self, topic: str, seed: str, content_type: str, count: int) -> list[dict[str, Any]]:
        frameworks = [
            ('Secret Reveal', 'secret_reveal', 'Secret reveal', f"The hidden truth about {topic}"),
            ('Contrarian Snapback', 'contrarian', 'Contrarian', f"Stop doing {topic} like everyone else"),
            ('Educational Reset', 'educational', 'Educational', f"How to actually win with {topic}"),
            ('Comparison', 'comparison', 'Comparison', f"{topic} before vs after"),
            ('Question Hook', 'question', 'Question', f"Why does {topic} fail for so many people?"),
            ('Experiment', 'experiment', 'Experiment', f"I tested {topic} so you do not have to"),
        ]
        hooks: list[dict[str, Any]] = []
        for idx, (label, slug, hook_type, base) in enumerate(frameworks[:count]):
            hook_text = base if not seed else f"{base}: {seed[:40]}" if idx == 0 else base
            hooks.append({
                'hook_framework': label,
                'hook_type': hook_type,
                'content_type': content_type,
                'score': round(0.94 - idx * 0.06, 2),
                'hook_text': hook_text,
                'why_it_works': self._why_it_works(slug),
                'raw_data': {'framework_slug': slug, 'seed': seed},
            })
        return hooks

    def _why_it_works(self, slug: str) -> str:
        reasons = {
            'secret_reveal': 'Creates curiosity by promising hidden information.',
            'contrarian': 'Interrupts expectations and creates tension.',
            'educational': 'Signals immediate utility and broad value.',
            'comparison': 'Frames the payoff as a direct contrast.',
            'question': 'Forces the viewer to answer internally.',
            'experiment': 'Reduces skepticism by showing a test.',
        }
        return reasons.get(slug, 'Creates a strong scroll-stopping pattern.')

    def _build_script(self, topic: str, hook: str, seed: str, content_type: str) -> dict[str, Any]:
        hook_framework = 'Hook-Story-Value-CTA'
        hook_type = 'Scripted Hook'
        body = (
            f"1) Hook: {hook}\n"
            f"2) Problem: Show why {topic} is frustrating or misunderstood.\n"
            f"3) Value: Give 3 quick beats that solve or reframe it.\n"
            f"4) CTA: Tell them exactly what to do next."
        )
        filming_card = (
            f"Topic: {topic}\n"
            f"Hook: {hook}\n"
            "Beat 1: State the problem in plain English.\n"
            "Beat 2: Show the key insight or transformation.\n"
            "Beat 3: Close with a clear next step."
        )
        cta = 'Save this for later and follow for more.'
        caption = f"{topic} explained simply.\n\n{cta}"
        instructions = 'Film as a tight talking-head video. Keep the first 2 seconds aggressive and clear.'
        return {
            'hook_framework': hook_framework,
            'hook_type': hook_type,
            'content_type': content_type,
            'hook': hook,
            'script_body': body,
            'filming_card': filming_card,
            'caption': caption,
            'cta': cta,
            'recording_instructions': instructions,
            'raw_data': {'topic': topic, 'seed': seed},
        }

    def _build_hook_brief(self, topic: str, hooks: list[dict[str, Any]]) -> str:
        lines = [
            '# Hook Pack',
            '',
            f'- Topic: {topic}',
            f'- Hooks generated: {len(hooks)}',
            '',
        ]
        for hook in hooks:
            lines.append(f"- {hook['hook_framework']}: {hook['hook_text']}")
        return '\n'.join(lines)
