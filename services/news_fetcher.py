import asyncio
import calendar
import logging
import re
import time
from typing import Dict

import aiohttp
import feedparser

from config import config
from database import Database

logger = logging.getLogger(__name__)

# Домены приоритетных источников (AI-лаборатории).
# Новости с этих доменов получают бонус к trending_score.
PRIORITY_DOMAINS: dict[str, int] = {
    "huggingface.co": 2,
    "blog.google": 2,
    "openai.com": 3,
    "deepmind.google": 3,
    "ai.meta.com": 2,
}

# Стоп-слова для детекции трендов (EN + RU)
_STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
    "to", "for", "of", "and", "or", "with", "how", "what", "why",
    "its", "it", "as", "by", "from", "that", "this", "new", "will",
    "has", "have", "been", "not", "but", "can", "all", "just",
    "и", "в", "на", "с", "по", "для", "из", "что", "как", "это",
    "не", "о", "к", "за", "от", "до", "но", "же", "бы",
}

# Regex для очистки пунктуации из заголовков (фикс бага AI. ≠ AI)
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _extract_keywords(title: str) -> set[str]:
    """Извлекает значимые слова из заголовка, очищая пунктуацию."""
    cleaned = _PUNCTUATION_RE.sub("", title.lower())
    return {word for word in cleaned.split() if len(word) > 2 and word not in _STOP_WORDS}


def _get_source_bonus(feed_url: str) -> int:
    """Возвращает бонус к trending_score для приоритетного источника."""
    for domain, bonus in PRIORITY_DOMAINS.items():
        if domain in feed_url:
            return bonus
    return 0


def _extract_image_from_entry(entry: feedparser.FeedParserDict) -> str | None:
    """
    Выдёргивает URL картинки из RSS-записи.
    Стратегии: enclosures → media:content → media:thumbnail → <img> в HTML.
    """
    # 1. Enclosures
    if entry.get("enclosures"):
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("url")

    # 2. media:content / media:thumbnail (через namespaces)
    media_content = entry.get("media_content")
    if media_content and isinstance(media_content, list):
        return media_content[0].get("url")

    media_thumbnail = entry.get("media_thumbnail")
    if media_thumbnail and isinstance(media_thumbnail, list):
        return media_thumbnail[0].get("url")

    # 3. <img> в summary/description (фоллбэк)
    content = entry.get("summary", entry.get("description", ""))
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
    if img_match:
        return img_match.group(1)

    return None


class NewsFetcher:
    """Асинхронный сборщик новостей из RSS-лент."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_news_batch(self, max_count: int = 10) -> list[dict[str, str]]:
        """
        Собирает пачку свежих новостей из всех лент.
        RSS-ленты скачиваются параллельно через aiohttp,
        затем парсятся feedparser-ом.
        """
        sources = [url for _, url in self.db.get_all_sources()]
        if not sources:
            logger.warning("No sources found in database!")
            return []

        logger.info(f"Fetching news from {len(sources)} sources...")

        # Скачиваем все ленты параллельно (неблокирующий I/O)
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            tasks = [self._fetch_feed(session, url) for url in sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        current_time = time.time()
        all_news: list[dict] = []
        stats = {"total": 0, "too_old": 0, "already_sent": 0, "errors": 0}

        for feed_url, result in zip(sources, results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {feed_url}: {result}")
                stats["errors"] += 1
                continue

            feed = feedparser.parse(result)
            source_bonus = _get_source_bonus(feed_url)
            
            feed_entries_count = len(feed.entries)
            stats["total"] += feed_entries_count

            for entry in feed.entries:
                news_item = self._parse_entry(entry, current_time, source_bonus, stats)
                if news_item:
                    all_news.append(news_item)

        logger.info(
            f"Fetch completed. Total parsed: {stats['total']}, "
            f"Too old: {stats['too_old']}, "
            f"Already sent: {stats['already_sent']}, "
            f"Errors: {stats['errors']}, "
            f"Fresh news found: {len(all_news)}"
        )

        # Сортируем по дате: от новых к старым
        epoch_zero = time.gmtime(0)
        all_news.sort(
            key=lambda item: item["published"] if item["published"] else epoch_zero,
            reverse=True,
        )

        # Детекция горячих новостей
        all_news = self._detect_trending(all_news)

        return all_news[:max_count]

    @staticmethod
    async def _fetch_feed(session: aiohttp.ClientSession, feed_url: str) -> str:
        """Скачивает RSS-ленту асинхронно, возвращает сырой XML-текст."""
        async with session.get(feed_url) as response:
            response.raise_for_status()
            return await response.text()

    def _parse_entry(
        self,
        entry: feedparser.FeedParserDict,
        current_time: float,
        source_bonus: int,
        stats: dict,
    ) -> dict | None:
        """Парсит одну запись RSS. Возвращает None, если запись невалидна."""
        pub_parsed = entry.get("published_parsed")
        if not pub_parsed:
            return None

        pub_epoch = calendar.timegm(pub_parsed)
        if (current_time - pub_epoch) > 172800:
            stats["too_old"] += 1
            return None

        if self.db.is_news_sent(entry.title, entry.link):
            stats["already_sent"] += 1
            return None

        return {
            "title": entry.title,
            "summary": entry.get("summary", entry.get("description", "")),
            "link": entry.link,
            "image": _extract_image_from_entry(entry),
            "published": pub_parsed,
            "source_bonus": source_bonus,
        }

    @staticmethod
    def _detect_trending(news_list: list[dict]) -> list[dict]:
        """Помечает новости, которые упоминаются в нескольких источниках."""
        for i, news_item in enumerate(news_list):
            keywords = _extract_keywords(news_item["title"])
            similar_count = 0

            for j, other in enumerate(news_list):
                if i == j:
                    continue
                other_keywords = _extract_keywords(other["title"])
                overlap = keywords & other_keywords
                if len(overlap) >= 3:
                    similar_count += 1

            news_item["trending"] = similar_count >= 2
            # Итоговый вес учитывает и количество совпадений, и приоритет источника
            news_item["trending_score"] = similar_count + news_item.get("source_bonus", 0)

        # Trending и приоритетные наверх, внутри — по дате
        news_list.sort(key=lambda item: item.get("trending_score", 0), reverse=True)
        return news_list


news_fetcher = NewsFetcher(Database())
