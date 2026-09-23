@echo off
title Algo Trading Bot
color 0A
cd /d "%~dp0"

echo.
echo  =============================================
echo   Zerodha Algo Trading Bot - Starting...
echo  =============================================
echo.

:: Port 5000 clear karo pehle
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr "LISTENING" ^| findstr ":5000"') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: Flask install check
python -c "import flask" 2>nul || pip install flask --prefer-binary -q
python -c "import certifi" 2>nul || pip install certifi --prefer-binary -q

echo  Starting backend...
echo.

:: Background mein server start karo
start "AlgoBot" /b python web_app.py

:: Wait for server
echo  Waiting for server to start...
timeout /t 5 /nobreak > nul

:: Chrome mein kholo
echo  Opening Chrome...
set URL=http://localhost:5000

:: Chrome paths check karo
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --new-window --start-maximized "%URL%"
    goto :done
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --new-window --start-maximized "%URL%"
    goto :done
)
:: Fallback - default browser
start "" "%URL%"

:done
echo.
echo  =============================================
echo   Bot running at: http://localhost:5000
echo   Is window band mat karo!
echo   Band karne ke liye: STOP.bat chalao
echo  =============================================
echo.

:: Server chal raha hai - window ko open rakhein
echo Server is running... Press Ctrl+C or run STOP.bat to stop.
pause > nul
