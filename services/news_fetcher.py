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

        for feed_url in config.RSS_FEEDS:
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
                        all_news.append({
                            "title": entry.title,
                            "summary": entry.get("summary", entry.get("description", "")),
                            "link": entry.link,
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
