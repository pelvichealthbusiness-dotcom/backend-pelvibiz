"""Instagram scraper with provider chain: PrivateAPI → Apify → RapidAPI."""

from __future__ import annotations

import asyncio
import time
import logging
from datetime import datetime

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple sliding window rate limiter."""

    def __init__(self, max_requests: int = 6, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.timestamps: list[float] = []

    async def acquire(self) -> bool:
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < self.window]
        if len(self.timestamps) >= self.max_requests:
            return False
        self.timestamps.append(now)
        return True


class PrivateApiProvider:
    """Instagram Private API — free, rate limited."""

    BASE_URL = "https://i.instagram.com/api/v1"
    HEADERS = {
        "User-Agent": "Instagram 275.0.0.27.98 Android",
        "X-IG-App-ID": "936619743392459",
    }

    async def fetch(self, username: str) -> tuple[dict, list[dict]]:
        async with httpx.AsyncClient(timeout=15, headers=self.HEADERS) as client:
            response = await client.get(
                f"{self.BASE_URL}/users/web_profile_info/",
                params={"username": username},
            )

            if response.status_code == 401:
                raise Exception("Instagram rate limited (401)")
            if response.status_code == 404:
                raise Exception(f"User @{username} not found")
            response.raise_for_status()

            data = response.json()
            user = data.get("data", {}).get("user", {})

            if not user:
                raise Exception(f"No user data for @{username}")
            
            if user.get("is_private", False):
                raise Exception(f"@{username} is a private account")

            profile = {
                "username": user.get("username", username),
                "full_name": user.get("full_name", ""),
                "biography": user.get("biography", ""),
                "followers": user.get("edge_followed_by", {}).get("count", 0),
                "following": user.get("edge_follow", {}).get("count", 0),
                "posts_count": user.get("edge_owner_to_timeline_media", {}).get(
                    "count", 0
                ),
                "is_verified": user.get("is_verified", False),
                "profile_pic_url": user.get(
                    "profile_pic_url_hd", user.get("profile_pic_url", "")
                ),
            }

            posts = []
            edges = (
                user.get("edge_owner_to_timeline_media", {}).get("edges", [])
            )
            for edge in edges:
                node = edge.get("node", {})
                caption_edges = (
                    node.get("edge_media_to_caption", {}).get("edges", [])
                )
                caption = (
                    caption_edges[0].get("node", {}).get("text", "")
                    if caption_edges
                    else ""
                )
                posts.append(
                    {
                        "id": node.get("id", ""),
                        "caption": caption,
                        "likes": node.get("edge_liked_by", {}).get("count", 0),
                        "comments": node.get("edge_media_to_comment", {}).get(
                            "count", 0
                        ),
                        "timestamp": node.get("taken_at_timestamp", 0),
                        "media_type": 2 if node.get("is_video") else 1,
                        "is_carousel": node.get("__typename") == "GraphSidecar",
                        "display_url": node.get("display_url", ""),
                    }
                )

            return (profile, posts)


class ApifyProvider:
    """Apify fallback — paid, reliable."""

    BASE_URL = "https://api.apify.com/v2"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch(
        self, username: str, max_posts: int = 30
    ) -> tuple[dict, list[dict]]:
        actor_id = "apify~instagram-profile-scraper"

        async with httpx.AsyncClient(timeout=120) as client:
            run_response = await client.post(
                f"{self.BASE_URL}/acts/{actor_id}/runs",
                params={"token": self.api_key},
                json={"usernames": [username], "resultsLimit": max_posts},
            )
            run_response.raise_for_status()
            run_data = run_response.json().get("data", {})
            run_id = run_data.get("id")
            dataset_id = run_data.get("defaultDatasetId")

            for _ in range(24):  # max 2 min
                await asyncio.sleep(5)
                status_resp = await client.get(
                    f"{self.BASE_URL}/actor-runs/{run_id}",
                    params={"token": self.api_key},
                )
                status = status_resp.json().get("data", {}).get("status")
                if status == "SUCCEEDED":
                    break
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    raise Exception(f"Apify run failed: {status}")

            results_resp = await client.get(
                f"{self.BASE_URL}/datasets/{dataset_id}/items",
                params={"token": self.api_key},
            )
            items = results_resp.json()
            if not items:
                raise Exception("Apify returned no results")

            item = items[0]
            profile = {
                "username": item.get("username", username),
                "full_name": item.get("fullName", ""),
                "biography": item.get("biography", ""),
                "followers": item.get("followersCount", 0),
                "following": item.get("followsCount", 0),
                "posts_count": item.get("postsCount", 0),
                "is_verified": item.get("verified", False),
                "profile_pic_url": item.get("profilePicUrlHD", ""),
            }

            posts = []
            for post in item.get("latestPosts", [])[:max_posts]:
                ts = post.get("timestamp", 0)
                if isinstance(ts, str):
                    try:
                        ts = int(
                            datetime.fromisoformat(
                                ts.replace("Z", "+00:00")
                            ).timestamp()
                        )
                    except Exception:
                        ts = 0
                posts.append(
                    {
                        "id": post.get("id", ""),
                        "caption": post.get("caption", ""),
                        "likes": post.get("likesCount", 0),
                        "comments": post.get("commentsCount", 0),
                        "timestamp": ts,
                        "media_type": 2 if post.get("type") == "Video" else 1,
                        "is_carousel": post.get("type") == "Sidecar",
                    }
                )

            return (profile, posts)


class RapidApiProvider:
    """Legacy RapidAPI — kept as last resort."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.host = "instagram-api-fast-reliable-data-scraper.p.rapidapi.com"
        self.headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": self.host,
        }

    async def fetch(
        self, username: str, max_posts: int = 30
    ) -> tuple[dict, list[dict]]:
        base = f"https://{self.host}"
        async with httpx.AsyncClient(timeout=30) as client:
            # Profile
            prof_resp = await client.get(
                f"{base}/profile",
                params={"username": username},
                headers=self.headers,
            )
            prof_resp.raise_for_status()
            raw = prof_resp.json()
            # API may nest under "data" or return flat
            prof_data = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw

            pk = prof_data.get("pk") or prof_data.get("id")
            profile = {
                "username": prof_data.get("username", username),
                "full_name": prof_data.get("full_name", ""),
                "biography": prof_data.get("biography", ""),
                "followers": prof_data.get("follower_count", 0),
                "following": prof_data.get("following_count", 0),
                "posts_count": prof_data.get("media_count", 0),
                "is_verified": prof_data.get("is_verified", False),
                "profile_pic_url": (
                    prof_data.get("hd_profile_pic_url_info", {}).get("url", "")
                    or prof_data.get("profile_pic_url_hd", "")
                    or prof_data.get("profile_pic_url", "")
                ),
            }

            # Posts
            posts = []
            if pk:
                feed_resp = await client.get(
                    f"{base}/feed",
                    params={"user_id": pk},
                    headers=self.headers,
                )
                feed_resp.raise_for_status()
                feed_raw = feed_resp.json()
                items = (
                    feed_raw.get("data", {}).get("items", [])
                    or feed_raw.get("items", [])
                    or feed_raw.get("feed", {}).get("items", [])
                )
                for item in items[:max_posts]:
                    cap = item.get("caption", {}) or {}
                    posts.append(
                        {
                            "id": item.get("id", ""),
                            "caption": (
                                cap.get("text", "")
                                if isinstance(cap, dict)
                                else str(cap)
                            ),
                            "likes": item.get("like_count", 0),
                            "comments": item.get("comment_count", 0),
                            "timestamp": item.get("taken_at", 0),
                            "media_type": item.get("media_type", 1),
                            "is_carousel": (
                                item.get("carousel_media_count", 0) > 0
                            ),
                        }
                    )

            return (profile, posts)


# Singleton rate limiter
_rate_limiter = RateLimiter(max_requests=6, window_seconds=60)


class InstagramScraper:
    """Instagram scraper with provider chain: PrivateAPI → Apify → RapidAPI."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.private_api = PrivateApiProvider()
        self.apify = (
            ApifyProvider(self.settings.apify_api_key)
            if self.settings.apify_api_key
            else None
        )
        self.rapidapi = (
            RapidApiProvider(self.settings.rapidapi_key)
            if self.settings.rapidapi_key
            else None
        )

    async def scrape(
        self, username: str, max_posts: int = 30, user_id: str | None = None,
    ) -> tuple[dict, list[dict]]:
        username = username.strip().lstrip("@").lower()

        # 1. Try Private API
        if await _rate_limiter.acquire():
            try:
                result = await self.private_api.fetch(username)
                logger.info(f"Private API success for @{username}")
                return result
            except Exception as e:
                logger.warning(f"Private API failed for @{username}: {e}")
        else:
            logger.info(f"Rate limited, skipping Private API for @{username}")

        # 2. Try Apify
        if self.apify:
            try:
                result = await self.apify.fetch(username, max_posts)
                logger.info(f"Apify success for @{username}")
                return result
            except Exception as e:
                logger.warning(f"Apify failed for @{username}: {e}")

        # 3. Try RapidAPI (legacy)
        if self.rapidapi:
            try:
                result = await self.rapidapi.fetch(username, max_posts)
                logger.info(f"RapidAPI success for @{username}")
                return result
            except Exception as e:
                logger.warning(f"RapidAPI failed for @{username}: {e}")

        from app.services.exceptions import AgentAPIError
        raise AgentAPIError(
            message=f'Could not analyze @{username}. The account may be private or have no posts.',
            code='SCRAPER_FAILED',
            status_code=422,
        )

    async def fetch_profile(self, username: str) -> dict:
        profile, _ = await self.scrape(username, max_posts=0)
        return profile

    async def fetch_posts(
        self, username: str, max_posts: int = 30
    ) -> list[dict]:
        _, posts = await self.scrape(username, max_posts)
        return posts
