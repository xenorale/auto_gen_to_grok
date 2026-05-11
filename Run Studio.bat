@echo off
cd /d "%~dp0"
echo Launching Auto Grok Studio...
.venv\Scripts\python.exe gui.py
if %errorlevel% neq 0 pause
