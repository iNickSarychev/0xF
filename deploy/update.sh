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

echo "🚀 Перезапуск службы бота..."
sudo systemctl restart 0xf-bot

echo "✅ Код обновлен и служба 0xf-bot перезагружена!"
echo "Логи теперь смотрим так: journalctl -u 0xf-bot -f"
