import logging
import time
import calendar
from typing import List, Dict
from config import config

logger = logging.getLogger(__name__)

class SelectorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model

    async def select_best_news(self, news_list: List[Dict], theme: str) -> int:
        """
        Эвристический отбор лучшей новости БЕЗ использования LLM.
        Формула: trending_score * 2.0 + свежесть * 1.5 + (длина описания / 500)
        """
        if not news_list:
            return 0
        if len(news_list) == 1:
            return 0

        current_time = time.time()
        best_score = -1.0
        best_index = 0

        logger.info(f"Starting heuristic scoring for {len(news_list)} news items...")

        for i, news in enumerate(news_list):
            try:
                # 1. Свежесть (от 0 до 1, где 1 - только что опубликовано, 0 - старше 24 часов)
                pub_parsed = news.get("published")
                if pub_parsed:
                    pub_epoch = calendar.timegm(pub_parsed)
                    hours_old = (current_time - pub_epoch) / 3600
                    freshness = max(0.0, 1.0 - (hours_old / 24.0))
                else:
                    freshness = 0.5

                # 2. Trending Score (из fetcher)
                trending_val = float(news.get("trending_score", 0))

                # 3. Бонус за детальность (summary length)
                summary_bonus = len(news.get("summary", "")) / 500.0

                # Итоговая формула
                score = (trending_val * 2.0) + (freshness * 1.5) + summary_bonus

                logger.debug(f"News [{i}] Score: {score:.2f} | Trending: {trending_val} | Fresh: {freshness:.2f} | Title: {news['title'][:50]}...")

                if score > best_score:
                    best_score = score
                    best_index = i

            except Exception as e:
                logger.error(f"Error heuristic scoring news item {i}: {e}")
                continue

        logger.info(f"Heuristic selector finalized: Index {best_index} with Score {best_score:.2f}")
        return best_index

selector_agent = SelectorAgent()
