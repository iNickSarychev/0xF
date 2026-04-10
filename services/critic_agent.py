import json
import logging
import re
from dataclasses import dataclass

import httpx
import ollama

from config import config
from services.prompts import CRITIC_PROMPT, REWRITE_PROMPT
from services.text_processor import text_processor

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
    """
    Агент-критик («Злой Главред»).
    Оценивает черновик и при необходимости запускает цикл переработки.
    Использует ту же модель Ollama, что и EditorAgent, но с другим промптом.
    """

    def __init__(self, model: str = config.OLLAMA_MODEL) -> None:
        self.model = model
        self.client = ollama.AsyncClient(
            host=config.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(180.0, connect=10.0),
        )

    async def critique(self, draft_text: str) -> CritiqueResult:
        """
        Отправляет черновик на оценку.
        Возвращает CritiqueResult с оценкой и замечаниями.
        """
        prompt = CRITIC_PROMPT.format(draft_text=draft_text)
        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                format="json",
                options={"num_predict": 512},
            )
            raw = response["response"].strip()
            logger.debug(f"Critic raw response: {raw}")

            data = json.loads(raw)
            return CritiqueResult(
                score=int(data.get("score", 5)),
                has_ai_cliches=bool(data.get("has_ai_cliches", False)),
                is_approved=bool(data.get("is_approved", False)),
                feedback=str(data.get("feedback", "")),
            )

        except Exception as exc:
            logger.warning(f"CriticAgent error (skipping critique): {exc}")
            # При сбое критика не блокируем публикацию — возвращаем одобрение
            return CritiqueResult(
                score=8,
                has_ai_cliches=False,
                is_approved=True,
                feedback="Критик недоступен, текст пропущен автоматически.",
            )

        return text.strip() # This is a cleanup of an old replacement artifact, I'll remove the whole method below


    async def rewrite(
        self, draft_text: str, feedback: str, news_input: str, temperature: float = 0.5
    ) -> str:
        """
        Просит модель переписать черновик по замечаниям критика.
        Возвращает исправленный текст (не JSON).
        """
        prompt = REWRITE_PROMPT.format(
            draft_text=draft_text, 
            feedback=feedback,
            news_input=news_input
        )
        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                options={
                    "num_predict": 1024,
                    "temperature": temperature,
                    "top_p": 0.9,
                    "repeat_penalty": 1.1
                },
            )
            rewritten = response["response"].strip()

            # Очищаем от возможных остатков JSON/markdown-обёрток
            rewritten = re.sub(r"^```[a-z]*\n?", "", rewritten)
            rewritten = re.sub(r"\n?```$", "", rewritten)
            
            # Принудительная очистка от мусорных заголовков и исправление HTML
            rewritten = text_processor.clean_llm_output(rewritten)

            logger.debug(f"Rewritten draft length: {len(rewritten)} chars")
            return rewritten

        except Exception as exc:
            logger.warning(f"Rewrite error (keeping original draft): {exc}")
            return draft_text

    async def run_reflection_loop(
        self,
        initial_draft: str,
        news_input: str,
        max_iterations: int = 3,
    ) -> tuple[str, CritiqueResult]:
        """
        Запускает цикл «Черновик → Критик → Переработка».

        Args:
            initial_draft: первый черновик от EditorAgent.
            news_input: исходный текст новости для контекста.
            max_iterations: максимальное количество итераций переработки.

        Returns:
            Кортеж (финальный_текст, последняя_оценка_критика).
        """
        current_draft = initial_draft
        last_critique = CritiqueResult(
            score=0, has_ai_cliches=False, is_approved=False, feedback=""
        )
        previous_score = -1
        stall_counter = 0

        for iteration in range(1, max_iterations + 1):
            logger.info(f"Reflection loop iteration {iteration}/{max_iterations}")

            last_critique = await self.critique(current_draft)
            logger.info(
                f"Critic score: {last_critique.score}/10 | "
                f"Approved: {last_critique.is_approved} | "
                f"Cliches: {last_critique.has_ai_cliches} | "
                f"Feedback: {last_critique.feedback[:120]}"
            )

            if last_critique.is_good_enough:
                logger.info(f"Text approved on iteration {iteration}.")
                break
            
            # Проверка на отсутствие прогресса (Stall Detection)
            if last_critique.score <= previous_score:
                stall_counter += 1
                if stall_counter >= 2:
                    logger.warning("Score stalled for 2 iterations. Stopping rewrite loop.")
                    break
            else:
                stall_counter = 0
            
            previous_score = last_critique.score

            if iteration < max_iterations:
                logger.info("Sending draft for rewrite...")
                # Увеличиваем температуру с каждой итерацией для "креативности" исправлений
                current_temp = 0.2 + (iteration * 0.15)
                
                current_draft = await self.rewrite(
                    draft_text=current_draft,
                    feedback=last_critique.feedback,
                    news_input=news_input,
                    temperature=current_temp
                )
            else:
                logger.warning(
                    f"Max iterations reached. Publishing best available draft "
                    f"(score={last_critique.score})."
                )

        return current_draft, last_critique


critic_agent = CriticAgent()
