"""Gemini-based video analysis for T3 (Viral Reaction) and T4 (Testimonial Story)."""

import asyncio
import json
import logging
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

    async def analyze_for_talking_head(self, video_url: str) -> VideoAnalysisResult:
        """Analyze video for Talking Head template.

        Returns actual video duration and word-level speech timestamps for
        karaoke-style captions. Falls back to phrase segments when words unavailable.
        """
        prompt = (
            "Analyze this video for a Talking Head auto-caption template.\n\n"
            "Tasks:\n"
            "1. Measure the total video duration in seconds (be precise).\n"
            "2. Transcribe ALL speech word by word. For each individual word, provide\n"
            "   the exact start and end time in seconds when that word is spoken.\n"
            "   If there is no speech, return empty arrays.\n\n"
            "Return ONLY valid JSON — no markdown, no explanation:\n"
            '{"duration": 18.5, "words": ['
            '{"word": "Hello", "start": 0.3, "end": 0.6}, '
            '{"word": "everyone", "start": 0.6, "end": 1.1}, '
            '{"word": "today", "start": 1.1, "end": 1.4}'
            "]}"
        )

        defaults: dict = {"duration": 30.0, "words": [], "segments": []}
        raw = await self._analyze(video_url, prompt, defaults)

        # Parse word-level timestamps (preferred — karaoke accuracy)
        raw_words = raw.get("words") or []
        clean_words = []
        for w in raw_words:
            try:
                word = str(w.get("word", "")).strip()
                if not word:
                    continue
                clean_words.append({
                    "word": word,
                    "start": float(w.get("start", 0)),
                    "end": float(w.get("end", 0)),
                })
            except (TypeError, ValueError):
                continue

        # Parse phrase segments as fallback (legacy path)
        raw_segments = raw.get("segments") or []
        clean_segments = []
        for seg in raw_segments:
            try:
                clean_segments.append({
                    "text": str(seg.get("text", "")).strip(),
                    "start": float(seg.get("start", 0)),
                    "end": float(seg.get("end", 0)),
                })
            except (TypeError, ValueError):
                continue

        logger.info(
            "analyze_for_talking_head: duration=%.1f words=%d segments=%d",
            float(raw.get("duration") or 30.0), len(clean_words), len(clean_segments),
        )

        return VideoAnalysisResult(
            duration_seconds=float(raw.get("duration") or 30.0),
            word_timestamps=clean_words if clean_words else None,
            transcript_segments=clean_segments if clean_segments else None,
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
        """Send video to Gemini for analysis via Files API. Falls back to *defaults* on failure."""
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                video_response = await client.get(video_url)
                video_response.raise_for_status()

            content_type = video_response.headers.get("content-type", "video/mp4")
            mime = "video/webm" if "webm" in content_type else "video/mp4"

            # Upload to Files API — gives Gemini proper audio access for accurate timestamps
            file_uri = await self._upload_to_files_api(video_response.content, mime)

            url = f"{self.endpoint}?key={self.api_key}"
            body = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"fileData": {"mimeType": mime, "fileUri": file_uri}},
                    ]
                }],
                "generationConfig": {"responseMimeType": "application/json"},
            }

            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(url, json=body, headers={"Content-Type": "application/json"})
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
            return {**defaults, **result}

        except Exception as e:
            logger.warning("Video analysis failed, using defaults: %s", e)
            return defaults

    async def _upload_to_files_api(self, video_bytes: bytes, mime: str) -> str:
        """Upload video to Gemini Files API, wait for ACTIVE state, return file URI.

        Files API gives Gemini access to the actual audio stream, which
        produces far more accurate word-level timestamps than inline base64.
        Must poll for ACTIVE state before using in generateContent — sending
        a PROCESSING file causes a 400 error.
        """
        boundary = "pelvi_video_boundary"
        metadata = json.dumps({"file": {"mimeType": mime}}).encode()
        body = (
            f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode()
            + metadata
            + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
            + video_bytes
            + f"\r\n--{boundary}--".encode()
        )
        upload_url = (
            f"https://generativelanguage.googleapis.com/upload/v1beta/files"
            f"?key={self.api_key}"
        )
        headers = {
            "X-Goog-Upload-Protocol": "multipart",
            "Content-Type": f"multipart/related; boundary={boundary}",
        }
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(upload_url, headers=headers, content=body)
            resp.raise_for_status()

        file_data = resp.json()["file"]
        file_name = file_data["name"]   # e.g. "files/abc123"
        file_uri = file_data["uri"]
        logger.info("Uploaded video to Files API: %s (state=%s)", file_uri, file_data.get("state"))

        # Poll until ACTIVE — file may be in PROCESSING for several seconds
        poll_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={self.api_key}"
        for attempt in range(20):
            async with httpx.AsyncClient(timeout=30) as client:
                poll_resp = await client.get(poll_url)
                poll_resp.raise_for_status()
            state = poll_resp.json().get("state", "PROCESSING")
            if state == "ACTIVE":
                logger.info("Files API file ACTIVE after %d poll(s)", attempt + 1)
                break
            if state == "FAILED":
                raise RuntimeError(f"Gemini Files API upload failed: {poll_resp.text}")
            await asyncio.sleep(2)
        else:
            raise RuntimeError("Gemini Files API file never reached ACTIVE state")

        return file_uri
