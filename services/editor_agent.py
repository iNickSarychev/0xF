import ollama
import httpx
import json
import logging
import re
from typing import List, Dict, Tuple, Any, Optional
import random
from config import config
from database import db
from services.vector_service import vector_service
from services.prompts import EDITOR_PROMPT, GOLDEN_SAMPLES, get_random_structure
from services.text_processor import text_processor
from services.critic_agent import critic_agent
from services.selector_agent import selector_agent
from services.llm_gateway import llm_gateway

logger = logging.getLogger(__name__)

class EditorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model

    def _safe_json_loads(self, text: str) -> dict:
        """Попытка починить и распарсить JSON от LLM."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Очистка от возможных Markdown-блоков
            clean_text = re.sub(r'^```json\s*|\s*```$', '', text.strip(), flags=re.MULTILINE)
            try:
                return json.loads(clean_text)
            except json.JSONDecodeError as e:
                # Если всё совсем плохо, пробуем совсем грубую очистку
                # (иногда LLM не экранирует кавычки внутри строк)
                logger.warning(f"JSON standard parse failed, trying aggressive fix: {e}")
                # Это очень упрощенный фикс, но часто помогает
                fixed_text = text.replace('\n', ' ').replace('\r', '')
                try:
                    return json.loads(fixed_text)
                except:
                    raise e

    async def process_news_batch(
        self, news_list: List[Dict[str, str]], temperature: float | None = 0.5
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

        # 3. Передаем список SelectorAgent'у
        theme = db.get_theme()
        best_news_idx = await selector_agent.select_best_news(news_list, theme)
        selected_news = news_list[best_news_idx]

        # 4. Подготовка ввода для Писателя (EditorAgent) с метаданными
        trending_mark = " [TRENDING]" if selected_news.get('trending') else ""
        pub_time = selected_news.get('published', (0,0,0,0,0,0,0,0,0))
        # Форматируем дату для контекста
        date_str = f"{pub_time[2]:02d}.{pub_time[1]:02d}.{pub_time[0]}"
        score = selected_news.get('trending_score', 0)
        
        news_input = (
            f"DATE: {date_str}\n"
            f"POPULARITY SCORE: {score}/10\n"
            f"TRENDING: {trending_mark}\n"
            f"TITLE: {selected_news['title']}\n"
            f"SOURCE SUMMARY: {selected_news['summary'][:800]}\n"
        )
        logger.debug(f"EDITOR_INPUT_NEWS:\n{news_input}")

        # 5. Генерация (Zero-shot режим, без GOLDEN_SAMPLES)
        try:
            chosen_structure = get_random_structure()
            logger.info(f"Post structure: {chosen_structure[:60]}...")
            prompt = EDITOR_PROMPT.format(
                structure_block=chosen_structure,
                news_input=news_input
            )
            
            llm_options: dict = {
                "num_predict": 4096,
                "top_p": 0.9,
                "repeat_penalty": 1.1
            }
            if temperature is not None:
                llm_options["temperature"] = temperature
            
            response = await llm_gateway.generate(
                model=self.model,
                prompt=prompt,
                format="json",
                options=llm_options
            )
            
            raw_content = response['response'].strip()
            logger.debug(f"Editor Raw Result (first 500 chars): {raw_content[:500]}...")
            logger.debug(f"Editor LLM JSON: {raw_content}")
            
            data = self._safe_json_loads(raw_content)
            
            image_query = data.get("image_query")
            article_text = data.get("post_text", "").strip()

            # Принудительная очистка и балансировка HTML для первого черновика
            article_text = text_processor.clean_llm_output(article_text)

            # 5. Reflection Loop: отправляем черновик Критику
            article_text, critique = await critic_agent.run_reflection_loop(
                initial_draft=article_text,
                news_input=news_input,
                max_iterations=3,
            )
            logger.info(
                f"Final critic score: {critique.score}/10 | "
                f"Approved: {critique.is_approved}"
            )

            return article_text, selected_news, image_query

        except Exception as e:
            logger.error(f"Error in EditorAgent generation: {e}")
            return f"Ошибка при генерации статьи: {str(e)}", None, None

    async def is_available(self) -> bool:
        try:
            await llm_gateway.client.list()
            return True
        except Exception:
            return False

editor_agent = EditorAgent()
