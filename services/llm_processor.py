import ollama
import httpx
from typing import List, Dict, Tuple
from config import config


class LLMProcessor:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model
        self.client = ollama.AsyncClient(
            host=config.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(300.0, connect=10.0)
        )

    async def process_news_batch(
        self, news_list: List[Dict[str, str]]
    ) -> Tuple[str, str]:
        """
        Принимает список новостей, выбирает ОДНУ и пишет лонгрид.
        Возвращает (текст_статьи, ссылка_на_источник).
        """
        news_input = ""
        for i, news in enumerate(news_list, 1):
            news_input += f"[{i}] {news['title']}\n{news['summary'][:200]}\n\n"

        prompt = f"""Ты — главный редактор крупного технологического медиа.

ЗАДАНИЕ:
Ниже список из {len(news_list)} новостей. Выбери ОДНУ самую важную и напиши по ней аналитическую статью.

ПРИОРИТЕТ ВЫБОРА (от высшего к низшему):
1. Релизы новых AI-моделей (скорость, цена, архитектура)
2. Прорывы в AI, которые меняют правила игры (disruptive tech)
3. Крупные запуски и скрытые мотивы корпораций (интрига рынка)
4. Регулирование AI, угрозы безопасности, AGI
5. Прочие важные технологические тренды

СТИЛЬ И ПОДАЧА (КРИТИЧНО):
- Пиши с тонкой журналистской интригой. Текст должен затягивать с первого предложения.
- Тон: умный, профессиональный, но захватывающий.
- Никакого дешёвого кликбейта ("Шок!", "Невероятно!"). Интрига должна быть элегантной и читаться между строк (почему это событие важнее, чем кажется на первый взгляд).

ФОРМАТ ОТВЕТА (строго соблюдай):

НОМЕР: [число от 1 до {len(news_list)}]

<b>[Интригующий, но строгий заголовок статьи]</b>

[Вводный абзац: мощный хук (крючок) и суть новости в 2-3 предложениях. Почему это происходит именно сейчас?]

[Основная часть: краткий и ёмкий анализ, вскрывающий неочевидные детали, скрытые угрозы или возможности. 1-2 абзаца, строго без воды]

[Заключение: сильный вывод или открытый прогноз, заставляющий задуматься о будущем]

ПРАВИЛА:
- Пиши ТОЛЬКО на русском языке
- Объём: 1000-1500 символов (пиши коротко и строго по делу)
- Первая строка ответа ОБЯЗАТЕЛЬНО: НОМЕР: N
- Используй <b>жирный</b> для выделения. Никакого Markdown (##, **, #)
- Анализируй КОНКРЕТНУЮ новость, не пиши общие рассуждения

НОВОСТИ:
{news_input}"""

        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                options={
                    "num_ctx": 4096,
                    "num_predict": 2048,
                    "temperature": 0.7
                }
            )
            import re
            raw_text = response['response'].strip()
            
            # Удаляем любые теги "размышлений" (встречаются у MoE-моделей)
            raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
            raw_text = re.sub(r'<\|thought\|>.*?</\|thought\|>', '', raw_text, flags=re.DOTALL)
            raw_text = raw_text.strip()

            # Извлекаем номер выбранной новости
            selected_link = ""
            article_lines = []

            for line in raw_text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("НОМЕР:") or stripped.upper().startswith("SELECTED:"):
                    try:
                        number_part = stripped.split(":")[1].strip().rstrip(".")
                        index = int(number_part) - 1
                        if 0 <= index < len(news_list):
                            selected_link = news_list[index].get("link", "")
                    except (ValueError, IndexError):
                        pass
                else:
                    article_lines.append(line)

            article_text = "\n".join(article_lines).strip()

            # Фоллбэк: если модель не указала номер, берём первую новость
            if not selected_link and news_list:
                selected_link = news_list[0].get("link", "")

            return article_text, selected_link

        except Exception as e:
            return f"Ошибка при анализе нейросетью: {str(e)}", ""


llm_processor = LLMProcessor()
