@echo off
chcp 65001 >nul
title Git Smart Manager (GSM)
cd /d "%~dp0"

start "" cmd /c "timeout /t 2 >nul & start http://localhost:8765"

python app.py
if %ERRORLEVEL% NEQ 0 (
    "C:\Users\phamn\scoop\apps\python313\current\python.exe" app.py
)
pause
