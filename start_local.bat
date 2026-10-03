@echo off
cd /d "%~dp0"
set AGENT_HOST=127.0.0.1
set AGENT_PORT=8781
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
powershell -NoProfile -Command "try { $s=Invoke-RestMethod 'http://127.0.0.1:8781/api/status' -TimeoutSec 2; if ($s.app_version -eq 'shopping-chat-2026-10-03') { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
    start "" "http://127.0.0.1:8781"
    exit /b 0
)
echo Starting AI Shopping Agent at http://127.0.0.1:8781
echo Please wait 10-20 seconds for the product knowledge base to load.
start "" "http://127.0.0.1:8781"
python agent_server.py
pause
