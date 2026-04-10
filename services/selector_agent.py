import json
import logging
import re
from typing import List, Dict, Optional

import ollama
import httpx

from config import config
from services.prompts import SELECTOR_PROMPT

from services.llm_gateway import llm_gateway

logger = logging.getLogger(__name__)

class SelectorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model

    def _safe_json_loads(self, text: str) -> dict:
        """Попытка починить и распарсить JSON от LLM."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            clean_text = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', text.strip(), flags=re.MULTILINE)
            try:
                return json.loads(clean_text)
            except json.JSONDecodeError as e:
                logger.warning(f"Selector JSON standard parse failed, trying aggressive fix: {e}")
                fixed_text = text.replace('\n', ' ').replace('\r', '')
                try:
                    return json.loads(fixed_text)
                except:
                    return {"selected_index": 1, "reason": "Fallback to index 1 due to JSON error"}

    async def select_best_news(self, news_list: List[Dict[str, str]], theme: str) -> int:
        """
        По очереди оценивает каждую новость и выбирает лучшую.
        """
        if not news_list:
            return 0
            
        if len(news_list) == 1:
            return 0

        # Оцениваем Топ-10 новостей (чтобы не ждать слишком долго)
        processing_list = news_list[:10]
        
        best_score = -1
        best_index = 0
        
        from services.prompts import SCORING_PROMPT

        logger.info(f"Starting one-by-one scoring for {len(processing_list)} news items...")

        for i, news in enumerate(processing_list):
            try:
                trending_mark = " [TRENDING]" if news.get('trending') else ""
                summary = news.get('summary', '')[:500]
                news_content = f"TITLE: {news['title']}{trending_mark}\nSUMMARY: {summary}"
                
                prompt = SCORING_PROMPT.format(theme=theme, news_content=news_content)
                
                response = await llm_gateway.generate(
                    model=self.model,
                    prompt=prompt,
                    format="json",
                    options={"num_predict": 256, "temperature": 0.3} # Низкая температура для точности оценок
                )
                
                raw_content = response['response'].strip()
                data = self._safe_json_loads(raw_content)
                
                score = int(data.get("score", 0))
                reason = data.get("reason", "No reason")
                
                logger.info(f"News [{i+1}/{len(processing_list)}] Score: {score}/10 | {news['title'][:50]}... | Reason: {reason}")

                if score > best_score:
                    best_score = score
                    best_index = i
                
                # Ранний выход, если нашли идеальную новость
                if score >= 10:
                    logger.info(f"Found perfect 10/10 news. Stopping search.")
                    break
                    
            except Exception as e:
                logger.error(f"Error scoring news item {i}: {e}")
                continue

        logger.info(f"SelectorAgent finalized choice: Index {best_index} with Score {best_score}")
        return best_index

selector_agent = SelectorAgent()
