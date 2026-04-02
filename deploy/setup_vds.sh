#!/bin/bash
# =============================================================
# 0xFUTURE Bot — VDS Setup Script (Ubuntu 22.04 / 24.04)
# =============================================================
set -e

echo "========================================"
echo "  0xFUTURE Bot — VDS Setup"
echo "========================================"

# --- 1. Обновление системы ---
echo "[1/6] Updating system..."
apt update && apt upgrade -y

# --- 2. Установка зависимостей ---
echo "[2/6] Installing Python, Git, and essentials..."
apt install -y python3 python3-pip python3-venv git curl

# --- 3. Установка Tailscale ---
echo "[3/6] Installing Tailscale VPN..."
curl -fsSL https://tailscale.com/install.sh | sh
echo ""
echo "============================================"
echo "  ВАЖНО: Запусти Tailscale авторизацию:"
echo "  sudo tailscale up"
echo "  Откроется ссылка — залогинься в браузере."
echo "============================================"
echo ""

# --- 4. Клонирование проекта ---
echo "[4/6] Cloning project from GitHub..."
if [ -d "/opt/0xf" ]; then
    echo "Directory /opt/0xf already exists, pulling latest..."
    cd /opt/0xf && git pull
else
    git clone https://github.com/NickSarychev/0xF.git /opt/0xf
fi

# --- 5. Создание виртуального окружения ---
echo "[5/6] Setting up Python virtual environment..."
cd /opt/0xf
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# --- 6. Создание .env файла ---
echo "[6/6] Creating .env template..."
if [ ! -f "/opt/0xf/.env" ]; then
    cat > /opt/0xf/.env << 'ENVFILE'
BOT_TOKEN=your_bot_token_here
OLLAMA_MODEL=gemma4
OLLAMA_BASE_URL=http://TAILSCALE_IP_OF_YOUR_PC:11434
CHANNEL_ID=@AxFUTURE
ADMIN_CHAT_ID=341481395
ENVFILE
    echo ""
    echo "============================================"
    echo "  ВАЖНО: Отредактируй /opt/0xf/.env"
    echo "  nano /opt/0xf/.env"
    echo "  - BOT_TOKEN: вставь токен бота"
    echo "  - OLLAMA_BASE_URL: замени на Tailscale IP"
    echo "============================================"
else
    echo ".env already exists, skipping."
fi

echo ""
echo "========================================"
echo "  Setup complete!"
echo "  Next steps:"
echo "  1. sudo tailscale up"
echo "  2. nano /opt/0xf/.env"
echo "  3. sudo cp /opt/0xf/deploy/bot.service /etc/systemd/system/"
echo "  4. sudo systemctl daemon-reload"
echo "  5. sudo systemctl enable --now 0xf-bot"
echo "========================================"
