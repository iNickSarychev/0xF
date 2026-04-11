#!/bin/bash

# Скрипт автоматического обновления и перезапуска бота
echo "🔄 Обновление кода из GitHub..."
git fetch --all
git reset --hard origin/main

echo "🛑 Остановка запущенных копий бота..."
pkill -f "python3 main.py" || true

echo "📦 Обновление зависимостей..."
source venv/bin/activate
pip install -r requirements.txt

echo "🚀 Запуск бота в фоновом режиме..."
# Используем nohup, чтобы бот не выключился после закрытия терминала
nohup python3 main.py > bot.log 2>&1 &

echo "✅ Бот запущен! Логи можно смотреть командой: tail -f bot.log"
