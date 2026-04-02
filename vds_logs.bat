@echo off
title 0xFUTURE VDS - Live Logs
echo ========================================
echo   0xFUTURE Bot - VDS Log Viewer
echo ========================================
echo.
echo Connecting to VDS...
echo (Password will be asked)
echo.
ssh root@104.253.74.112 -t "journalctl -u 0xf-bot -n 50 --no-pager -f"
pause
