@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_relay_autostart.ps1"
if errorlevel 1 (
  echo 请先完成账号绑定，再启动中转。
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0relay_supervisor.py"
echo 已启动后台中转，并启用当前 Windows 用户登录后的自启。
echo 服务器还需启用此设备的专属隧道；启动命令成功不等于网络已经连通。
pause
