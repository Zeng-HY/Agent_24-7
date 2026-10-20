import ctypes
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notify  # noqa: E402
import winctl  # noqa: E402

KEY = "AbCdEf1234567890xyZQ"


def codex_line(kind, ts, **payload):
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {"type": kind, **payload}}, ensure_ascii=False)


def claude_line(kind, ts, **fields):
    return json.dumps({"type": kind, "timestamp": ts, "isSidechain": False, **fields}, ensure_ascii=False)


def answer(mid, stop, *blocks, **extra):
    return {"message": {"id": mid, "stop_reason": stop, "content": list(blocks)}, **extra}


class Address(unittest.TestCase):
    def test_what_bark_shows(self):
        self.assertEqual(notify.parse_address(f"https://api.day.app/{KEY}/这里改成你自己的推送内容"),
                         {"server": "https://api.day.app", "key": KEY})
        self.assertEqual(notify.parse_address(f"  https://api.day.app/{KEY}/ \n"), {"server": "https://api.day.app", "key": KEY})
        self.assertEqual(notify.parse_address(f"api.day.app/{KEY}"), {"server": "https://api.day.app", "key": KEY})

    def test_a_server_of_ones_own_and_a_key_alone(self):
        self.assertEqual(notify.parse_address(f"http://bark.example.com:8080/{KEY}/标题/内容"),
                         {"server": "http://bark.example.com:8080", "key": KEY})
        self.assertEqual(notify.parse_address(KEY), {"server": "https://api.day.app", "key": KEY})

    def test_anything_else_is_refused(self):
        for text in ("", "你好", "https://api.day.app/", "https://api.day.app/ab"):
            with self.assertRaises(notify.NotifyError):
                notify.parse_address(text)


class Send(unittest.TestCase):
    def test_one_json_post_to_push(self):
        seen = {}

        def urlopen(request, timeout):
            seen.update(url=request.full_url, body=json.loads(request.data), method=request.get_method(), timeout=timeout)
            return io.BytesIO(b'{"code":200,"message":"success"}')

        with mock.patch.object(notify.urllib.request, "urlopen", urlopen):
            notify.send({"server": "https://api.day.app/", "key": KEY}, "标题", "内容", subtitle="家里电脑 · Codex 好了",
                        group="家里电脑", url="https://pc.example.ts.net/?open=codex:x")
        self.assertEqual((seen["url"], seen["method"]), ("https://api.day.app/push", "POST"))
        self.assertEqual(seen["body"], {"device_key": KEY, "title": "标题", "body": "内容", "subtitle": "家里电脑 · Codex 好了",
                                        "group": "家里电脑", "url": "https://pc.example.ts.net/?open=codex:x"})

    def test_refusals_say_why_without_the_key(self):
        def refused(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {},
                                         io.BytesIO(b'{"code":400,"message":"failed to get device token"}'))

        def unreachable(request, timeout):
            raise urllib.error.URLError("timed out")

        def odd(request, timeout):
            return io.BytesIO(b'{"code":500,"message":"push failed"}')

        for urlopen, words in ((refused, "failed to get device token"), (unreachable, "连不上"), (odd, "push failed")):
            with mock.patch.object(notify.urllib.request, "urlopen", urlopen), self.assertRaises(notify.NotifyError) as caught:
                notify.send({"server": "https://api.day.app", "key": KEY}, "t", "b")
            self.assertIn(words, str(caught.exception))
            self.assertNotIn(KEY, str(caught.exception))


class TurnEnd(unittest.TestCase):
    def test_codex(self):
        started = codex_line("task_started", "2026-10-14T03:00:00Z", turn_id="t1")
        done = codex_line("task_complete", "2026-10-14T03:01:00Z", turn_id="t1", last_agent_message="改好了。")
        aborted = codex_line("turn_aborted", "2026-10-14T03:02:00Z", turn_id="t2", reason="interrupted")
        other = json.dumps({"timestamp": "2026-10-14T03:01:01Z", "type": "response_item", "payload": {"type": "message"}})
        self.assertEqual(notify.turn_end("codex", [started.encode()])["state"], "running")
        self.assertEqual(notify.turn_end("codex", [started.encode(), done.encode(), other.encode()]),
                         {"state": "done", "key": "t1", "time": "2026-10-14T03:01:00Z", "text": "改好了。"})
        self.assertEqual(notify.turn_end("codex", [done.encode(), aborted.encode()])["state"], "stopped")
        self.assertIsNone(notify.turn_end("codex", [other.encode()]))

    def test_claude_one_answer_in_two_records(self):
        lines = [claude_line("user", "2026-10-14T03:00:00Z", uuid="u1", message={"content": "帮我看看"}),
                 claude_line("assistant", "2026-10-14T03:00:05Z", uuid="a1", **answer("m1", "tool_use", {"type": "tool_use", "name": "Read"})),
                 claude_line("user", "2026-10-14T03:00:06Z", uuid="u2", message={"content": [{"type": "tool_result", "content": "…"}]}),
                 claude_line("assistant", "2026-10-14T03:00:09Z", uuid="a2", **answer("m2", "end_turn", {"type": "thinking", "thinking": "…"})),
                 claude_line("assistant", "2026-10-14T03:00:09Z", uuid="a3", **answer("m2", "end_turn", {"type": "text", "text": "看完了，没问题。"})),
                 json.dumps({"type": "system", "subtype": "stop_hook_summary", "timestamp": "2026-10-14T03:00:10Z"})]
        self.assertEqual(notify.turn_end("claude", [ln.encode() for ln in lines[:3]])["state"], "running")
        self.assertEqual(notify.turn_end("claude", [ln.encode() for ln in lines]),
                         {"state": "done", "key": "m2", "time": "2026-10-14T03:00:09Z", "text": "看完了，没问题。"})

    def test_claude_stopped_failed_and_sidechains(self):
        stopped = claude_line("user", "2026-10-14T03:00:00Z", uuid="u3", message={"content": [{"type": "text", "text": "[Request interrupted by user]"}]})
        failed = claude_line("assistant", "2026-10-14T03:00:00Z", uuid="a4", isApiErrorMessage=True,
                             **answer("m4", "stop_sequence", {"type": "text", "text": "API Error: 529 Overloaded"}))
        side = json.dumps({"type": "assistant", "isSidechain": True, "timestamp": "2026-10-14T03:00:01Z", **answer("m5", "end_turn", {"type": "text", "text": "子任务"})})
        self.assertEqual(notify.turn_end("claude", [stopped.encode()])["state"], "stopped")
        self.assertEqual(notify.turn_end("claude", [failed.encode(), side.encode()])["state"], "failed")


class Watcher(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.now = 1_800_000_000.0  # 2027-01-15; the turns below end after it
        self.sent, self.saved, self.logged = [], [], []
        self.idle = None
        self.cfg = {"token": "secret", "bark": {"server": "https://api.day.app", "key": KEY}}
        self.codex = Path(self.dir.name) / "rollout.jsonl"
        self.codex.write_text(codex_line("task_complete", "2026-10-01T00:00:00Z", turn_id="old", last_agent_message="旧的") + "\n", encoding="utf-8")
        self.items = [{"app": "codex", "id": "x1", "title": "改通知", "path": str(self.codex)}]
        patches = [mock.patch.object(notify.chats, "_codex_rows", lambda where, args, limit: [dict(i) for i in self.items]),
                   mock.patch.object(notify.chats, "claude_sessions", lambda limit: []),
                   mock.patch.object(notify.chats, "conv_path", lambda item: Path(item["path"]))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.notifier = notify.Notifier(self.cfg, "家里电脑", self.logged.append, lambda: self.saved.append(dict(self.cfg)),
                                        clock=lambda: self.now, idle=lambda: self.idle,
                                        sender=lambda *a, **k: self.sent.append((a, k)), page_url=lambda: "https://pc.example.ts.net/")

    def turn(self, kind, turn_id, text="", ts="2027-01-15T08:00:10Z"):
        with self.codex.open("a", encoding="utf-8") as f:
            f.write(codex_line(kind, ts, turn_id=turn_id, last_agent_message=text) + "\n")

    def test_a_turn_that_ends_is_sent_once_with_a_link_to_it(self):
        self.notifier.look()  # what had ended before the service started is not sent
        self.assertEqual(self.sent, [])
        self.turn("task_started", "t1")
        self.notifier.look()
        self.turn("task_complete", "t1", "**改好了**，测试都过了。")
        self.notifier.look()
        self.notifier.look()
        self.assertEqual(len(self.sent), 1)
        (address, title, body), extra = self.sent[0]
        self.assertEqual((address["key"], title, body), (KEY, "改通知", "改好了，测试都过了。"))
        self.assertEqual(extra, {"subtitle": "家里电脑 · Codex 好了", "group": "家里电脑",
                                 "url": "https://pc.example.ts.net/?open=codex:x1"})
        self.assertEqual(self.notifier.public()["recent"][0]["text"], "Codex「改通知」好了 · 已推到手机")
        self.assertNotIn(KEY, json.dumps(self.notifier.public()) + "".join(self.logged))

    def test_not_sent_when_stopped_watched_or_someone_is_here(self):
        self.notifier.look()
        self.turn("turn_aborted", "t1")
        self.notifier.look()
        with self.notifier.watching("codex", "x1"):
            self.turn("task_complete", "t2", "好")
            self.notifier.look()
        self.idle = 35.0
        self.turn("task_complete", "t3", "好")
        self.notifier.look()
        self.idle = 300.0
        self.turn("task_complete", "t4", "好")
        self.notifier.look()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual([r["text"] for r in self.notifier.public()["recent"]],
                         ["Codex「改通知」好了 · 已推到手机", "Codex「改通知」好了 · 没推：有人 35 秒前用过这台电脑",
                          "Codex「改通知」好了 · 没推：手机正开着这个对话"])

    def test_nothing_is_read_without_an_address_and_only_later_turns_count(self):
        self.cfg.pop("bark")
        self.turn("task_complete", "t1", "好")
        self.notifier.look()
        self.assertEqual(self.sent, [])
        self.now += 60  # the address is set a minute later: t1 ended before that
        self.cfg["bark"] = {"server": "https://api.day.app", "key": KEY}
        self.notifier.look()
        self.assertEqual(self.sent, [])

    def test_bark_down_twice_is_noted(self):
        def down(*a, **k):
            raise notify.NotifyError("连不上 Bark 的服务器 api.day.app：timed out")
        self.notifier.sender = down
        self.notifier.stopped.set()  # no waiting between the two tries
        self.notifier.look()
        self.turn("task_complete", "t1", "好")
        self.notifier.look()
        self.assertIn("没推出去：连不上", self.notifier.public()["recent"][0]["text"])

    def test_the_address_is_kept_only_once_a_first_one_went_through(self):
        self.cfg.pop("bark")
        result = self.notifier.set_address(f"https://api.day.app/{KEY}/这里改成你自己的推送内容")
        self.assertTrue(result["configured"])
        self.assertEqual(self.cfg["bark"], {"server": "https://api.day.app", "key": KEY})
        self.assertEqual(self.sent[0][1]["url"], "https://pc.example.ts.net/")
        self.assertEqual(self.notifier.public(), {"configured": True, "server": "api.day.app", "recent": [],
                                                  "ntfy": {"on": False, "topic": "agent-remote", "server": "https://pc.example.ts.net",
                                                           "listening": 0, "last_seen": ""}})

        def refused(*a, **k):
            raise notify.NotifyError("Bark 没收下（400）：failed to get device token")
        self.notifier.sender = refused
        with self.assertRaises(notify.NotifyError):
            self.notifier.set_address("https://api.day.app/WrongKey123456/")
        self.assertEqual(self.cfg["bark"]["key"], KEY)
        self.assertFalse(self.notifier.set_address("")["configured"])
        self.assertNotIn("bark", self.cfg)
        self.assertEqual(len(self.saved), 2)

    # -- ntfy: the ntfy app on an Android phone listens to this service (ntfy_feed.py, 10-20)

    def test_with_ntfy_alone_the_turn_goes_to_the_app_with_its_link(self):
        self.cfg.pop("bark")
        self.cfg["ntfy"] = True
        self.notifier.look()
        self.turn("task_complete", "t1", "**改好了**，测试都过了。")
        self.notifier.look()
        self.assertEqual(self.sent, [])  # no Bark
        msg = self.notifier.feed.since("all")[0]
        self.assertEqual((msg["title"], msg["message"], msg["click"]),
                         ("改通知", "家里电脑 · Codex 好了\n改好了，测试都过了。", "https://pc.example.ts.net/?open=codex:x1"))
        self.assertEqual(self.notifier.public()["recent"][0]["text"], "Codex「改通知」好了 · ntfy 现在没连着，连上后会收到")
        with self.notifier.feed.listener():  # a phone connected
            self.turn("task_complete", "t2", "又好了")
            self.notifier.look()
        self.assertEqual(self.notifier.public()["recent"][0]["text"], "Codex「改通知」好了 · ntfy 已推到")

    def test_bark_and_ntfy_both_get_it_and_the_quiet_rules_hold_for_both(self):
        self.cfg["ntfy"] = True
        self.notifier.look()
        self.turn("task_complete", "t1", "好")
        self.notifier.look()
        self.assertEqual((len(self.sent), len(self.notifier.feed.since("all"))), (1, 1))
        self.assertEqual(self.notifier.public()["recent"][0]["text"], "Codex「改通知」好了 · ntfy 现在没连着，连上后会收到；已推到手机")
        self.idle = 20.0
        self.turn("task_complete", "t2", "好")
        self.notifier.look()
        self.assertEqual((len(self.sent), len(self.notifier.feed.since("all"))), (1, 1))

    def test_ntfy_turned_on_and_off_from_the_page_and_tried_alone(self):
        self.cfg.pop("bark")
        self.turn("task_complete", "t1", "好")  # ended before ntfy was turned on: not sent
        self.now += 60
        result = self.notifier.set_ntfy(True)
        self.assertEqual((self.cfg.get("ntfy"), len(self.saved)), (True, 1))
        self.assertIn("ntfy 现在没连着", result["text"])
        self.assertEqual(self.notifier.feed.since("all")[0]["title"], "家里电脑的通知设好了")
        self.notifier.look()
        self.assertEqual(len(self.notifier.feed.since("all")), 1)
        with self.notifier.feed.listener():
            self.assertEqual(self.notifier.test("ntfy")["text"], "推了一条，看看 ntfy")
            self.assertTrue(self.notifier.public()["ntfy"]["on"])
            self.assertEqual(self.notifier.public()["ntfy"]["listening"], 1)
        self.assertEqual(self.sent, [])
        with self.assertRaises(notify.NotifyError):
            self.notifier.test("bark")  # no Bark address
        self.assertFalse(self.notifier.set_ntfy(False)["ntfy"])
        self.assertNotIn("ntfy", self.cfg)
        with self.assertRaises(notify.NotifyError):
            self.notifier.test("ntfy")


class PersonIdle(unittest.TestCase):
    """The service's own key presses (SendInput for the phone) are not a person at the PC."""

    def fake(self, last_input, now):
        def last(ref):
            ref._obj.dwTime = last_input & 0xFFFFFFFF
            return 1
        return SimpleNamespace(GetLastInputInfo=last), SimpleNamespace(GetTickCount=lambda: now)

    def test_own_input_and_a_persons(self):
        cases = [((1000, 1010), 1005, 9000, None),        # the last input was ours
                 ((1000, 1010), 5000, 9000, 4.0),          # a person, four seconds ago
                 (None, 5000, 9000, 4.0),                  # nothing sent yet
                 ((2 ** 32 - 20, 2 ** 32 - 10), 5, 3000, None)]  # the tick count wrapped in between
        for sent, last_input, now, expected in cases:
            user32, kernel32 = self.fake(last_input, now)
            with mock.patch.object(winctl, "user32", user32), mock.patch.object(winctl, "kernel32", kernel32), \
                    mock.patch.object(winctl, "_sent_ticks", sent):
                self.assertEqual(winctl.person_idle_seconds(), expected, (sent, last_input))


if __name__ == "__main__":
    unittest.main()
