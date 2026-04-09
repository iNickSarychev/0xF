import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.markdown import hbold
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config
from database import db
from services.news_fetcher import news_fetcher
from services.llm_processor import llm_processor
from services.image_handler import image_handler

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


@dp.message.outer_middleware()
async def admin_only_middleware(handler, event: types.Message, data):
    """Игнорирует сообщения от всех, кроме админа."""
    if event.from_user.id != config.ADMIN_CHAT_ID:
        return  # Молча игнорируем
    return await handler(event, data)

# Хранилище статей, ожидающих модерации: {message_id: article_text}
pending_articles: dict[int, str] = {}


async def publish_to_channel(article_text: str, image_url: str = None):
    """Публикует статью на канале с фото или текстом."""
    try:
        if image_url:
            await bot.send_photo(
                config.CHANNEL_ID,
                photo=image_url,
                caption=article_text,
                request_timeout=60
            )
        else:
            await bot.send_message(
                config.CHANNEL_ID, article_text, request_timeout=60
            )
        logger.info("Article published to channel.")
    except Exception as e:
        logger.error(f"Failed to publish to channel: {e}")
        # Если не удалось отправить фото (например, битая ссылка), пробуем просто текст
        try:
            await bot.send_message(
                config.CHANNEL_ID, article_text, request_timeout=60
            )
        except Exception as fallback_error:
            logger.error(f"Fallback publish also failed: {fallback_error}")


async def auto_publish(message_id: int):
    """Автопубликация через 10 минут, если админ не ответил."""
    await asyncio.sleep(600)  # 10 минут

    if message_id in pending_articles:
        article_data = pending_articles.pop(message_id)
        await publish_to_channel(article_data['text'], article_data.get('image'))

        # Уведомляем админа
        try:
            await bot.edit_message_reply_markup(
                chat_id=config.ADMIN_CHAT_ID,
                message_id=message_id,
                reply_markup=None
            )
            await bot.send_message(
                config.ADMIN_CHAT_ID,
                "⏰ Время вышло — статья опубликована автоматически."
            )
        except Exception as e:
            logger.warning(f"Could not notify admin about auto-publish: {e}")


def clean_llm_output(text: str) -> str:
    """Очищает текст от технических артефактов нейросети."""
    import re
    # Удаляем строку IMAGE_QUERY
    text = re.sub(r'^IMAGE_QUERY:.*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    # Удаляем блоки самопроверки модели: [Проверка...], [Checklist...] и всё после них
    text = re.sub(r'\[(?:Проверка|Checklist|Check|Самопроверка).*', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Удаляем отдельные строки-метрики: "Структура:*", "Стиль:*", "Длина:*" и т.п.
    text = re.sub(r'^(?:Структура|Стиль|Понятность|Длина|Форматирование|Готово)[:\*].*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    # Удаляем приписки про объем текста
    text = re.sub(r'\(Объем текста:.*?\)', '', text, flags=re.IGNORECASE)
    # Удаляем пустые теги и странные конструкции вроде <i></i>*
    text = re.sub(r'<i><\/i>\*?', '', text)
    # Удаляем строки, состоящие только из спецсимволов и разделителей
    text = re.sub(r'\n[\*\-]{3,}\n', '\n\n', text)
    # Удаляем лишние пустые строки
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    # Удаляем одинокий номер новости в начале текста (1-2 цифры на отдельной строке)
    text = re.sub(r'^\d{1,2}\s*\n', '', text)
    return text.strip()


def _passes_quality_check(text: str) -> bool:
    """Проверяет качество сгенерированного текста."""
    if not text or len(text) < 150:
        return False
    # Проверяем на мусорные паттерны
    garbage_patterns = ['<i></i>', '<b></b>', '***', '---', 'Объем текста:']
    for pattern in garbage_patterns:
        if pattern in text:
            return False
    # Проверяем, что текст не состоит из одних тегов
    import re
    clean_text = re.sub(r'<[^>]+>', '', text).strip()
    if len(clean_text) < 100:
        return False
    return True


async def generate_and_moderate():
    """Генерирует статью и отправляет админу на модерацию."""
    try:
        if not await llm_processor.is_available():
            logger.warning("Ollama is offline. Skipping scheduled generation.")
            return

        news_list = news_fetcher.get_news_batch(max_count=15)

        if not news_list:
            logger.info("No fresh news found, skipping scheduled job.")
            return

        # Генерация с контролем качества (до 2 попыток)
        article_text = None
        news_item = None
        image_query = None
        for attempt in range(2):
            article_text, news_item, image_query = await llm_processor.process_news_batch(
                news_list
            )

            if not news_item:
                logger.info("News rejected by model or no news selected.")
                return

            # Очистка текста от мусора
            article_text = clean_llm_output(article_text)

            # Проверка качества
            if _passes_quality_check(article_text):
                break
            logger.warning(f"Quality check failed (attempt {attempt + 1}). Regenerating...")

        if not _passes_quality_check(article_text):
            logger.error("Quality check failed after 2 attempts. Skipping.")
            return

        # Если в RSS нет картинки — ищем через DuckDuckGo
        if not news_item.get("image") and image_query:
            logger.info(f"No RSS image. Searching DDG: '{image_query}'")
            found_image = await image_handler.find_best_image(
                query=image_query
            )
            if found_image:
                news_item["image"] = found_image
                logger.info(f"DDG image found: {found_image}")

        source_link = news_item.get("link", "")
        db.save_news(news_item['title'], source_link)

        # Умная обрезка: ищем последнюю точку перед лимитом Telegram
        article_text = article_text.strip()
        if len(article_text) > 3700:
            truncated = article_text[:3700]
            last_period = truncated.rfind('.')
            if last_period > 3000:
                article_text = truncated[:last_period + 1]
            else:
                article_text = truncated + "..."

        # Добавляем фирменную подпись
        final_text = article_text + f"\n\n<b>@AxFUTURE</b>"

        # Отправляем админу с кнопками модерации
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать", callback_data="approve"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data="reject"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎓 Отклонить (Обучить)", callback_data="reject_teach"
                )
            ]
        ])

        try:
            if news_item.get("image"):
                sent_msg = await bot.send_photo(
                    config.ADMIN_CHAT_ID,
                    photo=news_item["image"],
                    caption=(
                        f"📝 <b>На модерацию (авто через 10 мин):</b>\n\n"
                        f"{final_text}"
                    ),
                    reply_markup=keyboard,
                    request_timeout=60
                )
            else:
                sent_msg = await bot.send_message(
                    config.ADMIN_CHAT_ID,
                    f"📝 <b>На модерацию (авто через 10 мин):</b>\n\n"
                    f"{final_text}",
                    reply_markup=keyboard,
                    request_timeout=60
                )
        except Exception as e:
            logger.error(f"Error sending moderation message: {e}")
            sent_msg = await bot.send_message(
                config.ADMIN_CHAT_ID,
                f"📝 На модерацию:\n\n{final_text}",
                reply_markup=keyboard,
                parse_mode=None,
                request_timeout=60
            )

        # Сохраняем статью и запускаем таймер автопубликации
        pending_articles[sent_msg.message_id] = {
            'text': final_text, 
            'image': news_item.get("image"),
            'news_item': news_item
        }
        asyncio.create_task(auto_publish(sent_msg.message_id))

    except Exception as e:
        logger.error(f"Scheduled generate_and_moderate error: {e}")


# === Обработчик кнопок модерации ===

@dp.callback_query(F.data == "approve")
async def on_approve(callback: types.CallbackQuery):
    """Админ одобрил — публикуем на канале."""
    message_id = callback.message.message_id

    if message_id in pending_articles:
        article_data = pending_articles.pop(message_id)
        await publish_to_channel(article_data['text'], article_data.get('image'))
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Опубликовано на канале!", show_alert=True)
    else:
        await callback.answer("Эта статья уже обработана.", show_alert=True)


@dp.callback_query(F.data == "reject")
async def on_reject(callback: types.CallbackQuery):
    """Админ отклонил — не публикуем."""
    message_id = callback.message.message_id

    if message_id in pending_articles:
        pending_articles.pop(message_id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("❌ Статья отклонена.", show_alert=True)
    else:
        await callback.answer("Эта статья уже обработана.", show_alert=True)


@dp.callback_query(F.data == "reject_teach")
async def on_reject_teach(callback: types.CallbackQuery):
    """Админ отклонил с обучением — добавляем вектор в базу."""
    message_id = callback.message.message_id

    if message_id in pending_articles:
        article_data = pending_articles.pop(message_id)
        news_item = article_data['news_item']
        
        # Получаем вектор для обучения
        text_for_emb = f"{news_item['title']}. {news_item['summary']}"
        try:
            emb_resp = await llm_processor.client.embeddings(model='nomic-embed-text', prompt=text_for_emb)
            vector = emb_resp['embedding']
            db.save_rejected_vector(text_for_emb[:200], vector)
            await callback.answer("🎓 Модель успешно обучилась. Подобный смысл больше не появится в ленте!", show_alert=True)
        except Exception as e:
            await callback.answer(f"Ошибка обучения: {e}", show_alert=True)
            
        await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await callback.answer("Эта статья уже обработана.", show_alert=True)


# === Команды бота ===

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    db.add_subscriber(message.chat.id)

    kb = [[KeyboardButton(text="🔍 AI-новость дня")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    await message.answer(
        f"Привет, {hbold(message.from_user.full_name)}!\n\n"
        "🤖 Я — AI-редактор канала <b>0xFUTURE</b>.\n\n"
        "📬 Каждый час с 9:00 до 00:00 я генерирую аналитику "
        "и отправляю её на модерацию.\n\n"
        "Нажми кнопку для ручного запроса или используй /news.",
        reply_markup=keyboard
    )


@dp.message(Command("theme"))
async def cmd_theme(message: types.Message):
    current_theme = db.get_theme()
    await message.answer(f"🧠 <b>Текущие приоритеты (Тема):</b>\n\n{current_theme}")


@dp.message(Command("set_theme"))
async def cmd_set_theme(message: types.Message):
    new_theme = message.text.replace("/set_theme", "").strip()
    if not new_theme:
        await message.answer("Укажи новую тему. Пример:\n/set_theme Хочу новости только про крипту", parse_mode=None)
        return
    db.set_theme(new_theme)
    await message.answer("✅ Тема успешно обновлена! Нейросеть будет опираться на неё.")


@dp.message(Command("sources"))
async def cmd_sources(message: types.Message):
    sources = db.get_all_sources()
    if not sources:
        await message.answer("📭 Список источников пуст.")
        return
    text = "📡 <b>Источники RSS:</b>\n\n"
    for sid, url in sources:
        text += f"ID: {sid} | <code>{url}</code>\n"
    await message.answer(text)


@dp.message(Command("add_source"))
async def cmd_add_source(message: types.Message):
    url = message.text.replace("/add_source", "").strip()
    if not url.startswith("http"):
        await message.answer("Укажи валидный URL. Пример:\n/add_source https://test.com/rss", parse_mode=None)
        return
    
    if db.add_source(url):
        await message.answer(f"✅ Успешно добавлен источник:\n{url}")
    else:
        await message.answer("❌ Этот источник уже есть в базе!")


@dp.message(Command("del_source"))
async def cmd_del_source(message: types.Message):
    try:
        sid = int(message.text.replace("/del_source", "").strip())
        if db.remove_source(sid):
            await message.answer(f"🗑 Источник с ID {sid} удален.")
        else:
            await message.answer(f"❌ Источник с ID {sid} не найден.")
    except ValueError:
        await message.answer("Укажи числовой ID. Пример:\n/del_source 5", parse_mode=None)


@dp.message(Command("news"))
@dp.message(F.text == "🔍 AI-новость дня")
@dp.message(F.text == "Найти свежую новость")
async def cmd_news(message: types.Message):
    status_msg = await message.answer("🔍 Сканирую AI и tech-источники...")

    try:
        if not await llm_processor.is_available():
            await status_msg.edit_text(
                "🖥️ Ollama недоступна (ПК выключен или Ollama не запущена).\n"
                "Генерация невозможна."
            )
            return

        news_list = news_fetcher.get_news_batch(max_count=15)

        if not news_list:
            await status_msg.edit_text(
                "🤷 За последние 24 часа не нашлось значимых новостей."
            )
            return

        await status_msg.edit_text(
            f"🖊️ Найдено: {len(news_list)}. Генерирую статью..."
        )

        article_text, news_item, image_query = await llm_processor.process_news_batch(
            news_list
        )

        if not news_item:
            await status_msg.edit_text("🤷 За последние 24 часа не нашлось значимых не отклоненных новостей.")
            return

        # Очистка текста от мусора
        article_text = clean_llm_output(article_text)

        source_link = news_item.get("link", "")
        db.save_news(news_item['title'], source_link)

        # Если в RSS нет картинки — ищем через DuckDuckGo
        if not news_item.get("image") and image_query:
            await status_msg.edit_text("🖼️ Ищу подходящую картинку...")
            found_image = await image_handler.find_best_image(
                query=image_query
            )
            if found_image:
                news_item["image"] = found_image

        # Умная обрезка: ищем последнюю точку перед лимитом Telegram
        article_text = article_text.strip()
        if len(article_text) > 3700:
            truncated = article_text[:3700]
            last_period = truncated.rfind('.')
            if last_period > 3000:
                article_text = truncated[:last_period + 1]
            else:
                article_text = truncated + "..."

        # Добавляем фирменную подпись
        final_text = article_text + f"\n\n<b>@AxFUTURE</b>"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать", callback_data="approve"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data="reject"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎓 Отклонить (Обучить)", callback_data="reject_teach"
                )
            ]
        ])

        try:
            if news_item.get("image"):
                await status_msg.delete()  # Удаляем статусное сообщение, чтобы отправить фото
                sent_msg = await bot.send_photo(
                    message.chat.id,
                    photo=news_item["image"],
                    caption=final_text,
                    reply_markup=keyboard,
                    request_timeout=60
                )
                status_msg_id = sent_msg.message_id
            else:
                await status_msg.edit_text(final_text, reply_markup=keyboard, request_timeout=60)
                status_msg_id = status_msg.message_id
        except Exception as e:
            logger.error(f"Error sending manual news: {e}")
            await message.answer(final_text, reply_markup=keyboard, parse_mode=None)
            return
            
        pending_articles[status_msg_id] = {
            'text': final_text, 
            'image': news_item.get("image"),
            'news_item': news_item
        }

    except Exception as e:
        logger.error(f"Error processing /news: {e}")
        await message.answer(
            "❌ Ошибка при генерации. Попробуй через минуту."
        )


async def main():
    logger.info("Starting 0xFUTURE Bot with moderation...")

    scheduler.add_job(
        generate_and_moderate,
        "cron",
        hour="9-23",
        minute=0,
        id="hourly_moderation"
    )
    scheduler.start()
    logger.info("Scheduler: hourly 09:00–23:00 MSK → admin moderation.")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
