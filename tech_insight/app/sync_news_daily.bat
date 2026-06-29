@echo off
chcp 65001 >nul
REM Tech Insight: daily Supabase news sync + embedding
REM Registered in Windows Task Scheduler to run once a day.
REM SUPABASE_URL/KEY are auto-loaded from app\.env

cd /d C:\VS_Test\tech_insight\app

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set LLM_PROVIDER=ollama
set OLLAMA_MODEL=exaone3.5
set EMBED_PROVIDER=ollama
set EMBED_MODEL=bge-m3

echo ===== %DATE% %TIME% : news sync start ===== >> sync_news.log
C:\VS_Test\venv\Scripts\python.exe manage.py collect_news_supabase >> sync_news.log 2>&1
C:\VS_Test\venv\Scripts\python.exe manage.py embed_documents >> sync_news.log 2>&1
echo ===== %DATE% %TIME% : done ===== >> sync_news.log
