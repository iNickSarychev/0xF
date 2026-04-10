import ollama
import httpx
import numpy as np
import asyncio
import logging
from typing import List, Dict, Optional
from config import config

logger = logging.getLogger(__name__)

class VectorService:
    def __init__(self):
        self.client = ollama.AsyncClient(
            host=config.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(300.0, connect=10.0)
        )
        self.semaphore = asyncio.Semaphore(5)  # Ограничиваем параллелизм, чтобы не перегрузить Ollama

    async def get_embeddings_batch(self, news_list: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Получает эмбеддинги для списка новостей параллельно."""
        tasks = [self._get_single_embedding(news) for news in news_list]
        return await asyncio.gather(*tasks)

    async def _get_single_embedding(self, news: Dict[str, str]) -> Dict[str, str]:
        """Получает эмбеддинг для одной новости."""
        async with self.semaphore:
            summary_trunc = (news['summary'][:500] + '...') if len(news['summary']) > 500 else news['summary']
            text_for_emb = f"{news['title']}. {summary_trunc}"
            try:
                resp = await self.client.embeddings(
                    model='nomic-embed-text', 
                    prompt=text_for_emb
                )
                news['vector'] = resp['embedding']
            except Exception as e:
                logger.error(f"Error fetching embedding for '{news['title']}': {e}")
                news['vector'] = None
            return news

    def cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Быстрое вычисление косинусного сходства через numpy."""
        if not v1 or not v2:
            return 0.0
        vec1 = np.array(v1)
        vec2 = np.array(v2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return np.dot(vec1, vec2) / (norm1 * norm2)

    async def is_available(self) -> bool:
        try:
            await self.client.list()
            return True
        except Exception:
            return False

vector_service = VectorService()
