@echo off
chcp 65001 >nul
echo ========================================
echo    AI News Bot - Запуск
echo ========================================
echo.
echo Останавливаю старые процессы...
taskkill /F /IM python.exe >nul 2>&1
timeout /t 3 /nobreak >nul
echo Запускаю бота...
echo.
cd /d %~dp0
python main.py
pause
