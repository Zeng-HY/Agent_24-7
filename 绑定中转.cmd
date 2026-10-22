@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行安装.cmd。
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0relay_desktop.py"
