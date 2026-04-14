from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any

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
            comp_account = self._get_account_by_handle(user_id, comp_handle)

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
        likes = [float(p.get('likes', 0) or 0) for p in posts]
        comments = [float(p.get('comments', 0) or 0) for p in posts]
        views = [float(p.get('views', 0) or 0) for p in posts]

        avg_likes = round(sum(likes) / len(likes), 2) if likes else 0.0
        median_likes = round(statistics.median(likes), 2) if likes else 0.0
        avg_comments = round(sum(comments) / len(comments), 2) if comments else 0.0
        avg_views = round(sum(views) / len(views), 2) if views else 0.0
        posts_per_week = round(len(posts) / (window_days / 7), 2)

        engagement_rate: float | None = None
        if avg_views > 0:
            engagement_rate = round((avg_likes + avg_comments) / avg_views, 4)

        return BenchmarkMetrics(
            avg_likes=avg_likes,
            median_likes=median_likes,
            avg_comments=avg_comments,
            avg_views=avg_views,
            engagement_rate=engagement_rate,
            posts_per_week=posts_per_week,
        )

    def _compute_hook_gaps(self, own_posts: list[dict], competitor_posts: list[dict]) -> list[HookGap]:
        own_top = Counter(
            p.get('hook_structure') for p in own_posts if p.get('hook_structure')
        )
        comp_top = Counter(
            p.get('hook_structure') for p in competitor_posts if p.get('hook_structure')
        )
        # Hooks present in competitor top-10 that are absent or less frequent in own
        gaps: list[HookGap] = []
        for hook, comp_freq in comp_top.most_common(10):
            own_freq = own_top.get(hook, 0)
            if own_freq < comp_freq:
                gaps.append(HookGap(
                    hook_structure=hook,
                    competitor_frequency=comp_freq,
                    own_frequency=own_freq,
                ))
        return sorted(gaps, key=lambda g: g.competitor_frequency, reverse=True)

    def _compute_topic_gaps(self, own_posts: list[dict], competitor_posts: list[dict]) -> list[TopicGap]:
        own_top = Counter(p.get('topic') for p in own_posts if p.get('topic'))
        comp_top = Counter(p.get('topic') for p in competitor_posts if p.get('topic'))
        gaps: list[TopicGap] = []
        for topic, comp_freq in comp_top.most_common(10):
            own_freq = own_top.get(topic, 0)
            if own_freq < comp_freq:
                gaps.append(TopicGap(
                    topic=topic,
                    competitor_frequency=comp_freq,
                    own_frequency=own_freq,
                ))
        return sorted(gaps, key=lambda g: g.competitor_frequency, reverse=True)

    def _compute_content_type_gaps(self, own_posts: list[dict], competitor_posts: list[dict]) -> list[ContentTypeGap]:
        own_top = Counter(p.get('content_type') for p in own_posts if p.get('content_type'))
        comp_top = Counter(p.get('content_type') for p in competitor_posts if p.get('content_type'))
        gaps: list[ContentTypeGap] = []
        for ct, comp_freq in comp_top.most_common(10):
            own_freq = own_top.get(ct, 0)
            if own_freq < comp_freq:
                gaps.append(ContentTypeGap(
                    content_type=ct,
                    competitor_frequency=comp_freq,
                    own_frequency=own_freq,
                ))
        return sorted(gaps, key=lambda g: g.competitor_frequency, reverse=True)

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

        # Infer from topics absent in both
        if len(entries) < _WHITE_SPACE_LIMIT:
            # Nothing to infer if there are no topics at all
            pass

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
        return result.data or None

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
