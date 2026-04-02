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


async def publish_to_channel(article_text: str):
    """Публикует статью на канале."""
    try:
        await bot.send_message(
            config.CHANNEL_ID, article_text, request_timeout=60
        )
        logger.info("Article published to channel.")
    except Exception as e:
        logger.error(f"Failed to publish to channel: {e}")
        try:
            await bot.send_message(
                config.CHANNEL_ID, article_text,
                parse_mode=None, request_timeout=60
            )
        except Exception as fallback_error:
            logger.error(f"Fallback publish also failed: {fallback_error}")


async def auto_publish(message_id: int):
    """Автопубликация через 10 минут, если админ не ответил."""
    await asyncio.sleep(600)  # 10 минут

    if message_id in pending_articles:
        article_text = pending_articles.pop(message_id)
        await publish_to_channel(article_text)

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


async def generate_and_moderate():
    """Генерирует статью и отправляет админу на модерацию."""
    try:
        news_list = news_fetcher.get_news_batch(max_count=15)

        if not news_list:
            logger.info("No fresh news found, skipping scheduled job.")
            return

        article_text, source_link = await llm_processor.process_news_batch(
            news_list
        )

        # Сохраняем выбранную новость в базу
        for news in news_list:
            if news['link'] == source_link:
                db.save_news(news['title'], news['link'])
                break

        # Добавляем ссылку на источник
        if source_link:
            article_text += f'\n\n🔗 <a href="{source_link}">Источник</a>'

        final_text = article_text[:4000]

        # Отправляем админу с кнопками модерации
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать", callback_data="approve"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data="reject"
                )
            ]
        ])

        try:
            sent_msg = await bot.send_message(
                config.ADMIN_CHAT_ID,
                f"📝 <b>На модерацию:</b>\n"
                f"<i>(автопубликация через 10 мин)</i>\n\n"
                f"{'─' * 30}\n\n"
                f"{final_text}",
                reply_markup=keyboard,
                request_timeout=60
            )
        except Exception:
            sent_msg = await bot.send_message(
                config.ADMIN_CHAT_ID,
                f"📝 На модерацию (автопубликация через 10 мин):\n\n"
                f"{final_text}",
                reply_markup=keyboard,
                parse_mode=None,
                request_timeout=60
            )

        # Сохраняем статью и запускаем таймер автопубликации
        pending_articles[sent_msg.message_id] = final_text
        asyncio.create_task(auto_publish(sent_msg.message_id))

    except Exception as e:
        logger.error(f"Scheduled generate_and_moderate error: {e}")


# === Обработчик кнопок модерации ===

@dp.callback_query(F.data == "approve")
async def on_approve(callback: types.CallbackQuery):
    """Админ одобрил — публикуем на канале."""
    message_id = callback.message.message_id

    if message_id in pending_articles:
        article_text = pending_articles.pop(message_id)
        await publish_to_channel(article_text)
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


@dp.message(Command("news"))
@dp.message(F.text == "🔍 AI-новость дня")
@dp.message(F.text == "Найти свежую новость")
async def cmd_news(message: types.Message):
    status_msg = await message.answer("🔍 Сканирую AI и tech-источники...")

    try:
        news_list = news_fetcher.get_news_batch(max_count=15)

        if not news_list:
            await status_msg.edit_text(
                "🤷 За последние 24 часа не нашлось значимых новостей."
            )
            return

        await status_msg.edit_text(
            f"🖊️ Найдено: {len(news_list)}. Генерирую статью..."
        )

        article_text, source_link = await llm_processor.process_news_batch(
            news_list
        )

        for news in news_list:
            if news['link'] == source_link:
                db.save_news(news['title'], news['link'])
                break

        if source_link:
            article_text += f'\n\n🔗 <a href="{source_link}">Источник</a>'

        final_text = article_text[:4000]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data="approve"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data="reject")
            ]
        ])

        try:
            await status_msg.edit_text(final_text, reply_markup=keyboard, request_timeout=60)
        except Exception:
            await status_msg.edit_text(
                final_text, parse_mode=None, reply_markup=keyboard, request_timeout=60
            )
            
        pending_articles[status_msg.message_id] = final_text

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
