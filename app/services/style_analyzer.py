"""Pure-Python Instagram style analyzer — 15 analysis modules with cross-analysis."""

from __future__ import annotations

import math
import re
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import stdev

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────

HOOK_PATTERNS = {
    "question": re.compile(r"^[^.!]{5,}\?", re.IGNORECASE),
    "number": re.compile(r"^\d"),
    "bold_claim": re.compile(
        r"^(stop|never|don't|you're wrong|the truth|most people|nobody|everyone)",
        re.IGNORECASE,
    ),
    "story": re.compile(
        r"^(i was|when i|last|one day|picture this|imagine|remember)",
        re.IGNORECASE,
    ),
    "you_address": re.compile(r"^you\b", re.IGNORECASE),
    "list": re.compile(r"^\d+[.)]\s"),
}

CTA_PATTERNS = {
    "dm_me": re.compile(r"(?:dm|message)\s+(?:me|us)", re.IGNORECASE),
    "link_in_bio": re.compile(r"link\s+in\s+(?:bio|profile)", re.IGNORECASE),
    "comment": re.compile(r"(?:comment|drop)\s+(?:below|a|your)", re.IGNORECASE),
    "save": re.compile(r"save\s+this", re.IGNORECASE),
    "follow": re.compile(r"follow\s+(?:me|us|for)", re.IGNORECASE),
    "share": re.compile(r"(?:share|send)\s+(?:this|to)", re.IGNORECASE),
    "tag": re.compile(r"tag\s+(?:someone|a\s+friend)", re.IGNORECASE),
}

CONTENT_CATEGORIES = {
    "educational": [
        "tips", "how to", "guide", "learn", "step", "strategy", "method", "ways to", "mistake",
    ],
    "promotional": [
        "offer", "discount", "sale", "link", "book", "call", "dm me", "limited", "free",
    ],
    "personal": [
        "my story", "i was", "journey", "behind the scenes", "real talk", "honest", "personal",
    ],
    "motivational": [
        "believe", "growth", "mindset", "success", "never give up", "hustle", "grind", "dream",
    ],
    "myth_busting": [
        "myth", "truth", "wrong", "actually", "misconception", "lie", "debunk", "stop believing",
    ],
    "social_proof": [
        "client", "testimonial", "result", "transformation", "before", "after", "review",
    ],
}

BROAD_HASHTAGS = {
    "love", "instagood", "photooftheday", "fashion", "beautiful", "happy", "cute",
    "like4like", "followme", "picoftheday", "follow", "selfie", "me", "art",
    "instadaily", "friends", "repost", "nature", "girl", "fun", "style", "smile",
    "food", "instalike", "likeforlike", "family", "travel", "fitness", "motivation",
    "life", "beauty", "photo", "amazing", "lifestyle", "music", "sunset",
}

EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FA6F"
    r"\U0001FA70-\U0001FAFF\U00002702-\U000027B0]"
)


def _parse_post_date(post: dict) -> datetime | None:
    """Parse post date from either 'posted_at' (ISO) or 'timestamp' (epoch)."""
    # Prefer posted_at (ISO string) — used by instaloader + Apify providers
    posted_at = post.get("posted_at")
    if posted_at:
        try:
            dt = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except (ValueError, TypeError):
            pass

    # Fallback: epoch timestamp
    ts = post.get("timestamp", 0)
    if ts:
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (ValueError, OSError, TypeError):
            pass

    return None


class StyleAnalyzer:
    """Analyse a list of Instagram posts and return structured style metrics."""

    def analyze(self, posts: list[dict], profile_data: dict) -> dict:
        captions = [p["caption"] for p in posts if p.get("caption")]
        followers = profile_data.get("followers", 0)

        result: dict = {}

        # Original 8 modules
        result.update(self._analyze_captions(captions))
        result.update(self._analyze_hooks(captions))
        result.update(self._analyze_hashtags(captions))
        result.update(self._analyze_engagement(posts, followers))
        result.update(self._analyze_posting_patterns(posts))
        result.update(self._analyze_emojis(captions))
        result.update(self._analyze_ctas(captions))
        result.update(self._extract_themes(captions))

        # New cross-analysis modules
        result.update(self._analyze_profile_stats(profile_data, posts))
        result.update(self._analyze_content_type_performance(posts))
        result.update(self._analyze_engagement_depth(posts))
        result.update(self._analyze_caption_optimization(posts))
        result.update(self._analyze_hashtag_performance(posts))
        result.update(self._analyze_consistency_score(posts))
        result.update(self._analyze_top_posts(posts))

        return result

    # ── 1. Caption stats ──────────────────────────────────────────

    def _analyze_captions(self, captions: list[str]) -> dict:
        if not captions:
            return {"caption_avg_length": 0, "caption_avg_sentences": 0, "caption_length_distribution": {}}

        clean = [re.sub(r"#\w+", "", c).strip() for c in captions]
        word_counts = [len(c.split()) for c in clean]
        sentence_counts = [len(re.split(r"[.!?]+", c)) for c in clean]

        avg_len = sum(word_counts) / len(word_counts)
        n = len(word_counts)
        short = sum(1 for w in word_counts if w < 50) / n
        medium = sum(1 for w in word_counts if 50 <= w <= 100) / n
        long = sum(1 for w in word_counts if w > 100) / n

        return {
            "caption_avg_length": round(avg_len, 1),
            "caption_avg_sentences": round(sum(sentence_counts) / len(sentence_counts), 1),
            "caption_length_distribution": {
                "short": round(short, 2),
                "medium": round(medium, 2),
                "long": round(long, 2),
            },
        }

    # ── 2. Hook analysis ─────────────────────────────────────────

    def _analyze_hooks(self, captions: list[str]) -> dict:
        if not captions:
            return {"hook_types": {}, "hook_first_person_rate": 0, "hook_second_person_rate": 0}

        first_lines = [c.split("\n")[0].strip() for c in captions if c.strip()]
        hook_counts: Counter = Counter()
        first_person = 0
        second_person = 0

        for line in first_lines:
            if not line:
                continue
            for hook_type, pattern in HOOK_PATTERNS.items():
                if pattern.search(line):
                    hook_counts[hook_type] += 1
            if re.match(r"^I\b", line):
                first_person += 1
            if re.match(r"^You\b", line, re.IGNORECASE):
                second_person += 1

        total = len(first_lines) or 1
        return {
            "hook_types": {k: round(v / total, 2) for k, v in hook_counts.most_common(6)},
            "hook_first_person_rate": round(first_person / total, 2),
            "hook_second_person_rate": round(second_person / total, 2),
        }

    # ── 3. Hashtag analysis ──────────────────────────────────────

    def _analyze_hashtags(self, captions: list[str]) -> dict:
        if not captions:
            return {"hashtag_avg_count": 0, "hashtag_top_20": [], "hashtag_niche_vs_broad": {}}

        all_hashtags: list[str] = []
        counts_per_post: list[int] = []

        for caption in captions:
            tags = re.findall(r"#(\w+)", caption.lower())
            all_hashtags.extend(tags)
            counts_per_post.append(len(tags))

        counter = Counter(all_hashtags)
        top_20 = [tag for tag, _ in counter.most_common(20)]

        broad_count = sum(1 for tag in all_hashtags if tag in BROAD_HASHTAGS)
        total_tags = len(all_hashtags) or 1

        return {
            "hashtag_avg_count": round(sum(counts_per_post) / len(counts_per_post), 1) if counts_per_post else 0,
            "hashtag_top_20": top_20,
            "hashtag_niche_vs_broad": {
                "niche": round(1 - broad_count / total_tags, 2),
                "broad": round(broad_count / total_tags, 2),
            },
        }

    # ── 4. Engagement analysis ───────────────────────────────────

    def _analyze_engagement(self, posts: list[dict], followers: int) -> dict:
        if not posts:
            return {"avg_likes": 0, "avg_comments": 0, "engagement_rate": 0, "top_performing_posts": []}

        likes = [p.get("likes", 0) for p in posts]
        comments = [p.get("comments", 0) for p in posts]

        avg_likes = sum(likes) / len(likes)
        avg_comments = sum(comments) / len(comments)
        engagement_rate = (avg_likes + avg_comments) / max(followers, 1)

        scored = sorted(posts, key=lambda p: p.get("likes", 0) + p.get("comments", 0), reverse=True)
        top_3 = [
            {
                "caption_preview": (p.get("caption", "")[:100] + "...") if len(p.get("caption", "")) > 100 else p.get("caption", ""),
                "likes": p.get("likes", 0),
                "comments": p.get("comments", 0),
                "engagement": p.get("likes", 0) + p.get("comments", 0),
            }
            for p in scored[:3]
        ]

        return {
            "avg_likes": round(avg_likes, 1),
            "avg_comments": round(avg_comments, 1),
            "engagement_rate": round(engagement_rate, 4),
            "top_performing_posts": top_3,
        }

    # ── 5. Posting patterns ──────────────────────────────────────

    def _analyze_posting_patterns(self, posts: list[dict]) -> dict:
        if not posts:
            return {"posts_per_week": 0, "best_days": [], "best_hours": []}

        dates = [_parse_post_date(p) for p in posts]
        dates = [d for d in dates if d is not None]

        if len(dates) < 2:
            return {"posts_per_week": 0, "best_days": [], "best_hours": []}

        date_range = (max(dates) - min(dates)).days or 1
        posts_per_week = round(len(dates) / (date_range / 7), 1)

        day_counts: Counter = Counter(d.strftime("%A") for d in dates)
        best_days = [day for day, _ in day_counts.most_common(3)]

        hour_counts: Counter = Counter(d.hour for d in dates)
        best_hours = [hour for hour, _ in hour_counts.most_common(3)]

        return {
            "posts_per_week": posts_per_week,
            "best_days": best_days,
            "best_hours": sorted(best_hours),
        }

    # ── 6. Emoji analysis ────────────────────────────────────────

    def _analyze_emojis(self, captions: list[str]) -> dict:
        if not captions:
            return {"emoji_frequency": 0, "top_emojis": [], "emoji_position": {}}

        all_emojis: list[str] = []
        positions = {"start": 0, "middle": 0, "end": 0}

        for caption in captions:
            emojis = EMOJI_PATTERN.findall(caption)
            all_emojis.extend(emojis)

            if emojis and caption:
                third = len(caption) // 3
                for match in EMOJI_PATTERN.finditer(caption):
                    pos = match.start()
                    if pos < third:
                        positions["start"] += 1
                    elif pos < third * 2:
                        positions["middle"] += 1
                    else:
                        positions["end"] += 1

        total_emojis = len(all_emojis) or 1
        counter = Counter(all_emojis)

        return {
            "emoji_frequency": round(len(all_emojis) / len(captions), 2),
            "top_emojis": [e for e, _ in counter.most_common(10)],
            "emoji_position": {k: round(v / total_emojis, 2) for k, v in positions.items()},
        }

    # ── 7. CTA analysis ─────────────────────────────────────────

    def _analyze_ctas(self, captions: list[str]) -> dict:
        if not captions:
            return {"cta_rate": 0, "cta_types": {}}

        cta_counts: Counter = Counter()
        posts_with_cta = 0

        for caption in captions:
            found = False
            for cta_type, pattern in CTA_PATTERNS.items():
                if pattern.search(caption):
                    cta_counts[cta_type] += 1
                    found = True
            if found:
                posts_with_cta += 1

        total = len(captions)
        total_ctas = sum(cta_counts.values()) or 1

        return {
            "cta_rate": round(posts_with_cta / total, 2),
            "cta_types": {k: round(v / total_ctas, 2) for k, v in cta_counts.most_common(7)},
        }

    # ── 8. Content themes (simple TF-IDF) ────────────────────────

    def _extract_themes(self, captions: list[str]) -> dict:
        if not captions:
            return {"top_keywords": [], "content_categories": {}}

        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "dare", "ought",
            "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "up", "about", "into", "over", "after", "and", "but", "or", "nor",
            "not", "so", "yet", "both", "either", "neither", "each", "every",
            "all", "any", "few", "more", "most", "other", "some", "such", "no",
            "than", "too", "very", "just", "because", "as", "until", "while",
            "it", "its", "this", "that", "these", "those", "i", "me", "my",
            "we", "our", "you", "your", "he", "she", "they", "them", "their",
            "what", "which", "who", "whom", "how", "when", "where", "why",
        }

        doc_words: list[list[str]] = []
        for caption in captions:
            clean = re.sub(r"#\w+|https?://\S+|@\w+", "", caption.lower())
            words = re.findall(r"\b[a-z]{3,}\b", clean)
            doc_words.append([w for w in words if w not in stop_words])

        word_doc_count: Counter = Counter()
        word_total_count: Counter = Counter()
        for words in doc_words:
            word_total_count.update(words)
            word_doc_count.update(set(words))

        n_docs = len(doc_words)
        total_words = sum(word_total_count.values()) or 1
        tfidf_scores: dict[str, float] = {}
        for word, count in word_total_count.items():
            tf = count / total_words
            idf = math.log(n_docs / (word_doc_count[word] + 1))
            tfidf_scores[word] = round(tf * idf, 4)

        top_keywords = [
            {"word": w, "score": s}
            for w, s in sorted(tfidf_scores.items(), key=lambda x: -x[1])[:20]
        ]

        # Content categorisation
        category_scores: dict[str, int] = {}
        all_text = " ".join(c.lower() for c in captions)
        for category, keywords in CONTENT_CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in all_text)
            category_scores[category] = score

        total_score = sum(category_scores.values()) or 1
        content_categories = {
            k: round(v / total_score, 2)
            for k, v in sorted(category_scores.items(), key=lambda x: -x[1])
        }

        return {
            "top_keywords": top_keywords,
            "content_categories": content_categories,
        }

    # ── 9. Profile stats (new) ───────────────────────────────────

    def _analyze_profile_stats(self, profile_data: dict, posts: list[dict]) -> dict:
        followers = int(profile_data.get("followers", 0) or 0)
        following = int(profile_data.get("following", 0) or profile_data.get("followees", 0) or 0)
        total_posts = int(profile_data.get("posts_count", 0) or profile_data.get("mediacount", 0) or len(posts))

        ratio = round(followers / max(following, 1), 2)

        # Estimate activity: avg days between posts
        dates = [_parse_post_date(p) for p in posts]
        dates_sorted = sorted([d for d in dates if d is not None])
        avg_days_between = None
        if len(dates_sorted) >= 2:
            gaps = [(dates_sorted[i + 1] - dates_sorted[i]).days for i in range(len(dates_sorted) - 1)]
            avg_days_between = round(sum(gaps) / len(gaps), 1)

        return {
            "profile_followers": followers,
            "profile_following": following,
            "profile_followers_following_ratio": ratio,
            "profile_total_posts": total_posts,
            "profile_is_verified": bool(profile_data.get("is_verified", False)),
            "profile_biography": profile_data.get("biography", "") or "",
            "profile_avg_days_between_posts": avg_days_between,
        }

    # ── 10. Content type performance (new) ───────────────────────

    def _analyze_content_type_performance(self, posts: list[dict]) -> dict:
        if not posts:
            return {"content_type_performance": {}, "best_content_type": None}

        by_type: dict[str, list[dict]] = defaultdict(list)
        for p in posts:
            ct = p.get("content_type") or p.get("media_type") or "photo"
            by_type[ct].append(p)

        performance: dict[str, dict] = {}
        for ct, ct_posts in by_type.items():
            likes = [p.get("likes", 0) for p in ct_posts]
            comments = [p.get("comments", 0) for p in ct_posts]
            views = [p.get("views", 0) for p in ct_posts]
            total_engagement = [l + c for l, c in zip(likes, comments)]
            performance[ct] = {
                "count": len(ct_posts),
                "share": round(len(ct_posts) / len(posts), 2),
                "avg_likes": round(sum(likes) / len(likes), 1),
                "avg_comments": round(sum(comments) / len(comments), 1),
                "avg_views": round(sum(views) / len(views), 1),
                "avg_engagement": round(sum(total_engagement) / len(total_engagement), 1),
            }

        best_ct = max(performance, key=lambda ct: performance[ct]["avg_engagement"]) if performance else None

        return {
            "content_type_performance": performance,
            "best_content_type": best_ct,
        }

    # ── 11. Engagement depth (new) ───────────────────────────────

    def _analyze_engagement_depth(self, posts: list[dict]) -> dict:
        if not posts:
            return {
                "comments_to_likes_ratio": 0,
                "conversation_score": "low",
                "viral_outliers": [],
            }

        engagement_scores = [p.get("likes", 0) + p.get("comments", 0) for p in posts]
        avg_engagement = sum(engagement_scores) / len(engagement_scores)
        std_engagement = stdev(engagement_scores) if len(engagement_scores) > 1 else 0

        # Viral outliers: posts with engagement > avg + 2*std
        threshold = avg_engagement + 2 * std_engagement
        outliers = [
            {
                "caption_preview": (p.get("caption", "")[:80] + "...") if len(p.get("caption", "")) > 80 else p.get("caption", ""),
                "content_type": p.get("content_type", "photo"),
                "likes": p.get("likes", 0),
                "comments": p.get("comments", 0),
                "engagement": p.get("likes", 0) + p.get("comments", 0),
                "multiplier": round((p.get("likes", 0) + p.get("comments", 0)) / max(avg_engagement, 1), 1),
            }
            for p in posts
            if (p.get("likes", 0) + p.get("comments", 0)) > threshold
        ]
        outliers.sort(key=lambda x: x["engagement"], reverse=True)

        # Comments-to-likes ratio — higher = more conversation-driven
        total_likes = sum(p.get("likes", 0) for p in posts)
        total_comments = sum(p.get("comments", 0) for p in posts)
        ratio = round(total_comments / max(total_likes, 1), 4)

        # Conversation score label
        if ratio >= 0.1:
            conv_score = "high"
        elif ratio >= 0.04:
            conv_score = "medium"
        else:
            conv_score = "low"

        return {
            "comments_to_likes_ratio": ratio,
            "conversation_score": conv_score,
            "viral_outliers": outliers[:5],
        }

    # ── 12. Caption length optimization (new) ────────────────────

    def _analyze_caption_optimization(self, posts: list[dict]) -> dict:
        """Correlate caption length bucket with avg engagement."""
        if not posts:
            return {"caption_length_vs_engagement": {}, "optimal_caption_length": None}

        buckets: dict[str, list[int]] = {
            "micro (0-20 words)": [],
            "short (21-50 words)": [],
            "medium (51-100 words)": [],
            "long (101-200 words)": [],
            "very long (200+ words)": [],
        }

        for p in posts:
            caption = p.get("caption", "") or ""
            clean = re.sub(r"#\w+", "", caption).strip()
            word_count = len(clean.split())
            engagement = p.get("likes", 0) + p.get("comments", 0)

            if word_count <= 20:
                buckets["micro (0-20 words)"].append(engagement)
            elif word_count <= 50:
                buckets["short (21-50 words)"].append(engagement)
            elif word_count <= 100:
                buckets["medium (51-100 words)"].append(engagement)
            elif word_count <= 200:
                buckets["long (101-200 words)"].append(engagement)
            else:
                buckets["very long (200+ words)"].append(engagement)

        result: dict[str, dict] = {}
        best_bucket = None
        best_avg = -1

        for bucket, engagements in buckets.items():
            if engagements:
                avg = round(sum(engagements) / len(engagements), 1)
                result[bucket] = {"count": len(engagements), "avg_engagement": avg}
                if avg > best_avg:
                    best_avg = avg
                    best_bucket = bucket

        return {
            "caption_length_vs_engagement": result,
            "optimal_caption_length": best_bucket,
        }

    # ── 13. Hashtag count performance (new) ──────────────────────

    def _analyze_hashtag_performance(self, posts: list[dict]) -> dict:
        """Compare engagement across hashtag count groups."""
        if not posts:
            return {"hashtag_count_vs_engagement": {}, "optimal_hashtag_count": None}

        groups: dict[str, list[int]] = {
            "0 hashtags": [],
            "1–5 hashtags": [],
            "6–15 hashtags": [],
            "16–30 hashtags": [],
        }

        for p in posts:
            caption = p.get("caption", "") or ""
            tag_count = len(re.findall(r"#\w+", caption))
            engagement = p.get("likes", 0) + p.get("comments", 0)

            if tag_count == 0:
                groups["0 hashtags"].append(engagement)
            elif tag_count <= 5:
                groups["1–5 hashtags"].append(engagement)
            elif tag_count <= 15:
                groups["6–15 hashtags"].append(engagement)
            else:
                groups["16–30 hashtags"].append(engagement)

        result: dict[str, dict] = {}
        best_group = None
        best_avg = -1

        for group, engagements in groups.items():
            if engagements:
                avg = round(sum(engagements) / len(engagements), 1)
                result[group] = {"count": len(engagements), "avg_engagement": avg}
                if avg > best_avg:
                    best_avg = avg
                    best_group = group

        return {
            "hashtag_count_vs_engagement": result,
            "optimal_hashtag_count": best_group,
        }

    # ── 14. Consistency score (new) ──────────────────────────────

    def _analyze_consistency_score(self, posts: list[dict]) -> dict:
        """Calculate posting consistency — gap analysis, streak, 0-100 score."""
        if not posts:
            return {
                "consistency_score": 0,
                "avg_days_between_posts": None,
                "max_gap_days": None,
                "current_streak_days": None,
                "posting_regularity": "insufficient_data",
            }

        dates = [_parse_post_date(p) for p in posts]
        dates_sorted = sorted([d for d in dates if d is not None], reverse=True)

        if len(dates_sorted) < 2:
            return {
                "consistency_score": 0,
                "avg_days_between_posts": None,
                "max_gap_days": None,
                "current_streak_days": None,
                "posting_regularity": "insufficient_data",
            }

        # Gaps between consecutive posts (sorted desc, so gaps are positive)
        gaps = [(dates_sorted[i] - dates_sorted[i + 1]).days for i in range(len(dates_sorted) - 1)]
        avg_gap = sum(gaps) / len(gaps)
        max_gap = max(gaps)

        # Current streak: how many consecutive recent posts within 2× avg gap
        streak_days = 0
        if dates_sorted:
            now = datetime.now(timezone.utc)
            days_since_last = (now - dates_sorted[0]).days
            threshold = max(avg_gap * 2, 14)  # at least 14-day window
            if days_since_last <= threshold:
                streak_days = (dates_sorted[0] - dates_sorted[-1]).days

        # Consistency score: penalise for high gap variance and large max gaps
        # Score = 100 * (1 - variance_penalty) * (1 - max_gap_penalty)
        if len(gaps) > 1:
            gap_std = stdev(gaps)
            variance_penalty = min(gap_std / max(avg_gap, 1), 1.0)
        else:
            variance_penalty = 0.0

        max_gap_penalty = min(max_gap / 60, 1.0)  # 60+ days gap = full penalty
        score = round(100 * (1 - variance_penalty * 0.5) * (1 - max_gap_penalty * 0.5))
        score = max(0, min(100, score))

        # Label
        if score >= 80:
            regularity = "very_consistent"
        elif score >= 60:
            regularity = "consistent"
        elif score >= 40:
            regularity = "irregular"
        else:
            regularity = "sporadic"

        return {
            "consistency_score": score,
            "avg_days_between_posts": round(avg_gap, 1),
            "max_gap_days": max_gap,
            "current_streak_days": streak_days,
            "posting_regularity": regularity,
        }

    # ── 15. Top posts analysis (new) ─────────────────────────────

    def _analyze_top_posts(self, posts: list[dict]) -> dict:
        """Top 5 posts with contextual analysis of what they have in common."""
        if not posts:
            return {"top_posts": [], "top_posts_patterns": {}}

        scored = sorted(
            posts,
            key=lambda p: p.get("likes", 0) + p.get("comments", 0),
            reverse=True,
        )
        top_5 = scored[:5]

        top_posts = []
        for p in top_5:
            caption = p.get("caption", "") or ""
            clean_caption = re.sub(r"#\w+", "", caption).strip()
            first_line = caption.split("\n")[0].strip()[:100] if caption else ""
            tag_count = len(re.findall(r"#\w+", caption))
            word_count = len(clean_caption.split())

            top_posts.append({
                "caption_preview": (clean_caption[:120] + "...") if len(clean_caption) > 120 else clean_caption,
                "first_line": first_line,
                "content_type": p.get("content_type", "photo"),
                "likes": p.get("likes", 0),
                "comments": p.get("comments", 0),
                "views": p.get("views", 0),
                "engagement": p.get("likes", 0) + p.get("comments", 0),
                "hashtag_count": tag_count,
                "word_count": word_count,
                "posted_at": p.get("posted_at"),
            })

        # Find patterns: what do the top posts have in common?
        if top_5:
            content_types = Counter(p.get("content_type", "photo") for p in top_5)
            most_common_type = content_types.most_common(1)[0][0]
            avg_hashtags = round(
                sum(len(re.findall(r"#\w+", p.get("caption", "") or "")) for p in top_5) / len(top_5),
                1,
            )
            avg_words = round(
                sum(len(re.sub(r"#\w+", "", p.get("caption", "") or "").split()) for p in top_5) / len(top_5),
                1,
            )
            patterns = {
                "dominant_content_type": most_common_type,
                "avg_hashtags": avg_hashtags,
                "avg_caption_words": avg_words,
            }
        else:
            patterns = {}

        return {
            "top_posts": top_posts,
            "top_posts_patterns": patterns,
        }
