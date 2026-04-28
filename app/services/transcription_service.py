"""TranscriptionService — word-level subtitle pipeline for talking head videos.

Primary path: OpenAI Whisper (whisper-1) — real ASR with word-level timestamps.
Fallback path: Gemini video analysis — used when whisper_api_key is not configured.

Returns empty list on any failure (graceful degradation — renders proceed without captions).
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.models.video import PhraseBlock
from app.services.video_analysis import VideoAnalysisService

logger = logging.getLogger(__name__)

# Hard limits per spec
_MAX_CHARS_PER_BLOCK = 150
_MIN_BLOCK_DURATION = 0.6    # seconds — minimum for phrase-level blocks
_KARAOKE_MIN_DURATION = 0.5  # seconds — minimum for word-level karaoke blocks
_SENTENCE_ENDINGS = {".", "?", "!"}
_KARAOKE_WORDS_PER_BLOCK = 3  # 3 words per card — readable without flickering


class TranscriptionService:
    """Transcribes speech in a video URL and returns phrase blocks."""

    def __init__(self):
        self._analysis = VideoAnalysisService()

    async def transcribe(self, video_url: str) -> list[PhraseBlock]:
        """Transcribe speech and return PhraseBlocks for caption rendering.

        Uses Whisper (word-accurate) when configured, Gemini as fallback.
        Returns empty list if no speech detected or on failure.
        """
        settings = get_settings()
        if settings.whisper_api_key:
            try:
                return await self._transcribe_with_whisper(video_url, settings.whisper_api_key)
            except Exception as exc:
                logger.warning("Whisper transcription failed, falling back to Gemini: %s", exc)

        return await self._transcribe_with_gemini(video_url)

    # ------------------------------------------------------------------
    # Whisper path (primary)
    # ------------------------------------------------------------------

    async def _transcribe_with_whisper(self, video_url: str, api_key: str) -> list[PhraseBlock]:
        """Download video, extract audio, call Whisper API, return PhraseBlocks."""
        logger.info("TranscriptionService: Whisper path — %s", video_url)

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            video_bytes = resp.content

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            audio_path = os.path.join(tmpdir, "audio.mp3")

            with open(video_path, "wb") as f:
                f.write(video_bytes)

            # Extract mono 16kHz audio — reduces upload size, improves Whisper accuracy
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
                audio_path, "-y",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg audio extraction failed (code {proc.returncode})")

            whisper = AsyncOpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
            with open(audio_path, "rb") as f:
                response = await whisper.audio.transcriptions.create(
                    model="whisper-1",
                    file=("audio.mp3", f, "audio/mpeg"),
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )

        words = [
            {"word": w.word, "start": w.start, "end": w.end}
            for w in (response.words or [])
            if w.word and w.word.strip()
        ]
        if not words:
            logger.info("TranscriptionService: Whisper detected no speech in %s", video_url)
            return []

        logger.info("TranscriptionService: Whisper — %d words detected", len(words))
        blocks = _group_words_into_karaoke_blocks(words)
        logger.info("TranscriptionService: produced %d karaoke blocks", len(blocks))
        return blocks

    # ------------------------------------------------------------------
    # Gemini path (fallback)
    # ------------------------------------------------------------------

    async def _transcribe_with_gemini(self, video_url: str) -> list[PhraseBlock]:
        """Transcribe via Gemini video analysis (fallback when Whisper not configured)."""
        try:
            logger.info("TranscriptionService: Gemini fallback path — %s", video_url)
            result = await self._analysis.analyze_for_talking_head(video_url)

            if result.word_timestamps:
                logger.info(
                    "TranscriptionService: Gemini word-level — %d words",
                    len(result.word_timestamps),
                )
                blocks = _group_words_into_karaoke_blocks(result.word_timestamps)
                logger.info("TranscriptionService: produced %d karaoke blocks", len(blocks))
                return blocks

            segments = result.transcript_segments or []
            if not segments:
                logger.info("TranscriptionService: Gemini detected no speech in %s", video_url)
                return []
            logger.info("TranscriptionService: Gemini phrase-level — %d segments", len(segments))
            blocks = _group_into_phrase_blocks(segments)
            logger.info("TranscriptionService: produced %d phrase blocks", len(blocks))
            return blocks
        except Exception as exc:
            logger.warning("TranscriptionService: Gemini fallback failed: %s", exc, exc_info=True)
            return []


# ---------------------------------------------------------------------------
# Phrase-block grouping (pure functions — testable standalone)
# ---------------------------------------------------------------------------

def _group_into_phrase_blocks(segments: list[dict]) -> list[PhraseBlock]:
    """Group raw transcript segments into phrase blocks.

    Rules:
    - Each block ≤ 150 characters
    - Sentence boundaries (. ? !) force a split
    - Minimum block duration: 0.6 seconds
    """
    blocks: list[PhraseBlock] = []
    buffer_texts: list[str] = []
    buffer_start: float = 0.0
    buffer_end: float = 0.0

    def flush(end_time: float) -> None:
        if not buffer_texts:
            return
        text = " ".join(buffer_texts)
        duration = max(end_time - buffer_start, _MIN_BLOCK_DURATION)
        blocks.append(PhraseBlock(text=text, start=buffer_start, end=buffer_start + duration))

    for seg in segments:
        seg_text: str = str(seg.get("text", "")).strip()
        seg_start: float = float(seg.get("start", 0))
        seg_end: float = float(seg.get("end", seg_start + _MIN_BLOCK_DURATION))

        if not seg_text:
            continue

        candidate = " ".join(buffer_texts + [seg_text]) if buffer_texts else seg_text
        if len(candidate) > _MAX_CHARS_PER_BLOCK and buffer_texts:
            flush(buffer_end)
            buffer_texts = []
            buffer_start = seg_start

        if not buffer_texts:
            buffer_start = seg_start

        buffer_texts.append(seg_text)
        buffer_end = seg_end

        ends_sentence = seg_text.rstrip()[-1:] in _SENTENCE_ENDINGS if seg_text.rstrip() else False
        if ends_sentence:
            flush(buffer_end)
            buffer_texts = []
            buffer_start = buffer_end

    flush(buffer_end)
    return blocks


def _group_words_into_karaoke_blocks(
    words: list[dict],
    words_per_block: int = _KARAOKE_WORDS_PER_BLOCK,
) -> list[PhraseBlock]:
    """Group word-level timestamps into PhraseBlocks for karaoke display.

    Each block contains N words with precise start/end from Whisper timestamps.
    """
    blocks: list[PhraseBlock] = []
    for i in range(0, len(words), words_per_block):
        chunk = words[i : i + words_per_block]
        text = " ".join(str(w.get("word", "")).strip() for w in chunk if str(w.get("word", "")).strip())
        if not text:
            continue
        start = float(chunk[0].get("start", 0))
        end = float(chunk[-1].get("end", start + _KARAOKE_MIN_DURATION))
        duration = max(end - start, _KARAOKE_MIN_DURATION)
        blocks.append(PhraseBlock(text=text, start=round(start, 3), end=round(start + duration, 3)))
    return blocks
