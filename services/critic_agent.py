import logging
from dataclasses import dataclass
from config import config
from services.prompts import CRITIC_PROMPT, REWRITE_PROMPT
from services.text_processor import text_processor
from services.llm_gateway import llm_gateway

logger = logging.getLogger(__name__)

# Порог оценки, при котором текст считается одобренным
APPROVAL_SCORE_THRESHOLD: int = 8

@dataclass
class CritiqueResult:
    """Результат оценки черновика агентом-критиком."""
    score: int
    has_ai_cliches: bool
    is_approved: bool
    feedback: str

    @property
    def is_good_enough(self) -> bool:
        return self.is_approved or self.score >= APPROVAL_SCORE_THRESHOLD

class CriticAgent:
    """Оценивает черновик и запускает цикл переработки."""

    def __init__(self, model: str = config.OLLAMA_MODEL) -> None:
        self.model = model

    async def critique(self, draft_text: str) -> CritiqueResult:
        """Отправляет черновик на оценку."""
        if not draft_text.strip():
            logger.warning("Critic received empty draft_text!")

        prompt = CRITIC_PROMPT.format(draft_text=draft_text)
        try:
            response = await llm_gateway.generate(model=self.model, prompt=prompt, format="json")
            data = text_processor.safe_json_loads(response["response"])
            
            return CritiqueResult(
                score=int(data.get("score", 5)),
                has_ai_cliches=bool(data.get("has_ai_cliches", False)),
                is_approved=bool(data.get("is_approved", False)),
                feedback=str(data.get("feedback", "")),
            )
        except Exception as exc:
            logger.warning(f"Critique error: {exc}")
            return CritiqueResult(8, False, True, "Auto-approved due to error")

    async def rewrite(self, draft_text: str, feedback: str, news_input: str) -> str:
        """Переписывает черновик по замечаниям."""
        prompt = REWRITE_PROMPT.format(draft_text=draft_text, feedback=feedback, news_input=news_input)
        try:
            response = await llm_gateway.generate(
                model=self.model, 
                prompt=prompt
            )
            return text_processor.clean_llm_output(response["response"])
        except Exception as exc:
            logger.warning(f"Rewrite error: {exc}")
            return draft_text

    async def run_reflection_loop(self, initial_draft: str, news_input: str, max_iterations: int = 3) -> tuple[str, CritiqueResult]:
        """Цикл «Черновик → Критик → Переработка»."""
        current_draft, previous_score, stall_counter = initial_draft, -1, 0
        last_critique = CritiqueResult(0, False, False, "")

        for i in range(1, max_iterations + 1):
            logger.info(f"Reflection loop iteration {i}/{max_iterations}")
            last_critique = await self.critique(current_draft)
            
            if last_critique.is_good_enough:
                break
            
            # Проверка на отсутствие прогресса
            if last_critique.score <= previous_score:
                stall_counter += 1
                if stall_counter >= 2: break
            else:
                stall_counter = 0
            
            previous_score = last_critique.score
            if i < max_iterations:
                current_draft = await self.rewrite(current_draft, last_critique.feedback, news_input)

        return current_draft, last_critique

critic_agent = CriticAgent()
