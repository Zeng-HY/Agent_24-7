@echo off
chcp 65001 >nul
rem Sets this computer up for the phone (setup_machine.py): Python environment, name, Tailscale, start at login.
rem Run it again after an update (git pull): it installs what changed and restarts the service.
cd /d "%~dp0"
echo 正在把这台电脑设置成手机能控制的电脑……
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo 没找到 Python 3.11 或更新的版本。
  echo 先装 Python 3.12：https://www.python.org/downloads/windows/ ，安装第一页勾上 Add python.exe to PATH，装好后再双击一次 安装.cmd。
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo 没建成 Python 环境（.venv），看上面的错误。
  pause
  exit /b 1
)
echo 安装需要的 Python 包……
rem pip in UTF-8 mode (-X utf8): otherwise it reads requirements.txt in the system code page, GBK on a Chinese Windows.
".venv\Scripts\python.exe" -X utf8 -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 ".venv\Scripts\python.exe" -X utf8 -m pip install --disable-pip-version-check -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
if errorlevel 1 (
  echo Python 包没装上，看上面的错误。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" setup_machine.py %*
echo.
pause
