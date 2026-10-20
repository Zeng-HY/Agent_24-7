"""Phone remote for Codex and Claude on this PC.

Runs a small web service on this PC. The phone opens one page that lists the Codex and Claude
conversations, shows them, and passes on what you type or say: to Codex through its own channel,
to Claude by filling its message box on the desktop. The page reads the conversations' own files.

Start:   启动遥控.cmd   (or: python remote.py); at login 后台启动遥控.cmd starts it without a window
Expose:  tailscale serve --bg --https=443 http://127.0.0.1:8765
Open on the phone:  https://<this computer's Tailscale name>/   (手机链接.cmd shows it as a QR code)
On another computer: 安装.cmd (setup_machine.py). Each computer runs its own copy; the page switches between them.

Who gets in (10-20): through tailscale serve, the devices of this computer's own Tailscale account and of the
accounts in "allowed_logins" (Tailscale names the account in the request). Without that name (a program on this
computer at 127.0.0.1, Funnel, a tagged device, or bind other than 127.0.0.1) the token: ?t=<token> or the lbr cookie.
The token lives in remote_config.json next to this file, with "name" (this computer, as the phone shows it),
"voice": false on a computer without the microphone, and optionally "apps": ["codex"] to override what is found.
"bark" is the phone's notification address, pasted on the page (notify.py); "ntfy": true when the ntfy app on an
Android phone gets them from this service (ntfy_feed.py), turned on on the page. "phone_files": the folder files sent
up from the phone go into (pc_files.py; 下载\\手机传来的文件 when not set).
"""

from __future__ import annotations

import argparse
import collections
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from email.header import decode_header, make_header
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "remote_config.json"
PAGE_FILE = HERE / "remote.html"
LOG_DIR = HERE / "logs"

try:
    import chats  # Codex and Claude conversations: lists from their files, sends through their links
    CHATS_ERROR = ""
except Exception as exc:  # pragma: no cover
    chats = None
    CHATS_ERROR = str(exc).splitlines()[0][:200]

import codex_control
import deepseek_control
import activity
import chat_history
import chat_projects  # the sidebar: conversations by app and project, as the desktop apps group them
import live_events
import claude_control
import composer_references
import pc_files  # files on this computer attached by their path, and files sent up from the phone (10-20)
import new_conversations
import voice  # the microphone button: recordings from the phone turned into text with VoiceAnywhere's key
import voice_local  # the same button, recognised on this PC while the user talks (SenseVoice + Qwen3-ASR)
import voice_terms  # the voice dictionary: words to listen for and how to spell them
import machines  # this computer's name and apps, and the other computers the page can switch to
import notify  # a notification on the phone (Bark, ntfy) when a conversation is done
import ntfy_feed  # the ntfy app on an Android phone subscribes to this service for them
import re

VERSION = "0.21.0"  # ＋ attaches any file on this computer, or one from the phone; the message carries its path

# Static files are cached for a day, so each script's URL carries the service's version and an update is
# fetched at once. remote.html holds no version of its own (it used to, once per script, and drifted);
# the page is served without a cache, so stamp_page fills the version in as it goes out (10-19).
SCRIPT_SRC = re.compile(rb'(<script src="(/[A-Za-z0-9_.\-]+\.js))(?:\?[^"]*)?"')


def stamp_page(page: bytes) -> bytes:
    return SCRIPT_SRC.sub(lambda m: m.group(1) + b"?v=" + VERSION.encode("ascii") + b'"', page)

DEFAULT_CONFIG = {
    "port": 8765,
    "bind": "127.0.0.1",
    "token": "",
    # Tailscale accounts let in besides this computer's own, e.g. ["someone@example.com"] (Handler._authorized)
    "allowed_logins": [],
    "codex_auto_dismiss_answered_questions": False,
    "codex_dismiss_verified_version": "",
    # files a conversation names may be opened on the phone when they lie in one of these folders
    # (or in the conversation's own working folder); more go in remote_config.json
    "roots": [
        str(Path.home() / "Downloads"),
    ],
}
# Settings of the browser and desktop-window pages, removed 10-12; dropped from remote_config.json on start.
RETIRED_KEYS = ("browser", "profile", "userscripts", "window", "download_dir", "inbox", "urls", "dialog_wait_seconds",
                "chooser_wait_seconds", "question_wait_seconds", "page_pins", "win_presets")
STATIC_FILES = {  # served without the token: home-screen icons and the web app manifest
    '/deepseek-ui.js': ('deepseek-ui.js','application/javascript; charset=utf-8'),
    "/navigation-ui.js": ("navigation-ui.js", "application/javascript; charset=utf-8"),
    "/claude-ui.js": ("claude-ui.js", "application/javascript; charset=utf-8"),
    "/references-ui.js": ("references-ui.js", "application/javascript; charset=utf-8"),
    "/files-ui.js": ("files-ui.js", "application/javascript; charset=utf-8"),
    "/codex-ui.js": ("codex-ui.js", "application/javascript; charset=utf-8"),
    "/new-chat-ui.js": ("new-chat-ui.js", "application/javascript; charset=utf-8"),
    "/workspace-ui.js": ("workspace-ui.js", "application/javascript; charset=utf-8"),
    "/activity-ui.js": ("activity-ui.js", "application/javascript; charset=utf-8"),
    "/sidebar-ui.js": ("sidebar-ui.js", "application/javascript; charset=utf-8"),
    "/reading-ui.js": ("reading-ui.js", "application/javascript; charset=utf-8"),
    "/voice-ui.js": ("voice-ui.js", "application/javascript; charset=utf-8"),
    "/notify-ui.js": ("notify-ui.js", "application/javascript; charset=utf-8"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/apple-touch-icon-precomposed.png": ("apple-touch-icon.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    changed = not CONFIG_FILE.exists()
    for key in RETIRED_KEYS:
        changed = cfg.pop(key, None) is not None or changed
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(9)
        changed = True
    cfg["roots"] = [str(Path(r)) for r in cfg["roots"] if Path(r).is_dir()]
    if not cfg["roots"]:
        cfg["roots"] = [str(Path.home())]
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def allowed_logins(cfg: dict) -> list[str]:
    """"allowed_logins" in remote_config.json: the Tailscale accounts let in besides this computer's own."""
    value = cfg.get("allowed_logins") or []
    if isinstance(value, str):
        value = [value]
    return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def loopback(host: str) -> bool:
    """Whether the service listens on this computer only (bind 127.0.0.1, the default)."""
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def header_login(value: str) -> str:
    """The account in a Tailscale-User-Login header. Tailscale writes one that is not plain ASCII as an RFC 2047 word
    (=?utf-8?q?…?=), as it writes the display name in Tailscale-User-Name (seen 10-20)."""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


class Log:
    """The service's log, one file a day in logs/ (YYYYMMDD.log): failed sends, voice problems, tracebacks."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._file = None
        self._day = ""

    def __call__(self, text: str = "") -> None:
        self.write(str(text))

    def write(self, text: str) -> None:
        now = datetime.now()
        try:
            with self.lock:
                if self._file is None or self._day != f"{now:%Y%m%d}":
                    if self._file is not None:
                        self._file.close()
                    LOG_DIR.mkdir(parents=True, exist_ok=True)
                    self._day = f"{now:%Y%m%d}"
                    self._file = (LOG_DIR / f"{self._day}.log").open("a", encoding="utf-8", newline="\n")
                self._file.write(f"{now:%H:%M:%S} {text}\n")
                self._file.flush()
        except Exception:
            pass


# ---------------------------------------------------------------- http


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentRemote/" + VERSION
    protocol_version = "HTTP/1.1"  # keep-alive: the phone reuses one connection instead of handshaking each time

    @property
    def log(self) -> Log:
        return self.server.log  # type: ignore[attr-defined]

    @property
    def cfg(self) -> dict:
        return self.server.cfg  # type: ignore[attr-defined]

    @property
    def desktop(self):
        return self.server.desktop  # type: ignore[attr-defined]

    def _chat_call(self, fn, *args, timeout: float = 60) -> None:
        """Run a conversation action (reads directly, window work on the desktop worker) and answer with JSON."""
        if chats is None:
            self._json({"error": "对话功能不可用：" + CHATS_ERROR}, 500)
            return
        try:
            result = fn(*args) if timeout <= 0 else self.desktop.run(fn, *args, timeout=timeout)
        except chats.ChatError as exc:
            extra = {"draft": exc.draft} if getattr(exc, "draft", None) else {}  # what sits in Claude's box (DesktopDraft)
            self._json({"ok": False, "error": str(exc), "text": str(exc),
                        "not_submitted": bool(getattr(exc,'not_submitted',False)),"code":getattr(exc,'code',None), **extra}, 400)
            return
        except TimeoutError:
            self._json({"ok": False, "error": f"超过 {timeout:.0f} 秒没做完"}, 504)
            return
        except Exception as exc:
            self.log.write(traceback.format_exc())
            text = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"
            self._json({"ok": False, "error": text, "text": text}, 500)
            return
        self._json(result if isinstance(result, dict) else {"ok": True, "result": result})

    def log_message(self, fmt, *args):
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def _query(self) -> dict:
        return {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def _cookie_token(self) -> str:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "lbr":
                return v
        return ""

    def _token_given(self) -> bool:
        return secrets.compare_digest(self._query().get("t", ""), self.cfg["token"])

    def _visitor(self) -> str | None:
        """The Tailscale account asking, when the request came through tailscale serve from a person's device: serve
        writes Tailscale-User-Login itself and replaces one the client sent (checked 10-20). None without the header
        (a program on this computer, Funnel, a tagged device), and always when the service listens beyond this
        computer (bind other than 127.0.0.1): anyone on that network could write the header, so only the token counts."""
        if not loopback(str(self.cfg.get("bind") or "")):
            return None
        return header_login(self.headers.get("Tailscale-User-Login") or "") or None

    def _authorized(self) -> bool:
        login = self._visitor()
        if login is not None:  # the account decides; a token changes nothing for an account not let in
            allowed = [self.server.owner.login(), *allowed_logins(self.cfg)]  # type: ignore[attr-defined]
            return any(login.casefold() == name.casefold() for name in allowed if name)
        return self._token_given() or secrets.compare_digest(self._cookie_token(), self.cfg["token"])

    def _refusal(self) -> str:
        """What a refused page says: which account is not let in and how to let it in, or how to get the token."""
        name, login = self.server.machine["name"], self._visitor()  # type: ignore[attr-defined]
        if login is not None:
            return (f"这台电脑（{name}）只让它自己登录的 Tailscale 账号用，你现在用的账号是 {login}。\n"
                    f"要放行这个账号：在这台电脑的 remote_config.json 里把 \"{login}\" 加进 \"allowed_logins\"，再重启遥控服务。")
        return (f"这台电脑（{name}）的遥控页给登录同一个 Tailscale 账号的设备用：手机先打开 Tailscale，"
                "再扫这台电脑上「手机链接.cmd」显示的二维码。\n"
                "不经 Tailscale 打开（比如在这台电脑上用 127.0.0.1）要在地址后面加 ?t=口令，口令在 remote_config.json 里。")

    def _refuse(self) -> None:
        login = self._visitor()
        self._json({"error": f"这台电脑没放行 Tailscale 账号 {login}" if login is not None else "口令不对"}, 403)

    def _recheck_apps(self) -> None:
        """Which desktop apps this computer has, looked at again each time the page opens (a few folder checks), so an
        app installed after the service started shows on the next load. A new dict, not a change to the shared one."""
        apps = machine_facts(self.cfg)["apps"]
        self.server.machine = {**self.server.machine, "apps": apps}  # type: ignore[attr-defined]
        deepseek = getattr(self.server, "deepseek", None)
        if deepseek is not None and "deepseek" in apps and deepseek_control.HOME.is_dir():
            deepseek.events.start()  # its live events, if DeepSeek came after the service; started once, later calls do nothing

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200, extra: dict | None = None) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 256 << 10:
            self.close_connection = True
            return {"_bad": "请求过大"}
        if n <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            return data if isinstance(data, dict) else {"_bad": "请求体不是 JSON 对象"}
        except Exception:
            return {"_bad": "请求体不是合法的 UTF-8 JSON"}

    # -- GET

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in STATIC_FILES:  # icons and the manifest carry no secrets; the phone fetches them without the cookie
            name, ctype = STATIC_FILES[path]
            file = HERE / "static" / name
            if not file.is_file():
                self._json({"error": "没有这个文件"}, 404)
                return
            self._send(200, file.read_bytes(), ctype, {"Cache-Control": "public, max-age=86400"})
            return
        if path in ("/", "/input-diagnostics"):
            if not self._authorized():
                self._send(403, self._refusal().encode("utf-8"), "text/plain; charset=utf-8")
                return
            extra = {}
            if self._token_given():  # the QR code's link; a device let in by its account is not handed the token
                extra["Set-Cookie"] = f"lbr={self.cfg['token']}; Path=/; SameSite=Lax; HttpOnly; Max-Age=31536000"
            page_file = HERE / "static" / "input-diagnostics.html" if path == "/input-diagnostics" else PAGE_FILE
            page = page_file.read_bytes()
            if page_file == PAGE_FILE:  # which computer this is and what it has, before any of the page's scripts run
                self._recheck_apps()
                page = stamp_page(page)  # each script's URL carries this version; the file itself holds none
                # version: the page compares it with what /api/status says later, and reloads itself after an update
                facts = json.dumps({**self.server.machine, "version": VERSION}, ensure_ascii=False).replace("<", "\\u003c")
                page = page.replace(b"<!--machine-->", f"<script>window.MACHINE={facts};</script>".encode("utf-8"), 1)
            self._send(200, page, "text/html; charset=utf-8", extra)
            return
        if not self._authorized():
            self._refuse()
            return
        if path == "/api/hello":  # the other computers ask it to find this one (machines.py), through tailscale serve
            # with their account on the request: let in as the page is (10-20; it used to answer anyone)
            self._json({"app": machines.APP, "name": self.server.machine["name"], "version": VERSION})
            return
        # the ntfy app on an Android phone (ntfy_feed.py): /agent-remote/json and the like. Matched on the request as
        # sent, since a server address typed with a slash at its end gives //agent-remote/json
        feed = ntfy_feed.PATH.fullmatch("/" + self.path.split("?", 1)[0].lstrip("/"))
        if feed:
            ntfy_feed.serve(self, self.server.notifier.feed, feed[1], feed[2], self._query())
            return
        if path.startswith("/api/voice") and not self.server.machine["voice"]:
            self._json({"error": "这台电脑没开语音"}, 404)
            return
        if path == "/api/computers":  # this computer and the others on Tailscale, for the switch at the top of the page
            self._json(self.server.computers.listing())
            return
        if path == "/api/notify":  # 设置 → 手机通知: whether an address is set (never the address) and the last outcomes
            self._json(self.server.notifier.public())
            return
        if path == "/api/voice/status":
            self._json({"local": self.server.local_asr.status(), "cloud": self.server.voice.status()})
            return
        if path == "/api/voice/terms":  # the voice dictionary, to edit on the phone
            self._json({"text": voice_terms.read_text(), "count": len(voice_terms.words())})
            return
        if path == "/api/voice/https-link":  # the microphone needs the https address; the page is already trusted
            host = (self.headers.get("Host") or "").split(":")[0]  # a ts.net address: let in by the account, no token (10-20)
            self._json({"url": f"https://{host}/" if host.endswith(".ts.net") else ""})
            return
        if path.startswith('/api/deepseek/'):
            self._deepseek(path)
            return
        if path.startswith("/api/codex/"):
            self._codex_get(path)
            return
        if path == '/api/debug/claude-reads':  # did the phone read Claude's state, and when (it restores a minimised window)
            self._json({'reads': list(self.server.claude_reads)})
            return
        if path == '/api/claude/state':
            try:
                tid=self._query().get('id','')
                agent=self.headers.get('User-Agent') or ''
                self.server.claude_reads.append({'time':time.strftime('%H:%M:%S'),'id':tid[-6:],'fresh':self._query().get('fresh')=='1',
                                                 'from':'iPhone' if 'iPhone' in agent else 'Android' if 'Android' in agent else 'other'})
                self._json({**self.server.claude.state(tid,self._query().get('fresh')=='1'),'images':self.server.codex.message_images(tid)})
            except Exception as exc:self._json({'error':str(exc)},400)
            return
        if path=='/api/composer/references':
            q=self._query()
            try:self._json(self.server.references.search(q.get('app','codex'),q.get('id',''),q.get('kind','chat'),q.get('query',''),int(q.get('offset','0'))))
            except (chats.ChatError,OSError,ValueError,TypeError) as exc:self._json({'error':str(exc)},400)
            return
        if path in ('/api/files/places','/api/files/list'):  # 电脑上的文件: where to start, and one folder (pc_files.py)
            q=self._query()
            try:
                if path.endswith('/places'):self._json(self.server.files.places(self._conversation_folder(q)))
                else:self._json(self.server.files.listing(q.get('path',''),q.get('sort','name'),q.get('query',''),int(q.get('offset','0') or 0)))
            except pc_files.FileError as exc:self._json({'error':str(exc)},exc.status)
            except (chats.ChatError,OSError,ValueError) as exc:self._json({'error':str(exc)},400)
            return
        if path in ('/api/chat/new/state','/api/chat/new/references'):
            try:
                q=self._query()
                self._json(self.server.new_chats.status(q.get('request_id','')) if path.endswith('/state') else self.server.new_chats.search(q))
            except (chats.ChatError,OSError,ValueError,TypeError) as exc:self._json({'error':str(exc)},400)
            return
        if path=='/api/chat/new/options':  # the models and effort steps the new-conversation sheet offers (10-14)
            try:self._json(self.server.new_chats.options(self._query().get('app','')))
            except chats.ChatError as exc:self._json({'error':str(exc)},400)
            return
        if path in ("/api/events", "/api/chat/search", "/api/chat/message", "/api/chat/files", "/api/file", "/api/file/text", "/api/file/meta"):
            self._reading_get(path)
            return
        if path.startswith("/api/chat") and chats is None:
            self._json({"error": "对话功能不可用：" + CHATS_ERROR}, 500)
            return
        if path == "/api/status":  # the page's connection check (every 2 s); autostart.py asks it too
            self._json({"ok": True, "ui_version": VERSION, "chat": {"available": chats is not None,
                                             "error": CHATS_ERROR or (self.desktop.auto_error if self.desktop else "")}})
        elif path == "/api/chats":
            q = self._query()
            limit = max(5, min(100, int(q.get("limit", "40") or 40)))
            try:
                result=self.history.conversations(q.get("app", "all"),limit,q.get("cursor", ""),q.get("query", ""))
                apps=self.server.machine["apps"]  # an app this computer lacks lists nothing, even with files left behind (10-20)
                result['items']=[v for v in self.server.tasks.apply_status(result['items']) if v.get('app') in apps]
                self._json(result)
            except (chat_history.HistoryError,ValueError,TypeError) as exc:self._json({"error":str(exc)},getattr(exc,"status",400))
        elif path == "/api/chats/children":  # past the first children a row carries (10-20)
            q = self._query()
            try:self._json(self.history.children(q.get("app", ""),q.get("id", ""),int(q.get("offset", "0") or 0),int(q.get("limit", "50") or 50)))
            except (chat_history.HistoryError,ValueError,TypeError) as exc:self._json({"error":str(exc)},getattr(exc,"status",400))
        elif path == "/api/chat":
            q = self._query()
            try:self._json(self.history.conversation(q.get("app", ""),q.get("id", ""),int(q.get("n", "60") or 60),q.get("before", ""),q.get("around", "")))
            except (chat_history.HistoryError,chats.ChatError,ValueError) as exc:self._json({"error":str(exc)},getattr(exc,"status",400))
        elif path == "/api/chat/projects":  # the sidebar's tree; with key=…: more conversations of that project
            q = self._query()
            try:
                # DeepSeek sessions in no workspace go under 其他对话, as in the desktop's Ungrouped (10-20)
                rows = self.history.catalog() + [dict(v, ungrouped=True) for v in self.history.ungrouped()]
                if q.get("key"):
                    self._json(chat_projects.page(rows, q.get("app", ""), q["key"],
                                                  int(q.get("offset", "0") or 0), int(q.get("limit", "30") or 30), self._row_status))
                else:  # more=[[app, key, n], …]: projects the phone had opened further with 显示更多
                    more = {(str(a), str(k)): int(n) for a, k, n in json.loads(q.get("more") or "[]")[:50]}
                    tree = chat_projects.tree(rows, self._row_status, more=more)
                    tree["apps"] = [a for a in tree["apps"] if a.get("app") in self.server.machine["apps"]]  # no Claude group without Claude
                    self._json(tree)
            except Exception as exc:  # a locked Codex database, an unreadable state file
                self._json({"error": str(exc)[:200]}, 400)
        elif path == "/api/chat/folders":
            items=self.server.new_chats.folders(self._query().get('app',''))
            self._json({'folders':[v['path'] for v in items],'items':items})
        elif path == "/api/chat/options":
            q = self._query()
            self._chat_call(self.desktop.claude_options, q.get("id", ""), q.get("open") == "1", timeout=40)
        else:
            self._json({"error": "没有这个地址"}, 404)

    # -- POST

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if not self._authorized():
            self.close_connection = True
            self._refuse()
            return
        if path.startswith("/api/voice") and not self.server.machine["voice"]:
            self.close_connection = True  # the recording in the body is not read
            self._json({"error": "这台电脑没开语音"}, 404)
            return
        if path == "/api/codex/upload":
            self._codex_upload()
            return
        if path == "/api/files/upload":  # a file from the phone, its bytes as the body (pc_files.Files.upload)
            self._files_upload()
            return
        if path == "/api/voice":
            self._voice()
            return
        if path.startswith("/api/voice/stream/"):
            self._voice_stream(path)
            return
        body = self._body()
        if body.get("_bad"):
            self._json({"error": body["_bad"]}, 400)
            return
        if path == "/api/voice/tidy":  # 整理 for text already recognised on this PC
            context = {k: str(body.get(k, ""))[:200] for k in ("app", "title", "folder")}
            context["existing"] = str(body.get("existing", ""))[-400:]
            try:
                self._json(self.server.voice.tidy_text(str(body.get("text", "")), context))
            except voice.VoiceError as exc:
                self._json({"error": str(exc)}, exc.status if 400 <= exc.status < 600 else 400)
            return
        if path in ("/api/notify", "/api/notify/ntfy", "/api/notify/test"):
            # Bark's address (empty: off), ntfy on or off, one to try (on one channel, or on all)
            try:
                notifier = self.server.notifier
                if path.endswith("/test"):
                    self._json(notifier.test(str(body.get("channel", ""))))
                elif path.endswith("/ntfy"):
                    self._json(notifier.set_ntfy(body.get("on") is True))
                else:
                    self._json(notifier.set_address(str(body.get("address", ""))))
            except notify.NotifyError as exc:
                self._json({"error": str(exc)}, 400)
            return
        if path == "/api/voice/terms":
            try:
                count = voice_terms.save_text(str(body.get("text", "")))
            except (ValueError, OSError) as exc:
                self._json({"error": f"词典没保存：{exc}"}, 400)
                return
            self._json({"ok": True, "count": count})
            return
        if path == "/api/debug/client":  # the page tells the PC which of its files failed to load (parts-missing)
            try:  # 10-12: the keyboard trace that also came here (viewport_trace.jsonl) was taken out, the jump fixed
                trace = LOG_DIR / "client_events.jsonl"
                if trace.exists() and trace.stat().st_size > 400 << 10:  # keep the newer half
                    data = trace.read_bytes()
                    trace.write_bytes(data[len(data) // 2:].split(b"\n", 1)[-1])
                with trace.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), **body}, ensure_ascii=False) + "\n")
            except OSError:
                pass
            self._json({"ok": True})
            return
        if path.startswith('/api/deepseek/'):
            self._deepseek(path,body)
            return
        if path in ('/api/files/image','/api/files/remove'):
            self._files_post(path,body)
            return
        if path.startswith("/api/codex/"):
            self._codex_post(path, body)
            return
        if path.startswith('/api/claude/'):
            try:
                if path=='/api/claude/menu':result=self.server.claude.menu(str(body.get('id','')),str(body.get('kind','')))
                elif path=='/api/claude/catalog':result=self.server.claude.catalog(str(body.get('id','')),bool(body.get('fresh')))
                elif path=='/api/claude/setting':result=self.server.claude.select_setting(str(body.get('id','')),str(body.get('kind','')),str(body.get('name','')),body.get('value'),body.get('expected_model'))
                elif path=='/api/claude/choose':result=self.server.claude.choose(str(body.get('id','')),str(body.get('token','')),body.get('value'))
                elif path=='/api/claude/close-menu':result=self.server.claude.close_menu(str(body.get('id','')))
                elif path=='/api/claude/next':result=self.server.claude.next_step(str(body.get('id','')),str(body.get('tool_id','')),int(body.get('index',-1)),str(body.get('label','')))
                elif path=='/api/claude/task':result=self.server.claude.task_step(str(body.get('id','')),str(body.get('title','')),str(body.get('button','')))
                elif path=='/api/claude/steer':
                    tid=str(body.get('id',''));text=str(body.get('text',''))
                    if body.get('references'):text,_=self.server.references.compose('claude',tid,text,body['references'])
                    result=self.server.claude.send_steer(tid,text,str(body.get('expected_turn','')),str(body.get('request_id','')))
                    result['check_text']=text
                else:raise chats.ChatError('没有这个操作')
                self._json(result)
            except Exception as exc:
                if not isinstance(exc,chats.ChatError):  # 10-14 a raw COM error reached the phone with nothing in the log
                    self.log.write(f'Claude 操作 {path} 出错：\n'+traceback.format_exc())
                self._json({'error':claude_control.plain_error(exc),'not_submitted':bool(getattr(exc,'not_submitted',False)),'code':getattr(exc,'code',None)},409)
            return
        if path.startswith("/api/chat") and chats is None:
            self._json({"error": "对话功能不可用：" + CHATS_ERROR}, 500)
            return
        # a new DeepSeek conversation goes through /api/chat/new like the others (10-20); the rest has its own channel
        if body.get('app')=='deepseek' and path in ('/api/chat/send','/api/chat/enter','/api/chat/check'):
            self._json({'error':'DeepSeek 请使用专用控制通道；草稿已保留','not_submitted':True},400)
            return
        if path == "/api/chat/send":
            self._chat_call(self._send_with_references,body,timeout=60)
        elif path == "/api/chat/check":
            self._chat_call(chats.Desktop.check, str(body.get("app", "")), str(body.get("id", "")),
                            int(body.get("offset") or 0), str(body.get("text", "")), timeout=0)
        elif path == "/api/chat/new_check":
            self._chat_call(chats.Desktop.new_check, int(body.get("started") or 0), str(body.get("text", "")), timeout=0)
        elif path == "/api/chat/enter":
            self._chat_call(self.desktop.press_enter, str(body.get("app", "")), str(body.get("id", "")), timeout=15)
        elif path == "/api/chat/open":
            if body.get('app')=='deepseek':
                try:
                    self.server.deepseek.find(body.get('id'))
                    os.startfile('dsh://open')
                    self._json({'ok':True,'text':'已打开 DeepSeek；请在电脑侧选择对应对话'})
                except (deepseek_control.DeepSeekError,OSError) as exc:self._json({'error':str(exc)},400)
                return
            self._chat_call(self.desktop.open, str(body.get("app", "")), str(body.get("id", "")), timeout=45)
        elif path == "/api/chat/new":
            try:self._json(self.server.new_chats.submit(body))
            except (chats.ChatError,OSError,ValueError,TypeError) as exc:self._json({'error':str(exc),'not_submitted':True},400)
        elif path == '/api/chat/new/draft':
            self._json(self.server.new_chats.create_draft())
        elif path == '/api/chat/new/prepare':
            self._json({'ok':True,'enabled':False})  # older pages may still request prewarming
        elif path == '/api/chat/new/timing':
            try:self._json(self.server.new_chats.client_timing(body))
            except (chats.ChatError,OSError,ValueError,TypeError,AttributeError) as exc:self._json({'error':str(exc)},400)
        elif path == '/api/chat/new/retry':
            try:self._json(self.server.new_chats.retry(body.get('request_id','')))
            except (chats.ChatError,OSError,ValueError,TypeError) as exc:self._json({'error':str(exc)},400)
        elif path == "/api/chat/press":
            option = body.get("option") if isinstance(body.get("option"), dict) else {}
            self._chat_call(self.desktop.claude_press, str(body.get("id", "")), option, str(body.get("text", "")),
                            bool(body.get("enter")), timeout=40)
        else:
            self._json({"error": "没有这个地址"}, 404)

    def _send_with_references(self,body):
        app,tid=str(body.get('app','')),str(body.get('id',''));text=str(body.get('text',''))
        if app=='codex':raise chats.InputNotSubmitted('页面版本已过期，请刷新后通过 Codex 控制通道发送；草稿已保留')
        images=[]
        if body.get('attachments'):
            ids=body['attachments']
            if app!='claude' or not isinstance(ids,list) or len(ids)>5 or any(not isinstance(v,str) for v in ids) or len(set(ids))!=len(ids):
                raise chats.InputNotSubmitted('图片请求无效，尚未发送')
            images=[self.server.codex.attachment(v,tid) for v in ids]
            if any(v.get('app','codex')!='claude' for v in images) or sum(v['original_size'] for v in images)>50<<20:
                raise chats.InputNotSubmitted('图片不属于此 Claude 会话或超过大小限制，尚未发送')
            if not text.strip():text='请查看这些图片。'
        if body.get('references'):
            if app=='codex':raise chats.ChatError('带引用的消息请等待当前轮结束，再通过 Codex 控制通道发送')
            text,_=self.server.references.compose(app,tid,text,body['references'])
        if images:
            previous=self.server.codex._begin(str(body.get('request_id','')),tid,body)
            if previous:return previous
            for image in images:
                image['used']=True;self.server.codex._write_meta(image)
        # replace_draft: the text the phone was shown in Claude's box (DesktopDraft) and agreed may go
        replace={'replace':body['replace_draft'][:2000]} if app=='claude' and isinstance(body.get('replace_draft'),str) else {}
        result=self.desktop.send(app,tid,text,images,**replace) if images else self.desktop.send(app,tid,text,**replace)
        for image in images:
            image['used']=True;self.server.codex._write_meta(image)
        if body.get('references') or images:result['check_text']=text
        if images:self.server.codex._finish(body['request_id'],result)
        return result

    def _row_status(self, item: dict) -> str:
        """running / idle / unknown for a row of the sidebar: from the end of its file, or what the desktop last told."""
        row = {"app": item["app"], "id": item["id"], "status": chats.summary(item)["status"]}
        return self.server.tasks.apply_status([row])[0]["status"]

    @property
    def history(self):
        if not hasattr(self.server,"history"):
            self.server.history=chat_history.History(self.cfg.get("roots",[]),self.cfg["token"])
        return self.server.history

    def _reading_get(self,path):
        q=self._query();app=q.get('app','codex');tid=q.get('id','')
        try:
            if path=='/api/events':
                with self.server.notifier.watching(app,tid):  # the phone has it open: its turns are not notified
                    live_events.stream(self,self.history,self.server.codex,getattr(self.server,'tasks',None),app,tid)
            elif path=='/api/chat/search':self._json(self.history.search(app,tid,q.get('query',''),q.get('cursor','')))
            elif path=='/api/chat/message':self._json(self.history.message(app,tid,q.get('message','')))
            elif path=='/api/chat/files':self._json(self.history.list_files(app,tid))
            else:
                meta=self.history.file(app,tid,q.get('file',''))
                if path=='/api/file/meta':self._json({'name':meta['path'].name,'size':meta['size'],'kind':meta['kind']})
                elif path=='/api/file/text':
                    if meta['kind']!='text':raise chat_history.HistoryError('这个文件不提供文本预览')
                    raw=meta['path'].read_bytes()
                    try:text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
                    except UnicodeError:raise chat_history.HistoryError('无法按 UTF-8 或 UTF-16 预览，请下载原文件') from None
                    self._json({'text':text,'name':meta['path'].name})
                else:self._serve_result_file(meta,q.get('download')=='1')
        except (chat_history.HistoryError,chats.ChatError,OSError,ValueError,TypeError) as exc:
            self._json({'error':str(exc)},getattr(exc,'status',400))

    def _serve_result_file(self,meta,download=False):
        size=meta['size'];start=0;end=max(0,size-1);status=200
        requested=self.headers.get('Range')
        if requested:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
            if not match or not any(match.groups()) or size==0:
                self._send(416,b'', 'text/plain',{'Content-Range':f'bytes */{size}'});return
            if match[1]:start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
            else:start=max(0,size-int(match[2]));end=size-1
            if start>end or start>=size:
                self._send(416,b'', 'text/plain',{'Content-Range':f'bytes */{size}'});return
            status=206
        length=end-start+1 if size else 0
        with meta['path'].open('rb') as f:
            self.send_response(status);self.send_header('Content-Type',meta['mime']);self.send_header('Content-Length',str(length));self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Disposition',('attachment' if download or meta['kind']=='download' else 'inline')+"; filename*=UTF-8''"+quote(meta['path'].name))
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers();f.seek(start)
            try:
                while length:
                    block=f.read(min(65536,length))
                    if not block:break
                    self.wfile.write(block);length-=len(block)
            except (OSError,ConnectionError):self.close_connection=True

    def _deepseek(self,path,body=None):
        bridge=self.server.deepseek
        try:
            q=self._query()
            if body is None:
                if path=='/api/deepseek/image':
                    raw,mime=bridge.image(q.get('id',''),q.get('attachment',''),q.get('thumb')=='1')
                    self._send(200,raw,mime)
                    return
                if path=='/api/deepseek/state':result=bridge.state(q.get('id',''))
                elif path=='/api/deepseek/models':result=bridge.models()
                elif path=='/api/deepseek/receipt':result=bridge.receipt(q.get('request_id',''))
                elif path=='/api/deepseek/permissions':result=bridge.permissions(q.get('id',''))
                else:raise deepseek_control.DeepSeekError('没有这个接口',404)
            elif path=='/api/deepseek/send':result=bridge.send(body)
            elif path=='/api/deepseek/permission':result=bridge.set_permission(body.get('id'),body.get('preset'),body.get('confirmed') is True)
            elif path=='/api/deepseek/queue':result=bridge.queue_action(body.get('id'),body.get('item_id'),body.get('action'))
            elif path=='/api/deepseek/stop':result=bridge.stop(body.get('id'),body.get('expected_turn'))
            elif path=='/api/deepseek/model':result=bridge.select_model(body.get('id'),body.get('settings',{}))
            elif path=='/api/deepseek/create':result=bridge.create(body)
            elif path=='/api/deepseek/answer':result=bridge.answer(body)
            elif path=='/api/deepseek/approval':result=bridge.events.answer(body.get('id'),body.get('event_id'),body.get('choice'),'approval/request')
            else:raise deepseek_control.DeepSeekError('没有这个接口',404)
            self._json(result)
        except (deepseek_control.DeepSeekError,codex_control.ControlError,chats.ChatError) as exc:self._json({'error':str(exc)},getattr(exc,'status',400))
        except (ValueError,TypeError,KeyError):self._json({'error':'DeepSeek 请求或接口格式不兼容'},400)

    def _codex_get(self, path):
        bridge = self.server.codex
        q = self._query()
        try:
            if path == "/api/codex/state":
                data=bridge.status(q.get("id", ""), fresh=q.get("fresh") == "1")
                if hasattr(self.server,"tasks"):self.server.tasks.observe(q.get("id", ""),data)
                self._json(data)
            elif path == "/api/codex/image":
                meta = bridge.attachment(q.get("id", ""))
                file = bridge.data_root / meta["id"] / ("thumb.png" if q.get("thumb") == "1" else "image.png")
                self._send(200, file.read_bytes(), "image/png", {"X-Content-Type-Options": "nosniff"})
            elif path == "/api/codex/attachments":
                items = []
                for ident in q.get("ids", "").split(",")[:5]:
                    try:
                        items.append(bridge.public_attachment(bridge.attachment(ident, q.get("id", ""))))
                    except codex_control.ControlError:
                        continue
                self._json({"items": items})
            elif path == "/api/codex/receipt":
                self._json(bridge.receipt(q.get("id", ""), q.get("request_id", "")))
            else:
                self._json({"error": "没有这个接口"}, 404)
        except (codex_control.ControlError, chats.ChatError, OSError) as exc:
            self._json({"error": str(exc)}, getattr(exc, "status", 400))

    def _voice_stream(self, path: str):
        """Recognition on this PC while the user talks: start, small pieces of 16 kHz audio, end."""
        asr, q = self.server.local_asr, self._query()
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if size > 10 * voice_local.RATE * 2:  # more than 10 seconds in one piece
                self.close_connection = True
                raise voice_local.LocalError("这一段录音太大了")
            raw = self.rfile.read(size) if size > 0 else b""
            sid = q.get("sid", "")
            if path == "/api/voice/stream/start":
                if q.get("tidy") == "1":  # connect to the tidy service while the user is still talking
                    threading.Thread(target=self.server.voice.warm, name="voice-warm", daemon=True).start()
                self._json({"sid": asr.start(), "rate": voice_local.RATE})
            elif path == "/api/voice/stream/chunk":
                self._json(asr.feed(sid, raw))
            elif path == "/api/voice/stream/end":
                self._json(asr.end(sid))
            elif path == "/api/voice/stream/cancel":
                asr.cancel(sid)
                self._json({"ok": True})
            elif path == "/api/voice/stream/cloud":  # the same recording, recognised by the cloud service instead
                context = {k: q.get(k, "")[:200] for k in ("app", "title", "folder")}
                context["existing"] = ""
                self._json(self.server.voice.process(asr.wav(sid), "audio/wav", q.get("tidy") == "1", context))
            else:
                self._json({"error": "没有这个接口"}, 404)
        except voice_local.LocalError as exc:
            self._json({"error": str(exc), "local": asr.status()}, 409)
        except voice.VoiceError as exc:
            self._json({"error": str(exc)}, exc.status if 400 <= exc.status < 600 else 400)
        except Exception as exc:
            self.log.write(traceback.format_exc())
            self._json({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, 500)

    def _voice(self):
        """A recording from the microphone button; answers with the text to put in the message box."""
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= voice.MAX_AUDIO_BYTES:
                self.close_connection = True
                raise voice.VoiceError("录音为空或太长", 413)
            audio = self.rfile.read(size)
            if len(audio) != size:
                raise voice.VoiceError("录音上传不完整")
            q = self._query()
            context = {k: q.get(k, "")[:200] for k in ("app", "title", "folder")}
            context["existing"] = unquote(self.headers.get("X-Existing-Text", ""))[-400:]
            self._json(self.server.voice.process(audio, self.headers.get("Content-Type") or "audio/wav",
                                                 q.get("tidy") == "1", context))
        except voice.VoiceError as exc:
            self._json({"error": str(exc)}, exc.status if 400 <= exc.status < 600 else 400)
        except Exception as exc:
            self.log.write(traceback.format_exc())
            self._json({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, 500)

    def _conversation_folder(self, q: dict) -> str:
        """Where the file sheet starts: the folder picked for a new conversation, or the open one's working folder."""
        if q.get("folder"):
            return q["folder"]
        try:
            return chats._strip_unc(str(chats.find(q.get("app", ""), q.get("id", "")).get("cwd") or ""))
        except Exception:  # a conversation the lists no longer have: the sheet starts at the other places
            return ""

    def _files_upload(self):
        """A file from the phone written to the inbox on this computer; it answers with the reference that attaches it."""
        q = self._query()
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= pc_files.MAX_UPLOAD:
                raise pc_files.FileError(f"单个文件最多 {pc_files.MAX_UPLOAD >> 20} MB", 413)
            self._json(self.server.files.upload(q.get("name", "文件"), self.rfile.read, size, q.get("app", ""),
                                                q.get("id", "") or q.get("draft", "")))
        except pc_files.FileError as exc:
            self.close_connection = True  # what is left of the body is not read
            self._json({"error": str(exc)}, exc.status)
        except (OSError, ValueError) as exc:
            self.close_connection = True
            self._json({"error": f"文件没存下来：{exc}"}, 400)

    def _files_post(self, path: str, body: dict):
        try:
            if path == "/api/files/remove":  # taken off the draft before it went: deleted unless a message carried it
                self._json(self.server.files.remove_upload(body.get("upload")))
                return
            # /api/files/image: a picture on this computer, read into the photo path so the model sees it at once
            name, raw = self.server.files.picture(body.get("ref") if isinstance(body.get("ref"), dict) else {})
            if body.get("draft"):
                self._json(self.server.new_chats.upload(str(body["draft"]), name, raw))
            else:
                self._json(self.server.codex.upload(str(body.get("id", "")), name, raw, str(body.get("app", "codex"))))
        except pc_files.FileError as exc:
            self._json({"error": str(exc)}, exc.status)
        except (codex_control.ControlError, chats.ChatError, OSError, ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, getattr(exc, "status", 400))

    def _codex_upload(self):
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= 20 << 20:
                self.close_connection = True
                raise codex_control.ControlError("单张图片不能超过 20 MB", 413)
            q = self._query()
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise codex_control.ControlError("图片上传不完整", 400)
            self._json(self.server.new_chats.upload(q['draft'],q.get('name','图片'),raw) if q.get('draft') else self.server.codex.upload(q.get("id", ""), q.get("name", "图片"), raw,q.get('app','codex')))
        except (codex_control.ControlError, chats.ChatError, OSError, ValueError) as exc:
            self._json({"error": str(exc)}, getattr(exc, "status", 400))

    def _codex_post(self, path, body):
        try:
            bridge = self.server.codex
            if path == "/api/codex/send":
                result = bridge.send(body)
            elif path == "/api/codex/stop":
                result = bridge.stop_turn(body)
            elif path == "/api/codex/answer":
                result = bridge.answer(body)
            elif path == "/api/codex/queue-action":
                result = bridge.queue_action(body)
            elif path == "/api/codex/remove-attachment":
                result = bridge.remove_attachment(str(body.get("id", "")), str(body.get("attachment", "")))
            else:
                raise codex_control.ControlError("没有这个接口", 404)
            self._json(result)
        except (codex_control.ControlError, chats.ChatError, OSError, ValueError, TypeError) as exc:
            not_submitted = bool(getattr(exc,'not_submitted',False))
            if isinstance(exc, codex_control.ControlError) and body.get('request_id'):
                try:not_submitted = bridge.receipt(str(body.get('id','')),str(body['request_id']))['state'] in ('unknown','rejected')
                except Exception:pass
            self._json({"error": str(exc),"not_submitted":not_submitted,
                        "code":getattr(exc,'code',None)}, getattr(exc, "status", 400))
        except Exception:
            self.log.write(traceback.format_exc())
            self._json({"error": "Codex 操作结果未确认，请检查对话；不会自动重试"}, 500)


# ---------------------------------------------------------------- main


def local_addresses() -> list[str]:
    found = []
    ts = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
    for exe in ("tailscale", str(ts)):
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                found.append(out.splitlines()[0])
                break
        except Exception:
            continue
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except Exception:
        pass
    return found


def machine_facts(cfg: dict) -> dict:
    """What the page is told about this computer (window.MACHINE): its name, its desktop apps, whether it has voice.
    The apps are the ones found here, or "apps" in remote_config.json; none found is an empty list and the page says
    so (it used to pretend Codex and Claude)."""
    apps = cfg.get("apps")
    if not (isinstance(apps, list) and apps):
        apps = machines.installed_apps()
    return {"name": str(cfg.get("name") or socket.gethostname()), "apps": [str(a) for a in apps],
            "voice": cfg.get("voice") is not False}


class Server(ThreadingHTTPServer):
    # Through Tailscale (https) every file of the page arrives on its own connection, all at once. Python's
    # default queue of 5 waiting connections turned the rest away, Tailscale answered those with 502, and that
    # script never ran: no Claude buttons, no microphone (10-11; a burst of 36 lost 5, with 128 none).
    request_queue_size = 128
    daemon_threads = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="手机遥控电脑上 Codex 和 Claude 对话的小服务。")
    parser.add_argument("--port", type=int, help="监听端口（默认看配置，初始 8765）")
    parser.add_argument("--bind", help="监听地址；默认只听本机 127.0.0.1，由 tailscale serve 对外")
    parser.add_argument("--verbose", action="store_true", help="打印每个请求")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    cfg = load_config()
    if args.port:
        cfg["port"] = args.port
    if args.bind:
        cfg["bind"] = args.bind
    log = Log()
    server = Server((cfg["bind"], cfg["port"]), Handler)
    server.log = log  # type: ignore[attr-defined]
    server.cfg = cfg  # type: ignore[attr-defined]
    input_lock = threading.Lock()  # one stream of keys and clicks into the desktop apps at a time
    server.desktop = chats.Desktop(log, input_lock) if chats else None  # type: ignore[attr-defined]
    server.codex = codex_control.Bridge()  # shares the existing desktop owner's IPC connection
    server.deepseek = deepseek_control.bridge()
    server.deepseek.uploads = server.codex
    if deepseek_control.HOME.is_dir():server.deepseek.events.start()
    import codex_question_dismiss
    server.codex.dismiss_manager = codex_question_dismiss.DismissManager(
        server.codex, enabled=cfg.get("codex_auto_dismiss_answered_questions", False),
        verified_version=cfg.get("codex_dismiss_verified_version", ""), log=log.write)
    server.claude = claude_control.Controller(server.desktop)
    server.claude_reads = collections.deque(maxlen=60)  # when the page last read Claude's state, and from what (10-12)
    server.tasks = activity.TaskCenter(server.codex)
    server.history = chat_history.History(cfg.get('roots',[]),cfg['token'])
    server.files = pc_files.Files(cfg['token'], inbox=cfg.get('phone_files') or None)  # type: ignore[attr-defined]
    server.references = composer_references.References(server.history, files=server.files)
    server.deepseek.references = server.references
    server.codex.references = server.references
    server.new_chats = new_conversations.NewConversations(server.history,server.references,server.codex,server.desktop)
    server.new_chats.claude = server.claude  # a new Claude conversation's model and effort are picked through its menus
    server.machine = machine_facts(cfg)  # type: ignore[attr-defined]
    server.owner = machines.Owner()  # type: ignore[attr-defined]  (this computer's Tailscale account, let in without the token)
    server.computers = machines.Computers(server.machine["name"], HERE / "attachments" / "computers.json")  # type: ignore[attr-defined]
    server.computers.spawn(server.computers.look)  # the first tap on the computer's name need not wait for it
    server.notifier = notify.Notifier(cfg, server.machine["name"], log, lambda: save_config(cfg))  # type: ignore[attr-defined]
    server.notifier.start()
    if server.machine["voice"]:
        server.voice = voice.Voice(cfg, log)  # type: ignore[attr-defined]
        server.local_asr = voice_local.LocalASR(cfg, log)  # type: ignore[attr-defined]  (loads in the background)
    else:  # "voice": false in remote_config.json: no models loaded, no microphone on the page
        server.voice = server.local_asr = None  # type: ignore[attr-defined]
    if chats is None:
        print(f"对话功能不可用：{CHATS_ERROR}", flush=True)
    server.verbose = args.verbose  # type: ignore[attr-defined]
    token = cfg["token"]
    print(f"遥控服务已启动，监听 {cfg['bind']}:{cfg['port']}", flush=True)
    print(f"本机打开：http://127.0.0.1:{cfg['port']}/?t={token}", flush=True)
    if loopback(cfg["bind"]):
        https_port = machines.page_port(machines.serve_config(timeout=5) or {}, cfg["port"]) or 443
        url = machines.own_url(machines.tailscale_status(), https_port)
        print("手机通过 Tailscale 访问（和这台电脑同一个 Tailscale 账号的设备不用口令；别的账号要写进 allowed_logins）：", flush=True)
        print(f"  {url}" if url else "  （没读到这台电脑的 Tailscale 名字：先装好 Tailscale 并登录）", flush=True)
    else:
        for ip in local_addresses():
            print(f"手机打开：http://{ip}:{cfg['port']}/?t={token}", flush=True)
    print("按 Ctrl+C 结束。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.notifier.close()
        server.tasks.close()
        server.codex.close()
        server.deepseek.events.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
