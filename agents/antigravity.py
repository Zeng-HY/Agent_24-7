"""Antigravity desktop: its conversation list, reading, sending and phone approvals.

The list and the transcript are read from the two files Antigravity writes: the summaries database
`conversation_summaries.db` and each conversation's `brain/<id>/.system_generated/logs/transcript.jsonl`.
Sending and approving use the app's own local service, the way the user's `ag.py` does: the language
server writes its port and a CSRF token to `daemon/hub_<port>.json`, and the token is read from there,
kept in memory and sent only to `localhost`. It is never logged, returned or put into an error.

The format has no public description and may change in any Antigravity update, so a missing column, a
changed time or one bad row is read as an empty value instead of an error: the list returns what it can.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from .base import Agent, AgentError, NotFound, make_manifest

# The island asks only for these four kinds of work; the tools that are not one of them say nothing.
STEP_NAMES = {
    "run_command": "run",
    "run_workflow": "run",
    "edit_file": "edit",
    "write_file": "edit",
    "read_file": "read",
    "search_web": "search",
    "webview_browser": "search",
}

# One value of a tool call that says what it is doing (its own words, never the whole record).
ARG_KEYS = ("CommandLine", "Path", "Target", "query", "Description", "Prompt", "ScriptPath",
            "Message", "url", "focus", "Action", "result")

TITLE_FALLBACK = "Antigravity 对话"
PREVIEW_LIMIT = 150
TOOL_VALUE_LIMIT = 120
MESSAGE_TEXT_LIMIT = 6000
TAIL_BYTES = 256 << 10
LIST_SECONDS = 2.0        # at most one database read this often, even when it changed
CACHE_LIMIT = 8           # conversations kept parsed
FULL_CACHE_LIMIT = 4      # full transcripts kept for cut answers

# The app's own local service (the same one the user's ag.py drives).
SERVICE = "exa.language_server_pb.LanguageServerService"
HUB_SECONDS = 2.0         # capabilities_now asks again at most this often
WAITING_SECONDS = 3.0     # one conversation's waiting steps read at most this often
LIST_WAITING_SECONDS = 15.0  # the list only uses a result this recent, never reads for itself
WAITING_TIMEOUT = 5.0     # reading the waiting steps
SEND_TIMEOUT = 60.0       # SendUserCascadeMessage / agentapi / CancelCascadeInvocation
ANSWER_TIMEOUT = 10.0     # HandleCascadeUserInteraction / UpdateConversationAnnotations
SEND_LIMIT = 20000        # agentapi takes the text as one command-line argument
DETAIL_LIMIT = 4000       # a card's detail is cut here
NOT_OPEN = "电脑上的 Antigravity 没开"
QUEUED_SEND = "Antigravity 正在跑，这条会等这一轮做完再交给它"
NOT_RUNNING = "这个对话没在跑"

# New conversations (the same defaults ag.py uses).
MODEL = "gemini-4-neon-high"
TURBO = "AGENT_PERMISSION_PRESET_TURBO"
TURBO_MARK = "permission_preset:" + TURBO
WARM_UP = "只回复两个字：好的。不要做别的，不要运行任何命令。"
NEW_WAIT_SECONDS = 120.0
NEW_POLL_SECONDS = 3.0

# Pictures: checked before anything is sent; a bad one breaks that Antigravity conversation for good.
MAX_PICTURES = 5
MAX_PICTURE_BYTES = 20 << 20
MAX_PICTURE_SIDE = 8000
BAD_PICTURE = "这张图片打不开，没有发给 Antigravity"
# What actually goes out: a freshly encoded copy, never the stored file.
SEND_PICTURE_SIDE = 3072
SEND_PICTURE_PNG_LIMIT = 3 << 20
SEND_PICTURE_TOTAL_LIMIT = 15 << 20

# The three answers a phone may give to one approval step.
APPROVAL_CHOICES = {
    "允许一次": (True, "PERMISSION_SCOPE_ONCE", "已允许"),
    "本对话里这条都允许": (True, "PERMISSION_SCOPE_CONVERSATION", "已允许（本对话里这条都允许）"),
    "拒绝": (False, "PERMISSION_SCOPE_ONCE", "已拒绝"),
}
APPROVAL_OPTIONS = tuple({"label": label, "description": ""} for label in APPROVAL_CHOICES)

APPROVAL_TITLES = {
    "command": "Antigravity 想运行命令",
    "run_command": "Antigravity 想运行命令",
    "run_workflow": "Antigravity 想运行命令",
    "read_file": "Antigravity 想读文件",
    "edit_file": "Antigravity 想改文件",
    "write_file": "Antigravity 想改文件",
    "search_web": "Antigravity 想联网搜索",
    "webview_browser": "Antigravity 想打开网页",
}
APPROVAL_QUESTIONS = {
    "command": "允许运行这条命令吗？",
    "run_command": "允许运行这条命令吗？",
    "run_workflow": "允许运行这条命令吗？",
    "read_file": "允许读取这个文件吗？",
    "edit_file": "允许修改这个文件吗？",
    "write_file": "允许修改这个文件吗？",
}


class ControlError(AgentError):
    """One action Antigravity could not carry out; the HTTP layer turns it into JSON with .status."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status

_TIME_FRACTION = re.compile(r"(\.\d{6})\d")
_ISO_FRACTION = re.compile(r"(\.\d{3})\d+")

_LOCK = threading.Lock()
_LIST_CACHE: dict = {"path": None, "stamp": None, "at": 0.0, "rows": None}
_MESSAGE_CACHE: dict[str, tuple] = {}
_FULL_CACHE: dict[str, tuple] = {}
_HUB_CACHE: dict = {"at": 0.0, "data": None}
_WAITING_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SENT: dict[str, dict] = {}
_CREATED: dict[str, dict] = {}
_LOGGED: set[tuple[str, str]] = set()
_LOG_WRITER = [None]


def _now() -> float:
    """The clock caches are measured with (tests replace it)."""
    return time.monotonic()


# ---------------------------------------------------------------- where the data is


def _root() -> Path:
    """The data folder, read from machines.HOME at call time (tests replace it)."""
    import machines
    return machines.HOME / ".gemini" / "antigravity"


def _db_path() -> Path:
    return _root() / "conversation_summaries.db"


def _transcript_path(conv_id: str) -> Path:
    return _root() / "brain" / str(conv_id) / ".system_generated" / "logs" / "transcript.jsonl"


def _full_path(conv_id: str) -> Path:
    return _root() / "brain" / str(conv_id) / ".system_generated" / "logs" / "transcript_full.jsonl"


def reset() -> None:
    """Forget everything kept in memory (tests build their own data folder)."""
    with _LOCK:
        _LIST_CACHE.update(path=None, stamp=None, at=0.0, rows=None)
        _MESSAGE_CACHE.clear()
        _FULL_CACHE.clear()
        _HUB_CACHE.update(at=0.0, data=None)
        _WAITING_CACHE.clear()
        _SENT.clear()
        _CREATED.clear()
        _LOGGED.clear()


# ---------------------------------------------------------------- small helpers


def _one_line(text, limit: int = TOOL_VALUE_LIMIT) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _seconds(value) -> int:
    """A recorded time as Unix seconds; 0 when it is not one. The record keeps 7 fraction digits."""
    text = _TIME_FRACTION.sub(r"\1", str(value or ""))
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return 0


def _iso(value) -> str:
    """A recorded time as a page time, with at most three fraction digits."""
    text = str(value or "").strip()
    return _ISO_FRACTION.sub(r"\1", text.replace("Z", "+00:00"))


def _millis(value) -> int:
    """A recorded time as Unix milliseconds, so rows less than a second apart still sort correctly."""
    text = _TIME_FRACTION.sub(r"\1", str(value or ""))
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


_USER_OPEN = "<USER_REQUEST>"
_USER_CLOSE = "</USER_REQUEST>"
_META_OPEN = "<ADDITIONAL_METADATA>"
_SYSTEM_MARK = "[Message]"
_SYSTEM_END = "</SYSTEM_MESSAGE>"


def _user_request_text(content) -> str:
    """A real USER_INPUT: the words between <USER_REQUEST> and </USER_REQUEST>, or the whole text."""
    text = _text(content)
    start = text.find(_USER_OPEN)
    if start < 0:
        return text
    start += len(_USER_OPEN)
    end = text.find(_USER_CLOSE, start)
    if end < 0:
        end = text.find(_META_OPEN, start)
    if end < 0:
        end = len(text)
    return text[start:end].strip()


def _system_user_text(content) -> str:
    """A sender=system [Message] line's content= words, or '' for any other SYSTEM_MESSAGE."""
    text = _text(content)
    marker = text.find(_SYSTEM_MARK)
    if marker < 0:
        return ""
    content_at = text.find("content=", marker)
    if content_at < 0:
        return ""
    if "sender=system" not in text[marker:content_at]:
        return ""
    value = text[content_at + len("content="):]
    end = value.find(_SYSTEM_END)
    if end >= 0:
        value = value[:end]
    return value.strip()


def _row_value(row, name: str):
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def _log_once(what: str, reason: str) -> None:
    day = time.strftime("%Y%m%d")
    key = (what, day)
    with _LOCK:
        if key in _LOGGED:
            return
        _LOGGED.add(key)
    writer = _LOG_WRITER[0]
    if not callable(writer):
        return
    try:
        writer(f"Antigravity：{what}（{_one_line(reason, 200)}）")
    except Exception:
        pass


def _folder_of(value) -> str:
    """The first workspace_uris entry as a folder path, '' when there is none."""
    text = (value or "").strip()
    if not text:
        return ""
    try:
        found = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(found, list) or not found or not isinstance(found[0], str):
        return ""
    uri = unquote(found[0].strip())
    if uri.startswith("file:///"):
        path = uri[8:]
    elif uri.startswith("file://"):
        rest = uri[7:]
        path = "\\\\" + rest.replace("/", "\\") if rest and not rest.startswith("/") else rest.lstrip("/")
    elif uri.startswith("file:"):
        path = uri[5:].lstrip("/")
    else:
        path = uri
    return path.replace("/", "\\")


def _status_of(value) -> str:
    return {"CASCADE_RUN_STATUS_RUNNING": "running",
            "CASCADE_RUN_STATUS_IDLE": "idle"}.get(str(value or ""), "unknown")


def _title_of(row) -> str:
    title = _one_line(_user_request_text(_row_value(row, "title")), 120)
    if title:
        return title
    preview = _one_line(_user_request_text(_row_value(row, "preview")), 40)
    return preview or TITLE_FALLBACK


def _item_of(row) -> dict:
    conv_id = str(_row_value(row, "conversation_id") or "").strip()
    preview = _one_line(_user_request_text(_row_value(row, "preview")), PREVIEW_LIMIT)
    folder = _folder_of(_row_value(row, "workspace_uris"))
    status = _status_of(_row_value(row, "status"))
    modified = _millis(_row_value(row, "last_modified_time"))
    started = _seconds(_row_value(row, "last_user_input_time"))
    ended = modified // 1000 if status != "running" else 0
    title = _title_of(row)
    return {
        "app": "antigravity",
        "id": conv_id,
        "title": title,
        "preview": preview or title,
        "folder": Path(folder).name if folder else "",
        "cwd": folder,
        "updated": modified,
        "created": 0,
        "pinned": False,
        "status": status,
        "turn_started": started,
        "turn_ended": ended,
        "step": "",
        # Private: which rows the list leaves out (children, losing battles).
        "_nesting_depth": _row_value(row, "nesting_depth"),
        "_parent_id": _row_value(row, "parent_conversation_id"),
        "_battle_id": _row_value(row, "battle_id"),
        "_winning_id": _row_value(row, "winning_conversation_id"),
    }


# ---------------------------------------------------------------- the list


def _stamp() -> tuple:
    found = []
    for path in (_db_path(), Path(str(_db_path()) + "-wal")):
        try:
            stat = path.stat()
            found.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            found.append(None)
    return tuple(found)


def _read_rows() -> list[dict]:
    path = _db_path()
    if not path.is_file():
        return []
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    try:
        return [_item_of(row) for row in con.execute("SELECT * FROM conversation_summaries")]
    finally:
        con.close()


def _all_rows(fresh: bool = False) -> list[dict]:
    path = str(_db_path())
    stamp = _stamp()
    now = _now()
    with _LOCK:
        hit = _LIST_CACHE
        if (hit["rows"] is not None and hit["path"] == path and not fresh
                and (hit["stamp"] == stamp or now - hit["at"] < LIST_SECONDS)):
            return [dict(row) for row in hit["rows"]]
    try:
        rows = _read_rows()
    except Exception as exc:
        _log_once("对话列表读不到", f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}")
        rows = []
        with _LOCK:
            if _LIST_CACHE["rows"] is not None and _LIST_CACHE["path"] == path and _LIST_CACHE["stamp"] == stamp:
                return [dict(row) for row in _LIST_CACHE["rows"]]
    with _LOCK:
        _LIST_CACHE.update(path=path, stamp=stamp, at=now, rows=rows)
    return [dict(row) for row in rows]


def _is_child(row: dict) -> bool:
    try:
        depth = int(row.get("_nesting_depth") or 0)
    except (TypeError, ValueError):
        depth = 0
    return depth > 0 or bool(str(row.get("_parent_id") or "").strip())


def _top_level(rows: list[dict]) -> list[dict]:
    found = []
    for row in rows:
        if _is_child(row):
            continue
        battle = str(row.get("_battle_id") or "").strip()
        winning = str(row.get("_winning_id") or "").strip()
        if battle and winning and winning != row.get("id"):
            continue
        found.append(row)
    return found


def _trim(row: dict) -> dict:
    """The public shape: the list keeps its private keys out of the phone's data."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _tail_lines(path: Path, nbytes: int = TAIL_BYTES) -> list[bytes]:
    try:
        with path.open("rb") as file:
            file.seek(0, 2)
            size = file.tell()
            start = max(0, size - nbytes)
            file.seek(start)
            data = file.read()
    except OSError:
        return []
    if start and data:
        cut = data.find(b"\n")
        data = data[cut + 1:] if cut >= 0 else b""
    return data.splitlines()


def _last_tool_name(path: Path) -> str:
    for raw in reversed(_tail_lines(path)):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        calls = record.get("tool_calls") if isinstance(record, dict) else None
        if not isinstance(calls, list):
            continue
        for call in reversed(calls):
            if isinstance(call, dict) and _text(call.get("name")):
                return _text(call.get("name"))
    return ""


def _last_record_type(path: Path) -> str:
    """The newest step's type, skipping Antigravity's own bookkeeping messages."""
    for raw in reversed(_tail_lines(path)):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(record, dict):
            continue
        kind = _text(record.get("type"))
        if kind == "SYSTEM_MESSAGE":
            continue
        return kind
    return ""


# ---------------------------------------------------------------- one record's messages


def _media(record: dict) -> bool:
    value = record.get("media")
    return isinstance(value, (list, dict)) and bool(value)


def _tool_message(call: dict, status: str) -> dict | None:
    name = _text(call.get("name"))
    if not name:
        return None
    args = call.get("args")
    value = ""
    if isinstance(args, dict):
        # A command says what it does in its own one-line summary when Antigravity records one.
        if name == "run_command" and isinstance(args.get("toolSummary"), str) and args["toolSummary"].strip():
            value = _one_line(args["toolSummary"])
        else:
            for key in ARG_KEYS:
                if isinstance(args.get(key), str) and args[key].strip():
                    value = _one_line(args[key])
                    break
    elif isinstance(args, str):
        value = _one_line(args)
    text = f"{name}：{value}" if value else name
    message = {"role": "tool", "text": text, "activity_title": text}
    if status == "ERROR":
        message["tool_status"] = "failed"
    return message


def _is_structured(value) -> bool:
    """A finish result handed back to a program: an object, an array, or cut JSON text that starts like one."""
    if isinstance(value, (dict, list)):
        return True
    return isinstance(value, str) and value.lstrip().startswith(("{", "["))


def _plain_result(value) -> str:
    """A finish result written for a person; '' for a structured one."""
    if not isinstance(value, str) or _is_structured(value):
        return ""
    return value


def _finish_value(calls):
    """The finish call's result, whatever its shape, or None when this list has no finish call."""
    for call in calls or []:
        if isinstance(call, dict) and _text(call.get("name")) == "finish":
            args = call.get("args")
            if isinstance(args, dict):
                return args.get("result")
            return None
    return None


def _finish_result(calls) -> str:
    """A finish result written for a person, '' when it is structured or absent."""
    return _plain_result(_finish_value(calls))


def _records(path: Path, hide_warm_up: bool = True) -> list[dict]:
    """Every step of the transcript, in file order; unreadable lines are left out."""
    try:
        stat = path.stat()
    except OSError:
        return []
    key = f"{path}|{int(hide_warm_up)}"
    with _LOCK:
        hit = _MESSAGE_CACHE.get(key)
        if hit and hit[0] == stat.st_size and hit[1] == stat.st_mtime_ns:
            return hit[2]
    messages: list[dict] = []
    try:
        with path.open("rb") as file:
            for raw in file:
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(record, dict):
                    messages.extend(_records_one(record))
    except OSError:
        return []
    if hide_warm_up:
        _hide_warm_up(messages)
    _number_messages(messages)
    with _LOCK:
        if len(_MESSAGE_CACHE) >= CACHE_LIMIT:
            for old in list(_MESSAGE_CACHE)[:len(_MESSAGE_CACHE) - CACHE_LIMIT + 1]:
                _MESSAGE_CACHE.pop(old, None)
        _MESSAGE_CACHE[key] = (stat.st_size, stat.st_mtime_ns, messages)
    return messages


def _records_one(record: dict) -> list[dict]:
    kind = _text(record.get("type"))
    status = _text(record.get("status"))
    time_text = _iso(record.get("created_at"))
    content = _text(record.get("content"))
    cut = record.get("truncated_fields")
    cut_fields = {str(value) for value in cut} if isinstance(cut, list) else set()
    picture = _media(record) and "[图片]" not in content
    picture_text = ("\n[图片]" if content else "[图片]") if picture else ""

    if kind == "USER_INPUT":
        shown = _user_request_text(content)
        text = shown + picture_text
        if not text:
            return []
        message = {"role": "user", "text": text, "time": time_text}
        if picture:
            message["_picture"] = True
        if "content" in cut_fields:
            message["_truncated"] = True
            message["_step"] = record.get("step_index")
        return [message]

    if kind == "SYSTEM_MESSAGE":
        # The old agentapi send-message path wrote the user's words as sender=system: show those words as
        # the user's message. Every other SYSTEM_MESSAGE (background notices) stays out of the conversation.
        shown = _system_user_text(content)
        if not shown:
            return []
        message = {"role": "user", "text": shown + picture_text, "time": time_text,
                   "_system_user": True}
        if "content" in cut_fields:
            message["_truncated"] = True
            message["_step"] = record.get("step_index")
        return [message]

    if kind == "PLANNER_RESPONSE":
        # Antigravity puts its answers and its tool calls on this same line: the words first, then each call.
        found = []
        if content:
            message = {"role": "assistant", "text": content + picture_text, "time": time_text}
            if picture:
                message["_picture"] = True
            if "content" in cut_fields:
                message["_truncated"] = True
                message["_step"] = record.get("step_index")
            found.append(message)
        calls = record.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if not isinstance(call, dict):
                    continue
                if _text(call.get("name")) == "finish":
                    # A structured result goes back to a program, not to a person: one step, never the JSON.
                    value = _finish_value([call])
                    if _is_structured(value):
                        message = {"role": "tool", "text": "finish：交回了结构化结果",
                                   "activity_title": "finish：交回了结构化结果", "time": time_text}
                        found.append(message)
                        continue
                    result = _plain_result(value)
                    if result:
                        message = {"role": "assistant", "text": result, "time": time_text}
                        if "tool_calls" in cut_fields:
                            message["_finish_cut"] = True
                            message["_step"] = record.get("step_index")
                        found.append(message)
                    continue
                message = _tool_message(call, status)
                if message:
                    message["time"] = time_text
                    found.append(message)
        return found

    if kind == "GENERIC":
        # GENERIC is the tool's output. It is never an answer; only a future format's tool calls are steps.
        calls = record.get("tool_calls")
        if isinstance(calls, list) and calls:
            found = []
            for call in calls:
                if isinstance(call, dict):
                    message = _tool_message(call, status)
                    if message:
                        message["time"] = time_text
                        found.append(message)
            return found
        return []

    if kind == "ERROR_MESSAGE":
        reason = _text(record.get("error")) or content
        text = "出错：" + (reason[:2000] if reason else "Antigravity 出错了")
        return [{"role": "event", "text": text, "time": time_text}]

    if kind == "CHECKPOINT":
        return []

    # An unknown type is shown as ordinary words when it has any; nothing else about it is guessed.
    if content:
        return [{"role": "assistant", "text": content, "time": time_text}]
    return []


def _normalise_message(text) -> str:
    """Whitespace runs become one space, so a wrapped or truncated record still compares with what we sent."""
    return " ".join(str(text or "").split())


def _same_start(record_text, wanted) -> bool:
    """Whether the record's message begins with what we sent (long sends compare their first 200 characters)."""
    head = _normalise_message(wanted)
    got = _normalise_message(record_text)
    if not head:
        return False
    if len(head) >= 200:
        return got[:200] == head[:200]
    return got.startswith(head)


def _hide_warm_up(messages: list[dict]) -> None:
    """A new conversation starts with our fixed warm-up and its one answer: hide just that pair."""
    if not messages:
        return
    first = messages[0]
    if first.get("role") != "user" or _text(first.get("text")) != WARM_UP:
        return
    del messages[0]
    if messages and messages[0].get("role") in ("assistant", "tool"):
        del messages[0]


def _number_messages(messages: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for message in messages:
        identity = json.dumps([message.get("time"), message.get("role"), message.get("text")],
                              ensure_ascii=False)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        seen[digest] = seen.get(digest, 0) + 1
        message["id"] = f"{digest}:{seen[digest]}"
    return messages


def _full_records(path: Path, steps: set[int]) -> dict:
    """The full content and tool calls of these steps from transcript_full.jsonl; only those steps are kept."""
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = str(path)
    with _LOCK:
        hit = _FULL_CACHE.get(key)
        if hit and hit[0] == stat.st_size and hit[1] == stat.st_mtime_ns and steps <= hit[2]:
            return hit[3]
    found: dict[int, dict] = {}
    try:
        with path.open("rb") as file:
            for raw in file:
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                index = record.get("step_index")
                if isinstance(index, int) and index in steps:
                    content = record.get("content")
                    calls = record.get("tool_calls")
                    found[index] = {"content": content if isinstance(content, str) else None,
                                    "tool_calls": calls if isinstance(calls, list) else None}
    except OSError:
        return {}
    with _LOCK:
        if len(_FULL_CACHE) >= FULL_CACHE_LIMIT:
            for old in list(_FULL_CACHE)[:len(_FULL_CACHE) - FULL_CACHE_LIMIT + 1]:
                _FULL_CACHE.pop(old, None)
        _FULL_CACHE[key] = (stat.st_size, stat.st_mtime_ns, steps, found)
    return found


def _fill_cut(messages: list[dict], conv_id: str) -> None:
    steps = set()
    for message in messages:
        if (message.get("_truncated") or message.get("_finish_cut")) and isinstance(message.get("_step"), int):
            steps.add(message["_step"])
    if not steps:
        return
    full = _full_records(_full_path(conv_id), steps)
    for message in messages:
        record = full.get(message.get("_step")) if isinstance(message.get("_step"), int) else None
        if not record:
            continue
        if message.get("_truncated"):
            content = record.get("content")
            if content is not None:
                if message.get("role") == "user":
                    shown = (_system_user_text(content) if message.get("_system_user")
                             else _user_request_text(content))
                else:
                    shown = content
                message["text"] = shown + ("\n[图片]" if message.get("_picture") else "")
        if message.get("_finish_cut"):
            result = _finish_result(record.get("tool_calls") or [])
            if result:
                message["text"] = result


# ---------------------------------------------------------------- the app's local service
#
# Same interface as the user's ag.py: find the live language server through its hub file, then either
# POST to its Connect service or run `language_server.exe agentapi`. The CSRF token only ever travels
# in the request header / child environment, both to localhost; it is never logged or returned.


def _daemon_dir() -> Path:
    return _root() / "daemon"


def _alive(pid: int) -> bool:
    """Whether that process is running (ag.py's rule: OpenProcess + GetExitCodeProcess == 259)."""
    if pid <= 0:
        return False
    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:  # not Windows (the service itself only runs on Windows)
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _read_hub() -> dict | None:
    """The newest hub file whose language server is still running; None when Antigravity is not open."""
    folder = _daemon_dir()
    if not folder.is_dir():
        return None
    try:
        paths = sorted(folder.glob("hub_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            pid = int(data.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        if _alive(pid) and data.get("httpPort") and data.get("csrfToken"):
            return {"pid": pid, "httpPort": data["httpPort"], "csrfToken": data["csrfToken"]}
    return None


def _hub(max_age: float = HUB_SECONDS) -> dict | None:
    """The live language server, kept [max_age] seconds (0 reads it again now)."""
    now = _now()
    with _LOCK:
        hit = _HUB_CACHE
        if hit["at"] and now - hit["at"] < max_age:
            return hit["data"]
    data = _read_hub()
    with _LOCK:
        _HUB_CACHE.update(at=now, data=data)
    return data


def _safe(text, token) -> str:
    """A message that can be logged or returned: the token is never in it."""
    value = str(text or "")
    return value.replace(str(token), "***") if token else value


def _rpc(method: str, body: dict, timeout: float = WAITING_TIMEOUT) -> dict:
    """One POST to the app's own Connect service on localhost."""
    data = _hub(0)
    if data is None:
        raise ControlError(NOT_OPEN, 409)
    url = f"http://localhost:{data['httpPort']}/{SERVICE}/{method}"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json", "Connect-Protocol-Version": "1",
        "x-codeium-csrf-token": str(data["csrfToken"])})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise ControlError(f"Antigravity 没接受这次请求（HTTP {exc.code}）", 502) from None
    except (urllib.error.URLError, OSError):
        raise ControlError("连不上电脑上的 Antigravity，请打开它再试", 502) from None
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        raise ControlError("Antigravity 的回答看不懂", 502) from None


def _language_server() -> Path:
    """Where the app puts the program that has the agentapi command."""
    import machines
    return (Path(machines.LOCALAPPDATA) / "Programs" / "Antigravity"
            / "resources" / "bin" / "language_server.exe")


def _run_language_server(exe, args: list[str], env: dict, timeout: float):
    """Run `language_server.exe agentapi …` (tests replace this function, never the real program)."""
    return subprocess.run([str(exe), "agentapi", *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _agentapi(args: list[str], data: dict, timeout: float = SEND_TIMEOUT, project: str = "") -> dict:
    """One agentapi command; its output is JSON and an error field or a non-zero exit is a failure."""
    env = dict(os.environ)
    env["ANTIGRAVITY_LS_ADDRESS"] = f"localhost:{data['httpPort']}"
    env["ANTIGRAVITY_CSRF_TOKEN"] = str(data["csrfToken"])
    if project:
        env["ANTIGRAVITY_PROJECT_ID"] = str(project)
    try:
        done = _run_language_server(_language_server(), list(args), env, timeout)
    except subprocess.TimeoutExpired:
        raise ControlError("Antigravity 没有回应（超时），请到电脑上看看", 502) from None
    except OSError:
        raise ControlError("找不到 Antigravity 的程序，可能没装好", 502) from None
    text = (getattr(done, "stdout", "") or "").strip() or (getattr(done, "stderr", "") or "").strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        raise ControlError(_safe("Antigravity 的回答看不懂：" + text[:200], data["csrfToken"]), 502) from None
    if getattr(done, "returncode", 1) != 0 or (isinstance(parsed, dict) and parsed.get("error")):
        reason = parsed.get("error") if isinstance(parsed, dict) else ""
        raise ControlError(_safe("Antigravity 没做成：" + str(reason or text[:200]), data["csrfToken"]), 502) from None
    return parsed if isinstance(parsed, dict) else {}


def _pending_steps(data: dict) -> list[dict]:
    """The waiting-for-approval steps in one GetCascadeTrajectorySteps answer (ag.py's pending())."""
    found: list[dict] = []
    steps = data.get("steps") if isinstance(data, dict) else None
    for index, step in enumerate(steps or []):
        if not isinstance(step, dict) or step.get("status") != "CORTEX_STEP_STATUS_WAITING":
            continue
        interaction = step.get("requestedInteraction")
        permission = interaction.get("permission") if isinstance(interaction, dict) else None
        if not isinstance(permission, dict):
            continue
        resource = permission.get("resource")
        resource = resource if isinstance(resource, dict) else {}
        metadata = step.get("metadata")
        info = metadata.get("sourceTrajectoryStepInfo") if isinstance(metadata, dict) else None
        info = info if isinstance(info, dict) else {}
        step_index = info.get("stepIndex", index)
        try:
            step_index = int(step_index)
        except (TypeError, ValueError):
            step_index = index
        found.append({"trajectory_id": _text(info.get("trajectoryId")), "step_index": step_index,
                      "action": _text(resource.get("action")), "target": _text(resource.get("target"))})
    return found


def _cached_waiting(conv_id: str, max_age: float) -> list[dict] | None:
    """The waiting steps kept for this conversation if they are younger than [max_age]; None when there is none."""
    with _LOCK:
        hit = _WAITING_CACHE.get(conv_id)
        if hit and _now() - hit[0] < max_age:
            return [dict(step) for step in hit[1]]
    return None


def waiting_steps(conv_id: str, max_age: float = WAITING_SECONDS, fetch: bool = True) -> list[dict]:
    """This conversation's waiting-for-approval steps.

    Read from the app at most once every [max_age] seconds; with [fetch] False only a cached answer is
    used (the list never reads for itself). A read failure counts as "no waiting steps" and is logged
    once a day, without the token.
    """
    conv_id = str(conv_id or "").strip()
    if not conv_id:
        return []
    cached = _cached_waiting(conv_id, max_age)
    if cached is not None:
        return cached
    if not fetch:
        return []
    try:
        steps = _pending_steps(_rpc("GetCascadeTrajectorySteps", {"cascadeId": conv_id}, timeout=WAITING_TIMEOUT))
    except ControlError as exc:
        _log_once("等批准状态读不到", _one_line(f"{type(exc).__name__}: {exc}", 200))
        steps = []
    with _LOCK:
        if len(_WAITING_CACHE) >= 64:
            oldest = min(_WAITING_CACHE, key=lambda key: _WAITING_CACHE[key][0])
            _WAITING_CACHE.pop(oldest, None)
        _WAITING_CACHE[conv_id] = (_now(), steps)
    return [dict(step) for step in steps]


def _forget_waiting(conv_id: str) -> None:
    with _LOCK:
        _WAITING_CACHE.pop(str(conv_id or ""), None)


def _card_id(step: dict) -> str:
    return f"{step.get('trajectory_id', '')}:{step.get('step_index', 0)}"


def _card_detail(target: str) -> str:
    return target if len(target) <= DETAIL_LIMIT else target[:DETAIL_LIMIT - 1] + "…"


def _approval_card(step: dict) -> dict:
    action = str(step.get("action") or "")
    return {
        "id": _card_id(step),
        "status": "pending",
        "kind": "approval",
        "turn_id": str(step.get("trajectory_id") or ""),
        "title": APPROVAL_TITLES.get(action, "Antigravity 等你批准"),
        "detail": _card_detail(str(step.get("target") or "")),
        "questions": [{
            "id": "decision",
            "header": "",
            "question": APPROVAL_QUESTIONS.get(action, "允许这一步吗？"),
            "options": [dict(option) for option in APPROVAL_OPTIONS],
            "isOther": False,
            "isSecret": False,
            "isMultiple": False,
        }],
        "answer_revision": "",
        "expires_at": 0,
    }


def _waiting_cards(conv_id: str) -> list[dict]:
    return [_approval_card(step) for step in waiting_steps(conv_id)]


def _listed(row: dict) -> dict:
    """A public list row: a running one says waiting only when a recent read saw a pending step."""
    item = _trim(row)
    if item.get("status") in ("running", "waiting"):
        pending = _cached_waiting(str(item.get("id") or ""), LIST_WAITING_SECONDS)
        item["status"] = "waiting" if pending else "running"
    return item


def _send_user_message(conv_id: str, text: str, media: list[dict] | None = None, busy: bool = False) -> dict:
    """The app's own send path: recorded as the user's real message, queued when a turn is running."""
    body: dict = {"cascadeId": str(conv_id), "items": [{"text": str(text)}]}
    if media:
        body["media"] = list(media)
    if busy:
        body["deliveryStrategy"] = "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE"
    return _rpc("SendUserCascadeMessage", body, timeout=SEND_TIMEOUT)


def _annotations_path(conv_id: str) -> Path:
    return _root() / "annotations" / f"{conv_id}.pbtxt"


def _turbo_stored(conv_id: str) -> bool:
    """Whether this conversation's own annotation already names the turbo preset (ag.py's turbo_stored)."""
    try:
        return TURBO_MARK in _annotations_path(conv_id).read_text(encoding="utf-8")
    except OSError:
        return False


def _set_turbo(conv_id: str) -> None:
    """Turn this conversation's full-auto on; it applies from the next message."""
    _rpc("UpdateConversationAnnotations", {
        "cascadeId": str(conv_id),
        "annotations": {"permissionPreset": TURBO},
        "mergeAnnotations": True,
    }, timeout=ANSWER_TIMEOUT)


def _file_uri_path(uri) -> str:
    return _folder_of(json.dumps([str(uri)]))


def _projects() -> list[dict]:
    """Antigravity's projects: id, name and folders, read only from config\\projects\\*.json."""
    import machines
    folder = machines.HOME / ".gemini" / "config" / "projects"
    rows: list[dict] = []
    if not folder.is_dir():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        ident = str(data.get("id") or "").strip()
        name = str(data.get("name") or "").strip() or ident
        resources = ((data.get("projectResources") or {}).get("resources") or [])
        folders = [_file_uri_path(item.get("folderUri")) for item in resources if isinstance(item, dict)]
        if ident:
            rows.append({"id": ident, "name": name, "folders": [value for value in folders if value]})
    rows.sort(key=lambda row: (row["name"].casefold() != "personal", row["name"].casefold()))
    return rows


def _project_for_folder(folder: str = "") -> dict | None:
    """The project that owns [folder]; with no folder, the default one (Personal, else the first)."""
    projects = _projects()
    if not projects:
        return None
    if not folder:
        return projects[0]
    wanted = os.path.normcase(os.path.normpath(str(folder)))
    for project in projects:
        for path in project["folders"]:
            if os.path.normcase(os.path.normpath(path)) == wanted:
                return project
    return None


def _jpeg_size(raw: bytes) -> tuple[int, int] | None:
    """Width and height from a JPEG's SOF segment (the format's own few bytes, no new package)."""
    index = 2
    while index + 9 < len(raw):
        if raw[index] != 0xFF:
            index += 1
            continue
        marker = raw[index + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if index + 4 > len(raw):
            return None
        length = int.from_bytes(raw[index + 2:index + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if index + 9 > len(raw):
                return None
            return int.from_bytes(raw[index + 7:index + 9], "big"), int.from_bytes(raw[index + 5:index + 7], "big")
        index += 2 + length
    return None


def _webp_size(raw: bytes) -> tuple[int, int] | None:
    chunk = raw[12:16]
    if chunk == b"VP8X" and len(raw) >= 30:
        return (1 + int.from_bytes(raw[24:27], "little"), 1 + int.from_bytes(raw[27:30], "little"))
    if chunk == b"VP8 " and len(raw) >= 30:
        return (int.from_bytes(raw[26:28], "little") & 0x3FFF,
                int.from_bytes(raw[28:30], "little") & 0x3FFF)
    if chunk == b"VP8L" and len(raw) >= 25:
        bits = int.from_bytes(raw[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def picture_info(raw: bytes) -> tuple[str, int, int]:
    """(mime, width, height) for a picture this app can take; ControlError 400 for anything else."""
    if not raw:
        raise ControlError(BAD_PICTURE, 400)
    if len(raw) > MAX_PICTURE_BYTES:
        raise ControlError("这张图片超过 20 MB，没有发给 Antigravity", 400)
    size = None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
        if len(raw) >= 24 and raw[12:16] == b"IHDR":
            size = (int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big"))
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
        size = _jpeg_size(raw)
    elif raw.startswith(b"GIF8"):
        mime = "image/gif"
        if len(raw) >= 10:
            size = (int.from_bytes(raw[6:8], "little"), int.from_bytes(raw[8:10], "little"))
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
        size = _webp_size(raw)
    else:
        raise ControlError(BAD_PICTURE, 400)
    if not size or not (1 <= size[0] <= MAX_PICTURE_SIDE and 1 <= size[1] <= MAX_PICTURE_SIDE):
        raise ControlError(BAD_PICTURE, 400)
    return mime, size[0], size[1]


def send_picture(image: dict) -> tuple[dict, int]:
    """A fresh PNG or JPEG copy of a stored picture, fully decoded first; (media item, byte size).

    The stored file is never sent as it is: a file whose header looked right but whose data was broken
    would make Antigravity fail every later turn of that conversation.
    """
    from PIL import Image, ImageOps

    name = image.get("name") or "图片"
    try:
        raw = Path(image["path"]).read_bytes()
        with Image.open(io.BytesIO(raw)) as source:
            source.load()  # decode the whole picture, not just its header
            picture = ImageOps.exif_transpose(source)
            if max(picture.size) > SEND_PICTURE_SIDE:
                picture.thumbnail((SEND_PICTURE_SIDE, SEND_PICTURE_SIDE), Image.LANCZOS)
            if picture.mode not in ("RGB", "RGBA"):
                picture = picture.convert("RGBA" if "A" in picture.getbands() else "RGB")
            picture.info.clear()
            png = io.BytesIO()
            picture.save(png, format="PNG")
            outgoing = png.getvalue()
            mime = "image/png"
            if len(outgoing) > SEND_PICTURE_PNG_LIMIT:
                if picture.mode == "RGBA":
                    white = Image.new("RGB", picture.size, (255, 255, 255))
                    white.paste(picture, mask=picture.getchannel("A"))
                    picture = white
                else:
                    picture = picture.convert("RGB")
                jpeg = io.BytesIO()
                picture.save(jpeg, format="JPEG", quality=90)
                outgoing = jpeg.getvalue()
                mime = "image/jpeg"
    except Exception:
        raise ControlError(f"「{name}」{BAD_PICTURE}", 400) from None
    picture_info(outgoing)  # the freshly encoded copy must pass the same checks
    return {"mimeType": mime, "inlineData": base64.b64encode(outgoing).decode("ascii")}, len(outgoing)


# ---------------------------------------------------------------- the agent


class AntigravityAgent(Agent):
    id = "antigravity"
    notify_uses_file = False
    # Its sidebar group appears once it has conversations; an empty Antigravity group says nothing.
    sidebar_without_chats = False
    # The list's search box looks in the preview too (Antigravity's list has the user's first words there).
    search_in_preview = True
    # A new conversation is created by the shared NewConversations worker, with only Antigravity's projects.
    new_requires_desktop = False
    new_folder_list_own_only = True

    def build_manifest(self) -> dict:
        return make_manifest(
            ident="antigravity",
            zh="Antigravity",
            en="Antigravity",
            order=40,
            color="#4285F4",
            color_dark="#8AB4F8",
            icon={"kind": "builtin", "key": "generic"},
            legacy=False,
            min_protocol=2,
            capabilities={
                "list": True,
                "read": True,
                "search": True,
                "send_modes": ["send"],
                "stop": True,
                "new": True,
                "attachments": True,
                "settings": [],
                "skills": False,
                "waiting": True,
                "approve": True,
                "statuses": ["running", "waiting", "idle", "unknown"],
            },
            params={"send_timeout_s": 60, "new_timeout_s": 140,
                    "max_images": MAX_PICTURES, "max_image_bytes": MAX_PICTURE_BYTES},
            ui={"card_layout": "generic.v1", "waiting_text": "等待你处理"},
            sources={"catalog": "sqlite", "transcript": "jsonl", "control": "local-api", "live": "file-poll"},
        )

    def capabilities_now(self, server, conv_id: str) -> dict | None:
        """What this conversation can do right now.

        Sending only needs Antigravity open (a running turn takes a queued message). Stopping needs an open
        app and a turn that is running or waiting. The hub check is kept two seconds by _hub().
        """
        if _hub() is None:
            return {"capabilities": {"send_modes": [], "approve": False, "stop": False},
                    "notes": {"send": NOT_OPEN, "approve": NOT_OPEN, "stop": NOT_OPEN}}
        try:
            item = self._find(conv_id)
        except NotFound:
            return None
        if item.get("status") not in ("running", "waiting"):
            return {"capabilities": {"stop": False}, "notes": {"stop": NOT_RUNNING}}
        return None

    def on_server_start(self, cfg: dict, apps: list[str], log) -> None:
        _LOG_WRITER[0] = log

    def detect(self) -> bool:
        """Only its summaries database; no process, no window, no port is looked at."""
        return _db_path().is_file()

    # -- list
    def catalog(self, *, limit: int = 40, cursor: str = "", query: str = "",
                sort: str = "updated", status: str = "all") -> dict:
        rows = _top_level(_all_rows())
        needle = query.strip().casefold()[:200]
        if needle:
            rows = [row for row in rows
                    if needle in (row.get("title") or "").casefold()
                    or needle in (row.get("preview") or "").casefold()]
        if status and status != "all":
            rows = [row for row in rows if row.get("status") == status]
        rows.sort(key=lambda row: (-int(row.get("updated") or 0), row.get("id") or ""))
        try:
            start = max(0, int(cursor or 0))
        except (TypeError, ValueError):
            start = 0
        try:
            size = max(1, min(100, int(limit or 40)))
        except (TypeError, ValueError):
            size = 40
        page = rows[start:start + size]
        more = start + len(page) < len(rows)
        return {"items": [_listed(row) for row in page], "has_more": more,
                "next_cursor": str(start + len(page)) if more else "", "total": len(rows)}

    def catalog_entries(self, limit: int) -> list[dict]:
        """Every recent row the shared list and project tree read (they ask for a very large limit)."""
        rows = _top_level(_all_rows())
        rows.sort(key=lambda row: (-int(row.get("updated") or 0), row.get("id") or ""))
        try:
            size = max(1, int(limit or 40))
        except (TypeError, ValueError):
            size = 40
        return [_listed(row) for row in rows[:size]]

    def find(self, conv_id: str) -> dict:
        return self._find(conv_id)

    def _find(self, conv_id: str, fresh: bool = False) -> dict:
        wanted = str(conv_id or "").strip()
        for row in _all_rows(fresh):
            if row.get("id") == wanted:
                return row
        raise NotFound("找不到这个对话（可能已删掉，或者 Antigravity 换了数据格式）")

    def summary(self, item: dict) -> dict:
        status = item.get("status") or "unknown"
        conv_id = str(item.get("id") or "")
        step = ""
        if status in ("running", "waiting") and conv_id:
            step = STEP_NAMES.get(_last_tool_name(_transcript_path(conv_id)), "")
            # The list only uses a waiting result read in the last 15 seconds; it never reads for itself.
            pending = _cached_waiting(conv_id, LIST_WAITING_SECONDS)
            status = "waiting" if pending else "running"
        return {"status": status, "preview": item.get("preview", ""),
                "modified": int(item.get("updated") or 0),
                "turn_started": int(item.get("turn_started") or 0),
                "turn_ended": int(item.get("turn_ended") or 0), "step": step}

    def project_group(self, item: dict):
        import chat_projects
        folder = str(item.get("cwd") or "")
        if not folder:
            return chat_projects.OTHER_KEY, chat_projects.OTHER_NAME, ""
        name = Path(folder).name or folder
        return "f:" + folder.casefold(), name, ""

    # -- read
    def transcript(self, tid: str):
        """(item, transcript-like entry) for the shared readers that ask an interface assistant (files, a message)."""
        import threading
        from types import SimpleNamespace

        item = self.find(tid)
        path = _transcript_path(item["id"])
        if not path.is_file():
            raise NotFound("没找到这个对话的记录文件")
        messages = [dict(message) for message in _records(path)]
        _fill_cut(messages, item["id"])
        for message in messages:
            message.pop("_truncated", None)
            message.pop("_finish_cut", None)
            message.pop("_step", None)
            message.pop("_picture", None)
            message.pop("_system_user", None)
        try:
            stat = path.stat()
            size, mtime = stat.st_size, stat.st_mtime_ns
        except OSError:
            size, mtime = 0, 0
        return item, SimpleNamespace(messages=messages, by_id={message["id"]: message for message in messages},
                                     state={"running": item.get("status") == "running"}, context={},
                                     offset=0, size=size, mtime=mtime, lock=threading.RLock())

    def read(self, conv_id: str, *, limit: int = 60, before: str = "",
             around: str = "", lite: bool = False) -> dict:
        item = self.find(conv_id)
        path = _transcript_path(item["id"])
        out = {"app": self.id, "id": item["id"], "title": item["title"],
               "folder": item.get("folder", ""), "cwd": item.get("cwd", ""),
               "status": item.get("status", "unknown"), "runtime": {},
               "turn_started": int(item.get("turn_started") or 0),
               "turn_ended": int(item.get("turn_ended") or 0),
               "step": self.summary(item).get("step", "") if item.get("status") == "running" else "",
               "modified": int(item.get("updated") or 0), "size": 0,
               "messages": [], "has_more": False, "next_cursor": "", "has_newer": False,
               "reset": False, "total": 0}
        if not path.is_file():
            out["note"] = "没找到这个对话的记录文件"
            return out
        try:
            out["size"] = path.stat().st_size
        except OSError:
            pass
        messages = _records(path)
        try:
            size = max(1, min(100, int(limit or 60)))
        except (TypeError, ValueError):
            size = 60
        end = len(messages)
        reset = False
        if before:
            at = next((index for index, message in enumerate(messages) if message["id"] == before), None)
            if at is None:
                reset = True
            else:
                end = at
        if around:
            at = next((index for index, message in enumerate(messages) if message["id"] == around), None)
            if at is not None:
                end = min(len(messages), at + size // 2 + 1)
        start = max(0, end - size)
        page = [dict(message) for message in messages[start:end]]
        _fill_cut(page, item["id"])
        for message in page:
            message.pop("_truncated", None)
            message.pop("_finish_cut", None)
            message.pop("_step", None)
            message.pop("_picture", None)
            message.pop("_system_user", None)
            if len(message.get("text") or "") > MESSAGE_TEXT_LIMIT:
                message["text"] = message["text"][:MESSAGE_TEXT_LIMIT] + "\n…（太长，后面略）"
        out["messages"] = page
        out["has_more"] = start > 0
        out["next_cursor"] = page[0]["id"] if start > 0 and page else ""
        out["has_newer"] = end < len(messages)
        out["reset"] = reset
        out["total"] = len(messages)
        return out

    def state(self, conv_id: str, *, fresh: bool = False) -> dict:
        item = self._find(conv_id, fresh)
        status = item.get("status") or "unknown"
        running = status == "running"
        step = ""
        questions: list[dict] = []
        if running and item.get("id"):
            step = STEP_NAMES.get(_last_tool_name(_transcript_path(item["id"])), "")
            # Reading the app's waiting steps is at most once every 3 seconds, and only for a running turn.
            questions = _waiting_cards(str(item["id"]))
            if questions:
                status = "waiting"
        return {"available": True, "running": running, "status": status, "turn_id": "",
                "turn_started": int(item.get("turn_started") or 0),
                "turn_ended": int(item.get("turn_ended") or 0), "step": step,
                "settings": {}, "runtime": {}, "questions": questions, "tasks": [],
                "queued": [], "queue_available": False, "stop_token": ""}

    # -- acting

    def send(self, payload: dict, *, media: list[dict] | None = None) -> dict:
        """Send the user's words through the app's own SendUserCascadeMessage (not agentapi send-message).

        Only pictures that http_send checked and re-encoded reach this method; a `media` field in the phone's
        own request is never used. Full auto is turned on first, and a running turn takes the message queued.
        """
        conv_id = str(payload.get("id") or "").strip()
        text = str(payload.get("text") or "")
        media = list(media or [])
        if not text.strip() and not media:
            raise ControlError("消息不能为空", 400)
        if len(text) > SEND_LIMIT:
            raise ControlError(f"消息太长（最多 {SEND_LIMIT:,} 字）", 400)
        if not text.strip():
            text = "请查看这些图片。"
        data = _hub(0)
        if data is None:
            raise ControlError(f"{NOT_OPEN}，开了再发", 409)
        # The newest database, not the 2-second list cache: a turn that just ended must be able to take a message.
        item = self._find(conv_id, fresh=True)
        warning = ""
        if not _turbo_stored(str(item["id"])):
            try:
                _set_turbo(str(item["id"]))
            except ControlError as exc:
                # A changed app must not make sending impossible: say so and send anyway.
                _log_once("全自动没有打开", str(exc))
                warning = "；全自动没打开，命令可能要你在手机上批准"
        busy = item.get("status") != "idle"
        before = _records(_transcript_path(item["id"]))
        _send_user_message(str(item["id"]), text, media=media, busy=busy)
        with _LOCK:
            _SENT[str(item["id"])] = {"at": time.time(), "count": len(before), "text": text}
        return {"ok": True, "accepted": True, "pressed": False, "offset": 0,
                "request_id": str(payload.get("request_id") or ""),
                "text": (QUEUED_SEND if busy else "已交给 Antigravity") + warning,
                "delivery_state": "queued" if busy else "accepted",
                "accepted_at": int(time.time() * 1000)}

    def stop(self, payload: dict) -> dict:
        """Stop the turn that is running in this conversation."""
        conv_id = str(payload.get("id") or "").strip()
        if _hub(0) is None:
            raise ControlError(NOT_OPEN, 409)
        item = self._find(conv_id, fresh=True)
        if item.get("status") not in ("running", "waiting"):
            raise ControlError(NOT_RUNNING, 409)
        try:
            _rpc("CancelCascadeInvocation", {"cascadeId": str(item["id"]), "killBackgroundTasks": True},
                 timeout=SEND_TIMEOUT)
        except ControlError as exc:
            if exc.status == 409:
                raise
            raise ControlError(f"Antigravity 没有停下来：{exc}", 502) from None
        _forget_waiting(str(item["id"]))
        return {"ok": True, "text": "已让 Antigravity 停下"}

    def check(self, conv_id: str, offset: int = 0, text: str = "") -> dict:
        """Whether the transcript now has a new user message that begins with the text we sent."""
        item = self._find(conv_id)
        conv_id = str(item["id"])
        with _LOCK:
            mark = dict(_SENT.get(conv_id) or {})
        wanted = (str(text or "") or str(mark.get("text") or "")).strip()
        if not wanted:
            return {"delivered": False, "queued": False, "stage": "sent"}
        start = int(mark.get("count") or 0)
        sent_at = float(mark.get("at") or 0)
        for index, message in enumerate(_records(_transcript_path(conv_id))):
            if message.get("role") != "user":
                continue
            # Only messages that appeared after the send; without a mark every user message counts.
            if start or sent_at:
                later = index >= start or bool(sent_at and _seconds(message.get("time")) >= sent_at)
                if not later:
                    continue
            if _same_start(message.get("text"), wanted):
                return {"delivered": True, "queued": False, "stage": "received"}
        return {"delivered": False, "queued": False, "stage": "sent"}

    def answer(self, payload: dict) -> dict:
        """One phone approval: only a card that is still pending right now may be answered."""
        conv_id = str(payload.get("id") or "").strip()
        question_id = str(payload.get("question_id") or "")
        answers = payload.get("answers")
        choice = None
        if isinstance(answers, dict):
            given = answers.get("decision")
            if isinstance(given, list) and len(given) == 1 and isinstance(given[0], str):
                choice = APPROVAL_CHOICES.get(given[0].strip())
        if choice is None:
            raise ControlError("这个选项不存在，请刷新后重选", 400)
        if _hub(0) is None:
            raise ControlError(NOT_OPEN, 409)
        # Read the waiting steps again (no cache): an approval handled on the phone or the PC is gone.
        step = next((one for one in waiting_steps(conv_id, max_age=0) if _card_id(one) == question_id), None)
        if step is None:
            raise ControlError("这个批准已经处理过或已失效，请刷新", 409)
        allow, scope, done_text = choice
        body = {"cascadeId": conv_id, "interaction": {
            "trajectoryId": str(step.get("trajectory_id") or ""),
            "stepIndex": int(step.get("step_index") or 0),
            "permission": {"allow": allow, "scope": scope}}}
        try:
            _rpc("HandleCascadeUserInteraction", body, timeout=ANSWER_TIMEOUT)
        except ControlError as exc:
            if exc.status == 409:
                raise
            raise ControlError(f"Antigravity 没接受这次批准：{exc}", 502) from None
        _forget_waiting(conv_id)
        return {"ok": True, "accepted": True, "text": done_text}

    # -- new conversations

    def new_own_folders(self, svc) -> list[tuple[str, str, str]]:
        """Antigravity's project folders, so the new panel lists project names and their folders."""
        rows = []
        for project in _projects():
            for path in project["folders"]:
                rows.append((path, "Antigravity 项目", project["name"]))
        return rows

    def new_options(self, svc) -> dict:
        """Projects for the picker; the model is fixed, so there is nothing to choose."""
        projects = _projects()
        return {"models": [], "note": f"新建对话固定用 {MODEL}，手机上不用选模型",
                "projects": projects,
                "default_project": projects[0]["id"] if projects else ""}

    def create(self, payload: dict) -> dict:
        """Create a conversation with the fixed warm-up, wait until idle, turn full auto on, then send."""
        request_id = str(payload.get("request_id") or "")
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ControlError("消息不能为空", 400)
        if len(text) > SEND_LIMIT:
            raise ControlError(f"消息太长（最多 {SEND_LIMIT:,} 字）", 400)
        if payload.get("attachments"):
            raise ControlError("新建对话暂不支持带图片，请建好后再发", 400)
        if payload.get("references"):
            raise ControlError("新建对话暂不支持引用，请先建好对话再发", 400)
        data = _hub(0)
        if data is None:
            raise ControlError(NOT_OPEN, 409)
        if not _projects():
            raise ControlError("电脑上没有 Antigravity 项目，不能新建对话", 400)
        folder = str(payload.get("folder") or "").strip()
        project = _project_for_folder(folder)
        if project is None:
            raise ControlError("这个文件夹不属于任何 Antigravity 项目，请重新选择", 400)
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), text)
        title = _one_line(first_line, 40) or TITLE_FALLBACK
        answer = _agentapi(["new-conversation", f"--model={MODEL}", f"--title={title}", WARM_UP],
                           data, timeout=SEND_TIMEOUT, project=project["id"])
        response = answer.get("response") if isinstance(answer.get("response"), dict) else {}
        created = response.get("newConversation") if isinstance(response.get("newConversation"), dict) else {}
        conv_id = str(created.get("conversationId") or "").strip()
        if not conv_id:
            raise ControlError("Antigravity 没给出新对话的编号，请到电脑上看看", 502)
        self._wait_warm_up(conv_id)
        warning = ""
        try:
            _set_turbo(conv_id)
        except ControlError as exc:
            _log_once("全自动没有打开", str(exc))
            warning = "；全自动没打开，命令可能要你在手机上批准"
        _send_user_message(conv_id, text, busy=False)
        shown_folder = folder or (project["folders"][0] if project["folders"] else "")
        result = {"request_id": request_id, "state": "accepted", "app": self.id, "id": conv_id,
                  "title": title, "folder": Path(shown_folder).name if shown_folder else "",
                  "message": "Antigravity 已建好对话" + warning}
        if request_id:
            with _LOCK:
                _CREATED[request_id] = dict(result)
        return result

    def create_status(self, request_id: str) -> dict:
        with _LOCK:
            found = _CREATED.get(str(request_id or ""))
        if found is not None:
            return dict(found)
        return {"request_id": str(request_id or ""), "state": "unconfirmed",
                "message": "没有这次新建的记录，请到电脑上看对话列表"}

    def _warm_up_answer(self, conv_id: str) -> tuple[str, bool]:
        """('error text' or '', whether the warm-up's first user message already has an answer)."""
        messages = _records(_transcript_path(conv_id), hide_warm_up=False)
        first = next((index for index, message in enumerate(messages) if message.get("role") == "user"), None)
        after = messages[first + 1:] if first is not None else messages
        error = next((message for message in after
                      if message.get("role") == "event"
                      and str(message.get("text") or "").startswith("出错：")), None)
        if error is not None:
            return str(error.get("text") or ""), False
        if first is None:
            return "", False
        return "", any(message.get("role") in ("assistant", "tool") for message in after)

    def _wait_warm_up(self, conv_id: str) -> None:
        """Wait up to two minutes for the warm-up turn: idle and its first user message already answered."""
        deadline = _now() + NEW_WAIT_SECONDS
        while True:
            try:
                status = self._find(conv_id, fresh=True).get("status")
            except NotFound:
                status = ""
            error, answered = self._warm_up_answer(conv_id)
            if error:
                raise ControlError(f"新建的 Antigravity 对话在预热时出错：{error}", 502)
            if status == "idle" and answered:
                return
            if _now() >= deadline:
                raise ControlError(
                    f"新建的 Antigravity 对话在 {int(NEW_WAIT_SECONDS)} 秒内没有空闲，请到电脑上看看", 502)
            time.sleep(NEW_POLL_SECONDS)

    def _message_seen(self, conv_id: str, text: str) -> bool:
        return any(message.get("role") == "user" and _same_start(message.get("text"), text)
                   for message in _records(_transcript_path(conv_id)))

    def validate_new_references(self, refs: list) -> None:
        import chats
        if refs:
            raise chats.ChatError("新建 Antigravity 对话暂不支持引用，请建好后再发")

    def prepare_new_submission(self, svc, rid: str, data: dict, body: dict) -> None:
        import chats
        if data.get("attachments"):
            raise chats.ChatError("新建 Antigravity 对话暂不支持带图片，请建好后再发")
        if data.get("references"):
            raise chats.ChatError("新建 Antigravity 对话暂不支持引用，请建好后再发")

    def run_new(self, svc, rid: str, data: dict, trace) -> None:
        """The shared new-conversation worker: warm-up, wait for its answer, full auto, then the real words."""
        import chats
        text = str(data.get("compiled") or data.get("text") or "").strip()
        if not text:
            raise chats.SendNotSubmitted("没有要发的第一句话，尚未创建对话")
        conv_id = str(data.get("id") or "").strip()
        if not conv_id:
            app = _hub(0)
            if app is None:
                raise chats.SendNotSubmitted(f"{NOT_OPEN}，没有建对话")
            if not _projects():
                raise chats.SendNotSubmitted("电脑上没有 Antigravity 项目，不能新建对话")
            project = _project_for_folder(str(data.get("folder") or ""))
            if project is None:
                raise chats.SendNotSubmitted("这个文件夹不属于任何 Antigravity 项目，请重新选择")
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), text)
            title = _one_line(first_line, 40) or TITLE_FALLBACK
            trace.phase("antigravity_create", "在 Antigravity 里建对话")
            try:
                answer = _agentapi(["new-conversation", f"--model={MODEL}", f"--title={title}", WARM_UP],
                                   app, timeout=SEND_TIMEOUT, project=project["id"])
            except ControlError as exc:
                if "超时" in str(exc):
                    raise
                raise chats.SendNotSubmitted(f"Antigravity 没有建好对话：{exc}") from None
            response = answer.get("response") if isinstance(answer.get("response"), dict) else {}
            created = response.get("newConversation") if isinstance(response.get("newConversation"), dict) else {}
            conv_id = str(created.get("conversationId") or "").strip()
            if not conv_id:
                raise chats.SendNotSubmitted("Antigravity 没给出新对话的编号，没有建好")
            data.update(id=conv_id, title=title)
            svc._save(rid, "prepared", data, {"message": "对话已建好，正在准备…"})
        trace.phase("antigravity_warm_up", "等预热这一轮答完")
        self._wait_warm_up(conv_id)
        warning = ""
        if not _turbo_stored(conv_id):
            try:
                _set_turbo(conv_id)
            except ControlError as exc:
                _log_once("全自动没有打开", str(exc))
                warning = "；全自动没打开，命令可能要你在手机上批准"
        trace.phase("antigravity_dispatch", "发出第一句话")
        svc._save(rid, "dispatching", data, {"message": "正在发出第一句话…"})
        _send_user_message(conv_id, text, busy=False)
        data["accepted_message"] = "首条消息已送达" + warning

    def handle_new_error(self, svc, rid: str, state: str, data: dict, trace, exc: Exception) -> tuple[bool, bool]:
        import chats
        if state == "prepared":
            return False, True
        if state == "dispatching" and data.get("id"):
            text = str(data.get("compiled") or data.get("text") or "")
            if self._message_seen(str(data["id"]), text):
                data["accepted_message"] = "首条消息已送达"
                svc._save(rid, "accepted", data, {"message": "首条消息已送达"})
                return True, False
            return False, False
        return False, isinstance(exc, chats.SendNotSubmitted) and state != "dispatching"

    def reconcile_new_status(self, svc, rid: str, state: str, data: dict, result: dict) -> tuple[str, dict]:
        if data.get("id") and state in ("dispatching", "unconfirmed"):
            text = str(data.get("compiled") or data.get("text") or "")
            if self._message_seen(str(data["id"]), text):
                state, result = "accepted", {"message": "首条消息已送达"}
                svc._save(rid, state, data, result)
        if state == "prepared":
            state, result = "failed", {"message": "对话已建好，第一句话还没发出；可以继续发送",
                                       "not_submitted": True}
            svc._save(rid, state, data, result)
        return state, result

    # -- pictures

    def _upload_for_chat(self, handler, tid: str, name: str, raw: bytes) -> dict:
        """The shared uploader: checks the conversation, the picture, animation and size, and cleans old drafts."""
        return handler.server.codex.upload(tid, name, raw, self.id)

    def http_upload(self, handler) -> None:
        """An upload bigger than 20 MB is a 400 here (the shared uploader would say 413)."""
        import chats
        import codex_control
        try:
            size = int(handler.headers.get("Content-Length") or 0)
            if not 0 < size <= MAX_PICTURE_BYTES:
                handler.close_connection = True
                raise ControlError("单张图片不能超过 20 MB，没有发给 Antigravity", 400)
            q = handler._query()
            raw = handler.rfile.read(size)
            if len(raw) != size:
                raise ControlError("图片上传不完整，没有发给 Antigravity", 400)
            if q.get("draft"):
                raise ControlError("新建对话暂不支持带图片", 400)
            handler._json(self._upload_for_chat(handler, q.get("id", ""), q.get("name", "图片"), raw))
        except ControlError as exc:
            handler._json({"error": str(exc)}, exc.status)
        except (codex_control.ControlError, chats.ChatError) as exc:
            handler._json({"error": str(exc)}, getattr(exc, "status", 400))
        except Exception as exc:
            handler._json({"error": str(exc) or "图片没有收到"}, getattr(exc, "status", 400))

    def http_send(self, handler, body: dict) -> None:
        """A message with pictures: every picture is decoded and re-encoded before any of them is sent."""
        images = []
        try:
            ids = body.get("attachments")
            media = []
            total = 0
            if ids:
                if (not isinstance(ids, list) or len(ids) > MAX_PICTURES
                        or any(not isinstance(value, str) or not value for value in ids)
                        or len(set(ids)) != len(ids)):
                    raise ControlError(f"一次最多发 {MAX_PICTURES} 张图片，这条没有发出去", 400)
                images = [handler.server.codex.attachment(value, str(body.get("id") or "")) for value in ids]
                for image in images:
                    item, size = send_picture(image)
                    media.append(item)
                    total += size
                if total > SEND_PICTURE_TOTAL_LIMIT:
                    raise ControlError("图片合计太大，这条没有发出去", 400)
            # The phone's own media field is never forwarded: only the pictures prepared just above may go out.
            payload = {key: value for key, value in body.items() if key != "media"}
            if media:
                if not str(payload.get("text") or "").strip():
                    payload["text"] = "请查看这些图片。"
            result = self.send(payload, media=media)
            for image in images:
                image["used"] = True
                try:
                    handler.server.codex._write_meta(image)
                except Exception:
                    pass
            handler._json(result)
        except ControlError as exc:
            handler._json({"error": str(exc), "not_submitted": True}, exc.status)
        except Exception as exc:
            handler._json({"error": str(exc) or "图片没有发出去", "not_submitted": True},
                          getattr(exc, "status", 400))

    # -- notify
    def notify_conversations(self, limit: int) -> tuple[list[dict], list[dict]]:
        rows = _top_level(_all_rows())
        rows.sort(key=lambda row: (-int(row.get("updated") or 0), row.get("id") or ""))
        recent = []
        for row in rows[:max(0, int(limit or 0))]:
            item = _trim(row)
            item["_running"] = item.get("status") == "running"
            recent.append(item)
        full = []
        for row in rows:
            item = _trim(row)
            item["_running"] = item.get("status") == "running"
            full.append(item)
        return recent, full

    def notify_poll(self, notifier, found, item: dict) -> bool:
        from datetime import datetime
        conv = (self.id, str(item.get("id") or ""))
        status = item.get("status") or "unknown"
        initial = conv not in notifier.ended
        if initial:
            notifier.ended[conv] = "observed"
            if status != "running":
                return True  # already idle when 遥应 started: not a turn that just ended
        if status == "unknown":
            return True  # cannot tell: leave whatever was already said alone
        path = _transcript_path(item["id"]) if item.get("id") else None
        if status == "running":
            cards = _waiting_cards(str(item.get("id") or ""))
            if cards:
                previous = notifier.running.pop(conv, None) or {}
                started = int(previous.get("since") or item.get("turn_started") or notifier.clock())
                notifier.waiting[conv] = {"since": started, "title": item.get("title", ""), "item": item}
                key = "waiting:" + ",".join(card["id"] for card in cards)
                # One notice for each set of waiting cards: the same card is never told twice.
                if notifier.ended.get(conv) != key:
                    notifier.ended[conv] = key
                    notifier._tell(found, item, {"state": "done", "key": key, "time": "", "asks": True,
                                                 "text": item.get("preview", ""), "started": started,
                                                 "ended": int(notifier.clock()),
                                                 "started_source": "记录" if item.get("turn_started") else "不知道"})
                return True
            # Approved and still running: back to running (said once more only if it had been waiting).
            if notifier.waiting.pop(conv, None) is not None:
                notifier.reported_running.discard(conv)
            started = int(item.get("turn_started") or 0)
            started_iso = datetime.fromtimestamp(started).isoformat() if started else ""
            action = STEP_NAMES.get(_last_tool_name(path), "") if path is not None else ""
            notifier._running(item, {"started": started_iso, "key": str(item.get("updated") or ""),
                                     "action": action})
            if action:
                notifier._step(item, {"action": action}, notifier.relay_on())
            return True
        previous = notifier.running.pop(conv, None) or notifier.waiting.pop(conv, None) or {}
        notifier.waiting.pop(conv, None)
        notifier.reported_running.discard(conv)
        if not previous:
            return True  # it was not seen running: no turn of ours just ended
        key = f"done:{item.get('id')}:{item.get('updated') or 0}"
        if notifier.ended.get(conv) == key:
            return True
        notifier.ended[conv] = key
        failed = path is not None and _last_record_type(path) == "ERROR_MESSAGE"
        started = int(previous.get("since") or item.get("turn_started") or 0)
        try:
            ended = int(item.get("turn_ended") or notifier.clock())
        except (TypeError, ValueError):
            ended = int(notifier.clock())
        notifier._tell(found, item, {"state": "failed" if failed else "done", "key": key, "time": "",
                                     "text": item.get("preview", ""), "started": started, "ended": ended,
                                     "started_source": "记录" if item.get("turn_started") else "不知道"})
        return True


AGENT = AntigravityAgent
