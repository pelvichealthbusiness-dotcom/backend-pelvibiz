"""Pure-Python Instagram style analyzer — 8 analysis modules."""

from __future__ import annotations

import math
import re
import logging
from collections import Counter
from datetime import datetime

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


class StyleAnalyzer:
    """Analyse a list of Instagram posts and return structured style metrics."""

    def analyze(self, posts: list[dict], profile_data: dict) -> dict:
        captions = [p["caption"] for p in posts if p.get("caption")]
        followers = profile_data.get("followers", 0)

        result: dict = {}
        result.update(self._analyze_captions(captions))
        result.update(self._analyze_hooks(captions))
        result.update(self._analyze_hashtags(captions))
        result.update(self._analyze_engagement(posts, followers))
        result.update(self._analyze_posting_patterns(posts))
        result.update(self._analyze_emojis(captions))
        result.update(self._analyze_ctas(captions))
        result.update(self._extract_themes(captions))
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

        timestamps = [p.get("timestamp", 0) for p in posts if p.get("timestamp")]
        if not timestamps:
            return {"posts_per_week": 0, "best_days": [], "best_hours": []}

        dates = [datetime.fromtimestamp(ts) for ts in timestamps if ts > 0]
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
