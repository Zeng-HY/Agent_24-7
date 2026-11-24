"""Codex 26.1117+ local hook server, hooks.json installer, trust status reader, and safe command stop.

Handles PreToolUse, PermissionRequest, and Stop events forwarded by TeleplyCodexHook.exe over a
current-user-only Windows named pipe (\\\\.\\pipe\\teleply-codex-hooks-<username>).
- Fast path: returns empty ({} for Stop) in <1 ms when a conversation is not managed by the phone.
- Approval (PermissionRequest): waits up to 60 s ONLY while the phone is watching or initiated
  the turn; never auto-approves; returns empty on timeout so the desktop dialog takes over.
- Question (PreToolUse request_user_input): waits up to 120 s while watching; denies the tool call
  with the user's phone answers in permissionDecisionReason so Codex continues without a desktop card.
- Stop: sets a per-thread deny flag for all subsequent PreToolUse calls AND, under Full Access,
  terminates ONLY the matching user-owned pwsh.exe spawned by codex.exe for the active command.
- Queue handoff (Stop): pops the next queued phone message when stop_hook_active is false.
- Installation: edits only Teleply's 3 entries in ~/.codex/hooks.json (preserving all user hooks);
  never writes config.toml (trust status is read-only from config.toml).
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, Callable

from app_paths import ASSETS
import chats
import codex_control

HOOK_EXE_NAME = "TeleplyCodexHook.exe"
HOOK_EVENTS: tuple[tuple[str, int], ...] = (
    ("PreToolUse", 150),
    ("PermissionRequest", 90),
    ("Stop", 10),
)
TRUST_HINT = "在 Codex 设置 → Hooks 里打开并信任 3 个遥应钩子，手机才能批准、停止、回答"

WATCH_WINDOW_SECONDS = 20.0
APPROVAL_TIMEOUT_SECONDS = 60.0
QUESTION_TIMEOUT_SECONDS = 120.0
TRUST_CACHE_TTL = 2.0
MAX_FRAME_BYTES = 4 << 20
MAX_PROGRESS_EVENTS = 20

STOP_DENY_REASON = "用户在手机上按了停止。不要再调用任何工具，用一句话结束这一轮。"
APPROVAL_DENY_MESSAGE = "用户在手机上拒绝了这次操作。"

_CODEX_HOME_OVERRIDE: Path | None = None

_HOOK_STEPS = {
    "bash": "run",
    "exec": "run",
    "shell": "run",
    "exec_command": "run",
    "powershell": "run",
    "apply_patch": "edit",
    "edit": "edit",
    "write": "edit",
    "web_search": "search",
    "search": "search",
    "view_image": "read",
    "read": "read",
}


def set_default_codex_home_override(path: Path | None) -> None:
    """Test-only hook to ensure tests never read or write the real user's ~/.codex."""
    global _CODEX_HOME_OVERRIDE
    _CODEX_HOME_OVERRIDE = Path(path) if path is not None else None


def default_codex_home() -> Path:
    if _CODEX_HOME_OVERRIDE is not None:
        return _CODEX_HOME_OVERRIDE
    return Path.home() / ".codex"


def _sanitize_user(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return "user"
    safe = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_" for ch in text)
    return safe or "user"


def default_pipe_name(username: str | None = None) -> str:
    user = username or os.environ.get("USERNAME") or getpass.getuser()
    return r"\\.\pipe\teleply-codex-hooks-" + _sanitize_user(user)


def hook_executable() -> Path | None:
    """Locate TeleplyCodexHook.exe next to the installed exe (or in build/ when running from source)."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / HOOK_EXE_NAME)
        candidates.append(ASSETS / HOOK_EXE_NAME)
    else:
        candidates.append(ASSETS / "build" / HOOK_EXE_NAME)
        candidates.append(ASSETS / HOOK_EXE_NAME)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


# ---------------------------------------------------------------- hooks.json & config.toml (read-only)


def is_teleply_handler(handler: Any) -> bool:
    if not isinstance(handler, dict):
        return False
    for key in ("command", "commandWindows"):
        val = handler.get(key)
        if isinstance(val, str) and HOOK_EXE_NAME.lower() in val.lower():
            return True
    return False


def desired_handler(exe_path: Path | str, event: str, timeout: int) -> dict[str, Any]:
    return {
        "type": "command",
        "command": f'"{Path(exe_path)}" {event}',
        "timeout": int(timeout),
    }


def _read_hooks_json(path: Path, log: Callable[[str], None] | None) -> dict[str, Any] | None:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError) as exc:
        if callable(log):
            log(f"Codex hooks.json 读不懂，未改动（{path}）：{exc}")
        return None
    if not isinstance(data, dict):
        if callable(log):
            log(f"Codex hooks.json 格式异常，未改动（{path}）")
        return None
    hooks = data.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        if callable(log):
            log(f"Codex hooks.json 的 hooks 字段不是对象，未改动（{path}）")
        return None
    return data


def _write_hooks_json(path: Path, data: dict[str, Any], original: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".before-teleply")
    if original is not None and not backup.exists():
        backup.write_bytes(original)
    tmp = path.with_name(path.name + ".teleply-tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _find_teleply_coords(data: dict[str, Any]) -> dict[str, list[tuple[int, int, dict[str, Any], Any]]]:
    """Return event -> [(group_idx, hook_idx, handler, matcher), ...] for all Teleply handlers."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return {}
    found: dict[str, list[tuple[int, int, dict[str, Any], Any]]] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        matches: list[tuple[int, int, dict[str, Any], Any]] = []
        for gi, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            for hi, handler in enumerate(handlers):
                if is_teleply_handler(handler):
                    matches.append((gi, hi, handler, group.get("matcher")))
        if matches:
            found[str(event)] = matches
    return found


def _strip_teleply(data: dict[str, Any]) -> bool:
    """Remove only Teleply handlers in-place; preserve all user hooks. Returns True if anything changed."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    changed = False
    for event in list(hooks.keys()):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        new_groups = []
        for group in groups:
            if not isinstance(group, dict):
                new_groups.append(group)
                continue
            handlers = group.get("hooks")
            if isinstance(handlers, list) and any(is_teleply_handler(h) for h in handlers):
                kept = [h for h in handlers if not is_teleply_handler(h)]
                changed = True
                if kept:
                    new_groups.append({**group, "hooks": kept})
            else:
                new_groups.append(group)
        if new_groups:
            hooks[event] = new_groups
        else:
            if event in hooks and groups:
                changed = True
            hooks.pop(event, None)
    if not hooks and "hooks" in data:
        del data["hooks"]
    return changed


def install_hooks(
    exe_path: Path | str,
    *,
    codex_home: Path | None = None,
    log: Callable[[str], None] = print,
) -> bool:
    """Add or update Teleply's 3 entries in hooks.json while preserving every existing user hook.

    Never writes config.toml. Returns True if hooks.json was written.
    """
    home = Path(codex_home) if codex_home is not None else default_codex_home()
    path = home / "hooks.json"
    data = _read_hooks_json(path, log)
    if data is None:
        return False

    desired = {event: desired_handler(exe_path, event, timeout) for event, timeout in HOOK_EVENTS}
    existing = _find_teleply_coords(data)
    already_exact = (
        set(existing.keys()) == set(desired.keys())
        and all(
            len(existing[ev]) == 1
            and existing[ev][0][2] == desired[ev]
            and existing[ev][0][3] == "*"
            for ev in desired
        )
    )
    if already_exact:
        return False

    original = path.read_bytes() if path.exists() and not existing else None
    _strip_teleply(data)
    hooks = data.setdefault("hooks", {})
    for event, timeout in HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            if callable(log):
                log(f"Codex hooks.json 的 {event} 字段不是列表，未改动（{path}）")
            return False
        groups.append({"matcher": "*", "hooks": [desired[event]]})
    _write_hooks_json(path, data, original)
    if callable(log):
        log(f"已将遥应的 3 条 Codex 钩子写入 {path}（原有用户钩子保持不变）")
    return True


def remove_hooks(*, codex_home: Path | None = None, log: Callable[[str], None] = print) -> bool:
    """Remove only Teleply's entries from hooks.json while preserving all user hooks.

    Never touches config.toml. Returns True if hooks.json was written.
    """
    home = Path(codex_home) if codex_home is not None else default_codex_home()
    path = home / "hooks.json"
    if not path.exists():
        return False
    data = _read_hooks_json(path, log)
    if not data:
        return False
    if not _strip_teleply(data):
        return False
    _write_hooks_json(path, data, None)
    if callable(log):
        log(f"已从 {path} 移除遥应的 Codex 钩子")
    return True


def _norm_state_key(key: str) -> str:
    return key.replace("/", "\\").casefold()


def read_trust_status(*, codex_home: Path | None = None) -> str:
    """Read-only check of Teleply hooks status: 'not_installed' | 'pending_trust' | 'enabled'."""
    home = Path(codex_home) if codex_home is not None else default_codex_home()
    hooks_path = home / "hooks.json"
    if not hooks_path.is_file():
        return "not_installed"
    try:
        hooks_data = json.loads(hooks_path.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError):
        return "not_installed"
    if not isinstance(hooks_data, dict):
        return "not_installed"

    coords = _find_teleply_coords(hooks_data)
    if not all(event in coords and coords[event] for event, _ in HOOK_EVENTS):
        return "not_installed"

    cfg_path = home / "config.toml"
    if not cfg_path.is_file():
        return "pending_trust"
    try:
        cfg_data = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        return "pending_trust"

    state = (cfg_data.get("hooks") or {}).get("state") if isinstance(cfg_data.get("hooks"), dict) else None
    if not isinstance(state, dict):
        return "pending_trust"

    norm_state = {_norm_state_key(str(k)): v for k, v in state.items() if isinstance(v, dict)}
    path_candidates = {str(hooks_path), str(hooks_path.resolve())}
    for event, _ in HOOK_EVENTS:
        gi, hi, _, _ = coords[event][0]
        matched = None
        for p_str in path_candidates:
            candidate_key = _norm_state_key(f"{p_str}:{event}:{gi}:{hi}")
            if candidate_key in norm_state:
                matched = norm_state[candidate_key]
                break
        if matched is None:
            return "pending_trust"
        trusted_hash = matched.get("trusted_hash")
        if matched.get("enabled") is not True or not isinstance(trusted_hash, str) or not trusted_hash.strip():
            return "pending_trust"
    return "enabled"


# ---------------------------------------------------------------- safe immediate command stop


def _normalize_cmd(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\r\n", "\n")).strip()


def _short_user(owner: str) -> str:
    text = str(owner or "").strip()
    if "\\" in text:
        text = text.rsplit("\\", 1)[-1]
    return text.casefold()


def _default_list_processes() -> list[dict[str, Any]]:
    """List local processes with PID, PPID, Name, CommandLine, and Owner via WMI."""
    out: list[dict[str, Any]] = []
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            wmi = win32com.client.GetObject("winmgmts:")
            rows = wmi.ExecQuery("SELECT ProcessId, ParentProcessId, Name, CommandLine FROM Win32_Process")
            for proc in rows:
                name = str(getattr(proc, "Name", "") or "")
                low = name.lower()
                # Only query owner on pwsh.exe (saves time); keep codex.exe / parents for ancestor chain.
                owner = ""
                if low == "pwsh.exe":
                    try:
                        res = proc.ExecMethod_("GetOwner")
                        user = getattr(res, "User", "") or ""
                        domain = getattr(res, "Domain", "") or ""
                        owner = f"{domain}\\{user}" if domain and user else str(user)
                    except Exception:
                        owner = ""
                out.append({
                    "pid": int(getattr(proc, "ProcessId", 0) or 0),
                    "ppid": int(getattr(proc, "ParentProcessId", 0) or 0),
                    "name": name,
                    "cmdline": str(getattr(proc, "CommandLine", "") or ""),
                    "owner": owner,
                })
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return []
    return out


def _default_kill_process(pid: int) -> bool:
    """Terminate one specific PID with Win32 TerminateProcess (no shell spawn)."""
    try:
        import ctypes

        PROCESS_TERMINATE = 0x0001
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
        if not handle:
            return False
        try:
            return bool(ctypes.windll.kernel32.TerminateProcess(handle, 1))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def _has_codex_ancestor(pid: int, by_pid: dict[int, dict[str, Any]]) -> bool:
    seen: set[int] = {pid}
    cur = by_pid.get(pid)
    for _ in range(10):
        if not cur:
            return False
        ppid = int(cur.get("ppid") or 0)
        if not ppid or ppid in seen:
            return False
        seen.add(ppid)
        parent = by_pid.get(ppid)
        if not parent:
            return False
        if str(parent.get("name") or "").lower() == "codex.exe":
            return True
        cur = parent
    return False


def kill_running_command(
    command: str,
    *,
    list_processes: Callable[[], list[dict[str, Any]]] | None = None,
    kill_process: Callable[[int], Any] | None = None,
    current_user: str | None = None,
    log: Callable[[str], None] | None = None,
) -> list[int]:
    """Terminate ONLY the current user's codex-primary-runtime pwsh.exe running [command] under codex.exe.

    Never touches codex.exe, ChatGPT.exe, sandbox accounts (CodexSandboxOffline), or unrelated pwsh.exe.
    """
    raw_cmd = str(command or "").strip()
    norm_cmd = _normalize_cmd(raw_cmd)
    if not norm_cmd:
        return []
    want_user = _short_user(current_user or os.environ.get("USERNAME") or getpass.getuser())
    if not want_user:
        return []

    procs = (list_processes or _default_list_processes)()
    if not procs:
        return []
    by_pid = {int(p["pid"]): p for p in procs if isinstance(p, dict) and p.get("pid")}

    killer = kill_process or _default_kill_process
    killed: list[int] = []
    for proc in procs:
        if not isinstance(proc, dict):
            continue
        pid = int(proc.get("pid") or 0)
        name = str(proc.get("name") or "").lower()
        if not pid or name != "pwsh.exe":
            continue
        cmdline = str(proc.get("cmdline") or "")
        if "codex-primary-runtime" not in cmdline.lower():
            continue
        if raw_cmd not in cmdline and norm_cmd not in _normalize_cmd(cmdline):
            continue
        owner = _short_user(str(proc.get("owner") or ""))
        if not owner or owner != want_user or owner == "codexsandboxoffline":
            continue
        if not _has_codex_ancestor(pid, by_pid):
            continue
        try:
            if killer(pid) is not False:
                killed.append(pid)
                if callable(log):
                    log(f"手机停止 Codex：已结束当前命令进程 pwsh.exe (PID {pid})")
        except Exception:
            continue
    return killed


# ---------------------------------------------------------------- pending cards & hook server


def _tool_step(tool_name: str, tool_input: Any) -> str:
    low = (tool_name or "").rsplit(".", 1)[-1].lower()
    if low in _HOOK_STEPS:
        return _HOOK_STEPS[low]
    if "patch" in low or "edit" in low or "write" in low:
        return "edit"
    if "search" in low:
        return "search"
    if "image" in low or "read" in low:
        return "read"
    if "bash" in low or "exec" in low or "shell" in low or "command" in low:
        return "run"
    return ""


def _command_text(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "script"):
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, list) and val:
                return " ".join(str(v) for v in val if v is not None).strip()
    return ""


def _describe_permission(tool_name: str, tool_input: Any) -> tuple[str, str, str, list[str], str]:
    """Return (approval_type, header, command, files, prompt) for a PermissionRequest hook."""
    low = (tool_name or "").lower()
    cmd = _command_text(tool_input)
    files: list[str] = []
    if isinstance(tool_input, dict):
        for key in ("path", "file_path", "target_file"):
            v = tool_input.get(key)
            if isinstance(v, str) and v.strip():
                files.append(v.strip())
        if isinstance(tool_input.get("paths"), list):
            files.extend(str(v) for v in tool_input["paths"] if isinstance(v, str) and v.strip())

    if cmd or low in ("bash", "exec", "shell", "exec_command", "powershell"):
        prompt = cmd or f"运行工具 {tool_name}"
        return "command", "Codex 想运行命令", cmd, [], prompt
    if low in ("apply_patch", "edit", "write", "write_file") or files:
        prompt = "\n".join(files) if files else f"修改文件（{tool_name}）"
        return "file", "Codex 想改文件", "", files, prompt

    summary = ""
    if isinstance(tool_input, dict) and tool_input:
        summary = json.dumps(tool_input, ensure_ascii=False)
        if len(summary) > 500:
            summary = summary[:500] + "…"
    short_tool = tool_name.split("__")[-1] if "__" in tool_name else tool_name
    header = f"Codex 想调用工具 {short_tool}" if short_tool else "Codex 请求批准"
    prompt = f"{tool_name}\n\n{summary}".strip() if summary else tool_name or "请确认是否允许此次操作"
    return "tool", header, "", [], prompt


def _normalize_questions(tool_input: Any) -> list[dict[str, Any]]:
    if not isinstance(tool_input, dict):
        return []
    raw_qs = tool_input.get("questions")
    if not isinstance(raw_qs, list) or not raw_qs:
        return []
    out: list[dict[str, Any]] = []
    for idx, q in enumerate(raw_qs):
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or f"q{idx + 1}")
        question = str(q.get("question") or "").strip()
        if not question:
            continue
        options = []
        for opt in q.get("options") or []:
            if isinstance(opt, dict) and isinstance(opt.get("label"), str):
                options.append({
                    "label": opt["label"],
                    "description": str(opt.get("description") or ""),
                })
        out.append({
            "id": qid,
            "header": str(q.get("header") or ""),
            "question": question,
            "options": options,
            "isOther": bool(q.get("isOther", True)),
            "isMultiple": bool(q.get("isMultiple", q.get("multiSelect", False))),
            "isSecret": bool(q.get("isSecret", False)),
        })
    return out


def _card_revision(answers: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(answers, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class _PendingHook:
    def __init__(self, *, tid: str, kind: str, card: dict[str, Any]) -> None:
        self.tid = tid
        self.kind = kind  # "approval" | "native"
        self.card = card
        self.done = threading.Event()
        self.decision: str | None = None           # "allow" | "deny" (for approval)
        self.answers: dict[str, list[str]] | None = None  # for request_user_input
        self.cancelled = False


def _current_user_security_attributes():
    import ntsecuritycon
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    sd = win32security.SECURITY_DESCRIPTOR()
    dacl = win32security.ACL()
    access = getattr(ntsecuritycon, "FILE_ALL_ACCESS", 0x001F01FF)
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access, user_sid)
    sd.SetSecurityDescriptorDacl(1, dacl, 0)
    sa = win32security.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    return sa


def _read_pipe_exact(handle, count: int) -> bytes | None:
    import pywintypes
    import win32event
    import win32file

    buf = bytearray()
    while len(buf) < count:
        ov = pywintypes.OVERLAPPED()
        ov.hEvent = win32event.CreateEvent(None, True, False, None)
        read_buf = win32file.AllocateReadBuffer(count - len(buf))
        try:
            try:
                rc, _ = win32file.ReadFile(handle, read_buf, ov)
                if rc not in (0, 997):  # 0=completed, 997=ERROR_IO_PENDING
                    return None
            except pywintypes.error as exc:
                if exc.winerror != 997:
                    return None
            got = win32file.GetOverlappedResult(handle, ov, True)
            if got <= 0:
                return None
            buf.extend(bytes(read_buf[:got]))
        except Exception:
            return None
        finally:
            ov.hEvent.Close()
    return bytes(buf)


def _write_pipe_all(handle, data: bytes) -> bool:
    import pywintypes
    import win32event
    import win32file

    ov = pywintypes.OVERLAPPED()
    ov.hEvent = win32event.CreateEvent(None, True, False, None)
    try:
        try:
            win32file.WriteFile(handle, data, ov)
        except pywintypes.error as exc:
            if exc.winerror != 997:
                return False
        win32file.GetOverlappedResult(handle, ov, True)
        return True
    except Exception:
        return False
    finally:
        ov.hEvent.Close()


class CodexHookServer:
    """In-process hook coordinator and Windows named-pipe server for Codex 26.1117+."""

    def __init__(
        self,
        *,
        pipe_name: str | None = None,
        codex_home: Path | None = None,
        pop_queued: Callable[[str], dict[str, Any] | None] | None = None,
        has_queued: Callable[[str], bool] | None = None,
        on_change: Callable[[str], None] | None = None,
        on_waiting: Callable[[str, dict[str, Any]], None] | None = None,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
        list_processes: Callable[[], list[dict[str, Any]]] | None = None,
        kill_process: Callable[[int], Any] | None = None,
        current_user: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        approval_timeout: float = APPROVAL_TIMEOUT_SECONDS,
        question_timeout: float = QUESTION_TIMEOUT_SECONDS,
        watch_window: float = WATCH_WINDOW_SECONDS,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.pipe_name = pipe_name or default_pipe_name()
        self.codex_home = Path(codex_home) if codex_home is not None else None
        self._pop_queued = pop_queued
        self._has_queued = has_queued
        self._on_change = on_change
        self._on_waiting = on_waiting
        self._on_progress = on_progress
        self._list_processes = list_processes
        self._kill_process = kill_process
        self._current_user = current_user
        self._clock = clock
        self.approval_timeout = approval_timeout
        self.question_timeout = question_timeout
        self.watch_window = watch_window
        self.log = log

        self.enabled = True
        self.auto_install_enabled = False
        self.installed_once = False

        self._lock = threading.RLock()
        self._last_view: dict[str, float] = {}
        self._phone_turns: set[str] = set()
        self._stop_flags: set[str] = set()
        self._active_commands: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, _PendingHook] = {}
        self._progress: dict[str, list[dict[str, Any]]] = {}
        self._waiters: dict[str, list[threading.Event]] = {}
        self._trust_cache: tuple[float, str] | None = None

        self._stop_event = threading.Event()
        self._win_stop_event = None
        self._accept_thread: threading.Thread | None = None

    def _log(self, text: str) -> None:
        if callable(self.log):
            try:
                self.log(text)
            except Exception:
                pass

    def _notify_change(self, tid: str) -> None:
        with self._lock:
            waiters = list(self._waiters.get(tid) or [])
        for ev in waiters:
            ev.set()
        if callable(self._on_change):
            try:
                self._on_change(tid)
            except Exception:
                pass

    # -- lifecycle & installation

    def start(self) -> None:
        with self._lock:
            if self._accept_thread is not None and self._accept_thread.is_alive():
                return
            self._stop_event.clear()
            import win32event
            self._win_stop_event = win32event.CreateEvent(None, True, False, None)
            self._accept_thread = threading.Thread(
                target=self._accept_loop, name="codex-hook-pipe-server", daemon=True
            )
            self._accept_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        with self._lock:
            for pending in list(self._pending.values()):
                pending.cancelled = True
                pending.done.set()
            for waiters in self._waiters.values():
                for ev in waiters:
                    ev.set()
        if self._win_stop_event is not None:
            try:
                import win32event
                win32event.SetEvent(self._win_stop_event)
            except Exception:
                pass
        thread = self._accept_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        if self._win_stop_event is not None:
            try:
                self._win_stop_event.Close()
            except Exception:
                pass
            self._win_stop_event = None

    def ensure_installed(self, exe_path: Path | str | None = None) -> bool:
        if not self.enabled:
            return False
        exe = Path(exe_path) if exe_path is not None else hook_executable()
        if exe is None or not exe.is_file():
            return False
        written = install_hooks(exe, codex_home=self.codex_home, log=self._log)
        self.installed_once = True
        self._trust_cache = None
        return written

    def trust_status(self, *, fresh: bool = False) -> str:
        if not self.enabled:
            return "not_installed"
        now = self._clock()
        if not fresh and self._trust_cache is not None and now - self._trust_cache[0] < TRUST_CACHE_TTL:
            return self._trust_cache[1]
        status = read_trust_status(codex_home=self.codex_home)
        self._trust_cache = (now, status)
        return status

    def is_trusted(self, *, fresh: bool = False) -> bool:
        return self.trust_status(fresh=fresh) == "enabled"

    # -- phone activity & observation

    def note_phone_viewing(self, tid: str) -> None:
        if tid:
            with self._lock:
                self._last_view[tid] = self._clock()

    def note_phone_turn(self, tid: str) -> None:
        if tid:
            with self._lock:
                self._phone_turns.add(tid)
                self._stop_flags.discard(tid)

    def is_watching(self, tid: str) -> bool:
        if not tid:
            return False
        now = self._clock()
        with self._lock:
            if tid in self._phone_turns:
                return True
            last = self._last_view.get(tid)
            return last is not None and (now - last) <= self.watch_window

    def wait_change(self, tid: str, timeout: float) -> bool:
        ev = threading.Event()
        with self._lock:
            self._waiters.setdefault(tid, []).append(ev)
        try:
            return ev.wait(timeout)
        finally:
            with self._lock:
                items = self._waiters.get(tid)
                if items and ev in items:
                    items.remove(ev)
                    if not items:
                        self._waiters.pop(tid, None)

    def latest_progress(self, tid: str) -> dict[str, Any] | None:
        with self._lock:
            items = self._progress.get(tid)
            return dict(items[-1]) if items else None

    def latest_progress_step(self, tid: str) -> str:
        latest = self.latest_progress(tid)
        if not latest or latest.get("event") == "Stop":
            return ""
        return str(latest.get("step") or "")

    def progress_history(self, tid: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._progress.get(tid, [])]

    def pending_cards(self, tid: str) -> list[dict[str, Any]]:
        with self._lock:
            out = []
            for item in self._pending.values():
                if item.tid == tid and not item.done.is_set():
                    out.append(dict(item.card))
            return out

    # -- phone actions (stop, approve, answer)

    def request_stop(self, tid: str, *, turn_id: str = "") -> dict[str, Any]:
        with self._lock:
            self._stop_flags.add(tid)
            active_cmd = dict(self._active_commands[tid]) if tid in self._active_commands else None
            # Unblock any waiting approval/question on this thread
            for pending in list(self._pending.values()):
                if pending.tid == tid and not pending.done.is_set():
                    pending.cancelled = True
                    pending.done.set()
        killed: list[int] = []
        if active_cmd and active_cmd.get("command"):
            killed = kill_running_command(
                active_cmd["command"],
                list_processes=self._list_processes,
                kill_process=self._kill_process,
                current_user=self._current_user,
                log=self._log,
            )
        self._notify_change(tid)
        return {
            "ok": True,
            "accepted": True,
            "turn_id": turn_id or (active_cmd.get("turn_id") if active_cmd else ""),
            "killed": bool(killed),
            "killed_pids": killed,
            "text": "已结束当前命令并请求停止" if killed else "已请求停止，等待当前步骤结束后停下",
        }

    def submit_answer(self, tid: str, body: dict[str, Any]) -> dict[str, Any]:
        qid = str(body.get("question_id") or "")
        rid = str(body.get("request_id") or "")
        answers = body.get("answers") or {}
        with self._lock:
            pending = self._pending.get(qid)
            if pending is None or pending.tid != tid or pending.done.is_set():
                raise codex_control.ControlError("这个问题已回答或已失效，请刷新", 409)
            expected_rev = pending.card.get("answer_revision") or _card_revision({})
            if body.get("answer_revision", expected_rev) != expected_rev:
                raise codex_control.ControlError("答案已在其他设备更新，请刷新核对后再修改", 409)

            if pending.kind == "approval":
                decision = self._parse_approval_decision(answers, body)
                pending.decision = decision
                pending.done.set()
                self._notify_change(tid)
                return {
                    "ok": True,
                    "accepted": True,
                    "delivery_state": "accepted",
                    "request_id": rid,
                    "text": "已允许本次操作" if decision == "allow" else "已拒绝本次操作",
                    "evidence": {"source": "codex_hook_approval"},
                }

            # request_user_input question card
            qs = pending.card.get("questions") or []
            if not isinstance(answers, dict) or set(answers.keys()) != {str(q["id"]) for q in qs}:
                raise codex_control.ControlError("请回答所有问题", 400)
            cleaned_answers: dict[str, list[str]] = {}
            for q in qs:
                vals = answers.get(str(q["id"]))
                if (
                    not isinstance(vals, list)
                    or not vals
                    or any(not isinstance(v, str) or not v.strip() or len(v) > 8000 for v in vals)
                ):
                    raise codex_control.ControlError("答案不能为空或过长", 400)
                if not q.get("isMultiple") and len(vals) != 1:
                    raise codex_control.ControlError("这个问题只允许选择一项", 400)
                cleaned_answers[str(q["id"])] = [v.strip() for v in vals]
            pending.answers = cleaned_answers
            pending.done.set()
        self._notify_change(tid)
        return {
            "ok": True,
            "accepted": True,
            "delivery_state": "accepted",
            "request_id": rid,
            "text": "答案已交给 Codex",
            "evidence": {"source": "codex_hook_answer"},
        }

    def _parse_approval_decision(self, answers: Any, body: dict[str, Any]) -> str:
        raw = None
        if isinstance(answers, dict) and "decision" in answers:
            vals = answers.get("decision")
            if isinstance(vals, list) and len(vals) == 1 and isinstance(vals[0], str):
                raw = vals[0].strip()
        elif isinstance(body.get("decision"), str):
            raw = body["decision"].strip()
        if raw in ("允许一次", "accept", "allow"):
            return "allow"
        if raw in ("拒绝", "decline", "deny"):
            return "deny"
        raise codex_control.ControlError("请选择「允许一次」或「拒绝」", 400)

    # -- hook event core

    def _record_progress(self, tid: str, event: str, payload: dict[str, Any]) -> None:
        tool_name = str(payload.get("tool_name") or "")
        tool_input = payload.get("tool_input")
        cmd = _command_text(tool_input)
        step = "" if event == "Stop" else _tool_step(tool_name, tool_input)
        rec = {
            "event": event,
            "tool": tool_name,
            "command": cmd[:80],
            "step": step,
            "turn_id": str(payload.get("turn_id") or ""),
            "time": int(time.time() * 1000),
        }
        with self._lock:
            items = self._progress.setdefault(tid, [])
            items.append(rec)
            if len(items) > MAX_PROGRESS_EVENTS:
                del items[:-MAX_PROGRESS_EVENTS]
        self._notify_change(tid)
        if callable(self._on_progress):
            try:
                self._on_progress(tid, rec)
            except Exception:
                pass

    def handle_event(self, event_name: str, payload: dict[str, Any] | None) -> str:
        """Process one Codex hook event and return the exact stdout string to print."""
        data = payload if isinstance(payload, dict) else {}
        event = str(event_name or data.get("hook_event_name") or "").strip()
        is_stop = event.lower() == "stop"

        if not self.enabled:
            return "{}" if is_stop else ""

        tid = str(data.get("session_id") or "").strip()
        if not tid:
            return "{}" if is_stop else ""

        # Fast path: thread is not watched, not stopped, and has no queued messages -> instant empty.
        watching = self.is_watching(tid)
        with self._lock:
            has_stop = tid in self._stop_flags
        has_queue = bool(callable(self._has_queued) and self._has_queued(tid))
        if not watching and not has_stop and not has_queue:
            return "{}" if is_stop else ""

        turn_id = str(data.get("turn_id") or "")
        if event == "PreToolUse":
            return self._handle_pre_tool_use(tid, turn_id, data, watching=watching)
        if event == "PermissionRequest":
            return self._handle_permission_request(tid, turn_id, data, watching=watching)
        if is_stop:
            return self._handle_stop(tid, data)
        return ""

    def _handle_pre_tool_use(self, tid: str, turn_id: str, data: dict[str, Any], *, watching: bool) -> str:
        tool_name = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input")

        if watching:
            self._record_progress(tid, "PreToolUse", data)

        with self._lock:
            if tid in self._stop_flags:
                return json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": STOP_DENY_REASON,
                    }
                }, ensure_ascii=False)

        # Intercept request_user_input when phone is watching
        if tool_name.rsplit(".", 1)[-1] == "request_user_input":
            if not watching:
                return ""
            questions = _normalize_questions(tool_input)
            if not questions:
                return ""
            req_id = secrets.token_hex(8)
            card_id = f"native:{turn_id or 'active'}:{req_id}"
            card = {
                "id": card_id,
                "request_id": req_id,
                "kind": "native",
                "turn_id": turn_id or None,
                "questions": questions,
                "status": "pending",
                "answer_revision": _card_revision({}),
                "editable": False,
            }
            pending = _PendingHook(tid=tid, kind="native", card=card)
            with self._lock:
                self._pending[card_id] = pending
            self._notify_change(tid)
            if callable(self._on_waiting):
                try:
                    self._on_waiting(tid, card)
                except Exception:
                    pass
            try:
                answered = pending.done.wait(self.question_timeout)
            finally:
                with self._lock:
                    self._pending.pop(card_id, None)
                self._notify_change(tid)
            if not answered or pending.cancelled or not pending.answers:
                return ""
            parts = []
            for q in questions:
                qid = str(q["id"])
                vals = pending.answers.get(qid) or []
                parts.append(f"{qid}={'、'.join(vals)}")
            reason = f"用户在手机上回答了：{'；'.join(parts)}。按这个继续，不要再问。"
            return json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }, ensure_ascii=False)

        # Record running command so immediate stop can locate its pwsh.exe under Full Access
        cmd = _command_text(tool_input)
        if cmd:
            with self._lock:
                self._active_commands[tid] = {
                    "command": cmd,
                    "started_at": self._clock(),
                    "turn_id": turn_id,
                    "permission_mode": str(data.get("permission_mode") or ""),
                }
        return ""

    def _handle_permission_request(self, tid: str, turn_id: str, data: dict[str, Any], *, watching: bool) -> str:
        if not watching:
            return ""
        with self._lock:
            if tid in self._stop_flags:
                return json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PermissionRequest",
                        "decision": {"behavior": "deny", "message": "用户在手机上已停止这一轮。"},
                    }
                }, ensure_ascii=False)
        tool_name = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input")
        approval_type, header, cmd, files, prompt = _describe_permission(tool_name, tool_input)
        req_id = secrets.token_hex(8)
        card_id = f"approval:{turn_id or 'active'}:{req_id}"
        card = {
            "id": card_id,
            "request_id": req_id,
            "kind": "approval",
            "turn_id": turn_id or None,
            "status": "pending",
            "approval_type": approval_type,
            "reason": "",
            "command": cmd,
            "cwd": str(data.get("cwd") or ""),
            "files": files,
            "answerable": True,
            "question": prompt,
            "choices": [{"id": "accept", "label": "允许一次"}, {"id": "decline", "label": "拒绝"}],
            "questions": [{
                "id": "decision",
                "header": header,
                "question": prompt,
                "options": [{"label": "允许一次"}, {"label": "拒绝"}],
                "isOther": False,
            }],
            "answer_revision": _card_revision({}),
            "editable": False,
        }
        pending = _PendingHook(tid=tid, kind="approval", card=card)
        with self._lock:
            self._pending[card_id] = pending
        self._notify_change(tid)
        if callable(self._on_waiting):
            try:
                self._on_waiting(tid, card)
            except Exception:
                pass
        try:
            answered = pending.done.wait(self.approval_timeout)
        finally:
            with self._lock:
                self._pending.pop(card_id, None)
            self._notify_change(tid)
        # Never auto-approve: only explicit "allow" or "deny" from phone produces a decision.
        if not answered or pending.cancelled or pending.decision not in ("allow", "deny"):
            return ""
        decision_body: dict[str, Any] = {"behavior": pending.decision}
        if pending.decision == "deny":
            decision_body["message"] = APPROVAL_DENY_MESSAGE
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": decision_body,
            }
        }, ensure_ascii=False)

    def _handle_stop(self, tid: str, data: dict[str, Any]) -> str:
        with self._lock:
            self._stop_flags.discard(tid)
            self._active_commands.pop(tid, None)
            self._phone_turns.discard(tid)
        self._record_progress(tid, "Stop", data)

        if data.get("stop_hook_active") is True:
            return "{}"
        if callable(self._pop_queued):
            try:
                next_item = self._pop_queued(tid)
            except Exception:
                next_item = None
            if isinstance(next_item, dict) and str(next_item.get("prompt") or "").strip():
                with self._lock:
                    self._phone_turns.add(tid)
                return json.dumps(
                    {"decision": "block", "reason": str(next_item["prompt"])},
                    ensure_ascii=False,
                )
        return "{}"

    # -- Windows named pipe accept & client threads

    def _accept_loop(self) -> None:
        import pywintypes
        import win32event
        import win32file
        import win32pipe

        try:
            sa = _current_user_security_attributes()
        except Exception as exc:
            self._log(f"Codex 钩子管道安全描述符创建失败：{exc}")
            return

        while not self._stop_event.is_set():
            try:
                handle = win32pipe.CreateNamedPipe(
                    self.pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED,
                    win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    65536,
                    65536,
                    0,
                    sa,
                )
            except Exception as exc:
                self._log(f"Codex 钩子管道创建失败：{exc}")
                self._stop_event.wait(1.0)
                continue

            ov = pywintypes.OVERLAPPED()
            ov.hEvent = win32event.CreateEvent(None, True, False, None)
            connected = False
            try:
                rc = win32pipe.ConnectNamedPipe(handle, ov)
                if rc in (0, 535):  # 0=completed, 535=ERROR_PIPE_CONNECTED
                    connected = True
                elif rc == 997:  # ERROR_IO_PENDING
                    wait_rc = win32event.WaitForMultipleObjects(
                        [ov.hEvent, self._win_stop_event], False, win32event.INFINITE
                    )
                    if wait_rc == win32event.WAIT_OBJECT_0:
                        connected = True
            except pywintypes.error as exc:
                if exc.winerror == 535:  # ERROR_PIPE_CONNECTED
                    connected = True
                elif exc.winerror == 997:  # ERROR_IO_PENDING
                    wait_rc = win32event.WaitForMultipleObjects(
                        [ov.hEvent, self._win_stop_event], False, win32event.INFINITE
                    )
                    if wait_rc == win32event.WAIT_OBJECT_0:
                        connected = True
                else:
                    connected = False
            finally:
                ov.hEvent.Close()

            if not connected or self._stop_event.is_set():
                try:
                    win32file.CloseHandle(handle)
                except Exception:
                    pass
                continue

            threading.Thread(
                target=self._serve_client, args=(handle,), name="codex-hook-client", daemon=True
            ).start()

    def _serve_client(self, handle) -> None:
        import win32file
        import win32pipe

        try:
            header = _read_pipe_exact(handle, 4)
            if not header:
                return
            length = struct.unpack("<I", header)[0]
            if not 0 < length <= MAX_FRAME_BYTES:
                return
            body = _read_pipe_exact(handle, length)
            if not body:
                return
            try:
                req = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeError):
                req = {}
            event = str(req.get("event") or "") if isinstance(req, dict) else ""
            payload = req.get("payload") if isinstance(req, dict) and isinstance(req.get("payload"), dict) else {}
            stdout_text = self.handle_event(event, payload)
            resp = json.dumps({"stdout": stdout_text}, ensure_ascii=False).encode("utf-8")
            _write_pipe_all(handle, struct.pack("<I", len(resp)) + resp)
            try:
                win32file.FlushFileBuffers(handle)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            try:
                win32pipe.DisconnectNamedPipe(handle)
            except Exception:
                pass
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
