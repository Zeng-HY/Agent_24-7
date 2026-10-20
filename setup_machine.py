"""Set this computer up as one the phone can drive (10-13). 安装.cmd runs it once the Python environment is in place
(and again after an update: it restarts the service); 手机链接.cmd runs it with --link to show the phone link again.

1. remote_config.json: the name the phone shows for this computer (asked the first time), a token of its own, and
   "voice": false unless the voice models are here (%LOCALAPPDATA%\\AgentRemote\\models).
2. Tailscale, signed in to the same account as the phone: the page goes on this computer's https address
   (tailscale serve --bg --https=443 http://127.0.0.1:<port>). Something else on 443 stays as it is and the page goes
   on 8443; a port open to the whole internet (Funnel) stops the setup (10-20).
3. Starts after every Windows sign-in (install_autostart.ps1), and (re)starts now.
4. The phone link, as a QR code to scan with the phone's camera (a page opened in the browser). It carries no token
   (10-20): through Tailscale the phone is let in by its account (remote.py).
Nothing here needs an administrator.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autostart  # noqa: E402  (healthy: the service is up and it is ours)
import machines  # noqa: E402

CONFIG = HERE / "remote_config.json"
MODELS = machines.LOCALAPPDATA / "AgentRemote" / "models"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def say(text: str = "") -> None:
    print(text, flush=True)


def read_config() -> dict:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def configure(cfg: dict, name: str, has_models: bool) -> dict:
    """What this computer needs in remote_config.json; what is set already stays."""
    cfg = dict(cfg)
    cfg.setdefault("port", 8765)
    cfg.setdefault("bind", "127.0.0.1")
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(9)
    if name:
        cfg["name"] = name
    if "voice" not in cfg and not has_models:
        cfg["voice"] = False
    return cfg


def ask_name(cfg: dict, given: str) -> str:
    if given.strip():
        return given.strip()
    if cfg.get("name"):
        return ""  # named before: keep it
    host = socket.gethostname()
    answer = input(f"这台电脑在手机上叫什么名字？（例如 公司电脑；直接回车就用「{host}」）：").strip()
    return answer or host


def tailscale() -> tuple[str, dict, str]:
    """(tailscale.exe, its status, what is wrong or '')."""
    exe = machines.tailscale_exe()
    if not exe:
        return "", {}, ("没找到 Tailscale。先装 Tailscale（https://tailscale.com/download/windows），"
                        "登录手机上用的同一个账号，再运行一次。")
    status = machines.tailscale_status(timeout=15)
    state = status.get("BackendState") or "读不到状态"
    if state != "Running" or not machines.own_url(status):
        return exe, status, f"Tailscale 还没连上（{state}）。打开 Tailscale，登录手机上用的同一个账号，再运行一次。"
    return exe, status, ""


def serve(exe: str, https_port: int, port: int) -> bool:
    """Put the page on this computer's https address at that port. Tailscale's own words go to the console (it may ask
    for something once, such as turning on HTTPS for the account)."""
    try:
        return subprocess.run([exe, "serve", "--bg", f"--https={https_port}", f"http://127.0.0.1:{port}"],
                              timeout=300).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        say(str(exc))
        return False


def choose_port(config: dict, port: int) -> tuple[int, bool, str]:
    """Where on this computer's Tailscale address the page goes: (https port, whether it is there already, what stops
    it or ''). 443, unless something else is on it, which stays as it is: then 8443. A port open to the whole internet
    (Funnel) stops it: requests from there carry no Tailscale account, so only the token would keep anyone out."""
    placed = machines.page_port(config, port)
    https_port = placed or next((p for p in (443, machines.FALLBACK_HTTPS_PORT) if not machines.port_taken(config, p)), 0)
    if not https_port:
        return 0, False, (f"这台电脑的 Tailscale 地址上，443 和 {machines.FALLBACK_HTTPS_PORT} 端口都已经放着别的服务"
                          "（tailscale serve status 能看到），没动它们。腾出一个再运行一次。")
    if machines.funnel_on(config, https_port):
        return https_port, bool(placed), (f"{https_port} 端口开着 Funnel，放在上面的网页整个互联网都能连到；那些请求不带 "
                                          "Tailscale 账号，只有口令挡着，所以没往下装。"
                                          f"先关掉它（tailscale funnel --https={https_port} off），再运行一次。")
    return https_port, bool(placed), ""


def place(exe: str, status: dict, port: int) -> tuple[int, str]:
    """Put the page on this computer's Tailscale address without touching what is there already:
    (the https port it is on, what went wrong or '')."""
    config = machines.serve_config()
    if config is None:
        return 0, "读不到 Tailscale 现在放了什么（tailscale serve status --json），没敢改。确认 Tailscale 开着，再运行一次。"
    https_port, placed, problem = choose_port(config, port)
    if problem:
        return 0, problem
    if placed:
        say(f"   已经放在 {machines.own_url(status, https_port)}，没改。")
        return https_port, ""
    if https_port != 443:
        say(f"   443 端口上已经放着别的服务，没动它；网页放在 {machines.own_url(status, https_port)}")
    if not serve(exe, https_port, port):
        return 0, "没放上去，看上面 Tailscale 说了什么。"
    return https_port, ""


def install_autostart() -> str:
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "install_autostart.ps1")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return "" if done.returncode == 0 else (done.stdout + done.stderr).strip()


def listener(port: int) -> int:
    """The process listening on 127.0.0.1:port, or 0."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, errors="replace",
                             timeout=15, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1] == f"127.0.0.1:{port}" and parts[3] == "LISTENING" and parts[4].isdigit():
            return int(parts[4])
    return 0


def restart(port: int, token: str) -> bool:
    """Start the service, stopping our own old one first (after an update). Something else on the port stays."""
    if autostart.healthy(port, token):
        pid = listener(port)
        if pid:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30, creationflags=NO_WINDOW)
            for _ in range(20):
                if not autostart.occupied(port):
                    break
                time.sleep(.5)
    elif autostart.occupied(port):
        say(f"端口 {port} 被别的程序占着，没动它。")
        return False
    pythonw = HERE / ".venv" / "Scripts" / "pythonw.exe"
    subprocess.Popen([str(pythonw), str(HERE / "autostart.py")], cwd=str(HERE), close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    for _ in range(80):
        time.sleep(.5)
        if autostart.healthy(port, token):
            return True
    return False


def link_page(name: str, url: str, folder: Path | None = None) -> Path:
    """A page with the phone link as a QR code. The link carries no token (10-20): a phone on the same Tailscale
    account gets in by its account, so the QR code holds nothing secret."""
    import segno
    qr = segno.make(url, error="m")
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>用手机打开{html.escape(name)}</title>
<style>body{{font:16px/1.7 "Microsoft YaHei",sans-serif;max-width:720px;margin:32px auto;padding:0 16px;color:#1d2330}}
img{{width:320px;height:320px;display:block;margin:16px 0}}code{{word-break:break-all;color:#6b7280;font-size:13px}}</style>
<h1>用手机打开「{html.escape(name)}」</h1>
<img alt="手机链接的二维码" src="{qr.svg_data_uri(scale=10, border=2)}">
<ol><li>手机上先打开 Tailscale（和这台电脑登录同一个账号）。</li>
<li>用 iPhone 相机对准上面的二维码，点弹出的链接，会在 Safari 里打开。</li>
<li>想放到主屏幕：点分享按钮 →「添加到主屏幕」，关掉「作为网页 App 打开」。</li>
<li>以后在任意一台电脑的页面上，点标题下面的电脑名字，就能切到另一台。</li></ol>
<p>链接里没有口令：只有登录同一个 Tailscale 账号的设备能打开；别的账号要写进这台电脑 remote_config.json 的
"allowed_logins"。链接：<code>{html.escape(url)}</code></p></html>"""
    path = (folder or Path(tempfile.gettempdir())) / "agent_remote_phone_link.html"
    path.write_text(page, encoding="utf-8")
    return path


def show_link(cfg: dict, status: dict, https_port: int = 443) -> None:
    url = machines.own_url(status, https_port)
    page = link_page(str(cfg.get("name") or socket.gethostname()), url)
    try:
        os.startfile(page)  # the default browser
    except OSError:
        pass
    say("手机链接（浏览器里已打开它的二维码，用手机相机扫）：")
    say("  " + url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把这台电脑设置成手机能控制的电脑。")
    parser.add_argument("--name", default="", help="手机上显示的这台电脑的名字")
    parser.add_argument("--link", action="store_true", help="只显示手机链接（二维码）")
    args = parser.parse_args(argv)
    cfg = read_config()
    exe, status, problem = tailscale()
    if args.link:
        if not cfg.get("token"):
            say("这台电脑还没装好：先双击 安装.cmd。")
            return 1
        if problem:
            say(problem)
            return 1
        show_link(cfg, status, machines.page_port(machines.serve_config() or {}, int(cfg.get("port") or 8765)) or 443)
        return 0

    has_models = MODELS.is_dir() and any(MODELS.iterdir())
    cfg = configure(cfg, ask_name(cfg, args.name), has_models)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    voice = cfg.get("voice") is not False
    say(f"1/4 这台电脑叫「{cfg['name']}」，" + ("开语音。" if voice else "不开语音（没有语音模型）。"))
    if voice and subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r",
                                 str(HERE / "requirements-voice.txt")]).returncode != 0:
        say("语音要用的包没装上，看上面的错误。")
        return 1
    if problem:
        say(problem)
        return 1
    say("2/4 把网页放到这台电脑的 Tailscale 地址上……")
    https_port, trouble = place(exe, status, int(cfg["port"]))
    if trouble:
        say(trouble)
        return 1
    say("3/4 设成登录 Windows 后自动启动……")
    error = install_autostart()
    if error:
        say("没设上开机自启（不影响现在用）：" + re.sub(r"\s+", " ", error)[:300])
    say("4/4 启动服务……")
    if not restart(int(cfg["port"]), cfg["token"]):
        say("服务没起来，看 logs\\startup-errors.log。")
        return 1
    show_link(cfg, status, https_port)
    say("装好了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
