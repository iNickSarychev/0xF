import json
import logging
import re
from typing import List, Dict, Optional

import ollama
import httpx

from config import config
from services.prompts import SELECTOR_PROMPT

logger = logging.getLogger(__name__)

class SelectorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model
        self.client = ollama.AsyncClient(
            host=config.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(180.0, connect=10.0)
        )

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
        Отправляет пакет новостей LLM и просит выбрать самую важную.
        Возвращает индекс выбранной новости (от 0 до len(news_list)-1).
        """
        if not news_list:
            return 0
            
        if len(news_list) == 1:
            return 0

        news_batch = ""
        for i, news in enumerate(news_list, 1):
            trending_mark = " [TRENDING]" if news.get('trending') else ""
            news_batch += f"[{i}]{trending_mark} {news['title']}\n{news['summary'][:800]}\n\n"

        prompt = SELECTOR_PROMPT.format(theme=theme, news_batch=news_batch)

        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                format="json",
                options={"num_predict": 512}
            )

            raw_content = response['response'].strip()
            logger.debug(f"Selector LLM JSON: {raw_content}")

            data = self._safe_json_loads(raw_content)
            idx_val = data.get("selected_index", 1)
            reason = data.get("reason", "No reason provided")
            
            logger.info(f"SelectorAgent chose index {idx_val} | Reason: {reason}")
            
            idx = int(idx_val) - 1
            if 0 <= idx < len(news_list):
                return idx
            return 0

        except Exception as e:
            logger.error(f"Error in SelectorAgent: {e}")
            return 0

selector_agent = SelectorAgent()
