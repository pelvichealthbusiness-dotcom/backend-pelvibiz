from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Verified Creatomate font names — keyword matching from brand font_prompt
FONT_MAP: dict[str, str] = {
    "montserrat": "Montserrat",
    "roboto": "Roboto",
    "open sans": "Open Sans",
    "playfair": "Playfair Display",
    "lato": "Lato",
    "poppins": "Poppins",
    "raleway": "Raleway",
    "oswald": "Oswald",
    "inter": "Inter",
    "nunito": "Nunito",
    "ubuntu": "Ubuntu",
    "merriweather": "Merriweather",
    "source sans": "Source Sans Pro",
    "work sans": "Work Sans",
    "pt sans": "PT Sans",
    "bebas": "Bebas Neue",
    "barlow": "Barlow Condensed",
    "cormorant": "Cormorant Garamond",
    # Descriptive keyword mappings
    "geometric": "Montserrat",
    "humanist": "Open Sans",
    "slab": "Roboto Slab",
    "serif": "Playfair Display",
    "mono": "Roboto Mono",
    "rounded": "Nunito",
    "condensed": "Barlow Condensed",
    "elegant": "Cormorant Garamond",
    "sans": "Montserrat",
    "bold": "Oswald",
    "clean": "Inter",
    "modern": "Poppins",
    "minimal": "Inter",
    "script": "Raleway",
    # Heavy / display fonts (OpusClip-style captions)
    "anton": "Anton",
    "kanit": "Kanit",
    "impact": "Bebas Neue",
    "heavy": "Anton",
    "black": "Anton",
    "opusclip": "Anton",
    "caption": "Anton",
}

# Default font for auto-generated captions.
# Montserrat at weight 900 gives a clean, modern look suitable for healthcare content.
CAPTION_FONT = "Montserrat"


@dataclass
class BrandTheme:
    primary_color: str      # hex, e.g. "#D62828" — accent elements, CTA text
    secondary_color: str    # hex, e.g. "#FFFFFF" — body text, secondary panels
    background_color: str   # hex, e.g. "#0D0D0D" — dark overlay rectangles
    font_family: str        # Creatomate font name, e.g. "Montserrat"
    font_weight: str        # e.g. "700"
    font_size_vmin: str     # e.g. "5.0 vmin"
    logo_url: Optional[str]   # None → logo element omitted from composition
    music_url: Optional[str]  # None → audio element omitted from composition
    music_volume: float = 40.0  # 0–100, sent to Creatomate as "{n}%"


def resolve_theme(profile: dict, music_url: Optional[str] = None,
                  music_volume: float = 40.0) -> BrandTheme:
    """
    Build a BrandTheme from a user profile dict.
    Guarantees non-null values for all 6 visual properties via fallback cascade.
    Pure function — no I/O, no side effects.
    """
    return BrandTheme(
        primary_color=profile.get("brand_color_primary") or "#1A1A2E",
        secondary_color=profile.get("brand_color_secondary") or "#FFFFFF",
        background_color=profile.get("brand_color_background") or "#0D0D0D",
        font_family=_resolve_font(profile.get("font_prompt") or profile.get("font_style")),
        font_weight=_resolve_weight(profile.get("font_style")),
        font_size_vmin=_px_to_vmin(profile.get("font_size")),
        logo_url=profile.get("logo_url") or None,
        music_url=music_url or None,
        music_volume=music_volume,
    )


def _resolve_font(font_hint: Optional[str]) -> str:
    """Match font_prompt keywords against verified Creatomate font names."""
    if not font_hint:
        return "Montserrat"
    lower = font_hint.lower()
    for keyword, creatomate_name in FONT_MAP.items():
        if keyword in lower:
            return creatomate_name
    logger.warning(
        "[BrandTheme] No font match for hint '%.50s', defaulting to Montserrat", font_hint
    )
    return "Montserrat"


def _resolve_weight(font_style: Optional[str]) -> str:
    """Map font_style description to a CSS numeric font weight."""
    if not font_style:
        return "700"
    lower = font_style.lower()
    if "thin" in lower or "light" in lower:
        return "300"
    if "regular" in lower or "normal" in lower:
        return "400"
    if "semibold" in lower or "medium" in lower:
        return "600"
    if "black" in lower or "extrabold" in lower:
        return "900"
    return "700"


def _px_to_vmin(font_size: Optional[str | int]) -> str:
    """Convert a pixel font size to vmin units (1080px canvas). Clamps to [2.5, 8.0]."""
    if not font_size:
        return "4.0 vmin"
    try:
        px = int(str(font_size).replace("px", "").strip())
        vmin = round(px / 1080 * 100, 1)
        vmin = max(2.5, min(8.0, vmin))
        return f"{vmin} vmin"
    except (ValueError, TypeError):
        return "4.0 vmin"
