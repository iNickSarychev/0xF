import ollama
import httpx
import math
from typing import List, Dict, Tuple, Any, Optional
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
    ) -> Tuple[str, Any, Optional[str]]:
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
        
        prompt = f"""Ты — автор Telegram-канала о технологиях с аудиторией 100 000+.
Ты пишешь так, чтобы текст было легко читать с первого раза без усилий.

ЗАДАНИЕ:
Выбери одну новость и напиши пост.

ГЛАВНОЕ:
Текст должен быть максимально понятным.
Читатель не должен перечитывать предложения.

СТРУКТУРА (ОБЯЗАТЕЛЬНО):
1. Заголовок: Обязательно делай <b>жирный заголовок</b> в первой строке поста.
2. Первый абзац: Сразу к сути — что произошло.
3. Дальше — детали (по порядку, без прыжков)
4. В конце — что это значит для пользователя

ПРАВИЛА ПОНЯТНОСТИ:
- одно предложение = одна мысль
- не прыгай между идеями
- избегай абстракций (“доверие”, “будущее”, “революция”)
- объясняй простыми словами, как другу
- если предложение можно упростить — упростить

СТИЛЬ:
- разговорный, но без пафоса
- без философии и “глубоких выводов”
- без драматизации
- можно короткие предложения

АНТИ-ИИ:
- не пиши как статья
- не используй сложные конструкции
- избегай “красивых, но пустых” фраз

ПРАВИЛА:
- 300–1000 символов
- <b>жирным</b> только заголовок, названия и цифры
- списки через «–» если нужно
- без эмодзи и хештегов

В конце добавь техническое поле с кратким поисковым запросом для картинки на английском языке.
Запрос должен описывать конкретный визуальный образ, подходящий к новости.

ФОРМАТ:

НОМЕР: [номер_новости]
IMAGE_QUERY: [english search query for image]

ЗДЕСЬ_СРАЗУ_НАЧИНАЕТСЯ_ТЕКСТ_ПОСТА

ЗАПРЕЩЕНО добавлять в ответ:
- блоки проверки, чеклисты, самооценку
- строки вроде "Структура:", "Стиль:", "Длина:", "Готово"
- любые мета-комментарии о качестве текста

Пиши ТОЛЬКО на русском (кроме IMAGE_QUERY).
Выведи ТОЛЬКО: НОМЕР, IMAGE_QUERY и текст поста. Ничего больше.

НОВОСТИ:
{news_input}
"""

        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                options={
                    "num_predict": 4096,
                }
            )
            import re
            raw_text = response['response'].strip()
            
            # Удаляем любые теги "размышлений" (встречаются у MoE-моделей)
            raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
            raw_text = re.sub(r'<\|thought\|>.*?</\|thought\|>', '', raw_text, flags=re.DOTALL)
            raw_text = raw_text.strip()

            # Извлекаем номер выбранной новости и поисковый запрос
            selected_news = None
            image_query = None
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
                elif stripped.upper().startswith("IMAGE_QUERY:"):
                    image_query = stripped.split(":", 1)[1].strip()
                else:
                    article_lines.append(line)

            article_text = "\n".join(article_lines).strip()
            
            # Удаляем маркер ЗДЕСЬ_СРАЗУ_НАЧИНАЕТСЯ_ТЕКСТ_ПОСТА если модель его напечатала
            import re
            article_text = re.sub(r'(?i)ЗДЕСЬ_СРАЗУ_НАЧИНАЕТСЯ_ТЕКСТ_ПОСТА\n?', '', article_text).strip()
            article_text = re.sub(r'\[текст\]\n?', '', article_text).strip()

            # Конвертируем случайный маркдаун в HTML
            article_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', article_text)
            article_text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', article_text)

            # Фоллбэк: если модель не указала номер, берём первую новость
            if not selected_news and news_list:
                selected_news = news_list[0]

            return article_text, selected_news, image_query

        except Exception as e:
            return f"Ошибка при анализе нейросетью: {str(e)}", None, None

    async def check_image_relevance(self, post_text: str, image_url: str) -> bool:
        """Проверяет релевантность картинки посту через LLM."""
        prompt = (
            "Ты — редактор Telegram-канала.\n"
            "Проверь, подходит ли изображение к тексту поста.\n\n"
            f"ТЕКСТ ПОСТА:\n{post_text}\n\n"
            f"URL КАРТИНКИ: {image_url}\n\n"
            "Картинка должна визуально отражать суть новости "
            "или быть качественным тематическим фото.\n"
            "Ответь ТОЛЬКО одним словом: YES или NO."
        )
        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                options={"num_predict": 10}
            )
            answer = response['response'].strip().upper()
            return "YES" in answer
        except Exception:
            return True  # Фоллбэк — считаем релевантной


llm_processor = LLMProcessor()
