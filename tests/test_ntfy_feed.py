"""The ntfy app's requests, answered by this service (ntfy_feed.py, 10-20). A small server on 127.0.0.1 runs the
same GET as remote.py, and each test asks the way ntfy-android 1.25 does: the auth check when a subscription is added,
the JSON stream it keeps open, a poll, and the WebSocket it uses once switched to WebSockets."""
import base64
import http.client
import json
import os
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ntfy_feed  # noqa: E402
import remote  # noqa: E402


class FeedHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    _send = remote.Handler._send
    _json = remote.Handler._json

    def do_GET(self):
        query = {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}
        if urlsplit(self.path).path == "/api/notify/push":  # as remote.py answers the relay
            ntfy_feed.relay_stream(self, self.server.feed, query.get("since", "none"))
            return
        match = ntfy_feed.PATH.fullmatch("/" + self.path.split("?", 1)[0].lstrip("/"))
        ntfy_feed.serve(self, self.server.feed, match[1], match[2], query)

    def log_message(self, *args):
        pass


def until(condition, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


class FeedTests(unittest.TestCase):
    def test_since_as_the_app_gives_it(self):
        now = [1_800_000_000.0]
        feed = ntfy_feed.Feed(clock=lambda: now[0])
        old = feed.publish("旧的", "13 小时前")
        now[0] += 13 * 3600
        a, b, c = (feed.publish(t, "正文") for t in ("一", "二", "三"))
        self.assertEqual(feed.since("none"), [])
        self.assertEqual(feed.since(""), [])
        self.assertEqual(feed.since("all"), [a, b, c])  # the one from 13 hours ago is not kept
        self.assertEqual(feed.since("latest"), [c])
        self.assertEqual(feed.since(a["id"]), [b, c])
        self.assertEqual(feed.since(c["id"]), [])
        self.assertEqual(feed.since(old["id"]), [a, b, c])  # an id not kept any more (or from before a restart)
        self.assertEqual(feed.since(str(int(now[0]))), [a, b, c])
        self.assertEqual(feed.since(str(int(now[0]) + 1)), [])
        self.assertEqual(feed.since("10m"), [a, b, c])
        self.assertEqual(set(a), {"id", "time", "event", "topic", "title", "message", "priority"})
        self.assertEqual((a["event"], a["topic"], a["priority"], len(a["id"])), ("message", "agent-remote", 3, 12))
        self.assertEqual(feed.publish("t", "m", click="https://pc/?open=codex:x")["click"], "https://pc/?open=codex:x")

    def test_extra_fields_ride_along_for_the_relay(self):
        msg = ntfy_feed.Feed(topic="teleply-push").publish("", "", extra={"kind": "done", "app": "codex", "chat": "x1"})
        self.assertEqual({k: msg[k] for k in ("topic", "kind", "app", "chat")},
                         {"topic": "teleply-push", "kind": "done", "app": "codex", "chat": "x1"})

    def test_the_websocket_handshake_key(self):  # the example in RFC 6455 1.3
        self.assertEqual(ntfy_feed.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")


class ServedTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FeedHandler)
        self.server.daemon_threads = True
        self.feed = self.server.feed = ntfy_feed.Feed()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", path, headers={"User-Agent": "ntfy/1.25.2"})
        return conn.getresponse()

    def status(self, path):  # the answer read to its end, so closing the connection resets nothing
        answer = self.get(path)
        answer.read()
        return answer.status

    def test_auth_lets_the_subscription_in_and_another_topic_is_not_here(self):
        answer = self.get("/agent-remote/auth")
        self.assertEqual((answer.status, json.loads(answer.read())), (200, {"success": True}))
        self.assertEqual(self.status("/somebody-else/json"), 404)

    def test_a_poll_gets_what_came_after_and_ends(self):
        a, b = self.feed.publish("一", "正文"), self.feed.publish("二", "正文")
        answer = self.get(f"/agent-remote/json?poll=1&since={a['id']}")
        self.assertEqual(answer.getheader("Content-Type"), ntfy_feed.NDJSON)
        self.assertEqual([json.loads(line) for line in answer.read().splitlines()], [b])
        self.assertEqual(self.get("/agent-remote/json?poll=1&since=none").read(), b"")

    def test_the_stream_sends_open_what_is_owed_each_new_one_and_keepalives(self):
        a, b = self.feed.publish("一", "正文"), self.feed.publish("二", "做完了\n第二行")
        with mock.patch.object(ntfy_feed, "KEEPALIVE", 0.5):
            answer = self.get(f"/agent-remote,another/json?since={a['id']}")  # the app's topics on this server, together
            self.assertEqual((answer.status, answer.getheader("Content-Length")), (200, None))
            lines = [json.loads(answer.fp.readline()) for _ in range(2)]
            self.assertEqual([lines[0]["event"], lines[1]], ["open", b])
            self.assertTrue(until(lambda: self.feed.listening == 1))
            c = self.feed.publish("三", "正文", click="https://pc.example.ts.net/?open=claude:c1")
            self.assertEqual(json.loads(answer.fp.readline()), c)
            keepalive = answer.fp.readline()  # the app reads every line as JSON: never an empty one
            self.assertEqual(json.loads(keepalive)["event"], "keepalive")
        answer.close()
        self.assertTrue(until(lambda: self.feed.listening == 0))  # the phone went away
        self.assertGreater(self.feed.last_seen, 0)

    def test_the_relay_reads_the_same_lines_from_where_it_stopped(self):
        a = self.feed.publish("", "", extra={"kind": "done", "app": "codex", "chat": "x1"})
        b = self.feed.publish("", "", extra={"kind": "waiting", "app": "claude", "chat": "c1"})
        answer = self.get(f"/api/notify/push?since={a['id']}")
        self.assertEqual((answer.status, answer.getheader("Content-Type")), (200, ntfy_feed.NDJSON))
        self.assertEqual(json.loads(answer.fp.readline())["event"], "open")
        self.assertEqual(json.loads(answer.fp.readline()), b)
        self.assertTrue(until(lambda: self.feed.listening == 1))
        answer.close()
        self.assertTrue(until(lambda: self.feed.listening == 0))

    def test_a_double_slash_from_a_server_address_typed_with_a_slash_at_its_end(self):
        self.assertEqual(self.status("//agent-remote/auth"), 200)

    def test_the_websocket_sends_the_same_answers_pings_and_closes(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.addCleanup(sock.close)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET /agent-remote/ws?since=none HTTP/1.1\r\nHost: pc\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += sock.recv(1)
        self.assertTrue(head.startswith(b"HTTP/1.1 101"), head)
        self.assertIn(f"Sec-WebSocket-Accept: {ntfy_feed.accept_key(key)}".encode(), head)
        opcode, payload = ntfy_feed.read_frame(sock)
        self.assertEqual((opcode, json.loads(payload)["event"]), (0x1, "open"))
        msg = self.feed.publish("部署方案", "家里电脑 · Claude 在等你选\n先改方案还是先测？")
        self.assertEqual(ntfy_feed.read_frame(sock), (0x1, json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode()))

        def send(opcode, data):  # a client's frames are masked
            mask = os.urandom(4)
            sock.sendall(bytes([0x80 | opcode, 0x80 | len(data)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        send(0x9, b"ping?")
        self.assertEqual(ntfy_feed.read_frame(sock), (0xA, b"ping?"))
        send(0x8, (1000).to_bytes(2, "big"))
        self.assertEqual(ntfy_feed.read_frame(sock), (0x8, (1000).to_bytes(2, "big")))
        self.assertTrue(until(lambda: self.feed.listening == 0))

    def test_a_plain_request_to_the_websocket_address_is_refused(self):
        self.assertEqual(self.status("/agent-remote/ws"), 400)


class AccessTests(unittest.TestCase):
    """The app's requests come through tailscale serve and are let in as the page is: by the Tailscale account."""
    def ask(self, path, login=None):
        handler = object.__new__(remote.Handler); sent = []
        handler.path = path; handler.headers = {"Tailscale-User-Login": login} if login else {}; handler.close_connection = False
        handler.server = SimpleNamespace(machine={"name": "家里电脑", "apps": ["codex"], "voice": False},
                                         owner=SimpleNamespace(login=lambda: "me@example.com"),
                                         cfg={"token": "secret", "bind": "127.0.0.1", "allowed_logins": [], "apps": ["codex"]},
                                         notifier=SimpleNamespace(feed=ntfy_feed.Feed()))
        handler._send = lambda code, body, ctype, extra=None: sent.append((code, body.decode("utf-8")))
        handler.do_GET()
        return sent[0]

    def test_this_computers_own_account_subscribes_and_no_one_else(self):
        self.assertEqual(self.ask("/agent-remote/auth", login="me@example.com"), (200, '{"success": true}'))
        self.assertEqual(self.ask("//agent-remote/auth", login="me@example.com")[0], 200)
        self.assertEqual(self.ask("/agent-remote/auth", login="friend@example.com")[0], 403)
        self.assertEqual(self.ask("/agent-remote/auth")[0], 403)  # not through Tailscale: the token, which the app has not
        self.assertEqual(self.ask("/agent-remote/auth?t=secret")[0], 200)


if __name__ == "__main__":
    unittest.main()
