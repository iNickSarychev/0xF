import asyncio
import aiohttp
import logging
import io
from PIL import Image
from duckduckgo_search import DDGS
from typing import List, Optional

logger = logging.getLogger(__name__)


class ImageHandler:
    def __init__(self, min_width: int = 800):
        self.min_width = min_width

    def _search_sync(self, query: str, max_results: int) -> List[str]:
        """Синхронный поиск (вызывается через to_thread)."""
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=max_results))
            return [r["image"] for r in results if "image" in r]

    async def search_images(self, query: str, max_results: int = 5) -> List[str]:
        """Поиск изображений через DuckDuckGo."""
        try:
            return await asyncio.to_thread(self._search_sync, query, max_results)
        except Exception as e:
            logger.error(f"DuckDuckGo search error for query '{query}': {e}")
            return []

    async def is_valid_image(self, url: str) -> bool:
        """Проверка валидности и размера изображения."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status != 200:
                        return False
                    
                    content = await response.read()
                    img = Image.open(io.BytesIO(content))
                    
                    # Проверяем ширину
                    width, _ = img.size
                    if width < self.min_width:
                        logger.info(f"Image {url} rejected: width {width} < {self.min_width}")
                        return False
                    
                    return True
        except Exception as e:
            logger.debug(f"Failed to validate image {url}: {e}")
            return False

    async def find_best_image(
        self, 
        query: str, 
        max_search_results: int = 5
    ) -> Optional[str]:
        """
        Ищет до 5 картинок, проверяет размер.
        Возвращает первую валидную.
        """
        image_urls = await self.search_images(query, max_results=max_search_results)
        
        if not image_urls:
            # Fallback: пробуем добавить "news photo" к запросу
            logger.info("No images found, trying fallback query...")
            image_urls = await self.search_images(f"{query} news photo", max_results=3)

        logger.info(f"DDG returned {len(image_urls)} image URLs for '{query}'")

        for url in image_urls:
            if await self.is_valid_image(url):
                logger.info(f"Image selected: {url}")
                return url
            
        logger.warning(f"No valid images found for query '{query}'")
        return None

image_handler = ImageHandler()
