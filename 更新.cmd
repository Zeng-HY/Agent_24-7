@echo off
chcp 65001 >nul
rem Takes the newest version from GitHub (git pull), then 安装.cmd: new packages, and the service restarted.
cd /d "%~dp0"
echo 正在从 GitHub 取最新版……
git pull --ff-only
if errorlevel 1 (
  echo 没取到最新版，看上面的错误。
  pause
  exit /b 1
)
call "%~dp0安装.cmd" %*
