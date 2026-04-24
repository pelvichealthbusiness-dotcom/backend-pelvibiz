"""Utilities for formatting Instagram captions before saving to DB."""

import re


_MAX_HASHTAGS = 3


def _extract_hashtags(text: str) -> list[str]:
    return re.findall(r"#\w+", text)


def _strip_hashtags(text: str) -> str:
    return re.sub(r"\s*#\w+", "", text).strip()


def format_caption(caption: str) -> str:
    """Normalize an Instagram caption for real video.

    Rules applied:
    - Collapse 3+ consecutive blank lines to 2
    - Ensure the hashtag block is on its own line at the end
    - Cap hashtags at _MAX_HASHTAGS (keep the first N)
    - Remove trailing whitespace per line
    """
    if not caption or not caption.strip():
        return caption

    # Separate hashtag tokens from body
    hashtags = _extract_hashtags(caption)
    body = _strip_hashtags(caption)

    # Collapse excessive blank lines in body
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # Ensure single blank line between logical blocks (hook / body / cta)
    # Lines that are short (≤ 80 chars) and end without punctuation often act
    # as block separators — leave them as-is; don't add extra structure.

    # Trim trailing whitespace per line
    lines = [line.rstrip() for line in body.splitlines()]
    body = "\n".join(lines)

    # Cap hashtags
    kept = hashtags[:_MAX_HASHTAGS]

    if kept:
        hashtag_line = " ".join(kept)
        return f"{body}\n\n{hashtag_line}"
    return body
