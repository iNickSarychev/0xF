import logging
from typing import List, Dict
from config import config
from services.llm_gateway import llm_gateway
from services.text_processor import text_processor

logger = logging.getLogger(__name__)

class SelectorAgent:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model

    async def select_best_news(self, news_list: List[Dict[str, str]], theme: str) -> int:
        """По очереди оценивает каждую новость и выбирает лучшую."""
        if not news_list or len(news_list) <= 1:
            return 0

        processing_list = news_list[:10]
        best_score, best_index = -1, 0
        from services.prompts import SCORING_PROMPT

        logger.info(f"Starting one-by-one scoring for {len(processing_list)} items...")

        for i, news in enumerate(processing_list):
            try:
                trending_mark = " [TRENDING]" if news.get('trending') else ""
                summary = news.get('summary', '')[:500]
                news_content = f"TITLE: {news['title']}{trending_mark}\nSUMMARY: {summary}"
                
                prompt = SCORING_PROMPT.format(theme=theme, news_content=news_content)
                response = await llm_gateway.generate(
                    model=self.model,
                    prompt=prompt,
                    format="json"
                )
                
                data = text_processor.safe_json_loads(response['response'])
                score = int(data.get("score", 0))
                reason = data.get("reason", "No reason")
                
                logger.info(f"News [{i+1}/{len(processing_list)}] Score: {score}/10 | {news['title'][:50]}... | Reason: {reason}")

                if score > best_score:
                    best_score, best_index = score, i
                
                if score >= 10:
                    logger.info("Found perfect 10/10 news. Stopping.")
                    break
            except Exception as e:
                logger.error(f"Error scoring news item {i}: {e}")
                continue

        logger.info(f"SelectorAgent finalized choice: Index {best_index} with Score {best_score}")
        return best_index

selector_agent = SelectorAgent()
