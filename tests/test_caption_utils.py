"""Tests for caption_utils.format_caption()."""

from app.utils.caption_utils import format_caption


class TestFormatCaption:
    def test_caps_hashtags_at_3(self):
        caption = "Great tip!\n\n#pelvicfloor #health #wellness #fitness #women"
        result = format_caption(caption)
        hashtags = [w for w in result.split() if w.startswith("#")]
        assert len(hashtags) == 3

    def test_keeps_fewer_than_3_hashtags(self):
        caption = "Great tip!\n\n#pelvicfloor #health"
        result = format_caption(caption)
        hashtags = [w for w in result.split() if w.startswith("#")]
        assert len(hashtags) == 2

    def test_hashtags_moved_to_own_line(self):
        caption = "Your body matters. Start today. #health #pelvicfloor #women"
        result = format_caption(caption)
        lines = result.strip().splitlines()
        last_line = lines[-1]
        assert last_line.startswith("#")

    def test_collapses_excessive_blank_lines(self):
        caption = "Hook line.\n\n\n\nBody text here.\n\n\n\nCTA here."
        result = format_caption(caption)
        assert "\n\n\n" not in result

    def test_blank_caption_returns_as_is(self):
        assert format_caption("") == ""
        assert format_caption("   ") == "   "

    def test_hashtag_block_separated_by_blank_line(self):
        caption = "Hook.\n\nBody text.\n\nCTA here.\n\n#a #b #c"
        result = format_caption(caption)
        parts = result.rsplit("\n\n", 1)
        assert len(parts) == 2
        assert parts[1].startswith("#")

    def test_no_hashtags_no_trailing_blank(self):
        caption = "Just a caption with no hashtags."
        result = format_caption(caption)
        assert not result.endswith("\n")

    def test_trailing_whitespace_stripped_per_line(self):
        caption = "Line one.   \nLine two.   \n\n#health   "
        result = format_caption(caption)
        for line in result.splitlines():
            assert line == line.rstrip()
