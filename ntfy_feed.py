"""Done-notifications for the ntfy app on an Android phone, served by this service itself (10-20).

ntfy (https://ntfy.sh) is an open-source notification service. Its Android app subscribes to a topic on a server and
keeps a connection to it open, so a notification shows as soon as the server has one. Bark, which the iPhone uses, has
no Android app. Here this service answers the few requests the app makes, the way an ntfy server would, for one topic
(TOPIC): nothing more is installed on the computer and nothing goes through anyone else's server. In the app the
phone subscribes to TOPIC on this computer's Tailscale address (the page's own); its requests come through
tailscale serve with the phone's Tailscale account on them and are let in as the page is (remote.py _authorized).
So the phone gets them only while its Tailscale is connected.

What the app asks, as read in ntfy-android's source (1.25, 10-20):
- GET /<topic>/auth when the subscription is added: 2xx lets it in (401/403 make it ask for a login).
- GET /<topic>/json?since=<id | none | all>: a stream of JSON objects, one per line: "open" first, then the messages
  after `since`, then each new one, and a "keepalive" every KEEPALIVE seconds (the app drops a connection silent for
  77 s and comes back with since=<the last id it has>). Never an empty line: the app reads every line as JSON and
  takes one that is not for a broken connection.
- GET /<topic>/json?poll=1&since=...: the messages after `since`, and the answer ends.
- GET /<topic>/ws?since=...: the same objects as WebSocket text frames, once the app is switched to WebSockets (its
  main screen suggests that). It pings every 3 minutes and wants a pong back.
Several topics come comma-separated in one request; only TOPIC is answered.
A message is {"id", "time", "event": "message", "topic", "title", "message", "priority", "click"}; tapping the
notification opens `click`, the conversation's link on the page. Messages stay in memory for KEEP_SECONDS (at most
KEEP_COUNT), for a phone that was away to get when it connects again; a restart of the service forgets them.
"""

from __future__ import annotations

import base64
import collections
import contextlib
import hashlib
import json
import re
import secrets
import select
import socket
import string
import struct
import threading
import time

TOPIC = "agent-remote"
KEEPALIVE = 45            # seconds between keepalives; the app gives up on a connection silent for 77 s
KEEP_SECONDS = 12 * 3600  # how long a message waits for a phone that is away
KEEP_COUNT = 100
PATH = re.compile(r"/([-_A-Za-z0-9]{1,64}(?:,[-_A-Za-z0-9]{1,64})*)/(json|ws|auth)")  # topics, what is asked
NDJSON = "application/x-ndjson; charset=utf-8"
_ID = string.ascii_letters + string.digits
_DURATION = re.compile(r"(\d+)([smhd])")
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455: what the handshake's key is hashed with


class Feed:
    """TOPIC's messages, and how many phones listen to it now."""

    def __init__(self, topic: str = TOPIC, clock=time.time) -> None:
        self.topic, self.clock = topic, clock
        self.messages: collections.deque = collections.deque(maxlen=KEEP_COUNT)  # (number, message), oldest first
        self.fresh: collections.deque = collections.deque(maxlen=KEEP_COUNT)     # not kept for a reconnect (0.6.4)
        self.count = 0          # messages published since the service started; a message's number
        self.listening = 0      # connections open now (a stream or a WebSocket)
        self.last_seen = 0.0    # when a phone last connected, asked or went away
        self.changed = threading.Condition()

    def publish(self, title: str, message: str, click: str = "", priority: int = 3, extra: dict | None = None,
                keep: bool = True) -> dict:
        """A message; [extra] fields ride along (notify.py's events for the relay: kind, app, chat). [keep] False:
        a stream open now sees it, but a later reconnect is not given it (snapshot and step, 0.6.4)."""
        msg = {"id": _new_id(), "time": int(self.clock()), "event": "message", "topic": self.topic,
               "title": title, "message": message, "priority": priority, **(extra or {})}
        if click:
            msg["click"] = click
        with self.changed:
            self.count += 1
            (self.messages if keep else self.fresh).append((self.count, msg))
            self.changed.notify_all()
        return msg

    def event(self, kind: str) -> dict:
        """An "open" or "keepalive": the app reads it and shows nothing."""
        return {"id": _new_id(), "time": int(self.clock()), "event": kind, "topic": self.topic}

    def since(self, value: str) -> list[dict]:
        """The kept messages after `since` as the app gives it: a message id (all kept ones when the id is not kept
        any more, e.g. after a restart), none, all, latest, a Unix time, or a span like 10m."""
        with self.changed:
            kept = [m for _, m in self.messages if m["time"] >= self.clock() - KEEP_SECONDS]
        value = (value or "none").strip()
        if value == "none":
            return []
        if value == "all":
            return kept
        if value == "latest":
            return kept[-1:]
        span = _DURATION.fullmatch(value)
        if value.isdigit() or span:
            start = int(value) if value.isdigit() else self.clock() - int(span[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[span[2]]
            return [m for m in kept if m["time"] >= start]
        ids = [m["id"] for m in kept]
        return kept[ids.index(value) + 1:] if value in ids else kept

    def start(self, since: str) -> tuple[int, list[dict]]:
        """Where a new connection starts: the number of the newest message, and the kept ones it is owed."""
        with self.changed:
            return self.count, self.since(since)

    def wait(self, seen: int, timeout: float) -> tuple[list[dict], int]:
        """The messages after number `seen`, waiting up to `timeout` seconds for one; and the newest number. Includes
        the not-kept ones published meanwhile, so a stream open now still receives snapshots and progress."""
        with self.changed:
            if self.count == seen:
                self.changed.wait(timeout)
            rows = sorted([(n, m) for n, m in (*self.messages, *self.fresh) if n > seen], key=lambda v: v[0])
            return [m for _, m in rows], self.count

    @contextlib.contextmanager
    def listener(self):
        with self.changed:
            self.listening += 1
            self.last_seen = self.clock()
        try:
            yield
        finally:
            with self.changed:
                self.listening -= 1
                self.last_seen = self.clock()


def serve(handler, feed: Feed, topics: str, kind: str, query: dict) -> None:
    """Answer one of the app's requests (PATH: topics, kind) on remote.py's handler."""
    if feed.topic not in topics.split(","):
        handler._json({"code": 40401, "http": 404, "error": f"这台电脑只有 {feed.topic} 这个主题"}, 404)
        return
    since = query.get("since", "none")
    if kind == "auth":
        handler._json({"success": True})
    elif kind == "ws":
        _websocket(handler, feed, since)
    elif query.get("poll") in ("1", "true", "yes"):
        feed.last_seen = feed.clock()
        handler._send(200, b"".join(_line(m) for m in feed.since(since)), NDJSON)
    else:
        _stream(handler, feed, since)


def relay_stream(handler, feed: Feed, since: str) -> None:
    """GET /api/notify/push: the relay's stream of events for 遥应's own notifications (notify.py, relay_push.py),
    the same lines as the ntfy app's: "open", the kept events after `since`, then each new one, keepalives between."""
    _stream(handler, feed, since)


def _stream(handler, feed: Feed, since: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", NDJSON)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    handler.close_connection = True  # no length: the stream ends with the connection
    conn = handler.connection
    conn.settimeout(30)  # a phone that stops reading does not hold a write for ever

    def write(obj: dict) -> None:
        handler.wfile.write(_line(obj))
        handler.wfile.flush()

    with feed.listener():
        try:
            seen, owed = feed.start(since)
            for obj in [feed.event("open"), *owed]:
                write(obj)
            last = time.monotonic()
            while not _gone(conn):
                fresh, seen = feed.wait(seen, 1.0)
                for msg in fresh:
                    write(msg)
                    last = time.monotonic()
                if time.monotonic() - last >= KEEPALIVE:
                    write(feed.event("keepalive"))
                    last = time.monotonic()
        except (OSError, ValueError):  # the phone went away while something was written
            pass


def _websocket(handler, feed: Feed, since: str) -> None:
    key = handler.headers.get("Sec-WebSocket-Key") or ""
    if (handler.headers.get("Upgrade") or "").lower() != "websocket" or not key:
        handler._json({"code": 40001, "http": 400, "error": "这里只接 WebSocket"}, 400)
        return
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept_key(key))
    handler.end_headers()
    handler.close_connection = True
    conn = handler.connection
    conn.settimeout(30)

    def write(obj: dict) -> None:
        conn.sendall(frame(0x1, _line(obj).rstrip(b"\n")))

    with feed.listener():
        try:
            seen, owed = feed.start(since)
            for obj in [feed.event("open"), *owed]:
                write(obj)
            last = time.monotonic()
            while True:
                # what the phone sends: pings (answered), a close (answered, and the end); a client sends nothing
                # before the handshake's answer (RFC 6455 4.1), so no frame waits in the handler's read buffer
                while select.select([conn], [], [], 0)[0]:
                    got = read_frame(conn)
                    if got is None:
                        return
                    opcode, payload = got
                    if opcode == 0x8:
                        conn.sendall(frame(0x8, payload[:2]))
                        return
                    if opcode == 0x9:
                        conn.sendall(frame(0xA, payload))
                fresh, seen = feed.wait(seen, 1.0)
                for msg in fresh:
                    write(msg)
                    last = time.monotonic()
                if time.monotonic() - last >= KEEPALIVE:
                    write(feed.event("keepalive"))
                    last = time.monotonic()
        except (OSError, ValueError):
            pass


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key.strip() + _WS_GUID).encode("ascii")).digest()).decode("ascii")


def frame(opcode: int, payload: bytes) -> bytes:
    """One WebSocket frame from the server: final, not masked."""
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x80 | opcode, n)
    elif n < 1 << 16:
        head = struct.pack("!BBH", 0x80 | opcode, 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 127, n)
    return head + payload


def read_frame(conn) -> tuple[int, bytes] | None:
    """One frame from the phone (masked, as a client's are): (opcode, payload); None when the connection closed."""
    head = _exact(conn, 2)
    if head is None:
        return None
    opcode, n = head[0] & 0x0F, head[1] & 0x7F
    if n == 126:
        n = struct.unpack("!H", _exact(conn, 2) or b"\0\0")[0]
    elif n == 127:
        n = struct.unpack("!Q", _exact(conn, 8) or bytes(8))[0]
    if n > 1 << 16:
        raise ValueError("a frame this large is not one the app sends")
    mask = (_exact(conn, 4) or bytes(4)) if head[1] & 0x80 else bytes(4)
    data = _exact(conn, n) if n else b""
    if data is None:
        return None
    return opcode, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def _exact(conn, n: int) -> bytes | None:
    data = b""
    while len(data) < n:
        part = conn.recv(n - len(data))
        if not part:
            return None
        data += part
    return data


def _gone(conn) -> bool:
    """True once the phone closed the connection (nothing more is read from a stream's connection)."""
    try:
        return bool(select.select([conn], [], [], 0)[0]) and not conn.recv(1, socket.MSG_PEEK)
    except OSError:
        return True


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _new_id() -> str:
    return "".join(secrets.choice(_ID) for _ in range(12))
