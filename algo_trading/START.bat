@echo off
title Algo Trading Bot
color 0A
cd /d "%~dp0"

echo.
echo  =============================================
echo   Zerodha Algo Trading Bot - Starting...
echo  =============================================
echo.

:: Port 5000 clear karo pehle agar purana server chal raha ho
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr "LISTENING" ^| findstr ":5000"') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: Flask & Certifi check
python -c "import flask" 2>nul || pip install flask --prefer-binary -q
python -c "import certifi" 2>nul || pip install certifi --prefer-binary -q

echo  Starting backend server...
echo.

:: 3 second baad Chrome/browser automatically open karo
start "" powershell -WindowStyle Hidden -NoProfile -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:5000'"

echo  =============================================
echo   Bot running at: http://localhost:5000
echo   Band karne ke liye: STOP.bat chalaayein
echo  =============================================
echo.

:: Foreground me python chalayein (logs dikhenge)
python web_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Server error aaya!
    pause
)
