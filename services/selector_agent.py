import random
import logging
import time
import calendar
import re
from typing import List, Dict
from config import config

logger = logging.getLogger(__name__)

# Список обязательных AI/tech/Space ключевых слов
TECH_KEYWORDS = {
    'ai', 'llm', 'gpt', 'model', 'neural', 'deep', 'learning', 'machine',
    'algorithm', 'python', 'code', 'github', 'api', 'data', 'cloud',
    'quantum', 'chip', 'nvidia', 'openai', 'google', 'meta', 'microsoft',
    'apple', 'tesla', 'robot', 'automation', 'software', 'hardware',
    'security', 'cryptography', 'blockchain', 'cyber', 'framework',
    'library', 'tool', 'research', 'paper', 'arxiv', 'breakthrough',
    'nasa', 'spacex', 'starship', 'satellite', 'falcon', 'musk', 'futurology', 
    'discovery', 'space', 'orbit', 'mars', 'moon'
}

# Ключевые слова для детекции открытий и прорывов
DISCOVERY_KEYWORDS = {
    'discovery', 'found', 'scientists', 'researchers', 'experiment', 'study', 
    'nature', 'science', 'breakthrough', 'uncovered', 'identified', 'evidence',
    'открытие', 'ученые', 'исследование', 'обнаружено', 'прорыв', 'впервые'
}

class SelectorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model

    def is_tech_related(self, title: str, summary: str) -> bool:
        """Проверяет, относится ли новость к технологиям/AI."""
        text = (title + " " + summary).lower()
        # Поиск целых слов для точности
        words = set(re.findall(r'\w+', text))
        return any(keyword in words for keyword in TECH_KEYWORDS)

    async def select_best_news(self, news_list: List[Dict], theme: str) -> int:
        """
        Эвристический отбор лучшей новости БЕЗ использования LLM.
        Возвращает индекс лучшей новости.
        """
        scores = self.get_all_scores(news_list)
        if not scores:
            return 0
        return scores[0][0]  # Возвращаем индекс новости с самым высоким баллом

    def get_all_scores(self, news_list: List[Dict]) -> List[tuple[int, float]]:
        """
        Рассчитывает баллы для всех новостей.
        Возвращает список кортежей (index, score), отсортированный по убыванию score.
        """
        if not news_list:
            return []

        current_time = time.time()
        scored_indices = []

        logger.info(f"Starting heuristic scoring for {len(news_list)} news items...")

        for i, news in enumerate(news_list):
            try:
                # 0. Проверка на релевантность
                if not self.is_tech_related(news['title'], news.get('summary', '')):
                    logger.debug(f"News [{i}] rejected: Not tech-related | Title: {news['title'][:50]}...")
                    continue

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

                # 3. Бонус за детальность (summary length без HTML)
                clean_summary = re.sub(r'<[^>]+>', '', news.get("summary", ""))
                summary_bonus = min(len(clean_summary) / 500.0, 2.0)

                # 4. Бонус за научные открытия
                discovery_bonus = 0.0
                text_content = (news['title'] + " " + news.get("summary", "")).lower()
                content_words = set(re.findall(r'\w+', text_content))
                if any(kw in content_words for kw in DISCOVERY_KEYWORDS):
                    discovery_bonus = 1.5
                    logger.debug(f"News [{i}] discovery_bonus applied (+1.5)")

                # Итоговая формула + небольшой рандом для разнообразия
                jitter = random.uniform(-0.3, 0.3)
                score = (trending_val * 2.0) + (freshness * 1.5) + summary_bonus + discovery_bonus + jitter
                
                scored_indices.append((i, score))
                logger.debug(f"News [{i}] Score: {score:.2f} | Trending: {trending_val} | Fresh: {freshness:.2f} | Title: {news['title'][:50]}...")

            except Exception as e:
                logger.error(f"Error heuristic scoring news item {i}: {e}")
                continue

        # Сортируем: лучшие сверху
        scored_indices.sort(key=lambda x: x[1], reverse=True)
        return scored_indices

selector_agent = SelectorAgent()
