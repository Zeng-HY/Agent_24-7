@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行安装.cmd。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 relay_setup.py
if errorlevel 1 pause
