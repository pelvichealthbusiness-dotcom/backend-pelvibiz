import asyncio
import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

class ImageGeneratorService:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.google_gemini_api_key
        self.endpoint = settings.gemini_endpoint
        self.timeout = settings.gemini_timeout
        self.max_retries = settings.gemini_max_retries
        self.image_download_timeout = settings.image_download_timeout
        self.max_image_size = settings.max_image_size_mb * 1024 * 1024

    async def download_image_as_base64(self, url: str) -> str:
        """Download image from URL and return as base64."""
        import base64
        async with httpx.AsyncClient(timeout=self.image_download_timeout) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            
            if len(response.content) > self.max_image_size:
                raise ValueError(f"Image too large: {len(response.content)} bytes")
            
            return base64.b64encode(response.content).decode("utf-8")

    async def generate_slide(self, prompt: str, image_base64: str) -> str:
        """Call Gemini API to generate slide image. Returns base64 of generated image."""
        url = f"{self.endpoint}?key={self.api_key}"
        
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": "image/jpeg", "data": image_base64}},
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }

        last_error: Exception | None = None
        
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        url,
                        json=body,
                        headers={"Content-Type": "application/json"},
                    )
                
                if response.status_code in (429, 500, 503) and attempt < self.max_retries:
                    logger.warning(f"Gemini attempt {attempt+1} failed ({response.status_code}), retrying...")
                    await asyncio.sleep(2)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                candidates = data.get("candidates", [])
                if not candidates:
                    if attempt < self.max_retries:
                        logger.warning(f"Gemini returned no candidates (attempt {attempt+1}), retrying...")
                        await asyncio.sleep(2)
                        continue
                    raise ValueError("Gemini returned no candidates")
                
                parts = candidates[0].get("content", {}).get("parts", [])
                image_part = next((p for p in parts if "inlineData" in p), None)
                
                if not image_part:
                    if attempt < self.max_retries:
                        logger.warning(f"Gemini returned no image (attempt {attempt+1}), retrying...")
                        await asyncio.sleep(2)
                        continue
                    raise ValueError("Gemini response did not contain an image")
                
                return image_part["inlineData"]["data"]
                
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning(f"Gemini timeout (attempt {attempt+1}), retrying...")
                    await asyncio.sleep(2)
                    continue
            except Exception as e:
                last_error = e
                if attempt < self.max_retries and not isinstance(e, ValueError):
                    await asyncio.sleep(2)
                    continue
                break

        raise last_error or ValueError("Gemini generation failed after all retries")

    async def generate_from_prompt(self, prompt: str) -> str:
        """Call Gemini with text-only prompt (no source image). Returns base64."""
        url = f"{self.endpoint}?key={self.api_key}"

        body = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        url,
                        json=body,
                        headers={"Content-Type": "application/json"},
                    )

                if response.status_code in (429, 500, 503) and attempt < self.max_retries:
                    logger.warning(f"Gemini text-only attempt {attempt+1} failed ({response.status_code}), retrying...")
                    await asyncio.sleep(2)
                    continue

                response.raise_for_status()
                data = response.json()

                candidates = data.get("candidates", [])
                if not candidates:
                    if attempt < self.max_retries:
                        await asyncio.sleep(2)
                        continue
                    raise ValueError("Gemini returned no candidates")

                parts = candidates[0].get("content", {}).get("parts", [])
                image_part = next((p for p in parts if "inlineData" in p), None)

                if not image_part:
                    if attempt < self.max_retries:
                        await asyncio.sleep(2)
                        continue
                    raise ValueError("Gemini response did not contain an image")

                return image_part["inlineData"]["data"]

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(2)
                    continue
            except Exception as e:
                last_error = e
                if attempt < self.max_retries and not isinstance(e, ValueError):
                    await asyncio.sleep(2)
                    continue
                break

        raise last_error or ValueError("Gemini text-only generation failed")
