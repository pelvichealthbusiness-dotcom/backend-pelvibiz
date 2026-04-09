"""Image quality validation service — PIL pixel-based analysis.

Validates generated images before upload. Returns (passed, failures).
No Gemini Vision calls — uses fast PIL operations only (~50-100ms per image).
"""
from __future__ import annotations

import logging
from PIL import Image, ImageFilter, ImageStat

logger = logging.getLogger(__name__)


class ImageQA:
    """Lightweight PIL-based image quality checker."""

    # Thresholds
    MIN_EDGE_MEAN = 4.0        # Below = blurry/featureless
    MIN_BRIGHTNESS = 20        # Below = too dark
    MAX_BRIGHTNESS = 240       # Above = washed out / mostly white
    MAX_BOTTOM_BRIGHTNESS = 230  # Bottom strip — if too bright, likely white patch
    MAX_CORNER_SPREAD = 45     # Card corner color spread — above = not solid background

    def check(
        self,
        img: Image.Image,
        slide_type: str,
    ) -> tuple[bool, list[str]]:
        """Run all QA checks. Returns (passed, list_of_failure_messages)."""
        failures: list[str] = []

        try:
            rgb = img.convert("RGB")

            # 1. Blur detection via edge density
            edges = rgb.filter(ImageFilter.FIND_EDGES).convert("L")
            edge_mean = ImageStat.Stat(edges).mean[0]
            if edge_mean < self.MIN_EDGE_MEAN:
                failures.append(
                    f"Image too blurry or featureless (edge_mean={edge_mean:.1f}, min={self.MIN_EDGE_MEAN})"
                )

            # 2. Brightness range
            brightness = ImageStat.Stat(rgb.convert("L")).mean[0]
            if brightness < self.MIN_BRIGHTNESS:
                failures.append(f"Image too dark (brightness={brightness:.0f})")
            elif brightness > self.MAX_BRIGHTNESS:
                failures.append(f"Image washed out (brightness={brightness:.0f})")

            # 3. Bottom white patch — generic/face slides only
            if slide_type in ("generic", "face"):
                bottom = rgb.crop((0, img.height - 150, img.width, img.height))
                bottom_brightness = ImageStat.Stat(bottom.convert("L")).mean[0]
                if bottom_brightness > self.MAX_BOTTOM_BRIGHTNESS:
                    failures.append(
                        f"Bottom of image is white/blank (brightness={bottom_brightness:.0f}) — "
                        "background not complete"
                    )

            # 4. Card solid background check — corners must have similar color
            if slide_type == "card":
                margin = 80
                corners = [
                    rgb.crop((0, 0, margin, margin)),
                    rgb.crop((img.width - margin, 0, img.width, margin)),
                    rgb.crop((0, img.height - 180, margin, img.height - 100)),
                    rgb.crop((img.width - margin, img.height - 180, img.width, img.height - 100)),
                ]
                corner_means = [ImageStat.Stat(c).mean for c in corners]
                for ch in range(3):
                    vals = [m[ch] for m in corner_means]
                    spread = max(vals) - min(vals)
                    if spread > self.MAX_CORNER_SPREAD:
                        failures.append(
                            f"Card background not solid — corner color spread too high "
                            f"(channel {ch}, spread={spread:.0f}, max={self.MAX_CORNER_SPREAD})"
                        )
                        break  # One channel failure is enough

        except Exception as exc:
            logger.warning("ImageQA check error (skipping QA): %s", exc)
            return True, []  # Fail open — don't block generation on QA errors

        passed = len(failures) == 0
        if not passed:
            logger.warning("ImageQA failed: %s", "; ".join(failures))
        return passed, failures
