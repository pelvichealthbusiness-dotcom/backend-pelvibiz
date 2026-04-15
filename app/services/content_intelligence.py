from __future__ import annotations

from datetime import datetime, timezone
from collections import Counter
from typing import Any

from supabase import Client

from app.dependencies import get_supabase_admin


class ContentIntelligenceService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()

    async def upsert_account(
        self,
        *,
        user_id: str,
        handle: str,
        platform: str = 'instagram',
        account_type: str = 'personal',
        active: bool = True,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            'user_id': user_id,
            'handle': handle,
            'platform': platform,
            'account_type': account_type,
            'active': active,
            'display_name': display_name,
            'metadata': metadata or {},
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        result = self.supabase.table('content_accounts').upsert(payload, on_conflict='user_id,handle,platform').execute()
        return result.data[0] if result.data else payload

    async def upsert_content(
        self,
        *,
        user_id: str,
        account_id: str,
        source_post_id: str,
        media_type: str = 'reel',
        permalink: str | None = None,
        caption: str | None = None,
        posted_at: str | None = None,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        saves: int = 0,
        watch_time_seconds: int = 0,
        reach: int = 0,
        transcript: str | None = None,
        spoken_hook: str | None = None,
        hook_framework: str | None = None,
        hook_structure: str | None = None,
        text_hook: str | None = None,
        visual_format: str | None = None,
        audio_hook: str | None = None,
        topic: str | None = None,
        topic_summary: str | None = None,
        content_structure: str | None = None,
        content_type: str | None = None,
        call_to_action: str | None = None,
        analysis_status: str = 'pending',
        analysis_error: str | None = None,
        raw_data: dict[str, Any] | None = None,
        scraped_at: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            'user_id': user_id,
            'account_id': account_id,
            'source_post_id': source_post_id,
            'media_type': media_type,
            'permalink': permalink,
            'caption': caption,
            'posted_at': posted_at,
            'views': views,
            'likes': likes,
            'comments': comments,
            'shares': shares,
            'saves': saves,
            'watch_time_seconds': watch_time_seconds,
            'reach': reach,
            'transcript': transcript,
            'spoken_hook': spoken_hook,
            'hook_framework': hook_framework,
            'hook_structure': hook_structure,
            'text_hook': text_hook,
            'visual_format': visual_format,
            'audio_hook': audio_hook,
            'topic': topic,
            'topic_summary': topic_summary,
            'content_structure': content_structure,
            'content_type': content_type,
            'call_to_action': call_to_action,
            'analysis_status': analysis_status,
            'analysis_error': analysis_error,
            'raw_data': raw_data or {},
            'scraped_at': scraped_at or datetime.now(timezone.utc).isoformat(),
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        result = self.supabase.table('content').upsert(payload, on_conflict='account_id,source_post_id').execute()
        return result.data[0] if result.data else payload

    async def upsert_snapshot(
        self,
        *,
        user_id: str,
        account_id: str,
        content_id: str,
        snapshot_date: str | None = None,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        saves: int = 0,
        watch_time_seconds: int = 0,
        reach: int = 0,
        analysis_status: str = 'pending',
        raw_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            'user_id': user_id,
            'account_id': account_id,
            'content_id': content_id,
            'snapshot_date': snapshot_date or datetime.now(timezone.utc).date().isoformat(),
            'views': views,
            'likes': likes,
            'comments': comments,
            'shares': shares,
            'saves': saves,
            'watch_time_seconds': watch_time_seconds,
            'reach': reach,
            'analysis_status': analysis_status,
            'raw_data': raw_data or {},
        }
        result = self.supabase.table('content_snapshots').upsert(payload, on_conflict='content_id,snapshot_date').execute()
        return result.data[0] if result.data else payload

    async def store_scrape(
        self,
        *,
        user_id: str,
        handle: str,
        posts: list[dict[str, Any]],
        platform: str = 'instagram',
        account_type: str = 'competitor',
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        account = await self.upsert_account(
            user_id=user_id,
            handle=handle,
            platform=platform,
            account_type=account_type,
            display_name=display_name,
            metadata=metadata,
        )

        saved_posts: list[dict[str, Any]] = []
        for post in posts:
            content = await self.upsert_content(
                user_id=user_id,
                account_id=account['id'],
                source_post_id=str(post.get('id') or post.get('source_post_id')),
                media_type=post.get('media_type', 'reel'),
                permalink=post.get('permalink'),
                caption=post.get('caption'),
                posted_at=post.get('posted_at'),
                views=int(post.get('views', 0) or 0),
                likes=int(post.get('likes', 0) or 0),
                comments=int(post.get('comments', 0) or 0),
                shares=int(post.get('shares', 0) or 0),
                saves=int(post.get('saves', 0) or 0),
                watch_time_seconds=int(post.get('watch_time_seconds', 0) or 0),
                reach=int(post.get('reach', 0) or 0),
                transcript=post.get('transcript'),
                spoken_hook=post.get('spoken_hook'),
                hook_framework=post.get('hook_framework'),
                hook_structure=post.get('hook_structure'),
                text_hook=post.get('text_hook'),
                visual_format=post.get('visual_format'),
                audio_hook=post.get('audio_hook'),
                topic=post.get('topic'),
                topic_summary=post.get('topic_summary'),
                content_structure=post.get('content_structure'),
                content_type=post.get('content_type'),
                call_to_action=post.get('call_to_action'),
                analysis_status=post.get('analysis_status', 'pending'),
                analysis_error=post.get('analysis_error'),
                raw_data=post.get('raw_data'),
                scraped_at=post.get('scraped_at'),
            )
            saved_posts.append(content)
            await self.upsert_snapshot(
                user_id=user_id,
                account_id=account['id'],
                content_id=content['id'],
                views=int(post.get('views', 0) or 0),
                likes=int(post.get('likes', 0) or 0),
                comments=int(post.get('comments', 0) or 0),
                shares=int(post.get('shares', 0) or 0),
                saves=int(post.get('saves', 0) or 0),
                watch_time_seconds=int(post.get('watch_time_seconds', 0) or 0),
                reach=int(post.get('reach', 0) or 0),
                analysis_status=post.get('analysis_status', 'pending'),
                raw_data=post.get('raw_data'),
            )

        return {'account': account, 'posts': saved_posts}

    async def list_account_stats(self, user_id: str) -> list[dict[str, Any]]:
        result = (
            self.supabase.table('account_stats')
            .select('*')
            .eq('user_id', user_id)
            .order('avg_views', desc=True)
            .execute()
        )
        return result.data or []

    async def list_content_with_scores(
        self,
        *,
        user_id: str,
        account_id: str | None = None,
        account_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = (
            self.supabase.table('content_with_scores')
            .select('*')
            .eq('user_id', user_id)
            .order('scraped_at', desc=True)
            .limit(limit)
        )
        if account_id:
            query = query.eq('account_id', account_id)
        elif account_type:
            # content_with_scores view doesn't expose account_type — resolve the
            # own/competitor account IDs first and filter by those.
            accounts_result = (
                self.supabase.table('content_accounts')
                .select('id')
                .eq('user_id', user_id)
                .eq('account_type', account_type)
                .execute()
            )
            own_ids = [row['id'] for row in (accounts_result.data or [])]
            if own_ids:
                query = query.in_('account_id', own_ids)
            else:
                return []  # No own accounts yet — return empty rather than all
        result = query.execute()
        return result.data or []

    async def generate_brief(
        self,
        *,
        user_id: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        account_stats = await self.list_account_stats(user_id)
        # Filter to own-account content only to prevent competitor posts from
        # polluting style signals (T1.4). When a specific account_id is given we
        # trust the caller already selected the right account; otherwise restrict
        # to account_type='personal' to exclude competitor data.
        content_rows = await self.list_content_with_scores(
            user_id=user_id,
            account_id=account_id,
            account_type=None if account_id else 'personal',
        )

        if not content_rows:
            return {
                'ready': False,
                'reason': 'insufficient_data',
                'brief_markdown': 'Not enough analyzed content yet to generate a performance brief.',
                'account_stats': account_stats,
                'content_rows': [],
            }

        total_posts = len(content_rows)
        avg_views = round(sum(int(row.get('views', 0) or 0) for row in content_rows) / total_posts, 2)
        top_post = max(content_rows, key=lambda row: int(row.get('views', 0) or 0))

        outlier_counts = Counter(row.get('outlier_category', 'below_average') for row in content_rows)
        topic_counts = Counter(row.get('topic') for row in content_rows if row.get('topic'))
        hook_counts = Counter(row.get('hook_structure') for row in content_rows if row.get('hook_structure'))
        content_type_counts = Counter(row.get('content_type') for row in content_rows if row.get('content_type'))

        top_accounts = account_stats[:3]
        brief_markdown = "\n".join([
            '# Performance Brief',
            '',
            f'- Total posts: {total_posts}',
            f'- Average views: {avg_views}',
            f'- Top post: {top_post.get("topic") or top_post.get("content_type") or top_post.get("source_post_id")} ({int(top_post.get("views", 0) or 0)} views)',
            '',
            '## Outliers',
            *[f'- {label}: {count}' for label, count in outlier_counts.most_common()],
            '',
            '## Topics',
            *[f'- {label}: {count}' for label, count in topic_counts.most_common(10)],
            '',
            '## Hook Structures',
            *[f'- {label}: {count}' for label, count in hook_counts.most_common(10)],
            '',
            '## Content Types',
            *[f'- {label}: {count}' for label, count in content_type_counts.most_common(10)],
            '',
            '## Top Accounts',
            *[
                f'- @{row.get("handle")}: {row.get("avg_views", 0)} avg views, {row.get("post_count", 0)} posts'
                for row in top_accounts
            ],
        ])

        return {
            'ready': True,
            'reason': None,
            'brief_markdown': brief_markdown,
            'account_stats': account_stats,
            'content_rows': content_rows,
            'summary': {
                'total_posts': total_posts,
                'avg_views': avg_views,
                'top_post': top_post,
                'outliers': dict(outlier_counts),
                'topics': dict(topic_counts),
                'hook_structures': dict(hook_counts),
                'content_types': dict(content_type_counts),
            },
        }

    def get_competitor_context_block(self, user_id: str, competitor_handle: str | None) -> str | None:
        """
        Returns a formatted ## Competitor Intelligence block for injection into agent prompts.
        Reads from competitor_analyses cache only (no recompute).
        Returns None if handle is None or no cached analysis found.
        Enforces ~800-token budget: top 5 hook_gaps, top 5 topic_gaps, top 3 white_space.
        """
        if not competitor_handle:
            return None

        # 1. Find the competitor account by handle
        competitor_account = (
            self.supabase.table('content_accounts')
            .select('id, handle, followers_count')
            .eq('user_id', user_id)
            .eq('handle', competitor_handle.lstrip('@'))
            .eq('account_type', 'competitor')
            .maybe_single()
            .execute()
        )
        if not competitor_account.data:
            return None

        # 2. Find own account
        own_account = (
            self.supabase.table('content_accounts')
            .select('id')
            .eq('user_id', user_id)
            .eq('account_type', 'personal')
            .maybe_single()
            .execute()
        )
        if not own_account.data:
            return None

        # 3. Read cached analysis (must be within 24h)
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        cached = (
            self.supabase.table('competitor_analyses')
            .select('hook_gaps, topic_gaps, white_space, benchmarks')
            .eq('user_id', user_id)
            .eq('own_account_id', own_account.data['id'])
            .eq('competitor_account_id', competitor_account.data['id'])
            .gte('updated_at', cutoff)
            .order('updated_at', desc=True)
            .limit(1)
            .execute()
        )
        if not cached.data:
            return None

        analysis = cached.data[0]
        hook_gaps = (analysis.get('hook_gaps') or [])[:5]
        topic_gaps = (analysis.get('topic_gaps') or [])[:5]
        white_space = (analysis.get('white_space') or [])[:3]
        benchmarks = analysis.get('benchmarks') or {}

        # Format block
        handle_display = competitor_account.data['handle']
        followers = competitor_account.data.get('followers_count', 0)
        posts_per_week = benchmarks.get('posts_per_week', '?')

        lines = [
            '## Competitor Intelligence',
            '',
            f'Handle: @{handle_display} | Followers: {followers:,} | Posts/week: {posts_per_week}',
            '',
        ]

        if hook_gaps:
            lines += ['### Hook Gaps (hooks they use that you don\'t)']
            for h in hook_gaps:
                lines.append(f"- {h['hook_structure']} ({h['competitor_frequency']}x)")
            lines.append('')

        if topic_gaps:
            lines += ['### Topic Gaps (topics they own that you don\'t)']
            for t in topic_gaps:
                lines.append(f"- {t['topic']} ({t['competitor_frequency']}x)")
            lines.append('')

        if white_space:
            lines += ['### White Space Opportunities']
            for w in white_space:
                lines.append(f"- {w['topic']}")
            lines.append('')

        lines.append('Use this data to bias your output toward addressing these gaps where relevant.')

        return '\n'.join(lines)

    def get_competitor_gaps(self, user_id: str, competitor_handle: str) -> dict[str, Any]:
        """
        Return structured gap data for the given competitor handle.
        Reads from competitor_analyses cache (max 24h). Returns empty arrays if not found.
        """
        from datetime import timedelta

        empty: dict[str, Any] = {'hook_gaps': [], 'topic_gaps': [], 'white_space': []}
        handle = competitor_handle.lstrip('@')

        competitor_account = (
            self.supabase.table('content_accounts')
            .select('id')
            .eq('user_id', user_id)
            .eq('handle', handle)
            .eq('account_type', 'competitor')
            .maybe_single()
            .execute()
        )
        if not competitor_account.data:
            return empty

        own_account = (
            self.supabase.table('content_accounts')
            .select('id')
            .eq('user_id', user_id)
            .eq('account_type', 'personal')
            .maybe_single()
            .execute()
        )
        if not own_account.data:
            return empty

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        cached = (
            self.supabase.table('competitor_analyses')
            .select('hook_gaps, topic_gaps, white_space')
            .eq('user_id', user_id)
            .eq('own_account_id', own_account.data['id'])
            .eq('competitor_account_id', competitor_account.data['id'])
            .gte('updated_at', cutoff)
            .order('updated_at', desc=True)
            .limit(1)
            .execute()
        )
        if not cached.data:
            return empty

        analysis = cached.data[0]
        hook_gaps = analysis.get('hook_gaps') or []
        topic_gaps = analysis.get('topic_gaps') or []
        white_space = analysis.get('white_space') or []

        # Normalise to plain string lists for frontend consumption
        def _hook_str(h: Any) -> str:
            if isinstance(h, dict):
                freq = h.get('competitor_frequency', '')
                text = h.get('hook_structure') or h.get('hook_text') or str(h)
                return f"{text} ({freq}x)" if freq else text
            return str(h)

        def _topic_str(t: Any) -> str:
            if isinstance(t, dict):
                freq = t.get('competitor_frequency', '')
                text = t.get('topic') or str(t)
                return f"{text} ({freq}x)" if freq else text
            return str(t)

        def _space_str(w: Any) -> str:
            if isinstance(w, dict):
                return w.get('topic') or w.get('angle') or str(w)
            return str(w)

        return {
            'hook_gaps': [_hook_str(h) for h in hook_gaps],
            'topic_gaps': [_topic_str(t) for t in topic_gaps],
            'white_space': [_space_str(w) for w in white_space],
        }

    async def get_optional_studio_context(
        self,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        profile_result = (
            self.supabase.table('profiles')
            .select('content_style_brief')
            .eq('id', user_id)
            .maybe_single()
            .execute()
        )
        profile = profile_result.data or {}
        # Studio context must only reflect the user's own style — pass no
        # account_id so generate_brief applies the account_type='personal' guard
        # and competitor posts are excluded from style signals (T1.5).
        brief = await self.generate_brief(user_id=user_id)

        if not brief.get('ready'):
            brief = {
                'ready': False,
                'reason': brief.get('reason'),
                'brief_markdown': '',
                'summary': {},
                'account_stats': [],
            }

        summary = brief.get('summary') or {}
        return {
            'content_style_brief': profile.get('content_style_brief') or '',
            'brief_markdown': brief.get('brief_markdown') or '',
            'summary': summary,
            'top_topics': list((summary.get('topics') or {}).keys())[:5],
            'top_hooks': list((summary.get('hook_structures') or {}).keys())[:5],
            'top_content_types': list((summary.get('content_types') or {}).keys())[:5],
        }
