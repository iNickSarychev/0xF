@echo off
setlocal
title 0xFUTURE AI Bot Loader

echo ==========================================
echo    0xFUTURE AI NEWS EDITOR BOT
echo ==========================================

:: 1. Очистка старых процессов
echo 🧹 Cleaning up old processes...
taskkill /f /im python.exe /t 2>nul
:: Мы не убиваем Ollama сразу, так как она может быть общей, 
:: но если она зависла, иногда это нужно. Однако, оставим это пользователю.

:: 2. Проверка виртуального окружения
if exist venv (
    echo 📦 Using virtual environment...
    call venv\Scripts\activate
) else (
    echo ⚠️ Virtual environment not found. Using system python.
)

:: 3. Обновление/Создание модели в Ollama
echo 🧠 Updating Ollama model (0xf-writer)...
ollama create 0xf-writer -f Modelfile

:: 4. Запуск бота
echo 🚀 Starting the Bot...
echo.
python main.py

if errorlevel 1 (
    echo.
    echo ❌ Bot crashed. Checking for errors...
    pause
)

endlocal
