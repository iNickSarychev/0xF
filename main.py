import asyncio
import aiohttp
import logging
import sys
import pytz
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.markdown import hbold
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ForceReply
)
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config
from database import db
from services.news_fetcher import news_fetcher
from services.editor_agent import editor_agent
from services.vision_agent import vision_agent
from services.image_handler import image_handler
from services.text_processor import text_processor
from aiogram.exceptions import TelegramRetryAfter
from datetime import datetime, timedelta

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("debug.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Снижаем шум от библиотек
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

# ─── Инициализация ────────────────────────────────────────────────────────────
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML"),
)
dp = Dispatcher(storage=MemoryStorage())
msk_tz = pytz.timezone("Europe/Moscow")
scheduler = AsyncIOScheduler(timezone=msk_tz)

# Счётчик подряд идущих сбоев LLM для алертов
_llm_failure_streak: int = 0
LLM_ALERT_THRESHOLD: int = 5


# ─── FSM: причина отклонения с обучением ─────────────────────────────────────
class RejectTeachStates(StatesGroup):
    waiting_for_reason = State()


# ─── Middleware: только для админа ────────────────────────────────────────────
@dp.message.outer_middleware()
async def admin_only_middleware(handler, event: types.Message, data):
    """Молча игнорирует входящие сообщения от не-adminов."""
    if event.from_user.id != config.ADMIN_CHAT_ID:
        return
    return await handler(event, data)


# ─── Глобальный обработчик FloodWait ─────────────────────────────────────────
@dp.error()
async def error_handler(event: types.ErrorEvent):
    if isinstance(event.exception, TelegramRetryAfter):
        retry_after = event.exception.retry_after
        logger.warning(f"Flood limit reached. Sleeping for {retry_after}s.")
        await asyncio.sleep(retry_after)
        return True
    logger.error(f"Update error: {event.exception}", exc_info=event.exception)
    return False


# ─── Утилиты алертов ─────────────────────────────────────────────────────────
async def send_admin_alert(message: str) -> None:
    """Отправляет критическое сообщение напрямую в личку админу."""
    try:
        await bot.send_message(
            config.ADMIN_CHAT_ID,
            f"🚨 <b>ALERT:</b> {message}",
            request_timeout=30,
        )
    except Exception as exc:
        logger.error(f"Failed to send admin alert: {exc}")


def _reset_llm_failure_streak() -> None:
    global _llm_failure_streak
    _llm_failure_streak = 0


async def _register_llm_failure(reason: str) -> None:
    """Увеличивает счётчик ошибок LLM и шлёт алерт при достижении порога."""
    global _llm_failure_streak
    _llm_failure_streak += 1
    logger.error(f"LLM failure #{_llm_failure_streak}: {reason}")

    if _llm_failure_streak >= LLM_ALERT_THRESHOLD:
        await send_admin_alert(
            f"LLM упала или выдаёт мусор <b>{_llm_failure_streak}</b> раз(а) подряд.\n"
            f"Последняя ошибка: <code>{reason[:300]}</code>"
        )
        _llm_failure_streak = 0  # сброс, чтобы не спамить


# ─── Публикация на канал ──────────────────────────────────────────────────────
async def publish_to_channel(article_text: str, image_url: str = None) -> None:
    """Публикует статью на канале с фото или текстом."""
    try:
        if image_url:
            await bot.send_photo(
                config.CHANNEL_ID,
                photo=image_url,
                caption=article_text,
                request_timeout=60,
            )
        else:
            await bot.send_message(
                config.CHANNEL_ID, article_text, request_timeout=60
            )
        logger.info("Article published to channel.")
    except Exception as exc:
        logger.error(f"Failed to publish to channel: {exc}")
        # Фоллбэк: пробуем без фото
        try:
            await bot.send_message(
                config.CHANNEL_ID, article_text, request_timeout=60
            )
        except Exception as fallback_exc:
            logger.error(f"Fallback publish also failed: {fallback_exc}")


# ─── Автопубликация по таймеру ────────────────────────────────────────────────
async def auto_publish(message_id: int) -> None:
    """Автопубликует статью, если админ не ответил за отведённое время."""
    pending_data = db.get_pending_post(message_id)
    if not pending_data:
        return

    await publish_to_channel(pending_data["text"], pending_data.get("image"))
    db.remove_pending_post(message_id)

    try:
        await bot.edit_message_reply_markup(
            chat_id=config.ADMIN_CHAT_ID,
            message_id=message_id,
            reply_markup=None,
        )
        await bot.send_message(
            config.ADMIN_CHAT_ID,
            "⏰ Время вышло — статья опубликована автоматически.",
        )
    except Exception as exc:
        logger.warning(f"Could not notify admin about auto-publish: {exc}")


# ─── Утилиты подготовки публикации ───────────────────────────────────────────
def _build_moderation_keyboard(source_url: str | None = None) -> InlineKeyboardMarkup:
    """Строит клавиатуру модерации с кнопкой перегенерации и источником."""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data="approve"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data="reject"),
        ],
        [
            InlineKeyboardButton(
                text="🔄 Перегенерировать", callback_data="regenerate"
            ),
            InlineKeyboardButton(
                text="🎓 Обучить", callback_data="reject_teach"
            ),
        ]
    ]
    
    if source_url:
        buttons.append([InlineKeyboardButton(text="🔗 Читать оригинал", url=source_url)])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _truncate_article(article_text: str) -> str:
    """Умная обрезка: ищет последнюю точку перед лимитом Telegram."""
    article_text = article_text.strip()
    if len(article_text) <= 3700:
        return article_text

    truncated = article_text[:3700]
    last_period = truncated.rfind(".")
    if last_period > 3000:
        return truncated[: last_period + 1]
    return truncated + "..."


async def _find_valid_image(news_item: dict, image_query: str | None) -> str | None:
    """
    Ищет валидную картинку по трём стратегиям:
    1. RSS-картинка → 2. og:image из статьи → 3. DuckDuckGo.
    """
    # 1. RSS-картинка
    rss_image = news_item.get("image")
    if rss_image and await image_handler.is_valid_image(rss_image):
        if await vision_agent.check_image(news_item.get("title", ""), rss_image):
            logger.info(f"Using valid image from RSS: {rss_image}")
            return rss_image
        logger.info(f"Vision rejected RSS image: {rss_image}")

    # 2. og:image из оригинальной статьи
    if news_item.get("link"):
        logger.info("Parsing original article for og:image...")
        extracted_img = await image_handler.extract_article_image(news_item["link"])
        if extracted_img and await vision_agent.check_image(
            news_item.get("title", ""), extracted_img
        ):
            logger.info(f"Using og:image: {extracted_img}")
            return extracted_img
        if extracted_img:
            logger.info(f"Vision rejected og:image: {extracted_img}")

    # 3. DuckDuckGo
    if image_query:
        logger.info(f"Searching DDG: '{image_query}'")
        ddg_img = await image_handler.find_best_image(query=image_query)
        if ddg_img and await vision_agent.check_image(
            news_item.get("title", ""), ddg_img
        ):
            logger.info(f"DDG image approved: {ddg_img}")
            return ddg_img
        if ddg_img:
            logger.info(f"Vision rejected DDG image: {ddg_img}")

    return None


async def _send_to_admin(
    chat_id: int,
    final_text: str,
    image_url: str | None,
    keyboard: InlineKeyboardMarkup,
    header: str,
) -> types.Message | None:
    """
    Отправляет сообщение на модерацию.
    При ошибке фото — падает на текст. Возвращает None при критическом сбое.
    """
    try:
        if image_url:
            return await bot.send_photo(
                chat_id,
                photo=image_url,
                caption=f"{header}\n\n{final_text}",
                reply_markup=keyboard,
                request_timeout=60,
            )
        return await bot.send_message(
            chat_id,
            f"{header}\n\n{final_text}",
            reply_markup=keyboard,
            request_timeout=60,
        )
    except Exception as exc:
        logger.error(f"Error sending to admin (likely photo issue): {exc}")
        try:
            return await bot.send_message(
                chat_id,
                f"📝 <b>На модерацию (без фото):</b>\n\n{final_text}",
                reply_markup=keyboard,
                request_timeout=60,
            )
        except Exception as exc2:
            logger.error(f"Critical send error: {exc2}")
            return None


async def _schedule_pending_post(
    sent_msg: types.Message,
    pending_data: dict,
    publish_time: datetime,
) -> None:
    """Сохраняет пост в БД и добавляет задачу автопубликации в планировщик."""
    db.save_pending_post(sent_msg.message_id, pending_data, publish_time.isoformat())
    scheduler.add_job(
        auto_publish,
        trigger="date",
        run_date=publish_time,
        args=[sent_msg.message_id],
        id=f"publish_{sent_msg.message_id}",
    )


# ─── Основная генерация и модерация ──────────────────────────────────────────
async def _run_generation_pipeline(
    news_list: list[dict],
) -> tuple[str | None, dict | None, str | None]:
    """
    Запускает полный цикл генерации с качественной проверкой (2 попытки).
    Возвращает (article_text, news_item, image_query) или (None, None, None).
    """
    for attempt in range(2):
        article_text, news_item, image_query = await editor_agent.process_news_batch(
            news_list
        )

        if not news_item:
            logger.info("News rejected by model or no news selected.")
            return None, None, None

        article_text = text_processor.clean_llm_output(article_text)
        article_text = await text_processor.fix_spelling(article_text)

        if text_processor.passes_quality_check(article_text):
            _reset_llm_failure_streak()
            return article_text, news_item, image_query

        logger.warning(f"Quality check failed (attempt {attempt + 1}).")

    await _register_llm_failure("Quality check failed after 2 attempts.")
    return None, None, None


async def generate_and_moderate() -> None:
    """Генерирует статью и отправляет её в чат админа на модерацию."""
    try:
        if not await editor_agent.is_available():
            logger.warning("Ollama is offline. Skipping.")
            return

        news_list = await news_fetcher.get_news_batch(max_count=15)
        if not news_list:
            logger.info("No fresh news. Skipping.")
            return

        article_text, news_item, image_query = await _run_generation_pipeline(news_list)
        if not news_item:
            return

        valid_image = await _find_valid_image(news_item, image_query)
        news_item["image"] = valid_image

        source_link = news_item.get("link", "")
        db.save_news(news_item["title"], source_link)
        if "vector" in news_item:
            db.save_sent_vector(news_item["title"], news_item["vector"])

        final_text = _truncate_article(article_text) + "\n\n<b>@AxFUTURE</b>"
        keyboard = _build_moderation_keyboard(source_link)
        publish_time = datetime.now(msk_tz) + timedelta(minutes=10)

        pending_data = {
            "text": final_text,
            "image": news_item.get("image"),
            "news_item": news_item,
            "news_list": news_list,  # для перегенерации
        }

        sent_msg = await _send_to_admin(
            config.ADMIN_CHAT_ID,
            final_text,
            valid_image,
            keyboard,
            header="📝 <b>На модерацию (авто через 10 мин):</b>",
        )
        if sent_msg:
            await _schedule_pending_post(sent_msg, pending_data, publish_time)

    except Exception as exc:
        logger.error(f"Scheduled generate_and_moderate error: {exc}")


# ─── Callback-обработчики модерации ───────────────────────────────────────────
@dp.callback_query(F.data == "approve")
async def on_approve(callback: types.CallbackQuery) -> None:
    """Админ одобрил — публикуем на канале."""
    message_id = callback.message.message_id
    pending_data = db.get_pending_post(message_id)

    if not pending_data:
        await callback.answer("Эта статья уже обработана или не найдена.", show_alert=True)
        return

    await publish_to_channel(pending_data["text"], pending_data.get("image"))

    try:
        scheduler.remove_job(f"publish_{message_id}")
    except Exception:
        pass
    db.remove_pending_post(message_id)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Опубликовано на канале!", show_alert=True)


@dp.callback_query(F.data == "reject")
async def on_reject(callback: types.CallbackQuery) -> None:
    """Админ отклонил — не публикуем."""
    message_id = callback.message.message_id

    try:
        scheduler.remove_job(f"publish_{message_id}")
    except Exception:
        pass
    db.remove_pending_post(message_id)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("❌ Статья отклонена.", show_alert=True)


@dp.callback_query(F.data == "regenerate")
async def on_regenerate(callback: types.CallbackQuery) -> None:
    """Перегенерирует пост по той же выборке новостей с повышенной температурой."""
    message_id = callback.message.message_id
    pending_data = db.get_pending_post(message_id)

    if not pending_data:
        await callback.answer("Данные от предыдущей генерации не найдены.", show_alert=True)
        return

    await callback.answer("🔄 Перегенерирую...")

    # Снимаем старую задачу и запись
    try:
        scheduler.remove_job(f"publish_{message_id}")
    except Exception:
        pass
    db.remove_pending_post(message_id)
    await callback.message.edit_reply_markup(reply_markup=None)

    news_list = pending_data.get("news_list") or []
    if not news_list:
        await bot.send_message(
            config.ADMIN_CHAT_ID,
            "⚠️ Нет данных для перегенерации (список новостей пуст)."
        )
        return

    try:
        article_text, news_item, image_query = await editor_agent.process_news_batch(
            news_list, temperature=0.9
        )
        if not news_item:
            await bot.send_message(
                config.ADMIN_CHAT_ID, "🤷 Перегенерация не дала результата."
            )
            return

        article_text = text_processor.clean_llm_output(article_text)
        article_text = await text_processor.fix_spelling(article_text)

        valid_image = await _find_valid_image(news_item, image_query)
        news_item["image"] = valid_image

        final_text = _truncate_article(article_text) + "\n\n<b>@AxFUTURE</b>"
        source_link = news_item.get("link", "")
        keyboard = _build_moderation_keyboard(source_link)
        publish_time = datetime.now(msk_tz) + timedelta(minutes=10)

        new_pending = {
            "text": final_text,
            "image": valid_image,
            "news_item": news_item,
            "news_list": news_list,
        }

        sent_msg = await _send_to_admin(
            config.ADMIN_CHAT_ID,
            final_text,
            valid_image,
            keyboard,
            header="🔄 <b>Перегенерировано (авто через 10 мин):</b>",
        )
        if sent_msg:
            await _schedule_pending_post(sent_msg, new_pending, publish_time)

    except Exception as exc:
        logger.error(f"Regenerate error: {exc}")
        await bot.send_message(
            config.ADMIN_CHAT_ID, f"❌ Ошибка перегенерации: {exc}"
        )


@dp.callback_query(F.data == "reject_teach")
async def on_reject_teach(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Запускает FSM-диалог: спрашивает причину отклонения."""
    message_id = callback.message.message_id
    pending_data = db.get_pending_post(message_id)

    if not pending_data:
        await callback.answer("Эта статья уже обработана.", show_alert=True)
        return

    await state.update_data(pending_message_id=message_id)
    await state.set_state(RejectTeachStates.waiting_for_reason)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await bot.send_message(
        config.ADMIN_CHAT_ID,
        "🎓 <b>Почему отклоняем?</b>\n\n"
        "Напиши причину (например: <i>кликбейт, вода, не по теме, "
        "устаревшее</i>), или отправь /skip чтобы обучить без причины.",
        reply_markup=ForceReply(selective=True),
    )


@dp.message(RejectTeachStates.waiting_for_reason)
async def on_reject_teach_reason(message: types.Message, state: FSMContext) -> None:
    """Получает причину отклонения и сохраняет обучающий вектор."""
    data = await state.get_data()
    pending_message_id: int = data["pending_message_id"]
    pending_data = db.get_pending_post(pending_message_id)

    reason = (
        message.text.strip()
        if message.text and message.text.lower() != "/skip"
        else "не указана"
    )

    await state.clear()

    if not pending_data:
        await message.answer("⚠️ Статья уже была обработана другим способом.")
        return

    news_item = pending_data.get("news_item", {})
    text_for_emb = f"{news_item.get('title', '')}. {news_item.get('summary', '')}"

    # Снимаем задачу
    try:
        scheduler.remove_job(f"publish_{pending_message_id}")
    except Exception:
        pass
    db.remove_pending_post(pending_message_id)

    # Получаем вектор и сохраняем с причиной
    try:
        from services.vector_service import vector_service
        news_item = await vector_service._get_single_embedding(news_item)
        if news_item.get("vector"):
            db.save_rejected_vector(
                f"[{reason}] {text_for_emb[:180]}", news_item["vector"]
            )
            await message.answer(
                f"🎓 Готово! Причина <b>«{reason}»</b> сохранена.\n"
                "Подобный смысл больше не появится в ленте."
            )
        else:
            await message.answer("⚠️ Не удалось получить вектор для обучения.")
    except Exception as exc:
        await message.answer(f"❌ Ошибка обучения: {exc}")


# ─── Команды бота ─────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    db.add_subscriber(message.chat.id)

    kb = [[KeyboardButton(text="🔍 AI-новость дня")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    await message.answer(
        f"Привет, {hbold(message.from_user.full_name)}!\n\n"
        "🤖 Я — AI-редактор канала <b>0xFUTURE</b>.\n\n"
        "📬 Каждый час с 9:00 до 00:00 я генерирую аналитику "
        "и отправляю её на модерацию.\n\n"
        "Нажми кнопку для ручного запроса или используй /news.",
        reply_markup=keyboard,
    )


@dp.message(Command("theme"))
async def cmd_theme(message: types.Message) -> None:
    current_theme = db.get_theme()
    await message.answer(f"🧠 <b>Текущие приоритеты (Тема):</b>\n\n{current_theme}")


@dp.message(Command("set_theme"))
async def cmd_set_theme(message: types.Message) -> None:
    new_theme = message.text.replace("/set_theme", "").strip()
    if not new_theme:
        await message.answer(
            "Укажи новую тему. Пример:\n/set_theme Хочу новости только про крипту",
            parse_mode=None,
        )
        return
    db.set_theme(new_theme)
    await message.answer("✅ Тема успешно обновлена! Нейросеть будет опираться на неё.")


@dp.message(Command("sources"))
async def cmd_sources(message: types.Message) -> None:
    sources = db.get_all_sources()
    if not sources:
        await message.answer("📭 Список источников пуст.")
        return
    text = "📡 <b>Источники RSS:</b>\n\n"
    for sid, url in sources:
        text += f"ID: {sid} | <code>{url}</code>\n"
    await message.answer(text)


@dp.message(Command("add_source"))
async def cmd_add_source(message: types.Message) -> None:
    url = message.text.replace("/add_source", "").strip()
    if not url.startswith("http"):
        await message.answer(
            "Укажи валидный URL. Пример:\n/add_source https://test.com/rss",
            parse_mode=None,
        )
        return

    if db.add_source(url):
        await message.answer(f"✅ Успешно добавлен источник:\n{url}")
    else:
        await message.answer("❌ Этот источник уже есть в базе!")


@dp.message(Command("del_source"))
async def cmd_del_source(message: types.Message) -> None:
    try:
        sid = int(message.text.replace("/del_source", "").strip())
        if db.remove_source(sid):
            await message.answer(f"🗑 Источник с ID {sid} удален.")
        else:
            await message.answer(f"❌ Источник с ID {sid} не найден.")
    except ValueError:
        await message.answer(
            "Укажи числовой ID. Пример:\n/del_source 5", parse_mode=None
        )


@dp.message(Command("news"))
@dp.message(F.text == "🔍 AI-новость дня")
@dp.message(F.text == "Найти свежую новость")
async def cmd_news(message: types.Message) -> None:
    status_msg = await message.answer("🔍 Сканирую AI и tech-источники...")

    try:
        if not await editor_agent.is_available():
            await status_msg.edit_text(
                "🖥️ Ollama недоступна (ПК выключен или Ollama не запущена).\n"
                "Генерация невозможна."
            )
            return

        news_list = await news_fetcher.get_news_batch(max_count=15)
        if not news_list:
            await status_msg.edit_text(
                "🤷 За последние 24 часа не нашлось значимых новостей."
            )
            return

        await status_msg.edit_text(
            f"🖊️ Найдено: {len(news_list)}. Генерирую статью..."
        )

        article_text, news_item, image_query = await _run_generation_pipeline(news_list)
        if not news_item:
            await status_msg.edit_text(
                "🤷 Не нашлось значимых новостей, прошедших проверку качества."
            )
            return

        source_link = news_item.get("link", "")
        db.save_news(news_item["title"], source_link)
        if "vector" in news_item:
            db.save_sent_vector(news_item["title"], news_item["vector"])

        await status_msg.edit_text("🖼️ Ищу подходящее фото...")
        valid_image = await _find_valid_image(news_item, image_query)
        news_item["image"] = valid_image

        source_link = news_item.get("link")
        final_text = _truncate_article(article_text) + "\n\n<b>@AxFUTURE</b>"
        keyboard = _build_moderation_keyboard(source_url=source_link)

        try:
            if valid_image:
                await status_msg.delete()
                sent_msg = await bot.send_photo(
                    message.chat.id,
                    photo=valid_image,
                    caption=final_text,
                    reply_markup=keyboard,
                    request_timeout=60,
                )
                status_msg_id = sent_msg.message_id
            else:
                await status_msg.edit_text(
                    final_text, reply_markup=keyboard, request_timeout=60
                )
                status_msg_id = status_msg.message_id
        except Exception as exc:
            logger.error(f"Error sending manual news: {exc}")
            try:
                sent_msg = await message.answer(final_text, reply_markup=keyboard)
                status_msg_id = sent_msg.message_id
            except Exception as exc2:
                logger.error(f"Critical HTML formatting error: {exc2}")
                await message.answer("❌ Внутренняя ошибка форматирования поста.")
                return

        publish_time = datetime.now(msk_tz) + timedelta(minutes=10)
        pending_data = {
            "text": final_text,
            "image": valid_image,
            "news_item": news_item,
            "news_list": news_list,
        }
        db.save_pending_post(status_msg_id, pending_data, publish_time.isoformat())
        scheduler.add_job(
            auto_publish,
            trigger="date",
            run_date=publish_time,
            args=[status_msg_id],
            id=f"publish_{status_msg_id}",
        )

    except Exception as exc:
        logger.error(f"Error processing /news: {exc}")
        await message.answer("❌ Ошибка при генерации. Попробуй через минуту.")


# ─── Восстановление задач после рестарта ──────────────────────────────────────
async def restore_pending_jobs() -> None:
    """Восстанавливает задачи автопубликации из БД после перезагрузки."""
    pending_posts = db.get_all_pending_posts()
    count = 0
    for message_id, data, publish_at_str in pending_posts:
        publish_at = datetime.fromisoformat(publish_at_str)
        # Делаем время из БД тоже aware, если оно было сохранено в ISO
        if publish_at.tzinfo is None:
            publish_at = msk_tz.localize(publish_at)
            
        if publish_at <= datetime.now(msk_tz):
            logger.info(f"Auto-publishing missed post: {message_id}")
            await auto_publish(message_id)
        else:
            scheduler.add_job(
                auto_publish,
                trigger="date",
                run_date=publish_at,
                args=[message_id],
                id=f"publish_{message_id}",
            )
            count += 1
    if count:
        logger.info(f"Restored {count} pending publication jobs.")


# ─── Точка входа ─────────────────────────────────────────────────────────────
async def main() -> None:
    logger.info("Starting 0xFUTURE Bot with moderation...")

    await restore_pending_jobs()

    scheduler.add_job(
        generate_and_moderate,
        "cron",
        hour="9-23",
        minute=0,
        id="hourly_moderation",
    )
    scheduler.start()
    logger.info("Scheduler: hourly 09:00–23:00 MSK → admin moderation.")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
