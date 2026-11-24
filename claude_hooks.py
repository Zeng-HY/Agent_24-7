"""Claude Code HTTP hooks: questions, permissions, live state, and stop (10-27; extended 11-24).

Claude Code posts hook events to http://127.0.0.1:<port>/api/claude/hook/<key> (configured in
~/.claude/settings.json).
- PermissionRequest: held open until the phone answers (AskUserQuestion or tool permission), timeout 3600 s.
- UserPromptSubmit / PreToolUse / PostToolUse / PostToolUseFailure / Stop / Notification:
  fast-path events (timeout 10 s, target <5 ms in-process) that track live running/step state,
  record session_id -> claude.exe PID from the TCP connection table, and stop the turn on request.
- Never returns 'allow' from PreToolUse or any fast event; approvals stay strictly in PermissionRequest.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import chats

PATH = "/api/claude/hook/"  # + the hook key (remote_config.json "claude_hook_key"); remote.Handler serves it
HOOK_TIMEOUT = 3600         # seconds Claude Code waits on PermissionRequest
FAST_HOOK_TIMEOUT = 10      # seconds Claude Code waits on fast status/stop/queue hooks
WAIT_SECONDS = HOOK_TIMEOUT - 60  # the service lets go first, so Claude Code never cuts a request it still holds
NOT_HELD = {"ExitPlanMode"}  # a plan's approval wants its own input with "allow"; not tried, left to the desktop
SHOWN_AFTER = 3.0           # seconds the desktop's card may still be drawn after an answer went back
DENIED = ("The user said no to this from their phone (Teleply). Do not try it another way; stop and wait for the "
          "user's next message.")
NAV = {"back": ("Show previous question", "上一题"), "skip": ("Skip", "跳过"),
       "next": ("Next", "下一题"), "submit": ("Submit", "提交")}

# All 7 HTTP hook entries Teleply manages in Claude's user settings: (event, matcher_or_None, timeout)
MANAGED_HOOKS: tuple[tuple[str, str | None, int], ...] = (
    ("PermissionRequest", None, HOOK_TIMEOUT),
    ("UserPromptSubmit", None, FAST_HOOK_TIMEOUT),
    ("PreToolUse", "*", FAST_HOOK_TIMEOUT),
    ("PostToolUse", "*", FAST_HOOK_TIMEOUT),
    ("PostToolUseFailure", "*", FAST_HOOK_TIMEOUT),
    ("Stop", None, FAST_HOOK_TIMEOUT),
    ("Notification", None, FAST_HOOK_TIMEOUT),
)
FAST_EVENTS = frozenset({
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "Notification",
})

STOP_REASON = "用户在手机上停止了这一轮（遥应）"
STOP_DENY_REASON = "用户在手机上按了停止（遥应）。不要再调用任何工具。"
QUEUE_PREFIX = "用户在手机上发来下一条消息（遥应）："
STEER_PREFIX = "用户刚在手机上补充（遥应）："
MAX_BLOCKS_PER_TURN = 8  # Stop blocks Teleply sends in one user turn (Claude Code's own cap is also 8)

# A phone steer goes back only with the main conversation's own tool call (11-24): a subagent's call would take it
# and the main conversation would never see it. How much of the conversation's record is read to recognize that call.
STEER_RECORD_TAIL = 512 * 1024
SUBAGENT_KEYS = ("agent_id", "agent_type")  # what Claude Code adds to a hook event raised inside a subagent

COMMAND_TOOLS = frozenset({"Bash", "PowerShell"})
COMMAND_SHELLS = frozenset({"bash.exe", "sh.exe", "pwsh.exe", "powershell.exe", "cmd.exe"})
SESSION_BACKOFF_START = 2.0   # seconds before an unknown session is looked for again: 2, 4, 8 … 60
SESSION_BACKOFF_MAX = 60.0
PID_RECHECK_SECONDS = 60.0    # how long a verified conversation claude.exe is trusted before its path is checked again

# Images that cannot go through the desktop window (queued / steered) are stored for Claude's Read tool.
IMAGE_MAX_SIDE = 1600
IMAGE_FALLBACK_SIDE = 1280
IMAGE_MAX_BYTES = 400 * 1024
IMAGE_RETENTION_SECONDS = 7 * 86400
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _data_path(name: str) -> Path:
    from app_paths import DATA
    return Path(DATA) / name


def settings_file() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def _step_for_tool(tool_name: str) -> str:
    from agents.claude import CLAUDE_STEPS
    return CLAUDE_STEPS.get((tool_name or "").rsplit(".", 1)[-1]) or ""


def is_claude_code_exe(exe_path: str) -> bool:
    """Verify an executable path belongs to Claude desktop's embedded Claude Code binary."""
    norm = str(exe_path or "").replace("/", "\\").lower()
    return "\\claude\\claude-code\\" in norm and norm.endswith("\\claude.exe")


def _short_user(owner: str) -> str:
    text = str(owner or "").strip()
    if "\\" in text:
        text = text.rsplit("\\", 1)[-1]
    return text.casefold()


def lookup_tcp_owner_pid(client_port: int, server_port: int) -> int:
    """Find the PID that owns the client end of a local IPv4 TCP connection to server_port via GetExtendedTcpTable."""
    if client_port <= 0 or server_port <= 0:
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        iphlp = ctypes.windll.iphlpapi
        af_inet, tcp_table_owner_pid_all = 2, 5
        size = wintypes.DWORD(0)
        iphlp.GetExtendedTcpTable(None, ctypes.byref(size), False, af_inet, tcp_table_owner_pid_all, 0)
        if size.value == 0:
            return 0
        for _ in range(2):
            alloc = size.value + 4096
            size = wintypes.DWORD(alloc)
            buf = ctypes.create_string_buffer(alloc)
            rc = iphlp.GetExtendedTcpTable(buf, ctypes.byref(size), False, af_inet, tcp_table_owner_pid_all, 0)
            if rc == 0:
                break
            if rc != 122:  # ERROR_INSUFFICIENT_BUFFER
                return 0
        else:
            return 0
        count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
        rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(wintypes.DWORD * 6))
        for i in range(count):
            _state, _laddr, lport, _raddr, rport, pid = rows[i]
            local_port = ((lport & 0xFF) << 8) | ((lport >> 8) & 0xFF)
            remote_port = ((rport & 0xFF) << 8) | ((rport >> 8) & 0xFF)
            if local_port == client_port and remote_port == server_port:
                return int(pid)
    except Exception:
        return 0
    return 0


def lookup_process_exe(pid: int) -> str:
    """Return full executable path for [pid] via QueryFullProcessImageNameW, or '' on error."""
    if pid <= 0:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(n))
            return buf.value if ok else ""
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return ""


def _parse_creation_time(value: Any) -> float | None:
    """Parse WMI DMTF datetime ('20261124113005.123456+480'), datetime, or numeric Unix timestamp."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        text = value.strip()
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\.(\d{6})([+-])(\d{3})", text)
        if m:
            year, mon, day, hour, minute, sec, usec, sign, offset_min = m.groups()
            minutes = int(offset_min) * (1 if sign == "+" else -1)
            tz = timezone(timedelta(minutes=minutes))
            return datetime(int(year), int(mon), int(day), int(hour), int(minute), int(sec), int(usec), tzinfo=tz).timestamp()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _default_list_processes() -> list[dict[str, Any]]:
    """List local processes (PID, PPID, Name, ExecutablePath, CreationDate, Owner) via WMI.

    Never reads CommandLine: command termination relies strictly on process ancestry and start time.
    """
    out: list[dict[str, Any]] = []
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            wmi = win32com.client.GetObject("winmgmts:")
            rows = wmi.ExecQuery("SELECT ProcessId, ParentProcessId, Name, ExecutablePath, CreationDate FROM Win32_Process")
            raw_list = []
            for proc in rows:
                pid = int(getattr(proc, "ProcessId", 0) or 0)
                ppid = int(getattr(proc, "ParentProcessId", 0) or 0)
                name = str(getattr(proc, "Name", "") or "")
                exe = str(getattr(proc, "ExecutablePath", "") or "")
                created = _parse_creation_time(getattr(proc, "CreationDate", None))
                raw_list.append((proc, pid, ppid, name, exe, created))
            # Only query GetOwner for shells and descendants of claude.exe to keep it fast.
            claude_pids = {pid for _, pid, _, name, exe, _ in raw_list if name.lower() == "claude.exe" and is_claude_code_exe(exe)}
            descendant_pids = set()
            if claude_pids:
                frontier = set(claude_pids)
                while frontier:
                    next_frontier = set()
                    for _, pid, ppid, _, _, _ in raw_list:
                        if ppid in frontier and pid not in descendant_pids and pid not in claude_pids:
                            descendant_pids.add(pid)
                            next_frontier.add(pid)
                    frontier = next_frontier
            for proc, pid, ppid, name, exe, created in raw_list:
                owner = ""
                if pid in descendant_pids or name.lower() in COMMAND_SHELLS:
                    try:
                        res = proc.ExecMethod_("GetOwner")
                        user = getattr(res, "User", "") or ""
                        domain = getattr(res, "Domain", "") or ""
                        owner = f"{domain}\\{user}" if domain and user else str(user)
                    except Exception:
                        owner = ""
                out.append({
                    "pid": pid,
                    "ppid": ppid,
                    "name": name,
                    "executable_path": exe,
                    "created_at": created,
                    "owner": owner,
                })
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return []
    return out


def _default_kill_process(pid: int) -> bool:
    """Terminate one specific PID via Win32 TerminateProcess (never spawns a shell)."""
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if not handle:
            return False
        try:
            return bool(ctypes.windll.kernel32.TerminateProcess(handle, 1))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def kill_session_command(
    session_pid: int,
    since_ts: float,
    *,
    list_processes: Callable[[], list[dict[str, Any]]] | None = None,
    kill_process: Callable[[int], Any] | None = None,
    current_user: str | None = None,
    log: Callable[[str], None] | None = None,
) -> list[int]:
    """Terminate ONLY the newest current-user command shell directly under this conversation's claude.exe
    started at or after [since_ts - 1s], along with its current-user descendants.

    Strictly forbidden:
    - Never matches processes by command-line text (design 3.3).
    - Never touches claude.exe itself or any other conversation's processes.
    - Never touches processes belonging to other users or with unknown owner.
    """
    if not session_pid or session_pid <= 0 or not since_ts or since_ts <= 0:
        return []
    want_user = _short_user(current_user or os.environ.get("USERNAME") or getpass.getuser())
    if not want_user:
        return []

    procs = (list_processes or _default_list_processes)()
    if not procs:
        return []

    by_pid: dict[int, dict[str, Any]] = {}
    for p in procs:
        if isinstance(p, dict) and p.get("pid"):
            by_pid[int(p["pid"])] = p

    session = by_pid.get(int(session_pid))
    if not session:
        return []
    if str(session.get("name") or "").lower() != "claude.exe":
        return []
    if not is_claude_code_exe(str(session.get("executable_path") or "")):
        return []

    threshold = float(since_ts) - 1.0
    shells: list[tuple[float, int, dict[str, Any]]] = []
    for p in procs:
        if not isinstance(p, dict):
            continue
        pid = int(p.get("pid") or 0)
        ppid = int(p.get("ppid") or 0)
        name = str(p.get("name") or "").lower()
        if not pid or pid == int(session_pid) or ppid != int(session_pid):
            continue
        if name not in COMMAND_SHELLS:
            continue
        owner = _short_user(str(p.get("owner") or ""))
        if not owner or owner != want_user:
            continue
        created = _parse_creation_time(p.get("created_at"))
        if created is None or created < threshold:
            continue
        shells.append((created, pid, p))

    if not shells:
        return []
    shells.sort(key=lambda item: (item[0], item[1]))
    top_pid = shells[-1][1]
    top_name = str(shells[-1][2].get("name") or "")

    # Walk descendants of the chosen shell; never include claude.exe or other users' processes.
    tree_order: list[int] = [top_pid]
    tree_set: set[int] = {top_pid}
    grew = True
    while grew:
        grew = False
        for p in procs:
            if not isinstance(p, dict):
                continue
            pid = int(p.get("pid") or 0)
            ppid = int(p.get("ppid") or 0)
            if not pid or pid in tree_set or pid == int(session_pid):
                continue
            if ppid not in tree_set:
                continue
            if str(p.get("name") or "").lower() == "claude.exe":
                continue
            owner = _short_user(str(p.get("owner") or ""))
            if not owner or owner != want_user:
                continue
            tree_order.append(pid)
            tree_set.add(pid)
            grew = True

    killer = kill_process or _default_kill_process
    killed: list[int] = []
    # Kill deepest children first, then the shell itself.
    for pid in reversed(tree_order):
        if pid == int(session_pid):
            continue
        try:
            if killer(pid) is not False:
                killed.append(pid)
        except Exception:
            continue
    if killed and callable(log):
        log(f"手机停止 Claude：已结束命令进程 {top_name}#{top_pid} 及子进程（共 {len(killed)} 个）")
    return killed


class HookQueues:
    """Teleply's own per-conversation queue and steer slot: one small JSON file each, so a restart keeps them.

    A phone message sent while Claude runs goes into `queue`; one that should interrupt the current step goes into
    `steer`. The hook events hand them to Claude (design 3.5). `recent` only remembers request ids for a while, so a
    phone retrying a send does not enqueue the same message twice."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self.lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else _data_path("claude-queues")

    def _file(self, tid: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(tid or "conversation"))[:120] or "conversation"
        return self.root / f"{safe}.json"

    @staticmethod
    def _items(value) -> list[dict]:
        return [v for v in value if isinstance(v, dict) and v.get("id") and isinstance(v.get("text"), str)] \
            if isinstance(value, list) else []

    def _load(self, tid: str) -> dict:
        try:
            data = json.loads(self._file(tid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return {"queue": self._items(data.get("queue")), "steer": self._items(data.get("steer")),
                "recent": self._items(data.get("recent"))}

    def _save(self, tid: str, data: dict) -> None:
        path = self._file(tid)
        if not any(data.get(key) for key in ("queue", "steer", "recent")):
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)

    @staticmethod
    def _request_id(value: str) -> str:
        text = str(value or "")
        return text if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", text) else ""

    @staticmethod
    def _find(entry_id: str, data: dict) -> dict | None:
        if not entry_id:
            return None
        for item in data["queue"] + data["steer"] + data["recent"]:
            if str(item.get("id")) == entry_id:
                return item
        return None

    @staticmethod
    def _remember(data: dict, item: dict) -> None:
        data["recent"] = [v for v in data["recent"] if v.get("id") != item.get("id")] + [dict(item)]
        del data["recent"][:-80]

    def enqueue(self, tid: str, text: str, display: str | None = None, request_id: str = "") -> tuple[dict, bool]:
        """Put one message at the end of the conversation's queue. Returns (item, duplicate)."""
        rid = self._request_id(request_id)
        with self.lock:
            data = self._load(tid)
            found = self._find(rid, data)
            if found is not None:
                if found.get("text") != text:
                    raise ValueError("请求编号已用于其他消息")
                return found, True
            item = {"id": rid or uuid.uuid4().hex, "text": text,
                    "display": str(display) if display is not None else text,
                    "request_id": rid, "created": time.time()}
            data["queue"].append(item)
            self._remember(data, item)
            self._save(tid, data)
            return item, False

    def add_steer(self, tid: str, text: str, display: str | None = None, request_id: str = "") -> tuple[dict, bool]:
        """Put one message in the conversation's steer slot. Returns (item, duplicate)."""
        rid = self._request_id(request_id)
        with self.lock:
            data = self._load(tid)
            found = self._find(rid, data)
            if found is not None:
                if found.get("text") != text:
                    raise ValueError("请求编号已用于其他消息")
                return found, True
            item = {"id": rid or uuid.uuid4().hex, "text": text,
                    "display": str(display) if display is not None else text,
                    "request_id": rid, "created": time.time()}
            data["steer"].append(item)
            self._remember(data, item)
            self._save(tid, data)
            return item, False

    def promote(self, tid: str, item_id: str) -> dict:
        """Move one queued message into the steer slot: the phone's 'make this a steer'."""
        with self.lock:
            data = self._load(tid)
            item = next((v for v in data["queue"] if str(v.get("id")) == str(item_id)), None)
            if item is None:
                raise KeyError(item_id)
            data["queue"] = [v for v in data["queue"] if str(v.get("id")) != str(item_id)]
            data["steer"].append(item)
            self._save(tid, data)
            return item

    def take_steer(self, tid: str) -> list[dict]:
        with self.lock:
            data = self._load(tid)
            items, data["steer"] = data["steer"], []
            if items:
                self._save(tid, data)
            return items

    def pop_queue(self, tid: str) -> dict | None:
        with self.lock:
            data = self._load(tid)
            if not data["queue"]:
                return None
            item = data["queue"].pop(0)
            self._save(tid, data)
            return item

    def list_queue(self, tid: str) -> list[dict]:
        with self.lock:
            return list(self._load(tid)["queue"])

    def has_any(self, tid: str) -> bool:
        with self.lock:
            data = self._load(tid)
            return bool(data["queue"] or data["steer"])

    def has_steer(self, tid: str) -> bool:
        """Whether anything waits in the steer slot (asked before the more expensive checks that hand it over)."""
        with self.lock:
            return bool(self._load(tid)["steer"])


def cleanup_claude_images(images_root: Path, *, now: float | None = None) -> None:
    """Remove image files older than 7 days under <data_dir>/claude-images."""
    root = Path(images_root)
    if not root.is_dir():
        return
    cutoff = (now if now is not None else time.time()) - IMAGE_RETENTION_SECONDS
    for child in list(root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        for file in list(child.iterdir()):
            if file.is_symlink() or not file.is_file():
                continue
            try:
                if file.stat().st_mtime < cutoff:
                    file.unlink(missing_ok=True)
            except OSError:
                continue
        try:
            if not any(child.iterdir()):
                child.rmdir()
        except OSError:
            pass


def store_claude_image(images_root: Path, tid: str, meta: dict, *, now: float | None = None) -> Path:
    """Compress one phone picture for Claude's Read tool (long side ≤1600, ≤400 KB) into claude-images/<tid>/."""
    from codex_apptools import _prepare_codex_image  # the same Codex dev.48 compression
    cleanup_claude_images(images_root, now=now)
    safe_tid = re.sub(r"[^A-Za-z0-9._-]", "_", str(tid or "conversation"))[:120] or "conversation"
    dest_dir = Path(images_root) / safe_tid
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = Path(str(meta["path"]))
    ident = str(meta.get("id") or "")
    if not re.fullmatch(r"[a-f0-9]{32}", ident):
        import hashlib
        ident = hashlib.sha256(str(src).encode("utf-8")).hexdigest()[:32]
    for ext in IMAGE_SUFFIXES:
        existing = dest_dir / f"{ident}{ext}"
        if existing.is_file():
            return existing
    compressed, ext = _prepare_codex_image(src)
    dest = dest_dir / f"{ident}{ext}"
    temp = dest_dir / f"{ident}{ext}.tmp"
    if compressed is None:
        shutil.copy2(src, temp)
    else:
        temp.write_bytes(compressed)
    os.replace(temp, dest)
    return dest


def image_line(path: Path) -> str:
    return f"[附图] {path}（请先用 Read 工具打开这张图片）"


class Ask:
    """One request Claude Code holds open, and the phone's answer to it as it is put together."""

    def __init__(self, item: dict, payload: dict) -> None:
        self.id = secrets.token_hex(8)
        self.item = item
        self.tool = str(payload.get("tool_name") or "")
        self.input = payload["tool_input"]
        self.suggestions = payload.get("permission_suggestions") or []
        self.done = threading.Event()
        self.reply: dict | None = None  # what goes back to Claude Code; None: no decision
        self.ended = ""                 # phone / pc / gone / late / closed
        self.call: str | None = None    # the call's id in the conversation's record, once found there
        self.seen = None                # the record's size when last looked at
        self.at = 0                     # the question shown (AskUserQuestion)
        self.answers: dict[str, object] = {}
        self.picked: list[str] = []     # what is ticked on a question that takes several

    @property
    def questions(self) -> list:
        return self.input.get("questions") if self.tool == "AskUserQuestion" else []

    def stamp(self) -> list:
        """What a tap's ticket is bound to: a tap made on what the phone showed before is refused."""
        return [self.id, self.at, [[k, v] for k, v in sorted(self.answers.items())], list(self.picked)]


class _ConvState:
    """Live hook state tracked for one desktop Claude conversation."""

    def __init__(self, tid: str, session_id: str = "") -> None:
        self.tid = tid
        self.session_id = session_id
        self.running = False
        self.step = ""
        self.tool_name = ""
        self.tool_use_id = ""
        self.turn_started = 0
        self.turn_ended = 0
        self.step_started_at = 0.0
        self.stop_requested = False
        self.blocks_sent = 0      # Stop blocks used for queued/steered messages in this user turn
        self.continued = False    # a Stop was answered with a block: the same turn goes on
        self.continued_at = 0     # when that block went back, so an older recorded end is not read as idle
        self.last_event_at: float | None = None
        self.last_event_name = ""
        self.last_notification: dict[str, Any] | None = None
        self.pid = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "tid": self.tid,
            "session_id": self.session_id,
            "running": self.running,
            "step": self.step,
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "turn_started": self.turn_started,
            "turn_ended": self.turn_ended,
            "step_started_at": self.step_started_at,
            "stop_requested": self.stop_requested,
            "blocks_sent": self.blocks_sent,
            "continued": self.continued,
            "continued_at": self.continued_at,
            "last_event_at": self.last_event_at,
            "last_event_name": self.last_event_name,
            "last_notification": dict(self.last_notification) if self.last_notification else None,
            "pid": self.pid,
        }


class Bridge:
    link_wait = 10  # seconds a PermissionRequest waits for its conversation to be linked to its record (find)

    def __init__(
        self,
        log=print,
        notify=None,
        changed=None,
        sessions=None,
        record=None,
        clock=time.monotonic,
        wall_clock=time.time,
        tcp_owner=None,
        process_exe=None,
        list_processes=None,
        kill_process=None,
        current_user: str | None = None,
        server_port: int = 0,
        queue_root: Path | None = None,
        images_root: Path | None = None,
    ) -> None:
        self.log = log
        self.notify = notify          # notify.Notifier.asking: the phone hears that Claude waits
        self.changed = changed or (lambda tid: None)  # the controller drops what it read of this conversation
        self.sessions = sessions or (lambda: chats.claude_sessions(100000))
        self.record = record or chats.conv_path
        self.clock = clock
        self.wall_clock = wall_clock
        self._tcp_owner = tcp_owner or lookup_tcp_owner_pid
        self._process_exe = process_exe or lookup_process_exe
        self._list_processes = list_processes
        self._kill_process = kill_process
        self._current_user = current_user
        self.server_port = int(server_port or 0)
        self.queues = HookQueues(queue_root)
        self._images_root = Path(images_root) if images_root is not None else None

        self.lock = threading.Lock()
        self.asks: dict[str, Ask] = {}      # held now, oldest first
        self.answered: dict[str, float] = {}  # conversation -> when a phone answer last went back

        # Fast-path caches and live state
        self._session_map: dict[str, dict] = {}   # cliSessionId -> desktop item
        self._last_refresh = 0.0
        self._refreshing = False
        self._unknown_retry_at: dict[str, float] = {}   # session_id -> when to look for it again
        self._unknown_delay: dict[str, float] = {}
        self._session_pids: dict[str, int] = {}   # cliSessionId -> verified claude.exe PID
        self._pid_checked_at: dict[str, float] = {}  # cliSessionId -> when that PID was last verified
        self._session_ports: dict[str, int] = {}     # cliSessionId -> its hook connection's client port
        self._states: dict[str, _ConvState] = {}  # desktop conv id -> _ConvState
        self._main_calls: dict[str, bool] = {}   # tool_use_id -> whether the main conversation made that call

    # -- session cache

    def refresh_sessions(self) -> None:
        """Reload cliSessionId -> desktop conversation cache from self.sessions()."""
        try:
            items = self.sessions() or []
            mapping = {str(s["cli"]): s for s in items if isinstance(s, dict) and s.get("cli") and s.get("id")}
        except Exception:
            mapping = None
        now = self.clock()
        with self.lock:
            if mapping is not None:
                self._session_map.update(mapping)
                for session_id in mapping:  # found: its backoff is over
                    self._unknown_retry_at.pop(session_id, None)
                    self._unknown_delay.pop(session_id, None)
            self._last_refresh = now
            self._refreshing = False

    def register_session(self, item: dict) -> None:
        """Explicitly insert a desktop conversation into the session_id cache."""
        if isinstance(item, dict) and item.get("cli") and item.get("id"):
            with self.lock:
                self._session_map[str(item["cli"])] = item
                self._unknown_retry_at.pop(str(item["cli"]), None)
                self._unknown_delay.pop(str(item["cli"]), None)

    def _lookup_fast_session(self, session_id: str) -> dict | None:
        """O(1) lookup of desktop conversation by session_id.

        A miss schedules one background refresh, then backs off for this session alone: 2, 4, 8 … 60 seconds. A
        conversation opened while hooks were already running becomes known a few seconds after its first message;
        a terminal session that this desktop never lists is not rescanned on every one of its steps."""
        if not session_id:
            return None
        start_refresh = False
        now = self.clock()
        with self.lock:
            item = self._session_map.get(session_id)
            if item is not None:
                self._unknown_retry_at.pop(session_id, None)
                self._unknown_delay.pop(session_id, None)
                return item
            due = self._unknown_retry_at.get(session_id)
            if due is not None and now < due:
                return None
            delay = self._unknown_delay.get(session_id)
            delay = SESSION_BACKOFF_START if delay is None else min(delay * 2, SESSION_BACKOFF_MAX)
            self._unknown_delay[session_id] = delay
            self._unknown_retry_at[session_id] = now + delay
            if len(self._unknown_retry_at) > 512:  # old sessions that never answer: forget the stale ones
                for stale in [s for s, at in self._unknown_retry_at.items() if at < now - 3600]:
                    self._unknown_retry_at.pop(stale, None)
                    self._unknown_delay.pop(stale, None)
            if not self._refreshing:
                self._refreshing = True
                start_refresh = True
        if start_refresh:
            threading.Thread(target=self.refresh_sessions, name="claude-hook-sessions", daemon=True).start()
        return None

    def _process_is_claude(self, pid: int) -> bool:
        """Whether [pid] is still a Claude Code claude.exe (its path is checked, never its command line)."""
        if pid <= 0:
            return False
        try:
            exe = str(self._process_exe(pid) or "")
        except Exception:
            exe = ""
        return is_claude_code_exe(exe)

    def _sync_state_pid(self, session_id: str, tid: str, pid: int) -> None:
        if not tid:
            return
        with self.lock:
            st = self._states.get(tid)
            if st is not None and (pid > 0 or st.session_id == session_id):
                st.pid = max(int(pid or 0), 0)

    def _note_connection_pid(self, session_id: str, tid: str, client_port: int, server_port: int,
                             force: bool = False) -> int:
        """The claude.exe PID for this conversation, from the hook connection's client port.

        Once known it is trusted for PID_RECHECK_SECONDS: every event then costs two dict lookups, not a TCP table
        scan plus a process-path query. After that the PID's path is checked again (and the TCP table only if it is
        gone). force: request_stop checks again right before it ends a command."""
        if not session_id:
            return 0
        port = int(server_port or self.server_port or 0)
        now = self.clock()
        with self.lock:
            known = int(self._session_pids.get(session_id, 0) or 0)
            checked = self._pid_checked_at.get(session_id, 0.0)
            if client_port > 0:
                self._session_ports[session_id] = int(client_port)
            else:
                client_port = int(self._session_ports.get(session_id, 0) or 0)
        if known > 0 and not force and now - checked < PID_RECHECK_SECONDS:
            self._sync_state_pid(session_id, tid, known)
            return known
        pid = known if known > 0 and self._process_is_claude(known) else 0
        if not pid and client_port > 0 and port > 0:
            try:
                candidate = int(self._tcp_owner(client_port, port) or 0)
            except Exception:
                candidate = 0
            if candidate > 0 and self._process_is_claude(candidate):
                pid = candidate
        with self.lock:
            if pid > 0:
                self._session_pids[session_id] = pid
                self._pid_checked_at[session_id] = now
            else:
                self._session_pids.pop(session_id, None)
                self._pid_checked_at.pop(session_id, None)
        self._sync_state_pid(session_id, tid, pid)
        return pid

    def session_pid(self, session_id: str) -> int:
        with self.lock:
            return self._session_pids.get(session_id, 0)

    def conv_pid(self, tid: str) -> int:
        with self.lock:
            st = self._states.get(tid)
            if st is None:
                return 0
            return st.pid or self._session_pids.get(st.session_id, 0)

    def is_active(self, tid: str) -> bool:
        """Whether this conversation has received at least one of the new hook events."""
        with self.lock:
            st = self._states.get(tid)
            return st is not None and st.last_event_at is not None

    def is_running(self, tid: str) -> bool:
        """Whether hooks are active here and the turn is still running (the phone's queue/steer condition)."""
        with self.lock:
            st = self._states.get(tid)
            return bool(st is not None and st.last_event_at is not None and st.running)

    @property
    def images_root(self) -> Path:
        return self._images_root if self._images_root is not None else _data_path("claude-images")

    def enqueue_message(self, tid: str, text: str, display: str | None = None, request_id: str = "") -> tuple[dict, bool]:
        return self.queues.enqueue(tid, text, display, request_id)

    def enqueue_steer(self, tid: str, text: str, display: str | None = None, request_id: str = "") -> tuple[dict, bool]:
        return self.queues.add_steer(tid, text, display, request_id)

    def list_queued(self, tid: str) -> list[dict]:
        return self.queues.list_queue(tid)

    def promote_to_steer(self, tid: str, item_id: str) -> dict:
        return self.queues.promote(tid, item_id)

    def conv_state(self, tid: str) -> dict[str, Any] | None:
        with self.lock:
            st = self._states.get(tid)
            return st.snapshot() if st is not None else None

    # -- Claude Code's side

    def find(self, session: str) -> dict | None:
        """The desktop's conversation that runs this Claude Code session. A new one is linked to its record 6-7 s
        after its first message (chats.claude_sessions), so it is looked for again for a moment."""
        deadline = self.clock() + self.link_wait
        while True:
            items = self.sessions()
            item = next((s for s in items if s.get("cli") == session), None)
            if item is not None:
                self.register_session(item)
                return item
            if self.clock() >= deadline:
                return None
            time.sleep(1)

    def handle(self, payload: dict, gone=lambda: False, *, client_port: int = 0, server_port: int = 0) -> dict | None:
        """One hook request from Claude Code.
        - PermissionRequest: blocks until the phone answers or the request is let go (unchanged).
        - Fast events (UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, Notification):
          handled in milliseconds without blocking; unknown sessions return None immediately.
        """
        event = str(payload.get("hook_event_name") or "") if isinstance(payload, dict) else ""
        if event == "PermissionRequest":
            return self._handle_permission(payload, gone, client_port=client_port, server_port=server_port)
        if event in FAST_EVENTS:
            return self._handle_fast(event, payload, client_port=client_port, server_port=server_port)
        return None

    def _handle_fast(self, event: str, payload: dict, *, client_port: int = 0, server_port: int = 0) -> dict | None:
        session_id = str(payload.get("session_id") or "")
        item = self._lookup_fast_session(session_id)
        if item is None:
            return None
        tid = str(item["id"])
        now_mono = self.clock()
        now_wall = float(self.wall_clock())

        pid = self._note_connection_pid(session_id, tid, client_port, server_port)

        reply: dict | None = None
        with self.lock:
            st = self._states.get(tid)
            if st is None:
                st = _ConvState(tid, session_id)
                self._states[tid] = st
            elif session_id and st.session_id != session_id:
                st.session_id = session_id
            if pid > 0:
                st.pid = pid
            elif session_id in self._session_pids:
                st.pid = self._session_pids[session_id]

            st.last_event_at = now_mono
            st.last_event_name = event

            if event == "UserPromptSubmit":
                st.running = True
                st.turn_started = int(now_wall)
                st.turn_ended = 0
                st.step = ""
                st.tool_name = ""
                st.tool_use_id = ""
                st.step_started_at = 0.0
                st.stop_requested = False
                st.blocks_sent = 0
                st.continued = False

            elif event == "PreToolUse":
                st.continued = False
                if st.stop_requested:
                    st.running = False
                    st.turn_ended = int(now_wall)
                    st.step = ""
                    st.tool_name = ""
                    st.tool_use_id = ""
                    st.step_started_at = 0.0
                    reply = {
                        "continue": False,
                        "stopReason": STOP_REASON,
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": STOP_DENY_REASON,
                        },
                    }
                else:
                    tool_name = str(payload.get("tool_name") or "")
                    st.running = True
                    if not st.turn_started:
                        st.turn_started = int(now_wall)
                    st.turn_ended = 0
                    st.tool_name = tool_name
                    st.tool_use_id = str(payload.get("tool_use_id") or "")
                    st.step = _step_for_tool(tool_name)
                    st.step_started_at = now_wall

            elif event in ("PostToolUse", "PostToolUseFailure"):
                tuid = str(payload.get("tool_use_id") or "")
                if not st.tool_use_id or not tuid or st.tool_use_id == tuid:
                    st.tool_name = ""
                    st.tool_use_id = ""
                    st.step = ""
                    st.step_started_at = 0.0
                if not st.stop_requested and self._steer_goes_to_main(tid, item, payload):
                    # only the main conversation's own call takes the steer: a subagent's call would swallow it
                    pending = self.queues.take_steer(tid)
                    if pending:
                        text = "\n\n".join(str(v.get("text") or "") for v in pending)
                        reply = {"hookSpecificOutput": {"hookEventName": event,
                                                        "additionalContext": STEER_PREFIX + text}}

            elif event == "Stop":
                stopped = st.stop_requested
                st.stop_requested = False
                st.running = False
                st.continued = False
                st.turn_ended = int(now_wall)
                st.step = ""
                st.tool_name = ""
                st.tool_use_id = ""
                st.step_started_at = 0.0
                # A phone stop ends the turn; what is still queued stays for the next sending chance. Otherwise the
                # steer slot goes first (it could not be handed over during the turn), then one queued message.
                if not stopped and st.blocks_sent < MAX_BLOCKS_PER_TURN:
                    pending = self.queues.take_steer(tid)
                    if pending:
                        st.blocks_sent += 1
                        st.running = True
                        st.continued = True
                        st.continued_at = int(now_wall)
                        st.turn_ended = 0
                        text = "\n\n".join(str(v.get("text") or "") for v in pending)
                        reply = {"decision": "block", "reason": STEER_PREFIX + text}
                    else:
                        queued = self.queues.pop_queue(tid)
                        if queued:
                            st.blocks_sent += 1
                            st.running = True
                            st.continued = True
                            st.continued_at = int(now_wall)
                            st.turn_ended = 0
                            reply = {"decision": "block",
                                     "reason": QUEUE_PREFIX + str(queued.get("text") or "")}

            elif event == "Notification":
                st.last_notification = {
                    "type": str(payload.get("notification_type") or ""),
                    "message": str(payload.get("message") or "")[:200],
                    "at": now_wall,
                }

        self.changed(tid)
        return reply

    def _steer_goes_to_main(self, tid: str, item: dict, payload: dict) -> bool:
        """Whether the steer waiting in this conversation's slot goes back with this tool event (11-24).

        Cheap when nothing waits (no steer slot, no record read). The record looked at is the conversation's own
        (self.record), never the request's transcript_path, which may be a subagent's record."""
        if not self.queues.has_steer(tid):
            return False
        try:
            path = self.record(item)
        except Exception:
            return False
        return is_main_conversation_call(payload, path, self._main_calls)

    def _handle_permission(self, payload: dict, gone=lambda: False, *, client_port: int = 0, server_port: int = 0) -> dict | None:
        # Every way a request is let go says which it was, with its tool's name only: no conversation, command or input
        # goes in, and the phone relies on the desktop's own button for such a request (11-24).
        tool = str(payload.get("tool_name") or "")
        if not isinstance(payload.get("tool_input"), dict):
            self.log(f"Claude 权限请求：{tool or '（没有工具名）'} 没接，工具输入不是对象；留给桌面")
            return None
        if not tool:
            self.log("Claude 权限请求：没接，请求里没有工具名；留给桌面")
            return None
        if tool in NOT_HELD:
            self.log(f"Claude 权限请求：{tool} 没接，计划确认不在钩子里答；留给桌面")
            return None
        if tool == "AskUserQuestion" and not questions_ok(payload["tool_input"]):
            self.log(f"Claude 权限请求：{tool} 没接，问题格式不对；留给桌面")
            return None
        session_id = str(payload.get("session_id") or "")
        item = self.find(session_id)
        if item is None:  # Claude Code in a terminal or an editor, or a conversation this service does not list
            self.log(f"Claude 权限请求：{tool} 没接，{self.link_wait} 秒内没找到这个会话对应的对话；留给桌面")
            return None
        self._note_connection_pid(session_id, str(item["id"]), client_port, server_port)
        ask = Ask(item, payload)
        with self.lock:
            self.asks[ask.id] = ask
        self.changed(item["id"])
        what = summary(ask)
        self.log(f"Claude「{item.get('title', '')}」：{what}，等手机或电脑回答")
        if self.notify:
            threading.Thread(target=self.notify, args=(item, what), daemon=True).start()
        try:
            deadline, tick = self.clock() + WAIT_SECONDS, 0
            while not ask.done.wait(.5):
                tick += 1
                reason = ("gone" if gone() else "pc" if tick % 2 == 0 and self.settled(ask)
                          else "late" if self.clock() >= deadline else "")
                if reason:
                    with self.lock:  # a tap at this very moment either went back first or is refused
                        if not ask.done.is_set():
                            ask.ended = reason
                            ask.done.set()
        finally:
            with self.lock:
                self.asks.pop(ask.id, None)
            self.changed(item["id"])
        told = {"phone": "手机上答了", "pc": "在电脑上答了", "gone": "Claude 那边不等了（停止、超时或关掉了）",
                "late": f"{WAIT_SECONDS // 60} 分钟没人答，不再等"}.get(ask.ended, ask.ended)
        self.log(f"Claude「{item.get('title', '')}」：{what}——{told}")
        return ask.reply if ask.ended == "phone" else None

    def settled(self, ask: Ask) -> bool:
        """Whether the conversation's record holds this call's result: answered on the PC (allowed, refused or the
        question answered), so Claude Code no longer waits on this request."""
        path = self.record(ask.item)
        if path is None:
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == ask.seen:
            return False
        ask.seen = size
        lines, _ = chats.read_tail(path, 2 << 20)
        calls = open_calls(lines, ask.tool)
        if ask.call is None:
            same = [cid for cid, given in calls.items() if given == ask.input]
            ask.call = same[-1] if same else next(iter(calls)) if len(calls) == 1 else None
            return False
        return ask.call not in calls

    # -- the phone's side

    def request_stop(self, tid: str) -> dict[str, Any]:
        """Mark [tid] to stop on the next PreToolUse and immediately kill any running Bash/PowerShell child tree.
        The conversation's claude.exe is verified once more right before a command tree is ended (design 3.4)."""
        with self.lock:
            st = self._states.get(tid)
            if st is None:
                st = _ConvState(tid)
                self._states[tid] = st
            st.stop_requested = True
            tool_name = st.tool_name
            step_started_at = st.step_started_at
            session_id = st.session_id
            pid = st.pid or self._session_pids.get(session_id, 0)
            client_port = self._session_ports.get(session_id, 0)
        killed: list[int] = []
        if tool_name in COMMAND_TOOLS and step_started_at > 0 and pid > 0:
            # check again that it is still this conversation's claude.exe, and that its path is still Claude Code's
            if session_id:
                pid = self._note_connection_pid(session_id, tid, client_port, self.server_port, force=True)
            elif not self._process_is_claude(pid):
                pid = 0
        if tool_name in COMMAND_TOOLS and pid > 0 and step_started_at > 0:
            killed = kill_session_command(
                pid,
                step_started_at,
                list_processes=self._list_processes,
                kill_process=self._kill_process,
                current_user=self._current_user,
                log=self.log,
            )
        self.changed(tid)
        return {
            "ok": True,
            "killed": bool(killed),
            "killed_pids": killed,
            "tool": tool_name,
        }

    def layout(self, tid: str) -> tuple[str, dict, list] | None:
        """(request id, its prompt, the stamp its taps are bound to) for the oldest request held on this conversation,
        read at one moment; None when none is held."""
        with self.lock:
            ask = next((a for a in self.asks.values() if a.item["id"] == tid and not a.done.is_set()), None)
            return (ask.id, self.prompt(ask), ask.stamp()) if ask else None

    def just_answered(self, tid: str) -> bool:
        """Whether a phone answer went back a moment ago: the desktop may still draw the card it closes."""
        return self.clock() - self.answered.get(tid, -SHOWN_AFTER) < SHOWN_AFTER

    def prompt(self, ask: Ask) -> dict:
        """The request laid out as claude_control._dock_read lays out the desktop's prompt for the phone: title,
        progress, choices, nav, other. Each part says in 'do' what a tap on it does (Controller makes it a ticket)."""
        if ask.tool != "AskUserQuestion":
            choices = [{"name": "Allow", "label": "允许", "description": "", "do": ["allow"]}]
            rules = always_rules(ask.suggestions)
            if rules:
                choices.append({"name": "Always allow", "label": "允许，以后这类不再问",
                                "description": "、".join(rules), "do": ["always"]})
            choices.append({"name": "Deny", "label": "拒绝", "description": "", "do": ["deny"]})
            return {"title": describe(ask.tool, ask.input), "progress": None, "choices": choices, "nav": [], "other": None}
        qs = ask.questions
        q = qs[ask.at]
        several, last = bool(q.get("multiSelect")), ask.at == len(qs) - 1
        choices = []
        for i, option in enumerate(q.get("options") or []):
            label = str(option.get("label") or "")
            pressed = label in ask.picked if several else ask.answers.get(q["question"]) == label
            # the phone apps do not mark what is ticked (iOS passes selected: false, Android ignores 'pressed'), so a
            # question that takes several shows it in the label
            choices.append({"name": label, "label": ("✓ " if several and pressed else "") + label,
                            "description": str(option.get("description") or ""), "pressed": pressed, "do": ["pick", i]})
        nav = [{"name": NAV["back"][0], "label": NAV["back"][1], "do": ["back"]}] if ask.at else []
        nav.append({"name": NAV["skip"][0], "label": NAV["skip"][1], "do": ["skip"]})
        if several:
            name, label = NAV["submit" if last else "next"]
            nav.append({"name": name, "label": label, "do": ["next"], "ready": bool(ask.picked)})
        return {"title": str(q.get("question") or ""), "progress": f"{ask.at + 1} / {len(qs)}" if len(qs) > 1 else None,
                "choices": choices, "nav": nav, "other": {"name": "Other"}}

    def press(self, tid: str, ask_id: str, do: list, stamp: list) -> str:
        """A tap on the phone. Returns what the phone is told; raises chats.ChatError when the request is gone or the
        phone showed something else than there is now."""
        with self.lock:
            ask = self.asks.get(ask_id)
            if ask is None or ask.item["id"] != tid or ask.done.is_set():
                raise chats.ChatError("Claude 已经不在等这个了：电脑上答过了，或者这一轮停了。刷新看看")
            if ask.stamp() != stamp:
                raise chats.ChatError("题目已经变了，刷新后再选")
            kind = do[0] if do else ""
            if ask.tool != "AskUserQuestion":
                if kind == "allow":
                    return self._finish(ask, allow({}), "已允许")
                if kind == "always":
                    return self._finish(ask, allow({"updatedPermissions": [s for s in ask.suggestions
                                                                          if s.get("type") == "addRules"]}),
                                        "已允许，以后这类不再问")
                if kind == "deny":
                    return self._finish(ask, {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
                        "behavior": "deny", "message": DENIED}}}, "已拒绝")
                raise chats.ChatError("没有这个选项")
            q = ask.questions[ask.at]
            options = [str(o.get("label") or "") for o in q.get("options") or []]
            several = bool(q.get("multiSelect"))
            if kind == "pick" and len(do) > 1 and isinstance(do[1], int) and 0 <= do[1] < len(options):
                label = options[do[1]]
                if not several:
                    ask.answers[q["question"]] = label
                    return self._advance(ask, f"已选：{label}")
                ask.picked = [o for o in options if (o in ask.picked) != (o == label)]  # tick or untick, in option order
                return ("已勾选：" if label in ask.picked else "已取消：") + label
            if kind == "back" and ask.at:
                ask.at -= 1
                self._restore(ask)
                return "回到上一题"
            if kind == "skip":
                ask.answers.pop(q["question"], None)
                return self._advance(ask, "跳过了这一题")
            if kind == "next" and several and ask.picked:
                ask.answers[q["question"]] = list(ask.picked)
                return self._advance(ask, "已选：" + "、".join(ask.picked))
            raise chats.ChatError("这一步现在点不了，刷新看看")

    def _restore(self, ask: Ask) -> None:
        q = ask.questions[ask.at]
        given = ask.answers.get(q["question"])
        ask.picked = list(given) if q.get("multiSelect") and isinstance(given, list) else []

    def _advance(self, ask: Ask, text: str) -> str:
        ask.at += 1
        if ask.at < len(ask.questions):
            self._restore(ask)
            self.changed(ask.item["id"])
            return text
        # one answer per question, by its text; several as Claude Code's documents write them: "A, B"
        answers = {k: ", ".join(v) if isinstance(v, list) else v for k, v in ask.answers.items()}
        return self._finish(ask, allow({"updatedInput": {**ask.input, "answers": answers}}),
                            text + ("，已提交" if answers else "，都没答，已告诉 Claude"))

    def _finish(self, ask: Ask, reply: dict, text: str) -> str:
        ask.reply, ask.ended = reply, "phone"
        self.answered[ask.item["id"]] = self.clock()
        ask.done.set()
        self.changed(ask.item["id"])
        return text


def dispatch(bridge, payload: dict, gone=lambda: False, client_port: int = 0, server_port: int = 0) -> dict | None:
    """Invoke [bridge.handle], passing TCP ports when supported (keeps 2-arg test stubs compatible)."""
    if isinstance(bridge, Bridge):
        return bridge.handle(payload, gone, client_port=client_port, server_port=server_port)
    return bridge.handle(payload, gone)


def allow(extra: dict) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow", **extra}}}


def questions_ok(data: dict) -> bool:
    qs = data.get("questions")
    return isinstance(qs, list) and bool(qs) and all(
        isinstance(q, dict) and isinstance(q.get("question"), str) and isinstance(q.get("options"), list) and q["options"]
        and all(isinstance(o, dict) and isinstance(o.get("label"), str) for o in q["options"]) for q in qs)


def always_rules(suggestions: list) -> list[str]:
    """The rules a "don't ask again" would add, as the settings write them: Bash(npm run lint). Only rule suggestions:
    another kind may switch the conversation's mode (setMode acceptEdits, seen 10-27)."""
    out = []
    for s in suggestions:
        if isinstance(s, dict) and s.get("type") == "addRules" and s.get("behavior") == "allow":
            for r in s.get("rules") or []:
                if isinstance(r, dict) and r.get("toolName"):
                    out.append(f"{r['toolName']}({r['ruleContent']})" if r.get("ruleContent") else str(r["toolName"]))
    return out


def describe(tool: str, data: dict) -> str:
    """What Claude asks permission for: a first line the phone shows on its own, then the details."""
    def text(value, limit=800):
        value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return value if len(value) <= limit else value[:limit] + "…"
    if tool in ("Bash", "PowerShell"):
        head, body = "Claude 想运行命令", text(data.get("command") or "")
    elif tool in ("Edit", "MultiEdit", "NotebookEdit"):
        head, body = "Claude 想改文件", text(data.get("file_path") or data.get("notebook_path") or "")
    elif tool == "Write":
        head, body = "Claude 想写文件", text(data.get("file_path") or "")
    elif tool == "WebFetch":
        head, body = "Claude 想打开网页", text(data.get("url") or "")
    elif tool == "WebSearch":
        head, body = "Claude 想上网搜索", text(data.get("query") or "")
    elif tool.startswith("mcp__"):
        parts = tool.split("__")
        head, body = f"Claude 想用 {parts[1] if len(parts) > 2 else tool} 的 {parts[-1]}", text(data, 600)
    else:
        head, body = f"Claude 想用 {tool}", text(data, 600)
    note = data.get("description") if isinstance(data.get("description"), str) else ""
    return "\n".join(p for p in (head, body, note) if p)


def summary(ask: Ask) -> str:
    """One line for the log and the phone's notification."""
    if ask.tool == "AskUserQuestion":
        return "问：" + chats.one_line(str(ask.questions[0].get("question") or ""), 80)
    return chats.one_line(describe(ask.tool, ask.input).replace("\n", "："), 90)


def open_calls(lines: list[bytes], tool: str) -> dict[str, dict]:
    """The calls of this tool in these lines of a Claude record that have no result yet: their id -> their input, in
    the order they were made."""
    calls: dict[str, dict] = {}
    needle = tool.encode()
    for raw in lines:
        if needle not in raw and b"tool_result" not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        content = (rec.get("message") or {}).get("content") if isinstance(rec, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == tool and block.get("id"):
                calls[block["id"]] = block.get("input")
            elif block.get("type") == "tool_result":
                calls.pop(block.get("tool_use_id"), None)
    return calls


def _same_record(left: str, right: Path) -> bool:
    """Whether these two names are one file on disk (Windows: case and separators do not matter)."""
    def norm(value) -> str:
        text = str(value or "")
        if text.startswith("\\\\?\\"):  # the extended-length form of the same path
            text = text[4:]
        text = os.path.expanduser(text)
        try:
            return os.path.normcase(os.path.realpath(text))
        except (OSError, ValueError):
            return os.path.normcase(os.path.abspath(text))
    return norm(left) == norm(right)


def _record_holds_call(path: Path, tool_use_id: str) -> bool:
    """Whether the last part of this Claude record holds an assistant `tool_use` block with this id.

    Only the record's own side: a subagent's call written into the same file is marked isSidechain."""
    needle = tool_use_id.encode("utf-8", "ignore")
    try:
        lines, _ = chats.read_tail(path, STEER_RECORD_TAIL)
    except (OSError, ValueError):
        return False
    for raw in lines:
        if needle not in raw or b'"tool_use"' not in raw:
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain"):
            continue
        message = rec.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" \
                    and str(block.get("id") or "") == tool_use_id:
                return True
    return False


def is_main_conversation_call(payload: dict, record: Path | None, cache: dict[str, bool] | None = None) -> bool:
    """Whether this tool event is the main conversation's own call, not one a subagent it started made (11-24).

    A subagent's tool events reach the same conversation's hooks (same session_id), so a phone steer handed back on
    one of them lands in the subagent's tool result and the main conversation never sees it. Three signs, in order:
    the request names the subagent (`agent_id` / `agent_type`); its `transcript_path` is not the conversation's
    record; the end of that record holds no assistant `tool_use` block with this `tool_use_id`. Anything unreadable
    counts as another's: a steer waits for the main conversation's next call rather than going to the wrong one."""
    if not isinstance(payload, dict):
        return False
    if any(str(payload.get(key) or "") for key in SUBAGENT_KEYS):
        return False
    tool_use_id = str(payload.get("tool_use_id") or "")
    if not tool_use_id or record is None:
        return False
    elsewhere = str(payload.get("transcript_path") or "")
    if elsewhere and not _same_record(elsewhere, record):
        return False
    if cache is not None and tool_use_id in cache:
        return cache[tool_use_id]
    found = _record_holds_call(record, tool_use_id)
    if cache is not None:  # one id is asked about once: the cache only saves a repeated request
        if len(cache) >= 512:
            cache.clear()
        cache[tool_use_id] = found
    return found


# ---------------------------------------------------------------- Claude's settings


def _ours(handler) -> bool:
    url = handler.get("url") if isinstance(handler, dict) else None
    try:
        return isinstance(url, str) and PATH in url and urlsplit(url).hostname in ("127.0.0.1", "localhost")
    except ValueError:
        return False


def _read(path: Path, log) -> dict | None:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError) as exc:
        log(f"Claude 的设置读不懂，没改（{path}）：{exc}")
        return None
    if not isinstance(data, dict):
        log(f"Claude 的设置不是常见的样子，没改（{path}）")
        return None
    hooks = data.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        log(f"Claude 的设置不是常见的样子，没改（{path}）")
        return None
    if isinstance(hooks, dict):
        for event, _, _ in MANAGED_HOOKS:
            if event in hooks and not isinstance(hooks[event], list):
                log(f"Claude 的设置不是常见的样子，没改（{path}）")
                return None
    return data


def _write(path: Path, data: dict, original: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".before-teleply")
    if original is not None and not backup.exists():  # the user's file as it was before Teleply first changed it
        backup.write_bytes(original)
    temp = path.with_name(path.name + ".teleply-tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _find_ours(data: dict) -> dict[str, list[tuple[Any, dict]]]:
    """Return event -> [(matcher, handler), ...] for all Teleply HTTP hook entries across every event."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return {}
    found: dict[str, list[tuple[Any, dict]]] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        items = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if _ours(handler):
                    items.append((group.get("matcher"), handler))
        if items:
            found[str(event)] = items
    return found


def _strip(data: dict) -> None:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event in list(hooks.keys()):
        raw_groups = hooks.get(event)
        if not isinstance(raw_groups, list):
            continue
        groups = []
        for group in raw_groups:
            handlers = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(handlers, list) and any(_ours(h) for h in handlers):
                group = {**group, "hooks": [h for h in handlers if not _ours(h)]}
                if not group["hooks"]:
                    continue
            groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)


def _desired_group(url: str, matcher: str | None, timeout: int) -> dict:
    entry = {"type": "http", "url": url, "timeout": timeout}
    return {"matcher": matcher, "hooks": [entry]} if matcher is not None else {"hooks": [entry]}


def install(url: str, log=print, path: Path | None = None) -> bool:
    """Put Teleply's 7 HTTP hooks into Claude's user settings, or bring older entries up to date.
    The user's own hooks and settings stay untouched. Returns whether the file was written."""
    path = path or settings_file()
    data = _read(path, log)
    if data is None:
        return False
    existing = _find_ours(data)
    expected = {
        event: [(matcher, {"type": "http", "url": url, "timeout": timeout})]
        for event, matcher, timeout in MANAGED_HOOKS
    }
    if existing == expected:
        return False
    original = path.read_bytes() if path.exists() and not existing else None  # kept once: before Teleply first changed it
    _strip(data)
    hooks = data.setdefault("hooks", {})
    for event, matcher, timeout in MANAGED_HOOKS:
        hooks.setdefault(event, []).append(_desired_group(url, matcher, timeout))
    _write(path, data, original)
    log(f"Claude 的设置里加上了遥应的 {len(MANAGED_HOOKS)} 条 hook（{path}）：同步状态、停止、提问与权限")
    return True


def remove(log=print, path: Path | None = None) -> bool:
    """Take Teleply's hooks out of Claude's user settings (uninstall / disabled). Returns whether the file was written."""
    path = path or settings_file()
    data = _read(path, log)
    if not data:
        return False
    before = json.dumps(data, sort_keys=True)
    _strip(data)
    if json.dumps(data, sort_keys=True) == before:
        return False
    _write(path, data, None)
    log(f"Claude 的设置里去掉了遥应的 hook（{path}）")
    return True
