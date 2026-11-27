@echo off
setlocal
cd /d "%~dp0"
echo Stopping web backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_backend.ps1"
echo.
echo Stopping AI backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_ai_backend.ps1"
pause
endlocal
