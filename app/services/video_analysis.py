"""Gemini-based video analysis for T3 (Viral Reaction) and T4 (Testimonial Story)."""

import json
import logging
import base64

import httpx

from app.config import get_settings
from app.models.video import VideoAnalysisResult

logger = logging.getLogger(__name__)


class VideoAnalysisService:
    """Sends video to Gemini for analysis (trim points, overlays, duration)."""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.google_gemini_api_key
        self.model = "gemini-2.5-flash"
        self.endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_for_viral_reaction(self, video_url: str) -> VideoAnalysisResult:
        """Analyze video for T3 Viral Reaction template.

        Returns a VideoAnalysisResult with start_time_seconds, duration_seconds,
        and generated_hook populated.
        """
        prompt = (
            "Analyze this video for a Viral Reaction reel template.\n\n"
            "Determine:\n"
            "1. The best moment to start the clip (trim_start in seconds) "
            "- find the most engaging/dramatic moment\n"
            "2. The ideal duration for a short-form reel (8-15 seconds)\n"
            "3. A short reaction text overlay (1-5 words, bold, attention-grabbing)\n\n"
            "Return ONLY valid JSON:\n"
            '{"trim_start": 2.5, "duration": 12, "text_overlay": "Wait for it..."}'
        )

        defaults = {"trim_start": 0, "duration": 10, "text_overlay": "Watch this"}
        raw = await self._analyze(video_url, prompt, defaults)

        return VideoAnalysisResult(
            start_time_seconds=raw.get("trim_start", 0),
            duration_seconds=raw.get("duration", 10),
            generated_hook=raw.get("text_overlay", "Watch this"),
        )

    async def analyze_for_testimonial(self, video_url: str) -> VideoAnalysisResult:
        """Analyze video for T4 Testimonial Story template.

        Returns a VideoAnalysisResult with start_time_seconds,
        generated_hook (testimonial quote), and analysis_summary.
        """
        prompt = (
            "Analyze this video for a Testimonial Story reel.\n\n"
            "Determine:\n"
            "1. The best starting point (trim_start in seconds) "
            "- where the person begins speaking or the key moment starts\n"
            "2. A short testimonial quote overlay (5-15 words capturing the essence)\n"
            "3. Best text position to avoid covering the speaker's face "
            "(text_y as percentage, text_x as percentage)\n\n"
            "Return ONLY valid JSON:\n"
            '{"trim_start": 1.0, "text_overlay": "This changed everything for me", '
            '"text_x": "50%", "text_y": "80%"}'
        )

        defaults = {
            "trim_start": 0,
            "text_overlay": "My experience",
            "text_x": "50%",
            "text_y": "71.6%",
        }
        raw = await self._analyze(video_url, prompt, defaults)

        return VideoAnalysisResult(
            start_time_seconds=raw.get("trim_start", 0),
            generated_hook=raw.get("text_overlay", "My experience"),
            analysis_summary=json.dumps(
                {"text_x": raw.get("text_x", "50%"), "text_y": raw.get("text_y", "71.6%")}
            ),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _analyze(self, video_url: str, prompt: str, defaults: dict) -> dict:
        """Send video to Gemini for analysis. Falls back to *defaults* on failure."""
        try:
            # Download video as base64
            async with httpx.AsyncClient(timeout=60) as client:
                video_response = await client.get(video_url, follow_redirects=True)
                video_response.raise_for_status()
                video_base64 = base64.b64encode(video_response.content).decode("utf-8")

            # Determine mime type
            content_type = video_response.headers.get("content-type", "video/mp4")
            if "webm" in content_type:
                mime = "video/webm"
            else:
                mime = "video/mp4"

            url = f"{self.endpoint}?key={self.api_key}"
            body = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inlineData": {
                                    "mimeType": mime,
                                    "data": video_base64,
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {"responseMimeType": "application/json"},
            }

            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    url, json=body, headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("Gemini video analysis returned no candidates, using defaults")
                return defaults

            text = (
                candidates[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            result = json.loads(text)
            # Merge with defaults for any missing fields
            return {**defaults, **result}

        except Exception as e:
            logger.warning("Video analysis failed, using defaults: %s", e)
            return defaults
