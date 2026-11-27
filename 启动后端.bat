@echo off
setlocal
cd /d "%~dp0"
echo Starting FanDian backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_backend.ps1"
if errorlevel 1 (
    echo.
    echo Backend failed to start. Check logs\backend.err.log
    pause
    exit /b 1
)
start "" "http://127.0.0.1:18080/"
echo.
echo Backend is running in the background.
echo URL: http://127.0.0.1:18080/
echo To stop it, double-click the stop script in this folder.
pause
endlocal
