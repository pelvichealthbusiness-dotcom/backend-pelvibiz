from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd

from supabase import Client

from app.core.supabase_client import get_service_client
from app.dependencies import get_supabase_admin
from app.models.competitors import (
    BenchmarkMetrics,
    CompareResponse,
    CompetitorResult,
    ContentTypeGap,
    HookGap,
    TopicGap,
    WhiteSpaceEntry,
)
from app.services.content_intelligence import ContentIntelligenceService
from app.services.style_analyzer import StyleAnalyzer

logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 24
_MIN_POSTS_REQUIRED = 10
_WHITE_SPACE_LIMIT = 5


class CompetitorService:
    def __init__(self, supabase: Client | None = None):
        # Keep backward-compatible ctor: existing endpoints pass nothing or a client
        self.supabase = supabase or get_supabase_admin()
        self.content_service = ContentIntelligenceService(self.supabase)
        # Service-role client used specifically for competitor_analyses upsert
        self._svc = get_service_client()

    # ------------------------------------------------------------------
    # Existing public methods (kept intact for backward compatibility)
    # ------------------------------------------------------------------

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

    async def delete_competitor(self, *, user_id: str, handle: str) -> None:
        self.supabase.table('content_accounts') \
            .delete() \
            .eq('user_id', user_id) \
            .eq('handle', handle) \
            .eq('account_type', 'competitor') \
            .execute()

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
        user_summary = brief.get('summary', {})
        competitor_feed = await self.get_competitor_feed(user_id=user_id, handle=handle)

        # Fetch stored profile metadata (followers, biography, etc.)
        account_row = (
            self.supabase.table('content_accounts')
            .select('metadata, display_name')
            .eq('user_id', user_id)
            .eq('handle', handle)
            .maybe_single()
            .execute()
        )
        account_meta: dict[str, Any] = {}
        if account_row and account_row.data:
            account_meta = account_row.data.get('metadata') or {}

        if not competitor_feed:
            return {
                'user_summary': user_summary,
                'competitor_summary': {},
                'profile': account_meta,
                'gaps': ['No competitor content found — try re-scanning this account.'],
                'shared_topics': [],
                'top_competitor_posts': [],
                'viral_posts': [],
            }

        n = len(competitor_feed)
        views_list  = [int(row.get('views', 0)  or 0) for row in competitor_feed]
        likes_list  = [int(row.get('likes', 0)  or 0) for row in competitor_feed]
        comments_list = [int(row.get('comments', 0) or 0) for row in competitor_feed]
        saves_list  = [int(row.get('saves', 0)  or 0) for row in competitor_feed]
        engagement_list = [float(row.get('engagement_rate', 0) or 0) for row in competitor_feed]

        avg_views    = round(sum(views_list)    / n, 0)
        avg_likes    = round(sum(likes_list)    / n, 0)
        avg_comments = round(sum(comments_list) / n, 1)
        avg_saves    = round(sum(saves_list)    / n, 1)
        avg_engagement = round(sum(engagement_list) / n, 4) if any(engagement_list) else None

        # Posts per week from date range
        posts_per_week: float | None = None
        dates = [row.get('posted_at') or row.get('scraped_at') for row in competitor_feed if row.get('posted_at') or row.get('scraped_at')]
        if len(dates) >= 2:
            try:
                from datetime import datetime as _dt
                parsed = sorted([_dt.fromisoformat(d.replace('Z', '+00:00')) for d in dates])
                span_days = max((parsed[-1] - parsed[0]).days, 1)
                posts_per_week = round(n / (span_days / 7), 1)
            except Exception:
                pass

        topics       = Counter(row.get('topic') for row in competitor_feed if row.get('topic'))
        hooks        = Counter(row.get('hook_structure') for row in competitor_feed if row.get('hook_structure'))
        content_types = Counter(row.get('content_type') for row in competitor_feed if row.get('content_type'))

        user_topics = set(user_summary.get('topics', {}).keys())
        competitor_topics = set(topics.keys())
        shared_topics = sorted(user_topics.intersection(competitor_topics))

        gaps: list[str] = []
        if hooks:
            top_hook = hooks.most_common(1)[0][0]
            if top_hook and top_hook not in user_summary.get('hook_structures', {}):
                gaps.append(f'Competitor uses "{top_hook}" hooks more than you do')
        if content_types:
            top_type = content_types.most_common(1)[0][0]
            if top_type and top_type not in user_summary.get('content_types', {}):
                gaps.append(f'Competitor leans on {top_type} content more than you do')
        if competitor_topics:
            top_topic = topics.most_common(1)[0][0]
            if top_topic and top_topic not in user_topics:
                gaps.append(f'Competitor dominates topic "{top_topic}" — you haven\'t covered it yet')

        # Top posts sorted by views desc
        top_posts = sorted(competitor_feed, key=lambda r: int(r.get('views', 0) or 0), reverse=True)[:5]

        # Viral outliers: posts with views > 2× avg_views (min 2× threshold)
        viral_posts = [
            row for row in competitor_feed
            if avg_views > 0 and int(row.get('views', 0) or 0) >= avg_views * 2
        ]
        viral_posts = sorted(viral_posts, key=lambda r: int(r.get('views', 0) or 0), reverse=True)[:5]

        return {
            'user_summary': user_summary,
            'profile': {
                'followers': account_meta.get('followers', 0),
                'following': account_meta.get('following', 0),
                'biography': account_meta.get('biography', ''),
                'is_verified': account_meta.get('is_verified', False),
                'full_name': account_meta.get('full_name', ''),
            },
            'competitor_summary': {
                'total_posts': n,
                'avg_views': avg_views,
                'avg_likes': avg_likes,
                'avg_comments': avg_comments,
                'avg_saves': avg_saves,
                'avg_engagement': avg_engagement,
                'posts_per_week': posts_per_week,
                'top_topics': dict(topics),
                'top_hooks': dict(hooks),
                'top_content_types': dict(content_types),
            },
            'gaps': gaps,
            'shared_topics': shared_topics,
            'top_competitor_posts': top_posts,
            'viral_posts': viral_posts,
        }

    # ------------------------------------------------------------------
    # Phase 2 — compare_accounts (synchronous, uses service-role client)
    # ------------------------------------------------------------------

    def compare_accounts(
        self,
        user_id: str,
        own_handle: str,
        competitor_handles: list[str],
        window_days: int = 30,
        force_recompute: bool = False,
    ) -> CompareResponse:
        """Main comparison. Caches results in competitor_analyses."""
        own_account = self._get_account_by_handle(user_id, own_handle, account_type='own')
        own_posts = self._get_posts_for_account(own_account['id'], window_days) if own_account else []
        own_summary = {
            'handle': own_handle,
            'account_id': own_account['id'] if own_account else None,
            'post_count': len(own_posts),
        }

        competitor_results: list[CompetitorResult] = []

        for comp_handle in competitor_handles:
            comp_account = self._get_account_by_handle(user_id, comp_handle, account_type='competitor')

            if not comp_account:
                competitor_results.append(CompetitorResult(
                    handle=comp_handle,
                    followers_count=0,
                    benchmarks=None,
                    hook_gaps=[],
                    topic_gaps=[],
                    content_type_gaps=[],
                    white_space=[],
                    cadence_delta_per_week=None,
                    style_diff=None,
                    cached=False,
                    computed_at=None,
                    status='insufficient_data',
                ))
                continue

            # Check cache
            if not force_recompute and own_account:
                cached = self._load_cache(
                    user_id=user_id,
                    own_account_id=own_account['id'],
                    competitor_account_id=comp_account['id'],
                    window_days=window_days,
                )
                if cached:
                    competitor_results.append(cached)
                    continue

            # Compute fresh
            comp_posts = self._get_posts_for_account(comp_account['id'], window_days)

            if len(comp_posts) < _MIN_POSTS_REQUIRED:
                result = CompetitorResult(
                    handle=comp_handle,
                    followers_count=int(comp_account.get('followers_count', 0) or 0),
                    benchmarks=None,
                    hook_gaps=[],
                    topic_gaps=[],
                    content_type_gaps=[],
                    white_space=[],
                    cadence_delta_per_week=None,
                    style_diff=None,
                    cached=False,
                    computed_at=None,
                    status='insufficient_data',
                )
            else:
                benchmarks = self._compute_benchmarks(comp_posts, window_days)
                own_benchmarks = self._compute_benchmarks(own_posts, window_days) if own_posts else None
                cadence_delta = None
                if own_benchmarks is not None:
                    cadence_delta = round(benchmarks.posts_per_week - own_benchmarks.posts_per_week, 2)

                computed_at = datetime.now(timezone.utc).isoformat()
                result = CompetitorResult(
                    handle=comp_handle,
                    followers_count=int(comp_account.get('followers_count', 0) or 0),
                    benchmarks=benchmarks,
                    hook_gaps=self._compute_hook_gaps(own_posts, comp_posts),
                    topic_gaps=self._compute_topic_gaps(own_posts, comp_posts),
                    content_type_gaps=self._compute_content_type_gaps(own_posts, comp_posts),
                    white_space=self._compute_white_space(user_id, own_posts, comp_posts),
                    cadence_delta_per_week=cadence_delta,
                    style_diff=self._compute_style_diff(comp_posts),
                    cached=False,
                    computed_at=computed_at,
                    status='ok',
                )

                # Persist to cache if we have own_account
                if own_account:
                    self._store_cache(
                        user_id=user_id,
                        own_account_id=own_account['id'],
                        competitor_account_id=comp_account['id'],
                        window_days=window_days,
                        result=result,
                    )

            competitor_results.append(result)

        return CompareResponse(
            own=own_summary,
            competitors=competitor_results,
            status='ok',
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_benchmarks(self, posts: list[dict], window_days: int) -> BenchmarkMetrics:
        df = pd.DataFrame(posts)
        likes = pd.to_numeric(df.get('likes', pd.Series(dtype=float)), errors='coerce').fillna(0)
        comments = pd.to_numeric(df.get('comments', pd.Series(dtype=float)), errors='coerce').fillna(0)
        views = pd.to_numeric(df.get('views', pd.Series(dtype=float)), errors='coerce').fillna(0)

        avg_likes = round(float(likes.mean()), 2) if len(likes) > 0 else 0.0
        median_likes = round(float(likes.median()), 2) if len(likes) > 0 else 0.0
        avg_comments = round(float(comments.mean()), 2) if len(comments) > 0 else 0.0
        avg_views = round(float(views.mean()), 2) if len(views) > 0 else 0.0
        posts_per_week = round(len(posts) / (window_days / 7), 2)
        engagement_rate = round(float((avg_likes + avg_comments) / avg_views), 4) if avg_views > 0 else None

        return BenchmarkMetrics(
            avg_likes=avg_likes,
            median_likes=median_likes,
            avg_comments=avg_comments,
            avg_views=avg_views,
            engagement_rate=engagement_rate,
            posts_per_week=posts_per_week,
        )

    def _compute_hook_gaps(self, own_posts: list[dict], competitor_posts: list[dict]) -> list[HookGap]:
        df_own = pd.DataFrame(own_posts)
        df_comp = pd.DataFrame(competitor_posts)

        own_freq = df_own['hook_structure'].dropna().value_counts() if 'hook_structure' in df_own else pd.Series(dtype=int)
        comp_freq = df_comp['hook_structure'].dropna().value_counts() if 'hook_structure' in df_comp else pd.Series(dtype=int)

        merged = pd.DataFrame({'comp': comp_freq, 'own': own_freq}).fillna(0).astype(int)
        gaps_df = merged[merged['comp'] > merged['own']].sort_values('comp', ascending=False).head(10)

        return [
            HookGap(hook_structure=idx, competitor_frequency=int(row['comp']), own_frequency=int(row['own']))
            for idx, row in gaps_df.iterrows()
        ]

    def _compute_topic_gaps(self, own_posts: list[dict], competitor_posts: list[dict]) -> list[TopicGap]:
        df_own = pd.DataFrame(own_posts)
        df_comp = pd.DataFrame(competitor_posts)

        own_freq = df_own['topic'].dropna().value_counts() if 'topic' in df_own else pd.Series(dtype=int)
        comp_freq = df_comp['topic'].dropna().value_counts() if 'topic' in df_comp else pd.Series(dtype=int)

        merged = pd.DataFrame({'comp': comp_freq, 'own': own_freq}).fillna(0).astype(int)
        gaps_df = merged[merged['comp'] > merged['own']].sort_values('comp', ascending=False).head(10)

        return [
            TopicGap(topic=idx, competitor_frequency=int(row['comp']), own_frequency=int(row['own']))
            for idx, row in gaps_df.iterrows()
        ]

    def _compute_content_type_gaps(self, own_posts: list[dict], competitor_posts: list[dict]) -> list[ContentTypeGap]:
        df_own = pd.DataFrame(own_posts)
        df_comp = pd.DataFrame(competitor_posts)

        own_freq = df_own['content_type'].dropna().value_counts() if 'content_type' in df_own else pd.Series(dtype=int)
        comp_freq = df_comp['content_type'].dropna().value_counts() if 'content_type' in df_comp else pd.Series(dtype=int)

        merged = pd.DataFrame({'comp': comp_freq, 'own': own_freq}).fillna(0).astype(int)
        gaps_df = merged[merged['comp'] > merged['own']].sort_values('comp', ascending=False).head(10)

        return [
            ContentTypeGap(content_type=idx, competitor_frequency=int(row['comp']), own_frequency=int(row['own']))
            for idx, row in gaps_df.iterrows()
        ]

    def _compute_white_space(
        self,
        user_id: str,
        own_posts: list[dict],
        competitor_posts: list[dict],
    ) -> list[WhiteSpaceEntry]:
        own_topics = {p.get('topic') for p in own_posts if p.get('topic')}
        comp_topics = {p.get('topic') for p in competitor_posts if p.get('topic')}
        both_topics = own_topics | comp_topics

        entries: list[WhiteSpaceEntry] = []

        # Try research_topics table first
        try:
            result = (
                self._svc.table('research_topics')
                .select('topic, source')
                .eq('user_id', user_id)
                .execute()
            )
            for row in (result.data or []):
                topic = row.get('topic')
                if topic and topic not in both_topics:
                    entries.append(WhiteSpaceEntry(topic=topic, signal_source='trending'))
                if len(entries) >= _WHITE_SPACE_LIMIT:
                    break
        except Exception:
            logger.debug('research_topics not available, falling back to inferred white space')

        # Infer from topics that appear in one side but not the other
        if len(entries) < _WHITE_SPACE_LIMIT:
            asymmetric = own_topics.symmetric_difference(comp_topics)
            for topic in sorted(asymmetric):
                if topic:
                    entries.append(WhiteSpaceEntry(topic=topic, signal_source='inferred'))
                if len(entries) >= _WHITE_SPACE_LIMIT:
                    break

        return entries[:_WHITE_SPACE_LIMIT]

    def _compute_style_diff(self, competitor_posts: list[dict]) -> dict | None:
        try:
            analyzer = StyleAnalyzer()
            profile_data = {'followers': 0}
            return analyzer.analyze(competitor_posts, profile_data)
        except Exception as exc:
            logger.warning('StyleAnalyzer failed: %s', exc)
            return None

    def _get_posts_for_account(self, account_id: str, window_days: int) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        result = (
            self._svc.table('content')
            .select('*')
            .eq('account_id', account_id)
            .gte('scraped_at', cutoff)
            .execute()
        )
        return result.data or []

    def _get_account_by_handle(
        self,
        user_id: str,
        handle: str,
        account_type: str | None = None,
    ) -> dict | None:
        query = (
            self._svc.table('content_accounts')
            .select('*')
            .eq('user_id', user_id)
            .eq('handle', handle)
        )
        if account_type is not None:
            query = query.eq('account_type', account_type)
        result = query.maybe_single().execute()
        return (result.data if result else None) or None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _load_cache(
        self,
        *,
        user_id: str,
        own_account_id: str,
        competitor_account_id: str,
        window_days: int,
    ) -> CompetitorResult | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)).isoformat()
        try:
            result = (
                self._svc.table('competitor_analyses')
                .select('*')
                .eq('user_id', user_id)
                .eq('own_account_id', own_account_id)
                .eq('competitor_account_id', competitor_account_id)
                .eq('window_days', window_days)
                .gte('updated_at', cutoff)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            logger.warning('Cache read failed: %s', exc)
            return None

        if not result.data:
            return None

        row = result.data
        payload = row.get('analysis_payload') or {}
        try:
            return CompetitorResult(**payload, cached=True)
        except Exception as exc:
            logger.warning('Cache deserialization failed: %s', exc)
            return None

    def _store_cache(
        self,
        *,
        user_id: str,
        own_account_id: str,
        competitor_account_id: str,
        window_days: int,
        result: CompetitorResult,
    ) -> None:
        payload = result.model_dump()
        record = {
            'user_id': user_id,
            'own_account_id': own_account_id,
            'competitor_account_id': competitor_account_id,
            'window_days': window_days,
            'analysis_payload': payload,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._svc.table('competitor_analyses').upsert(
                record,
                on_conflict='user_id,own_account_id,competitor_account_id,window_days',
            ).execute()
        except Exception as exc:
            logger.warning('Cache write failed: %s', exc)
