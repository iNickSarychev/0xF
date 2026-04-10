import logging
from typing import List, Dict, Tuple, Any, Optional
from config import config
from database import db
from services.vector_service import vector_service
from services.prompts import EDITOR_PROMPT, get_random_structure
from services.text_processor import text_processor
from services.critic_agent import critic_agent
from services.selector_agent import selector_agent
from services.llm_gateway import llm_gateway

logger = logging.getLogger(__name__)

class EditorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model

    async def process_news_batch(
        self, news_list: List[Dict[str, str]], temperature: float | None = 0.5
    ) -> Tuple[str, Any, Optional[str]]:
        """
        Фильтрует новости и пытается сгенерировать пост, используя fallback-цикл по лучшим новостям.
        """
        try:
            # 1. Сначала фильтруем весь входящий список (дубликаты и отклоненные)
            news_list = await vector_service.get_embeddings_batch(news_list)
            rejected_data = db.get_all_rejected_vectors()
            sent_data = db.get_all_sent_vectors()
            filtered_news = []
            
            for news in news_list:
                if not news.get('vector'):
                    filtered_news.append(news)
                    continue
                    
                is_rejected_or_dup = False
                for _, rej_vec in rejected_data:
                    if vector_service.cosine_similarity(news['vector'], rej_vec) > 0.85:
                        is_rejected_or_dup = True
                        break
                
                if not is_rejected_or_dup:
                    for _, sent_vec in sent_data:
                        if vector_service.cosine_similarity(news['vector'], sent_vec) > 0.88:
                            is_rejected_or_dup = True
                            break
                            
                if not is_rejected_or_dup:
                    filtered_news.append(news)
            
            if not filtered_news:
                return "🤷 Все новости были отфильтрованы как дубликаты или неинтересные темы.", None, None
                
            # 2. Получаем отсортированный список новостей по рейтингу
            theme = db.get_theme()
            scored_news = selector_agent.get_all_scores(filtered_news)
            
            if not scored_news:
                return "🤷 Нет новостей, подходящих под критерии AI/Tech.", None, None

            # 3. Fallback-цикл: пробуем 3 лучшие новости
            # Берем максимум 3 попытки
            max_fallback_attempts = min(3, len(scored_news))
            
            for attempt_idx in range(max_fallback_attempts):
                news_idx, score = scored_news[attempt_idx]
                selected_news = filtered_news[news_idx]
                
                logger.info(f"Fallback Attempt {attempt_idx + 1}/{max_fallback_attempts} | News: {selected_news['title'][:60]}... | Score: {score:.2f}")
                
                result = await self._try_generate_post(selected_news, score)
                if result:
                    article_text, image_query = result
                    return article_text, selected_news, image_query
                
                logger.warning(f"Attempt {attempt_idx + 1} failed for '{selected_news['title'][:30]}...'. Trying next news...")

            return "🤷 Не удалось сгенерировать качественный пост после нескольких попыток.", None, None

        except Exception as e:
            logger.error(f"Error in process_news_batch: {e}")
            return f"Критическая ошибка: {str(e)}", None, None

    async def _try_generate_post(self, selected_news: Dict, score: float) -> Optional[Tuple[str, str]]:
        """Внутренняя попытка генерации для конкретной новости."""
        try:
            # Подготовка ввода
            pub_time = selected_news.get('published', (0,0,0,0,0,0,0,0,0))
            date_str = f"{pub_time[2]:02d}.{pub_time[1]:02d}.{pub_time[0]}"
            trending_mark = " [TRENDING]" if selected_news.get('trending') else ""
            
            news_input = (
                f"DATE: {date_str}\n"
                f"POPULARITY SCORE: {score:.1f}/10\n"
                f"TRENDING: {trending_mark}\n"
                f"TITLE: {selected_news['title']}\n"
                f"SOURCE SUMMARY: {selected_news['summary'][:800]}\n"
            )

            chosen_structure = get_random_structure()
            prompt = EDITOR_PROMPT.format(
                structure_block=chosen_structure,
                news_input=news_input
            )
            
            response = await llm_gateway.generate(
                model=self.model,
                prompt=prompt,
                format="json"
            )
            
            raw_content = response['response'].strip()
            data = text_processor.safe_json_loads(raw_content)
            
            image_query = data.get("image_query")
            article_text = data.get("post_text", "").strip()
            
            if not article_text:
                return None

            article_text = text_processor.clean_llm_output(article_text)

            # Reflection Loop (1 итерация)
            article_text, critique = await critic_agent.run_reflection_loop(
                initial_draft=article_text,
                news_input=news_input,
                max_iterations=1,
            )
            
            if critique.is_approved or critique.score >= 7:
                return article_text, image_query or selected_news['title']
            
            logger.warning(f"Critique rejected news. Score: {critique.score}")
            return None

        except Exception as e:
            logger.error(f"Try generate post error: {e}")
            return None

    async def is_available(self) -> bool:
        try:
            await llm_gateway.client.list()
            return True
        except Exception:
            return False

editor_agent = EditorAgent()
