"""Which computer this is, what it has, and the other computers the phone can switch to (10-13).

The service can only drive the Codex and Claude of the computer it runs on, so every computer runs its own copy and
the phone opens each one at its own Tailscale address. The page names the computer it is on and lists the others.
They are found through Tailscale: of the devices signed in to this computer's own account (not ones another account
shares in), every Windows one that is online is asked GET https://<its name>/api/hello, and on 8443 when 443 does not
answer (setup_machine.py puts the page there when 443 carries something else). Tailscale tells that computer which
account asks; it answers its own account without the token, with only {"app": "agent_remote", "name": ...}.
Computers seen once are remembered, so one that is switched off still shows, as not reachable.

The same account is what the service lets in without the token (remote.py, 10-20); Owner reads it from Tailscale.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

APP = "agent_remote"
FRESH_SECONDS = 60   # after this long the next request starts a new look at the other computers
PROBE_SECONDS = 5    # how long each computer gets to answer /api/hello (through a Tailscale relay 10-13: 0.34 s a round trip)
FALLBACK_HTTPS_PORT = 8443  # where the page goes when 443 of the Tailscale address carries something else
OWNER_SECONDS = 300         # how long the account read from Tailscale is kept
OWNER_RETRY_SECONDS = 15    # how soon it is read again while not known (Tailscale still starting)

HOME = Path.home()
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local")
APPDATA = Path(os.environ.get("APPDATA") or HOME / "AppData" / "Roaming")


def tailscale_exe() -> str:
    installed = Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "Tailscale" / "tailscale.exe"
    return str(installed) if installed.is_file() else (shutil.which("tailscale") or "")


def tailscale_status(timeout: float = 5) -> dict:
    """`tailscale status --json`; {} when Tailscale is not installed or does not answer."""
    exe = tailscale_exe()
    if not exe:
        return {}
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, encoding="utf-8",
                             timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        data = json.loads(out or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    return data if isinstance(data, dict) else {}


def dns_name(node) -> str:
    return str((node or {}).get("DNSName") or "").rstrip(".").lower() if isinstance(node, dict) else ""


def own_url(status: dict, port: int = 443) -> str:
    """This computer's address on Tailscale, the one the phone opens (with the port when the page is not on 443)."""
    name = dns_name((status or {}).get("Self"))
    return "" if not name else f"https://{name}/" if port == 443 else f"https://{name}:{port}/"


def owner_login(status: dict) -> str:
    """The Tailscale account this computer is signed in to (User[Self.UserID].LoginName); '' when not known."""
    me = (status or {}).get("Self") or {}
    user = ((status or {}).get("User") or {}).get(str(me.get("UserID")))
    return str(user.get("LoginName") or "") if isinstance(user, dict) else ""


class Owner:
    """This computer's Tailscale account, which remote.py lets in through tailscale serve without the token. Read from
    `tailscale status` when first needed and kept five minutes; while it is not known (Tailscale still starting at
    sign-in or after an update), read again after 15 seconds."""

    def __init__(self, status=tailscale_status, clock=time.monotonic):
        self.status = status
        self.clock = clock
        self.lock = threading.Lock()
        self.value = ""
        self.at: float | None = None

    def login(self) -> str:
        with self.lock:
            if self.at is None or self.clock() - self.at >= (OWNER_SECONDS if self.value else OWNER_RETRY_SECONDS):
                self.value, self.at = owner_login(self.status()), self.clock()
            return self.value


def serve_config(timeout: float = 15) -> dict | None:
    """`tailscale serve status --json`: what this computer puts on its Tailscale address ({} for nothing);
    None when Tailscale is not installed or does not answer."""
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        done = subprocess.run([exe, "serve", "status", "--json"], capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if done.returncode != 0:
            return None
        data = json.loads(done.stdout or "null")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return data if isinstance(data, dict) else {}  # "null": nothing is served


def _on_port(entries, port: int) -> list:
    """The values of a serve config section keyed "<name>:<port>" (Web, AllowFunnel) for that port."""
    return [v for k, v in (entries or {}).items() if str(k).rpartition(":")[2] == str(port)]


def _is_page(proxy, port: int) -> bool:
    """Whether a serve handler's Proxy ("http://127.0.0.1:8765", "localhost:8765", "8765") is this service."""
    text = str(proxy or "")
    if text.isdigit():
        return int(text) == port
    try:
        parts = urlsplit(text if "://" in text else "http://" + text)
        return parts.hostname in ("127.0.0.1", "localhost", "::1") and parts.port == port
    except ValueError:
        return False


def page_port(config: dict, port: int) -> int:
    """The https port of the Tailscale address whose / goes to this service (127.0.0.1:<port>), 443 first; 0 for none."""
    config = config or {}
    found = [int(p) for p, tcp in (config.get("TCP") or {}).items()
             if str(p).isdigit() and isinstance(tcp, dict) and tcp.get("HTTPS")
             and any(_is_page((((web or {}).get("Handlers") or {}).get("/") or {}).get("Proxy"), port)
                     for web in _on_port(config.get("Web"), int(p)))]
    return 443 if 443 in found else min(found, default=0)


def port_taken(config: dict, port: int) -> bool:
    """Whether that port of the Tailscale address already carries something (a web handler or a TCP forward)."""
    return str(port) in ((config or {}).get("TCP") or {}) or bool(_on_port((config or {}).get("Web"), port))


def funnel_on(config: dict, port: int) -> bool:
    """Whether that port is open to the whole internet (Funnel), not only to the devices on the tailnet."""
    return any(_on_port((config or {}).get("AllowFunnel"), port))


def installed_apps() -> list[str]:
    """The desktop apps on this computer: Codex (Store package or not), Claude (Store package or installer) and
    DeepSeek Harness (its desktop app's own folder: ~/.dsh alone may be only the command-line dsh, which the phone
    cannot drive). A few folder checks; remote.py looks again each time the page opens."""
    packages = LOCALAPPDATA / "Packages"

    def package(prefix: str) -> bool:
        return packages.is_dir() and any(packages.glob(prefix + "_*"))

    apps = []
    if package("OpenAI.Codex") or (LOCALAPPDATA / "OpenAI" / "Codex").is_dir():
        apps.append("codex")
    if package("Claude") or (LOCALAPPDATA / "AnthropicClaude").is_dir() or (APPDATA / "Claude").is_dir():
        apps.append("claude")
    if (APPDATA / "@deepseek-ai" / "dsh-desktop").is_dir():
        apps.append("deepseek")
    return apps


def hello(url: str, timeout: float = PROBE_SECONDS) -> dict | None:
    """What the service at url says about itself, when it is one of ours."""
    try:
        request = Request(url.rstrip("/") + "/api/hello", headers={"User-Agent": APP})
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            data = json.load(response)
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("app") == APP else None


class Computers:
    """This computer and the others, for the switch on the page (GET /api/computers). The page gets the last look at
    once; a look older than a minute starts a new one in the background. Only a request before any look waits."""

    def __init__(self, name: str, memory: Path, status=tailscale_status, probe=hello, clock=time.monotonic, spawn=None):
        self.name = name
        self.memory = memory  # computers seen before: {url: name}
        self.status = status
        self.probe = probe
        self.clock = clock
        self.spawn = spawn or (lambda work: threading.Thread(target=work, name="computers", daemon=True).start())
        self.lock = threading.Lock()       # cached, at, looking
        self.look_lock = threading.Lock()  # one look at a time
        self.cached: dict | None = None
        self.at = 0.0
        self.looking = False

    def _find(self, name: str):
        """(url, answer) of our service on that computer: on 443, or on 8443 where 443 carries something else."""
        for url in (f"https://{name}/", f"https://{name}:{FALLBACK_HTTPS_PORT}/"):
            info = self.probe(url)
            if info:
                return url, info
        return None

    def _known(self) -> dict[str, str]:
        try:
            data = json.loads(self.memory.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _remember(self, known: dict[str, str]) -> None:
        try:
            self.memory.parent.mkdir(parents=True, exist_ok=True)
            self.memory.write_text(json.dumps(known, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def listing(self) -> dict:
        with self.lock:
            cached = self.cached
            renew = cached is not None and self.clock() - self.at >= FRESH_SECONDS and not self.looking
            if renew:
                self.looking = True
        if cached is None:
            return self.look()
        if renew:
            self.spawn(self._look_again)
        return cached

    def _look_again(self) -> None:
        try:
            self.look()
        finally:
            with self.lock:
                self.looking = False

    def look(self) -> dict:
        with self.look_lock:
            status = self.status()
            me = own_url(status)
            mine = (status.get("Self") or {}).get("UserID")  # devices another account shares in are not asked
            names = [dns_name(node) for node in (status.get("Peer") or {}).values()
                     if isinstance(node, dict) and node.get("Online") and dns_name(node)
                     and mine is not None and node.get("UserID") == mine
                     and str(node.get("OS") or "").lower() == "windows"]
            with ThreadPoolExecutor(max_workers=8) as pool:
                answers = [answer for answer in pool.map(self._find, names) if answer]
            found = {url: str(info.get("name") or url) for url, info in answers}
            known = self._known()
            if any(known.get(url) != name for url, name in found.items()):
                known.update(found)
                self._remember(known)
            others = [{"name": name, "url": url, "reachable": url in found} for url, name in known.items() if url != me]
            others.sort(key=lambda c: (not c["reachable"], c["name"]))
            result = {"self": {"name": self.name, "url": me}, "others": others}
            with self.lock:
                self.cached, self.at = result, self.clock()
            return result
