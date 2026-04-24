"""Tests for the OpusClip-style caption pipeline.

Covers:
- _group_into_phrase_blocks() grouping logic
- _caption_elem() element structure
- _append_captions() builder helper
- TranscriptionService.transcribe() with mocked VideoAnalysisService
- End-to-end: builders receive phrase_blocks and produce caption elements
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.models.video import PhraseBlock, VideoAnalysisResult, GenerateVideoRequest
from app.services.transcription_service import (
    TranscriptionService,
    _group_into_phrase_blocks,
    _group_words_into_karaoke_blocks,
)
from app.templates.brand_theme import BrandTheme
from app.templates.renderscript_builders import (
    _caption_elem,
    _append_captions,
    build_bullet_reel,
    build_talking_head,
    build_talking_head_v2,
    build_hook_reveal,
    build_edu_steps,
    RENDERSCRIPT_BUILDERS,
    DEFAULT_CAPTION_COLOR,
    DEFAULT_CAPTION_STROKE,
    CAPTION_STROKE_MAP,
)


# ── Shared test fixtures ──────────────────────────────────────────────────

def _make_theme() -> BrandTheme:
    return BrandTheme(
        primary_color="#FF0000",
        secondary_color="#FFFFFF",
        background_color="#000000",
        font_family="Montserrat",
        font_weight="700",
        font_size_vmin="4.0 vmin",
        logo_url=None,
        music_url=None,
    )


def _make_phrase_blocks() -> list[PhraseBlock]:
    return [
        PhraseBlock(text="This is the first phrase.", start=0.0, end=1.5),
        PhraseBlock(text="And here is the second one.", start=1.5, end=3.0),
        PhraseBlock(text="Finally the third.", start=3.0, end=4.5),
    ]


def _make_request(**kwargs) -> GenerateVideoRequest:
    defaults = {
        "template": "bullet-reel",
        "video_urls": ["https://example.com/v1.mp4", "https://example.com/v2.mp4"],
        "text_1": "Stop scrolling",
        "text_2": "Point one",
        "text_3": "Point two",
        "enable_captions": True,
    }
    defaults.update(kwargs)
    return GenerateVideoRequest(**defaults)


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

    def test_has_dark_pill_background(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert "background_color" in el
        assert "0,0,0" in el["background_color"]  # dark background for legibility

    def test_default_y_position(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0)
        assert el["y"] == "78%"

    def test_custom_y_position(self):
        el = _caption_elem(track=500, text="Hello", time=0.0, duration=1.0, y="65%")
        assert el["y"] == "65%"

    def test_minimum_duration_enforced(self):
        # Very short duration should be clamped to 0.1 (avoid zero-duration elements)
        el = _caption_elem(track=500, text="Hi", time=0.0, duration=0.0)
        assert el["duration"] >= 0.1

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
            assert len(block.text) <= 150, f"Block exceeded 150 chars: {len(block.text)}"


# ── End-to-end: builders receive phrase_blocks → produce caption elements ─

def _get_caption_elements(source: dict) -> list[dict]:
    """Extract elements that use the Anton caption font."""
    return [
        el for el in source["elements"]
        if el.get("type") == "text" and el.get("font_family") == "Anton"
    ]


class TestBuilderCaptionIntegration:
    """Verify each builder actually appends caption elements when phrase_blocks are passed."""

    def test_bullet_reel_includes_captions(self):
        request = _make_request(template="bullet-reel", clip_count=2)
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_bullet_reel(request, theme, phrase_blocks=blocks)
        captions = _get_caption_elements(source)

        # _MAX_CAPTION_WORDS=2 may split multi-word blocks → at least one element per block
        assert len(captions) >= len(blocks), "At least one caption element per phrase block"
        assert all(el["font_weight"] == "900" for el in captions)

    def test_bullet_reel_with_captions_shows_only_hook_text(self):
        """When captions are active, bullet text (text_2-6) is omitted to avoid collision."""
        request = _make_request(
            template="bullet-reel", clip_count=3,
            text_1="Stop scrolling", text_2="Point one", text_3="Point two",
        )
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_bullet_reel(request, theme, phrase_blocks=blocks)
        # Non-caption text elements (not Anton font)
        template_texts = [
            el for el in source["elements"]
            if el.get("type") == "text" and el.get("font_family") != "Anton"
        ]
        # Only the hook should be present
        assert len(template_texts) == 1
        assert template_texts[0]["name"] == "Hook"

    def test_bullet_reel_hook_in_top_zone_with_captions(self):
        request = _make_request(template="bullet-reel", clip_count=2, text_1="Watch this")
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_bullet_reel(request, theme, phrase_blocks=blocks)
        hook_els = [el for el in source["elements"] if el.get("name") == "Hook"]

        assert len(hook_els) == 1
        hook_y = float(hook_els[0]["y"].replace("%", ""))
        assert hook_y <= 30, f"Hook y={hook_els[0]['y']} exceeds top zone when captions enabled"

    def test_talking_head_includes_captions(self):
        request = _make_request(template="talking-head", clip_count=1)
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = _get_caption_elements(source)

        assert len(captions) >= len(blocks)

    def test_talking_head_captions_at_bottom_safe_zone(self):
        request = _make_request(template="talking-head", clip_count=1)
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = _get_caption_elements(source)

        for el in captions:
            y_pct = float(el["y"].replace("%", ""))
            assert y_pct >= 65, f"Caption y={el['y']} is above bottom safe zone"

    def test_talking_head_hook_at_top_zone(self):
        request = _make_request(
            template="talking-head", clip_count=1, text_1="Stop scrolling now"
        )
        theme = _make_theme()

        source = build_talking_head(request, theme)
        hook_els = [el for el in source["elements"] if el.get("name") == "Hook"]

        assert len(hook_els) == 1
        hook_y = float(hook_els[0]["y"].replace("%", ""))
        assert hook_y <= 20, f"Hook y={hook_els[0]['y']} exceeds top zone"

    def test_hook_reveal_includes_captions(self):
        request = _make_request(
            template="hook-reveal",
            video_urls=["https://example.com/v1.mp4"],
            text_1="You won't believe this",
            text_2="The answer is pelvic floor",
        )
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_hook_reveal(request, theme, phrase_blocks=blocks)
        captions = _get_caption_elements(source)

        assert len(captions) >= len(blocks)

    def test_hook_reveal_cta_moves_to_top_when_captions_present(self):
        """CTA band at y=83% would collide with captions at y=78%. Must move to top."""
        request = _make_request(
            template="hook-reveal",
            video_urls=["https://example.com/v1.mp4"],
            text_1="You won't believe this",
            text_2="The answer",
            text_3="Follow for more",
        )
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_hook_reveal(request, theme, phrase_blocks=blocks)
        cta_el = next((el for el in source["elements"] if el.get("name") == "CTA"), None)

        assert cta_el is not None
        cta_y = float(cta_el["y"].replace("%", ""))
        assert cta_y <= 30, f"CTA y={cta_el['y']} collides with caption zone when captions enabled"

    def test_hook_reveal_cta_uses_bottom_band_without_captions(self):
        """Without captions, CTA should use the original bottom band layout."""
        request = _make_request(
            template="hook-reveal",
            video_urls=["https://example.com/v1.mp4"],
            text_1="You won't believe this",
            text_2="The answer",
            text_3="Follow for more",
        )
        theme = _make_theme()

        source = build_hook_reveal(request, theme, phrase_blocks=None)
        cta_el = next((el for el in source["elements"] if el.get("name") == "CTA"), None)

        assert cta_el is not None
        cta_y = float(cta_el["y"].replace("%", ""))
        assert cta_y >= 70, f"Without captions, CTA should be in bottom zone, got y={cta_el['y']}"

    def test_edu_steps_includes_captions(self):
        request = _make_request(
            template="edu-steps",
            video_urls=["https://example.com/v1.mp4", "https://example.com/v2.mp4"],
            text_1="How to strengthen",
            text_2="Step one",
            text_3="Step two",
            clip_count=2,
        )
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_edu_steps(request, theme, phrase_blocks=blocks)
        captions = _get_caption_elements(source)

        assert len(captions) >= len(blocks)

    def test_edu_steps_text_moves_up_when_captions_present(self):
        """Step text at y=55% and step# at y=36% shift up when captions occupy bottom."""
        request = _make_request(
            template="edu-steps",
            video_urls=["https://example.com/v1.mp4", "https://example.com/v2.mp4"],
            text_1="How to strengthen",
            text_2="Step one",
            text_3="Step two",
            clip_count=2,
        )
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_edu_steps(request, theme, phrase_blocks=blocks)
        step_texts = [
            el for el in source["elements"]
            if el.get("name", "").startswith("Step-")
        ]
        step_nums = [
            el for el in source["elements"]
            if el.get("name", "").startswith("StepNum-")
        ]

        for el in step_texts:
            y = float(el["y"].replace("%", ""))
            assert y <= 55, f"Step text y={el['y']} too low when captions enabled"
        for el in step_nums:
            y = float(el["y"].replace("%", ""))
            assert y <= 30, f"Step number y={el['y']} too low when captions enabled"

    def test_no_template_text_below_65_percent_when_captions_enabled(self):
        """Regression: verify no template text element lands in the caption zone (y > 65%)."""
        for build_fn, kwargs in [
            (build_bullet_reel, {"template": "bullet-reel", "clip_count": 2}),
            (build_hook_reveal, {
                "template": "hook-reveal",
                "video_urls": ["https://example.com/v1.mp4"],
                "text_1": "Hook text", "text_2": "Reveal", "text_3": "CTA here",
            }),
            (build_edu_steps, {
                "template": "edu-steps",
                "video_urls": ["https://example.com/v1.mp4", "https://example.com/v2.mp4"],
                "text_1": "Title", "text_2": "Step one", "text_3": "Step two",
                "clip_count": 2,
            }),
        ]:
            request = _make_request(**kwargs)
            theme = _make_theme()
            blocks = _make_phrase_blocks()

            source = build_fn(request, theme, phrase_blocks=blocks)
            captions = _get_caption_elements(source)
            template_texts = [
                el for el in source["elements"]
                if el.get("type") == "text" and el not in captions
            ]

            for el in template_texts:
                y = float(el["y"].replace("%", ""))
                assert y <= 65, (
                    f"{build_fn.__name__}: element '{el.get('name')}' at y={el['y']} "
                    f"collides with caption zone (>65%)"
                )

    def test_no_captions_when_phrase_blocks_empty(self):
        request = _make_request(template="bullet-reel", clip_count=2)
        theme = _make_theme()

        source = build_bullet_reel(request, theme, phrase_blocks=[])
        captions = _get_caption_elements(source)

        assert captions == [], "No caption elements when phrase_blocks is empty"

    def test_caption_timing_matches_phrase_blocks(self):
        request = _make_request(template="bullet-reel", clip_count=2)
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_bullet_reel(request, theme, phrase_blocks=blocks)
        captions = sorted(_get_caption_elements(source), key=lambda e: e["time"])

        # Every phrase block start time must appear as the start of at least one caption
        caption_starts = {round(el["time"], 2) for el in captions}
        for block in blocks:
            assert round(block.start, 2) in caption_starts, (
                f"No caption found starting at block.start={block.start}"
            )

    def test_caption_tracks_dont_collide_with_template_tracks(self):
        """Caption elements use track 500+ so they don't collide with template elements."""
        request = _make_request(template="bullet-reel", clip_count=2)
        theme = _make_theme()
        blocks = _make_phrase_blocks()

        source = build_bullet_reel(request, theme, phrase_blocks=blocks)
        captions = _get_caption_elements(source)
        template_tracks = {
            el["track"] for el in source["elements"] if el not in captions
        }

        for cap in captions:
            assert cap["track"] not in template_tracks, (
                f"Caption track {cap['track']} collides with template element"
            )

    def test_all_builders_accept_phrase_blocks_via_router_pattern(self):
        """Regression: router passes phrase_blocks only to builders that accept it.
        All builders must be callable via the inspect-based dispatch without TypeError.
        """
        import inspect
        from app.models.video import VideoTemplate

        blocks = _make_phrase_blocks()
        theme = _make_theme()

        for template_enum, builder in RENDERSCRIPT_BUILDERS.items():
            request = GenerateVideoRequest(
                template=template_enum.value,
                video_urls=["https://example.com/v1.mp4", "https://example.com/v2.mp4"],
                text_1="Hook text",
                text_2="Point one",
                text_3="Point two",
                enable_captions=True,
            )
            # This is the exact pattern used in the router
            _bkw = (
                {"phrase_blocks": blocks}
                if "phrase_blocks" in inspect.signature(builder).parameters
                else {}
            )
            # Must not raise TypeError regardless of whether the builder supports captions
            source = builder(request, theme, None, **_bkw)
            assert "elements" in source, f"{builder.__name__} did not return a valid source dict"


# ── Karaoke word-level pipeline ───────────────────────────────────────────

class TestGroupWordsIntoKaraokeBlocks:
    def test_one_word_per_block(self):
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.3},
            {"word": "everyone", "start": 0.3, "end": 0.7},
            {"word": "today", "start": 0.7, "end": 1.0},
            {"word": "we", "start": 1.0, "end": 1.2},
        ]
        blocks = _group_words_into_karaoke_blocks(words)
        assert len(blocks) == 4
        assert blocks[0].text == "Hello"
        assert blocks[1].text == "everyone"
        assert blocks[2].text == "today"
        assert blocks[3].text == "we"

    def test_timestamps_come_from_words(self):
        words = [
            {"word": "Start", "start": 2.5, "end": 2.9},
            {"word": "here", "start": 2.9, "end": 3.4},
        ]
        blocks = _group_words_into_karaoke_blocks(words)
        # 1 word per block → 2 blocks
        assert blocks[0].start == pytest.approx(2.5, abs=0.01)
        assert blocks[0].end == pytest.approx(2.9, abs=0.1)
        assert blocks[1].start == pytest.approx(2.9, abs=0.01)
        assert blocks[1].end == pytest.approx(3.4, abs=0.1)

    def test_minimum_duration_enforced(self):
        # Two words with very short duration — should be clamped
        words = [
            {"word": "fast", "start": 0.0, "end": 0.1},
            {"word": "word", "start": 0.1, "end": 0.15},
        ]
        blocks = _group_words_into_karaoke_blocks(words)
        assert blocks[0].end - blocks[0].start >= 0.3

    def test_empty_words_returns_empty(self):
        assert _group_words_into_karaoke_blocks([]) == []

    def test_skips_empty_word_strings(self):
        words = [
            {"word": "", "start": 0.0, "end": 0.3},
            {"word": "Hello", "start": 0.3, "end": 0.7},
            {"word": "world", "start": 0.7, "end": 1.0},
        ]
        blocks = _group_words_into_karaoke_blocks(words)
        assert all(b.text.strip() for b in blocks)


class TestTranscriptionServiceKaraoke:
    @pytest.mark.asyncio
    async def test_prefers_word_timestamps_over_segments(self):
        """When word_timestamps are present, karaoke path is used (1-word blocks)."""
        mock_result = VideoAnalysisResult(
            duration_seconds=5.0,
            word_timestamps=[
                {"word": "Hello", "start": 0.0, "end": 0.4},
                {"word": "everyone", "start": 0.4, "end": 0.9},
                {"word": "welcome", "start": 0.9, "end": 1.4},
                {"word": "here", "start": 1.4, "end": 1.8},
            ],
            transcript_segments=[
                {"text": "Hello everyone welcome here", "start": 0.0, "end": 1.8},
            ],
        )
        with patch(
            "app.services.transcription_service.VideoAnalysisService.analyze_for_talking_head",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            service = TranscriptionService()
            blocks = await service.transcribe("https://example.com/video.mp4")

        # Karaoke path → 1 word per block (4 words → 4 blocks)
        assert len(blocks) == 4
        assert blocks[0].text == "Hello"
        assert blocks[1].text == "everyone"

    @pytest.mark.asyncio
    async def test_falls_back_to_segments_when_no_words(self):
        """When word_timestamps is None, falls back to phrase grouping."""
        mock_result = VideoAnalysisResult(
            duration_seconds=5.0,
            word_timestamps=None,
            transcript_segments=[
                {"text": "Hello everyone.", "start": 0.0, "end": 1.0},
                {"text": "Welcome here.", "start": 1.0, "end": 2.0},
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
        # Phrase path — blocks contain full sentences
        assert all(len(b.text) > 2 for b in blocks)

    @pytest.mark.asyncio
    async def test_karaoke_blocks_have_accurate_timestamps(self):
        """Each karaoke block's start/end should match the word timestamps from Gemini."""
        mock_result = VideoAnalysisResult(
            duration_seconds=3.0,
            word_timestamps=[
                {"word": "Doctor", "start": 0.5, "end": 0.9},
                {"word": "explica", "start": 0.9, "end": 1.3},
                {"word": "cómo", "start": 1.3, "end": 1.6},
                {"word": "funciona", "start": 1.6, "end": 2.1},
            ],
        )
        with patch(
            "app.services.transcription_service.VideoAnalysisService.analyze_for_talking_head",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            service = TranscriptionService()
            blocks = await service.transcribe("https://example.com/video.mp4")

        # 4 words → 4 blocks (1 word each)
        assert len(blocks) == 4
        assert blocks[0].start == pytest.approx(0.5, abs=0.01)
        assert blocks[0].text == "Doctor"
        assert blocks[2].start == pytest.approx(1.3, abs=0.01)
        assert blocks[2].text == "cómo"


class TestTalkingHeadCaptionFont:
    """Verify caption_font is applied in all three rendering paths."""

    def test_phrase_blocks_path_applies_custom_font(self):
        request = _make_request(template="talking-head", clip_count=1, caption_font="Oswald")
        theme = _make_theme()
        blocks = [PhraseBlock(text="Doctor explica cómo", start=0.0, end=1.5)]

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = [el for el in source["elements"] if el.get("type") == "text" and el.get("font_family") == "Oswald"]

        assert len(captions) >= 1, "caption_font=Oswald not applied in phrase_blocks path"

    def test_legacy_segments_path_applies_custom_font(self):
        """Legacy Gemini segments path must also use caption_font."""
        from unittest.mock import MagicMock
        request = _make_request(template="talking-head", clip_count=1, caption_font="Bebas Neue")
        theme = _make_theme()

        analysis = MagicMock()
        analysis.duration_seconds = 5.0
        analysis.transcript_segments = [
            {"text": "Hello world", "start": 0.0, "end": 1.0},
            {"text": "testing now", "start": 1.0, "end": 2.0},
        ]

        source = build_talking_head(request, theme, analysis=analysis, phrase_blocks=None)
        captions = [
            el for el in source["elements"]
            if el.get("type") == "text" and el.get("font_family") == "Bebas Neue"
        ]

        assert len(captions) >= 1, "caption_font=Bebas Neue not applied in legacy segments path"

    def test_fallback_text2_path_applies_custom_font(self):
        """Fallback text_2 path must also use caption_font."""
        request = _make_request(
            template="talking-head", clip_count=1,
            caption_font="Kanit", text_2="This is my caption text for the video"
        )
        theme = _make_theme()

        source = build_talking_head(request, theme, analysis=None, phrase_blocks=None)
        captions = [
            el for el in source["elements"]
            if el.get("type") == "text" and el.get("font_family") == "Kanit"
        ]

        assert len(captions) >= 1, "caption_font=Kanit not applied in fallback text_2 path"

    def test_defaults_to_anton_when_no_font_specified(self):
        request = _make_request(template="talking-head", clip_count=1)
        theme = _make_theme()
        blocks = [PhraseBlock(text="Hello world", start=0.0, end=1.5)]

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = [el for el in source["elements"] if el.get("type") == "text" and el.get("font_family") == "Anton"]

        assert len(captions) >= 1, "Should default to Anton when no caption_font specified"


# ── Talking Head v2 ───────────────────────────────────────────────────────

def _v2_captions(source: dict) -> list[dict]:
    """Extract karaoke caption elements from a v2 renderscript (named Sub-NNN)."""
    return [
        el for el in source["elements"]
        if el.get("type") == "text" and (el.get("name") or "").startswith("Sub-")
    ]


class TestTalkingHeadV2:
    """Verify Talking Head Pro (v2) builder: title card + word-by-word karaoke."""

    def test_title_is_centered_and_lasts_3s(self):
        request = _make_request(template="talking-head-v2", clip_count=1, text_1="My title here")
        theme = _make_theme()

        source = build_talking_head_v2(request, theme)
        title_els = [el for el in source["elements"] if el.get("name") == "Title"]

        assert len(title_els) == 1
        title = title_els[0]
        assert title["y"] == "50%", "Title must be vertically centered"
        assert title["x"] == "50%", "Title must be horizontally centered"
        assert title["duration"] == pytest.approx(3.0), "Title must show for 3s"

    def test_no_title_element_when_text1_empty(self):
        request = _make_request(template="talking-head-v2", clip_count=1, text_1="")
        theme = _make_theme()

        source = build_talking_head_v2(request, theme)
        title_els = [el for el in source["elements"] if el.get("name") == "Title"]

        assert len(title_els) == 0

    def test_captions_centered_on_screen(self):
        request = _make_request(template="talking-head-v2", clip_count=1)
        theme = _make_theme()
        blocks = [
            PhraseBlock(text="Hello world", start=4.0, end=5.5),
            PhraseBlock(text="Testing now", start=5.5, end=7.0),
        ]

        source = build_talking_head_v2(request, theme, phrase_blocks=blocks)
        captions = _v2_captions(source)

        for el in captions:
            assert el["y"] == "50%", f"Caption y={el['y']} must be centered (50%)"

    def test_captions_use_poppins_by_default(self):
        request = _make_request(template="talking-head-v2", clip_count=1)
        theme = _make_theme()
        blocks = [PhraseBlock(text="Hello everyone", start=4.0, end=5.5)]

        source = build_talking_head_v2(request, theme, phrase_blocks=blocks)
        captions = _v2_captions(source)

        assert len(captions) >= 1
        for el in captions:
            assert el["font_family"] == "Poppins", f"Expected Poppins, got {el['font_family']}"

    def test_captions_skip_title_window(self):
        """Phrase blocks inside the 3s title window must not appear as captions."""
        request = _make_request(template="talking-head-v2", clip_count=1, text_1="Title")
        theme = _make_theme()
        blocks = [
            PhraseBlock(text="Too early", start=0.5, end=2.0),   # inside 0-3s title window
            PhraseBlock(text="After title", start=3.5, end=5.0),  # after title → should appear
        ]

        source = build_talking_head_v2(request, theme, phrase_blocks=blocks)
        captions = _v2_captions(source)

        # No caption should start before 3.0s
        for el in captions:
            assert el["time"] >= 3.0, f"Caption at {el['time']}s falls inside title window"

    def test_captions_are_word_level(self):
        """Each phrase block must be split into individual word elements."""
        request = _make_request(template="talking-head-v2", clip_count=1, text_1="")
        theme = _make_theme()
        # 3 words → expect 3 caption elements
        blocks = [PhraseBlock(text="one two three", start=0.0, end=3.0)]

        source = build_talking_head_v2(request, theme, phrase_blocks=blocks)
        captions = _v2_captions(source)

        assert len(captions) == 3, f"Expected 3 word elements, got {len(captions)}"
        texts = [el["text"] for el in captions]
        assert texts == ["one", "two", "three"]

    def test_caption_font_respected(self):
        request = _make_request(template="talking-head-v2", clip_count=1, caption_font="Montserrat")
        theme = _make_theme()
        blocks = [PhraseBlock(text="Hello world", start=4.0, end=5.5)]

        source = build_talking_head_v2(request, theme, phrase_blocks=blocks)
        captions = _v2_captions(source)

        assert len(captions) >= 1
        for el in captions:
            assert el["font_family"] == "Montserrat"

    def test_registered_in_dispatch_table(self):
        from app.models.video import VideoTemplate
        assert VideoTemplate.TALKING_HEAD_V2 in RENDERSCRIPT_BUILDERS


# ── Caption color and stroke propagation ──────────────────────────────────

def _get_talking_head_captions(source: dict) -> list[dict]:
    """Extract caption elements from a talking-head renderscript (Anton font or Sub- name)."""
    return [
        el for el in source["elements"]
        if el.get("type") == "text" and (
            el.get("font_family") == "Anton"
            or (el.get("name") or "").startswith("Sub-")
        )
    ]


class TestCaptionColorAndStroke:
    def test_caption_color_propagates_to_creatomate(self):
        request = _make_request(
            template="talking-head", clip_count=1, caption_color="#FF00FF"
        )
        theme = _make_theme()
        blocks = [
            PhraseBlock(text="Doctor explica cómo", start=0.0, end=1.5),
            PhraseBlock(text="funciona el suelo", start=1.5, end=3.0),
        ]

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = _get_talking_head_captions(source)

        assert len(captions) >= 1
        for el in captions:
            assert el.get("fill_color") != DEFAULT_CAPTION_COLOR, (
                f"Caption still has hardcoded {DEFAULT_CAPTION_COLOR}"
            )
            assert el.get("fill_color") == "#FF00FF", (
                f"Expected #FF00FF, got {el.get('fill_color')}"
            )

    def test_caption_stroke_thin_maps_to_1vmin(self):
        request = _make_request(
            template="talking-head", clip_count=1, caption_stroke="thin"
        )
        theme = _make_theme()
        blocks = [
            PhraseBlock(text="Thin stroke test", start=0.0, end=1.5),
        ]

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = _get_talking_head_captions(source)

        assert len(captions) >= 1
        for el in captions:
            assert el.get("stroke_width") == CAPTION_STROKE_MAP["thin"], (
                f"Expected {CAPTION_STROKE_MAP['thin']}, got {el.get('stroke_width')}"
            )

    def test_caption_stroke_thick_maps_to_2vmin(self):
        request = _make_request(
            template="talking-head", clip_count=1, caption_stroke="thick"
        )
        theme = _make_theme()
        blocks = [
            PhraseBlock(text="Thick stroke test", start=0.0, end=1.5),
        ]

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = _get_talking_head_captions(source)

        assert len(captions) >= 1
        for el in captions:
            assert el.get("stroke_width") == CAPTION_STROKE_MAP["thick"], (
                f"Expected {CAPTION_STROKE_MAP['thick']}, got {el.get('stroke_width')}"
            )

    def test_legacy_request_without_stroke_uses_default(self):
        request = _make_request(
            template="talking-head", clip_count=1
        )
        theme = _make_theme()
        blocks = [
            PhraseBlock(text="Default stroke test", start=0.0, end=1.5),
        ]

        source = build_talking_head(request, theme, phrase_blocks=blocks)
        captions = _get_talking_head_captions(source)

        assert len(captions) >= 1
        for el in captions:
            assert el.get("stroke_width") == DEFAULT_CAPTION_STROKE, (
                f"Expected {DEFAULT_CAPTION_STROKE}, got {el.get('stroke_width')}"
            )
