import ollama
import httpx
import math
from typing import List, Dict, Tuple, Any
from config import config
from database import db


class LLMProcessor:
    def __init__(self, model: str = config.OLLAMA_MODEL):
        self.model = model
        self.client = ollama.AsyncClient(
            host=config.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(300.0, connect=10.0)
        )

    async def is_available(self) -> bool:
        """Проверяет доступность Ollama (лёгкий ping)."""
        try:
            await self.client.list()
            return True
        except Exception:
            return False

    def cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2))
        mag1 = math.sqrt(sum(a * a for a in v1))
        mag2 = math.sqrt(sum(b * b for b in v2))
        if mag1 * mag2 == 0:
            return 0
        return dot / (mag1 * mag2)

    async def process_news_batch(
        self, news_list: List[Dict[str, str]]
    ) -> Tuple[str, Any]:
        """
        Принимает список новостей, векторами фильтрует отклоненные, 
        выбирает ОДНУ и пишет лонгрид.
        Возвращает (текст_статьи, selected_news).
        """
        try:
            rejected_data = db.get_all_rejected_vectors()
            filtered_news = []
            
            for news in news_list:
                text_for_emb = f"{news['title']}. {news['summary']}"
                try:
                    emb_resp = await self.client.embeddings(model='nomic-embed-text', prompt=text_for_emb)
                    news_vector = emb_resp['embedding']
                    
                    is_rejected = False
                    for _, rej_vec in rejected_data:
                        sim = self.cosine_similarity(news_vector, rej_vec)
                        if sim > 0.85:
                            is_rejected = True
                            break
                    if not is_rejected:
                        filtered_news.append(news)
                except Exception:
                    filtered_news.append(news)
            
            news_list = filtered_news
            
            if not news_list:
                return "🤷 Все свежие новости были отфильтрованы как дубликаты или ранее отклонённые темы.", None
        except Exception as e:
            pass

        news_input = ""
        for i, news in enumerate(news_list, 1):
            news_input += f"[{i}] {news['title']}\n{news['summary'][:200]}\n\n"

        current_theme = db.get_theme()
        
        prompt = f"""Ты — стратегический аналитик уровня Leopold Aschenbrenner, составляющий закрытый отчет «Situational Awareness». Твой текст — это холодная, сухая и предельно концентрированная аналитика для первых лиц индустрии.

ЗАДАНИЕ:
Ниже список из {len(news_list)} новостей. 
1. Выбери ОДНУ наиболее системно значимую новость (Scaling Laws, инфраструктура, AGI, геополитика технологий).
2. Напиши по ней глубокий аналитический материал.

ПРИОРИТЕТ ВЫБОРА:
1. Фундаментальные прорывы в архитектуре AI и Scaling Laws.
2. Инфраструктура AGI: вычислительные кластеры, энергия, чипы.
3. Геополитическая конкуренция и суверенитет в области AI.

ЗАПРЕЩЕНО (NEGATIVE CONSTRAINTS) — КРИТИЧЕСКИ ВАЖНО:
- НИКАКИХ ЭМОДЗИ (никаких 🚀, ✅, 🟢, 🟡, 🔵 и прочих).
- НИКАКИХ СИМВОЛОВ ОФОРМЛЕНИЯ кроме жирного шрифта.
- НИКАКОГО КЛИКБЕЙТА и журналистских штампов («мир меняется», «будущее наступило»).
- НИКАКИХ ПРИПИСОК в конце текста (никаких «Объем текста: ...», «Статья подготовлена...» или пустых тегов <i></i>).

СТИЛЬ И СТРУКТУРА:
- Тон: Академический, суровый, плотный. Плотность информации — максимальная.
- Разделы: Используй только римские цифры для заголовков (I. [Глава], II. [Глава]...).
- Формат: Только текст и <b>жирные заголовки</b>.

ФОРМАТ ОТВЕТА (строго):

НОМЕР: [число]

<b>[СТРОГИЙ ТЕХНОКРАТИЧЕСКИЙ ЗАГОЛОВОК]</b>

[Текст отчета с делением на главы I, II, III]

ПРАВИЛА ОФОРМЛЕНИЯ:
- Пиши ТОЛЬКО на русском языке.
- Первая строка ответа ОБЯЗАТЕЛЬНО: НОМЕР: N.
- Используй <b>жирный</b> только для заголовков разделов и ключевых терминов.
- Для разделения мыслей используй только двойной перенос строки.

НОВОСТИ:
{news_input}"""

        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                options={
                    "num_ctx": 8192,
                    "num_predict": 4096,
                    "temperature": 0.5
                }
            )
            import re
            raw_text = response['response'].strip()
            
            # Удаляем любые теги "размышлений" (встречаются у MoE-моделей)
            raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
            raw_text = re.sub(r'<\|thought\|>.*?</\|thought\|>', '', raw_text, flags=re.DOTALL)
            raw_text = raw_text.strip()

            # Извлекаем номер выбранной новости
            selected_news = None
            article_lines = []

            for line in raw_text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("НОМЕР:") or stripped.upper().startswith("SELECTED:"):
                    try:
                        number_part = stripped.split(":")[1].strip().rstrip(".")
                        index = int(number_part) - 1
                        if 0 <= index < len(news_list):
                            selected_news = news_list[index]
                    except (ValueError, IndexError):
                        pass
                else:
                    article_lines.append(line)

            article_text = "\n".join(article_lines).strip()
            
            # Конвертируем случайный маркдаун в HTML
            article_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', article_text)
            article_text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', article_text)
            
            # Гарантированно делаем первую строку (заголовок) жирной, если она еще не жирная
            if article_text:
                blocks = article_text.split('\n\n')
                if blocks and not blocks[0].startswith("<b>"):
                    blocks[0] = f"<b>{blocks[0]}</b>"
                article_text = "\n\n".join(blocks)

            # Фоллбэк: если модель не указала номер, берём первую новость
            if not selected_news and news_list:
                selected_news = news_list[0]

            return article_text, selected_news

        except Exception as e:
            return f"Ошибка при анализе нейросетью: {str(e)}", None


llm_processor = LLMProcessor()
