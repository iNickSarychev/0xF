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
    FORBIDDEN_PHRASES = []

    @staticmethod
    def hallucination_filter(text: str) -> str:
        """
        Удаляет блоки текста, которые не являются кириллицей, латиницей или цифрами.
        Эффективно вырезает 'китайские галлюцинации'.
        """
        # Очистка на уровне символов: оставляем только "нормальные" для ведения канала символы
        bad_chars_pattern = re.compile(r"[^\x00-\x7F\u0400-\u04FF\s\.,!?;:\"\'\-\(\)\+\«\»\—\>\<\=]")
        return bad_chars_pattern.sub("", text)

    @staticmethod
    def balance_html_tags(text: str) -> str:
        """
        Находит незакрытые теги <b> и <i> и принудительно закрывает их.
        Telegram падает, если есть открытый тег без парного закрывающего.
        """
        text = text.strip()
        for tag in ['b', 'i']:
            open_tags = len(re.findall(rf'<{tag}>', text, re.IGNORECASE))
            close_tags = len(re.findall(rf'</{tag}>', text, re.IGNORECASE))
            
            if open_tags > close_tags:
                text += f'</{tag}>' * (open_tags - close_tags)
            elif close_tags > open_tags:
                # Если закрывающих больше, удаляем лишние с конца (грубый фикс)
                for _ in range(close_tags - open_tags):
                    text = re.sub(rf'</{tag}>$', '', text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def clean_llm_output(text: str) -> str:
        """Очищает текст от технических артефактов нейросети и форматирует логику."""
        # 0. Предварительная фильтрация галлюцинаций
        text = TextProcessor.hallucination_filter(text)

        # 1. Принудительная замена <br> и подобных на переносы
        text = re.sub(r'<(?:br|p|div)[^>]*>', '\n', text, flags=re.IGNORECASE)

        # Удаляем все остальные теги, кроме разрешенных Telegram (b, i, a, code, pre)
        text = re.sub(r'<(?!b\b|/b\b|i\b|/i\b|a\b|/a\b|code\b|/code\b|pre\b|/pre\b)[^>]+>', '', text, flags=re.IGNORECASE)

        # HTML-очистка: Markdown в HTML
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)

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

        # 2. Очистка запрещенных фраз
        for phrase in TextProcessor.FORBIDDEN_PHRASES:
            pattern = re.compile(rf"(?m)^[\s\-–—•]*{re.escape(phrase)}\s*", re.IGNORECASE)
            text = pattern.sub("", text)
            # Также удаляем если фраза просто затесалась в тексте
            text = text.replace(phrase, "")

        # 3. Балансировка HTML
        text = TextProcessor.balance_html_tags(text)
        
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
        if len(clean_text) < 100:
            return False
            
        # Строгая проверка: первая строка должна начинаться с жирного текста
        first_line = text.strip().split("\n")[0].strip()
        if not first_line.startswith("<b>"):
            logger.warning(f"Quality check failed: No <b> at the start of first line: {first_line[:20]}")
            return False
            
        return True


text_processor = TextProcessor()
