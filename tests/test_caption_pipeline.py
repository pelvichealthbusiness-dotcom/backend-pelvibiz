"""Tests for the OpusClip-style caption pipeline.

Covers:
- _group_into_phrase_blocks() grouping logic
- _caption_elem() element structure
- _append_captions() builder helper
- TranscriptionService.transcribe() with mocked VideoAnalysisService
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.models.video import PhraseBlock, VideoAnalysisResult
from app.services.transcription_service import (
    TranscriptionService,
    _group_into_phrase_blocks,
)
from app.templates.renderscript_builders import _caption_elem, _append_captions


# ── _group_into_phrase_blocks ─────────────────────────────────────────────

class TestGroupIntoPhraseBlocks:
    def test_basic_grouping(self):
        segments = [
            {"text": "Hello", "start": 0.0, "end": 0.5},
            {"text": "everyone", "start": 0.5, "end": 1.0},
            {"text": "today", "start": 1.0, "end": 1.5},
        ]
        blocks = _group_into_phrase_blocks(segments)
        assert len(blocks) >= 1
        assert all(isinstance(b, PhraseBlock) for b in blocks)

    def test_respects_150_char_limit(self):
        # Generate segments that together exceed 150 chars
        long_word = "word" * 10  # 40 chars
        segments = [
            {"text": long_word, "start": float(i), "end": float(i) + 0.5}
            for i in range(10)
        ]
        blocks = _group_into_phrase_blocks(segments)
        for block in blocks:
            assert len(block.text) <= 150, f"Block exceeded 150 chars: {len(block.text)}"

    def test_sentence_boundary_forces_split(self):
        segments = [
            {"text": "This is a sentence.", "start": 0.0, "end": 1.0},
            {"text": "And this is another.", "start": 1.0, "end": 2.0},
        ]
        blocks = _group_into_phrase_blocks(segments)
        # Two sentences → must produce at least 2 blocks
        assert len(blocks) >= 2

    def test_question_mark_forces_split(self):
        segments = [
            {"text": "Are you ready?", "start": 0.0, "end": 1.0},
            {"text": "Let's go!", "start": 1.0, "end": 2.0},
        ]
        blocks = _group_into_phrase_blocks(segments)
        assert len(blocks) >= 2

    def test_minimum_block_duration(self):
        # Segment with same start and end (edge case)
        segments = [
            {"text": "Short", "start": 1.0, "end": 1.0},
        ]
        blocks = _group_into_phrase_blocks(segments)
        assert len(blocks) == 1
        assert blocks[0].end - blocks[0].start >= 0.6

    def test_empty_segments_returns_empty(self):
        assert _group_into_phrase_blocks([]) == []

    def test_skips_empty_text(self):
        segments = [
            {"text": "", "start": 0.0, "end": 0.5},
            {"text": "Hello", "start": 0.5, "end": 1.0},
        ]
        blocks = _group_into_phrase_blocks(segments)
        assert len(blocks) == 1
        assert blocks[0].text == "Hello"

    def test_block_time_continuity(self):
        segments = [
            {"text": "First", "start": 1.0, "end": 1.5},
            {"text": "second", "start": 1.5, "end": 2.0},
            {"text": "third", "start": 2.0, "end": 2.5},
        ]
        blocks = _group_into_phrase_blocks(segments)
        # First block should start at 1.0
        assert blocks[0].start == pytest.approx(1.0)


# ── _caption_elem ─────────────────────────────────────────────────────────

class TestCaptionElem:
    def test_uses_anton_font(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert el["font_family"] == "Anton"

    def test_uses_weight_900(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert el["font_weight"] == "900"

    def test_white_fill_color(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert el["fill_color"] == "#FFFFFF"

    def test_thick_stroke(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        # Must be thicker than legacy 1.2 vmin
        stroke_vmin = float(el["stroke_width"].replace(" vmin", ""))
        assert stroke_vmin >= 1.5

    def test_has_shadow(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert "shadow_color" in el
        assert "shadow_offset_x" in el
        assert "shadow_offset_y" in el

    def test_no_background_box(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert "background_color" not in el

    def test_default_y_position(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert el["y"] == "78%"

    def test_custom_y_position(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0, y="65%")
        assert el["y"] == "65%"

    def test_minimum_duration_enforced(self):
        # duration=0 should be clamped to minimum 0.5
        el = _caption_elem(track=500, text="Hi", time=0.0, duration=0.0)
        assert el["duration"] >= 0.5

    def test_correct_track(self):
        el = _caption_elem(track=42, text="Test", time=0.0, duration=1.0)
        assert el["track"] == 42


# ── _append_captions ──────────────────────────────────────────────────────

class TestAppendCaptions:
    def test_appends_correct_count(self):
        blocks = [
            PhraseBlock(text="First block", start=0.0, end=1.0),
            PhraseBlock(text="Second block", start=1.0, end=2.0),
            PhraseBlock(text="Third block", start=2.0, end=3.0),
        ]
        elements = []
        _append_captions(elements, blocks)
        assert len(elements) == 3

    def test_tracks_are_sequential(self):
        blocks = [
            PhraseBlock(text="A", start=0.0, end=1.0),
            PhraseBlock(text="B", start=1.0, end=2.0),
        ]
        elements = []
        _append_captions(elements, blocks, base_track=500)
        tracks = [el["track"] for el in elements]
        assert tracks == [500, 501]

    def test_empty_blocks_adds_nothing(self):
        elements = []
        _append_captions(elements, [])
        assert elements == []

    def test_timing_matches_phrase_blocks(self):
        blocks = [
            PhraseBlock(text="Hello world", start=2.5, end=4.0),
        ]
        elements = []
        _append_captions(elements, blocks)
        assert elements[0]["time"] == pytest.approx(2.5)


# ── TranscriptionService ──────────────────────────────────────────────────

class TestTranscriptionService:
    @pytest.mark.asyncio
    async def test_returns_phrase_blocks_on_success(self):
        mock_result = VideoAnalysisResult(
            duration_seconds=10.0,
            transcript_segments=[
                {"text": "Hello everyone", "start": 0.0, "end": 1.0},
                {"text": "welcome to my channel.", "start": 1.0, "end": 2.5},
            ],
        )
        with patch(
            "app.services.transcription_service.VideoAnalysisService.analyze_for_talking_head",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            service = TranscriptionService()
            blocks = await service.transcribe("https://example.com/video.mp4")

        assert len(blocks) >= 1
        assert all(isinstance(b, PhraseBlock) for b in blocks)

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_speech(self):
        mock_result = VideoAnalysisResult(
            duration_seconds=10.0,
            transcript_segments=[],
        )
        with patch(
            "app.services.transcription_service.VideoAnalysisService.analyze_for_talking_head",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            service = TranscriptionService()
            blocks = await service.transcribe("https://example.com/muted.mp4")

        assert blocks == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_gemini_failure(self):
        with patch(
            "app.services.transcription_service.VideoAnalysisService.analyze_for_talking_head",
            new_callable=AsyncMock,
            side_effect=Exception("Gemini API error"),
        ):
            service = TranscriptionService()
            blocks = await service.transcribe("https://example.com/video.mp4")

        assert blocks == []

    @pytest.mark.asyncio
    async def test_phrase_blocks_respect_char_limit(self):
        # Many short segments that should be grouped ≤ 150 chars each
        segments = [
            {"text": f"word{i}", "start": float(i), "end": float(i) + 0.5}
            for i in range(50)
        ]
        mock_result = VideoAnalysisResult(
            duration_seconds=50.0,
            transcript_segments=segments,
        )
        with patch(
            "app.services.transcription_service.VideoAnalysisService.analyze_for_talking_head",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            service = TranscriptionService()
            blocks = await service.transcribe("https://example.com/video.mp4")

        for block in blocks:
            assert len(block.text) <= 150
