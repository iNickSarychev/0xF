import asyncio
import aiohttp
import logging
import io
from PIL import Image
from ddgs import DDGS
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import List, Optional

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# Домены со стоковыми фото (водяные знаки)
WATERMARK_DOMAINS = [
    "shutterstock.com", "gettyimages.com", "istockphoto.com",
    "dreamstime.com", "123rf.com", "depositphotos.com",
    "alamy.com", "bigstockphoto.com", "canstockphoto.com",
    "stock.adobe.com", "photospin.com", "pngtree.com",
    "freepik.com", "vecteezy.com", "pxfuel.com", "piqsels.com",
    "wallpaperflare.com"
]


class ImageHandler:
    def __init__(self, min_width: int = 800):
        self.min_width = min_width

    def _is_stock_url(self, url: str) -> bool:
        """Проверяет, не ведёт ли URL на стоковый сайт с водяными знаками."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in WATERMARK_DOMAINS)

    def _search_sync(self, query: str, max_results: int) -> List[str]:
        """Синхронный поиск (вызывается через to_thread)."""
        results = DDGS().images(query, max_results=max_results)
        return [
            r["image"] for r in results
            if "image" in r and not self._is_stock_url(r["image"])
        ]

    async def search_images(self, query: str, max_results: int = 5) -> List[str]:
        """Поиск изображений через DuckDuckGo с retry при ratelimit."""
        for attempt in range(MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._search_sync, query, max_results)
            except Exception as e:
                error_message = str(e).lower()
                if "ratelimit" in error_message or "403" in error_message:
                    wait_time = RETRY_DELAY_SECONDS * (attempt + 1)
                    logger.warning(
                        f"DDG ratelimit (attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Waiting {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"DDG search error for '{query}': {e}")
                    return []
        logger.error(f"DDG ratelimit: all {MAX_RETRIES} retries exhausted for '{query}'")
        return []

    async def is_valid_image(self, url: str) -> bool:
        """Проверка валидности и размера изображения."""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return False

                    content = await response.read()
                    img = Image.open(io.BytesIO(content))

                    # Проверяем ширину
                    width, _ = img.size
                    if width < self.min_width:
                        logger.info(f"Image rejected: width {width} < {self.min_width}")
                        return False

                    return True
        except Exception as e:
            logger.debug(f"Failed to validate image {url}: {e}")
            return False

    async def extract_article_image(self, article_url: str) -> Optional[str]:
        """Парсит страницу статьи в поисках качественной обложки (og:image / twitter:image)."""
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5"
                }
                async with session.get(article_url, headers=headers) as response:
                    if response.status != 200:
                        return None
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")
                    
                    # Ищем og:image (самый качественный вариант обложки)
                    meta_og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
                    if meta_og and meta_og.get("content"):
                        img_url = urljoin(article_url, meta_og["content"])
                        if not self._is_stock_url(img_url) and await self.is_valid_image(img_url):
                            logger.info(f"High-quality og:image extracted: {img_url}")
                            return img_url
                            
                    # Ищем twitter:image (альтернатива)
                    meta_tw = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"})
                    if meta_tw and meta_tw.get("content"):
                        img_url = urljoin(article_url, meta_tw["content"])
                        if not self._is_stock_url(img_url) and await self.is_valid_image(img_url):
                            logger.info(f"High-quality twitter:image extracted: {img_url}")
                            return img_url
                            
                    logger.info("No valid OpenGraph/Twitter image found in article HTML.")
                    return None
        except Exception as e:
            logger.debug(f"Failed to parse article {article_url} for images: {e}")
            return None

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
            await asyncio.sleep(2)
            image_urls = await self.search_images(
                f"{query} news photo -watermark -stock", max_results=5
            )

        logger.info(f"DDG returned {len(image_urls)} image URLs for '{query}'")

        for url in image_urls:
            if await self.is_valid_image(url):
                logger.info(f"Image selected: {url}")
                return url

        logger.warning(f"No valid images found for query '{query}'")
        return None


image_handler = ImageHandler()
