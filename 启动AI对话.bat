@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_ai_backend.ps1"
if errorlevel 2 (
    echo.
    echo Model qwen2:7b-instruct is missing.
    echo Double-click the model pull script in this folder first.
    pause
    exit /b 2
)
if errorlevel 1 (
    echo.
    echo Ollama failed to start. Check logs\ollama.err.log
    pause
    exit /b 1
)
echo.
echo Starting AI chat. Type quit or exit to leave.
python nl2sql.py
echo.
pause
endlocal
