"""Montserrat font download and caching utility.

Downloads Montserrat-Regular and Montserrat-Black from Google Fonts on first use
and caches them in /tmp/pelvibiz_fonts/ for the process lifetime.
"""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from pathlib import Path

import httpx
from PIL import ImageFont

logger = logging.getLogger(__name__)

FONT_CACHE_DIR = Path("/tmp/pelvibiz_fonts")
_MONTSERRAT_ZIP_URL = "https://fonts.google.com/download?family=Montserrat"

_download_lock = asyncio.Lock()
_fonts_ready = False


async def _ensure_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return

    regular_path = FONT_CACHE_DIR / "Montserrat-Regular.ttf"
    black_path = FONT_CACHE_DIR / "Montserrat-Black.ttf"

    if regular_path.exists() and black_path.exists():
        _fonts_ready = True
        return

    FONT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading Montserrat fonts from Google Fonts...")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(_MONTSERRAT_ZIP_URL)
        resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        for name in z.namelist():
            basename = Path(name).name
            if basename in ("Montserrat-Regular.ttf", "Montserrat-Black.ttf"):
                target = FONT_CACHE_DIR / basename
                target.write_bytes(z.read(name))
                logger.info("Extracted font: %s", basename)

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
