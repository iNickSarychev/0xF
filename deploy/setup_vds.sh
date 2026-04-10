#!/bin/bash

# Скрипт настройки VDS для Бота 0xFUTURE и Media-X (Go)

echo "🚀 Начинаем настройку сервера..."

# 1. Обновление системы
sudo apt-get update && sudo apt-get upgrade -y

# 2. Установка Python и зависимостей
sudo apt-get install -y python3-pip python3-venv git curl ffmpeg

# 3. Установка Docker (если не установлен)
if ! command -v docker &> /dev/null; then
    echo "🐳 Устанавливаем Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    echo "Docker установлен."
fi

# 4. Настройка проекта
cd ~/PRO || { echo "❌ Директория ~/PRO не найдена!"; exit 1; }
git pull

# 5. Сборка и запуск Media-X (Go)
echo "🐹 Сборка Media-X сервера..."
cd media-x
sudo docker stop media-x || true
sudo docker rm media-x || true
sudo docker build -t 0xf-media-x .
sudo docker run -d --name media-x --restart always -p 8080:8080 0xf-media-x
cd ..

# 6. Настройка Python окружения
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

echo "✅ Настройка завершена!"
echo "⚠️  Не забудьте обновить .env файл, прописав Tailscale IP вашего ПК в OLLAMA_BASE_URL."
echo "Запустите бота командой: source venv/bin/activate && python3 main.py"
