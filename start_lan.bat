@echo off
cd /d "%~dp0"
set AGENT_HOST=0.0.0.0
set AGENT_PORT=8781
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
echo Starting AI Shopping Agent for LAN sharing.
echo Watch this window for the LAN test link, then send that link to another device on the same network.
python agent_server.py
pause
