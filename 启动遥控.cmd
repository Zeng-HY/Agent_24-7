@echo off
rem Starts the phone remote service in a console, for debugging; uses this folder's own Python environment (.venv, see requirements.txt).
chcp 65001 >nul
"%~dp0.venv\Scripts\python.exe" "%~dp0remote.py" %*
echo.
pause
