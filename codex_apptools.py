"""Codex 26.1117+ local app-tools named-pipe client, route selector, queue and image store.

When Codex desktop removes \\\\.\\pipe\\codex-ipc (26.1117+), it still exposes a per-launch
\\\\.\\pipe\\codex-app-tools-<uuid> JSON-RPC 2.0 pipe (4-byte little-endian length prefix +
UTF-8 JSON, max 8 MB). This module:
- Detects which Codex route is available on this machine (legacy / apptools / none), cached 2 s.
- Verifies tools/list before first use; disables the new route with a plain Chinese reason if the
  required tool schemas changed.
- Sends messages (idle start or active steer), polls thread status (cross-checking the rollout
  file so a premature idle reading is not trusted blindly), persists Teleply's own queue, and
  stores phone images under <data_dir>/codex-images/<thread_id>/ for 7 days.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import struct
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app_paths import DATA
import chats
import codex_control
import composer_commands
import pc_clock

PIPE_DIR = "\\\\.\\pipe\\"
LEGACY_PIPE = "codex-ipc"
APPTOOLS_PREFIX = "codex-app-tools-"
MAX_FRAME_BYTES = 8 << 20
ROUTE_CACHE_TTL = 2.0
IMAGE_RETENTION_SECONDS = 7 * 86400
CODEX_IMAGE_MAX_SIDE = 1600
CODEX_IMAGE_FALLBACK_SIDE = 1280
CODEX_IMAGE_MAX_BYTES = 400 * 1024
_CODEX_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
DEFAULT_WAKE_DELAY = 2.0
STATUS_CACHE_TTL = 1.5
# 11-27 S4: the pre-send "is it running" reading may reuse a pipe status read this recently,
# but only while the rollout file has not changed since that reading.
SEND_STATUS_CACHE_TTL = 3.0
# 11-27 S5: accepted sends without delivery evidence are watched for this long, then left to the
# ordinary receipt path (someone reading the state) as before.
PENDING_DELIVERY_WINDOW = 15 * 60
PENDING_DELIVERY_POLL = 0.5

INCOMPATIBLE_REASON = "电脑上的 Codex 升级了，遥应暂时不能从手机发给 Codex"
NOT_RUNNING_REASON = "Codex 没在运行，请先在电脑上打开 Codex"
WINDOW_NOT_READY_REASON = "Codex 窗口没准备好，请先在电脑上打开 Codex 窗口再试"
PLAN_MODE_IGNORED_NOTE = "新版 Codex 从手机发的消息跟着电脑上当前的模式走，这次选的「计划模式」没有生效。"


def _is_plan_mode_requested(settings: Any) -> bool:
    return isinstance(settings, dict) and str(settings.get("mode") or "").strip().lower() == "plan"


def _log_request_tag(request_id: Any) -> str:
    """First 8 safe characters of a request id; the log carries no message text, command or file name."""
    return re.sub(r"[^0-9A-Za-z-]", "", str(request_id or ""))[:8]


# 11-27 S2: permission modes whose commands run in Codex's sandbox account. kill_running_command
# never touches that account, so the phone must not offer to end such a command.
SANDBOX_PERMISSION_MODES = {
    "default",
    "read-only",
    "readonly",
    "workspace-write",
    "workspacewrite",
    "plan",
    "acceptedits",
    "accept-edits",
    "on-request",
    "on-request-approval",
    "on-failure",
    "untrusted",
    "sandbox",
}


def is_full_access_permission(mode: Any) -> bool:
    """True unless the recorded mode is a known sandbox mode (a missing mode is not proven sandboxed)."""
    text = str(mode or "").strip().lower()
    return text not in SANDBOX_PERMISSION_MODES


def command_state(file_state: dict | None, hooks: Any, tid: str) -> dict[str, Any] | None:
    """The `command` field phones read (6.3): running command and whether this phone may end it."""
    command = (file_state or {}).get("command") if isinstance(file_state, dict) else None
    if not isinstance(command, dict) or not command.get("running"):
        return None
    can_kill = False
    if hooks is not None and getattr(hooks, "is_trusted", lambda: False)():
        active = getattr(hooks, "_active_commands", {}).get(tid) or {}
        can_kill = bool(active.get("command")) and is_full_access_permission(active.get("permission_mode"))
    return {
        "running": True,
        # 11-27: the phone counts this command's timer from here against its own now.
        "since_ms": pc_clock.to_true_ms(int(command.get("since_ms") or 0)),
        "can_kill": bool(can_kill),
    }


class _CallTimes:
    """Milliseconds spent inside each kind of pipe call during one request (11-27 S4)."""

    __slots__ = ("read", "send")

    def __init__(self) -> None:
        self.read = 0.0
        self.send = 0.0


_ROUTE_LOCK = threading.Lock()
_ROUTE_CACHE: tuple[float, str, str | None] | None = None
_DATA_DIR_OVERRIDE: Path | None = None
_DELIVERY_LINK_CACHE_LOCK = threading.Lock()
_DELIVERY_LINK_CACHE: dict[str, tuple[int, int, dict[str, str], dict[str, str]]] = {}
DELIVERY_LINKS_DIRNAME = "codex-delivery-links"
MAX_DELIVERY_LINKS_PER_THREAD = 500


def set_default_data_dir_override(path: Path | None) -> None:
    """Test helper: redirect default codex_apptools data directory away from repo/user data."""
    global _DATA_DIR_OVERRIDE
    _DATA_DIR_OVERRIDE = Path(path) if path is not None else None
    with _DELIVERY_LINK_CACHE_LOCK:
        _DELIVERY_LINK_CACHE.clear()


def default_data_dir() -> Path:
    return _DATA_DIR_OVERRIDE if _DATA_DIR_OVERRIDE is not None else DATA


class AppToolsError(codex_control.ControlError):
    """Error raised on the app-tools route; carries not_submitted so phone keeps draft safely."""

    def __init__(self, message: str, status: int = 409, code: str = "", *, not_submitted: bool = False):
        super().__init__(message, status=status, code=code)
        self.not_submitted = not_submitted


def _list_pipes() -> list[str]:
    try:
        return os.listdir(PIPE_DIR)
    except OSError:
        return []


def reset_route_cache() -> None:
    global _ROUTE_CACHE
    with _ROUTE_LOCK:
        _ROUTE_CACHE = None


def detect_route(*, force: bool = False, clock: Callable[[], float] = time.monotonic) -> tuple[str, str | None]:
    """Return (route, pipe_name): ('legacy', 'codex-ipc'), ('apptools', 'codex-app-tools-...'), or ('none', None)."""
    global _ROUTE_CACHE
    now = clock()
    with _ROUTE_LOCK:
        if not force and _ROUTE_CACHE is not None and now - _ROUTE_CACHE[0] < ROUTE_CACHE_TTL:
            return _ROUTE_CACHE[1], _ROUTE_CACHE[2]
    names = _list_pipes()
    legacy = next((n for n in names if n.lower() == LEGACY_PIPE), None)
    if legacy:
        result: tuple[str, str | None] = ("legacy", legacy)
    else:
        apptools = sorted(n for n in names if n.lower().startswith(APPTOOLS_PREFIX))
        if apptools:
            result = ("apptools", apptools[0])
        else:
            result = ("none", None)
    with _ROUTE_LOCK:
        _ROUTE_CACHE = (clock(), result[0], result[1])
    return result


def current_route(*, force: bool = False) -> str:
    return detect_route(force=force)[0]


def translate_error(raw: str, *, default_not_submitted: bool = False) -> AppToolsError:
    """Turn a raw Codex app-tools error string into plain Chinese for the phone."""
    text = str(raw or "").strip()
    low = text.lower()
    if "no ready app window supports app tools" in low:
        return AppToolsError(WINDOW_NOT_READY_REASON, 409, code="window_not_ready", not_submitted=True)
    if any(k in low for k in ("thread not found", "unknown thread", "conversation not found", "not found")):
        return AppToolsError("Codex 找不到这个对话，可能已删除或尚未加载", 404, code="thread_not_found", not_submitted=True)
    if any(k in low for k in ("unauthorized", "not authorized", "permission denied", "access denied")):
        return AppToolsError("电脑上的 Codex 拒绝了本机连接，遥应暂时无法发消息", 403, code="unauthorized", not_submitted=True)
    if "timeout" in low or "timed out" in low:
        return AppToolsError("Codex 响应超时，结果未确认；不会自动重试", 504, code="timeout", not_submitted=False)
    if any(k in low for k in ("pipe", "eof", "closed", "broken", "file not found")):
        return AppToolsError(NOT_RUNNING_REASON, 409, code="codex_not_running", not_submitted=True)
    short = text.splitlines()[0][:160] if text else "未知错误"
    return AppToolsError("Codex 未完成操作：" + short, 409, code="apptools_error", not_submitted=default_not_submitted)


def pack_frame(payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise AppToolsError("请求过大，超过 8 MB 限制", 413, code="frame_too_large", not_submitted=True)
    return struct.pack("<I", len(raw)) + raw


def unpack_frame_size(header: bytes) -> int:
    if len(header) != 4:
        raise AppToolsError("Codex 管道连接已断开", 409, code="pipe_closed")
    size = struct.unpack("<I", header)[0]
    if not 0 < size <= MAX_FRAME_BYTES:
        raise AppToolsError("Codex 返回的数据帧格式异常", 502, code="invalid_frame")
    return size


def is_matching_jsonrpc_response(frame: Any, req_id: Any) -> bool:
    """Return True only when [frame] is a JSON-RPC response whose id matches [req_id]."""
    if not isinstance(frame, dict):
        return False
    if "id" not in frame or frame.get("id") != req_id:
        return False
    return "result" in frame or "error" in frame


class WindowsPipeTransport:
    """Overlapped Windows named-pipe transport for one JSON-RPC request/response cycle."""

    def __init__(self, pipe_path: str, timeout: float = 30.0) -> None:
        import pywintypes
        import win32con
        import win32event
        import win32file

        self._pywintypes = pywintypes
        self._win32event = win32event
        self._win32file = win32file
        self.pipe_path = pipe_path
        self.timeout = timeout
        import win32pipe
        deadline = time.monotonic() + min(timeout, 3.0)
        while True:
            try:
                self.handle = win32file.CreateFile(
                    pipe_path,
                    win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                    0,
                    None,
                    win32con.OPEN_EXISTING,
                    win32con.FILE_FLAG_OVERLAPPED,
                    None,
                )
                break
            except pywintypes.error as exc:
                if exc.winerror == 231 and time.monotonic() < deadline:  # ERROR_PIPE_BUSY
                    try:
                        win32pipe.WaitNamedPipe(pipe_path, max(50, int((deadline - time.monotonic()) * 1000)))
                        continue
                    except Exception:
                        pass
                raise AppToolsError(NOT_RUNNING_REASON, 409, code="pipe_open_failed", not_submitted=True) from exc
            except Exception as exc:
                raise AppToolsError(NOT_RUNNING_REASON, 409, code="pipe_open_failed", not_submitted=True) from exc

    def _wait_overlapped(self, ov, timeout_ms: int, label: str) -> int:
        rc = self._win32event.WaitForSingleObject(ov.hEvent, max(1, int(timeout_ms)))
        if rc == self._win32event.WAIT_TIMEOUT:
            self.close()
            raise AppToolsError(f"Codex {label}超时，结果未确认；不会自动重试", 504, code="timeout", not_submitted=False)
        return self._win32file.GetOverlappedResult(self.handle, ov, True)

    def _write_all(self, data: bytes, timeout: float) -> None:
        ov = self._pywintypes.OVERLAPPED()
        ov.hEvent = self._win32event.CreateEvent(None, True, False, None)
        try:
            try:
                self._win32file.WriteFile(self.handle, data, ov)
            except self._pywintypes.error as exc:
                if exc.winerror != 997:  # ERROR_IO_PENDING
                    raise AppToolsError("Codex 管道连接已断开", 409, code="pipe_closed") from exc
            self._wait_overlapped(ov, max(100, int(timeout * 1000)), "请求发送")
        finally:
            ov.hEvent.Close()

    def _read_exact(self, n: int, deadline: float) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            rem = deadline - time.monotonic()
            if rem <= 0:
                self.close()
                raise AppToolsError("Codex 响应超时，结果未确认；不会自动重试", 504, code="timeout", not_submitted=False)
            ov = self._pywintypes.OVERLAPPED()
            ov.hEvent = self._win32event.CreateEvent(None, True, False, None)
            read_buf = self._win32file.AllocateReadBuffer(n - len(buf))
            try:
                try:
                    rc, _ = self._win32file.ReadFile(self.handle, read_buf, ov)
                    if rc not in (0, 997):
                        raise AppToolsError("Codex 管道连接已断开", 409, code="pipe_closed")
                except self._pywintypes.error as exc:
                    if exc.winerror != 997:
                        raise AppToolsError("Codex 管道连接已断开", 409, code="pipe_closed") from exc
                got = self._wait_overlapped(ov, max(1, int(rem * 1000)), "响应读取")
                if got <= 0:
                    raise AppToolsError("Codex 管道连接已断开", 409, code="pipe_closed")
                buf.extend(bytes(read_buf[:got]))
            finally:
                ov.hEvent.Close()
        return bytes(buf)

    def _read_frame(self, deadline: float) -> dict:
        size = unpack_frame_size(self._read_exact(4, deadline))
        body = self._read_exact(size, deadline)
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise AppToolsError("Codex 返回了无法解析的响应", 502, code="invalid_json") from exc
        if not isinstance(data, dict):
            raise AppToolsError("Codex 返回了格式异常的响应", 502, code="invalid_json")
        return data

    def request(self, payload: dict, timeout: float = 30.0) -> dict:
        frame = pack_frame(payload)
        self._write_all(frame, min(timeout, 15.0))
        expected_id = payload.get("id")
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                self.close()
                raise AppToolsError("Codex 响应超时，结果未确认；不会自动重试", 504, code="timeout", not_submitted=False)
            data = self._read_frame(deadline)
            if expected_id is None or is_matching_jsonrpc_response(data, expected_id):
                return data
            # Skip notifications or responses for other request IDs and keep reading until match or timeout.

    def close(self) -> None:
        if getattr(self, "handle", None) is not None:
            try:
                import ctypes
                ctypes.windll.kernel32.CancelIoEx(ctypes.c_void_p(int(self.handle)), None)
            except Exception:
                pass
            try:
                self._win32file.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


def verify_tools_schema(tools: Any) -> tuple[bool, str]:
    """Check that send_message_to_thread and read_thread exist and their required inputs haven't changed."""
    if not isinstance(tools, list):
        return False, "tools/list 返回不是列表"
    by_name: dict[str, dict] = {}
    for item in tools:
        if not isinstance(item, dict):
            continue
        ns = item.get("namespace")
        if ns not in (None, "", "codex_app"):
            continue
        name = item.get("name")
        if isinstance(name, str):
            by_name[name] = item

    def check_tool(name: str, must_have: set[str], allowed_required: set[str]) -> str | None:
        tool = by_name.get(name)
        if tool is None:
            return f"缺少工具 {name}"
        schema = tool.get("inputSchema") or tool.get("input_schema")
        if not isinstance(schema, dict):
            return f"{name} 缺少参数定义"
        req = schema.get("required")
        if not isinstance(req, list) or not all(isinstance(v, str) for v in req):
            return f"{name} 必填参数格式异常"
        req_set = set(req)
        if not must_have <= req_set:
            return f"{name} 缺少必填项 {sorted(must_have - req_set)}"
        extra = req_set - allowed_required
        if extra:
            return f"{name} 新增未知必填项 {sorted(extra)}"
        return None

    for name, must, allowed in (
        ("send_message_to_thread", {"threadId", "prompt"}, {"threadId", "prompt", "hostId"}),
        ("read_thread", {"threadId"}, {"threadId", "hostId"}),
    ):
        err = check_tool(name, must, allowed)
        if err:
            return False, err
    return True, ""


class AppToolsClient:
    """JSON-RPC 2.0 client over Codex's codex-app-tools-<uuid> pipe."""

    def __init__(
        self,
        *,
        transport_factory: Callable[[str, float], Any] | None = None,
        opener: Callable[[str], Any] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        wake_delay: float = DEFAULT_WAKE_DELAY,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._transport_factory = transport_factory or (lambda path, timeout: WindowsPipeTransport(path, timeout))
        self._opener = opener or os.startfile
        self._sleep = sleep_fn
        self._wake_delay = wake_delay
        self.log = log
        self._lock = threading.RLock()
        self._req_id = 0
        self._verified_pipe: str | None = None
        self._disabled_pipe: str | None = None
        self._disabled_detail: str = ""

    def _log(self, text: str) -> None:
        if callable(self.log):
            try:
                self.log(text)
            except Exception:
                pass

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _resolve_pipe(self, *, force: bool = False) -> str:
        route, pipe_name = detect_route(force=force)
        if route != "apptools" or not pipe_name:
            raise AppToolsError(NOT_RUNNING_REASON, 409, code="codex_not_running", not_submitted=True)
        return pipe_name

    def _rpc_once(self, pipe_name: str, method: str, params: dict, timeout: float = 30.0) -> dict:
        transport = self._transport_factory(PIPE_DIR + pipe_name, timeout)
        try:
            req_id = self._next_id()
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            resp = transport.request(payload, timeout=timeout)
            if not is_matching_jsonrpc_response(resp, req_id):
                raise AppToolsError("Codex 响应超时，结果未确认；不会自动重试", 504, code="timeout", not_submitted=False)
            return resp
        finally:
            try:
                transport.close()
            except Exception:
                pass

    def ensure_verified(self, pipe_name: str) -> None:
        if self._verified_pipe == pipe_name:
            return
        if self._disabled_pipe == pipe_name:
            raise AppToolsError(INCOMPATIBLE_REASON, 409, code="protocol_incompatible", not_submitted=True)
        resp = self._rpc_once(pipe_name, "tools/list", {"threadStartKind": "default"}, timeout=15.0)
        if "error" in resp:
            err = resp["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise translate_error(str(msg), default_not_submitted=True)
        tools = (resp.get("result") or {}).get("tools")
        ok, detail = verify_tools_schema(tools)
        if not ok:
            self._disabled_pipe = pipe_name
            self._disabled_detail = detail
            self._log(f"Codex app-tools 工具表校验未通过（{detail}），已停用新路线")
            raise AppToolsError(INCOMPATIBLE_REASON, 409, code="protocol_incompatible", not_submitted=True)
        self._verified_pipe = pipe_name
        self._disabled_pipe = None
        self._disabled_detail = ""

    def _call_tool_raw(
        self,
        pipe_name: str,
        tool: str,
        arguments: dict,
        thread_id: str,
        turn_id: str,
        timeout: float = 30.0,
    ) -> dict:
        params = {
            "tool": tool,
            "namespace": "codex_app",
            "arguments": arguments,
            "threadId": thread_id,
            "callerSource": "codex",
            "hostId": "local",
            "callId": f"teleply-{uuid.uuid4()}",
            "turnId": turn_id,
        }
        resp = self._rpc_once(pipe_name, "tools/call", params, timeout=timeout)
        if "error" in resp:
            err = resp["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise translate_error(str(msg), default_not_submitted=True)
        result = resp.get("result")
        if not isinstance(result, dict):
            raise AppToolsError("Codex 返回了无效的工具响应", 502, code="invalid_result")
        if result.get("success") is False:
            texts = [str(i.get("text") or "") for i in result.get("contentItems") or [] if isinstance(i, dict)]
            detail = " ".join(t for t in texts if t).strip() or str(result.get("error") or "调用失败")
            raise translate_error(detail, default_not_submitted=True)
        return result

    def call_tool(
        self,
        tool: str,
        arguments: dict,
        *,
        thread_id: str,
        turn_id: str,
        timeout: float = 30.0,
        allow_wake: bool = True,
    ) -> dict:
        with self._lock:
            pipe_name = self._resolve_pipe()
            retried_pipe = False
            woke_window = False
            while True:
                try:
                    self.ensure_verified(pipe_name)
                    return self._call_tool_raw(pipe_name, tool, arguments, thread_id, turn_id, timeout=timeout)
                except AppToolsError as exc:
                    if exc.code == "pipe_open_failed" and not retried_pipe:
                        retried_pipe = True
                        self._verified_pipe = None
                        reset_route_cache()
                        pipe_name = self._resolve_pipe(force=True)
                        continue
                    if exc.code == "window_not_ready" and allow_wake and not woke_window and thread_id:
                        woke_window = True
                        self._log(f"Codex 窗口未准备好，尝试用 codex://threads/{thread_id[:8]} 唤起窗口后重试")
                        try:
                            self._opener(f"codex://threads/{thread_id}")
                        except Exception:
                            raise exc
                        self._sleep(self._wake_delay)
                        continue
                    raise

    def read_thread(
        self,
        thread_id: str,
        *,
        include_turns: bool = False,
        turn_id: str | None = None,
        timeout: float = 15.0,
    ) -> dict:
        args: dict[str, Any] = {"threadId": thread_id, "hostId": "local", "includeTurns": bool(include_turns)}
        result = self.call_tool(
            "read_thread",
            args,
            thread_id=thread_id,
            turn_id=turn_id or f"teleply-read-{uuid.uuid4()}",
            timeout=timeout,
        )
        for item in result.get("contentItems") or []:
            if isinstance(item, dict) and item.get("type") == "inputText" and isinstance(item.get("text"), str):
                try:
                    parsed = json.loads(item["text"])
                    if isinstance(parsed, dict):
                        return parsed
                except ValueError:
                    continue
        return {}

    def send_message_to_thread(
        self,
        thread_id: str,
        prompt: str,
        *,
        turn_id: str,
        model: str | None = None,
        thinking: str | None = None,
        timeout: float = 30.0,
    ) -> dict:
        args: dict[str, Any] = {"threadId": thread_id, "hostId": "local", "prompt": prompt}
        if model:
            args["model"] = model
        if thinking:
            args["thinking"] = thinking
        return self.call_tool(
            "send_message_to_thread",
            args,
            thread_id=thread_id,
            turn_id=turn_id,
            timeout=timeout,
        )


# ---------------------------------------------------------------- transcript helpers


def latest_turn_state(path: Path | None) -> dict[str, Any]:
    """Read tail of a Codex rollout JSONL to find latest turn id, running status, timestamps, step and command."""
    info: dict[str, Any] = {
        "turn_id": None,
        "running": None,
        "turn_started": 0,
        "turn_ended": 0,
        "step": "",
        "recent_turns": [],
        "stale": False,
        "command": None,
    }
    if path is None or not path.is_file():
        return info
    try:
        st = path.stat()
        lines, _ = chats.read_tail(path, 256 << 10)
    except OSError:
        return info

    def unix(ts: str) -> int:
        try:
            return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
        except (ValueError, AttributeError, TypeError):
            return 0

    turns: dict[str, str] = {}
    turn_order: list[str] = []
    latest_ts = ""
    # 11-27 S2: the last exec-like call in the tail that has no matching output yet.
    open_command: dict[str, Any] | None = None

    def open_call(call_id: Any, name: Any, argument: Any, ts: str) -> None:
        nonlocal open_command
        step = chats._step_of("codex", str(name or ""), str(argument or ""))
        if step != "run":
            return
        open_command = {
            "call_id": str(call_id or ""),
            "name": str(name or ""),
            "since_ms": unix(ts) * 1000,
        }

    def close_call(call_id: Any) -> None:
        nonlocal open_command
        if open_command is None:
            return
        if not call_id or not open_command.get("call_id") or str(call_id) == str(open_command["call_id"]):
            open_command = None

    for raw in lines:
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        ts = rec.get("timestamp") or ""
        if ts:
            latest_ts = ts
        kind = rec.get("type")
        payload = rec.get("payload") or {}
        if kind == "turn_context":
            tid = payload.get("turn_id")
            if tid:
                info["turn_id"] = tid
        elif kind == "event_msg":
            ev = payload.get("type")
            tid = payload.get("turn_id")
            if ev == "task_started":
                if tid:
                    info["turn_id"] = tid
                    if tid not in turns:
                        turn_order.append(tid)
                    turns[tid] = "inProgress"
                info["running"] = True
                info["turn_started"] = unix(ts)
                info["turn_ended"] = 0
                info["step"] = ""
                open_command = None
            elif ev in ("task_complete", "turn_aborted"):
                status = "interrupted" if ev == "turn_aborted" else "completed"
                key = tid or info["turn_id"]
                if key:
                    info["turn_id"] = key
                    if key not in turns:
                        turn_order.append(key)
                    turns[key] = status
                info["running"] = False
                info["turn_ended"] = unix(ts)
                info["step"] = ""
                open_command = None
            elif ev == "item_completed":
                item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
                item_type = str(item.get("type") or "")
                if item_type in ("FunctionCall", "CustomToolCall"):
                    open_call(
                        item.get("call_id") or item.get("id"),
                        item.get("name"),
                        item.get("input") if "input" in item else item.get("arguments"),
                        ts,
                    )
                elif item_type in ("FunctionCallOutput", "CustomToolCallOutput"):
                    close_call(item.get("call_id") or item.get("id"))
                elif item_type == "CommandExecution":
                    # Codex's own record of a finished command (exit code and output included).
                    close_call(None)
        elif kind == "response_item":
            item_type = str(payload.get("type") or "")
            if item_type in ("function_call", "custom_tool_call"):
                step = chats._step_of("codex", str(payload.get("name") or ""), str(payload.get("input") or ""))
                if step:
                    info["step"] = step
                open_call(
                    payload.get("call_id") or payload.get("id"),
                    payload.get("name"),
                    payload.get("input") if "input" in payload else payload.get("arguments"),
                    ts,
                )
            elif item_type in ("function_call_output", "custom_tool_call_output"):
                close_call(payload.get("call_id") or payload.get("id"))

    if info["running"] is True:
        last_at = unix(latest_ts) or int(st.st_mtime)
        if time.time() - last_at >= chats.STALE_SECONDS:
            info["stale"] = True
    info["recent_turns"] = [{"id": tid, "status": turns[tid]} for tid in turn_order[-4:]]
    info["command"] = (
        {"running": True, "since_ms": open_command["since_ms"], "name": open_command["name"]}
        if open_command
        else None
    )
    return info


def find_delegation_delivery(
    path: Path | None,
    thread_id: str,
    prompt: str,
    *,
    exclude_message_ids: set[str] | None = None,
) -> dict | None:
    """Find a matching self-delegation or Stop-hook <hook_prompt> entry in the transcript tail."""
    if path is None or not path.is_file():
        return None
    want_raw = chats.norm(prompt)
    cleaned_prompt, _ = chats._extract_codex_images(prompt)
    want_clean = chats.norm(cleaned_prompt)
    if not want_raw and not want_clean:
        return None
    try:
        lines, _ = chats.read_tail(path, 2 << 20)
    except OSError:
        return None
    excluded = exclude_message_ids or set()
    fallback_hook_prompt: dict | None = None
    for raw in reversed(lines):
        if b"codex_delegation" not in raw and b"hook_prompt" not in raw and b"HookPrompt" not in raw:
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if rec.get("type") != "event_msg":
            continue
        payload = rec.get("payload") or {}
        kind = payload.get("type")
        if kind == "item_completed":
            item = payload.get("item") or {}
            t = item.get("type")
            if t == "FunctionCallOutput":
                delegated = chats._codex_delegation(item, thread_id=thread_id)
                if delegated and not delegated.get("origin"):
                    mid = delegated.get("source_id")
                    if mid and mid in excluded:
                        continue
                    raw_input = chats._codex_delegation_raw_text(item)
                    if (want_raw and raw_input and chats.norm(raw_input) == want_raw) or (
                        want_clean and chats.norm(delegated.get("text") or "") == want_clean
                    ):
                        return {
                            "source": "conversation_record",
                            "message_id": mid,
                            "time": rec.get("timestamp"),
                        }
            elif t == "UserMessage":
                mid = item.get("id")
                if mid and mid in excluded:
                    continue
                raw_text, is_hook = chats._unwrap_hook_prompt(chats._join_text(item.get("content")))
                if is_hook:
                    cleaned, _ = chats._extract_codex_images(raw_text)
                    if (want_raw and chats.norm(raw_text) == want_raw) or (
                        want_clean and chats.norm(cleaned) == want_clean
                    ):
                        return {
                            "source": "conversation_record",
                            "message_id": mid,
                            "time": rec.get("timestamp"),
                        }
            elif t == "HookPrompt" and fallback_hook_prompt is None:
                mid = item.get("id")
                if mid and mid in excluded:
                    continue
                raw_text = chats._hook_prompt_item_text(item)
                cleaned, _ = chats._extract_codex_images(raw_text)
                if (want_raw and chats.norm(raw_text) == want_raw) or (
                    want_clean and chats.norm(cleaned) == want_clean
                ):
                    fallback_hook_prompt = {
                        "source": "conversation_record",
                        "message_id": mid,
                        "time": rec.get("timestamp"),
                    }
        elif kind == "user_message":
            mid = payload.get("id")
            if mid and mid in excluded:
                continue
            raw_text, is_hook = chats._unwrap_hook_prompt(payload.get("message") or "")
            if is_hook:
                cleaned, _ = chats._extract_codex_images(raw_text)
                if (want_raw and chats.norm(raw_text) == want_raw) or (
                    want_clean and chats.norm(cleaned) == want_clean
                ):
                    return {
                        "source": "conversation_record",
                        "message_id": mid,
                        "time": rec.get("timestamp"),
                    }
    return fallback_hook_prompt


# ---------------------------------------------------------------- Teleply local queue


class LocalQueueStore:
    """Per-thread JSON queue stored under <data_dir>/codex-queues/<tid>.json (atomic writes, survives restart)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    def _file(self, tid: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", tid)
        return self.root / f"{safe}.json"

    def list_items(self, tid: str) -> list[dict]:
        with self._lock:
            path = self._file(tid)
            if not path.is_file():
                return []
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [v for v in data if isinstance(v, dict) and v.get("id")]
            except (OSError, ValueError):
                return []
            return []

    def _save(self, tid: str, items: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._file(tid)
        if not items:
            path.unlink(missing_ok=True)
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def enqueue(self, tid: str, entry: dict) -> dict:
        with self._lock:
            items = self.list_items(tid)
            if any(v["id"] == entry["id"] for v in items):
                return entry
            items.append(entry)
            self._save(tid, items)
            return entry

    def pop_first(self, tid: str) -> dict | None:
        with self._lock:
            items = self.list_items(tid)
            if not items:
                return None
            first = items.pop(0)
            self._save(tid, items)
            return first

    def remove(self, tid: str, mid: str) -> dict | None:
        with self._lock:
            items = self.list_items(tid)
            target = next((v for v in items if v["id"] == mid), None)
            if target is None:
                return None
            remaining = [v for v in items if v["id"] != mid]
            self._save(tid, remaining)
            return target

    def has_any(self, tid: str) -> bool:
        return bool(self.list_items(tid))

    def queued_threads(self) -> list[str]:
        with self._lock:
            if not self.root.is_dir():
                return []
            out = []
            for p in self.root.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, list) and data:
                        tid = data[0].get("thread_id") or p.stem
                        out.append(str(tid))
                except (OSError, ValueError):
                    continue
            return out


# ---------------------------------------------------------------- image file storage (7-day retention)


def _image_has_transparency(img) -> bool:
    """Return True only when the image actually contains non-opaque pixels."""
    if "A" in img.getbands():
        lo, _ = img.getchannel("A").getextrema()
        return lo < 255
    if "transparency" in img.info:
        rgba = img.convert("RGBA")
        lo, _ = rgba.getchannel("A").getextrema()
        return lo < 255
    return False


def _resize_to_max_side(img, max_side: int, resampling):
    if max(img.width, img.height) <= max_side:
        return img
    resized = img.copy()
    resized.thumbnail((max_side, max_side), resampling)
    return resized


def _encode_jpeg_under_limit(img, resampling) -> bytes:
    rgb = img.convert("RGB")
    rgb.info.clear()
    best: bytes | None = None
    attempts = (
        (CODEX_IMAGE_MAX_SIDE, (85, 75, 65, 55, 45, 35)),
        (CODEX_IMAGE_FALLBACK_SIDE, (85, 75, 65, 55, 45, 35, 25)),
        (1024, (65, 50, 35, 25)),
        (800, (55, 40, 25)),
        (640, (45, 30, 20)),
    )
    for max_side, qualities in attempts:
        scaled = _resize_to_max_side(rgb, max_side, resampling)
        for q in qualities:
            buf = io.BytesIO()
            scaled.save(buf, format="JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if best is None or len(data) < len(best):
                best = data
            if len(data) <= CODEX_IMAGE_MAX_BYTES:
                return data
    return best or b""


def _encode_png_under_limit(img, resampling, quantize_method, dither_method) -> bytes:
    rgba = img.convert("RGBA")
    rgba.info.clear()
    best: bytes | None = None
    for max_side in (CODEX_IMAGE_MAX_SIDE, CODEX_IMAGE_FALLBACK_SIDE, 1024, 800, 640, 480):
        scaled = _resize_to_max_side(rgba, max_side, resampling)
        buf = io.BytesIO()
        scaled.save(buf, format="PNG", optimize=True, compress_level=9)
        data = buf.getvalue()
        if best is None or len(data) < len(best):
            best = data
        if len(data) <= CODEX_IMAGE_MAX_BYTES:
            return data
        for colors in (256, 128, 64):
            try:
                quantized = scaled.quantize(colors=colors, method=quantize_method, dither=dither_method)
                buf = io.BytesIO()
                quantized.save(buf, format="PNG", optimize=True, compress_level=9)
                data = buf.getvalue()
                if len(data) < len(best):
                    best = data
                if len(data) <= CODEX_IMAGE_MAX_BYTES:
                    return data
            except Exception:
                continue
    return best or b""


def _prepare_codex_image(src: Path) -> tuple[bytes | None, str]:
    """Return (compressed_bytes_or_None_for_verbatim_copy, file_extension) for Codex's image viewer.

    Small images already within 1600 px and 400 KB (without EXIF rotation) are copied verbatim.
    Larger images are EXIF-transposed, resized to <=1600 px (falling back to 1280 px if needed),
    and encoded as JPEG (opaque) or PNG (transparent) at <=400 KB.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    src_size = src.stat().st_size
    orig_ext = src.suffix.lower() if src.suffix.lower() in _CODEX_IMAGE_SUFFIXES else ".png"
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    quantize_method = getattr(Image, "Quantize", Image).FASTOCTREE
    dither_method = getattr(Image, "Dither", Image).FLOYDSTEINBERG

    try:
        with Image.open(src) as source:
            try:
                exif = source.getexif()
                orientation = exif.get(274, 1) if exif else 1
            except Exception:
                orientation = 1
            if (
                orientation in (1, None)
                and max(source.width, source.height) <= CODEX_IMAGE_MAX_SIDE
                and src_size <= CODEX_IMAGE_MAX_BYTES
            ):
                return None, orig_ext
            transposed = ImageOps.exif_transpose(source)
            transposed.load()
            has_alpha = _image_has_transparency(transposed)
    except (UnidentifiedImageError, OSError, ValueError):
        return None, orig_ext

    if has_alpha:
        return _encode_png_under_limit(transposed, resampling, quantize_method, dither_method), ".png"
    return _encode_jpeg_under_limit(transposed, resampling), ".jpg"


def store_codex_image(images_root: Path, tid: str, meta: dict, *, now: float | None = None) -> Path:
    """Save an uploaded attachment under <images_root>/<tid>/<id>.<ext> (compressed for Codex) and prune >7d files."""
    cleanup_codex_images(images_root, now=now)
    safe_tid = re.sub(r"[^A-Za-z0-9._-]", "_", tid)
    dest_dir = Path(images_root) / safe_tid
    dest_dir.mkdir(parents=True, exist_ok=True)
    ident = str(meta.get("id") or uuid.uuid4().hex)
    for ext in _CODEX_IMAGE_SUFFIXES:
        existing = dest_dir / f"{ident}{ext}"
        if existing.is_file():
            return existing
    src = Path(meta["path"])
    compressed, ext = _prepare_codex_image(src)
    dest = dest_dir / f"{ident}{ext}"
    tmp = dest_dir / f"{ident}{ext}.tmp"
    if compressed is None:
        shutil.copy2(src, tmp)
    else:
        tmp.write_bytes(compressed)
    os.replace(tmp, dest)
    return dest


def cleanup_codex_images(images_root: Path, *, now: float | None = None) -> None:
    """Remove image files older than 7 days under <data_dir>/codex-images."""
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


# ---------------------------------------------------------------- message source_id <-> request_id links


def _delivery_link_file(root: Path, tid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", tid)
    return Path(root) / f"{safe}.json"


def _read_delivery_links_cached(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        with _DELIVERY_LINK_CACHE_LOCK:
            _DELIVERY_LINK_CACHE.pop(key, None)
        return {}, {}
    with _DELIVERY_LINK_CACHE_LOCK:
        cached = _DELIVERY_LINK_CACHE.get(key)
        if cached and cached[0] == st.st_size and cached[1] == st.st_mtime_ns:
            return dict(cached[2]), dict(cached[3])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    by_source: dict[str, str] = {}
    by_request: dict[str, str] = {}
    if isinstance(raw, dict):
        src_map = raw.get("by_source")
        if isinstance(src_map, dict):
            for sid, rid in src_map.items():
                if isinstance(sid, str) and sid and isinstance(rid, str) and rid:
                    by_source[sid] = rid
                    by_request[rid] = sid
        req_map = raw.get("by_request")
        if isinstance(req_map, dict):
            for rid, sid in req_map.items():
                if isinstance(rid, str) and rid and isinstance(sid, str) and sid:
                    by_request[rid] = sid
                    by_source.setdefault(sid, rid)
    with _DELIVERY_LINK_CACHE_LOCK:
        _DELIVERY_LINK_CACHE[key] = (st.st_size, st.st_mtime_ns, dict(by_source), dict(by_request))
        if len(_DELIVERY_LINK_CACHE) > 64:
            _DELIVERY_LINK_CACHE.pop(next(iter(_DELIVERY_LINK_CACHE)))
    return by_source, by_request


def read_source_request_map(tid: str, *, data_dir: Path | None = None) -> dict[str, str]:
    """Read persisted {source_id: request_id} mapping for [tid], surviving restarts."""
    if not tid:
        return {}
    base = Path(data_dir) if data_dir is not None else default_data_dir()
    by_source, _ = _read_delivery_links_cached(_delivery_link_file(base / DELIVERY_LINKS_DIRNAME, tid))
    return by_source


def read_request_source_map(tid: str, *, data_dir: Path | None = None) -> dict[str, str]:
    """Read persisted {request_id: source_id} mapping for [tid], surviving restarts."""
    if not tid:
        return {}
    base = Path(data_dir) if data_dir is not None else default_data_dir()
    _, by_request = _read_delivery_links_cached(_delivery_link_file(base / DELIVERY_LINKS_DIRNAME, tid))
    return by_request


class DeliveryLinkStore:
    """Persists message source_id <-> request_id pairs under <data_dir>/codex-delivery-links/<tid>.json."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    def _file(self, tid: str) -> Path:
        return _delivery_link_file(self.root, tid)

    def source_to_request(self, tid: str) -> dict[str, str]:
        with self._lock:
            by_source, _ = _read_delivery_links_cached(self._file(tid))
            return by_source

    def request_to_source(self, tid: str) -> dict[str, str]:
        with self._lock:
            _, by_request = _read_delivery_links_cached(self._file(tid))
            return by_request

    def record(self, tid: str, source_id: str, request_id: str) -> bool:
        sid = str(source_id or "").strip()
        rid = str(request_id or "").strip()
        if not tid or not sid or not rid:
            return False
        with self._lock:
            path = self._file(tid)
            by_source, by_request = _read_delivery_links_cached(path)
            if by_source.get(sid) == rid and by_request.get(rid) == sid:
                return False
            # Keep one-to-one mapping cleanly updated
            old_sid = by_request.get(rid)
            if old_sid and old_sid != sid and by_source.get(old_sid) == rid:
                by_source.pop(old_sid, None)
            old_rid = by_source.get(sid)
            if old_rid and old_rid != rid and by_request.get(old_rid) == sid:
                by_request.pop(old_rid, None)
            by_source[sid] = rid
            by_request[rid] = sid
            while len(by_source) > MAX_DELIVERY_LINKS_PER_THREAD:
                oldest_sid = next(iter(by_source))
                oldest_rid = by_source.pop(oldest_sid)
                if by_request.get(oldest_rid) == oldest_sid:
                    by_request.pop(oldest_rid, None)
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"by_source": by_source, "by_request": by_request}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, path)
            with _DELIVERY_LINK_CACHE_LOCK:
                _DELIVERY_LINK_CACHE.pop(str(path), None)
            return True


# ---------------------------------------------------------------- new-route controller


class AppToolsBridge:
    """High-level new-route controller matching codex_control.Bridge's public shape (codex.v1)."""

    def __init__(
        self,
        legacy_bridge: codex_control.Bridge,
        *,
        client: AppToolsClient | None = None,
        data_dir: Path | None = None,
        hooks: Any = None,
        clock: Callable[[], float] = time.monotonic,
        enable_background_drain: bool = True,
        enable_background_watch: bool = True,
    ) -> None:
        self.legacy = legacy_bridge
        self.client = client or AppToolsClient(log=getattr(legacy_bridge, "log", None))
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.queues = LocalQueueStore(self.data_dir / "codex-queues")
        self.images_root = self.data_dir / "codex-images"
        self.delivery_links = DeliveryLinkStore(self.data_dir / DELIVERY_LINKS_DIRNAME)
        self.hooks = hooks
        self._clock = clock
        self._lock = threading.RLock()
        self._status_cache: dict[str, tuple[float, dict, tuple[int, int] | None]] = {}
        self._reconcile_seen: dict[tuple[str, str], tuple[int, int]] = {}
        self._stop = threading.Event()
        self._drain_wake = threading.Event()
        self._drain_thread: threading.Thread | None = None
        self._enable_background_drain = enable_background_drain
        self._enable_background_watch = enable_background_watch
        # 11-27 S5: conversations with accepted sends that have no delivery evidence yet.
        self._pending_deliveries: dict[str, dict[str, Any]] = {}
        self._reconcile_wake = threading.Event()
        self._reconcile_thread: threading.Thread | None = None

    def _log(self, text: str) -> None:
        log = getattr(self.legacy, "log", None)
        if callable(log):
            try:
                log(text)
            except Exception:
                pass

    def _ensure_drainer(self) -> None:
        if not self._enable_background_drain:
            return
        with self._lock:
            if self._drain_thread is not None and self._drain_thread.is_alive():
                self._drain_wake.set()
                return
            self._drain_thread = threading.Thread(
                target=self._drain_loop, name="codex-apptools-queue-drain", daemon=True
            )
            self._drain_thread.start()
            self._drain_wake.set()

    def _drain_loop(self) -> None:
        while not self._stop.is_set():
            tids = self.queues.queued_threads()
            if not tids:
                self._drain_wake.wait(30.0)
                self._drain_wake.clear()
                continue
            if self.hooks is not None and getattr(self.hooks, "is_trusted", lambda: False)():
                # When hooks are active, Stop hook dispatches queued items immediately.
                self._drain_wake.wait(5.0)
                self._drain_wake.clear()
                continue
            for tid in tids:
                if self._stop.is_set():
                    break
                try:
                    self.drain_if_idle(tid)
                except Exception:
                    pass
            self._stop.wait(2.5)

    def close(self) -> None:
        self._stop.set()
        self._drain_wake.set()
        self._reconcile_wake.set()

    def _thread_file(self, tid: str) -> Path | None:
        try:
            item = chats.find("codex", tid)
        except Exception:
            return None
        path = Path(item["path"]) if item.get("path") else None
        return path if path is not None and path.is_file() else None

    # -- 11-27 S4: pipe call timing and the pre-send status reading

    def _file_signature(self, path: Path | None) -> tuple[int, int] | None:
        """(size, mtime_ns) of the rollout file, or None when it cannot be read."""
        if path is None:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def _timed_read_thread(self, tid: str, *, turn_id: str | None, times: _CallTimes) -> dict:
        started = time.monotonic()
        try:
            return self.client.read_thread(tid, include_turns=False, turn_id=turn_id)
        finally:
            times.read += time.monotonic() - started

    def _timed_send_message(
        self,
        tid: str,
        prompt: str,
        *,
        turn_id: str,
        model: str | None,
        thinking: str | None,
        times: _CallTimes,
    ) -> dict:
        started = time.monotonic()
        try:
            return self.client.send_message_to_thread(
                tid, prompt, turn_id=turn_id, model=model, thinking=thinking
            )
        finally:
            times.send += time.monotonic() - started

    def _log_request_timing(self, request_id: Any, started: float, times: _CallTimes) -> None:
        """One line with numbers only: how long this request spent in each kind of pipe call."""
        total_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        read_ms = max(0, int(round(times.read * 1000)))
        send_ms = max(0, int(round(times.send * 1000)))
        other_ms = max(0, total_ms - read_ms - send_ms)
        self._log(
            f"codex timing request={_log_request_tag(request_id)} "
            f"read_ms={read_ms} send_ms={send_ms} other_ms={other_ms} total_ms={total_ms}"
        )

    def _cached_running_for_send(
        self, tid: str, path: Path | None, intent: str
    ) -> bool | None:
        """A pipe reading from the last 3 s, still valid because the rollout file has not changed.

        Returns None when there is no trustworthy cached answer and the pipe must be asked again.
        """
        cached = self._status_cache.get(tid)
        if not cached or len(cached) < 3:
            return None
        when, result, signature = cached[0], cached[1], cached[2]
        if self._clock() - when > SEND_STATUS_CACHE_TTL:
            return None
        current = self._file_signature(path)
        if signature is None or current != signature:
            return None
        running = bool(result.get("running"))
        # A queue decision must never send instead of queue: a cached "not running" is only a
        # reading, so ask the pipe again. A cached "running" can only queue, which is the safe side.
        if intent == "queue" and not running:
            return None
        return running

    def _running_for_send(
        self,
        tid: str,
        path: Path | None,
        file_state: dict,
        intent: str,
        times: _CallTimes,
    ) -> bool:
        cached = self._cached_running_for_send(tid, path, intent)
        if cached is not None:
            return cached
        thread_data = self._timed_read_thread(tid, turn_id=file_state.get("turn_id"), times=times)
        running, _, _ = self._parse_pipe_status(thread_data, file_state)
        return running

    # -- 11-27 S5: mark accepted sends delivered when their rollout entry appears

    def _watch_delivery(self, tid: str, signature: tuple[int, int] | None = None) -> None:
        """Watch one conversation's rollout for an accepted send still lacking delivery evidence.

        One shared thread handles every conversation (no thread per conversation). The signature is
        the file state *before* the send, so any later write is noticed; None means "from now on".
        """
        if not tid:
            return
        with self._lock:
            if signature is None:
                signature = self._file_signature(self._thread_file(tid))
            self._pending_deliveries[tid] = {
                "deadline": self._clock() + PENDING_DELIVERY_WINDOW,
                "signature": signature,
            }
            thread = self._reconcile_thread
            if self._enable_background_watch and (thread is None or not thread.is_alive()):
                self._reconcile_thread = threading.Thread(
                    target=self._reconcile_loop, name="codex-apptools-delivered", daemon=True
                )
                self._reconcile_thread.start()
        self._reconcile_wake.set()

    def _reconcile_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._reconcile_pending_once()
            except Exception:
                pass
            self._reconcile_wake.wait(PENDING_DELIVERY_POLL)
            self._reconcile_wake.clear()

    def _reconcile_pending_once(self) -> int:
        """One poll: for each watched conversation whose file changed, reconcile its deliveries.

        Returns how many still lack evidence. Does nothing at all when nothing is being watched.
        """
        now = self._clock()
        with self._lock:
            pending = list(self._pending_deliveries.items())
            if not pending:
                return 0
            for tid, entry in pending:
                if now >= float(entry.get("deadline") or 0):
                    self._pending_deliveries.pop(tid, None)
            pending = list(self._pending_deliveries.items())
        for tid, entry in pending:
            if self._stop.is_set():
                break
            signature = self._file_signature(self._thread_file(tid))
            if signature is None or signature == entry.get("signature"):
                continue
            entry["signature"] = signature  # record first: a failed reconcile must not spin
            try:
                remaining = self.reconcile_deliveries(tid)
            except Exception:
                continue
            if remaining == 0:
                with self._lock:
                    self._pending_deliveries.pop(tid, None)
        with self._lock:
            return len(self._pending_deliveries)

    def _read_settings(self, path: Path | None) -> dict:
        model, effort = None, None
        if path is not None and path.is_file():
            try:
                rt = chats.runtime_info("codex", path)
                model = rt.get("model")
                effort = rt.get("effort")
            except Exception:
                pass
        models = codex_control.catalog().get("models") or []
        if not model and models:
            model = models[0]["id"]
            effort = effort or models[0].get("default_effort")
        return {"model": model, "effort": effort, "mode": "default", "service_tier": None}

    def _validate_settings(self, wanted: dict | None, current: dict) -> dict:
        if not wanted:
            return dict(current)
        desired = codex_control.normalize_settings({**current, **wanted})
        models = codex_control.catalog().get("models") or []
        if models and desired.get("model"):
            model = next((m for m in models if m["id"] == desired["model"]), None)
            if not model:
                raise AppToolsError(
                    f"电脑当前模型目录中没有 {desired['model']}，尚未发送消息；请刷新模型列表后重试",
                    409,
                    code="unknown_model",
                    not_submitted=True,
                )
            if desired.get("effort") and model.get("efforts") and desired["effort"] not in model["efforts"]:
                raise AppToolsError(
                    f"{desired['model']} 不支持推理强度 {desired['effort']}，尚未发送消息；可选：{', '.join(model['efforts'])}",
                    409,
                    code="invalid_effort",
                    not_submitted=True,
                )
        return desired

    def _parse_pipe_status(self, thread_data: dict, file_state: dict) -> tuple[bool, list[str], str]:
        """Combine read_thread status with rollout file state.

        Returns (running, active_flags, kind) where kind is 'idle' | 'active' | 'unknown'.
        Never trusts a single idle reading blindly if the rollout file's latest turn is still open.
        """
        thread = thread_data.get("thread") or {}
        st = thread.get("status")
        st_type = st.get("type") if isinstance(st, dict) else (st if isinstance(st, str) else "")
        flags = list(st.get("activeFlags") or []) if isinstance(st, dict) else []
        if st_type == "active":
            return True, flags, "active"
        if st_type == "systemError":
            return False, [], "unknown"
        if st_type in ("idle", "notLoaded"):
            # Cross-check with rollout file: a premature idle (seen up to 40 s early in live tests)
            # must not falsely report idle while the rollout's latest turn has not completed.
            if file_state.get("running") is True and not file_state.get("stale"):
                return True, flags, "active"
            return False, [], "idle"
        # Fallback to file state if status is missing
        if file_state.get("running") is True and not file_state.get("stale"):
            return True, flags, "active"
        return False, [], "unknown"

    def status(self, tid: str, fresh: bool = False) -> dict:
        if self.hooks is not None:
            try:
                self.hooks.note_phone_viewing(tid)
            except Exception:
                pass
        now = self._clock()
        if not fresh:
            cached = self._status_cache.get(tid)
            if cached and now - cached[0] < STATUS_CACHE_TTL:
                return dict(cached[1])
        try:
            item = chats.find("codex", tid)
            path = Path(item["path"]) if item.get("path") else None
            # 11-27 S4: the signature is taken before the file state and pipe reading, so any later
            # change invalidates this cached answer instead of being hidden by a newer signature.
            status_sig = self._file_signature(path)
            file_state = latest_turn_state(path)
            thread_data = self.client.read_thread(tid, include_turns=False, turn_id=file_state.get("turn_id"))
            running, active_flags, kind = self._parse_pipe_status(thread_data, file_state)

            # Polling queue drain when hooks aren't handling Stop
            if not running and self.queues.has_any(tid):
                if self.hooks is None or not getattr(self.hooks, "is_trusted", lambda: False)():
                    if self.drain_if_idle(tid, already_checked_idle=True):
                        running = True
                        kind = "active"

            settings = self._read_settings(path)
            active_turn_id = file_state.get("turn_id") if running else None
            questions = self._build_questions(tid, active_turn_id, active_flags)
            queued = [
                {"id": v["id"], "text": v.get("text", ""), "status": v.get("status", "queued")}
                for v in self.queues.list_items(tid)
            ]
            step = file_state.get("step", "") if running else ""
            if self.hooks is not None and running:
                hook_step = self.hooks.latest_progress_step(tid)
                if hook_step:
                    step = hook_step
            hook_notice = self._hook_notice()
            result: dict[str, Any] = {
                "available": True,
                "route": "apptools",
                "settings": settings,
                "running": running,
                "status": "waiting" if any(q.get("status") == "pending" for q in questions) else ("running" if running else kind),
                "active_turn_id": active_turn_id,
                # 11-27: the turn's times as the phone's clock reads them; the value above is the record's own.
                "turn_started": pc_clock.to_true_seconds(file_state.get("turn_started", 0)),
                "turn_ended": pc_clock.to_true_seconds(0 if running else file_state.get("turn_ended", 0)),
                "step": step,
                "compacting": False,
                "compact_started": 0,
                "recent_turns": file_state.get("recent_turns") or [],
                "questions": questions,
                "plan": None,
                "catalog": codex_control.catalog(),
                "queued": queued,
                "queue_available": True,
                "images": self.message_images(tid),
                "command": command_state(file_state, self.hooks, tid),
                "observed_at": int(time.time() * 1000),
            }
            if hook_notice:
                result["hook_notice"] = hook_notice
                result["hook_status"] = self.hooks.trust_status() if self.hooks is not None else "not_installed"
            elif self.hooks is not None:
                result["hook_status"] = self.hooks.trust_status()
            if self.hooks is not None:
                prog = self.hooks.latest_progress(tid)
                if prog:
                    result["hook_progress"] = prog
            self._status_cache[tid] = (self._clock(), result, status_sig)
            return dict(result)
        except (codex_control.ControlError, chats.ChatError, OSError) as exc:
            return {
                "available": False,
                "route": "apptools",
                "reason": str(exc),
                "questions": [],
                "plan": None,
                "catalog": codex_control.catalog(),
                "queued": [
                    {"id": v["id"], "text": v.get("text", ""), "status": v.get("status", "queued")}
                    for v in self.queues.list_items(tid)
                ],
                "queue_available": True,
                "images": self.message_images(tid),
            }

    def _hook_notice(self) -> str:
        if self.hooks is None:
            return ""
        status = self.hooks.trust_status()
        if status == "pending_trust":
            return "在 Codex 设置 → Hooks 里打开并信任 3 个遥应钩子，手机才能批准、停止、回答"
        return ""

    def _build_questions(self, tid: str, active_turn_id: str | None, active_flags: list[str]) -> list[dict]:
        cards: list[dict] = []
        if self.hooks is not None:
            cards.extend(self.hooks.pending_cards(tid))
        has_approval_card = any(c.get("kind") == "approval" and c.get("status") == "pending" for c in cards)
        has_question_card = any(c.get("kind") == "native" and c.get("status") == "pending" for c in cards)
        notice = self._hook_notice()
        suffix = f"（{notice}）" if notice else ""
        if "waitingOnApproval" in active_flags and not has_approval_card:
            cards.append({
                "id": f"approval:{active_turn_id or 'active'}:desktop",
                "request_id": "desktop-approval",
                "kind": "approval",
                "turn_id": active_turn_id,
                "status": "pending",
                "approval_type": "other",
                "reason": "",
                "command": "",
                "cwd": "",
                "files": [],
                "answerable": False,
                "question": "在等你在电脑上批准" + suffix,
                "choices": [],
            })
        if "waitingOnUserInput" in active_flags and not has_question_card:
            cards.append({
                "id": f"native:{active_turn_id or 'active'}:desktop",
                "request_id": "desktop-question",
                "kind": "approval",
                "turn_id": active_turn_id,
                "status": "pending",
                "approval_type": "other",
                "reason": "",
                "command": "",
                "cwd": "",
                "files": [],
                "answerable": False,
                "question": "在等你在电脑上回答" + suffix,
                "choices": [],
            })
        for q in cards:
            q.setdefault(
                "answer_revision",
                hashlib.sha256(json.dumps(q.get("answers", {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],
            )
            q.setdefault("editable", False)
        return cards

    def _build_prompt(self, tid: str, text: str, image_metas: list[dict], references: list | None) -> str:
        body_text = text
        if references:
            if self.legacy.references is None:
                raise AppToolsError("引用服务不可用，请重新打开页面", 503, code="references_unavailable", not_submitted=True)
            body_text, _ = self.legacy.references.compose("codex", tid, body_text, references, native_skills=False)
        image_lines: list[str] = []
        for meta in image_metas:
            saved = store_codex_image(self.images_root, tid, meta)
            image_lines.append(f"[附图] {saved}（请先用看图工具打开这张图片）")
        if image_lines:
            joined = "\n".join(image_lines)
            body_text = f"{body_text}\n\n{joined}".strip() if body_text else joined
        return body_text

    def send(self, body: dict, timing=None) -> dict:
        tid = str(body.get("id", ""))
        rid = str(body.get("request_id", ""))
        text = str(body.get("text", "")).strip()
        ids = body.get("attachments") or []
        references = body.get("references") or []

        command = composer_commands.parse(text)
        if command and command[0] == "/compact" and not ids and not references and not body.get("plan_id"):
            raise AppToolsError(
                "新版 Codex 暂不支持从手机执行 /compact，请等它自动压缩或在电脑上输入 /compact",
                400,
                code="unsupported_on_route",
                not_submitted=True,
            )

        if not isinstance(ids, list) or len(ids) > 5 or len(set(ids)) != len(ids):
            raise AppToolsError("每条消息最多 5 张不同图片", 400, code="invalid_attachments", not_submitted=True)
        files = any(isinstance(v, dict) and v.get("kind") in ("file", "folder") for v in references)
        if (not text and not ids and not files) or len(text) > chats.MAX_TEXT:
            raise AppToolsError("请填写消息或添加图片，文字不能超过 20000 字", 400, code="invalid_text", not_submitted=True)

        intent = body.get("intent", "auto")
        if intent not in ("auto", "steer", "queue"):
            raise AppToolsError("无效的发送方式", 400, code="invalid_intent", not_submitted=True)

        started = time.monotonic()
        times = _CallTimes()
        try:
            with self._lock:
                prior = self.receipt(tid, rid)
                if prior["state"] != "unknown":
                    return self.legacy._begin(rid, tid, body)

                item = chats.find("codex", tid)
                path = Path(item["path"]) if item.get("path") else None
                file_state = latest_turn_state(path)
                running = self._running_for_send(tid, path, file_state, intent, times)

                current_settings = self._read_settings(path)
                desired = self._validate_settings(body.get("settings"), current_settings)

                images = [self.legacy.attachment(ident, tid) for ident in ids]
                if sum(v["original_size"] for v in images) > 50 << 20:
                    raise AppToolsError("图片合计不能超过 50 MB", 413, code="images_too_large", not_submitted=True)

                prompt = self._build_prompt(tid, text, images, references)
                if not prompt:
                    raise AppToolsError("请填写消息或添加图片", 400, code="empty_prompt", not_submitted=True)

                # Only send model/thinking when explicitly selected or known
                wanted = body.get("settings") or {}
                plan_mode_ignored = _is_plan_mode_requested(wanted)
                send_model = desired.get("model") if wanted.get("model") else None
                send_thinking = desired.get("effort") if wanted.get("effort") else None

                self.legacy._begin(rid, tid, body)
                for v in images:
                    v["used"] = True
                    self.legacy._write_meta(v)

                if intent == "queue" and running:
                    entry = {
                        "id": rid,
                        "thread_id": tid,
                        "text": text or (f"{len(images)} 张图片" if images else "附带的内容"),
                        "prompt": prompt,
                        "model": send_model,
                        "thinking": send_thinking,
                        "attachments": list(ids),
                        "created_at": int(time.time() * 1000),
                        "status": "queued",
                    }
                    self.queues.enqueue(tid, entry)
                    result = {
                        "ok": True,
                        "accepted": True,
                        "delivery_state": "queued",
                        "request_id": rid,
                        "queue_message_id": rid,
                        "intent": "queue",
                        "text": f"已排队。{PLAN_MODE_IGNORED_NOTE}" if plan_mode_ignored else "已排队",
                        "compiled_prompt": prompt,
                        "evidence": {"source": "teleply_queue"},
                    }
                    self.legacy._finish(rid, result)
                    self._status_cache.pop(tid, None)
                    self._ensure_drainer()
                    return result

                turn_id = file_state.get("turn_id") or f"teleply-turn-{uuid.uuid4()}"
                delivery_sig = self._file_signature(path)
                try:
                    self._timed_send_message(
                        tid,
                        prompt,
                        turn_id=turn_id,
                        model=send_model,
                        thinking=send_thinking,
                        times=times,
                    )
                except AppToolsError as exc:
                    if exc.not_submitted:
                        self.legacy._finish(
                            rid,
                            {"ok": False, "delivery_state": "rejected", "request_id": rid, "text": str(exc)},
                        )
                    raise

                if self.hooks is not None:
                    try:
                        self.hooks.note_phone_turn(tid)
                    except Exception:
                        pass

                actual_intent = "steer" if running else "start"
                response = {
                    "ok": True,
                    "accepted": True,
                    "delivery_state": "accepted",
                    "intent": actual_intent,
                    "request_id": rid,
                    "text": f"已交给 Codex。{PLAN_MODE_IGNORED_NOTE}" if plan_mode_ignored else "已交给 Codex",
                    "settings": desired,
                    "compiled_prompt": prompt,
                    "evidence": {"source": "app_tools_ack"},
                }
                self.legacy._finish(rid, response)
                self._status_cache.pop(tid, None)
                self._watch_delivery(tid, delivery_sig)
                return response
        finally:
            self._log_request_timing(rid, started, times)

    def drain_if_idle(self, tid: str, *, already_checked_idle: bool = False) -> bool:
        """If thread is confirmed idle and has queued items, dispatch the first item via app-tools."""
        with self._lock:
            items = self.queues.list_items(tid)
            if not items:
                return False
            started = time.monotonic()
            times = _CallTimes()
            first: dict | None = None
            try:
                path = self._thread_file(tid)
                file_state = latest_turn_state(path)
                if not already_checked_idle:
                    thread_data = self._timed_read_thread(
                        tid, turn_id=file_state.get("turn_id"), times=times
                    )
                    running, _, kind = self._parse_pipe_status(thread_data, file_state)
                    if running or kind != "idle":
                        return False
                first = self.queues.pop_first(tid)
                if first is None:
                    return False
                turn_id = file_state.get("turn_id") or f"teleply-turn-{uuid.uuid4()}"
                delivery_sig = self._file_signature(path)
                try:
                    self._timed_send_message(
                        tid,
                        first["prompt"],
                        turn_id=turn_id,
                        model=first.get("model"),
                        thinking=first.get("thinking"),
                        times=times,
                    )
                except Exception:
                    # Re-insert at front so nothing is lost on transient error
                    rest = self.queues.list_items(tid)
                    self.queues._save(tid, [first] + rest)
                    return False
                if self.hooks is not None:
                    try:
                        self.hooks.note_phone_turn(tid)
                    except Exception:
                        pass
                self.legacy._finish(
                    first["id"],
                    {
                        "ok": True,
                        "accepted": True,
                        "delivery_state": "accepted",
                        "intent": "start",
                        "request_id": first["id"],
                        "text": "已交给 Codex",
                        "compiled_prompt": first["prompt"],
                        "evidence": {"source": "app_tools_queue_dispatch"},
                    },
                )
                self._status_cache.pop(tid, None)
                self._watch_delivery(tid, delivery_sig)
                return True
            finally:
                # One line per queued message that was actually taken out to be dispatched.
                if first is not None:
                    self._log_request_timing(first["id"], started, times)

    def pop_queued_for_stop_hook(self, tid: str) -> dict | None:
        """Called by the Stop hook to hand off the next queued prompt directly into the continuing turn."""
        with self._lock:
            first = self.queues.pop_first(tid)
            if first is None:
                return None
            self.legacy._finish(
                first["id"],
                {
                    "ok": True,
                    "accepted": True,
                    "delivery_state": "accepted",
                    "intent": "queue_hook",
                    "request_id": first["id"],
                    "text": "已交给 Codex",
                    "compiled_prompt": first["prompt"],
                    "evidence": {"source": "stop_hook_handoff"},
                },
            )
            self._status_cache.pop(tid, None)
            self._watch_delivery(tid)
            return first

    def queue_action(self, body: dict) -> dict:
        tid = str(body.get("id", ""))
        rid = str(body.get("request_id", ""))
        mid = str(body.get("message_id", "") or body.get("item_id", ""))
        raw_action = body.get("action")
        action_map = {"steer": "promote", "remove": "cancel", "delete": "cancel"}
        action = action_map.get(raw_action, raw_action)
        if action not in ("promote", "cancel"):
            raise AppToolsError("无效队列操作", 400, code="invalid_queue_action", not_submitted=True)

        started = time.monotonic()
        times = _CallTimes()
        try:
            with self._lock:
                if rid and self.receipt(tid, rid)["state"] != "unknown":
                    return self.legacy._begin(rid, tid, body)
                removed = self.queues.remove(tid, mid)
                if removed is None:
                    raise AppToolsError("消息已离开队列或正在发送，请刷新核对", 409, code="queue_item_missing", not_submitted=True)
                if rid:
                    self.legacy._begin(rid, tid, body)
                cancelled = {"ok": True, "delivery_state": "cancelled", "request_id": mid, "text": "已取消排队"}
                if action == "cancel":
                    self.legacy._finish(mid, cancelled)
                    result = {**cancelled, "request_id": rid or mid, "queue_message_id": mid}
                    if rid:
                        self.legacy._finish(rid, result)
                    self._status_cache.pop(tid, None)
                    return result

                # promote -> send immediately (steers if active, starts turn if idle)
                path = self._thread_file(tid)
                file_state = latest_turn_state(path)
                turn_id = file_state.get("turn_id") or f"teleply-turn-{uuid.uuid4()}"
                delivery_sig = self._file_signature(path)
                try:
                    self._timed_send_message(
                        tid,
                        removed["prompt"],
                        turn_id=turn_id,
                        model=removed.get("model"),
                        thinking=removed.get("thinking"),
                        times=times,
                    )
                except AppToolsError as exc:
                    if exc.not_submitted:
                        # Put back at front of queue so user doesn't lose the message
                        rest = self.queues.list_items(tid)
                        self.queues._save(tid, [removed] + rest)
                        if rid:
                            self.legacy._finish(rid, {"ok": False, "delivery_state": "rejected", "request_id": rid, "text": str(exc)})
                    raise
                result = {
                    "ok": True,
                    "accepted": True,
                    "delivery_state": "accepted",
                    "request_id": rid or mid,
                    "client_id": mid,
                    "intent": "steer",
                    "text": "已交给 Codex",
                    "compiled_prompt": removed["prompt"],
                    "evidence": {"source": "app_tools_promote"},
                }
                self.legacy._finish(mid, {**result, "request_id": mid})
                if rid and rid != mid:
                    self.legacy._finish(rid, result)
                self._status_cache.pop(tid, None)
                self._watch_delivery(tid, delivery_sig)
                return result
        finally:
            self._log_request_timing(rid or mid, started, times)

    def stop_turn(self, body: dict) -> dict:
        tid = str(body.get("id", ""))
        if self.hooks is None or not getattr(self.hooks, "is_trusted", lambda: False)():
            raise AppToolsError(
                "请在电脑上停止（在 Codex 设置 → Hooks 信任遥应钩子后，才能从手机停止）",
                409,
                code="hooks_not_trusted",
                not_submitted=True,
            )
        result = self.hooks.request_stop(tid, turn_id=str(body.get("turn_id") or body.get("expected_turn") or ""))
        self._status_cache.pop(tid, None)
        return result

    def answer(self, body: dict) -> dict:
        tid = str(body.get("id", ""))
        if self.hooks is None or not getattr(self.hooks, "is_trusted", lambda: False)():
            raise AppToolsError(
                "请在电脑上批准或回答（在 Codex 设置 → Hooks 信任遥应钩子后，才能从手机处理）",
                409,
                code="hooks_not_trusted",
                not_submitted=True,
            )
        result = self.hooks.submit_answer(tid, body)
        self._status_cache.pop(tid, None)
        return result

    def confirm_open(self, tid: str, seconds: float = 5.0, step: float = 0.5) -> dict:
        deadline = self._clock() + seconds
        last_exc: Exception | None = None
        while True:
            try:
                self.client.read_thread(tid, include_turns=False)
                title = chats.find("codex", tid)["title"]
                return {"ok": True, "text": f"电脑上已打开「{title}」，可以发了"}
            except Exception as exc:
                last_exc = exc
                if self._clock() >= deadline:
                    break
                time.sleep(step)
        raise codex_control.CodexNotTaken(str(last_exc or WINDOW_NOT_READY_REASON))

    def _link_delivery(self, tid: str, rid: str, evidence: dict | None) -> None:
        msg_id = (evidence or {}).get("message_id")
        if msg_id and self.delivery_links.record(tid, str(msg_id), rid):
            self._status_cache.pop(tid, None)

    def _claimed_sources_excluding(self, tid: str, rid: str) -> set[str]:
        by_source = self.delivery_links.source_to_request(tid)
        return {sid for sid, owner in by_source.items() if owner != rid}

    def reconcile_deliveries(self, tid: str) -> int:
        """Match recently accepted/dispatched new-route sends to their transcript source_id and persist links.

        Returns how many accepted sends still have no delivery evidence (used by the S5 watcher).
        """
        if not tid or not (self.legacy.data_root / "delivery.sqlite").exists():
            return 0
        with self._lock:
            with self.legacy._db() as con:
                rows = con.execute(
                    "SELECT id,state,result,data FROM deliveries WHERE thread=? AND state IN ('dispatching','accepted','queued') ORDER BY created DESC LIMIT 30",
                    (tid,),
                ).fetchall()
            if not rows:
                return 0
            queued_ids = {v["id"] for v in self.queues.list_items(tid)}
            by_req = self.delivery_links.request_to_source(tid)
            claimed = set(self.delivery_links.source_to_request(tid).keys())
            pending: list[tuple[str, dict, dict, str]] = []
            for rid, status, raw_result, raw_data in reversed(rows):
                if rid in queued_ids:
                    continue
                try:
                    result = json.loads(raw_result or "{}")
                    body = json.loads(raw_data or "{}")
                except ValueError:
                    continue
                if body.get("question_id") or body.get("action"):
                    continue
                ev_mid = (result.get("evidence") or {}).get("message_id")
                if ev_mid:
                    if by_req.get(rid) != ev_mid:
                        self._link_delivery(tid, rid, result.get("evidence"))
                        by_req[rid] = str(ev_mid)
                        claimed.add(str(ev_mid))
                    continue
                if rid in by_req:
                    continue
                prompt = result.get("compiled_prompt") or body.get("text") or ""
                if prompt:
                    pending.append((rid, result, body, prompt))
            if not pending:
                return 0
            path = self._thread_file(tid)
            if path is None:
                return 0
            try:
                st = path.stat()
                file_sig = (st.st_size, st.st_mtime_ns)
            except OSError:
                return 0
            remaining = 0
            for rid, result, _body, prompt in pending:
                key = (tid, rid)
                if self._reconcile_seen.get(key) == file_sig:
                    remaining += 1
                    continue
                evidence = find_delegation_delivery(path, tid, prompt, exclude_message_ids=claimed)
                if evidence:
                    updated = {
                        **result,
                        "ok": True,
                        "accepted": True,
                        "delivery_state": "accepted",
                        "request_id": rid,
                        "text": "已送达",
                        "evidence": evidence,
                    }
                    self.legacy._finish(rid, updated)
                    self._link_delivery(tid, rid, evidence)
                    if evidence.get("message_id"):
                        claimed.add(str(evidence["message_id"]))
                    self._reconcile_seen.pop(key, None)
                else:
                    remaining += 1
                    self._reconcile_seen[key] = file_sig
                    if len(self._reconcile_seen) > 256:
                        self._reconcile_seen.pop(next(iter(self._reconcile_seen)))
            return remaining

    def message_images(self, tid: str) -> list[dict]:
        """Return control-state image records enriched with confirmed transcript message_id."""
        self.reconcile_deliveries(tid)
        rows = self.legacy.message_images(tid)
        by_req = self.delivery_links.request_to_source(tid)
        if not by_req:
            return rows
        out = []
        for row in rows:
            mid = by_req.get(str(row.get("request_id") or ""))
            out.append({**row, "message_id": mid} if mid else row)
        return out

    def receipt(self, tid: str, rid: str) -> dict:
        path = self.legacy.data_root / "delivery.sqlite"
        if not path.exists():
            return {"state": "unknown"}
        # 11-26 P1: read before _db() makes the table (see codex_control.record_missing), and in any conversation.
        missing = codex_control.record_missing(path, rid)
        with self.legacy._db() as con:
            row = con.execute(
                "SELECT state,result,data,created FROM deliveries WHERE id=? AND thread=?", (rid, tid)
            ).fetchone()
        if not row:
            # 8.1: the record file reads and holds no row for this request id: the message never arrived.
            return {"state": "unknown", "missing": True} if missing else {"state": "unknown"}
        status, raw_result, raw_data, _ = row
        result = json.loads(raw_result or "{}")
        body = json.loads(raw_data or "{}")

        if status == "queued":
            still_queued = any(v["id"] == rid for v in self.queues.list_items(tid))
            if still_queued:
                return {"state": "queued", "request_id": rid, "result": result}

        # Check rollout transcript for matching self-delegation / hook_prompt to upgrade ack -> delivered
        existing_ev = result.get("evidence") or {}
        if existing_ev.get("message_id"):
            self._link_delivery(tid, rid, existing_ev)
        prompt = result.get("compiled_prompt") or body.get("text") or ""
        if status in ("dispatching", "accepted", "queued") and prompt and not existing_ev.get("message_id"):
            evidence = find_delegation_delivery(
                self._thread_file(tid),
                tid,
                prompt,
                exclude_message_ids=self._claimed_sources_excluding(tid, rid),
            )
            if evidence:
                result = {
                    **result,
                    "ok": True,
                    "accepted": True,
                    "delivery_state": "accepted",
                    "request_id": rid,
                    "text": "已送达",
                    "evidence": evidence,
                }
                self.legacy._finish(rid, result)
                self._link_delivery(tid, rid, evidence)
                status = "accepted"

        if status == "accepted" and not body.get("question_id"):
            result["submission"] = {k: body.get(k) for k in ("text", "attachments", "settings", "plan_id", "references")}
        return {"state": status, "request_id": rid, "result": result}

    def delivery_locations(self, tid: str, request_ids: list[str]) -> dict:
        out = self.legacy.delivery_locations(tid, request_ids)
        # Reconcile unresolved new-route items against transcript self-delegation
        for rid in request_ids:
            entry = out.get(rid)
            if entry and entry.get("message_id"):
                continue
            rec = self.receipt(tid, rid)
            ev = (rec.get("result") or {}).get("evidence") or {}
            if ev.get("message_id"):
                out[rid] = {
                    "state": rec["state"],
                    "client_id": (rec.get("result") or {}).get("client_id"),
                    "message_id": ev["message_id"],
                }
        return out
