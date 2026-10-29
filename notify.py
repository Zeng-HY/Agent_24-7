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

Every 10 s the newest conversations are looked at, and a file that grew is read from its end. A turn that ended there
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
import json
import re
import sqlite3
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import quote, urlsplit

import chats
import machines
import ntfy_feed

POLL_SECONDS = 5   # between looks while nothing runs (user 10-28: pushes felt slow at 10 s)
POLL_FAST = 2      # between looks while any turn is running
HISTORY_BYTES = 64 << 20  # the first look reads back this far for the last start and end (0.6.4)
SNAPSHOT_EVERY = 60       # a running conversation's record reaches the relay this often (0.6.4)
STEP_GAP = 15             # seconds between two progress events of one conversation (0.6.4)
LIMIT = 30              # conversations of each app looked at, newest first
DEFAULT_SERVER = "https://api.day.app"
# The Codex threads a person talks in: the desktop's and the command line's, started by the user, by this service's
# new-conversation button (no thread_source) or by another conversation. Not: codex exec runs (the translation
# workflows start thousands), sub-agents, reviews, automations.
CODEX_WHERE = "source in ('vscode', 'cli') and coalesce(thread_source, '') in ('', 'user', 'agent_created_thread')"


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
    return _codex_end(lines) if app == "codex" else _claude_end(lines)


def _codex_end(lines: list[bytes]) -> dict | None:
    states = {"task_started": "running", "task_complete": "done", "turn_aborted": "stopped"}
    end = None
    for raw in lines:
        if b"event_msg" not in raw[:160]:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        payload = rec.get("payload") or {}
        state = states.get(payload.get("type"))
        if state:
            ts = rec.get("timestamp") or ""
            end = {"state": state, "key": payload.get("turn_id") or ts, "time": ts,
                   "text": chats.codex_answer(payload.get("last_agent_message") or "")}
    return end


def _claude_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _claude_end(lines: list[bytes]) -> dict | None:
    # Read as chats.parse_claude reads it. One answer comes as several records (thinking, then text) with one message
    # id; an answer that stops to use a tool, or a tool's result, means the turn goes on.
    end = None
    asks = {}  # next-step boxes with a question, by their call: the turn ends at their result (10-16)
    for raw in lines:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        kind = rec.get("type")
        if kind not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        ts = rec.get("timestamp") or ""
        message = rec.get("message") or {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        if kind == "user":
            box = next((asks[b["tool_use_id"]] for b in content if isinstance(b, dict) and b.get("type") == "tool_result"
                        and b.get("tool_use_id") in asks), None)
            if box:  # Claude waits on the user; read as still running before 10-16, so such a turn was never told
                end = {"state": "done", "key": box["tool_id"], "time": ts, "text": box["ask"], "asks": True}
                continue
            stopped = _claude_text(message.get("content")).lstrip().startswith("[Request interrupted")
            end = {"state": "stopped" if stopped else "running", "key": rec.get("uuid") or ts, "time": ts, "text": ""}
            continue
        for block in content:
            box = chats._claude_next(block) if isinstance(block, dict) and block.get("type") == "tool_use" else None
            if box and box["ask"]:
                asks[block.get("id")] = box
        key = message.get("id") or rec.get("uuid") or ts
        if message.get("stop_reason") in (None, "tool_use"):
            end = {"state": "running", "key": key, "time": ts, "text": ""}
            continue
        text = _claude_text(message.get("content")).strip()
        if end and end["key"] == key and end["state"] in ("done", "failed"):
            end["text"] = (end["text"] + "\n" + text).strip()
        else:  # an API error comes as an answer of its own, marked so
            end = {"state": "failed" if rec.get("isApiErrorMessage") else "done", "key": key, "time": ts, "text": text}
    return end


_CJK = "　-〿一-鿿＀-￯"


def _preview(text: str) -> str:
    """The start of an answer on one line, without Markdown marks or the spaces they leave inside Chinese."""
    line = chats.one_line(chats.plain(text or ""), 150)
    return re.sub(f"(?<=[{_CJK}]) (?=[{_CJK}])", "", line)


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
    name = (name or "").strip()
    if app == "claude":
        return CLAUDE_STEPS.get(name)
    if app == "deepseek":
        return DEEPSEEK_STEPS.get(name.rsplit(".", 1)[-1])
    if app != "codex":
        return None
    action = CODEX_STEPS.get(name)
    if name == "exec":  # Codex's one command tool; a patch or a web search runs through it
        text = (argument or "").lower()
        if "apply_patch" in text or "*** begin patch" in text:
            return "edit"
        if "web_search" in text or "search_query" in text or "web.run" in text:
            return "search"
        return "run"
    return action


def new_scan(app: str) -> dict:
    """What one conversation's turn looks like while its record is read a piece at a time (0.6.4)."""
    return {"app": app, "state": None, "started": "", "ended": "", "latest": "", "key": "", "text": "", "action": "",
            "asks": set(), "answer_id": "", "last_kind": None, "last_stop": None}


def scan_lines(scan: dict, lines: list[bytes]) -> dict:
    """Read record lines into [scan]; the state after them is the newest turn's, with the record's own times."""
    for raw in lines:
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if scan["app"] == "codex":
            _scan_codex(scan, rec)
        else:
            _scan_claude(scan, rec)
    return scan


def _scan_codex(scan: dict, rec: dict) -> None:
    kind = rec.get("type")
    payload = rec.get("payload") or {}
    ts = rec.get("timestamp") or ""
    if ts:
        scan["latest"] = ts
    event = payload.get("type") if kind == "event_msg" else None
    if event == "task_started":
        scan.update(state="running", started=ts, ended="", key=payload.get("turn_id") or ts, text="", action="")
    elif event in ("task_complete", "turn_aborted"):
        scan.update(state="stopped" if event == "turn_aborted" else "done", ended=ts,
                    key=payload.get("turn_id") or scan["key"] or ts,
                    text=chats.codex_answer(payload.get("last_agent_message") or "") if event == "task_complete"
                    else scan["text"], action="")
    elif kind == "response_item":
        ptype = payload.get("type")
        if ptype in ("function_call", "custom_tool_call"):
            step = record_step("codex", str(payload.get("name") or ""), str(payload.get("input") or ""))
            if step:
                scan["action"] = step
        elif ptype == "item_completed" and (payload.get("item") or {}).get("type") == "CommandExecution":
            scan["action"] = "run"


def _scan_claude(scan: dict, rec: dict) -> None:
    kind = rec.get("type")
    if kind not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
        return
    ts = rec.get("timestamp") or ""
    if ts:
        scan["latest"] = ts
    message = rec.get("message") or {}
    content = message.get("content")
    blocks = content if isinstance(content, list) else []
    if kind == "user":
        tool_results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
        if tool_results:
            asked = any(b.get("tool_use_id") in scan["asks"] for b in tool_results)
            if asked and scan["state"] == "running":
                scan.update(state="done", ended=ts, action="")
            return
        text = _claude_text(content).strip()
        if not text:
            return
        if text.startswith("[Request interrupted"):
            scan.update(state="stopped", ended=ts, action="")
            return
        scan.update(state="running", started=ts, ended="", key=rec.get("uuid") or ts, text="", action="")
        return
    # assistant: an answer may be written as several records under one message id (thinking, then text)
    key = message.get("id") or rec.get("uuid") or ts
    if key != scan.get("answer_id"):
        scan["answer_id"], scan["text"] = key, ""
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            box = chats._claude_next(block)
            if box and box.get("ask"):
                scan["asks"].add(block.get("id"))
            step = record_step("claude", str(block.get("name") or ""))
            if step and scan["state"] == "running":
                scan["action"] = step
        elif block.get("type") == "text" and (block.get("text") or "").strip():
            scan["text"] = (scan.get("text", "") + "\n" + block["text"].strip()).strip()
    if rec.get("isApiErrorMessage"):
        scan.update(state="failed", ended=ts, key=key, action="")
        return
    stop = message.get("stop_reason")
    if stop in (None, "tool_use"):
        if scan["state"] is None:
            scan["state"] = "running"
        return
    scan.update(state="done", ended=ts, key=key, action="")
    scan["last_kind"] = "assistant"


# ---------------------------------------------------------------- the watcher


class Notifier:
    def __init__(self, cfg: dict, name: str, log, save, clock=time.time, sender=send, page_url=None, feed=None) -> None:
        self.cfg, self.name, self.log, self.save = cfg, name, log, save
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
        self.relay_was_on = False
        self.relay_was_listening = False
        self.running_quiet = True                    # kept for older callers; running is now always reported (0.6.4)
        self.open: collections.Counter = collections.Counter()  # (app, id) -> live streams the phone has on it
        self.recent: collections.deque = collections.deque(maxlen=8)  # the last outcomes, for the page
        self.url = ""                                # this computer's https address on Tailscale
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
                "relay": {"listening": self.relay.listening > 0}, "recent": list(self.recent)[::-1]}

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
        self.feed.publish(f"{self.name}的通知设好了", "对话做完时会推到这里，点通知能打开那个对话。", click=self.page_url())
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
            self.feed.publish(f"{self.name}的通知是好的", "这是一条试推。", click=self.page_url())
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
        self.relay_was_listening = listening
        self.relay_was_on = on
        if found is None and not self.ntfy_on() and not on:
            self.since = None  # nothing to send to; once Bark, ntfy or the relay is on, only later turns count
            return
        if self.since is None:
            self._count_from_now()
        for item in self._conversations():
            if item['app'] == 'deepseek':
                self._deepseek(found, item)
                continue
            scan = self._scan_file(item)
            if scan is None or scan.get("state") is None:
                continue
            conv = (item["app"], item["id"])
            title = chats.one_line(item.get("title") or "", 60)
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
            self.reported_running.discard(conv)
            key = scan.get("key") or scan.get("ended") or ""
            if self.ended.get(conv) == key:
                continue
            self.ended[conv] = key
            ended = _unix(scan.get("ended"))
            if scan["state"] == "stopped" or (ended is not None and ended < self.since):
                continue
            answer = scan.get("text") or ""
            started = _unix(scan.get("started")) or previous.get("since") or 0
            source = "记录" if _unix(scan.get("started")) else ("不知道" if not started else "电脑注意到")
            self._tell(found, item, {"state": scan["state"], "key": key, "time": scan.get("ended") or "",
                                     "text": answer, "started": int(started or self.clock()),
                                     "ended": int(ended or self.clock()), "started_source": source})
        self.running_quiet = False
        self._snapshot()

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
                              "title": chats.one_line(item.get("title") or "", 60)}
        if not self.relay_on() or conv in self.reported_running:
            return
        try:
            self.relay.publish("", "", extra={"kind": "running", "app": item["app"], "chat": item["id"],
                                              "since": int(since), "started": int(since), "started_source": source,
                                              "title": chats.one_line(item.get("title") or "", 60)},
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
                                              "since": int(self.running.get(conv, {}).get("since") or self.clock()),
                                              "title": chats.one_line(item.get("title") or "", 60)}, keep=False)
        except Exception:
            self.log("通知：进度没报给中转\n" + traceback.format_exc())

    def _snapshot(self) -> None:
        """Every 60 s (and once when the relay connects): all running and waiting conversations on this computer, so a
        relay that restarted can rebuild them. Not kept for a reconnect (0.6.4)."""
        if not self.relay_on() or self.clock() - self.last_snapshot < SNAPSHOT_EVERY:
            return
        items = []
        for conv, info in self.running.items():
            items.append({"app": conv[0], "chat": conv[1], "state": "working", "started": int(info["since"]),
                          "since": int(info["since"]), "title": info.get("title", ""),
                          "step": (self.steps.get(conv) or ("", ""))[0]})
        for conv, info in self.waiting.items():
            items.append({"app": conv[0], "chat": conv[1], "state": "waiting", "started": int(info["since"]),
                          "since": int(info["since"]), "title": info.get("title", ""),
                          "step": (self.steps.get(conv) or ("", ""))[0]})
        try:
            self.relay.publish("", "", extra={"kind": "snapshot", "items": items}, keep=False)
            self.last_snapshot = self.clock()
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
        try:
            codex = chats._codex_rows(CODEX_WHERE, (), LIMIT)
        except sqlite3.Error:  # a Codex whose database lacks these columns
            try:
                codex = chats.codex_threads(LIMIT)
            except sqlite3.Error:
                codex = []
        import deepseek_control
        return codex + chats.claude_sessions(LIMIT) + deepseek_control.catalog()[:LIMIT]

    def _deepseek(self,found,item):
        """DeepSeek's Harness keeps turn/start and turn/end events with their own times; read them, not the clock."""
        import deepseek_control
        if item.get('status') == 'unknown':
            return
        bridge = deepseek_control.bridge()
        conv = ('deepseek', item['id'])
        initial = conv not in self.ended
        if initial:
            self.ended[conv] = 'observed'
        now = int(getattr(self, "clock", time.time)())
        events = []
        try:
            page, _ = bridge.records(item['id'], limit=100)
            events = [v.get('event') for v in page.get('records', []) if v.get('event')]
        except deepseek_control.DeepSeekError:
            pass
        starts = [e.get('time', 0) / 1000 for e in events if e.get('type') == 'turn/start' and e.get('time')]
        starts = [int(v) for v in starts if v > 0]
        ends = [e for e in events if e.get('type') == 'turn/end']
        action = ""
        for event in reversed(events):
            if event.get('type') == 'tool/call':
                name = (event.get('data') or {}).get('name') or ""
                action = record_step("deepseek", str(name)) or action
                if action:
                    break
        interactions = bridge.events.for_session(item['id'])
        questions = (item.get('_values', {}).get('userQuestions') or {}).get('active', [])
        waiting = getattr(self, "waiting", None)
        if interactions or questions:
            self.running.pop(conv, None)
            ids = [v['eventId'] for v in interactions] + [q['callId'] for q in questions]
            key = 'pending:' + ','.join(sorted(ids))
            text = 'DeepSeek 有待处理的提问或批准，请打开对话查看。'
            asks = True
            started = starts[-1] if starts else int(self.running.get(conv, {}).get('since') or now)
            if waiting is not None:
                waiting[conv] = {"since": started, "title": chats.one_line(item.get('title') or "", 60)}
            end = dict(key=key, state='done', text=text, asks=asks, started=started, ended=now,
                       started_source='记录' if starts else '不知道')
        elif item.get('_running'):
            if waiting is not None:
                waiting.pop(conv, None)
            started = starts[-1] if starts else None
            self._running(item, {"started": datetime.fromtimestamp(started).isoformat() if started else "",
                                 "key": str(starts[-1]) if starts else "", "action": action})
            if action and hasattr(self, "_step"):
                self._step(item, {"action": action}, self.relay_on())
            return
        else:
            self.running.pop(conv, None)
            if waiting is not None:
                waiting.pop(conv, None)
            if not ends:
                return
            end_event = ends[-1]
            ended = int(end_event.get('time', 0) / 1000) if end_event.get('time') else now
            if ended < self.since or (end_event.get('data', {}).get('reason', {}).get('kind') != 'completed'):
                return
            key = str(end_event.get('seq'))
            text = item.get('preview', '')
            asks = False
            started = starts[-1] if starts else int(self.running.get(conv, {}).get('since') or 0)
            end = dict(key=key, state='done', text=text, asks=asks, started=started or ended, ended=ended,
                       started_source='记录' if starts else ('电脑注意到' if started else '不知道'))
        old = self.ended.get(conv)
        self.ended[conv] = end['key']
        if old == end['key']:
            return
        if asks and initial:
            return  # establish pending baseline; no replay of pre-start questions
        if asks and waiting is not None:
            waiting[conv] = {"since": end['started'], "title": chats.one_line(item.get('title') or "", 60)}
        self._tell(found, item, end)

    def _quiet(self, item: dict) -> str:
        """Why this turn's end is not sent, or ''."""
        with self.lock:
            if self.open.get((item["app"], item["id"])):
                return "手机正开着这个对话"
        return ""

    def _tell(self, found: dict | None, item: dict, end: dict) -> None:
        app = {'codex':'Codex','claude':'Claude','deepseek':'DeepSeek'}[item['app']]
        done = "出错停了" if end["state"] == "failed" else "在等你选" if end.get("asks") else "好了"
        title = chats.one_line(item.get("title") or "（无标题）", 40)
        what = f"{app}「{title}」{done}"
        why = self._quiet(item)
        body, subtitle, outcomes = _preview(end["text"]), f"{self.name} · {app} {done}", []
        conv = (item["app"], item["id"])
        if end.get("asks"):
            self.waiting[conv] = {"since": int(end.get("started") or self.clock()), "title": title}
        if self.relay_on():  # what happened, not what was said: the relay writes the words (relay_push.py)
            kind = "failed" if end["state"] == "failed" else "waiting" if end.get("asks") else "done"
            # quiet: the phone has this conversation open, so no banner — but its island still needs the state.
            self.relay.publish("", "", extra={"kind": kind, "app": item["app"], "chat": item["id"],
                                              "quiet": bool(why), "title": title,
                                              "started": int(end.get("started") or 0),
                                              "ended": int(end.get("ended") or self.clock()),
                                              "started_source": end.get("started_source") or "不知道"},
                               keep=True)
            outcomes.append("遥应通知已交给中转" if self.relay.listening else "中转现在没连着，连上后会补报")
        if why:
            self._note(what, "没推：" + why + ("；只更新岛" if self.relay_on() else ""))
            return
        if self.ntfy_on():  # kept for a phone that is away, which gets it when it connects again (ntfy_feed.py)
            self.feed.publish(title, f"{subtitle}\n{body}", click=self.page_url(item))
            outcomes.append("ntfy 已推到" if self.feed.listening else "ntfy 现在没连着，连上后会收到")
        if found:
            outcomes.append(self._bark(found, title, body, subtitle, item))
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
