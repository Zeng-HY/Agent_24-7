@echo off
chcp 65001 >nul
rem Shows this computer's phone link again, as a QR code (setup_machine.py --link).
cd /d "%~dp0"
".venv\Scripts\python.exe" setup_machine.py --link
echo.
pause
