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
TAIL_BYTES = 256 << 10  # how much of a grown file is read; a turn's end is the last thing written
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
        self.ended: dict[tuple, str] = {}            # (app, id) -> key of its newest turn end seen, sent or not
        # (app, id) -> when this turn was first seen running; a turn that starts is told to the relay once
        self.running: dict[tuple, float] = {}
        self.running_quiet = True                    # the first look after starting records, never sends
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
        if found is None and not self.ntfy_on() and not self.relay_on():
            self.since = None  # nothing to send to; once Bark, ntfy or the relay is on, only later turns count
            return
        if self.since is None:
            self._count_from_now()
        for item in self._conversations():
            if item['app']=='deepseek':
                self._deepseek(found,item)
                continue
            path = chats.conv_path(item)
            if path is None:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            if self.sizes.get(str(path)) == (st.st_size, st.st_mtime_ns):
                continue
            self.sizes[str(path)] = (st.st_size, st.st_mtime_ns)
            lines, _ = chats.read_tail(path, TAIL_BYTES)
            end = turn_end(item["app"], lines)
            conv = (item["app"], item["id"])
            if end is None:
                continue
            if end["state"] == "running":
                self._running(item)
                continue
            self.running.pop(conv, None)
            if self.ended.get(conv) == end["key"]:
                continue
            self.ended[conv] = end["key"]
            if end["state"] == "stopped" or _seconds(end["time"], st.st_mtime) < self.since:
                continue
            self._tell(found, item, end)
        self.running_quiet = False  # from here a turn seen running is a new one, told to the relay

    def _running(self, item: dict) -> None:
        """A turn began: said to the relay once, so a conversation running for a minute can get an island (方案一).
        Only the app, the conversation and when it began; never the words. Quiet for turns already running when the
        watch starts (10-27's rule: nothing is replayed for the past)."""
        conv = (item["app"], item["id"])
        if conv in self.running:
            return
        start = self.clock()
        self.running[conv] = start
        if self.running_quiet or not self.relay_on():
            return
        try:
            self.relay.publish("", "", extra={"kind": "running", "app": item["app"], "chat": item["id"],
                                              "since": int(start), "title": chats.one_line(item.get("title") or "", 60)})
        except Exception:
            self.log("通知：在干活没报给中转\n" + traceback.format_exc())

    def asking(self, item: dict, text: str) -> None:
        """Claude waits on a question or a permission in the middle of a turn, as Claude Code's hook tells it
        (claude_hooks.py): sent as a turn that ends with a question is. The record reads as running then, so such a
        wait was never sent before 10-27."""
        found = self.address()
        if found is None and not self.ntfy_on() and not self.relay_on():
            return
        try:
            self._tell(found, item, {"state": "done", "key": "", "time": "", "text": text, "asks": True})
        except Exception:
            self.log("通知：Claude 在等回答，没推出去\n" + traceback.format_exc())

    def _count_from_now(self) -> None:
        self.since = self.clock()
        self.sizes.clear()
        self.ended.clear()

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
        import deepseek_control
        if item.get('status')=='unknown':return
        bridge=deepseek_control.bridge()
        conv=('deepseek',item['id']);initial=conv not in self.ended
        if initial:self.ended[conv]='observed'
        interactions=bridge.events.for_session(item['id'])
        questions=(item.get('_values',{}).get('userQuestions') or {}).get('active',[])
        if interactions or questions:
            self.running.pop(conv, None)
            ids=[v['eventId'] for v in interactions]+[q['callId'] for q in questions]
            key='pending:'+','.join(sorted(ids));text='DeepSeek 有待处理的提问或批准，请打开对话查看。';asks=True
        elif item.get('_running'):
            self._running(item)
            return
        else:
            self.running.pop(conv, None)
            try:page,_=bridge.records(item['id'],limit=5)
            except deepseek_control.DeepSeekError:return
            ends=[v['event'] for v in page['records'] if v.get('event',{}).get('type')=='turn/end']
            if not ends:return
            end=ends[-1]
            if end.get('time',0)/1000<self.since or end.get('data',{}).get('reason',{}).get('kind')!='completed':return
            key=str(end['seq']);text=item.get('preview','');asks=False
        old=self.ended.get(conv)
        self.ended[conv]=key
        if old==key:return
        if asks and initial:return  # establish pending baseline; no replay of pre-start questions
        self._tell(found,item,dict(key=key,state='done',text=text,asks=asks))

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
        if self.relay_on():  # what happened, not what was said: the relay writes the words (relay_push.py)
            kind = "failed" if end["state"] == "failed" else "waiting" if end.get("asks") else "done"
            # quiet: the phone has this conversation open, so no banner — but its island still needs the state.
            self.relay.publish("", "", extra={"kind": kind, "app": item["app"], "chat": item["id"],
                                              "quiet": bool(why), "title": title})
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
