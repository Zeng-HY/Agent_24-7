"""Antigravity desktop, read-only: its conversation list and the steps of a conversation.

Antigravity is only read from two things it writes on this computer: the summaries database
`conversation_summaries.db` and each conversation's `brain/<id>/.system_generated/logs/transcript.jsonl`.
Nothing else under its data folder is opened, and none of its programs, ports or windows are touched.

The format has no public description and may change in any Antigravity update, so a missing column, a
changed time or one bad row is read as an empty value instead of an error: the list returns what it can.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from .base import Agent, NotFound, make_manifest

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

_TIME_FRACTION = re.compile(r"(\.\d{6})\d")
_ISO_FRACTION = re.compile(r"(\.\d{3})\d+")

_LOCK = threading.Lock()
_LIST_CACHE: dict = {"path": None, "stamp": None, "at": 0.0, "rows": None}
_MESSAGE_CACHE: dict[str, tuple] = {}
_FULL_CACHE: dict[str, tuple] = {}
_LOGGED: set[tuple[str, str]] = set()
_LOG_WRITER = [None]


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


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


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
    title = _one_line(_text(_row_value(row, "title")), 120)
    if title:
        return title
    preview = _one_line(_text(_row_value(row, "preview")), 40)
    return preview or TITLE_FALLBACK


def _item_of(row) -> dict:
    conv_id = str(_row_value(row, "conversation_id") or "").strip()
    preview = _one_line(_text(_row_value(row, "preview")), PREVIEW_LIMIT)
    folder = _folder_of(_row_value(row, "workspace_uris"))
    status = _status_of(_row_value(row, "status"))
    modified = _seconds(_row_value(row, "last_modified_time"))
    started = _seconds(_row_value(row, "last_user_input_time"))
    ended = modified if status != "running" else 0
    title = _title_of(row)
    return {
        "app": "antigravity",
        "id": conv_id,
        "title": title,
        "preview": preview or title,
        "folder": Path(folder).name if folder else "",
        "cwd": folder,
        "updated": modified * 1000,
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
    now = time.monotonic()
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


def _records(path: Path) -> list[dict]:
    """Every step of the transcript, in file order; unreadable lines are left out."""
    try:
        stat = path.stat()
    except OSError:
        return []
    key = str(path)
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
        text = content + picture_text
        if not text:
            return []
        message = {"role": "user", "text": text, "time": time_text}
        if picture:
            message["_picture"] = True
        if "content" in cut_fields:
            message["_truncated"] = True
            message["_step"] = record.get("step_index")
        return [message]

    if kind == "PLANNER_RESPONSE":
        if not content:
            return []
        message = {"role": "assistant", "text": content + picture_text, "time": time_text}
        if picture:
            message["_picture"] = True
        if "content" in cut_fields:
            message["_truncated"] = True
            message["_step"] = record.get("step_index")
        return [message]

    if kind == "GENERIC":
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
        if content:
            message = {"role": "assistant", "text": content + picture_text, "time": time_text}
            if picture:
                message["_picture"] = True
            if "content" in cut_fields:
                message["_truncated"] = True
                message["_step"] = record.get("step_index")
            return [message]
        return []

    if kind == "ERROR_MESSAGE":
        reason = _text(record.get("error")) or content
        text = "出错：" + (reason[:2000] if reason else "Antigravity 出错了")
        return [{"role": "event", "text": text, "time": time_text}]

    if kind == "SYSTEM_MESSAGE":
        return []

    # An unknown type is shown as ordinary words when it has any; nothing else about it is guessed.
    if content:
        return [{"role": "assistant", "text": content, "time": time_text}]
    return []


def _number_messages(messages: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for message in messages:
        identity = json.dumps([message.get("time"), message.get("role"), message.get("text")],
                              ensure_ascii=False)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        seen[digest] = seen.get(digest, 0) + 1
        message["id"] = f"{digest}:{seen[digest]}"
    return messages


def _full_contents(path: Path, steps: set[int]) -> dict:
    """The full content of these steps from transcript_full.jsonl; only those steps are kept."""
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = str(path)
    with _LOCK:
        hit = _FULL_CACHE.get(key)
        if hit and hit[0] == stat.st_size and hit[1] == stat.st_mtime_ns and steps <= hit[2]:
            return hit[3]
    found: dict[int, str] = {}
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
                    if isinstance(content, str):
                        found[index] = content
    except OSError:
        return {}
    with _LOCK:
        if len(_FULL_CACHE) >= FULL_CACHE_LIMIT:
            for old in list(_FULL_CACHE)[:len(_FULL_CACHE) - FULL_CACHE_LIMIT + 1]:
                _FULL_CACHE.pop(old, None)
        _FULL_CACHE[key] = (stat.st_size, stat.st_mtime_ns, steps, found)
    return found


def _fill_cut(messages: list[dict], conv_id: str) -> None:
    steps = {message.get("_step") for message in messages if message.get("_truncated")}
    steps = {value for value in steps if isinstance(value, int)}
    if not steps:
        return
    full = _full_contents(_full_path(conv_id), steps)
    for message in messages:
        content = full.get(message.get("_step"))
        if content is not None:
            message["text"] = content + ("\n[图片]" if message.get("_picture") else "")


# ---------------------------------------------------------------- the agent


class AntigravityAgent(Agent):
    id = "antigravity"
    notify_uses_file = False
    # Its sidebar group appears once it has conversations; an empty Antigravity group says nothing.
    sidebar_without_chats = False
    # The list's search box looks in the preview too (Antigravity's list has the user's first words there).
    search_in_preview = True

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
                "send_modes": [],
                "settings": [],
                "skills": False,
                "waiting": False,
                "statuses": ["running", "idle", "unknown"],
            },
            ui={"card_layout": "generic.v1", "waiting_text": "等待你处理"},
            sources={"catalog": "sqlite", "transcript": "jsonl", "control": "none", "live": "file-poll"},
        )

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
        if status in ("running", "idle", "unknown"):
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
        return {"items": [_trim(row) for row in page], "has_more": more,
                "next_cursor": str(start + len(page)) if more else "", "total": len(rows)}

    def catalog_entries(self, limit: int) -> list[dict]:
        """Every recent row the shared list and project tree read (they ask for a very large limit)."""
        rows = _top_level(_all_rows())
        rows.sort(key=lambda row: (-int(row.get("updated") or 0), row.get("id") or ""))
        try:
            size = max(1, int(limit or 40))
        except (TypeError, ValueError):
            size = 40
        return [_trim(row) for row in rows[:size]]

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
        step = ""
        if status == "running" and item.get("id"):
            step = STEP_NAMES.get(_last_tool_name(_transcript_path(item["id"])), "")
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
            message.pop("_step", None)
            message.pop("_picture", None)
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
            message.pop("_step", None)
            message.pop("_picture", None)
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
        if running:
            step = STEP_NAMES.get(_last_tool_name(_transcript_path(item["id"])), "")
        return {"available": True, "running": running, "status": status, "turn_id": "",
                "turn_started": int(item.get("turn_started") or 0),
                "turn_ended": int(item.get("turn_ended") or 0), "step": step,
                "settings": {}, "runtime": {}, "questions": [], "tasks": [],
                "queued": [], "queue_available": False, "stop_token": ""}

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
            notifier.waiting.pop(conv, None)
            started = int(item.get("turn_started") or 0)
            started_iso = datetime.fromtimestamp(started).isoformat() if started else ""
            action = STEP_NAMES.get(_last_tool_name(path), "") if path is not None else ""
            notifier._running(item, {"started": started_iso, "key": str(item.get("updated") or ""),
                                     "action": action})
            if action:
                notifier._step(item, {"action": action}, notifier.relay_on())
            return True
        previous = notifier.running.pop(conv, None) or {}
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
