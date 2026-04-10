# 0xFUTURE AI News Editor Bot

![0xFUTURE Logo](https://img.shields.io/badge/0xFUTURE-AI_Editor-00FF00?style=for-the-badge&logo=telegram)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat)
![Ollama](https://img.shields.io/badge/Ollama-2026-black?style=flat)

**0xFUTURE Bot** — это автономный Telegram-бот, который собирает, анализирует и пишет аналитические лонгриды по новостям технологий и AI. Бот работает на базе локальной LLM-архитектуры через Ollama (оптимизировано под **T-lite-it-2.1**).

## 🚀 Основной функционал

- **Автоматический парсинг (RSSFetcher):** Мониторинг ключевых новостных лент (Google, DeepMind, OpenAI, Meta, HuggingFace и др.) с фильтрацией дубликатов через эмбеддинги.
- **Интеллектуальный анализ (LLMProcessor):** Перехват топ-15 новостей и генерация одной ёмкой экспертной статьи через локальную LLM с использованием Reflection Loop (Критик + Редактор).
- **Интеграция ссылок:** Автоматическое добавление ссылок на оригинальный источник в конце каждого поста.
- **Система модерации:** Каждое сгенерированное сообщение сначала отправляется администратору. Публикация происходит только после нажатия одной из In-line кнопок (`Опубликовать` / `Отклонить`). 
- **Защита от сбоев:** При отсутствии активности администратора более 10 минут, новость публикуется в канал автоматически (только для запланированных крон-задач).
- **Планировщик APScheduler:** Ежечасная генерация и модерация статей (с 09:00 до 23:00 по MSK).

## 🛠 Технологический стек
- Python 3.10+
- [Aiogram 3.x](https://docs.aiogram.dev/en/latest/) (Асинхронная работа с Telegram API)
- [Ollama](https://ollama.com/) (Локальный запуск открытых моделей)
- [APScheduler](https://apscheduler.readthedocs.io/en/3.x/) (Планировщик)
- SQLite (Хранение базы обработанных ссылок)
- asyncio, aiohttp, feedparser

## 📦 Установка и запуск

1. **Клонируйте репозиторий:**
   ```bash
   git clone https://github.com/NickSarychev/0xF.git
   cd 0xF
   ```

2. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Установите [Ollama](https://ollama.com/)** и загрузите базовые модели:
   ```bash
   ollama pull t-tech/T-lite-it-2.1:q4_K_M
   ollama pull nomic-embed-text
   ```
   *Примечание: скрипт start_bot.bat сам создаст кастомную модель `0xf-writer` из Modelfile.*

4. **Настройте переменные окружения:**
   Создайте файл `.env` в корне проекта (смотрите `config.py` для списка) и внесите ваши данные:
   ```env
   BOT_TOKEN=your_bot_token_here
   OLLAMA_MODEL=gemma4
   OLLAMA_BASE_URL=http://localhost:11434
   CHANNEL_ID=@YourChannelUsername
   ADMIN_CHAT_ID=123456789
   ```

5. **Запуск (локально, Windows):**
   В Windows используйте `start_bot.bat` для автоматической очистки зависших процессов и спокойного старта:
   ```cmd
   start_bot.bat
   ```

## 🌐 Деплой на VDS (Ubuntu) + Ollama на локальном ПК

Бот может работать на удалённом сервере, а LLM-генерацию выполнять на вашем ПК через **Tailscale VPN**.

1. **Установите Tailscale** на ПК ([tailscale.com/download](https://tailscale.com/download)) и на VDS:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

2. **Настройте Ollama** на ПК для приёма внешних подключений (переменная окружения Windows):
   ```
   OLLAMA_HOST=0.0.0.0
   ```

3. **Запустите скрипт установки** на VDS:
   ```bash
   bash <(curl -s https://raw.githubusercontent.com/NickSarychev/0xF/main/deploy/setup_vds.sh)
   ```

4. **Отредактируйте `.env`** на VDS, указав Tailscale IP вашего ПК:
   ```bash
   nano /opt/0xf/.env
   # OLLAMA_BASE_URL=http://100.x.x.x:11434
   ```

5. **Запустите как systemd-сервис:**
   ```bash
   sudo cp /opt/0xf/deploy/bot.service /etc/systemd/system/0xf-bot.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now 0xf-bot
   ```

> **Примечание:** Если ПК выключен или Ollama не запущена, бот автоматически пропускает генерацию и ждёт следующего цикла.

## 🎮 Администрирование через Telegram
Бот поддерживает прямое управление параметрами из интерфейса Telegram для Администратора:

- **RSS Источники:**
  - `/sources` — Показать все текущие активные RSS-ленты
  - `/add_source [URL]` — Добавить новую ленту
  - `/del_source [ID]` — Удалить ленту по ID

- **Фокус-тема нейросети:**
  - `/theme` — Узнать текущую тему генерации
  - `/set_theme [текст]` — Указать нейросети главный приоритет. Например: `/set_theme Ищи только новости про новые LLM и OpenSource`

## 🧠 Архитектура
- `main.py` — Точка входа, Middleware для защиты (Admin_only), клавиатуры и Scheduler.
- `database.py` — Управление SQLite.
- `config.py` — Подгрузка данных из `.env` и список RSS-источников.
- `services/news_fetcher.py` — Асинхронный RSS-агрегатор.
- `services/llm_processor.py` — Логика взаимодействия с Ollama API (включая очистку от тегов размышлений `think` `thought`).

## 👨‍💻 Разработчик
NickSarychev
Создано специально для канала 0xFUTURE.
