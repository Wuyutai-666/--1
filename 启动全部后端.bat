@echo off
setlocal
cd /d "%~dp0"
echo Starting FanDian web backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_backend.ps1"
echo.
echo Starting Ollama AI backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_ai_backend.ps1"
set AI_CODE=%errorlevel%
echo.
if %AI_CODE% equ 2 (
    echo AI model is missing. Web backend is still available.
    echo Double-click the model pull script first if you need AI chat.
) else if %AI_CODE% neq 0 (
    echo AI backend failed to start. Check logs\ollama.err.log
    echo Web backend is still available.
) else (
    echo Web and AI backends are running.
)
start "" "http://127.0.0.1:18080/"
echo URL: http://127.0.0.1:18080/
pause
endlocal
