from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import httpx
from supabase import Client

from app.dependencies import get_supabase_admin
from app.services.brand import BrandService
from app.services.competitors import CompetitorService
from app.services.content_intelligence import ContentIntelligenceService
from app.services.instagram_scraper import InstagramScraper

logger = logging.getLogger(__name__)

_SOCIAL_PLATFORMS = ("instagram", "facebook", "tiktok", "google")
_SEARCH_USER_AGENT = "PelviBizSocialResearch/1.0"
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "your", "from", "you", "are", "how", "what",
    "why", "when", "who", "what", "can", "should", "into", "over", "under", "about", "after",
    "before", "than", "then", "they", "their", "them", "more", "less", "have", "has", "was",
    "were", "been", "will", "would", "could", "there", "here", "like", "just", "case", "women",
    "woman", "people", "thing", "things", "best", "most", "real", "viral", "trending", "post",
    "posts", "video", "videos", "reel", "reels", "facebook", "instagram", "tiktok", "google",
}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", unescape(text or "")).strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def _extract_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in ("views", "likes", "comments", "shares", "saves", "plays"):
        match = re.search(rf"(\d[\d,.]*\s?[kKmM]?)\s*{label}", text, re.IGNORECASE)
        if match:
            counts[label] = _parse_number(match.group(1))
    return counts


def _parse_number(raw: str) -> int:
    clean = raw.strip().replace(",", "").replace(" ", "")
    multiplier = 1
    if clean[-1:] in {"k", "K"}:
        multiplier = 1_000
        clean = clean[:-1]
    elif clean[-1:] in {"m", "M"}:
        multiplier = 1_000_000
        clean = clean[:-1]
    try:
        return int(float(clean) * multiplier)
    except Exception:
        return 0


def _extract_google_result_cards(html_text: str, platform: str, query: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<a[^>]+href="/url\?q=([^"&]+)[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*<h3[^>]*>(.*?)</h3>',
        re.IGNORECASE | re.DOTALL,
    )
    for idx, match in enumerate(pattern.finditer(html_text), start=1):
        if len(results) >= limit:
            break
        url = unquote(match.group(1))
        title = _strip_html(match.group(2))
        tail = html_text[match.end(): match.end() + 700]
        snippet = _strip_html(tail)
        if not title:
            continue
        results.append({
            "platform": platform,
            "source_kind": "google_search",
            "title": title,
            "url": url,
            "author": _guess_author_from_url(url),
            "summary": snippet[:300] or None,
            "published_at": None,
            "rank": idx,
            "query": query,
        })
    return results


def _guess_author_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc.endswith("instagram.com") and parts:
        return parts[0]
    if parsed.netloc.endswith("tiktok.com") and parts:
        return parts[0]
    if parsed.netloc.endswith("facebook.com") and parts:
        return parts[0]
    return parsed.netloc or None


class SocialIntelligenceService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()
        self.brand_service = BrandService(self.supabase)
        self.content_service = ContentIntelligenceService(self.supabase)

    async def run_research(
        self,
        *,
        user_id: str,
        topic: str,
        platforms: list[str] | None = None,
        limit: int = 12,
        language: str = "en",
    ) -> dict[str, Any]:
        platforms = [p for p in (platforms or list(_SOCIAL_PLATFORMS)) if p in _SOCIAL_PLATFORMS]
        if not platforms:
            platforms = list(_SOCIAL_PLATFORMS)

        run = self.supabase.table("social_research_runs").insert({
            "user_id": user_id,
            "topic": topic,
            "platforms": platforms,
        }).execute()
        run_id = run.data[0]["id"] if run.data else ""

        collectors: list[tuple[str, Any]] = []
        for platform in platforms:
            collectors.append((platform, asyncio.ensure_future(self._collect_platform(topic, platform, limit, language))))
        collectors.append(("google_news", asyncio.ensure_future(self._collect_google_news(topic, limit, language))))

        gathered = await asyncio.gather(*(task for _, task in collectors), return_exceptions=True)
        raw_items: list[dict[str, Any]] = []
        for (label, _), result in zip(collectors, gathered, strict=False):
            if isinstance(result, Exception):
                logger.warning("Social research collector failed [%s]: %s", label, result)
                continue
            raw_items.extend(result)

        scored = self._score_and_dedupe(raw_items, topic)
        top_items = scored[:limit]

        if not top_items:
            return {
                "ready": False,
                "run_id": run_id,
                "topic": topic,
                "platforms": platforms,
                "items": [],
                "brief_markdown": "Not enough signal yet.",
                "summary": {},
            }

        saved_items: list[dict[str, Any]] = []
        for item in top_items:
            payload = {
                "user_id": user_id,
                "run_id": run_id,
                "platform": item["platform"],
                "source_kind": item["source_kind"],
                "title": item["title"],
                "url": item.get("url"),
                "author": item.get("author"),
                "summary": item.get("summary"),
                "published_at": item.get("published_at"),
                "viral_score": item.get("viral_score", 0),
                "engagement": item.get("engagement", {}),
                "raw_data": item.get("raw_data", {}),
            }
            result = self.supabase.table("social_research_items").insert(payload).execute()
            saved_items.append(result.data[0] if result.data else payload)

        summary = self._build_summary(topic, saved_items)
        brief_markdown = self._build_research_brief(topic, saved_items, summary)

        return {
            "ready": True,
            "run_id": run_id,
            "topic": topic,
            "platforms": platforms,
            "items": saved_items,
            "brief_markdown": brief_markdown,
            "summary": summary,
        }

    async def generate_ideas(
        self,
        *,
        user_id: str,
        topic: str | None = None,
        research_run_id: str | None = None,
        research_item_id: str | None = None,
        variations: int = 6,
    ) -> dict[str, Any]:
        research_items = await self._load_research_items(user_id=user_id, research_run_id=research_run_id, research_item_id=research_item_id)
        if not research_items and not topic:
            return {
                "ready": False,
                "run_id": None,
                "source_topic": "",
                "variations": [],
                "brief_markdown": "No research items available yet.",
                "summary": {},
            }

        source_topic = topic or research_items[0]["title"]
        run = self.supabase.table("social_idea_runs").insert({
            "user_id": user_id,
            "research_run_id": research_run_id,
            "source_topic": source_topic,
            "variations_count": variations,
        }).execute()
        run_id = run.data[0]["id"] if run.data else ""

        summary = self._build_summary(source_topic, research_items)
        keyword_bank = summary.get("keywords", [])[:10]

        specs = [
            ("Contrarian", "contrarian", "myth-busting", "Flip the obvious belief and open with tension."),
            ("How To", "how-to", "educational", "People save clear steps; it feels actionable fast."),
            ("Proof", "proof", "case-study", "Social proof lowers skepticism and increases trust."),
            ("Checklist", "checklist", "carousel", "Checklists are easy to scan, save, and share."),
            ("Story", "story", "reel", "A human story makes the topic feel real and memorable."),
            ("Opportunity", "opportunity", "post", "Framing the upside gives the audience a reason to act now."),
        ]

        variations_payload: list[dict[str, Any]] = []
        for idx, (label, angle, content_type, reason) in enumerate(specs[:variations]):
            hook = self._build_idea_hook(source_topic, angle, keyword_bank)
            idea_keywords = self._idea_keywords(keyword_bank, label)
            variations_payload.append({
                "user_id": user_id,
                "run_id": run_id,
                "research_item_id": research_items[0].get("id") if research_items else None,
                "source_topic": source_topic,
                "title": f"{source_topic} - {label}",
                "hook": hook,
                "angle": angle,
                "content_type": content_type,
                "slides_suggestion": 6 if content_type == "carousel" else 5,
                "score": round(0.96 - idx * 0.05, 2),
                "why_it_works": f"{reason} Keywords: {', '.join(idea_keywords[:4]) if idea_keywords else source_topic}.",
                "best_hooks": self._build_best_hooks(source_topic, hook, keyword_bank),
                "raw_data": {
                    "research_run_id": research_run_id,
                    "research_item_ids": [row.get("id") for row in research_items[:6]],
                    "keywords": idea_keywords,
                    "signals": summary.get("signals", []),
                },
            })

        saved_variations: list[dict[str, Any]] = []
        for payload in variations_payload:
            result = self.supabase.table("social_idea_variations").insert(payload).execute()
            saved_variations.append(result.data[0] if result.data else payload)

        brief_markdown = self._build_ideation_brief(source_topic, saved_variations, summary)
        return {
            "ready": True,
            "run_id": run_id,
            "source_topic": source_topic,
            "variations": saved_variations,
            "brief_markdown": brief_markdown,
            "summary": summary,
        }

    async def generate_script(
        self,
        *,
        user_id: str,
        topic: str | None = None,
        research_run_id: str | None = None,
        idea_variation_id: str | None = None,
        selected_hook: str | None = None,
    ) -> dict[str, Any]:
        idea = None
        if idea_variation_id:
            result = self.supabase.table("social_idea_variations").select("*").eq("user_id", user_id).eq("id", idea_variation_id).maybe_single().execute()
            idea = result.data or None

        research_items = await self._load_research_items(user_id=user_id, research_run_id=research_run_id)
        source_topic = topic or (idea.get("source_topic") if idea else None) or (research_items[0]["title"] if research_items else "topic")
        hook = selected_hook or (idea.get("hook") if idea else None) or self._build_idea_hook(source_topic, "how-to", [])

        script_run = self.supabase.table("social_script_runs").insert({
            "user_id": user_id,
            "research_run_id": research_run_id,
            "idea_variation_id": idea.get("id") if idea else None,
            "source_topic": source_topic,
            "selected_hook": hook,
        }).execute()
        run_id = script_run.data[0]["id"] if script_run.data else ""

        brand_profile = await self._load_brand_profile(user_id)
        tone = brand_profile.get("brand_voice") or "clear and warm"
        keywords = self._extract_keywords_from_items(research_items)[:8]
        hook_pack = self._build_hook_pack(source_topic, hook, keywords)
        content_type = idea.get("content_type") if idea else "reel"

        script_body, filming_card, caption, cta, recording_instructions = self._build_script_assets(
            source_topic=source_topic,
            hook=hook,
            content_type=content_type,
            tone=tone,
            keywords=keywords,
            brand_profile=brand_profile,
            research_items=research_items,
        )

        payload = {
            "user_id": user_id,
            "run_id": run_id,
            "idea_variation_id": idea.get("id") if idea else None,
            "source_topic": source_topic,
            "selected_hook": hook,
            "hook_pack": hook_pack,
            "script_body": script_body,
            "filming_card": filming_card,
            "caption": caption,
            "cta": cta,
            "recording_instructions": recording_instructions,
            "raw_data": {
                "tone": tone,
                "keywords": keywords,
                "content_type": content_type,
                "research_run_id": research_run_id,
            },
        }
        result = self.supabase.table("social_scripts").insert(payload).execute()
        saved = result.data[0] if result.data else payload

        return {
            "ready": True,
            "run_id": run_id,
            "source_topic": source_topic,
            "selected_hook": hook,
            "hook_pack": hook_pack,
            "script_body": script_body,
            "filming_card": filming_card,
            "caption": caption,
            "cta": cta,
            "recording_instructions": recording_instructions,
            "raw_data": saved.get("raw_data", {}),
        }

    async def compare_accounts(
        self,
        *,
        user_id: str,
        own_handle: str,
        competitor_handles: list[str],
        platform: str = "instagram",
        window_days: int = 30,
        force_recompute: bool = False,
    ) -> dict[str, Any]:
        if platform != "instagram":
            return {
                "ready": False,
                "reason": "only_instagram_auto_scrape_supported",
                "platform": platform,
                "own_handle": own_handle,
                "competitor_handles": competitor_handles,
            }

        scraper = InstagramScraper()
        await self._ensure_instagram_account(user_id, own_handle, account_type="own", scraper=scraper)
        for handle in competitor_handles:
            await self._ensure_instagram_account(user_id, handle, account_type="competitor", scraper=scraper)

        return CompetitorService(self.supabase).compare_accounts(
            user_id=user_id,
            own_handle=own_handle,
            competitor_handles=competitor_handles,
            window_days=window_days,
            force_recompute=force_recompute,
        ).model_dump()

    async def list_latest_research(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        result = (
            self.supabase.table("social_research_runs")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def list_latest_ideas(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        result = (
            self.supabase.table("social_idea_variations")
            .select("*")
            .eq("user_id", user_id)
            .order("score", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def list_latest_scripts(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        result = (
            self.supabase.table("social_scripts")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def _collect_platform(self, topic: str, platform: str, limit: int, language: str) -> list[dict[str, Any]]:
        query = self._platform_query(topic, platform)
        html_text = await self._search_google(query, language=language, limit=limit)
        items = _extract_google_result_cards(html_text, platform, query, limit)
        return await self._enrich_items(items)

    async def _collect_google_news(self, topic: str, limit: int, language: str) -> list[dict[str, Any]]:
        params = {
            "q": topic,
            "hl": f"{language}-US" if len(language) == 2 else language,
            "gl": "US",
            "ceid": "US:en",
        }
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": _SEARCH_USER_AGENT}) as client:
            resp = await client.get("https://news.google.com/rss/search", params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)

        items: list[dict[str, Any]] = []
        for idx, node in enumerate(root.findall(".//item")[:limit], start=1):
            title_el = node.find("title")
            link_el = node.find("link")
            pub_el = node.find("pubDate")
            if title_el is None or not title_el.text:
                continue
            title = _normalize_text(title_el.text)
            link = _normalize_text(link_el.text) if link_el is not None and link_el.text else None
            published_at = None
            if pub_el is not None and pub_el.text:
                published_at = self._parse_rss_date(pub_el.text)
            items.append({
                "platform": "google",
                "source_kind": "google_news",
                "title": title,
                "url": link,
                "author": _guess_author_from_url(link),
                "summary": "Google News",
                "published_at": published_at,
                "rank": idx,
                "query": topic,
            })
        return await self._enrich_items(items)

    async def _enrich_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": _SEARCH_USER_AGENT}) as client:
            for item in items:
                url = item.get("url")
                page_meta: dict[str, Any] = {}
                if url and len(enriched) < 6:
                    try:
                        resp = await client.get(url, follow_redirects=True)
                        if resp.status_code < 400 and resp.text:
                            page_meta = self._extract_page_meta(resp.text)
                    except Exception:
                        page_meta = {}
                combined = {**item}
                if page_meta:
                    combined["summary"] = combined.get("summary") or page_meta.get("description")
                    combined["author"] = combined.get("author") or page_meta.get("author")
                combined["engagement"] = self._build_engagement_signals(combined, page_meta)
                combined["viral_score"] = self._score_item(combined, page_meta)
                combined["raw_data"] = {
                    "query": combined.get("query"),
                    "page_meta": page_meta,
                    "search_rank": combined.get("rank"),
                }
                enriched.append(combined)
        return enriched

    async def _search_google(self, query: str, language: str, limit: int) -> str:
        params = {
            "q": query,
            "num": max(10, limit),
            "hl": language,
            "gl": "us",
            "gbv": 1,
            "pws": 0,
        }
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": _SEARCH_USER_AGENT}) as client:
            resp = await client.get("https://www.google.com/search", params=params)
            resp.raise_for_status()
            return resp.text

    def _platform_query(self, topic: str, platform: str) -> str:
        if platform == "google":
            return f"{topic} viral trending"
        return f'site:{platform}.com {topic}'

    def _extract_page_meta(self, html_text: str) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for key in ("title", "description", "author"):
            match = re.search(rf'<meta[^>]+property="og:{key}"[^>]+content="([^"]+)"', html_text, re.IGNORECASE)
            if not match:
                match = re.search(rf'<meta[^>]+name="{key}"[^>]+content="([^"]+)"', html_text, re.IGNORECASE)
            if match:
                meta[key] = _normalize_text(match.group(1))
        for key in ("likeCount", "commentCount", "playCount", "viewCount", "interactionCount"):
            match = re.search(rf'"{key}"\s*:\s*(\d+)', html_text)
            if match:
                meta[key] = int(match.group(1))
        return meta

    def _build_engagement_signals(self, item: dict[str, Any], page_meta: dict[str, Any]) -> dict[str, Any]:
        summary = f"{item.get('title') or ''} {item.get('summary') or ''} {json.dumps(page_meta or {})}"
        signals = _extract_counts(summary)
        return {
            **signals,
            "rank": item.get("rank"),
            "search_platform": item.get("platform"),
        }

    def _score_item(self, item: dict[str, Any], page_meta: dict[str, Any]) -> float:
        text = f"{item.get('title', '')} {item.get('summary', '')} {json.dumps(page_meta or {})}".lower()
        score = 0.25
        if item.get("platform") in {"instagram", "tiktok", "facebook"}:
            score += 0.15
        if any(token in text for token in ("viral", "trending", "how to", "why", "stop", "secret", "vs", "best")):
            score += 0.2
        counts = _extract_counts(text)
        if counts:
            score += min(sum(counts.values()) / 1_000_000, 0.25)
        if item.get("rank"):
            score += max(0, 0.2 - (int(item["rank"]) - 1) * 0.03)
        topic_tokens = _tokenize(item.get("query") or "")
        if topic_tokens:
            matches = sum(1 for t in topic_tokens if t in text)
            score += min(matches * 0.04, 0.2)
        return round(min(score, 1.0), 2)

    def _score_and_dedupe(self, items: list[dict[str, Any]], topic: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        scored: list[dict[str, Any]] = []
        topic_tokens = _tokenize(topic)
        for item in items:
            url = item.get("url") or ""
            key = url or f"{item.get('platform')}::{item.get('title')}"
            if key in seen:
                continue
            seen.add(key)
            title = item.get("title") or ""
            summary = item.get("summary") or ""
            keyword_hits = sum(1 for token in topic_tokens if token in f"{title} {summary}".lower())
            item["viral_score"] = round(min(1.0, float(item.get("viral_score", 0)) + keyword_hits * 0.06), 2)
            scored.append(item)
        scored.sort(key=lambda row: (row.get("viral_score", 0), row.get("rank", 999)), reverse=True)
        return scored

    def _build_summary(self, topic: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        platform_counts = Counter(item.get("platform") for item in items if item.get("platform"))
        keyword_counts = Counter()
        hook_counts = Counter()
        for item in items:
            keyword_counts.update(_tokenize(f"{item.get('title', '')} {item.get('summary', '')}"))
            title = (item.get("title") or "").lower()
            if title.startswith(("how to", "how", "guide")):
                hook_counts["how_to"] += 1
            if "?" in title:
                hook_counts["question"] += 1
            if any(token in title for token in ("stop", "why", "vs", "secret", "truth", "myth")):
                hook_counts["contrarian"] += 1

        top_keywords = [word for word, _ in keyword_counts.most_common(12)]
        best_hooks = [
            f"Why {topic} matters now",
            f"What nobody tells you about {topic}",
            f"How to talk about {topic} in a way people save",
        ]
        return {
            "topic": topic,
            "platforms": dict(platform_counts),
            "keywords": top_keywords,
            "signals": dict(hook_counts),
            "best_hooks": best_hooks,
        }

    def _build_research_brief(self, topic: str, items: list[dict[str, Any]], summary: dict[str, Any]) -> str:
        lines = [
            "# Social Research Brief",
            "",
            f"- Topic: {topic}",
            f"- Items analyzed: {len(items)}",
            f"- Platform mix: {', '.join(summary.get('platforms', {}).keys()) or 'n/a'}",
            "",
            "## Top Signals",
        ]
        for keyword in summary.get("keywords", [])[:8]:
            lines.append(f"- {keyword}")
        lines.extend(["", "## Best Hooks"])
        for hook in summary.get("best_hooks", []):
            lines.append(f"- {hook}")
        lines.extend(["", "## Top Items"])
        for item in items[:6]:
            lines.append(f"- [{item.get('platform')}] {item.get('title')} (score {item.get('viral_score', 0)})")
        return "\n".join(lines)

    def _build_ideation_brief(self, topic: str, variations: list[dict[str, Any]], summary: dict[str, Any]) -> str:
        lines = [
            "# Social Ideation Brief",
            "",
            f"- Topic: {topic}",
            f"- Ideas generated: {len(variations)}",
            "",
            "## Keyword Bank",
        ]
        for kw in summary.get("keywords", [])[:10]:
            lines.append(f"- {kw}")
        lines.extend(["", "## Idea Hooks"])
        for item in variations:
            lines.append(f"- {item['hook']}")
        return "\n".join(lines)

    def _build_idea_hook(self, topic: str, angle: str, keywords: list[str]) -> str:
        keyword = keywords[0] if keywords else topic
        if angle == "contrarian":
            return f"Stop treating {keyword} like a generic topic"
        if angle == "how-to":
            return f"How to turn {keyword} into content people save"
        if angle == "proof":
            return f"What the best {keyword} posts are doing right now"
        if angle == "checklist":
            return f"5 signs your {keyword} angle is ready to post"
        if angle == "story":
            return f"I kept seeing the same thing around {keyword}"
        return f"The smartest move for {keyword} right now"

    def _idea_keywords(self, keywords: list[str], label: str) -> list[str]:
        return [label.lower(), *keywords[:5]]

    def _build_best_hooks(self, topic: str, hook: str, keywords: list[str]) -> list[str]:
        alt = keywords[0] if keywords else topic
        return [
            hook,
            f"Why {alt} is showing up everywhere",
            f"The real reason people click on {alt}",
            f"If you're posting about {alt}, start here",
        ]

    def _build_hook_pack(self, topic: str, hook: str, keywords: list[str]) -> list[str]:
        main = keywords[0] if keywords else topic
        return [
            hook,
            f"Why {main} keeps getting attention",
            f"The mistake people make with {main}",
            f"How to explain {main} without losing attention",
            f"What to say first when talking about {main}",
        ]

    def _build_script_assets(
        self,
        *,
        source_topic: str,
        hook: str,
        content_type: str,
        tone: str,
        keywords: list[str],
        brand_profile: dict[str, Any],
        research_items: list[dict[str, Any]],
    ) -> tuple[str, str, str, str, str]:
        kw = keywords[0] if keywords else source_topic
        secondary = keywords[1] if len(keywords) > 1 else kw
        cta = brand_profile.get("cta") or "Follow for the next part"
        caption_words = ", ".join(keywords[:4]) if keywords else source_topic

        if content_type == "carousel":
            script_body = "\n".join([
                f"Slide 1: {hook}",
                f"Slide 2: Why {kw} matters now.",
                f"Slide 3: The pattern we keep seeing across the research.",
                f"Slide 4: Why {secondary} changes the angle.",
                f"Slide 5: What to do next.",
                f"Slide 6: {cta}",
            ])
            filming_card = "\n".join([
                "Format: carousel",
                f"Tone: {tone}",
                "Keep each slide short and saveable.",
                "Use bold opening text and one clear idea per slide.",
            ])
            recording_instructions = "Build the carousel from a single promise, then stack the proof and CTA."
        else:
            script_body = "\n".join([
                f"Hook: {hook}",
                f"1) Say why {kw} is relevant now.",
                f"2) Show the pattern from the research: {secondary}.",
                "3) Give one clear action the viewer can use today.",
                f"4) Close with: {cta}",
            ])
            filming_card = "\n".join([
                f"Format: {content_type}",
                f"Tone: {tone}",
                "Open with eye contact and a fast first sentence.",
                "Use one visual example per point.",
            ])
            recording_instructions = "Speak like you're helping a client make a fast decision. No fluff."

        caption = f"{hook}\n\n{source_topic}.\n\nUse this if you want to save time, avoid guesswork, and post with intention. #" + " #".join([w.replace(" ", "") for w in keywords[:4]] or [caption_words.replace(" ", "")])
        return script_body, filming_card, caption, cta, recording_instructions

    async def _load_research_items(
        self,
        *,
        user_id: str,
        research_run_id: str | None = None,
        research_item_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = self.supabase.table("social_research_items").select("*").eq("user_id", user_id).order("created_at", desc=True)
        if research_item_id:
            query = query.eq("id", research_item_id)
        elif research_run_id:
            query = query.eq("run_id", research_run_id)
        result = query.limit(12).execute()
        return result.data or []

    async def _load_brand_profile(self, user_id: str) -> dict[str, Any]:
        try:
            return await self.brand_service.load_profile(user_id)
        except Exception:
            return {}

    def _extract_keywords_from_items(self, items: list[dict[str, Any]]) -> list[str]:
        counts = Counter()
        for item in items:
            counts.update(_tokenize(f"{item.get('title', '')} {item.get('summary', '')}"))
        return [word for word, _ in counts.most_common()]

    async def _ensure_instagram_account(self, user_id: str, handle: str, account_type: str, scraper: InstagramScraper) -> None:
        normalized = handle.lstrip("@").strip()
        existing = (
            self.supabase.table("content_accounts")
            .select("id")
            .eq("user_id", user_id)
            .eq("handle", normalized)
            .eq("platform", "instagram")
            .maybe_single()
            .execute()
        )
        if existing.data:
            return

        profile, posts = await scraper.scrape(normalized, max_posts=20)
        await self.content_service.store_scrape(
            user_id=user_id,
            handle=normalized,
            platform="instagram",
            account_type=account_type,
            display_name=profile.get("full_name") or normalized,
            metadata={
                "followers": profile.get("followers", 0),
                "following": profile.get("following", 0),
                "is_verified": profile.get("is_verified", False),
            },
            posts=[
                {
                    "id": post.get("id", ""),
                    "caption": post.get("caption", ""),
                    "posted_at": datetime.fromtimestamp(post.get("timestamp", 0), tz=timezone.utc).isoformat() if post.get("timestamp") else None,
                    "media_type": "reel" if post.get("media_type") == 2 else "carousel" if post.get("is_carousel") else "post",
                    "likes": post.get("likes", 0),
                    "comments": post.get("comments", 0),
                    "raw_data": post,
                    "analysis_status": "pending",
                }
                for post in posts
                if post.get("id")
            ],
        )

    def _parse_rss_date(self, raw: str) -> str | None:
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(raw)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return None
