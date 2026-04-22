"""Montserrat font loader.

Reads bundled TTF files from the repo's /fonts directory.
No network download required — fonts ship with the application.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import ImageFont

logger = logging.getLogger(__name__)

# Repo root is 3 levels up from app/utils/fonts.py
_FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"

_WEIGHT_MAP: dict[str, str] = {
    "regular": "Montserrat-Regular.ttf",
    "semibold": "Montserrat-SemiBold.ttf",
    "bold": "Montserrat-Bold.ttf",
    "bold_italic": "Montserrat-BoldItalic.ttf",
    "black": "Montserrat-Black.ttf",
    "script": "GreatVibes-Regular.ttf",
}

_FALLBACK: dict[str, str] = {
    "Montserrat-Black.ttf": "Montserrat-Bold.ttf",
}


def get_montserrat_sync(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Return a Montserrat font for the given weight and pixel size (sync).

    Parameters
    ----------
    weight:
        ``'regular'``, ``'bold'``, or ``'black'``.
    size:
        Font size in pixels.
    """
    filename = _WEIGHT_MAP.get(weight, "Montserrat-Regular.ttf")
    path = _FONTS_DIR / filename

    if not path.exists():
        fallback = _FALLBACK.get(filename)
        if fallback:
            logger.warning("%s not found, falling back to %s", filename, fallback)
            path = _FONTS_DIR / fallback
        if not path.exists():
            raise FileNotFoundError(f"Font not found: {path}")

    return ImageFont.truetype(str(path), size)


async def get_montserrat(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Async wrapper — fonts are local so no I/O wait needed."""
    return get_montserrat_sync(weight, size)
