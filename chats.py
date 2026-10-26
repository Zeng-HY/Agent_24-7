"""Conversations on this PC for the phone page: Codex desktop threads and Claude desktop sessions.

Nothing here needs a screenshot.

Lists and messages come from the apps' own files:
- Codex: the `threads` table in ~/.codex/state_<n>.sqlite (title, folder, rollout file); each
  conversation is a rollout .jsonl under ~/.codex/sessions.
- Claude: one small index file per Code session in the app's package folder (title, folder,
  transcript id); the conversation is a .jsonl under ~/.claude/projects.

Sending uses each app's own link, then one key press:
- Codex:  codex://threads/<id>?prompt=<text> opens the thread, fills the message box and puts the
          cursor in it; Enter sends. codex://threads/new?prompt=<text>&path=<folder> starts a thread.
- Claude: claude://claude.ai/epitaxy/<session>?r=<random> opens the session (the random tail keeps
          Claude from ignoring a repeated link; the switch can take many seconds on a busy PC); the
          message box ("Prompt") is found through UI Automation, the text is written and read back,
          and the Send button is pressed.
A send counts as delivered only when the message shows up in the conversation file: Codex writes a
UserMessage item, Claude an enqueue record.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlsplit

import win32con
import win32gui
import win32process

import winctl

HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or HOME / ".codex")
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local")
APPDATA = Path(os.environ.get("APPDATA") or HOME / "AppData" / "Roaming")

CODEX_PROCESS = "chatgpt.exe"  # the Codex desktop app runs as ChatGPT.exe
CLAUDE_PROCESS = "claude.exe"
URL_PREFILL_LIMIT = 1800       # longer text goes in by paste; a link that long may be cut somewhere
PLACEHOLDER = "…"
MAX_TEXT = 20000
STALE_SECONDS = 20 * 60        # "running" with no file change for this long is shown as unknown
# A claude:// link starts a second Claude.exe that hands it to the running app. On a busy PC that took
# 1-20 s (Claude's main.log, 10-11); the old 6 s limit gave up before the switch, so the first send from
# the phone failed and the session showed up afterwards with an empty message box.
CLAUDE_SWITCH_WAIT = 25
CLAUDE_PROMPT_WAIT = 8         # after the switch, until the session's message box is there
# Keyboard or mouse used this recently: someone is at the PC, and gets the keyboard back after a send (_give_back_keyboard)
KEYBOARD_IN_USE = 120
# After a sidebar click Claude logs the switch at once, but a very long session can take half a minute to draw: 37 s
# for one with a 42 MB record (10-12). The whole send has to fit in the 60 s the service gives it.
CLAUDE_SWITCH_TAKEN_WAIT = 45
_FOCUS_LINE = re.compile(rb"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[info\] \[CCD\] LocalSessions\.setFocusedSession: sessionId=(\S+)")
CLAUDE_NO_FOLDER = "No folder"  # a new session in no folder: the first item of the folder menu, then the folder button's name
# What Claude's sidebar says of a session after its title (claude.ai's page code, 10-26: waiting on a permission, on a
# question, running, using the browser, unread, idle, done); before Claude 2.1.299 (10-15) it came before the title.
CLAUDE_ROW_STATES = ("Running", "Awaiting input", "Awaiting answer", "Using the browser", "Unread response", "Idle", "Done")
_CLAUDE_ROW_STATE = re.compile("|".join(CLAUDE_ROW_STATES))
# after '<title> ' in a row's name: a state, or the line under the title ('Started by Claude from <parent>', 'Started
# from a suggestion in <project>'), with or without a state before it
_CLAUDE_ROW_ENDING = re.compile(rf"(?:(?:{_CLAUDE_ROW_STATE.pattern}) )?Started (?:by|from) .+|{_CLAUDE_ROW_STATE.pattern}")
_CLAUDE_ROW_ID = re.compile(r"_r_[0-9a-z]+_(local_[0-9a-fA-F-]{36})")  # React's id for a row's part, then the session id

# buttons that always sit around Claude's message box; the phone lists only the others
# Get more usage: the usage-limit notice above the box ("Approaching weekly usage limit · Resets … · Get more usage ·
# Dismiss"), shown on the phone as a choice Claude waited on (10-16). The notice is a status bar, and nothing in a status
# bar is a question any more (in_notice); the name stays here too.
CLAUDE_FIXED_BUTTONS = {"Add", "Press and hold to record", "Dictation settings", "Send", "Stop", "Dismiss", "Auto",
                        "Attach", "Voice mode", "Show more", "Show less", "New messages", "Get more usage"}
# "Scroll to bottom" shows up whenever the desktop chat is scrolled up; like the other page-moving and
# attachment buttons it is not a question Claude is waiting on, so it must not count as a pending option
# Usage: the meter by the model; "Usage: Context 527k / 1M (53%), Weekly · …", but "Usage, Weekly · all models: 38%, …"
# while a conversation has no context figure yet, and that one was shown on the phone as a choice Claude waited on (10-14)
CLAUDE_FIXED_PREFIXES = ("Model:", "Effort:", "Usage:", "Usage,", "Permission", "Environment:",
                         "Folder:", "Claude thinks longer with Max effort", "Scroll ", "Jump to", "Remove ")
OPTION_TYPES = ("ButtonControl", "RadioButtonControl", "CheckBoxControl", "ListItemControl", "MenuItemControl",
                "HyperlinkControl", "TabItemControl", "EditControl", "ComboBoxControl")
# Claude's new window asks a question (AskUserQuestion) in a card of this class among the messages, not in the dock (10-26)
CLAUDE_QUESTION_CARD = "epitaxy-approval-card"


def in_notice(kinds: list[str]) -> bool:
    """Whether a control whose ancestors in the dock are these control types sits in a notice bar. Claude's notices
    (the usage limit, 10-16) are status bars; a question (AskUserQuestion, recorded 10-11) is a group and never is."""
    return "StatusBarControl" in kinds


def question_card(ctrl) -> bool:
    """Whether this is one of the question cards of Claude's new window rather than the dock."""
    try:
        return CLAUDE_QUESTION_CARD in (ctrl.ClassName or "")
    except Exception:
        return False


class ChatError(Exception):
    """Something the person can act on."""


class SendNotSubmitted(ChatError):
    not_submitted = True
    code = 'desktop_unavailable'


class InputNotSubmitted(SendNotSubmitted):
    code = 'input_not_ready'


class DesktopDraft(InputNotSubmitted):
    """Claude's message box holds text that is not this message: someone's draft, or a key pressed on the PC (10-12: an
    'e'). It is never overwritten on its own; the phone shows it and may send again naming that exact text to replace."""
    code = 'desktop_draft'

    def __init__(self, message: str, draft: str):
        super().__init__(message)
        self.draft = draft


def require_send_desktop():
    if not winctl.input_desktop_ready():
        raise SendNotSubmitted('电脑已锁屏或交互桌面不可用，尚未发送；解锁后可恢复草稿再发送')


# ---------------------------------------------------------------- text helpers

_WS = re.compile(r"[\s​‌‍﻿]+")
_CLAUDE_TAGS = re.compile(
    r"<(system-reminder|command-name|command-message|command-args|local-command-stdout|local-command-stderr|"
    r"session-mentions|local-command-caveat)>.*?</\1>", re.S)


def norm(text: str) -> str:
    """For matching: no whitespace, one Unicode form."""
    return _WS.sub("", unicodedata.normalize("NFC", text or ""))


def one_line(text: str, n: int = 100) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def plain(text: str) -> str:
    """Markdown marks out, for one-line previews."""
    text = re.sub(r"```[a-zA-Z0-9_-]*", " ", text or "")
    text = re.sub(r"\*\*|__|`|^#+\s*|^\s*[-*]\s+|\|", " ", text, flags=re.M)
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def clean_text(text: str) -> str:
    """The message as it will be sent; checks it is sendable."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise ChatError("没有要发送的文字")
    if len(text) > MAX_TEXT:
        raise ChatError(f"太长了（{len(text)} 字），一次最多 {MAX_TEXT} 字")
    return text


def task_notice(text: str) -> str | None:
    """A background-task notice that Claude Code writes as a user message: keep only its summary."""
    if not text.lstrip().startswith("<task-notification>"):
        return None
    found = re.search(r"<summary>(.*?)</summary>", text, re.S)
    return "后台任务：" + (found.group(1).strip() if found else "有结果了")


def clean_claude_user(text: str) -> str:
    return _CLAUDE_TAGS.sub("", text or "").strip()


_COMMAND_NAME = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
_COMMAND_ARGS = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)
_COMMAND_OUTPUT = re.compile(r"<local-command-(?:stdout|stderr)>")


def claude_command(text: str) -> str:
    """The slash command a Claude user line holds, as typed ("/compact", "/model opus"); '' for anything else. Claude
    records a command in tags, never as the words sent, so a /compact from the phone stayed 排队中 for good (10-20)."""
    name = _COMMAND_NAME.search(text or "")
    if not name or not name.group(1):
        return ""
    command = name.group(1) if name.group(1).startswith("/") else "/" + name.group(1)
    args = _COMMAND_ARGS.search(text)
    return f"{command} {args.group(1)}" if args and args.group(1) else command


def clean_codex_user(text: str) -> str:
    text = (text or "").strip()
    envelope=re.fullmatch(r'<send_user_message_question_reply>\s*([\s\S]*?)\s*</send_user_message_question_reply>',text)
    if envelope:
        try:
            answers=json.loads(envelope[1])
            if isinstance(answers,list) and answers and all(isinstance(v,dict) and isinstance(v.get('answer'),str) and isinstance(json.loads(v.get('questionItemId','null')),list) and json.loads(v['questionItemId'])[0]=='request_user_input_async' for v in answers):
                return '\n\n'.join(v['answer'] for v in answers)
        except (ValueError,TypeError,KeyError,IndexError):pass
    if text.startswith("<heartbeat>"):
        return "[自动任务]"
    if text.startswith("# Files mentioned by the user"):
        files = len(re.findall(r"^## (?!My request).+?:", text, re.M))
        found = re.search(r"^## My request[^\n]*:\s*\n", text, re.M)
        body = text[found.end():].strip() if found else ""
        return (f"[附件 {files} 个] " if files else "[附件] ") + body
    return text


def _join_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _strip_unc(path: str) -> str:
    return path[4:] if path.startswith("\\\\?\\") else path


# ---------------------------------------------------------------- reading files


def read_tail(path: Path, nbytes: int) -> tuple[list[bytes], bool]:
    """Whole lines from the last nbytes of a file, and whether the start of the file was reached."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        offset = max(0, size - nbytes)
        f.seek(offset)
        data = f.read(size - offset)
    if offset:
        cut = data.find(b"\n")
        data = data[cut + 1:] if cut >= 0 else b""
    return [ln for ln in data.split(b"\n") if ln.strip()], offset == 0


def read_from(path: Path, offset: int) -> list[bytes]:
    """Lines written after offset (the size noted before a send)."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size < offset:  # rewritten meanwhile: look at the recent part instead
            offset = max(0, size - (1 << 20))
        f.seek(offset)
        data = f.read(size - offset)
    return [ln for ln in data.split(b"\n") if ln.strip()]


def file_size(path: Path | None) -> int:
    try:
        return path.stat().st_size if path else 0
    except OSError:
        return 0


# ---------------------------------------------------------------- Codex threads


def codex_db() -> Path | None:
    found = []
    for p in CODEX_HOME.glob("state_*.sqlite"):
        m = re.fullmatch(r"state_(\d+)", p.stem)
        if m:
            found.append((int(m.group(1)), p))
    return max(found)[1] if found else None


def _codex_rows(where: str, args: tuple, limit: int) -> list[dict]:
    db = codex_db()
    if db is None:
        return []
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3)
    try:
        cols = {r[1] for r in con.execute("pragma table_info(threads)")}

        def col(name: str, fallback: str) -> str:
            return name if name in cols else fallback

        sql = ("select id, " + col("name", "''") + ", title, cwd, rollout_path, "
               + col("updated_at_ms", "updated_at * 1000") + ", " + col("is_pinned", "0") + ", " + col("created_at_ms", col("created_at", "0") + " * 1000")
               + " from threads where archived = 0 and " + where
               + " order by 6 desc limit ?")
        rows = con.execute(sql, args + (limit,)).fetchall()
    finally:
        con.close()
    out = []
    for tid, name, title, cwd, rollout, updated, pinned, created in rows:
        cwd = _strip_unc(cwd or "")
        label = (name or "").strip()
        if not label:
            first = clean_codex_user(title or "").strip().splitlines()
            label = one_line(first[0], 60) if first else ""
        out.append({"app": "codex", "id": tid, "title": label or "（无标题）", "cwd": cwd,
                    "folder": Path(cwd).name if cwd else "", "updated": int(updated or 0),
                    "path": _strip_unc(rollout or ""), "pinned": bool(pinned), "created": int(created or 0)})
    return out


def codex_threads(limit: int = 60) -> list[dict]:
    # Not the codex exec runs either: the desktop does not list them, and the translation workflows had made 2 115 of 3 045
    # threads (10-14). Reading them all, titles of up to a million characters included, took 0.46 s of the 0.5 s the
    # sidebar waited for; without them 0.04 s. A database without the source column is read as before.
    where = "coalesce(thread_source, '') not in ('subagent', 'guardian_review')"
    try:
        return _codex_rows(where + " and coalesce(source, '') != 'exec'", (), limit)
    except sqlite3.OperationalError:
        return _codex_rows(where, (), limit)


def codex_thread(thread_id: str) -> dict | None:
    rows = _codex_rows("id = ?", (thread_id,), 1)
    return rows[0] if rows else None


def codex_new_thread_since(ms: int, text: str) -> dict | None:
    """The thread a 'new conversation' send created: started after ms, first message matching."""
    want = norm(text)[:40]
    for item in _codex_rows("coalesce(" + "created_at_ms" + ", created_at * 1000) >= ?", (ms - 2000,), 10):
        path = Path(item["path"])
        if not path.is_file():
            continue
        lines, _ = read_tail(path, 1 << 20)
        msgs, _ = parse_codex(lines)
        if any(m["role"] == "user" and want and want in norm(m["text"]) for m in msgs):
            return item
    return None


# ---------------------------------------------------------------- Claude sessions


def claude_main_logs() -> list[Path]:
    packages = LOCALAPPDATA / "Packages"
    logs = [pkg / "LocalCache" / "Local" / "Claude" / "logs" / "main.log" for pkg in packages.glob("Claude_*")] if packages.is_dir() else []
    return [p for p in logs + [LOCALAPPDATA / "Claude" / "logs" / "main.log"] if p.is_file()]


def claude_focus_logged(conv_id: str, since: float) -> bool:
    """Claude's own log says it switched to this session at or after since (time.time(); the log has local time to the
    second). Its lines are not always in time order, so the whole tail is read."""
    after = datetime.fromtimestamp(since - 1).strftime("%Y-%m-%d %H:%M:%S").encode()
    for path in claude_main_logs():
        try:
            lines, _ = read_tail(path, 64 << 10)
        except OSError:
            continue
        for raw in lines:
            m = _FOCUS_LINE.match(raw.rstrip(b"\r"))
            if m and m[1] >= after and m[2].decode(errors="replace") == conv_id:
                return True
    return False


def claude_index_dirs() -> list[Path]:
    dirs = []
    packages = LOCALAPPDATA / "Packages"
    if packages.is_dir():
        for pkg in packages.glob("Claude_*"):
            d = pkg / "LocalCache" / "Roaming" / "Claude" / "claude-code-sessions"
            if d.is_dir():
                dirs.append(d)
    d = APPDATA / "Claude" / "claude-code-sessions"
    if d.is_dir():
        dirs.append(d)
    return dirs


_index_cache: dict[str, tuple[int, dict]] = {}
_transcript_cache: dict[str, Path] = {}


def claude_sessions(limit: int = 60, pending: bool = False) -> list[dict]:
    """pending: also sessions Claude has not yet linked to their record (cliSessionId; cli is None then). A new one
    stays unlinked for 6-7 s after its record holds the first message (10-12); only the new-conversation check wants it."""
    out, seen = [], set()
    for base in claude_index_dirs():  # %APPDATA%\Claude can be a second view of the package folder
        for f in base.glob("*/*/local_*.json"):
            try:
                mtime = f.stat().st_mtime_ns
            except OSError:
                continue
            hit = _index_cache.get(str(f))
            if hit and hit[0] == mtime:
                d = hit[1]
            else:
                try:
                    raw = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                d = {k: raw.get(k) for k in ("sessionId", "cliSessionId", "cwd", "originCwd", "title",
                                             "lastActivityAt", "isArchived")}
                _index_cache[str(f)] = (mtime, d)
            if d.get("isArchived") or not d.get("sessionId") or not (d.get("cliSessionId") or pending) or d["sessionId"] in seen:
                continue
            seen.add(d["sessionId"])
            cwd = d.get("cwd") or d.get("originCwd") or ""
            out.append({"app": "claude", "id": d["sessionId"], "title": (d.get("title") or "").strip() or "（无标题）",
                        "cwd": cwd, "folder": Path(cwd).name if cwd else "", "updated": int(d.get("lastActivityAt") or 0),
                        "cli": d.get("cliSessionId"), "origin": d.get("originCwd") or cwd, "pinned": False})
    out.sort(key=lambda x: -x["updated"])
    return out[:limit]


def claude_transcript(item: dict) -> Path | None:
    cli = item.get("cli")
    if not cli:
        return None
    hit = _transcript_cache.get(cli)
    if hit is not None and hit.exists():
        return hit
    for cwd in (item.get("origin"), item.get("cwd")):
        if cwd:
            p = CLAUDE_PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", cwd) / f"{cli}.jsonl"
            if p.exists():
                _transcript_cache[cli] = p
                return p
    for p in CLAUDE_PROJECTS.glob(f"*/{cli}.jsonl"):
        _transcript_cache[cli] = p
        return p
    return None


# ---------------------------------------------------------------- one conversation


def find(app: str, conv_id: str) -> dict:
    if app == 'deepseek':
        import deepseek_control
        try:return deepseek_control.bridge().find(conv_id)
        except deepseek_control.DeepSeekError as exc:raise ChatError(str(exc)) from None
    if app == "codex":
        item = codex_thread(conv_id)
    elif app == "claude":
        item = next((s for s in claude_sessions(100000) if s["id"] == conv_id), None)
    else:
        raise ChatError(f"不认识的应用 {app}")
    if item is None:
        raise ChatError("找不到这个对话（可能已归档或删掉了）")
    return item


def conv_path(item: dict) -> Path | None:
    if item['app']=='deepseek':return None
    if item["app"] == "codex":
        p = Path(item["path"]) if item.get("path") else None
        return p if p is not None and p.is_file() else None
    return claude_transcript(item)


def _codex_command(item: dict) -> str:
    parsed = item.get("parsed_cmd") or []
    if parsed and isinstance(parsed[0], dict):
        p = parsed[0]
        if p.get("type") == "read" and p.get("name"):
            return "读 " + str(p["name"])
        if p.get("cmd"):
            return one_line(str(p["cmd"]), 120)
    cmd = item.get("command")
    if isinstance(cmd, list) and cmd:
        return one_line(str(cmd[-1]), 120)
    return one_line(str(cmd or "命令"), 120)


def _codex_delegation(item: dict) -> dict | None:
    """The desktop displays this narrow tool envelope as an incoming message."""
    if (item.get("type") != "FunctionCallOutput" or item.get("namespace") != "codex_app"
            or item.get("name") not in ("create_thread", "send_message_to_thread")):
        return None
    output = item.get("output")
    if not isinstance(output, str):
        return None
    match = re.fullmatch(
        r"\s*<codex_delegation>\s*<source_thread_id>\s*"
        r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})"
        r"\s*</source_thread_id>\s*<input>([\s\S]*?)</input>\s*</codex_delegation>\s*", output)
    if not match:
        return None
    # Match the desktop's envelope escaping without interpreting its body as XML.
    text = match[2].strip().replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    if not text:
        return None
    return {"role": "user", "text": text, "source_id": item.get("id"),
            "origin": "other_chat", "source_thread_id": match[1]}


def parse_codex(lines: list[bytes]) -> tuple[list[dict], dict]:
    msgs: list[dict] = []
    state = {"running": None, "turn_time": ""}
    saw_items = False
    for raw in lines:
        if b"event_msg" not in raw[:160] and b"response_item" not in raw[:160]:
            continue  # response items, token records, turn context: not shown
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        payload = rec.get("payload") or {}
        kind = payload.get("type")
        ts = rec.get("timestamp") or ""
        if rec.get('type')=='response_item':
            if kind=='message' and payload.get('role')=='assistant' and payload.get('phase') in ('commentary','final_answer'):
                text=_join_text(payload.get('content')).strip()
                if text:msgs.append({'role':'assistant','text':text,'time':ts,'phase':payload['phase'],'source_id':payload.get('id'),'public_response':True})
            continue
        if ts:
            state["latest_event_time"] = ts
        if kind == "item_completed":
            item = payload.get("item") or {}
            t = item.get("type")
            if t == "UserMessage":
                saw_items = True
                msgs.append({"role": "user", "text": clean_codex_user(_join_text(item.get("content"))), "time": ts,
                             "client_request_id": item.get("client_id"), "source_id": item.get("id")})
            elif t == "AgentMessage":
                saw_items = True
                text = _join_text(item.get("content")).strip()
                if text and item.get('phase') in (None, 'commentary', 'final_answer'):
                    msgs.append({"role": "assistant", "text": text, "time": ts, "phase": item.get("phase") or "", "source_id": item.get("id")})
            elif t == 'Plan' and isinstance(item.get('text'),str):
                msgs.append({'role':'assistant','phase':'final_answer','text':item['text'],'time':ts,'source_id':item.get('id'),'native_plan':True})
            elif t == "FunctionCallOutput":
                delegated = _codex_delegation(item)
                if delegated:
                    saw_items = True
                    msgs.append({**delegated, "time": ts})
            elif t == "CommandExecution":
                msgs.append({"role": "tool", "text": _codex_command(item), "time": ts, "source_id": item.get("id")})
            elif t == "Extension":
                action = item.get("action") or {}
                queries = action.get("queries") or ([action.get("query")] if action.get("query") else [])
                label = item.get("kind") or "工具"
                msgs.append({"role": "tool", "text": f"{label}：" + "；".join(str(q) for q in queries if q)[:160],
                             "time": ts})
        elif kind == "task_started":
            state.update(running=True, turn_time=ts)
            if payload.get('turn_id'):state['current_turn_id']=payload['turn_id']
        elif kind in ("task_complete", "turn_aborted"):
            state.update(running=False, turn_time=ts)
            if payload.get('turn_id'):state['current_turn_id']=payload['turn_id']
        elif kind == "user_message":  # older Codex versions
            msgs.append({"role": "user", "text": clean_codex_user(payload.get("message") or ""), "time": ts, "legacy": True,
                         "source_id": payload.get("id"), "client_request_id": payload.get("client_id")})
        elif kind == "agent_message":
            if payload.get("phase") in (None, "commentary", "final_answer"):
                msgs.append({"role": "assistant", "text": payload.get("message") or "", "time": ts, "legacy": True,
                             "phase": payload.get("phase") or "", "source_id": payload.get("id")})
    if saw_items:
        msgs = [m for m in msgs if not (m.get('legacy') and m.get('time') and any(
            not v.get('legacy') and v.get('time')==m['time'] and v['role']==m['role']
            and v.get('phase','')==m.get('phase','') and v['text']==m['text'] for v in msgs))]
    return msgs, state


def _claude_tool(block: dict) -> str:
    name = block.get("name") or "工具"
    args = block.get("input") or {}
    for key in ("command", "file_path", "path", "pattern", "url", "query", "description", "prompt"):
        if isinstance(args.get(key), str) and args[key].strip():
            return f"{name}：{one_line(args[key], 110)}"
    return name


def _claude_plan(block: dict) -> dict | None:
    """The checklist Claude keeps, as the desktop shows it: Claude desktop's update_plan tool ({items: [{content,
    status}]}) or Claude Code's TodoWrite ({todos: […]}). None for any other tool."""
    name = block.get("name") or ""
    args = block.get("input") or {}
    rows = args.get("items") if name.endswith("update_plan") else args.get("todos") if name == "TodoWrite" else None
    if not isinstance(rows, list):
        return None
    items = [{"text": str(r.get("content") or r.get("step") or "").strip(), "status": str(r.get("status") or "pending")}
             for r in rows if isinstance(r, dict)]
    items = [i for i in items if i["text"]]
    if not items:
        return None
    done = sum(i["status"] == "completed" for i in items)
    return {"role": "plan", "items": items, "text": f"计划 {done}/{len(items)}：" + "；".join(i["text"] for i in items)}


# The app's own buttons a next-step box can offer (wrap_up actions), named as the phone shows them: the desktop draws them
# with labels of its own, which the record does not hold.
NEXT_APP_ACTIONS = {"commit": "提交", "create_pr": "创建 PR", "merge": "合并", "fix_ci": "修复 CI", "address_comments": "处理评论",
                    "resolve_conflicts": "解决冲突", "verify": "验证", "archive": "归档", "new_session": "新开对话"}


def _claude_next(block: dict) -> dict | None:
    """Claude desktop's next-step box (its mcp__ccd_turn__wrap_up tool, 10-16), drawn at the end of the chat: a recap of
    where the turn left things and, when the next move is the user's, a question with a button or two. A reply button
    sends its message (its label when it has none); an app button does what the app does. None for any other tool."""
    if not (block.get("name") or "").endswith("ccd_turn__wrap_up"):
        return None
    args = block.get("input") or {}
    recap, ask = str(args.get("recap") or "").strip(), str(args.get("ask") or "").strip()
    if not recap and not ask:
        return None
    actions = []
    for a in (args.get("actions") or []) if ask else []:
        if not isinstance(a, dict):
            continue
        app = str(a.get("action") or "").strip()
        label = NEXT_APP_ACTIONS.get(app, app) if app else str(a.get("label") or "").strip()
        if label:
            actions.append({"label": label, **({"action": app} if app else {"message": str(a.get("message") or "").strip() or label})})
    return {"role": "next", "tool_id": block.get("id"), "recap": recap, "ask": ask, "actions": actions,
            "blocked": bool(args.get("blocked")), "text": "\n\n".join(t for t in (recap, ask) if t)}


def _claude_task(block: dict) -> dict | None:
    """A task Claude proposes in a card of its own (its mcp__ccd_session__start_session tool, 10-16): a title and a brief;
    on the desktop, a proposal (initiation own_initiative) has Start, Do it here and a cross, and an offer asks New
    session or Do it here before the turn goes on. None for any other tool, and for a session started at once."""
    if not (block.get("name") or "").endswith("ccd_session__start_session"):
        return None
    args = block.get("input") or {}
    title, brief = str(args.get("title") or "").strip(), str(args.get("prompt") or "").strip()
    if args.get("initiation") not in ("own_initiative", "offer") or not title:
        return None
    return {"role": "task", "tool_id": block.get("id"), "title": title, "brief": brief, "offer": args.get("initiation") == "offer",
            "text": title + ("\n\n" + brief if brief else "")}


def _claude_steer_message(rec):
    data=rec.get('attachment') or {}
    prompt=data.get('prompt')
    if (rec.get('type')!='attachment' or rec.get('isSidechain') or rec.get('isMeta') or
        data.get('type')!='queued_command' or data.get('humanTurn') is not True or
        (data.get('origin') or {}).get('kind')!='human' or not isinstance(prompt,(str,list))):
        return None
    # With pictures the prompt is a list (the pictures, then the text) and the queue's enqueue line holds no text.
    # Read only as a string, such a message was never found: the phone said 没确认送达 for both of them (10-12).
    text=_join_text(prompt).strip()
    if isinstance(prompt,list) and any(isinstance(b,dict) and b.get('type')=='image' for b in prompt):text=('[图片] '+text).strip()
    if not text:return None
    return {'role':'user','text':text,'time':rec.get('timestamp') or data.get('timestamp'),
            'source_id':data.get('source_uuid') or rec.get('uuid'),'delivery_kind':'steer'}


def mark_open_next(msgs: list[dict]) -> None:
    """Marks the next-step box that still waits on the user, the newest one with a question and nothing said since (the
    desktop drops its question and buttons once the next turn starts), and unmarks any other; older ones keep their recap."""
    last = None
    for i, m in enumerate(msgs):
        if m["role"] == "next":
            m.pop("open", None)
            last = i
    if last is not None and msgs[last]["ask"] and not any(m["role"] in ("user", "event") for m in msgs[last + 1:]):
        msgs[last]["open"] = True


def parse_claude(lines: list[bytes], context: dict | None = None) -> tuple[list[dict], dict]:
    """context: kept by a caller that reads a record a line at a time (chat_history.Transcript), for what one line needs
    to know of earlier ones."""
    msgs: list[dict] = []
    state = {"running": None, "title": ""}
    last_kind, last_stop = None, None
    # next-step boxes with a question: the turn ends at their result, the record's last line (10-16)
    asks = context.setdefault("asks", set()) if context is not None else set()
    for raw in lines:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        t = rec.get("type")
        if t == "custom-title":
            state["title"] = rec.get("customTitle") or state["title"]
            continue
        steered=_claude_steer_message(rec)
        if steered:
            msgs.append(steered);last_kind='user';state['latest_event_time']=steered['time'];continue
        if t not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        ts = rec.get("timestamp") or ""
        if ts:
            state["latest_event_time"] = ts
        message = rec.get("message") or {}
        content = message.get("content")
        if t == "user":
            if rec.get("isCompactSummary"):
                # /compact (or Claude running out of room) writes its summary as a user line. The desktop shows a divider
                # in its place; the phone showed all 10,000 characters as the user's own message and, the turn seeming to
                # wait on it, 停止这一轮 (10-20)
                msgs.append({"role": "event", "text": "对话已压缩", "time": ts})
                continue
            if isinstance(content, str):
                text = clean_claude_user(content)
                # a local command's output (/compact's "Compacted") ends what the command started: no turn follows
                last_kind = "command_done" if not text and _COMMAND_OUTPUT.search(content) else "user"
            else:
                blocks = content or []
                text = clean_claude_user("\n".join(b.get("text", "") for b in blocks
                                                   if isinstance(b, dict) and b.get("type") == "text"))
                if any(isinstance(b, dict) and b.get("type") == "image" for b in blocks):
                    text = ("[图片] " + text).strip()
                last_kind = "user" if text else ("tool_result" if blocks else last_kind)
                if not text and any(isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in asks for b in blocks):
                    last_kind = "asked"  # read as running before 10-16: the phone offered 停止这一轮 for a turn long over
            if text:
                if text.startswith("[Request interrupted"):
                    last_kind, last_stop = "interrupted", None
                notice = task_notice(text)
                msgs.append({"role": "event", "text": notice, "time": ts} if notice else {"role": "user", "text": text, "time": ts})
        else:
            last_kind, last_stop = "assistant", message.get("stop_reason")
            for block in content or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and (block.get("text") or "").strip():
                    msgs.append({"role": "assistant", "text": block["text"].strip(), "time": ts})
                elif block.get("type") == "thinking" and (block.get("thinking") or "").strip():
                    # What Claude shows of its thinking, a line or two between steps, as the desktop shows it. A review run
                    # on 10-15 wrote no answer text between its steps at all, so the phone had only 已执行 N 步操作; shown
                    # like Codex's own progress notes (commentary: grey, no copy button). Empty ones are hidden thinking.
                    msgs.append({"role": "assistant", "phase": "commentary", "thinking": True,
                                 "text": block["thinking"].strip(), "time": ts})
                elif block.get("type") == "tool_use":
                    # the checklist, the next-step box and a proposed task are cards of their own, not one more step
                    card = _claude_plan(block) or _claude_next(block) or _claude_task(block)
                    if card and card["role"] == "next" and card["ask"]:
                        asks.add(block.get("id"))
                    msgs.append({**card, "time": ts} if card else {"role": "tool", "text": _claude_tool(block), "time": ts})
    mark_open_next(msgs)
    if last_kind is not None:
        state["running"] = not (last_kind in ("interrupted", "asked", "command_done") or (last_kind == "assistant" and last_stop not in (None, "tool_use")))
    return msgs, state


def claude_open_next(item: dict) -> dict | None:
    """The next-step box at the end of this Claude conversation that still waits on the user, as its record holds it
    (10-16); None when the last turn did not end with one, or it has been answered."""
    path = conv_path(item)
    if path is None:
        return None
    lines, _ = read_tail(path, 1 << 20)
    msgs, _ = parse_claude(lines)
    box = next((m for m in reversed(msgs) if m["role"] == "next"), None)
    return box if box and box.get("open") else None


def claude_last_sent(lines: list[bytes]) -> list[str]:
    """What the user last sent, as these lines of a Claude record show it: the newest last-prompt line and the last
    user message. Empty when the lines hold neither. Claude writes a last-prompt line after every step, so it is
    near the end even after a long turn; it cuts text over 200 characters and ends it with …, so a cut one is left out."""
    found = []
    for raw in reversed(lines):
        if b"last-prompt" not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        prompt = rec.get("lastPrompt") if rec.get("type") == "last-prompt" else None
        if isinstance(prompt, str):
            if not (len(prompt) > 200 and prompt.endswith("…")):
                found.append(prompt)
            break
    msgs, _ = parse_claude(lines)
    last = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
    if last:  # the record marks pictures; the box shows them apart
        found.append(re.sub(r"^(\[图片\]\s*)+", "", last.get("text", "")))
    return [s for s in found if s.strip()]


def _parse(app: str, lines: list[bytes], context: dict | None = None) -> tuple[list[dict], dict]:
    return parse_codex(lines) if app == "codex" else parse_claude(lines, context)


def _status(state: dict, mtime: float) -> str:
    if state.get("running") is None:
        return "unknown"
    if state["running"]:
        # Windows may retain an old last-write time while the app holds the log open.
        # Use the timestamps in the actual appended events when available.
        try:
            latest = datetime.fromisoformat(state.get("latest_event_time") or state.get("turn_time") or "").timestamp()
        except (ValueError, TypeError):
            latest = mtime
        return "running" if time.time() - latest < STALE_SECONDS else "unknown"
    return "idle"


_summary_cache: dict[str, tuple[tuple, dict]] = {}


def summary(item: dict) -> dict:
    """Status and last line of one conversation, read from the end of its file (cached by size)."""
    if item['app']=='deepseek':return {'status':item.get('status','unknown'),'preview':item.get('preview','')}
    path = conv_path(item)
    if path is None:
        return {"status": "unknown", "preview": "", "path_missing": True}
    try:
        st = path.stat()
    except OSError:
        return {"status": "unknown", "preview": ""}
    key = (st.st_size, st.st_mtime_ns)
    hit = _summary_cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    nbytes, msgs, state = 256 << 10, [], {}
    while True:
        lines, at_start = read_tail(path, nbytes)
        msgs, state = _parse(item["app"], lines)
        have_message=any(m["role"] in ("user", "assistant") for m in msgs)
        have_status=item['app']!='codex' or state.get('running') is not None
        if (have_message and have_status) or at_start or nbytes >= (8 << 20):
            break
        nbytes *= 4
    last = next((m for m in reversed(msgs) if m["role"] in ("user", "assistant")), None)
    prefix = "来自其他对话：" if last and last.get("origin") == "other_chat" else "你：" if last and last["role"] == "user" else ""
    out = {"status": _status(state, st.st_mtime), "modified": int(st.st_mtime * 1000),
           "preview": prefix + one_line(plain(last["text"]), 90) if last else ""}
    _summary_cache[str(path)] = (key, out)
    return out


def public(item: dict) -> dict:
    return {k: item.get(k) for k in ("app", "id", "title", "folder", "cwd", "updated", "created", "pinned")}


def parse_runtime(app: str, lines: list[bytes]) -> dict:
    """Only expose recorded settings and a single usage snapshot, never cumulative usage."""
    out = {"model": None, "effort": None, "model_time": None, "usage_time": None,
           "used_tokens": None, "context_window": None, "percent": None,
           "context_state": "unavailable", "turn_time": None, "model_turn_id": None}
    for raw in lines:
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        ts, kind = rec.get("timestamp"), rec.get("type")
        payload = rec.get("payload") or {}
        if app == "claude":
            if kind == "assistant" and not rec.get("isSidechain") and not rec.get("isMeta"):
                model = (rec.get("message") or {}).get("model")
                if model and model != "<synthetic>":
                    out.update(model=model, model_time=ts)
                    usage=(rec.get('message') or {}).get('usage') or {}
                    parts=[usage.get(k,0) for k in ('input_tokens','cache_read_input_tokens','cache_creation_input_tokens')]
                    if all(isinstance(v,(int,float)) and not isinstance(v,bool) and v>=0 for v in parts) and any(parts):
                        out.update(used_tokens=sum(parts),usage_time=ts,context_state='partial',source='last_request')
            elif kind=='system' and rec.get('subtype')=='compact_boundary':
                out.update(used_tokens=None,usage_time=ts,context_state='waiting')
            continue
        event = payload.get("type") if kind == "event_msg" else None
        if event == "task_started":
            out["turn_time"] = ts
        if kind == "turn_context":
            settings = (payload.get("collaboration_mode") or {}).get("settings") or {}
            model = payload.get("model") or settings.get("model")
            if out["model"] and model != out["model"]:
                out.update(used_tokens=None, context_window=None, percent=None, usage_time=None,
                           context_state="waiting")
            out.update(model=model, effort=payload.get("effort") or payload.get("reasoning_effort")
                       or settings.get("reasoning_effort"), model_time=ts, model_turn_id=payload.get("turn_id"))
        if kind == "compacted" or event == "context_compacted":
            out.update(used_tokens=None, context_window=None, percent=None, usage_time=None,
                       context_state="waiting")
        if event == "token_count":
            info = payload.get("info") or {}
            used = (info.get("last_token_usage") or {}).get("total_tokens")
            window = info.get("model_context_window")
            if isinstance(used, int) and not isinstance(used, bool) and used >= 0 and isinstance(window, int) and window > 0:
                out.update(used_tokens=used, context_window=window, percent=round(used / window * 100, 1),
                           usage_time=ts, context_state="available")
    return out


_runtime_cache: dict[tuple, dict] = {}
_runtime_lock = threading.Lock()


def runtime_info(app: str, path: Path) -> dict:
    st = path.stat()
    key = (app, str(path), st.st_size, st.st_mtime_ns)
    with _runtime_lock:
        if key in _runtime_cache:
            return dict(_runtime_cache[key])
    nbytes = 1 << 20
    while True:
        lines, at_start = read_tail(path, nbytes)
        out = parse_runtime(app, lines)
        if at_start or nbytes >= (32 << 20) or (out["model"] and
                (app == "claude" or out["context_state"] != "unavailable")):
            break
        nbytes = min(nbytes * 4, 32 << 20)
    with _runtime_lock:
        for old in list(_runtime_cache):
            if old[:2] == key[:2]:
                del _runtime_cache[old]
        if len(_runtime_cache) >= 128:
            _runtime_cache.pop(next(iter(_runtime_cache)))
        _runtime_cache[key] = out
    return dict(out)


def list_conversations(app: str = "all", limit: int = 40) -> list[dict]:
    items: list[dict] = []
    if app in ("all", "codex"):
        try:
            items += codex_threads(limit)
        except sqlite3.Error:
            pass
    if app in ("all", "claude"):
        items += claude_sessions(limit)
    for item in items:
        s = summary(item)
        item["status"], item["preview"] = s["status"], s["preview"]
        item["updated"] = max(item["updated"], s.get("modified") or 0)
    items.sort(key=lambda x: -x["updated"])
    return [public(i) | {"status": i["status"], "preview": i["preview"]} for i in items[:limit]]


def conversation(app: str, conv_id: str, n: int = 60) -> dict:
    item = find(app, conv_id)
    path = conv_path(item)
    out = public(item) | {"messages": [], "status": "unknown", "size": 0, "runtime": None}
    if path is None:
        out["note"] = "没找到这个对话的记录文件"
        return out
    st = path.stat()
    nbytes, msgs, state = 1 << 20, [], {}
    while True:
        lines, at_start = read_tail(path, nbytes)
        msgs, state = _parse(app, lines)
        talk = sum(1 for m in msgs if m["role"] in ("user", "assistant"))
        if talk >= n // 2 or at_start or nbytes >= (32 << 20):
            break
        nbytes *= 4
    if app == "claude" and state.get("title"):
        out["title"] = state["title"]
    duplicates: dict[str, int] = {}
    for m in msgs:
        identity = json.dumps([m.get("time"), m["role"], m.get("phase"), m["text"]], ensure_ascii=False)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        duplicates[digest] = duplicates.get(digest, 0) + 1
        m["id"] = digest + ":" + str(duplicates[digest])
        if len(m["text"]) > 6000:
            m["text"] = m["text"][:6000] + "\n…（太长，后面略）"
        m.pop("legacy", None)
    out.update(messages=msgs[-n:], status=_status(state, st.st_mtime), size=st.st_size,
               modified=int(st.st_mtime * 1000), runtime=runtime_info(app, path))
    return out


def recent_folders(limit: int = 12) -> list[str]:
    """Working folders of recent Codex threads, for starting a new one."""
    seen, out = set(), []
    for item in codex_threads(200):
        cwd = item.get("cwd") or ""
        if cwd and cwd.lower() not in seen and Path(cwd).is_dir():
            seen.add(cwd.lower())
            out.append(cwd)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- delivery check


def _is_ours(app: str, rec: dict, want: str) -> bool:
    if app == "codex":
        payload = rec.get("payload") or {}
        if payload.get("type") == "item_completed":
            item = payload.get("item") or {}
            return item.get("type") == "UserMessage" and want in norm(_join_text(item.get("content")))
        if payload.get("type") == "user_message":
            return want in norm(payload.get("message") or "")
        return False
    steered=_claude_steer_message(rec)
    if steered:return want in norm(steered['text'])
    if rec.get("type") == "queue-operation" and rec.get("operation") == "enqueue":
        return want in norm(_join_text(rec.get("content")))
    if rec.get("type") == "user":
        return want in norm(_join_text((rec.get("message") or {}).get("content")))
    return False


def delivered(app: str, path: Path | None, offset: int, text: str) -> bool:
    if path is None or not path.exists():
        return False
    want = norm(text)[:40]
    marker = (b"UserMessage", b"user_message") if app == "codex" else (b"enqueue", b'"user"', b'"queued_command"')
    for raw in read_from(path, offset):
        if not any(m in raw for m in marker):
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if _is_ours(app, rec, want):
            return True
    return False


def claude_delivery_stage(path,offset,text):
    if path is None or not path.exists():return 'unknown'
    want=norm(text);stage='unknown'
    for raw in read_from(path,offset):
        try:rec=json.loads(raw)
        except ValueError:continue
        steered=_claude_steer_message(rec)
        if steered and want and norm(re.sub(r'^(\[图片\]\s*)+','',steered['text']))==want:return 'received'  # the mark is ours, not sent
        if rec.get('type')=='user':
            actual=_join_text((rec.get('message') or {}).get('content'))
            # 10-26: Claude writes its own notes (<system-reminder>Linked sessions now …) into the user's record
            if want and want in (norm(actual),norm(clean_claude_user(actual)),norm(claude_command(actual))):return 'received'
        elif rec.get('type')=='queue-operation' and rec.get('operation')=='enqueue':
            if want and norm(_join_text(rec.get('content')))==want:stage='queued'
    return stage


# ---------------------------------------------------------------- windows and clipboard


def _process_of(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return ""
    return winctl._process_name(pid).lower()


def app_window(process: str) -> int:
    wins = [w for w in winctl.list_windows() if w["process"].lower() == process]
    wins.sort(key=lambda w: -(w["width"] * w["height"]))
    return wins[0]["hwnd"] if wins else 0


def front_process() -> str:
    fg = win32gui.GetForegroundWindow()
    return _process_of(fg) if fg else ""


def _clip_open() -> None:
    import win32clipboard
    for _ in range(20):
        try:
            win32clipboard.OpenClipboard(0)
            return
        except Exception:
            time.sleep(0.05)
    raise ChatError("电脑的剪贴板被别的程序占着，稍后再试")


@contextmanager
def clipboard_text(text: str):
    """Put text on the clipboard for one paste, then put back the text that was there."""
    import win32clipboard
    import win32con
    _clip_open()
    try:
        saved = None
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            try:
                saved = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            except Exception:
                saved = None
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()
    try:
        yield
    finally:
        time.sleep(0.25)  # let the app read it first
        try:
            _clip_open()
            try:
                win32clipboard.EmptyClipboard()
                if saved is not None:
                    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, saved)
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            pass


def picture_mark(hwnd: int) -> bytes | None:
    """A small grey copy of the window, to tell later whether it changed."""
    try:
        image, _, _ = winctl.grab_image(hwnd)
        return winctl.thumbprint(image)
    except Exception:
        return None


def settle(hwnd: int, before: bytes | None = None, min_wait: float = 0.7, max_wait: float = 4.0) -> None:
    """Wait until the window has changed from `before` (the link took effect) and then stopped changing.

    Without the first condition a window that was already in front looks 'settled' at once, and Enter
    could land in the previous conversation before the new one is shown."""
    start, last, still_since, moved = time.time(), None, None, before is None
    while True:
        mark = picture_mark(hwnd)
        now = time.time()
        if not moved and mark is not None and winctl.changed(before, mark):
            moved = True
        if moved and last is not None and mark is not None and not winctl.changed(last, mark):
            still_since = still_since or now
            if now - start >= min_wait and now - still_since >= 0.3:
                return
        else:
            still_since = None
        if now - start >= max_wait:
            return
        last = mark
        time.sleep(0.15)


# ---------------------------------------------------------------- the desktop worker


class Desktop:
    """Links, UI Automation and key presses, on one thread, one action at a time."""

    def __init__(self, log, input_lock: threading.Lock):
        self.log = log
        self.input_lock = input_lock
        self.sent_last: dict[str, str] = {}  # conversation id -> the text this service last sent there (_claude_stale_copy)
        self.auto = None
        self.uia = None  # Windows' own UI Automation object, for _find
        self.auto_error = ""
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desktop", initializer=self._init)
        self.pool.submit(lambda: None)  # start the thread now, so a missing package shows up in the status

    def _init(self) -> None:
        try:
            import uiautomation as auto
            from uiautomation import uiautomation as core
            auto.InitializeUIAutomationInCurrentThread()
            auto.SetGlobalSearchTimeout(2)
            self.uia = core._AutomationClient.instance().IUIAutomation  # the library has no public handle to it
            self.auto = auto
        except Exception as exc:  # pragma: no cover
            self.auto_error = str(exc).splitlines()[0][:200]

    def run(self, fn, *args, timeout: float = 60):
        return self.pool.submit(fn, *args).result(timeout)

    # -- small pieces

    def _front(self, process: str, seconds: float) -> int:
        """After a link: wait for the app to come to the front; return its main window."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if front_process() == process:
                break
            time.sleep(0.1)
        hwnd = app_window(process)
        if hwnd and front_process() != process:
            winctl.focus(hwnd, strict=False)
        return hwnd

    def _paste(self, hwnd: int, text: str) -> None:
        with clipboard_text(text):
            winctl.press(hwnd, "Control+a")
            time.sleep(0.05)
            winctl.press(hwnd, "Control+v")
            time.sleep(0.2)

    def _need_auto(self):
        if self.auto is None:
            raise ChatError("读不了界面元素：" + (self.auto_error or "uiautomation 没装"))
        return self.auto

    # -- Claude window

    def _claude_root(self):
        auto = self._need_auto()
        hwnd = app_window(CLAUDE_PROCESS)
        if not hwnd:
            raise ChatError("电脑上 Claude 没开")
        return hwnd, auto.ControlFromHandle(hwnd)

    def _claude_title(self, root) -> str:
        doc = root.DocumentControl(searchDepth=14, Compare=lambda c, d: (c.Name or "").endswith(" - Claude Code"))
        if doc.Exists(0.3, 0.1):
            return doc.Name[: -len(" - Claude Code")].strip()
        return ""

    @staticmethod
    def _same_title(shown: str, titles: list[str]) -> bool:
        """The whole title must match: sessions often share long prefixes such as a project code."""
        a = norm(shown)
        return bool(a) and any(t and norm(t) == a for t in titles)

    def _claude_wait_title(self, root, titles: list[str], seconds: float) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._same_title(self._claude_title(root), titles):
                return True
            time.sleep(0.25)
        return False

    def _claude_prompt(self, root):
        edit = root.EditControl(Name="Prompt", searchDepth=70)
        return edit if edit.Exists(2, 0.2) else None

    def _claude_document(self,root,conv_id):
        doc=root.DocumentControl(searchDepth=18,Compare=lambda c,d:(c.Name or '').endswith(' - Claude Code') if conv_id!='__new__' else self._value(c).rstrip('/')=='https://claude.ai/epitaxy')
        if not doc.Exists(.3,.1):return None
        value=self._value(doc)
        if not value.startswith('https://claude.ai/'):
            try:value=doc.GetLegacyIAccessiblePattern().Value or ''
            except Exception:return None
        try:
            url=urlsplit(value)
            return doc if url.hostname=='claude.ai' and (url.path.rstrip('/')=='/epitaxy' if conv_id=='__new__' else url.path.rstrip('/').split('/')[-1]==conv_id) else None
        except ValueError:return None

    def _find(self,scope,kind,name=None):
        """Everything under scope of this kind ('EditControl', 'ButtonControl'), with exactly this name if one is given:
        one question that Windows answers itself. On 10-12 it found Claude's message box in 0.02 s, where walking the
        page element by element took 0.7 s (1 200 elements); one send walked it six times or more, so sending took
        3.5-10 s."""
        uia,auto=self.uia,self.auto
        condition=uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty,getattr(auto.ControlType,kind))
        if name is not None:condition=uia.CreateAndCondition(condition,uia.CreatePropertyCondition(auto.PropertyId.NameProperty,name))
        found=scope.Element.FindAll(4,condition)  # 4: TreeScope_Descendants
        return [auto.Control.CreateControlFromElement(found.GetElement(i)) for i in range(found.Length)]

    def _find_class(self,scope,part):
        """Everything under scope whose class holds part (Chromium gives an element all its classes in one string), from
        one question that Windows answers itself, as _find."""
        uia,auto=self.uia,self.auto
        found=scope.Element.FindAll(4,uia.CreatePropertyConditionEx(auto.PropertyId.ClassNameProperty,part,2))  # 2: within the name
        return [auto.Control.CreateControlFromElement(found.GetElement(i)) for i in range(found.Length)]

    def _claude_verified_prompt(self,root,conv_id):
        doc=self._claude_document(root,conv_id)
        if doc is None:raise InputNotSubmitted('Claude 会话身份未核实，尚未发送；请打开目标对话')
        edits=[c for c in self._find(doc,'EditControl','Prompt') if not c.IsOffscreen and c.IsEnabled]
        if len(edits)!=1:raise InputNotSubmitted('Claude 输入框不唯一或尚未就绪，尚未发送')
        return doc,edits[0]

    @staticmethod
    def _same_input(actual,expected):
        # Contenteditable appends a final line break. Preserve meaningful spaces and all text.
        return actual.replace('\r\n','\n').rstrip('\n')==expected.replace('\r\n','\n').rstrip('\n')

    def _claude_show(self,hwnd):
        """Claude keeps its page, and what UI Automation reads of it, up to date only while its window is shown. Minimised,
        the message box went on reading as the message just sent after Claude had emptied it, until the window came back:
        the phone's next message was turned away as somebody's draft (10-12, 12:04 and 12:44, after the user had glanced at
        the PC the next one went), and a write took seconds to read back (12:03, read back wrong and given up). Brought up,
        the box read empty within 0.1 s (test session, 10-12 20:59). So the window is brought up first and given a moment to
        draw, and stays up afterwards, so Claude's questions keep reaching the phone.
        It is not made the active window: the keyboard stays where it was. While a send made Claude the active window, an
        'e' typed on the PC went into Claude's box and turned the next phone message away (10-12 21:31). Restored without
        activation, the page caught up within 0.3 s with WeChat still in front (21:46); covered at its message box, it is
        put on top, still without activation. Text and Send go through UI Automation and need no keyboard."""
        try:
            changed=False
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd,win32con.SW_SHOWNOACTIVATE);changed=True;time.sleep(.25)  # it slides up first
            if self._claude_covered(hwnd):
                win32gui.SetWindowPos(hwnd,win32con.HWND_TOP,0,0,0,0,win32con.SWP_NOMOVE|win32con.SWP_NOSIZE|win32con.SWP_NOACTIVATE);changed=True
        except Exception:return  # gone, or would not come up: the send goes on and reports what it finds
        if changed:time.sleep(.3)

    def _claude_unminimize(self):
        """For the phone's reading of a Claude conversation (every 5 s): a minimised window is restored, never made the
        active window, and never put over other windows (the user's pick, 10-12). Minimised, the Stop button still read as
        shown 4 s after the turn had ended; restored, it was gone within 0.3 s (10-12 21:46)."""
        try:
            hwnd=app_window(CLAUDE_PROCESS)
            if not hwnd or not win32gui.IsIconic(hwnd):return False
            win32gui.ShowWindow(hwnd,win32con.SW_SHOWNOACTIVATE)
        except Exception:return False
        time.sleep(.3);return True

    @staticmethod
    def _claude_covered(hwnd)->bool:
        """Other windows over all of Claude's window: at its middle, at its message box and near its top. A window that
        shows somewhere is drawn; one wholly covered may not be."""
        left,top,right,bottom=win32gui.GetWindowRect(hwnd)
        if right-left<50 or bottom-top<200:return False
        x=(left+right)//2
        for y in ((top+bottom)//2,bottom-90,top+120):
            if win32gui.GetAncestor(win32gui.WindowFromPoint((x,y)),2)==hwnd:return False  # 2: GA_ROOT
        return True

    def _fill_claude_prompt(self,item,root,text,replace=None):
        name=item.get('title') or '新会话'
        _,edit=self._claude_verified_prompt(root,item['id'])
        draft=self._value(edit)
        # A window that was just brought up may still be catching up on what Claude did while it was down: look again
        # for a moment before taking the box's text for somebody's draft.
        deadline=time.monotonic()+.8
        while draft.strip() and not self._same_input(draft,text) and time.monotonic()<deadline:
            time.sleep(.15);_,edit=self._claude_verified_prompt(root,item['id']);draft=self._value(edit)
        if draft.strip() and not self._same_input(draft,text):
            if self._claude_stale_copy(item,draft):
                self.log(f"Claude「{name}」输入框里留着刚发出去那条的副本，已换成新消息")
            elif replace is not None and norm(replace) and norm(replace)==norm(draft):
                # the phone was shown exactly this text and asked for it to go (DesktopDraft); anything else stays
                self.log(f"Claude「{name}」按手机上的确认，换掉了输入框里的 {len(draft.strip())} 个字（开头：{one_line(draft,20)}）")
            else:
                hidden='；框里第一行却标着空，屏幕上多半看不到这些字' if self._claude_box_marked_empty(edit) else ''
                self.log(f"Claude「{name}」输入框里已有别的文字（{len(draft.strip())} 字，开头：{one_line(draft,20)}），没有覆盖{hidden}")
                raise DesktopDraft(f'电脑上 Claude 的输入框里有别的字（「{one_line(draft,16)}」），没有覆盖；可以在这里换掉它再发，'
                                   '或者先到电脑上处理', draft.strip()[:2000])
        # Written at most twice, with longer waits than the 2 s there were. On 10-12 a write was read back wrong for
        # 2 s while Claude's window was busy, and the message was given up. A write replaces the whole box, so a first
        # write that lands late does no harm.
        for wait in (3,4):
            _,edit=self._claude_verified_prompt(root,item['id'])
            if not self._same_input(self._value(edit),text):
                try:
                    # the box, not whatever else in the window had the keyboard (an open side panel); only while Claude is
                    # the active window already: a focus call can make it the active one, and keys typed on the PC follow
                    try:
                        if winctl._is_front(root.NativeWindowHandle):edit.SetFocus()
                    except Exception:pass
                    value=edit.GetValuePattern()
                    if value is None or value.IsReadOnly:raise RuntimeError('no writable ValuePattern')
                    if value.SetValue(text) is False:raise RuntimeError('SetValue failed')
                except Exception as exc:raise InputNotSubmitted('文字未能完整写入 Claude，尚未发送；手机副本已保留') from exc
            deadline=time.monotonic()+wait
            while True:
                doc,edit=self._claude_verified_prompt(root,item['id'])
                if self._same_input(self._value(edit),text):return doc,edit
                if time.monotonic()>=deadline:break
                time.sleep(.1)
        shown=self._value(edit)
        self.log(f"Claude「{name}」写进输入框后读回不一致（读到 {len(shown.strip())} 字：{one_line(shown,20)}）")
        raise InputNotSubmitted('Claude 输入框内容与消息不一致，尚未发送；请检查输入法候选和桌面草稿')

    def _claude_stale_copy(self,item,draft):
        """The box holds exactly the last message this session already received: a copy left behind, not anyone's
        draft. On 10-12 such text sat in the box after a send, while the screen showed the box empty, and turned away
        the phone's next message five times. The cause was a minimised window (_claude_show now brings it up first);
        this stays for a window that could not be brought up.
        What was sent last is known from what this service sent there itself, or else from the record, read from its
        end: 512 KB, then 8 MB. At 12:44 that day the last message lay 1.2 MB back, behind a long turn full of
        screenshots; only 512 KB was read then, and the copy was taken for a draft three times."""
        want=norm(draft)
        if not want or item.get('id')=='__new__':return False
        if want==norm(self.sent_last.get(item['id'],'')):return True
        try:
            path=conv_path(item)
            if not path:return False
            for size in (512<<10,8<<20):
                lines,whole=read_tail(path,size)
                sent=claude_last_sent(lines)
                if sent or whole:break
        except Exception:return False
        return any(norm(s)==want for s in sent)

    @staticmethod
    def _claude_box_marked_empty(edit)->bool:
        """Claude marks the first line of an empty box 'is-editor-empty'; its gray placeholder or suggested next message
        shows there. Read only for the log: whether text read from the box was on screen at all."""
        try:
            first=next((c for c in edit.GetChildren() if c.ControlTypeName=='GroupControl'),None)
            return first is not None and 'is-editor-empty' in (first.ClassName or '').split()
        except Exception:return False

    @staticmethod
    def _value(ctrl) -> str:
        try:
            return ctrl.GetValuePattern().Value or ""
        except Exception:
            pass
        try:
            return ctrl.GetTextPattern().DocumentRange.GetText(-1) or ""
        except Exception:
            return ""

    def _claude_sidebar_buttons(self, root, item, titles=()) -> list:
        """The buttons in Claude's sidebar that may open this session, best first. A click there switches inside
        the running app at once, while a claude:// link first starts a second Claude.exe (8-15 s on a busy morning,
        10-12), and since Claude 2.1.299 (10-15) Claude mostly ignores the link: with no row found, sending to a
        session not on screen failed after 25 s (10-20).
        A row is named by the session's title, alone or followed by what Claude says of it; in Claude's new window
        (10-26) '<title> Running', '<title> Awaiting answer', '<title> Started by Claude from <parent>' or '<title>
        Started from a suggestion in <project>'; before 10-15, '<state> <title>'. Until 10-26 only 'Started by' was
        looked for after the title, so a running session, or one waiting on an answer from the phone, went to the
        link. A name with any other ending (an error, say) counts when the row's first line is the title itself.
        A row that has nested sessions carries its session id: that row comes first, and a row of the same title that
        carries another session's id is left out. Two sessions can still share a title and one session can show
        twice, so the caller presses these in turn and checks the session address after each. A suggested task card
        names a button by its title too, and so do buttons inside a row ('More options for …', 'Hide nested
        sessions …'): those are left out."""
        wanted = {t.strip() for t in [item.get("title") or "", *titles] if t and t.strip()}
        conv_id = item.get("id") or ""
        found = self._claude_id_rows(root, conv_id)
        by_id = bool(found)
        if not wanted:
            return found
        for ctrl in self._find(root, "ButtonControl"):
            try:
                name = (ctrl.Name or "").strip()
            except Exception:
                continue
            fit = self._claude_row_fit(name, wanted)
            if not fit or self._in_task_card(ctrl):
                continue
            carried, first_line = self._claude_row_parts(ctrl)
            if carried and (carried != conv_id or by_id):
                continue  # another session's row, or this one's, already first
            if fit == "first line" and first_line not in wanted:
                continue
            found.append(ctrl)
        return found

    @staticmethod
    def _claude_row_fit(name: str, wanted) -> str:
        """'name' when a row of one of these titles is named so; 'first line' when the name is a title and something
        else ('<title> <error>', or another session's '<title> and more'), a row of that title only if its first line
        is the title; '' otherwise."""
        fit = ""
        for title in wanted:
            if name == title:
                return "name"
            if name.startswith(title + " "):
                if _CLAUDE_ROW_ENDING.fullmatch(name[len(title) + 1:]):
                    return "name"
                fit = "first line"
            elif name.endswith(" " + title) and _CLAUDE_ROW_STATE.fullmatch(name[: -len(title) - 1]):
                return "name"
        return fit

    def _claude_row_parts(self, ctrl) -> tuple[str, str]:
        """The session id a sidebar row carries ('' for most rows) and its first line, from one question to Windows
        (1-7 ms on 10-26). Neither the group that holds the id nor the row's lines are control elements, so _find does
        not see them; the raw view does."""
        try:
            uia, auto = self.uia, self.auto
            request = uia.CreateCacheRequest()
            request.TreeFilter = uia.RawViewCondition
            props = auto.PropertyId
            for prop in (props.AutomationIdProperty, props.ControlTypeProperty, props.NameProperty):
                request.AddProperty(prop)
            found = ctrl.Element.FindAllBuildCache(4, uia.RawViewCondition, request)  # 4: TreeScope_Descendants
            carried = first_line = ""
            for i in range(found.Length):
                element = found.GetElement(i)
                m = _CLAUDE_ROW_ID.fullmatch(element.CachedAutomationId or "")
                carried = carried or (m[1] if m else "")
                if not first_line and element.CachedControlType == auto.ControlType.TextControl:
                    first_line = (element.CachedName or "").strip()
            return carried, first_line
        except Exception:
            return "", ""

    def _claude_id_rows(self, root, conv_id: str) -> list:
        """The sidebar rows that carry this session's id. In Claude's new window (10-26) a row that has nested sessions
        holds a group named by React's id for it and then the session's ('_r_82_local_…'), and the row is that group's
        parent. One question to Windows (0.05 s on 10-26), in the raw view: the group is not a control element."""
        if not conv_id.startswith("local_"):
            return []
        try:
            uia, auto = self.uia, self.auto
            request = uia.CreateCacheRequest()
            request.TreeFilter = uia.RawViewCondition
            request.AddProperty(auto.PropertyId.AutomationIdProperty)
            condition = uia.CreatePropertyConditionEx(auto.PropertyId.AutomationIdProperty, conv_id, 2)  # 2: substring
            found = root.Element.FindAllBuildCache(4, condition, request)
            rows = []
            for i in range(found.Length):
                group = found.GetElement(i)
                m = _CLAUDE_ROW_ID.fullmatch(group.CachedAutomationId or "")
                if not m or m[1] != conv_id:
                    continue  # the search palette's items hold the id too ('command-palette-item-local_…')
                parent = uia.RawViewWalker.GetParentElement(group)
                row = auto.Control.CreateControlFromElement(parent) if parent else None
                if row is not None and row.ControlTypeName == "ButtonControl":
                    rows.append(row)
            return rows
        except Exception:
            return []

    @staticmethod
    def _in_task_card(ctrl) -> bool:
        node = ctrl
        for _ in range(4):
            try:
                node = node.GetParentControl()
                if node is None:
                    return False
                if re.fullmatch(r"\d+ suggested tasks?", (node.Name or "").strip()):
                    return True
            except Exception:
                return False
        return False

    def _claude_press(self, hwnd, button) -> bool:
        try:
            self._claude_show(hwnd)  # a minimised window does not redraw the new session; brought up without activation
            pattern = button.GetInvokePattern()
            return pattern is not None and pattern.Invoke() is not False
        except Exception:
            return False

    def _claude_open(self, item: dict, titles: list[str]):
        taken=False
        try:
            hwnd,root=self._claude_root()
            if self._claude_document(root,item['id']) is not None:return hwnd,root
            for button in self._claude_sidebar_buttons(root,item,titles)[:4]:
                clicked=time.time()
                if not self._claude_press(hwnd,button):continue
                # Once Claude's log shows the click was taken, wait for the page and open no link: on 10-12 a 42 MB
                # session took 37 s to draw after its click, and the link opened 12 s in only started a second
                # Claude.exe. With no such line in 3 s this button led elsewhere (another session of the same title),
                # and the next one is pressed; after the last, the link below decides.
                start=time.monotonic()
                while True:
                    if self._claude_document(root,item['id']) is not None:return hwnd,root
                    waited=time.monotonic()-start
                    taken=taken or claude_focus_logged(item['id'],clicked)
                    if waited>=(CLAUDE_SWITCH_TAKEN_WAIT if taken else 3):break
                    time.sleep(.25)
                if taken:break
        except ChatError:pass
        if taken:
            raise InputNotSubmitted(f"电脑上的 Claude 已经切到这个会话，但 {CLAUDE_SWITCH_TAKEN_WAIT} 秒还没显示出来（对话很长时会这样），尚未发送；请稍后再发")
        # Claude ignores a link identical to the one before it ("second-instance: suppressing duplicate
        # argv" in its main.log), so a second try with the same link changed nothing; a random tail makes
        # every link new and the session address is unaffected.
        os.startfile(f"claude://claude.ai/epitaxy/{item['id']}?r={secrets.token_hex(3)}")
        hwnd = self._front(CLAUDE_PROCESS, 8.0)
        if not hwnd:
            raise SendNotSubmitted("电脑上 Claude 没开，尚未发送")
        root = self._need_auto().ControlFromHandle(hwnd)
        deadline=time.monotonic()+CLAUDE_SWITCH_WAIT
        while time.monotonic()<deadline and self._claude_document(root,item['id']) is None:time.sleep(.25)
        if self._claude_document(root,item['id']) is None:
            shown = self._claude_title(root)
            raise InputNotSubmitted(f"电脑上的 Claude 等了 {CLAUDE_SWITCH_WAIT} 秒还没切到这个会话（现在显示的是「{shown or '别的页面'}」），尚未发送")
        return hwnd, root

    def _claude_wait_prompt(self, root, conv_id: str, seconds: float = CLAUDE_PROMPT_WAIT):
        """Right after a switch the session's message box can be missing for a moment, or be rebuilt while it
        is being read (a busy PC draws slowly); nothing has been typed yet, so just look again."""
        deadline = time.monotonic() + seconds
        while True:
            try:
                return self._claude_verified_prompt(root, conv_id)
            except Exception as exc:
                if time.monotonic() >= deadline:
                    if isinstance(exc, ChatError):
                        raise
                    raise InputNotSubmitted("Claude 输入框还没准备好，尚未发送") from exc
            time.sleep(0.2)

    def _claude_dock(self, root):
        """The part below the conversation that holds the message box and, above it, Claude's questions and plan
        choices (class approval-dock): six levels up from the box on 10-12. Going up from the box takes 0.03 s;
        searching the window for it took 0.45 s, every 5 s while the phone shows the conversation, on the one desktop
        worker that also sends. With no message box (a question can take its place) the window is searched as before."""
        try:
            for edit in self._find(root,'EditControl','Prompt'):
                node=edit
                for _ in range(12):
                    node=node.GetParentControl()
                    if node is None:break
                    if 'approval-dock' in (node.ClassName or ''):return node
        except Exception:pass
        dock = root.GroupControl(searchDepth=45, Compare=lambda c, d: "approval-dock" in (c.ClassName or ""))
        return dock if dock.Exists(1, 0.1) else None

    def _claude_ask(self, root, doc=None):
        """Where Claude asks something: its newest question card, or else the dock. In Claude's new window (10-26) a
        question (AskUserQuestion) is a card among the messages (CLAUDE_QUESTION_CARD) and the dock holds only the message
        box; read in the dock alone, the phone showed no question at all, with the conversation on screen all along
        (10-26 22:00-22:17), and none could be answered from it. A card with no button left to press is passed over.
        doc: the conversation, to look in it alone (one question to Windows) rather than the whole window."""
        try:
            for card in reversed(self._find_class(doc if doc is not None else root, CLAUDE_QUESTION_CARD)):
                if any(button.IsEnabled for button in self._find(card, "ButtonControl")):
                    return card
        except Exception:
            pass
        return self._claude_dock(root)

    # -- actions (run on the worker thread)

    def send(self, app: str, conv_id: str, text: str, images=None, replace=None) -> dict:
        """Open the conversation, put the text in, press Enter. Returns right after Enter; the phone then
        asks check() until the message shows up in the conversation file.
        replace: text in Claude's box that the phone was shown (DesktopDraft) and agreed may be replaced."""
        text = clean_text(text)
        require_send_desktop()
        item = find(app, conv_id)
        path = conv_path(item)
        offset = file_size(path)
        started = time.time()
        name = "Codex" if app == "codex" else "Claude"
        try:
            if app == "codex":
                self._send_codex(item, text)
            else:
                self._send_claude(item, text, images, replace)
        except ChatError as exc:  # the phone shows it too, but a failed send should be in the log
            self.log(f"没发给 {name}「{item['title']}」（{time.time() - started:.1f} 秒）：{exc}")
            raise
        self.log(f"发给 {name}「{item['title']}」：{one_line(text, 40)}（{time.time() - started:.1f} 秒提交）")
        return {"ok": True, "pressed": True, "offset": offset, "running": summary(item).get("status") == "running",
                "text": "已提交，等待对话记录确认" if app=='claude' else "已按回车，等对话记录确认"}

    @staticmethod
    def check(app: str, conv_id: str, offset: int, text: str) -> dict:
        """Has the message from send() reached the conversation file? (no window work: runs anywhere)"""
        item = find(app, conv_id)
        if app=='claude':
            stage=claude_delivery_stage(conv_path(item),int(offset),clean_text(text))
            return {'delivered':stage=='received','queued':stage=='queued','stage':stage}
        return {"delivered": delivered(app, conv_path(item), int(offset), clean_text(text))}

    def _send_codex(self, item: dict, text: str) -> None:
        encoded = quote(text, safe="")
        direct = len(encoded) <= URL_PREFILL_LIMIT
        url = f"codex://threads/{item['id']}?prompt=" + (encoded if direct else quote(PLACEHOLDER, safe=""))
        old = app_window(CODEX_PROCESS)
        before = picture_mark(old) if old else None
        os.startfile(url)
        hwnd = self._front(CODEX_PROCESS, 8.0)
        if not hwnd:
            raise ChatError("电脑上 Codex 没开，或者没能打开它的窗口")
        settle(hwnd, before if hwnd == old else None)
        with self.input_lock:
            if not direct:
                self._paste(hwnd, text)
            require_send_desktop()
            winctl.press(hwnd, "Enter")

    def _claude_image_count(self,edit):
        """Pictures waiting in the message box: its Remove image/attachment/file buttons, counted in the nearest
        surrounding part that holds the box's Add button."""
        node=edit
        for _ in range(9):
            node=node.GetParentControl()
            if any(not c.IsOffscreen for c in self._find(node,'ButtonControl','Add')):
                # Current Claude places the attachment tray just OUTSIDE the
                # first ancestor holding Add (live probe: depth 4 has zero
                # removers, depth 5 has the pasted card). Expand once, bounded
                # by the same unique composer, never to the document/window.
                parent=node.GetParentControl() if hasattr(node,'GetParentControl') else None
                if parent is not None and parent.ControlTypeName not in ('DocumentControl','WindowControl'):
                    prompts=self._find(parent,'EditControl','Prompt')
                    adds=self._find(parent,'ButtonControl','Add')
                    if len(prompts)==1 and len(adds)==1:node=parent
                buttons=self._find(node,'ButtonControl')
                previews={c.Name for c in buttons if not (c.Name or '').startswith('Remove ')}
                count=0
                for c in buttons:
                    name=c.Name or ''
                    # Current attachment cards pair image.png with Remove image.png.
                    # UIA may report the preview/remover as offscreen while the
                    # composer is active. Their paired presence in this bounded
                    # composer proves the card exists. Count each
                    # card, not distinct filenames (all clipboard images share one).
                    paired=name.startswith('Remove ') and name[7:] in previews
                    if paired or not c.IsOffscreen and re.match(r'^Remove (?:image|attachment|file)',name,re.I):count+=1
                return count
        raise InputNotSubmitted('无法核对 Claude 图片附件，尚未发送')

    def _paste_claude_image(self,hwnd,root,item,edit,path,expected_count):
        """Paste bitmap data, never text shortcuts. Submit only after the attachment appears."""
        import io,win32clipboard,win32con
        from PIL import Image
        with Image.open(path) as source:
            buf=io.BytesIO();source.convert('RGB').save(buf,format='BMP');dib=buf.getvalue()[14:]
        _clip_open();saved={}
        try:
            fmt=0
            while True:
                fmt=win32clipboard.EnumClipboardFormats(fmt)
                if not fmt:break
                try:
                    value=win32clipboard.GetClipboardData(fmt)
                    if isinstance(value,(bytes,str)):saved[fmt]=value
                except Exception:pass
            win32clipboard.EmptyClipboard();win32clipboard.SetClipboardData(win32con.CF_DIB,dib)
            sequence=win32clipboard.GetClipboardSequenceNumber()
        finally:win32clipboard.CloseClipboard()
        try:
            winctl.focus(hwnd);_,edit=self._claude_verified_prompt(root,item['id']);edit.SetFocus()
            if not edit.HasKeyboardFocus:raise InputNotSubmitted('Claude 图片粘贴焦点未确认，尚未发送')
            winctl.press(hwnd,'Control+v')
            deadline=time.monotonic()+6
            observed=0
            while time.monotonic()<deadline:
                _,edit=self._claude_verified_prompt(root,item['id'])
                observed=self._claude_image_count(edit)
                if observed==expected_count:return
                time.sleep(.15)
            # Counts only: enough to diagnose a future layout change without
            # putting draft text or filenames in the service log.
            try:
                node=edit;probe=[]
                for depth in range(1,10):
                    node=node.GetParentControl()
                    if node is None:break
                    buttons=self._find(node,'ButtonControl')
                    removes=[c for c in buttons if (c.Name or '').startswith('Remove ')]
                    probe.append((depth,sum(c.Name=='Add' for c in buttons),len(removes),sum(not c.IsOffscreen for c in removes)))
                    if node.ControlTypeName=='DocumentControl':break
                self.log(f'Claude attachment probe expected={expected_count} observed={observed} scopes(depth,add,remove,visible_remove)={probe}')
            except Exception:pass
            raise InputNotSubmitted(f'第 {expected_count} 张图片核验未通过（输入区识别到 {observed} 张），尚未发送；后续图片未继续粘贴，请检查桌面草稿')
        finally:
            _clip_open()
            try:
                if win32clipboard.GetClipboardSequenceNumber()==sequence:
                    win32clipboard.EmptyClipboard()
                    for fmt,value in saved.items():
                        try:win32clipboard.SetClipboardData(fmt,value)
                        except Exception:pass
            finally:win32clipboard.CloseClipboard()

    @staticmethod
    def _keyboard_owner():
        """The window someone at the PC is using: keyboard or mouse used within KEYBOARD_IN_USE seconds, and not Claude."""
        try:
            idle=winctl.idle_seconds()
            if idle is None or idle>KEYBOARD_IN_USE:return None
            hwnd=win32gui.GetForegroundWindow()
            if not hwnd or _process_of(hwnd)==CLAUDE_PROCESS or win32gui.GetClassName(hwnd) in ('Progman','WorkerW','Shell_TrayWnd'):return None
            return hwnd
        except Exception:return None

    @staticmethod
    def _give_back_keyboard(before):
        """Writing into Claude's box through UI Automation makes Claude the active window (10-12: Notepad was in front until
        the text was written, Claude after). Someone using the PC gets the keyboard back in the window they were in, so
        what they type goes there and not into Claude's box (10-12 21:31: an 'e'). With nobody at the PC Claude stays in
        front, where its questions keep reaching the phone."""
        if not before:return
        try:
            if win32gui.IsWindow(before) and not win32gui.IsIconic(before) and _process_of(win32gui.GetForegroundWindow())==CLAUDE_PROCESS:
                winctl.focus(before,strict=False)
        except Exception:pass

    def _send_claude(self, item: dict, text: str, images=None, replace=None) -> None:
        before=self._keyboard_owner()
        try:self._send_claude_now(item,text,images,replace)
        finally:self._give_back_keyboard(before)

    def _send_claude_now(self, item: dict, text: str, images=None, replace=None) -> None:
        titles = [item["title"], conversation_title(item)]
        hwnd, root = self._claude_open(item, titles)
        self._claude_show(hwnd)  # a minimised window reads stale: the message box still held the last message (10-12)
        self._claude_wait_prompt(root, item['id'])
        with self.input_lock:
            require_send_desktop()
            try:
                doc,edit=self._fill_claude_prompt(item,root,text,replace)
                if images:
                    if self._claude_image_count(edit):raise InputNotSubmitted('Claude 桌面已有附件，尚未发送；请先处理桌面草稿')
                    for index,image in enumerate(images,1):
                        self._paste_claude_image(hwnd,root,item,edit,image['path'],index)
                    doc,edit=self._claude_verified_prompt(root,item['id'])
                    if self._claude_image_count(edit)!=len(images):raise InputNotSubmitted('Claude 附件数量已变化，尚未发送')
                controls=[c for c in self._find(doc,'ButtonControl','Send') if not c.IsOffscreen and c.IsEnabled]
                if len(controls)!=1:raise InputNotSubmitted('没有唯一可用的 Claude 发送按钮，尚未发送')
                require_send_desktop()
                _,edit=self._claude_verified_prompt(root,item['id'])
                if not self._same_input(self._value(edit),text):raise InputNotSubmitted('提交前输入内容已变化，尚未发送')
            except ChatError:raise
            except Exception as exc:  # the window changed under UI Automation before Send was pressed
                raise InputNotSubmitted('Claude 界面正在变化，尚未发送；手机副本已保留') from exc
            try:
                pattern=controls[0].GetInvokePattern()
                if pattern is None:raise InputNotSubmitted('Claude 发送按钮不支持可靠提交，尚未发送')
                if pattern.Invoke() is False:raise ChatError('Claude 发送按钮结果未确认，请先核对，不会重复提交')
            except InputNotSubmitted:raise
            except Exception as exc:raise ChatError('Claude 提交结果未确认，请先核对，不会自动重复提交') from exc
            self.sent_last[item['id']]=text  # a copy of it left in the box is no one's draft

    def press_enter(self, app: str, conv_id: str) -> dict:
        """The 'press Enter once more' button: only when that app is in front."""
        process = CODEX_PROCESS if app == "codex" else CLAUDE_PROCESS
        if front_process() != process:
            raise ChatError("那个应用现在不在电脑最前面，没按")
        hwnd = app_window(process)
        with self.input_lock:
            winctl.press(hwnd, "Enter")
        return {"ok": True, "text": "按了回车"}

    def open(self, app: str, conv_id: str) -> dict:
        item = find(app, conv_id)
        if app == "codex":
            os.startfile(f"codex://threads/{item['id']}")
            self._front(CODEX_PROCESS, 6.0)
        else:
            self._claude_open(item, [item["title"], conversation_title(item)])
        return {"ok": True, "text": f"电脑上已打开「{item['title']}」"}

    def new_codex(self, folder: str, text: str) -> dict:
        """Start a Codex thread with this first message. Returns right after Enter; the phone then asks
        new_check() until the thread shows up (Codex takes several seconds to set a new thread up)."""
        text = clean_text(text)
        if folder and not Path(folder).is_dir():
            raise ChatError("这个文件夹不存在")
        started = int(time.time() * 1000)
        encoded = quote(text, safe="")
        direct = len(encoded) <= URL_PREFILL_LIMIT
        url = "codex://threads/new?prompt=" + (encoded if direct else quote(PLACEHOLDER, safe=""))
        if folder:
            url += "&path=" + quote(folder, safe="")
        old = app_window(CODEX_PROCESS)
        before = picture_mark(old) if old else None
        os.startfile(url)
        hwnd = self._front(CODEX_PROCESS, 8.0)
        if not hwnd:
            raise ChatError("电脑上 Codex 没开，或者没能打开它的窗口")
        settle(hwnd, before if hwnd == old else None)
        with self.input_lock:
            if not direct:
                self._paste(hwnd, text)
            winctl.press(hwnd, "Enter")
        self.log(f"新建 Codex 对话：{one_line(text, 40)}")
        return {"ok": True, "pressed": True, "started": started, "text": "已按回车，等新对话出现"}

    def new_claude(self,*args,**kwargs):
        before=self._keyboard_owner()  # writing the first message makes Claude the active window, as in _send_claude
        try:return self._new_claude_now(*args,**kwargs)
        finally:self._give_back_keyboard(before)

    def _claude_new_buttons(self,root):
        doc,edit=self._claude_verified_prompt(root,'__new__')
        # The new Environment picker is a sibling of the composer. Query the
        # identity-checked new-session document instead of a fixed ancestor depth.
        return doc,[c for c in self._find(doc,'ButtonControl') if not c.IsOffscreen]

    @staticmethod
    def _claude_folder_ready(names,expected):
        if expected==CLAUDE_NO_FOLDER:
            modern=names.count('Environment: This computer')==1 and names.count('Folder: Choose folder…')==1
        else:modern=names.count('Environment: '+expected)==1
        return modern or ('Local' in names and names.count(expected)==1)

    def _new_claude_now(self,folder,text,images,dispatched,folder_unique=False,timing=None,prepare=None):
        """A fresh Code composer; never invoke a workspace-trust or permission button.

        folder '': a session in no folder, "No folder" on the desktop (Claude makes a scratch folder for it). The
        composer opens on the last folder used, so No folder is picked in its folder menu (10-12).
        folder_unique: no other folder the phone knows has this folder's name, so the folder button by the
        message box, which shows only the name, is proof enough. Otherwise its menu is opened to read the
        full path of the ticked entry; that check ran twice per new conversation and was the menu the user
        saw flicker open and shut after the folder had already changed (10-12)."""
        phase=timing or (lambda *args:None)
        phase('claude_open','打开 Claude 新建输入区')
        require_send_desktop();item={'id':'__new__'}
        expected=Path(folder).name if folder else CLAUDE_NO_FOLDER
        def bar(root):  # the new session's page and the buttons around its message box, in page order
            return self._claude_new_buttons(root)
        def close_menu(menu,hwnd):
            if self._claude_document(self._need_auto().ControlFromHandle(hwnd),'__new__') is not None and menu.Exists(.1) and not menu.IsOffscreen:
                # ExpandCollapse does not focus the popup. Escape in the composer can
                # cancel the folder selection instead of closing the menu.
                menu.SetFocus()
                if not menu.HasKeyboardFocus:
                    rows=[c for c,_ in self.auto.WalkControl(menu,maxDepth=5) if c.ControlTypeName=='RadioButtonControl']
                    if rows:rows[0].SetFocus()
                winctl.press(hwnd,'Escape');time.sleep(.15)
        def exact_folder(root,hwnd):
            if not folder:  # the folder button reads No folder; a second folder (Add another folder) needs a first one
                try:names=[c.Name for c in bar(root)[1]]
                except Exception:return False
                return self._claude_folder_ready(names,CLAUDE_NO_FOLDER) and 'Add another folder' not in names
            doc,buttons=bar(root)
            if any(c.Name=='Environment: '+expected for c in buttons):
                # The selected recent environment shows its full path on the
                # new page; other recent environments are only name buttons.
                target=str(Path(folder).resolve()).casefold()
                rows=self._find(doc,'ListItemControl')
                return sum((c.Name or '').casefold()==(expected+target).casefold() and not c.IsOffscreen for c in rows)==1
            if folder_unique:return ready(root)
            doc,edit=self._claude_verified_prompt(root,'__new__');node=edit
            for _ in range(6):node=node.GetParentControl()
            buttons=[c for c,_ in self.auto.WalkControl(node,maxDepth=3) if c.ControlTypeName=='ButtonControl' and c.Name==expected and not c.IsOffscreen]
            if len(buttons)!=1:return False
            pattern=buttons[0].GetExpandCollapsePattern()
            if pattern is None:return False
            pattern.Expand();menu=doc.MenuControl(Name=expected,searchDepth=70)
            if not menu.Exists(.5,.1):return False
            try:
                selected=[c for c,_ in self.auto.WalkControl(menu,maxDepth=5) if c.ControlTypeName=='RadioButtonControl' and c.GetSelectionItemPattern().IsSelected]
                return len(selected)==1 and selected[0].HelpText and Path(selected[0].HelpText).resolve()==Path(folder).resolve()
            finally:close_menu(menu,hwnd)
        def names(root):
            try:return [c.Name for c in bar(root)[1]]
            except Exception:return []
        def ready(root):return self._claude_folder_ready(names(root),expected)
        def pick_no_folder(root,hwnd):
            # The folder button sits right after Local; its menu starts with No folder (no path), then recent folders.
            doc,buttons=bar(root);shown=[c.Name for c in buttons]
            if self._claude_folder_ready(shown,CLAUDE_NO_FOLDER):return
            modern=[c for c in buttons if (c.Name or '').startswith('Environment: ')]
            if modern:
                if len(modern)!=1:raise InputNotSubmitted('Claude 环境选择器不唯一，首条消息未发送')
                trigger=modern[0];menu=doc.MenuControl(Name=trigger.Name,searchDepth=85)
                if not menu.Exists(.1) or menu.IsOffscreen:
                    pattern=trigger.GetExpandCollapsePattern()
                    if pattern is not None:pattern.Expand()
                    else:trigger.GetInvokePattern().Invoke()
                if not menu.Exists(1,.1):raise InputNotSubmitted('Claude 环境菜单没有打开，首条消息未发送')
                # Default must be under Local, never a similarly named cloud environment.
                groups=[c for c in self._find(menu,'GroupControl','Local') if not c.IsOffscreen]
                rows=[]
                for group in groups:
                    rows.extend(c for c in self._find(group,'MenuItemControl')+self._find(group,'RadioButtonControl') if c.Name=='Default' and not c.IsOffscreen and c.IsEnabled)
                if len(rows)!=1:
                    close_menu(menu,hwnd);raise InputNotSubmitted('Claude 没有唯一的本机 Default 环境，首条消息未发送')
                selected=rows[0].GetSelectionItemPattern()
                if selected is not None:selected.Select()
                else:rows[0].GetInvokePattern().Invoke()
                time.sleep(.3);close_menu(menu,hwnd)
                return
            at=shown.index('Local')+1 if 'Local' in shown else len(shown)
            pattern=buttons[at].GetExpandCollapsePattern() if at<len(buttons) else None
            if pattern is None:raise InputNotSubmitted('没找到 Claude 新建页的文件夹按钮，首条消息未发送')
            name=buttons[at].Name;pattern.Expand();menu=doc.MenuControl(Name=name,searchDepth=70)
            if not menu.Exists(1,.1):raise InputNotSubmitted('Claude 的文件夹菜单没有打开，首条消息未发送')
            rows=[c for c,_ in self.auto.WalkControl(menu,maxDepth=6) if c.ControlTypeName=='RadioButtonControl' and c.Name==CLAUDE_NO_FOLDER and not c.HelpText]
            if len(rows)!=1:
                close_menu(menu,hwnd);raise InputNotSubmitted('Claude 的文件夹菜单里没有 No folder，首条消息未发送')
            rows[0].GetSelectionItemPattern().Select();time.sleep(.3)  # picking closes the menu
            close_menu(menu,hwnd)
        hwnd,root=self._claude_root()
        self._claude_show(hwnd)  # minimised, the page and its buttons read stale (10-12)
        if not ready(root):
            if folder:
                # Use the desktop's existing project action where its name is unambiguous.
                paths={str(Path(v.get('origin') or v['cwd']).resolve()) for v in claude_sessions(1000000) if Path(v.get('origin') or v['cwd']).name==expected}
                buttons=self._find(root,'ButtonControl','New session in '+expected)
                if paths=={str(Path(folder).resolve())} and len(buttons)==1:buttons[0].GetInvokePattern().Invoke()
                else:os.startfile('claude://code/new?folder='+quote(folder,safe=''))
            elif not any(n=='Local' or n.startswith('Environment: ') for n in names(root)):
                # the sidebar's New (in the app, no second Claude.exe); the code/new link if it is not there
                buttons=self._find(root,'ButtonControl','New')  # 0.02 s; walking the window for it took 0.47 s (10-12)
                if len(buttons)==1:buttons[0].GetInvokePattern().Invoke()
                else:os.startfile('claude://code/new?r='+secrets.token_hex(3))
            hwnd=self._front(CLAUDE_PROCESS,8)
            if not hwnd:raise InputNotSubmitted('Claude 尚未打开，首条消息未发送')
            root=self._need_auto().ControlFromHandle(hwnd)
            until=time.monotonic()+12
            if not folder:
                while not any(n=='Local' or n.startswith('Environment: ') for n in names(root)) and time.monotonic()<until:time.sleep(.25)
                if any(n=='Local' or n.startswith('Environment: ') for n in names(root)):
                    with self.input_lock:pick_no_folder(root,hwnd)
            while not ready(root) and time.monotonic()<until:time.sleep(.25)
        if not ready(root):raise InputNotSubmitted('Claude 新建页尚未显示目标本机环境或文件夹，首条消息未发送；请检查桌面新建页后恢复草稿重试')
        if prepare:  # the model and effort picked on the phone (claude_control.apply_new); outside input_lock, which its menus take
            phase('claude_settings','设置模型与推理强度')
            prepare(hwnd)
        phase('claude_folder','核对 Claude 项目文件夹')
        with self.input_lock:
            require_send_desktop()
            if not exact_folder(root,hwnd):raise InputNotSubmitted('Claude 当前选定目录与手机不一致，首条消息未发送')
            phase('claude_fill','填写首条消息')
            doc,edit=self._fill_claude_prompt(item,root,text)
            phase('claude_images','准备图片附件')
            if self._claude_image_count(edit):raise InputNotSubmitted('Claude 新建输入框已有附件，请先处理电脑草稿')
            for index,image in enumerate(images,1):self._paste_claude_image(hwnd,root,item,edit,image['path'],index)
            phase('claude_verify','核对输入内容和发送按钮')
            doc,edit=self._claude_verified_prompt(root,'__new__')
            if not ready(root) or not self._same_input(self._value(edit),text) or self._claude_image_count(edit)!=len(images) or not exact_folder(root,hwnd):raise InputNotSubmitted('新对话内容发生变化，尚未发送')
            controls=[c for c in self._find(doc,'ButtonControl','Send') if c.IsEnabled and not c.IsOffscreen]
            if len(controls)!=1:raise InputNotSubmitted('Claude 新对话发送按钮尚未就绪')
            pattern=controls[0].GetInvokePattern()
            if pattern is None:raise InputNotSubmitted('Claude 发送按钮暂不可操作')
            require_send_desktop();dispatched()
            phase('claude_invoke','提交给 Claude')
            if pattern.Invoke() is False:raise ChatError('Claude 首条消息提交结果未确认，不会自动重试')

    @staticmethod
    def new_check(started: int, text: str) -> dict:
        item = codex_new_thread_since(int(started), clean_text(text))
        return {"id": item["id"], "title": item["title"], "folder": item["folder"]} if item else {"id": None}

    def claude_options(self, conv_id: str, open_first: bool = False) -> dict:
        """Buttons and choices Claude shows around its message box (permission prompts, questions)."""
        item = find("claude", conv_id)
        titles = [item["title"], conversation_title(item)]
        if open_first:
            hwnd, root = self._claude_open(item, titles)
        else:
            hwnd, root = self._claude_root()
        shown = self._claude_title(root)
        if not self._same_title(shown, titles):
            return {"on_screen": False, "shown": shown, "options": [], "running": None}
        box = self._claude_ask(root)  # a question card of Claude's new window (10-26), or else the dock
        if box is None:
            return {"on_screen": True, "shown": shown, "options": [], "running": None}
        card = question_card(box)
        auto = self.auto
        options, counts, kinds = [], {}, []
        running = False
        if card:  # Stop stays in the dock, below the card
            dock = self._claude_dock(root)
            running = dock is not None and bool(self._find(dock, "ButtonControl", "Stop"))
        for ctrl, depth in auto.WalkControl(box, maxDepth=30):
            ctype = ctrl.ControlTypeName
            del kinds[max(depth - 1, 0):]
            kinds.append(ctype)
            if ctype not in OPTION_TYPES or in_notice(kinds[:-1]):
                continue
            name = (ctrl.Name or "").strip()
            if ctype == "ButtonControl" and name == "Stop":
                running = True
            if ctype == "EditControl":
                if name == "Prompt":
                    continue
            elif not name or name in CLAUDE_FIXED_BUTTONS or name.startswith(CLAUDE_FIXED_PREFIXES):
                continue
            try:
                if ctrl.IsOffscreen and not card:  # a card scrolled out of view still asks
                    continue
                r = ctrl.BoundingRectangle
                if r.width() <= 2 or r.height() <= 2:
                    continue
            except Exception:
                continue
            key = (ctype, name)
            nth = counts.get(key, 0)
            counts[key] = nth + 1
            entry = {"type": ctype[: -len("Control")], "name": name[:300], "nth": nth}
            if ctype in ("CheckBoxControl", "RadioButtonControl"):
                try:
                    entry["checked"] = bool(ctrl.GetTogglePattern().ToggleState) if ctype == "CheckBoxControl" \
                        else bool(ctrl.GetSelectionItemPattern().IsSelected)
                except Exception:
                    pass
            if ctype == "EditControl":
                entry["value"] = self._value(ctrl)[:500]
            options.append(entry)
            if len(options) >= 40:
                break
        return {"on_screen": True, "shown": shown, "options": options, "running": running}

    def claude_press(self, conv_id: str, option: dict, text: str = "", enter: bool = False) -> dict:
        item = find("claude", conv_id)
        titles = [item["title"], conversation_title(item)]
        hwnd, root = self._claude_root()
        if not self._same_title(self._claude_title(root), titles):
            hwnd, root = self._claude_open(item, titles)
        box = self._claude_ask(root)  # where claude_options read the option
        if box is None:
            raise ChatError("Claude 的输入区没找到")
        ctype = str(option.get("type", "")) + "Control"
        name = str(option.get("name", ""))
        nth = int(option.get("nth", 0))
        seen = 0
        target = None
        for ctrl, _depth in self.auto.WalkControl(box, maxDepth=30):
            if ctrl.ControlTypeName == ctype and (ctrl.Name or "").strip() == name:
                if seen == nth:
                    target = ctrl
                    break
                seen += 1
        if target is None:
            raise ChatError(f"界面上已经没有「{name}」了，刷新一下选项")
        if ctype == "EditControl":
            with self.input_lock:
                winctl.focus(hwnd)
                target.SetFocus()
                time.sleep(0.1)
                self._paste(hwnd, text)
                if enter:
                    winctl.press(hwnd, "Enter")
            return {"ok": True, "text": "已填入" + ("并回车" if enter else "")}
        for how in ("Invoke", "Select", "Toggle"):
            try:
                if how == "Invoke":
                    target.GetInvokePattern().Invoke()
                elif how == "Select":
                    target.GetSelectionItemPattern().Select()
                else:
                    target.GetTogglePattern().Toggle()
                self.log(f"Claude「{item['title']}」：点了「{name}」")
                return {"ok": True, "text": f"点了「{name}」"}
            except Exception:
                continue
        r = target.BoundingRectangle
        with self.input_lock:
            winctl.click_screen(hwnd, (r.left + r.right) // 2, (r.top + r.bottom) // 2)
        self.log(f"Claude「{item['title']}」：点了「{name}」（鼠标）")
        return {"ok": True, "text": f"点了「{name}」"}


def conversation_title(item: dict) -> str:
    """The newest title written in a Claude transcript (renames land there before the index)."""
    if item["app"] != "claude":
        return ""
    path = conv_path(item)
    if path is None:
        return ""
    lines, _ = read_tail(path, 256 << 10)
    for raw in reversed(lines):
        if b"custom-title" in raw[:80]:
            try:
                return json.loads(raw).get("customTitle") or ""
            except ValueError:
                continue
    return ""
