"""Tells the phone when a conversation on this PC is done: an iPhone through Bark, an Android phone through ntfy.

Bark is a free iPhone app. It gives the phone an address (https://api.day.app/<key>/); what is sent there shows up
as a notification. Apple delivers it the way it delivers WeChat's, over the one connection the phone keeps to Apple
for all its apps, so nothing runs on the phone meanwhile. The address is pasted on the page (设置 → 手机通知) and
kept in remote_config.json as "bark"; it is not shown again and not written to the log.
Bark has no Android app. An Android phone gets them in the ntfy app, which subscribes to this service itself over
Tailscale (ntfy_feed.py); turned on on the page, kept as "ntfy": true. Both can be on, for two phones.
遥应's own notifications on the iPhone (10-26) need nothing set here: while an account has such a phone, the relay
reads GET /api/notify/push (ntfy_feed.relay_stream) and is told only which app, which conversation and whether it is
done, failed or waiting; it writes the words and asks Apple to deliver them (relay_push.py).

Every 2 s while a turn runs (5 s when not) the newest conversations are looked at. Since 0.6.4 each file is read from
where the last look stopped, so every start and end record is seen once; the first look goes back up to 64 MB for the
newest turn, and a turn's own timestamps (never the clock) say when it began and ended. A turn that ended there
after this service started (Codex: task_complete; Claude: an answer that stopped for good, not to use a tool) is sent
once, with the conversation's title and the start of its last answer; tapping it opens that conversation on this
computer's page. Not sent: turns the user stopped, and turns that end while the phone has that conversation open (its
live stream is connected). Someone using this PC no longer holds them back (10-27): the user wants them there too, and
the keyboard and mouse input that held them back for 2 minutes also came from programs (on 10-26, UI tests typing into
Claude once a second held back every one). What happened goes into the log, and the last few show under 设置 → 手机通知.
"""

from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import re
import sqlite3
import threading
import time
import tomllib
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import chats
import machines
import ntfy_feed
import pc_clock
from codex_control import native_approvals

POLL_SECONDS = 5   # between looks while nothing runs (user 10-28: pushes felt slow at 10 s)
POLL_FAST = 2      # between looks while any turn is running
HISTORY_BYTES = 64 << 20  # the first look reads back this far for the last start and end (0.6.4)
SNAPSHOT_EVERY = 60       # a running conversation's record reaches the relay this often (0.6.4)
SNAPSHOT_AGAIN = 60       # an empty snapshot, sent again once this later, for a relay that missed the first (11-01)
STEP_GAP = 15             # seconds between two progress events of one conversation (0.6.4)
APPROVAL_EVERY = 12       # seconds between desktop reads of a running Codex conversation's approvals (11-16)
LIMIT = 30              # conversations of each app looked at, newest first (and any still under way: _followed)
LATEST_TIME = 4102444800  # 2100-01-01 00:00:00 UTC: a turn's time later than this is a placeholder, not a time (11-27)
DEFAULT_SERVER = "https://api.day.app"
# The Codex threads a person talks in: the desktop's and the command line's, started by the user, by this service's
# new-conversation button (no thread_source) or by another conversation. Not: codex exec runs (the translation
# workflows start thousands), sub-agents, reviews, automations.
CODEX_WHERE = "source in ('vscode', 'cli') and coalesce(thread_source, '') in ('', 'user', 'agent_created_thread')"
# 定时任务 (11-24): the assistant that has such runs declares the setting's modes and its own rules; this module only
# carries the value around. The marker rules and the words below are the shared part.
POLICY_SECONDS = 60  # a task's automation.toml is read at most this often per id
_HEARTBEAT = re.compile(r"<heartbeat>([\s\S]*?)</heartbeat>", re.I)
_DECISION = re.compile(r"<decision>\s*(DONT_NOTIFY|NOTIFY)\s*</decision>", re.I)
_MESSAGE = re.compile(r"<message>([\s\S]*?)</message>", re.I)
_INBOX = re.compile(r"::inbox-item\{([^{}]*)\}")
_INBOX_PARAM = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')
_FENCE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```")
_TILDE = re.compile(r"~~~[A-Za-z0-9_-]*[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*~~~")
_ESCAPE = re.compile(r"<escape>([\s\S]*?)</escape>", re.I)
_TICKS = re.compile(r"`{1,2}([\s\S]*?)`{1,2}")
_AUTOMATION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_AUTOMATION_POLICY: dict[str, tuple] = {}  # id -> (when read, failed runs only)


class NotifyError(Exception):
    """Something to tell the person: the address is not Bark's, Bark refused it, Bark could not be reached."""


def parse_address(text: str) -> dict:
    """{server, key} from the address Bark shows (https://api.day.app/<key>/…, or a Bark server of one's own),
    or from the key alone."""
    text = (text or "").strip()
    m = re.search(r"((?:https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?)/([A-Za-z0-9_-]{6,80})(?=[/?#\s]|$)", text)
    if m:
        server = m[1] if m[1].startswith(("http://", "https://")) else "https://" + m[1]
        return {"server": server, "key": m[2]}
    if re.fullmatch(r"[A-Za-z0-9_-]{6,80}", text):
        return {"server": DEFAULT_SERVER, "key": text}
    raise NotifyError("没认出 Bark 的推送地址：在 Bark 首页复制 https://api.day.app/ 开头的那一行再贴")


def send(address: dict, title: str, body: str, subtitle: str = "", group: str = "", url: str = "",
         timeout: float = 10) -> None:
    """One notification to the phone; NotifyError when Bark does not take it."""
    data = {"device_key": address["key"], "title": title[:120], "body": body[:600] or "（没有文字）"}
    for name, value in (("subtitle", subtitle[:120]), ("group", group[:60]), ("url", url)):
        if value:
            data[name] = value
    request = urllib.request.Request(address["server"].rstrip("/") + "/push", method="POST",
                                     data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            answer = json.loads(exc.read() or b"{}")
        except ValueError:
            answer = {}
        reason = answer.get("message") if isinstance(answer, dict) else ""
        raise NotifyError(f"Bark 没收下（{exc.code}）：{reason or exc.reason}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        host = urlsplit(address["server"]).netloc
        raise NotifyError(f"连不上 Bark 的服务器 {host}：{getattr(exc, 'reason', None) or exc}") from None
    if not isinstance(answer, dict) or answer.get("code") != 200:
        raise NotifyError(f"Bark 没收下：{answer.get('message') if isinstance(answer, dict) else answer}")


# ---------------------------------------------------------------- how a conversation's newest turn stands


def turn_end(app: str, lines: list[bytes]) -> dict | None:
    """The newest turn in these lines of a conversation file: {"state": running / done / failed / stopped,
    "key": the same for one turn's end, "time": ISO time, "text": its last answer}; None when no turn shows."""
    from agents import registry
    try:
        return registry.get(app).notify_turn_end(lines)
    except Exception:
        return None


_CJK = "　-〿一-鿿＀-￯"


def _preview(text: str) -> str:
    """The start of an answer on one line, without Markdown marks or the spaces they leave inside Chinese."""
    line = chats.one_line(chats.plain(text or ""), 150)
    return re.sub(f"(?<=[{_CJK}]) (?=[{_CJK}])", "", line)


def used_text(started: int, ended: int) -> str:
    """'用了 6 分钟' for a turn of a minute or more; '' when shorter or unknown. The same words relay_push uses."""
    try:
        started, ended = int(started), int(ended)
    except (TypeError, ValueError):
        return ""
    if started <= 0 or ended - started < 60:
        return ""
    minutes = (ended - started) // 60
    if minutes < 60:
        return f"用了 {minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"用了 {hours} 小时" + (f" {rest} 分钟" if rest else "")


def time_text(seconds) -> str:
    """A turn's time as the ISO text a running record is told with; '' when there is none.

    0 is no time, and so is one no clock has: a 0001-01-01 placeholder reads as a huge negative number on 11-27,
    and datetime.fromtimestamp refuses those on Windows. Such a turn is told as one 遥应 noticed itself."""
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return ""
    if value <= 0 or value > LATEST_TIME:
        return ""
    try:
        return datetime.fromtimestamp(value).isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def notice_state(end: dict) -> str:
    """What happened to a turn in the words the iPhone's notice uses (relay_push.notice_body)."""
    if end.get("asks"):
        return "在等你选"
    if end.get("state") == "failed":
        return "出错停了"
    used = used_text(end.get("started") or 0, end.get("ended") or 0)
    return "好了" + (f" · {used}" if used else "")


def notice_title(title: str, app: str, computer: str) -> str:
    """A notice's first line: the conversation's title, or 'Codex · 家里电脑' when it has none (11-24)."""
    line = chats.one_line((title or "").strip(), 40)
    return f"{app} · {computer}" if line in ("", "（无标题）") else line


def sequence_id(app: str, conv_id: str) -> str:
    """ntfy's key for one conversation: a new notice replaces the old one in the app; 64 characters at most."""
    cleaned = re.sub(r"[^-_A-Za-z0-9]", "_", f"{app}-{conv_id}")
    if len(cleaned) <= 64:
        return cleaned
    return cleaned[:40] + "-" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def agent_push_fields(app: str) -> dict:
    """The name, colour, icon and protocol of an assistant newer than the three legacy ones.

    The three legacy assistants' events keep every byte they had, so an older relay reads them as before.
    A newer assistant's name is extra: a relay without these fields falls back to the id itself.
    """
    try:
        from agents import registry
        manifest = registry.get(app).manifest()
    except Exception:
        return {}
    if manifest.get("legacy"):
        return {}
    names = manifest.get("name") if isinstance(manifest.get("name"), dict) else {}
    icon = manifest.get("icon") if isinstance(manifest.get("icon"), dict) else {}
    return {
        "app_name": str(names.get("zh") or names.get("en") or ""),
        "app_color": str(manifest.get("color") or ""),
        "app_icon": str(icon.get("key") or ""),
        "min_protocol": int(manifest.get("min_protocol") or 1),
    }


def _cdata(text: str) -> str:
    """[text] without the CDATA shell."""
    return re.sub(r"<!\[CDATA\[|\]\]>", "", text or "")


def _peeled(text: str) -> str:
    """[text] with up to four shells off: a code block, <escape>, one or two backticks, a JSON string's quotes."""
    text = (text or "").strip()
    for _ in range(4):
        match = _FENCE.fullmatch(text) or _TILDE.fullmatch(text)
        if match:
            text = match.group(1).strip()
            continue
        match = _ESCAPE.fullmatch(text)
        if match:
            text = match.group(1).strip()
            continue
        match = _TICKS.fullmatch(text)
        if match:
            text = match.group(1).strip()
            continue
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            try:
                value = json.loads(text)
            except ValueError:
                break
            if isinstance(value, str):
                text = value.strip()
                continue
        break
    return text


def inbox_summary(raw: str) -> str:
    """What an automation wrote for its inbox (::inbox-item{title="…" summary="…"}); the last one wins."""
    found = _INBOX.findall(raw or "")
    if not found:
        return ""
    params = dict(_INBOX_PARAM.findall(found[-1]))
    return params.get("summary") or params.get("title") or ""


def _without_markers(text: str) -> str:
    """An answer without the heartbeat block and the inbox-item line, which a phone should not show."""
    text = _HEARTBEAT.sub("", text or "")
    return re.sub(r"(?m)^[ \t]*::inbox-item\{[^{}]*\}[ \t]*$", "", text)


def notice_decision(raw: str, heartbeat: bool = False, task: bool = False, failed: bool = False,
                    failed_only: bool = False, off: bool = False) -> dict:
    """Whether a turn's end goes to the phone, why not, and the words written for it (11-24, rechecked 11-24 night).

    Codex 26.1117's order: a heartbeat turn's bare DONT_NOTIFY; a heartbeat block's decision (the last block, bare or
    fenced, no other text needed); on a successful turn, the skip marks; on a successful empty answer, a heartbeat or
    a task run says nothing; then only-failed overrides all of it; anything left is sent. [task] is a cron thread or a
    heartbeat turn, [failed] this turn's own error (see agents/codex.py). Returns {"send", "why", "text"}."""
    text = raw or ""
    task = task or heartbeat  # a heartbeat turn is an automation run (change 2)
    if off and task:
        return {"send": False, "why": "定时任务的通知已关掉", "text": ""}
    bare = _cdata(text).strip()
    send, why, words = None, "", ""
    if heartbeat and bare == "DONT_NOTIFY":  # a heartbeat answer that is only this (Codex writes spaces in CDATA too)
        send, why = False, "Codex 说这次不用提醒"
    if send is None:
        blocks = list(_HEARTBEAT.finditer(text))
        found = blocks[-1] if blocks else None  # the last block decides; a block alone is a complete answer
        if found is not None:
            decision = _DECISION.search(found.group(1))
            if decision:
                if decision.group(1).upper() == "DONT_NOTIFY":
                    send, why = False, "Codex 说这次不用提醒"
                else:
                    message = _MESSAGE.search(found.group(1))
                    send, why, words = True, "", _cdata(message.group(1)).strip() if message else ""
    if send is None and not failed and _skip_marker(_peeled(bare)):
        send, why = False, "Codex 说这次不用提醒"
    if send is None and not failed and not bare and task:
        send, why = False, "定时任务这次没有回答"
    if failed_only:  # Codex's last override: a task that only wants failed runs
        send = bool(failed)
        why = "" if failed else "这个定时任务只在失败时提醒"
    if send is None:
        send, why = True, ""
    return {"send": send, "why": "" if send else why, "text": words}


def _skip_marker(text: str) -> bool:
    """Whether a whole answer is one of Codex's marks for "do not tell the user" (::SKIP_COMPLETION:: and friends)."""
    if re.fullmatch(r"::\s*SKIP_COMPLETION\s*::", text or "") or text == "skip_notification":
        return True
    if (text or "").startswith("{"):
        try:
            value = json.loads(text)
        except ValueError:
            return False
        return isinstance(value, dict) and value.get("type") in ("skip_notification", "skip_completion")
    return False


def automation_failed_runs_only(automation_id: str, home, clock=time.time) -> bool:
    """Whether the task's automation.toml under [home] says failed_runs_only; an id that could walk the path is never
    read, and the answer is kept POLICY_SECONDS (11-24)."""
    ident = (automation_id or "").strip()
    if not _AUTOMATION_ID.fullmatch(ident):
        return False
    now = clock()
    cached = _AUTOMATION_POLICY.get(ident)
    if cached is not None and now - cached[0] < POLICY_SECONDS:
        return cached[1]
    result = False
    try:
        with (Path(home) / "automations" / ident / "automation.toml").open("rb") as f:
            result = tomllib.load(f).get("notification_policy") == "failed_runs_only"
    except (OSError, ValueError):
        result = False  # unreadable or not TOML: the rule is not known, so the assistant's markers decide
    _AUTOMATION_POLICY[ident] = (now, result)
    return result


def _seconds(ts: str, fallback: float) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return fallback


def _unix(ts: str) -> int | None:
    """A record's ISO time as Unix seconds; None when it has none (0.6.4: times come from the record)."""
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return None


# 0.6.4 方案六: the kind of work a tool call is, from its recorded name (never its arguments' words). Checked against
# real records on this computer: Claude names Bash/PowerShell/Edit/Write/Read/Grep/Glob/WebSearch/WebFetch; Codex
# writes every command as a custom tool call named exec, and patches/searches run inside it.
CLAUDE_STEPS = {"Bash": "run", "PowerShell": "run", "Edit": "edit", "Write": "edit", "MultiEdit": "edit",
                "NotebookEdit": "edit", "Read": "read", "Grep": "read", "Glob": "read",
                "WebSearch": "search", "WebFetch": "search"}
CODEX_STEPS = {"exec": "run", "shell": "run", "exec_command": "run", "apply_patch": "edit",
               "web_search": "search", "search": "search", "js": "run"}
DEEPSEEK_STEPS = {"pwsh": "run", "shell": "run", "bash": "run", "terminal": "run", "exec": "run",
                  "apply_patch": "edit", "edit": "edit", "write": "edit", "write_file": "edit",
                  "read": "read", "read_file": "read", "grep": "read", "glob": "read",
                  "web_search": "search", "web_fetch": "search", "fetch": "search"}


def record_step(app: str, name: str, argument: str = "") -> str | None:
    """edit | run | search | read for one tool call, or None when it is not one of the four (0.6.4)."""
    from agents import registry
    try:
        return registry.get(app).notify_step(name, argument)
    except Exception:
        return None


def turn_start(previous, starts, now):
    """The current turn's start: the newest start the record showed, never an older turn's (0.6.5)."""
    return max(int(previous or 0), starts[-1] if starts else 0) or int(now)


def new_scan(app: str) -> dict:
    """What one conversation's turn looks like while its record is read a piece at a time (0.6.4)."""
    return {"app": app, "state": None, "started": "", "ended": "", "latest": "", "key": "", "text": "", "action": "",
            "raw_text": "", "automation_id": "", "automation_name": "", "abort_reason": "",
            "heartbeat": False, "error": False,
            "asks": set(), "answer_id": "", "last_kind": None, "last_stop": None, "uuids": set()}


def scan_lines(scan: dict, lines: list[bytes]) -> dict:
    """Read record lines into [scan]; the state after them is the newest turn's, with the record's own times."""
    from agents import registry
    try:
        agent = registry.get(scan["app"])
    except Exception:
        return scan
    for raw in lines:
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        agent.notify_scan_record(scan, rec)
    return scan


# ---------------------------------------------------------------- the watcher


class Notifier:
    def __init__(self, cfg: dict, name: str, log, save, clock=time.time, sender=send, page_url=None, feed=None,
                 bridge=None) -> None:
        self.cfg, self.name, self.log, self.save = cfg, name, log, save
        self.bridge = bridge  # codex_control.Bridge, for approval requests the record does not hold (11-16)
        self.approval_checks: dict[tuple, tuple] = {}  # (app, id) -> (when read, cards)
        self.reported_approvals: dict[tuple, str] = {}  # (app, id) -> the pending key last told
        self.clock, self.sender = clock, sender
        self.feed = feed or ntfy_feed.Feed(clock=clock)  # what the ntfy app on an Android phone listens to
        self.relay = ntfy_feed.Feed(topic="teleply-push", clock=clock)  # what the relay reads for 遥应's own
        self._own_url = page_url or (lambda: machines.own_url(machines.tailscale_status()))
        self.lock = threading.Lock()
        self.since = clock()                         # turns that ended before this are not sent
        self.sizes: dict[str, tuple] = {}            # conversation file -> (size, mtime) when last read
        self.reads: dict[tuple, dict] = {}           # (app, id) -> {offset, scan}: read only what was added
        self.ended: dict[tuple, str] = {}            # (app, id) -> key of its newest turn end seen, sent or not
        # (app, id) -> {since, key, title, source}; also decides the 2 s poll while a turn runs
        self.running: dict[tuple, dict] = {}
        # (app, id) -> the running one has been told to the relay on its current connection
        self.reported_running: set = set()
        self.waiting: dict[tuple, dict] = {}         # (app, id) -> {since, title}: a question waits for the user
        self.steps: dict[tuple, tuple] = {}          # (app, id) -> (action, when it was last told)
        self.last_snapshot = 0.0
        self.last_snapshot_empty = True
        self.snapshot_again = False  # the backup empty snapshot has gone (11-01)
        self.snapshot_force = True
        self.relay_was_on = False
        self.relay_was_listening = False
        self.running_quiet = True                    # kept for older callers; running is now always reported (0.6.4)
        self.open: collections.Counter = collections.Counter()  # (app, id) -> live streams the phone has on it
        self.recent: collections.deque = collections.deque(maxlen=8)  # the last outcomes, for the page
        self.url = ""                                # this computer's https address on Tailscale
        self._automation = False                     # the assistant with 定时任务 runs, found once (11-24)
        self.stopped = threading.Event()

    # -- what the page asks

    def address(self) -> dict | None:
        found = self.cfg.get("bark")
        return found if isinstance(found, dict) and found.get("key") and found.get("server") else None

    def ntfy_on(self) -> bool:
        return self.cfg.get("ntfy") is True

    def relay_on(self) -> bool:
        """The relay reads this computer's events now, or did lately (12 h, what the stream keeps for it): an account
        with a phone for 遥应's own notifications. A relay that comes back gets what it missed."""
        seen = self.relay.last_seen
        return self.relay.listening > 0 or bool(seen and self.clock() - seen < ntfy_feed.KEEP_SECONDS)

    def public(self) -> dict:
        found, seen = self.address(), self.feed.last_seen
        ntfy = {"on": self.ntfy_on(), "topic": self.feed.topic, "server": self.url.rstrip("/"),
                "listening": self.feed.listening, "last_seen": time.strftime("%m-%d %H:%M", time.localtime(seen)) if seen else ""}
        return {"configured": bool(found), "server": urlsplit(found["server"]).netloc if found else "", "ntfy": ntfy,
                "relay": {"listening": self.relay.listening > 0}, "automations": self.automations(),
                "recent": list(self.recent)[::-1]}

    def _automation_agent(self):
        """The assistant whose conversations may be automation runs (it declares automation_modes), or None."""
        if self._automation is False:
            from agents import registry
            self._automation = next((a for a in registry.load() if getattr(a, "automation_modes", None)), None)
        return self._automation

    def automation_modes(self) -> dict:
        return dict(getattr(self._automation_agent(), "automation_modes", {}) or {})

    def automations(self) -> str:
        """The 定时任务 setting the assistant declared: its modes; anything else reads as its default."""
        modes = self.automation_modes()
        mode = self.cfg.get("automations")
        return mode if mode in modes else str(getattr(self._automation_agent(), "automation_default", "") or "")

    def set_automations(self, mode: str) -> dict:
        modes = self.automation_modes()
        mode = str(mode or "").strip()
        if mode not in modes:
            raise NotifyError("定时任务的通知只有三个选项：跟 Codex 一样、只推失败的、不推")
        with self.lock:
            self.cfg["automations"] = mode
            self.save()
        self.log(f"通知：定时任务的通知已改成「{modes[mode]}」")
        return {"ok": True, "automations": mode, "text": f"已改成：{modes[mode]}"}

    def set_address(self, text: str) -> dict:
        """Keep the pasted address once a first notification went through; an empty one turns them off."""
        if not (text or "").strip():
            with self.lock:
                self.cfg.pop("bark", None)
                self.save()
            self.log("通知：已关掉")
            return {"ok": True, "configured": False, "text": "已关掉，不再推送"}
        found = parse_address(text)
        self.sender(found, f"{self.name}的通知设好了", "对话做完时会推到这里，点通知能打开那个对话。",
                    group=self.name, url=self.page_url())
        with self.lock:
            if self.address() is None and not self.ntfy_on() and not self.relay_on():
                self._count_from_now()
            self.cfg["bark"] = found
            self.save()
        self.log(f"通知：已设好（{urlsplit(found['server']).netloc}）")
        return {"ok": True, "configured": True, "text": "已保存，刚推了一条，看看手机"}

    def set_ntfy(self, on: bool) -> dict:
        """Turn on (or off) what the ntfy app gets; turned on, a first one goes to the phones listening now."""
        with self.lock:
            if on and self.address() is None and not self.ntfy_on() and not self.relay_on():
                self._count_from_now()
            if on:
                self.cfg["ntfy"] = True
            else:
                self.cfg.pop("ntfy", None)
            self.save()
        self.log("通知：ntfy " + ("已打开" if on else "已关掉"))
        if not on:
            return {"ok": True, "ntfy": False, "text": "ntfy 已关掉，不再推送"}
        self.feed.publish(f"{self.name}的通知设好了", "对话做完时会推到这里，点通知能打开那个对话。", click=self.page_url(),
                          icon=self.icon_url())
        return {"ok": True, "ntfy": True, "text": "已打开，刚推了一条，看看 ntfy" if self.feed.listening else
                "已打开。ntfy 现在没连着这台电脑：在 ntfy App 里订阅后就能收到"}

    def test(self, channel: str = "") -> dict:
        """One to try: on Bark ("bark"), on ntfy ("ntfy"), or on both when no channel is named."""
        found = self.address() if channel != "ntfy" else None
        ntfy = self.ntfy_on() and channel != "bark"
        if not found and not ntfy:
            raise NotifyError("ntfy 还没打开" if channel == "ntfy" else "还没设推送地址")
        texts = []
        if ntfy:
            self.feed.publish(f"{self.name}的通知是好的", "这是一条试推。", click=self.page_url(), icon=self.icon_url())
            texts.append("推了一条，看看 ntfy" if self.feed.listening else "推了一条，但 ntfy 现在没连着这台电脑")
        if found:
            self.sender(found, f"{self.name}的通知是好的", "这是一条试推。", group=self.name, url=self.page_url())
            texts.append("推了一条，看看手机")
        return {"ok": True, "text": "；".join(texts)}

    @contextlib.contextmanager
    def watching(self, app: str, conv_id: str):
        """While the phone has this conversation open (its live stream), its turns are not sent."""
        with self.lock:
            self.open[(app, conv_id)] += 1
        try:
            yield
        finally:
            with self.lock:
                self.open[(app, conv_id)] -= 1
                if self.open[(app, conv_id)] <= 0:
                    del self.open[(app, conv_id)]

    def page_url(self, item: dict | None = None) -> str:
        if not self.url:
            try:
                self.url = self._own_url() or ""
            except Exception:
                self.url = ""
        if not self.url:
            return ""
        return self.url + (f"?open={item['app']}:{quote(item['id'], safe='')}" if item else "")

    def icon_url(self) -> str:
        """The icon a notice carries: this computer's page, which serves it without a token (11-24)."""
        root = self.page_url()
        return root.rstrip("/") + "/icon-192.png" if root else ""

    # -- the loop

    def start(self) -> None:
        threading.Thread(target=self._run, name="notify", daemon=True).start()

    def close(self) -> None:
        self.stopped.set()

    def _poll_seconds(self) -> float:
        """2 s while a turn runs, 5 s otherwise: the record's next change reaches the relay and the island sooner."""
        return POLL_FAST if self.running else POLL_SECONDS

    def _run(self) -> None:
        self.page_url()  # the Tailscale name takes up to 5 s to read; not when the first notification is due
        trouble = ""
        while not self.stopped.wait(self._poll_seconds()):
            try:
                self.look()
                trouble = ""
            except Exception as exc:
                if str(exc) != trouble:  # once for each kind of trouble, not every few seconds
                    trouble = str(exc)
                    self.log("通知：读对话出错\n" + traceback.format_exc())

    def look(self) -> None:
        found = self.address()
        on = self.relay_on()
        listening = self.relay.listening > 0
        if listening and not self.relay_was_listening:  # the relay came (back): running turns and a snapshot again
            self.reported_running.clear()
            self.steps.clear()
            self.last_snapshot = 0
            self.snapshot_force = True
        self.relay_was_listening = listening
        self.relay_was_on = on
        if found is None and not self.ntfy_on() and not on:
            self.since = None  # nothing to send to; once Bark, ntfy or the relay is on, only later turns count
            return
        if self.since is None:
            self._count_from_now()
        from agents import registry
        for item in self._conversations():
            try:
                agent = registry.get(item["app"])
            except Exception:
                continue
            if agent.notify_poll(self, found, item):
                continue
            scan = self._scan_file(item)
            if scan is None or scan.get("state") is None:
                continue
            conv = (item["app"], item["id"])
            title = chats.one_line(item.get("title") or "", 60)
            # A turn waiting on an approval writes nothing more to the record, so its start record still reads
            # running; only such a turn is worth the desktop read (11-16).
            if scan["state"] == "running" and agent.notify_check_approvals(self, item, conv, title, found):
                continue
            latest = _unix(scan.get("latest"))
            if scan["state"] == "running" and latest and self.clock() - latest > chats.STALE_SECONDS:
                # a record left "running" by a crash or a killed app: not a turn doing work now (same 20 min as lists)
                self.running.pop(conv, None)
                self.waiting.pop(conv, None)
                continue
            if scan["state"] == "running":
                self.waiting.pop(conv, None)
                self._running(item, scan)
                self._step(item, scan, on)
                continue
            previous = self.running.pop(conv, None) or {}
            self.waiting.pop(conv, None)
            self.reported_approvals.pop(conv, None)
            self.reported_running.discard(conv)
            key = scan.get("key") or scan.get("ended") or ""
            if self.ended.get(conv) == key:
                continue
            self.ended[conv] = key
            ended = _unix(scan.get("ended"))
            aborted = scan.get("abort_reason") or ""
            # 11-24 night: a cron thread or a heartbeat turn is an automation run. Codex marks one failed when an
            # error event appeared in it (it still ends with task_complete), or when it was aborted for any reason
            # other than the user's own stop. Other conversations keep the old behaviour.
            automation_turn = bool(item.get("automation")) or bool(scan.get("heartbeat"))
            failed_run = (automation_turn and aborted != "interrupted"
                          and (bool(scan.get("error")) or bool(aborted)))
            if scan["state"] == "stopped" and not failed_run:
                continue
            if ended is not None and ended < self.since:
                continue
            answer = scan.get("text") or ""
            started = _unix(scan.get("started")) or previous.get("since") or 0
            source = "记录" if _unix(scan.get("started")) else ("不知道" if not started else "电脑注意到")
            self._tell(found, item, {"state": "failed" if failed_run else scan["state"], "key": key,
                                     "time": scan.get("ended") or "", "text": answer,
                                     "raw_text": scan.get("raw_text") or "", "abort_reason": aborted,
                                     "automation": automation_turn, "heartbeat": bool(scan.get("heartbeat")),
                                     "automation_id": scan.get("automation_id") or "",
                                     "automation_name": scan.get("automation_name") or "",
                                     "started": int(started or self.clock()),
                                     "ended": int(ended or self.clock()), "started_source": source})
        self.running_quiet = False
        self._snapshot()

    def _codex_approvals(self, item: dict, conv: tuple, title: str, found: dict | None) -> bool:
        """11-16: Codex's approval requests are only in the desktop's live state, never in the record, so a turn
        waiting on one looked like a turn doing work forever. Read them (at most every ~12 s, without blocking on
        the bridge), tell the relay and the banner 在等你 once, and keep the conversation in `waiting` while the
        request is there. The 20-minute record rule must not drop it: the record does not change while it waits.
        A request that is gone puts the turn back to running, reported once more."""
        found_bridge = getattr(self, "bridge", None)
        if found_bridge is None:
            return False
        now = self.clock()
        checked = self.approval_checks.get(conv)
        cards = checked[1] if checked and now - checked[0] < APPROVAL_EVERY else None
        if cards is None:
            try:
                if found_bridge.lock.acquire(blocking=False):
                    try:
                        _, _, state = found_bridge.snapshot(item["id"], timeout=2)
                        cards = native_approvals(state)
                    finally:
                        found_bridge.lock.release()
            except Exception:
                cards = None  # cannot tell: leave whatever was already said alone
            if cards is not None:
                self.approval_checks[conv] = (now, cards)
        if cards is None:
            return self.reported_approvals.get(conv) is not None
        if cards:
            key = "pending:" + ",".join(sorted(str(v["request_id"]) for v in cards))
            previous = self.running.get(conv) or {}
            since = int(previous.get("since") or self.clock())
            self.running.pop(conv, None)
            self.waiting[conv] = {"since": since, "title": title, "item": item}
            if self.reported_approvals.get(conv) != key:
                self.reported_approvals[conv] = key
                source = "记录" if previous.get("source") == "记录" else "电脑注意到"
                self._tell(found, item, {"state": "done", "key": key, "time": "", "asks": True,
                                         "text": "Codex 在等你批准，请打开对话处理。",
                                         "started": since, "ended": int(self.clock()),
                                         "started_source": source})
            return True
        if self.reported_approvals.pop(conv, None) is not None:
            # Handled on the phone or the PC: the turn is working again, so say running once more.
            self.waiting.pop(conv, None)
            self.running.pop(conv, None)
            self.reported_running.discard(conv)
        return False

    def _scan_file(self, item: dict) -> dict | None:
        """The conversation's newest turn, read from where the file was last read to (0.6.4). The first look goes back
        up to HISTORY_BYTES, so a start record far from the end is still seen; after that only the added bytes are read."""
        path = chats.conv_path(item)
        if path is None:
            return None
        conv = (item["app"], item["id"])
        try:
            st = path.stat()
        except OSError:
            return None
        slot = self.reads.get(conv)
        if slot and st.st_ino == slot.get("inode") and st.st_dev == slot.get("dev") and st.st_size >= slot["offset"]:
            if st.st_size == slot["offset"]:
                return slot["scan"]
            try:
                with path.open("rb") as f:
                    f.seek(slot["offset"])
                    data = f.read(st.st_size - slot["offset"])
            except OSError:
                return slot["scan"]
            cut = data.rfind(b"\n")
            if cut >= 0:
                scan_lines(slot["scan"], data[:cut + 1].splitlines())
                slot["offset"] += cut + 1
            self.sizes[str(path)] = (st.st_size, st.st_mtime_ns)
            return slot["scan"]
        start = max(0, st.st_size - HISTORY_BYTES)
        try:
            with path.open("rb") as f:
                f.seek(start)
                data = f.read(st.st_size - start)
        except OSError:
            return None
        shift = 0
        if start:
            first = data.find(b"\n")
            shift = first + 1 if first >= 0 else len(data)
            data = data[shift:]
        complete = data.rfind(b"\n") + 1
        scan = new_scan(item["app"])
        scan_lines(scan, data[:complete].splitlines())
        self.reads[conv] = {"offset": start + shift + complete, "inode": st.st_ino, "dev": st.st_dev, "scan": scan}
        self.sizes[str(path)] = (st.st_size, st.st_mtime_ns)
        return scan

    def _running(self, item: dict, scan: dict | None = None) -> None:
        """A turn is running: told to the relay with the record's real start, once per relay connection (0.6.4).
        Only the app, the conversation and when it began; never the words."""
        conv = (item["app"], item["id"])
        scan = scan or {}
        record_start = _unix(scan.get("started"))
        previous = self.running.get(conv, {}).get("since")
        since = record_start or previous or int(self.clock())
        source = "记录" if record_start else ("电脑注意到" if previous else "不知道")
        self.running[conv] = {"since": int(since), "key": scan.get("key") or "", "source": source,
                              "title": chats.one_line(item.get("title") or "", 60), "item": item}
        if not self.relay_on() or conv in self.reported_running:
            return
        try:
            self.relay.publish("", "", extra={"kind": "running", "app": item["app"], "chat": item["id"],
                                              # 11-27: the island counts up from these against its own now.
                                              "since": pc_clock.to_true_seconds(int(since)),
                                              "started": pc_clock.to_true_seconds(int(since)),
                                              "started_source": source,
                                              "title": chats.one_line(item.get("title") or "", 60),
                                              **agent_push_fields(item["app"])},
                               keep=True)
            self.reported_running.add(conv)
        except Exception:
            self.log("通知：在干活没报给中转\n" + traceback.format_exc())

    def _step(self, item: dict, scan: dict, on: bool) -> None:
        """方案六: the action changed (at most once in STEP_GAP seconds). Progress is not kept for a reconnect."""
        action = scan.get("action")
        if not action:
            return
        conv = (item["app"], item["id"])
        last = self.steps.get(conv)
        if last and (last[0] == action or self.clock() - last[1] < STEP_GAP):
            return
        self.steps[conv] = (action, self.clock())
        if not on:
            return
        try:
            self.relay.publish("", "", extra={"kind": "step", "app": item["app"], "chat": item["id"], "step": action,
                                              "since": pc_clock.to_true_seconds(
                                                  int(self.running.get(conv, {}).get("since") or self.clock())),
                                              "title": chats.one_line(item.get("title") or "", 60),
                                              **agent_push_fields(item["app"])}, keep=False)
        except Exception:
            self.log("通知：进度没报给中转\n" + traceback.format_exc())

    def _snapshot(self, force: bool = False) -> None:
        """Every 60 s while something runs (and once when the relay connects): all running and waiting conversations
        on this computer. An empty snapshot goes only after the last one ended, or on a reconnect (0.6.5 fix)."""
        force = force or self.snapshot_force
        if not self.relay_on():
            return
        # an empty snapshot goes as soon as the last conversation ends, not on the next minute
        transition_empty = not (self.running or self.waiting) and not self.last_snapshot_empty
        if not (force or transition_empty) and self.clock() - self.last_snapshot < SNAPSHOT_EVERY:
            return
        items = []
        for conv, info in self.running.items():
            items.append({"app": conv[0], "chat": conv[1], "state": "working",
                          # 11-27: the island counts up from these against its own now.
                          "started": pc_clock.to_true_seconds(int(info["since"])),
                          "since": pc_clock.to_true_seconds(int(info["since"])), "title": info.get("title", ""),
                          "step": (self.steps.get(conv) or ("", ""))[0],
                          **agent_push_fields(conv[0])})
        for conv, info in self.waiting.items():
            items.append({"app": conv[0], "chat": conv[1], "state": "waiting",
                          "started": pc_clock.to_true_seconds(int(info["since"])),
                          "since": pc_clock.to_true_seconds(int(info["since"])), "title": info.get("title", ""),
                          "step": (self.steps.get(conv) or ("", ""))[0],
                          **agent_push_fields(conv[0])})
        if not items and self.last_snapshot_empty and not force:
            # 11-01: an older relay may have been reading nothing at the moment the first empty snapshot went; send it
            # once more a minute later, never again until something ran.
            if self.snapshot_again or self.clock() - self.last_snapshot < SNAPSHOT_AGAIN:
                return
        again = not items and not force and self.last_snapshot_empty
        try:
            self.relay.publish("", "", extra={"kind": "snapshot", "items": items}, keep=False)
            self.last_snapshot = self.clock()
            self.last_snapshot_empty = not items
            self.snapshot_again = again
            self.snapshot_force = False
        except Exception:
            self.log("通知：快照没报给中转\n" + traceback.format_exc())

    def asking(self, item: dict, text: str) -> None:
        """Claude waits on a question or a permission in the middle of a turn, as Claude Code's hook tells it
        (claude_hooks.py): sent as a turn that ends with a question is. The record reads as running then, so such a
        wait was never sent before 10-27."""
        found = self.address()
        if found is None and not self.ntfy_on() and not self.relay_on():
            return
        conv = (item["app"], item["id"])
        started = int(self.running.get(conv, {}).get("since") or self.clock())
        try:
            self._tell(found, item, {"state": "done", "key": "", "time": "", "text": text, "asks": True,
                                     "started": started, "ended": int(self.clock()),
                                     "started_source": "记录" if self.running.get(conv, {}).get("source") == "记录"
                                     else "电脑注意到" if self.running.get(conv) else "不知道"})
        except Exception:
            self.log("通知：Claude 在等回答，没推出去\n" + traceback.format_exc())

    def _count_from_now(self) -> None:
        self.since = self.clock()
        self.sizes.clear()
        self.ended.clear()
        self.reads.clear()
        self.reported_running.clear()
        self.steps.clear()

    def _conversations(self) -> list[dict]:
        from agents import registry
        rows: list[dict] = []
        full_by_app: dict[str, list[dict]] = {}
        for agent in registry.load():
            # Only the assistant that declares automations is told the setting; the others' interface stays as it was.
            recent, full = (agent.notify_conversations(LIMIT, self.automations()) if getattr(agent, "automations", False)
                            else agent.notify_conversations(LIMIT))
            rows += recent
            if full:
                full_by_app[agent.id] = full
        return rows + self._followed(rows, full_by_app)

    def _followed(self, rows: list[dict], full_by_app: dict[str, list[dict]]) -> list[dict]:
        """What the newest LIMIT leave out but is still under way."""
        from agents import registry
        shown = {(row["app"], row["id"]) for row in rows}
        active = {*self.running, *self.waiting}
        off = str(getattr(self._automation_agent(), "automation_off", "") or "")
        if off and self.automations() == off:
            # 11-24: with 定时任务 off an automation is not even followed, and nothing of it reaches the relay.
            for conv in list(active):
                if ((self.running.get(conv) or self.waiting.get(conv) or {}).get("item") or {}).get("automation"):
                    self.running.pop(conv, None)
                    self.waiting.pop(conv, None)
                    self.reported_running.discard(conv)
            active = {*self.running, *self.waiting}
        more: list[dict] = []
        for app_id, catalog in full_by_app.items():
            for row in catalog:
                conv = (app_id, row["id"])
                if conv not in shown and (row.get("_running") or row.get("status") == "waiting" or conv in active):
                    more.append(row)
        known = shown | {(row["app"], row["id"]) for row in more}
        for conv in active - known:
            item = (self.running.get(conv) or self.waiting.get(conv) or {}).get("item")
            try:
                uses_file = registry.get(conv[0]).notify_uses_file
            except Exception:
                uses_file = False
            if item and uses_file and chats.conv_path(item) is not None:
                more.append(item)
            else:
                self.running.pop(conv, None)
                self.waiting.pop(conv, None)
                self.reported_running.discard(conv)
        return more

    def _deepseek(self, found, item):
        """Backwards-compatible entry point used by tests; delegates to DeepSeekAgent.notify_poll."""
        import agents.deepseek
        agents.deepseek.AGENT().notify_poll(self, found, item)

    def _quiet(self, item: dict) -> str:
        """Why this turn's end is not sent, or ''."""
        with self.lock:
            if self.open.get((item["app"], item["id"])):
                return "手机正开着这个对话"
        return ""

    def _tell(self, found: dict | None, item: dict, end: dict) -> None:
        from agents import registry
        agent = None
        try:
            agent = registry.get(item["app"])
            app = agent.manifest()["name"]["zh"]
        except Exception:
            app = item["app"]
        automation = bool(item.get("automation")) or bool(end.get("automation"))
        heartbeat = bool(end.get("heartbeat"))
        label = str(getattr(self._automation_agent(), "automation_label", "") or "") if automation else app
        label = label or app
        done = "出错停了" if end["state"] == "failed" else "在等你选" if end.get("asks") else "好了"
        title = chats.one_line(item.get("title") or "（无标题）", 40)
        what = f"{label}「{title}」{done}"
        why = self._quiet(item)
        preview = _preview(end.get("text") or "")
        subtitle, outcomes = f"{self.name} · {label} {done}", []
        decision = {"send": True, "why": "", "text": ""}
        hook = getattr(agent, "notify_decision", None)  # 11-24: the assistant's own rule for a phone notice
        if hook is not None:
            decision = hook(end.get("raw_text") or end.get("text") or "", heartbeat, automation,
                            end["state"] == "failed", self.automations(), end.get("automation_id") or "")
            if not decision["send"] and not why:
                why = decision["why"]
        conv = (item["app"], item["id"])
        if end.get("asks"):
            self.waiting[conv] = {"since": int(end.get("started") or self.clock()), "title": title, "item": item}
        if self.relay_on():  # what happened, not what was said: the relay writes the words (relay_push.py)
            kind = "failed" if end["state"] == "failed" else "waiting" if end.get("asks") else "done"
            event = {"kind": kind, "app": item["app"], "chat": item["id"],
                     "quiet": bool(why), "title": title,
                     # 11-27: the phone and its island count this turn up from these against their own now.
                     "started": pc_clock.to_true_seconds(int(end.get("started") or 0)),
                     "ended": pc_clock.to_true_seconds(int(end.get("ended") or self.clock())),
                     "started_source": end.get("started_source") or "不知道"}
            event.update(agent_push_fields(item["app"]))
            if automation:
                event["automation"] = True  # today's relay ignores it; the iPhone's words stay as they were
            # quiet: the phone has this conversation open (or Codex asked for none) — but its island still needs the state.
            self.relay.publish("", "", extra=event, keep=True)
            outcomes.append("遥应通知已交给中转" if self.relay.listening else "中转现在没连着，连上后会补报")
        if why:
            self._note(what, "没推：" + why + ("；只更新岛" if self.relay_on() else ""))
            return
        if self.ntfy_on():  # kept for a phone that is away, which gets it when it connects again (ntfy_feed.py)
            chosen = decision["text"] or (inbox_summary(end.get("raw_text") or "") if automation else "")
            shown = _preview(chosen) if chosen else _preview(_without_markers(end.get("text") or ""))
            message = f"{label} · {self.name} · {notice_state(end)}" + (f"\n{shown}" if shown else "")
            self.feed.publish(notice_title(item.get("title") or "", label, self.name), message,
                              click=self.page_url(item),
                              priority=4 if (end.get("asks") or end["state"] == "failed") else 3,
                              icon=self.icon_url(), sequence_id=sequence_id(item["app"], item["id"]))
            outcomes.append("ntfy 已推到" if self.feed.listening else "ntfy 现在没连着，连上后会收到")
        if found:  # Bark keeps its own words; only an automation's name in the subtitle is new
            outcomes.append(self._bark(found, title, preview, subtitle, item))
        if outcomes:  # none when both were turned off a moment ago
            self._note(what, "；".join(outcomes))

    def _bark(self, found: dict, title: str, body: str, subtitle: str, item: dict) -> str:
        for attempt in (1, 2):
            try:
                self.sender(found, title, body, subtitle=subtitle, group=self.name, url=self.page_url(item))
                return "已推到手机"
            except NotifyError as exc:
                if attempt == 2:
                    return f"没推出去：{exc}"
                self.stopped.wait(3)
        return ""

    def _note(self, what: str, outcome: str) -> None:
        self.recent.append({"time": time.strftime("%H:%M"), "text": f"{what} · {outcome}"})
        self.log(f"通知：{what}，{outcome}")
