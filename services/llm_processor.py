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
            trending_mark = " [TRENDING — тема в нескольких источниках]" if news.get('trending') else ""
            news_input += f"[{i}]{trending_mark} {news['title']}\n{news['summary'][:200]}\n\n"

        current_theme = db.get_theme()
        
        prompt = f"""Ты — автор крупного Telegram-канала о технологиях с 100 000+ подписчиков.
Ты пишешь так, чтобы дочитывали до конца: быстро, цепко, без воды.

ЗАДАНИЕ:
Ниже {len(news_list)} новостей. Выбери ОДНУ самую интересную и напиши по ней пост.

ГЛАВНАЯ ЦЕЛЬ:
Удержать внимание до последней строки.

КАК ПИСАТЬ:
- первое предложение — сразу цепляет (факт, цифра или неожиданность)
- второе — усиливает интерес или добавляет контекст
- дальше — короткие абзацы или список
- в тексте должен быть "крючок" (что здесь необычного / почему это важно)
- можно добавить легкий поворот или контраст в конце

СТИЛЬ:
- как будто пишешь коллеге-разработчику в личку
- допускаются короткие, резкие предложения
- можно ломать ритм (длинное → короткое)
- допускается легкая эмоция: удивление, скепсис, ирония
- текст НЕ должен быть идеально гладким

АНТИ-ИИ (КРИТИЧНО):
- не используй шаблоны:
  "это открывает новые возможности"
  "стоит отметить"
  "интересно, что"
  "в целом"
- избегай идеальной структуры
- не делай одинаковые по длине предложения
- не пиши как статья или пресс-релиз

ПРАВИЛА:
- 300–600 символов
- без заголовка
- сразу с факта
- <b>жирным</b> только названия и цифры
- списки через «–»
- без эмодзи, хештегов, Markdown
- без вводных фраз

ФИШКА ДЛЯ УДЕРЖАНИЯ:
- можно добавить микро-интригу:
  "и вот тут самое интересное"
  "но есть нюанс"
  "и это не самое странное"
(использовать редко, не всегда)

ФОРМАТ:

НОМЕР: [число]

[текст]

Перед отправкой:
если текст звучит как статья — перепиши проще и жестче.

Пиши ТОЛЬКО на русском языке.

Сделай так, чтобы после первого предложения хотелось дочитать.
Если нет — перепиши первое предложение.

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
            article_text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', article_text)

            # Фоллбэк: если модель не указала номер, берём первую новость
            if not selected_news and news_list:
                selected_news = news_list[0]

            return article_text, selected_news

        except Exception as e:
            return f"Ошибка при анализе нейросетью: {str(e)}", None


llm_processor = LLMProcessor()
