@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ===== HTTP MCP 서버 (tech-insight-local 용, :9000) =====
REM 주의: 이 서버는 로컬 REST API(:8000)를 호출하므로,
REM       먼저 ..\start.bat 로 로컬 Django 서버(:8000)를 띄워야 한다.
REM 토큰은 git에 올리지 않으려고 ..\app\.env 의 API_TOKENS(첫 토큰)에서 읽는다.

set "MCP_TRANSPORT=http"
set "MCP_HOST=127.0.0.1"
set "MCP_PORT=9000"
set "TECHINSIGHT_API=http://127.0.0.1:8000/api/v1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM ---- .env(gitignore됨)에서 API_TOKENS 첫 토큰을 TECHINSIGHT_TOKEN 으로 ----
set "TECHINSIGHT_TOKEN="
for /f "usebackq tokens=1* delims==" %%A in ("%~dp0..\app\.env") do (
  if /i "%%A"=="API_TOKENS" (
    for /f "tokens=1 delims=," %%C in ("%%B") do set "TECHINSIGHT_TOKEN=%%C"
  )
)
if "%TECHINSIGHT_TOKEN%"=="" (
  echo [경고] ..\app\.env 에서 API_TOKENS 를 읽지 못했습니다. .env 파일을 확인하세요.
  pause
  exit /b 1
)

echo ========================================
echo   HTTP MCP server  (tech-insight-local)
echo   Endpoint: http://127.0.0.1:9000/mcp
echo   (먼저 ..\start.bat 로 :8000 서버가 떠 있어야 함)
echo   Stop: Ctrl+C
echo ========================================
echo.

"%~dp0..\..\venv\Scripts\python.exe" techinsight_mcp.py

echo.
echo HTTP MCP server stopped.
pause
