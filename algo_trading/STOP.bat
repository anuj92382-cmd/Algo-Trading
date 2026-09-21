@echo off
echo Stopping server on port 5000...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr "LISTENING" ^| findstr ":5000"') do (
    echo Killing PID %%a
    taskkill /f /pid %%a >nul 2>&1
)
echo Done.
timeout /t 2 /nobreak >nul
