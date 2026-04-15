"""TranscriptionService — generic audio-to-PhraseBlock pipeline via Gemini.

Uses the existing VideoAnalysisService under the hood. Works with any video URL
that contains audible speech. Returns empty list when no speech is detected or
on any failure (graceful degradation — renders proceed without captions).
"""

from __future__ import annotations

import logging

from app.models.video import PhraseBlock
from app.services.video_analysis import VideoAnalysisService

logger = logging.getLogger(__name__)

# Hard limits per spec
_MAX_CHARS_PER_BLOCK = 150
_MIN_BLOCK_DURATION = 0.6  # seconds
_SENTENCE_ENDINGS = {".", "?", "!"}


class TranscriptionService:
    """Transcribes speech in a video URL and returns phrase blocks."""

    def __init__(self):
        self._analysis = VideoAnalysisService()

    async def transcribe(self, video_url: str) -> list[PhraseBlock]:
        """Transcribe speech and return grouped PhraseBlocks.

        Returns:
            List of PhraseBlock objects (empty list if no speech or on failure).
        """
        try:
            logger.info("TranscriptionService: transcribing %s", video_url)
            result = await self._analysis.analyze_for_talking_head(video_url)
            segments = result.transcript_segments or []
            if not segments:
                logger.info("TranscriptionService: no speech detected in %s", video_url)
                return []
            logger.info("TranscriptionService: got %d segments → grouping into phrase blocks", len(segments))
            blocks = _group_into_phrase_blocks(segments)
            logger.info("TranscriptionService: produced %d phrase blocks", len(blocks))
            return blocks
        except Exception as exc:
            logger.warning("TranscriptionService.transcribe failed: %s", exc, exc_info=True)
            return []


# ---------------------------------------------------------------------------
# Phrase-block grouping logic (pure function — testable standalone)
# ---------------------------------------------------------------------------

def _group_into_phrase_blocks(
    segments: list[dict],
) -> list[PhraseBlock]:
    """Group raw transcript segments into phrase blocks.

    Rules (from spec S4):
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
        blocks.append(PhraseBlock(
            text=text,
            start=buffer_start,
            end=buffer_start + duration,
        ))

    for i, seg in enumerate(segments):
        seg_text: str = str(seg.get("text", "")).strip()
        seg_start: float = float(seg.get("start", 0))
        seg_end: float = float(seg.get("end", seg_start + _MIN_BLOCK_DURATION))

        if not seg_text:
            continue

        candidate = " ".join(buffer_texts + [seg_text]) if buffer_texts else seg_text
        would_exceed = len(candidate) > _MAX_CHARS_PER_BLOCK

        if would_exceed and buffer_texts:
            # Flush current buffer before adding this segment
            flush(buffer_end)
            buffer_texts = []
            buffer_start = seg_start

        if not buffer_texts:
            buffer_start = seg_start

        buffer_texts.append(seg_text)
        buffer_end = seg_end

        # Sentence boundary: flush immediately
        ends_sentence = seg_text.rstrip()[-1:] in _SENTENCE_ENDINGS if seg_text.rstrip() else False
        if ends_sentence:
            flush(buffer_end)
            buffer_texts = []
            buffer_start = buffer_end

    # Flush any remaining text
    flush(buffer_end)

    return blocks
