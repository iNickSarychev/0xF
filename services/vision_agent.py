import logging
import aiohttp
from typing import Optional
from config import config

logger = logging.getLogger(__name__)

class VisionAgent:
    """
    Отвечает за визуальное сопровождение постов.
    Использует Media-X (Go-сервер) для интеллектуального поиска фото.
    """
    def __init__(self):
        self.media_x_url = f"{config.MEDIA_X_URL}/v1/extract"

    async def get_best_image(self, article_url: str, query: str = None) -> Optional[str]:
        """
        Ищет наилучшее изображение для статьи через микросервис Media-X.
        """
        if not article_url:
            return None

        image_url = await self._extract_from_media_x(article_url)
        if image_url:
            logger.info(f"Media-X found image: {image_url}")
            return image_url

        return None

    async def check_image(self, title: str, image_url: str) -> bool:
        """
        Заглушка для проверки релевантности изображения через VLM.
        В будущем здесь можно добавить запрос к LLaVA/Gemma-Vision.
        Сейчас просто одобряет любое непустое изображение.
        """
        if not image_url:
            return False
        return True

    async def _extract_from_media_x(self, url: str) -> Optional[str]:
        """Запрос к микросервису Media-X (Go)."""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {"url": url}
                async with session.post(self.media_x_url, json=payload, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "success":
                            return data.get("image_url")
        except Exception as e:
            logger.error(f"Error calling Media-X service: {e}")
        return None

vision_agent = VisionAgent()
