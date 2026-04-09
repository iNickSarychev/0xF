import ollama
import httpx
import json
import logging
import re
from typing import List, Dict, Tuple, Any, Optional
from config import config
from database import db
from services.vector_service import vector_service
from services.prompts import EDITOR_PROMPT

logger = logging.getLogger(__name__)

class EditorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model
        self.client = ollama.AsyncClient(
            host=config.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(300.0, connect=10.0)
        )

    async def process_news_batch(
        self, news_list: List[Dict[str, str]], temperature: float | None = None
    ) -> Tuple[str, Any, Optional[str]]:
        """
        Фильтрует новости по векторам и пишет пост.
        Возвращает (текст_статьи, selected_news, image_query).
        
        Args:
            news_list: список новостей для обработки.
            temperature: температура генерации (None — из Modelfile, 0.9 — творческий режим).
        """
        try:
            # 1. Получаем эмбеддинги параллельно
            news_list = await vector_service.get_embeddings_batch(news_list)
            
            # 2. Фильтрация
            rejected_data = db.get_all_rejected_vectors()
            sent_data = db.get_all_sent_vectors()
            filtered_news = []
            
            for news in news_list:
                if not news.get('vector'):
                    filtered_news.append(news)
                    continue
                    
                is_rejected_or_dup = False
                # Проверка на отклоненные
                for _, rej_vec in rejected_data:
                    if vector_service.cosine_similarity(news['vector'], rej_vec) > 0.85:
                        is_rejected_or_dup = True
                        break
                
                # Проверка на дубликаты
                if not is_rejected_or_dup:
                    for _, sent_vec in sent_data:
                        if vector_service.cosine_similarity(news['vector'], sent_vec) > 0.88:
                            is_rejected_or_dup = True
                            logger.info(f"Duplicate blocked: {news['title']}")
                            break
                            
                if not is_rejected_or_dup:
                    filtered_news.append(news)
            
            news_list = filtered_news
            if not news_list:
                return "🤷 Все новости были отфильтрованы как дубликаты или неинтересные темы.", None, None
                
        except Exception as e:
            logger.error(f"Error in news filtering: {e}")

        # 3. Подготовка ввода для LLM
        news_input = ""
        for i, news in enumerate(news_list, 1):
            trending_mark = " [TRENDING — тема в нескольких источниках]" if news.get('trending') else ""
            news_input += f"[{i}]{trending_mark} {news['title']}\n{news['summary'][:200]}\n\n"

        # 4. Генерация
        try:
            prompt = EDITOR_PROMPT.format(news_input=news_input)
            
            llm_options: dict = {"num_predict": 2048}
            if temperature is not None:
                llm_options["temperature"] = temperature
            
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                format="json",
                options=llm_options,
            )
            
            raw_content = response['response'].strip()
            logger.debug(f"LLM JSON: {raw_content}")
            
            data = json.loads(raw_content)
            
            # Извлечение данных
            idx_val = data.get("selected_index") or data.get("selected_news_index", 1)
            idx = int(idx_val) - 1
            selected_news = news_list[idx] if 0 <= idx < len(news_list) else news_list[0]
            
            image_query = data.get("image_query")
            article_text = data.get("post_text", "").strip()

            # HTML-очистка
            article_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', article_text)
            article_text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', article_text)

            return article_text, selected_news, image_query

        except Exception as e:
            logger.error(f"Error in EditorAgent generation: {e}")
            return f"Ошибка при генерации статьи: {str(e)}", None, None

    async def is_available(self) -> bool:
        try:
            await self.client.list()
            return True
        except Exception:
            return False

editor_agent = EditorAgent()
