import aiohttp
import hashlib
import logging
import re

from async_lru import alru_cache

logger = logging.getLogger(__name__)

SPELLER_URL = "https://speller.yandex.net/services/spellservice.json/checkText"


@alru_cache(maxsize=128)
async def _fetch_spelling_corrections(text_hash: str, text: str) -> str:
    """
    Внутренняя кэшируемая функция: делает HTTP-запрос к Яндекс.Спеллеру.
    Ключ кэша — text_hash (md5 от текста), text передаётся для самого запроса.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                SPELLER_URL,
                data={"text": text, "lang": "ru", "options": 2},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return text

                corrections = await response.json()
                if not corrections:
                    return text

                result = text
                for correction in sorted(corrections, key=lambda c: c["pos"], reverse=True):
                    original_word = correction["word"]

                    # Не трогаем плейсхолдеры тегов
                    if "TAG" in original_word:
                        continue

                    # Не трогаем латиницу (OpenAI, Meta и т.д.)
                    if not any("а" <= ch.lower() <= "я" for ch in original_word):
                        continue

                    if correction.get("s"):
                        fixed_word = correction["s"][0]
                        start_pos = correction["pos"]
                        end_pos = start_pos + correction["len"]
                        result = result[:start_pos] + fixed_word + result[end_pos:]

                return result

    except Exception as exc:
        logger.warning(f"Speller API error: {exc}")
        return text


class TextProcessor:
    @staticmethod
    def clean_llm_output(text: str) -> str:
        """Очищает текст от технических артефактов нейросети."""
        # Удаляем строку IMAGE_QUERY
        text = re.sub(r"^IMAGE_QUERY:.*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
        # Удаляем строки с номером новости
        text = re.sub(
            r"^.*(?:НОМЕР|НОМБР|НОВОМБР|SELECTED|NUMBER|NOMEP)\s*[:\-]?\s*\[?\d+\]?.*$",
            "",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        # Удаляем одинокие числа на отдельной строке
        text = re.sub(r"^\s*\d{1,2}\s*$", "", text, flags=re.MULTILINE)
        # Удаляем блоки самопроверки
        text = re.sub(
            r"\[(?:Проверка|Checklist|Check|Самопроверка).*",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Удаляем строки-метрики
        text = re.sub(
            r"^(?:Структура|Стиль|Понятность|Длина|Форматирование|Готово)[:\*].*$",
            "",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        # Удаляем приписки про объем
        text = re.sub(r"\(Объем текста:.*?\)", "", text, flags=re.IGNORECASE)
        # Удаляем пустые теги
        text = re.sub(r"<i></i>\*?", "", text)
        # Очистка пустых строк
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        # Удаляем одинокий номер новости в начале
        text = re.sub(r"^\d{1,2}\s*\n", "", text)
        # Удаляем заголовки-секции из промпта, которые модель иногда печатает буквально
        # Паттерн для bullet-маркеров перед заголовком: "- Победители:", "– Проигравшие:", "- - Победители:"
        _bullet_prefix = r"^[\s\-–—•]*"
        # Русские варианты
        text = re.sub(
            _bullet_prefix
            + r"(?:TL;?DR|Суть(?:\s+для\s+нас)?|So\s+What\??|Финал|"
            r"Практический\s+юзкейс|Детали|Заголовок|Контекст|Вердикт|"
            r"Киллер[\-\s]?фичи|Ложка\s+дегтя|Ограничения|"
            r"Победители|Проигравшие|Итог)[:\-]?\s*",
            "",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        # Английские варианты
        text = re.sub(
            _bullet_prefix
            + r"(?:Winners|Losers|Verdict|Context|Catch|Bottom\s+line|"
            r"Killer\s+features|Why\s+it\s+matters|Practical\s+use\s+case|"
            r"Closing(?:\s+line)?|Limitations|Details|Headline)[:\-]?\s*",
            "",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        return text.strip()

    @staticmethod
    async def fix_spelling(text: str) -> str:
        """
        Исправляет опечатки через Яндекс.Спеллер.
        HTML-теги временно заменяются плейсхолдерами, чтобы API их не испортил.
        Результат кэшируется по md5-хэшу входного текста.
        """
        html_tags: dict[str, str] = {}
        tag_counter = 0

        def replace_tag(match: re.Match) -> str:
            nonlocal tag_counter
            placeholder = f"__TAG{tag_counter}__"
            html_tags[placeholder] = match.group(0)
            tag_counter += 1
            return placeholder

        clean_text = re.sub(r"<[^>]+>", replace_tag, text)

        text_hash = hashlib.md5(clean_text.encode()).hexdigest()
        corrected_text = await _fetch_spelling_corrections(text_hash, clean_text)

        # Восстанавливаем теги
        for placeholder, tag in html_tags.items():
            corrected_text = corrected_text.replace(placeholder, tag)

        return corrected_text

    @staticmethod
    def passes_quality_check(text: str) -> bool:
        """Проверяет качество текста по минимальным критериям."""
        if not text or len(text) < 150:
            return False

        garbage_markers = ["<i></i>", "<b></b>", "***", "---", "Объем текста:"]
        if any(marker in text for marker in garbage_markers):
            return False

        clean_text = re.sub(r"<[^>]+>", "", text).strip()
        return len(clean_text) >= 100


text_processor = TextProcessor()
