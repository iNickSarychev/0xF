import logging
import aiohttp
import io
from typing import Optional, Tuple
from config import config

logger = logging.getLogger(__name__)

class VisionAgent:
    """
    Отвечает за визуальное сопровождение постов.
    Использует Media-X (Go-сервер) для интеллектуального поиска фото.
    """
    def __init__(self):
        self.media_x_url = f"{config.MEDIA_X_URL}/v1/extract"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    async def get_best_image(self, article_url: str, query: str = None) -> Optional[str]:
        """
        Ищет наилучшее изображение для статьи через микросервис Media-X.
        """
        if not article_url:
            return None

        image_url = await self._extract_from_media_x(article_url)
        if image_url:
            return image_url

        return None

    async def download_image(self, url: str) -> Optional[bytes]:
        """
        Скачивает изображение по ссылке, маскируясь под браузер.
        Возвращает байты изображения.
        """
        if not url:
            return None
            
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        content = await response.read()
                        # Проверка на разумный размер (до 10 МБ)
                        if len(content) > 10 * 1024 * 1024:
                            logger.warning(f"Image too large: {len(content)} bytes")
                            return None
                        return content
                    else:
                        logger.error(f"Failed to download image: status {response.status}")
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
        return None

    async def check_image(self, title: str, image_url: str) -> bool:
        if not image_url:
            return False
        return True

    async def _extract_from_media_x(self, url: str) -> Optional[str]:
        """Запрос к микросервису Media-X (Go)."""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {"url": url}
                async with session.post(self.media_x_url, json=payload, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "success":
                            return data.get("image_url")
        except Exception as e:
            logger.error(f"Error calling Media-X service: {e}")
        return None

vision_agent = VisionAgent()
