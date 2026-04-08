import feedparser
import time
import calendar
from typing import Optional, Dict
from config import config
from database import Database

class NewsFetcher:
    def __init__(self, db: Database):
        self.db = db

    def get_news_batch(self, max_count: int = 10) -> list[Dict[str, str]]:
        """
        Собирает пачку свежих новостей из всех лент.
        """
        all_news = []
        current_time = time.time()
        
        sources = [url for _, url in self.db.get_all_sources()]

        for feed_url in sources:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    # Пропускаем новости без даты или старее 24 часов
                    pub_parsed = entry.get("published_parsed")
                    if not pub_parsed:
                        continue
                    
                    # feedparser.published_parsed - это UTC, используем calendar.timegm
                    pub_epoch = calendar.timegm(pub_parsed)
                    if (current_time - pub_epoch) > 86400:
                        continue

                    # Проверяем, есть ли уже такая новость в БД
                    if not self.db.is_news_sent(entry.title, entry.link):
                        # Ищем картинку
                        image_url = None
                        
                        # 1. Проверяем enclosures
                        if entry.get("enclosures"):
                            for enc in entry.enclosures:
                                if enc.get("type", "").startswith("image/"):
                                    image_url = enc.get("url")
                                    break
                        
                        # 2. Проверяем media:content или media:thumbnail (через namespaces)
                        if not image_url:
                            media_content = entry.get("media_content")
                            if media_content and isinstance(media_content, list):
                                image_url = media_content[0].get("url")
                            elif entry.get("media_thumbnail"):
                                image_url = entry.get("media_thumbnail")[0].get("url")
                        
                        # 3. Достаем из текста (превью в summary/description)
                        if not image_url:
                            import re
                            content = entry.get("summary", entry.get("description", ""))
                            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
                            if img_match:
                                image_url = img_match.group(1)

                        all_news.append({
                            "title": entry.title,
                            "summary": entry.get("summary", entry.get("description", "")),
                            "link": entry.link,
                            "image": image_url,
                            "published": pub_parsed
                        })
            except Exception as e:
                print(f"Error parsing {feed_url}: {e}")

        # Сортируем по дате публикации (от новых к старым)
        epoch_time = time.gmtime(0)
        all_news.sort(key=lambda x: x["published"] if x["published"] else epoch_time, reverse=True)

        # Возвращаем не более max_count новостей
        return all_news[:max_count]

news_fetcher = NewsFetcher(Database())
