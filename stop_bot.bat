@echo off
chcp 65001 >nul
echo ========================================
echo    AI News Bot - Остановка
echo ========================================
echo.
taskkill /F /IM python.exe >nul 2>&1
echo Бот остановлен.
echo.
pause
