from __future__ import annotations

from collections import Counter
from typing import Any

from supabase import Client

from app.dependencies import get_supabase_admin
from app.services.content_intelligence import ContentIntelligenceService


class CompetitorService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()
        self.content_service = ContentIntelligenceService(self.supabase)

    async def add_competitor(
        self,
        *,
        user_id: str,
        handle: str,
        display_name: str | None = None,
        platform: str = 'instagram',
        active: bool = True,
    ) -> dict[str, Any]:
        return await self.content_service.upsert_account(
            user_id=user_id,
            handle=handle,
            platform=platform,
            account_type='competitor',
            active=active,
            display_name=display_name,
        )

    async def list_competitors(self, user_id: str) -> list[dict[str, Any]]:
        result = (
            self.supabase.table('content_accounts')
            .select('*')
            .eq('user_id', user_id)
            .eq('account_type', 'competitor')
            .order('created_at', desc=True)
            .execute()
        )
        return result.data or []

    async def get_competitor_feed(
        self,
        *,
        user_id: str,
        handle: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        account = (
            self.supabase.table('content_accounts')
            .select('*')
            .eq('user_id', user_id)
            .eq('handle', handle)
            .eq('account_type', 'competitor')
            .maybe_single()
            .execute()
        )
        if not account.data:
            return []

        result = (
            self.supabase.table('content_with_scores')
            .select('*')
            .eq('user_id', user_id)
            .eq('account_id', account.data['id'])
            .order('scraped_at', desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def compare_user_vs_competitor(
        self,
        *,
        user_id: str,
        handle: str,
    ) -> dict[str, Any]:
        brief = await self.content_service.generate_brief(user_id=user_id)
        competitor_feed = await self.get_competitor_feed(user_id=user_id, handle=handle)

        if not competitor_feed:
            return {
                'user_summary': brief['summary'],
                'competitor_summary': {},
                'gaps': ['No competitor content found'],
                'shared_topics': [],
                'top_competitor_posts': [],
            }

        topics = Counter(row.get('topic') for row in competitor_feed if row.get('topic'))
        hooks = Counter(row.get('hook_structure') for row in competitor_feed if row.get('hook_structure'))
        content_types = Counter(row.get('content_type') for row in competitor_feed if row.get('content_type'))

        user_topics = set(brief['summary'].get('topics', {}).keys())
        competitor_topics = set(topics.keys())
        shared_topics = sorted(user_topics.intersection(competitor_topics))

        gaps: list[str] = []
        if hooks:
            top_hook = hooks.most_common(1)[0][0]
            if top_hook and top_hook not in brief['summary'].get('hook_structures', {}):
                gaps.append(f'Competitor uses {top_hook} hooks more than you do')
        if content_types:
            top_type = content_types.most_common(1)[0][0]
            if top_type and top_type not in brief['summary'].get('content_types', {}):
                gaps.append(f'Competitor leans on {top_type} content more than you do')
        if competitor_topics:
            top_topic = topics.most_common(1)[0][0]
            if top_topic and top_topic not in user_topics:
                gaps.append(f'Competitor owns topic "{top_topic}" more strongly')

        return {
            'user_summary': brief['summary'],
            'competitor_summary': {
                'total_posts': len(competitor_feed),
                'avg_views': round(sum(int(row.get('views', 0) or 0) for row in competitor_feed) / len(competitor_feed), 2),
                'top_topics': dict(topics),
                'top_hooks': dict(hooks),
                'top_content_types': dict(content_types),
            },
            'gaps': gaps,
            'shared_topics': shared_topics,
            'top_competitor_posts': competitor_feed[:5],
        }
