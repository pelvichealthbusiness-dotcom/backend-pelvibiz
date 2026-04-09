import base64
import logging
import time
import uuid
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self):
        settings = get_settings()
        self.supabase_url = settings.supabase_url
        self.service_key = settings.supabase_service_role_key
        self.bucket = settings.storage_bucket

    async def upload_image(self, image_base64: str, user_id: str) -> str:
        """Upload base64 image to Supabase Storage. Returns public URL."""
        file_data = base64.b64decode(image_base64)
        timestamp = int(time.time() * 1000)
        unique_id = uuid.uuid4().hex[:8]
        storage_path = f"generated/{user_id}/{timestamp}-{unique_id}.png"
        
        upload_url = f"{self.supabase_url}/storage/v1/object/{self.bucket}/{storage_path}"
        
        for attempt in range(2):  # 1 retry
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        upload_url,
                        content=file_data,
                        headers={
                            "Authorization": f"Bearer {self.service_key}",
                            "apikey": self.service_key,
                            "Content-Type": "image/png",
                            "x-upsert": "true",
                        },
                    )
                    response.raise_for_status()
                    
                    public_url = f"{self.supabase_url}/storage/v1/object/public/{self.bucket}/{storage_path}"
                    logger.info(f"Uploaded image: {storage_path}")
                    return public_url
                    
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"Storage upload failed (attempt 1), retrying: {e}")
                    continue
                raise
        
        raise RuntimeError("Storage upload failed after retries")  # unreachable but satisfies type checker
