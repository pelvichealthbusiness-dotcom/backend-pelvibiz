import io
import time
import logging
import httpx
from PIL import Image

logger = logging.getLogger(__name__)

# In-memory logo cache: {user_id: (Image, timestamp)}
_logo_cache: dict[str, tuple[Image.Image, float]] = {}
_CACHE_TTL = 600  # 10 minutes


class WatermarkService:
    def __init__(self):
        self.target_width_ratio = 0.085  # Logo = 8.5% of image width
        self.opacity = int(255 * 0.70)  # 70% opacity
        self.margin = 40  # px from edges

    async def apply(self, image_bytes: bytes, logo_url: str | None, user_id: str = "") -> bytes:
        """Apply logo watermark to image. Returns original if no logo or on error."""
        if not logo_url:
            return image_bytes

        try:
            logo = await self._get_logo(logo_url, user_id)
            if logo is None:
                return image_bytes

            # Open the generated image
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

            # Resize logo to target width ratio
            target_logo_width = int(img.width * self.target_width_ratio)
            aspect = logo.height / logo.width
            target_logo_height = int(target_logo_width * aspect)
            logo_resized = logo.resize((target_logo_width, target_logo_height), Image.LANCZOS)

            # Apply opacity
            if logo_resized.mode == "RGBA":
                r, g, b, a = logo_resized.split()
                a = a.point(lambda x: min(x, self.opacity))
                logo_resized = Image.merge("RGBA", (r, g, b, a))
            else:
                logo_resized = logo_resized.convert("RGBA")
                r, g, b, a = logo_resized.split()
                a = a.point(lambda _: self.opacity)
                logo_resized = Image.merge("RGBA", (r, g, b, a))

            # Position: bottom-center with margin
            x = (img.width - target_logo_width) // 2  # centered
            y = img.height - target_logo_height - self.margin

            # Composite
            img.paste(logo_resized, (x, y), logo_resized)

            # Convert back to bytes (PNG)
            output = io.BytesIO()
            img.save(output, format="PNG", quality=95)
            return output.getvalue()

        except Exception as e:
            logger.warning(f"Watermark failed, returning original: {e}")
            return image_bytes

    async def _get_logo(self, url: str, user_id: str) -> Image.Image | None:
        """Fetch logo with caching."""
        cache_key = user_id or url
        now = time.time()

        if cache_key in _logo_cache:
            cached_logo, ts = _logo_cache[cache_key]
            if now - ts < _CACHE_TTL:
                return cached_logo.copy()

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()

            logo = Image.open(io.BytesIO(response.content)).convert("RGBA")
            _logo_cache[cache_key] = (logo, now)
            return logo.copy()
        except Exception as e:
            logger.warning(f"Failed to fetch logo from {url}: {e}")
            return None
