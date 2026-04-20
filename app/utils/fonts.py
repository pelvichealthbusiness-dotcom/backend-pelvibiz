"""Montserrat font download and caching utility.

Downloads Montserrat-Regular and Montserrat-Black from Google Fonts on first use
and caches them in /tmp/pelvibiz_fonts/ for the process lifetime.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx
from PIL import ImageFont

logger = logging.getLogger(__name__)

FONT_CACHE_DIR = Path("/tmp/pelvibiz_fonts")

# Direct TTF downloads from the official Google Fonts GitHub repo
_FONT_URLS: dict[str, str] = {
    "Montserrat-Regular.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Regular.ttf"
    ),
    "Montserrat-Black.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Black.ttf"
    ),
}

_download_lock = asyncio.Lock()
_fonts_ready = False


async def _ensure_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return

    all_cached = all((FONT_CACHE_DIR / fname).exists() for fname in _FONT_URLS)
    if all_cached:
        _fonts_ready = True
        return

    FONT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for filename, url in _FONT_URLS.items():
            target = FONT_CACHE_DIR / filename
            if target.exists():
                continue
            logger.info("Downloading font %s ...", filename)
            resp = await client.get(url)
            resp.raise_for_status()
            target.write_bytes(resp.content)
            logger.info("Font cached: %s (%d bytes)", filename, len(resp.content))

    _fonts_ready = True


async def get_montserrat(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Return a Montserrat font for the given weight and pixel size.

    Parameters
    ----------
    weight:
        ``'regular'`` (400) or ``'black'`` (900).
    size:
        Font size in pixels.
    """
    async with _download_lock:
        await _ensure_fonts()

    filename = "Montserrat-Regular.ttf" if weight == "regular" else "Montserrat-Black.ttf"
    path = FONT_CACHE_DIR / filename
    return ImageFont.truetype(str(path), size)
