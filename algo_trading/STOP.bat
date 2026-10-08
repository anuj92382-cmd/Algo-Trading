@echo off
title Stopping Algo Trading Bot...
echo.
echo  =============================================
echo   Stopping Algo Trading Bot...
echo  =============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"

echo.
echo  =============================================
echo   Algo Trading Bot STOPPED!
echo  =============================================
ping 127.0.0.1 -n 3 >nul
exit
