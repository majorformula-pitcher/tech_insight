@echo off
chcp 65001 >nul
cd /d "%~dp0app"

REM ===== env vars =====
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set LLM_PROVIDER=ollama
set OLLAMA_MODEL=exaone3.5
set EMBED_PROVIDER=ollama
set EMBED_MODEL=bge-m3
set DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,jwook-bang004.tail9f20b6.ts.net

set PYEXE=%~dp0..\venv\Scripts\python.exe

echo ========================================
echo   Tech Insight server
echo ----------------------------------------
echo   Local : http://127.0.0.1:8000/chat
echo   Public: https://jwook-bang004.tail9f20b6.ts.net:8443/chat
echo   admin / dashboard also available
echo   Stop  : press Ctrl+C in this window
echo ========================================
echo.

REM ===== 1) kill any existing server on port 8000 (prevent duplicates) =====
echo  Cleaning old server on port 8000...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
  taskkill /F /PID %%P >nul 2>&1
)

REM ===== 2) start Ollama in background (ignored if already running) =====
start "" /min ollama serve

REM ===== 3) open browser after 3 seconds =====
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/chat"

REM ===== 4) run Django server (this window is the server console) =====
"%PYEXE%" manage.py runserver 127.0.0.1:8000

echo.
echo Server stopped.
pause
