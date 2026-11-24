"""ntfy's wording (11-24), the 定时任务 setting, the records it needs, Codex's own notify rules, and the routes.

Nothing here opens a real Codex database, automation.toml or record: every CODEX_HOME is a temporary directory.
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notify  # noqa: E402
import relay_push  # noqa: E402
import remote  # noqa: E402
import agents.codex as codex_agent  # noqa: E402
from agents.codex import AUTOMATION_WHERE, CodexAgent  # noqa: E402

KEY = "AbCdEf1234567890xyZQ"
NOW = 1_800_000_000.0  # 2027-01-15T08:00:00Z
TS = "2027-01-15T08:00:00Z"


def codex_line(kind, ts, **payload):
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {"type": kind, **payload}}, ensure_ascii=False)


def make_notifier(cfg=None, sent=None, page="https://pc.example.ts.net/", log=None):
    return notify.Notifier(
        {"ntfy": True} if cfg is None else cfg, "家里电脑",
        (log if log is not None else []).append, lambda: None,
        clock=lambda: NOW, sender=lambda *a, **k: (sent if sent is not None else []).append((a, k)),
        page_url=lambda: page,
    )


class NtfyWording(unittest.TestCase):
    def tell(self, end, item=None, cfg=None, page="https://pc.example.ts.net/"):
        notifier = make_notifier(cfg, page=page)
        item = item or {"app": "codex", "id": "x1", "title": "改通知"}
        notifier._tell(None, item, end)
        return notifier, notifier.feed.since("all")[-1]

    def end(self, seconds, state="done", text="改好了。", **extra):
        return {"state": state, "started": int(NOW) - int(seconds), "ended": int(NOW), "text": text, **extra}

    def test_done_wording_under_a_minute_six_minutes_and_two_hours(self):
        for seconds, state in ((5, "好了"), (360, "好了 · 用了 6 分钟"),
                               (2 * 3600 + 5 * 60, "好了 · 用了 2 小时 5 分钟"),
                               (3600, "好了 · 用了 1 小时"), (60, "好了 · 用了 1 分钟")):
            with self.subTest(seconds=seconds):
                _, msg = self.tell(self.end(seconds))
                self.assertEqual(msg["message"], f"Codex · 家里电脑 · {state}\n改好了。")
                self.assertEqual(msg["title"], "改通知")
                self.assertEqual(msg["priority"], 3)

    def test_waiting_and_failed_are_high_priority_and_say_so(self):
        _, waiting = self.tell(self.end(5, asks=True, text="先改方案还是先测？"))
        self.assertEqual(waiting["message"].split("\n")[0], "Codex · 家里电脑 · 在等你选")
        self.assertEqual(waiting["priority"], 4)
        _, failed = self.tell(self.end(5, state="failed", text="API Error"))
        self.assertEqual(failed["message"].split("\n")[0], "Codex · 家里电脑 · 出错停了")
        self.assertEqual(failed["priority"], 4)

    def test_a_title_less_conversation_falls_back_to_the_assistant_and_the_computer(self):
        for title in ("", "（无标题）"):
            with self.subTest(title=title):
                _, msg = self.tell(self.end(5), item={"app": "claude", "id": "c1", "title": title})
                self.assertEqual(msg["title"], "Claude · 家里电脑")
                self.assertEqual(msg["message"], "Claude · 家里电脑 · 好了\n改好了。")

    def test_the_icon_the_same_conversation_key_and_the_click(self):
        _, msg = self.tell(self.end(5))
        self.assertEqual(msg["icon"], "https://pc.example.ts.net/icon-192.png")
        self.assertEqual(msg["sequence_id"], "codex-x1")
        self.assertEqual(msg["click"], "https://pc.example.ts.net/?open=codex:x1")
        notifier, _ = self.tell(self.end(5), page="")
        self.assertNotIn("icon", notifier.feed.since("all")[-1])

    def test_try_pushes_carry_the_icon_but_never_a_sequence(self):
        notifier = make_notifier({"ntfy": True})
        notifier.set_ntfy(True)
        first = notifier.feed.since("all")[-1]
        self.assertEqual(first["icon"], "https://pc.example.ts.net/icon-192.png")
        self.assertNotIn("sequence_id", first)
        notifier.test("ntfy")
        tried = notifier.feed.since("all")[-1]
        self.assertEqual(tried["icon"], "https://pc.example.ts.net/icon-192.png")
        self.assertNotIn("sequence_id", tried)

    def test_the_sequence_survives_any_id_and_keeps_to_64_characters(self):
        self.assertEqual(notify.sequence_id("codex", "x1"), "codex-x1")
        self.assertEqual(notify.sequence_id("codex", "a b/c:d"), "codex-a_b_c_d")
        long = notify.sequence_id("codex", "z" * 80)
        self.assertRegex(long, r"^codex-z{34}-[0-9a-f]{16}$")
        self.assertLessEqual(len(long), 64)


class Wording(unittest.TestCase):
    def test_the_used_time_matches_the_relay_word_for_word(self):
        for started, ended in ((0, 100), (100, 159), (100, 160), (100, 100 + 3599), (100, 100 + 3600),
                               (100, 100 + 2 * 3600 + 5 * 60), (100, 100 + 59)):
            with self.subTest(started=started, ended=ended):
                self.assertEqual(notify.used_text(started, ended), relay_push.used_text(started, ended))
                self.assertEqual(notify.notice_state({"state": "done", "started": started, "ended": ended}),
                                 relay_push.notice_body("done", started, ended))

    def test_waiting_and_failed_match_the_relay_too(self):
        for kind, state in (("waiting", {"state": "done", "asks": True}), ("failed", {"state": "failed"})):
            self.assertEqual(notify.notice_state(state), relay_push.notice_body(kind, 0, 0))


class Decision(unittest.TestCase):
    def test_a_heartbeat_block_alone_with_do_not_notify(self):
        for raw in ("<heartbeat><decision>DONT_NOTIFY</decision></heartbeat>",
                    "```xml\n<heartbeat><decision>DONT_NOTIFY</decision></heartbeat>\n```"):
            with self.subTest(raw=raw):
                got = notify.notice_decision(raw)
                self.assertFalse(got["send"])
                self.assertIn("不用提醒", got["why"])

    def test_a_heartbeat_block_alone_saying_notify_carries_its_message(self):
        raw = ("<heartbeat><decision>NOTIFY</decision>"
               "<message><![CDATA[日报写好了]]></message></heartbeat>")
        got = notify.notice_decision(raw)
        self.assertEqual((got["send"], got["text"]), (True, "日报写好了"))

    def test_a_notify_block_after_words_is_read_too(self):
        raw = "干完了\n<heartbeat><decision>NOTIFY</decision></heartbeat>"
        self.assertTrue(notify.notice_decision(raw)["send"])

    def test_the_last_heartbeat_block_decides(self):
        raw = ("<heartbeat><decision>NOTIFY</decision></heartbeat>\n"
               "<heartbeat><decision>DONT_NOTIFY</decision></heartbeat>")
        self.assertFalse(notify.notice_decision(raw)["send"])

    def test_a_heartbeat_turn_that_answers_only_dont_notify(self):
        for raw in ("DONT_NOTIFY", "<![CDATA[DONT_NOTIFY]]>", "  \n<![CDATA[ DONT_NOTIFY ]]>\n ",
                    "<![CDATA[ DONT_NOTIFY]]>"):
            with self.subTest(raw=raw):
                got = notify.notice_decision(raw, heartbeat=True)
                self.assertFalse(got["send"])
                self.assertIn("不用提醒", got["why"])
        # a normal conversation keeps DONT_NOTIFY as ordinary words (Codex's own check is for heartbeat turns)
        self.assertTrue(notify.notice_decision("DONT_NOTIFY")["send"])

    def test_the_skip_marks_in_every_shell(self):
        cases = ["::SKIP_COMPLETION::", ":: SKIP_COMPLETION ::", "skip_notification",
                 '{"type": "skip_notification"}', '{"type": "skip_completion"}',
                 "```\n::SKIP_COMPLETION::\n```", "```json\n" + '{"type":"skip_notification"}' + "\n```",
                 "`skip_notification`", "<escape>::SKIP_COMPLETION::</escape>",
                 json.dumps('{"type":"skip_notification"}')]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertFalse(notify.notice_decision(raw)["send"])

    def test_an_ordinary_answer_is_sent(self):
        self.assertTrue(notify.notice_decision("改好了。")["send"])
        self.assertTrue(notify.notice_decision("")["send"])  # not a task: an empty answer still goes (f)

    def test_the_order_of_codex_26_1117(self):
        # a heartbeat that answers only DONT_NOTIFY is quiet; failed_only overrides it on a failed run
        self.assertFalse(notify.notice_decision("DONT_NOTIFY", heartbeat=True)["send"])
        self.assertTrue(notify.notice_decision("DONT_NOTIFY", heartbeat=True, task=True, failed=True,
                                               failed_only=True)["send"])
        # a block's DONT_NOTIFY is quiet, and failed_only overrides it on a failed run
        block = "<heartbeat><decision>DONT_NOTIFY</decision></heartbeat>"
        self.assertFalse(notify.notice_decision(block, heartbeat=True, task=True)["send"])
        self.assertTrue(notify.notice_decision(block, heartbeat=True, task=True, failed=True,
                                               failed_only=True)["send"])
        # a skip mark is only read on a successful turn
        self.assertFalse(notify.notice_decision("::SKIP_COMPLETION::")["send"])
        self.assertTrue(notify.notice_decision("::SKIP_COMPLETION::", task=True, failed=True)["send"])
        # an empty successful answer says nothing for a heartbeat or a task, but is sent for a normal conversation
        self.assertFalse(notify.notice_decision("", heartbeat=True)["send"])
        self.assertFalse(notify.notice_decision("", task=True)["send"])
        self.assertTrue(notify.notice_decision("")["send"])
        # failed_only: a success is quiet, a failure goes
        self.assertFalse(notify.notice_decision("好了", task=True, failed_only=True)["send"])
        self.assertTrue(notify.notice_decision("好了", task=True, failed=True, failed_only=True)["send"])
        # the setting off is quiet whatever the answer says
        self.assertFalse(notify.notice_decision("干完了", task=True, off=True)["send"])
        self.assertFalse(notify.notice_decision("干完了", heartbeat=True, task=True, off=True)["send"])


class HeartbeatInput(unittest.TestCase):
    BLOCK = ("<heartbeat>\n<automation_id>10-a</automation_id>\n"
             "<current_time_iso>2026-10-03T02:00:37.975Z</current_time_iso>\n"
             "<instructions>do it</instructions>\n</heartbeat>")

    def test_a_whole_block_is_a_heartbeat_and_anything_around_it_is_not(self):
        self.assertEqual(codex_agent.heartbeat_input(self.BLOCK), self.BLOCK.strip())
        self.assertIsNone(codex_agent.heartbeat_input("hello\n" + self.BLOCK))
        self.assertIsNone(codex_agent.heartbeat_input(self.BLOCK + "\nthanks"))
        self.assertIsNone(codex_agent.heartbeat_input("<heartbeat><automation_id>x</automation_id></heartbeat>"))

    def test_a_tool_outputs_words_are_unwrapped(self):
        self.assertEqual(codex_agent.output_text(self.BLOCK), self.BLOCK)
        self.assertEqual(codex_agent.output_text(json.dumps({"output": self.BLOCK, "metadata": {}})), self.BLOCK)
        self.assertEqual(codex_agent.output_text({"output": self.BLOCK}), self.BLOCK)
        self.assertEqual(codex_agent.output_text(""), "")

    def test_a_model_made_heartbeat_arrives_as_a_tool_output(self):
        agent, scan = CodexAgent(), notify.new_scan("codex")
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "event_msg", "payload": {"type": "task_started"}})
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "c1", "output": json.dumps({"output": self.BLOCK})}})
        self.assertTrue(scan["heartbeat"])
        self.assertEqual(scan["automation_id"], "10-a")

    def test_each_turn_clears_the_heartbeat_and_reads_its_own_id(self):
        agent, scan = CodexAgent(), notify.new_scan("codex")
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "event_msg", "payload": {"type": "task_started"}})
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": self.BLOCK}]}})
        self.assertEqual((scan["heartbeat"], scan["automation_id"]), (True, "10-a"))
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "event_msg", "payload": {"type": "task_started"}})
        self.assertEqual((scan["heartbeat"], scan["automation_id"]), (False, ""))  # a person's own next turn
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "你好"}]}})
        self.assertFalse(scan["heartbeat"])

    def test_an_error_event_marks_the_turn_and_is_cleared_at_the_next_start(self):
        agent, scan = CodexAgent(), notify.new_scan("codex")
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "event_msg", "payload": {"type": "task_started"}})
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "event_msg", "payload": {"type": "error", "message": "boom"}})
        self.assertTrue(scan["error"])
        agent.notify_scan_record(scan, {"timestamp": TS, "type": "event_msg", "payload": {"type": "task_started"}})
        self.assertFalse(scan["error"])


class PolicyFile(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patches = [mock.patch.object(notify.chats, "CODEX_HOME", Path(self.home.name)),
                   mock.patch.dict(notify._AUTOMATION_POLICY, clear=True)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, ident, text):
        folder = Path(self.home.name) / "automations" / ident
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "automation.toml").write_text(text, encoding="utf-8")

    def test_failed_runs_only_is_read_and_cached(self):
        home = Path(self.home.name)
        self.write("daily", 'notification_policy = "failed_runs_only"\n')
        self.assertTrue(notify.automation_failed_runs_only("daily", home))
        self.write("daily", 'notification_policy = "always"\n')  # still the cached answer for a minute
        self.assertTrue(notify.automation_failed_runs_only("daily", home))
        notify._AUTOMATION_POLICY.clear()
        self.assertFalse(notify.automation_failed_runs_only("daily", home))

    def test_missing_or_odd_files_read_as_not_failed_only(self):
        home = Path(self.home.name)
        self.write("broken", "this is not toml\n")
        self.assertFalse(notify.automation_failed_runs_only("broken", home))
        self.assertFalse(notify.automation_failed_runs_only("none", home))

    def test_an_id_that_could_walk_the_path_is_never_read(self):
        home = Path(self.home.name)
        with mock.patch.object(notify.tomllib, "load", side_effect=AssertionError("read")):
            for ident in ("../x", "a/b", "a\\b", "", "a" * 81, "dot.name"):
                self.assertFalse(notify.automation_failed_runs_only(ident, home))

    def test_failed_mode_pushes_only_failures(self):
        good = notify.notice_decision("好了", task=True, failed_only=True)
        self.assertFalse(good["send"])
        self.assertIn("只在失败时提醒", good["why"])
        failed = notify.notice_decision("", task=True, failed=True, failed_only=True)
        self.assertTrue(failed["send"])

    def test_failed_runs_only_in_codex_mode(self):
        self.assertFalse(notify.notice_decision("好了", task=True, failed_only=True)["send"])
        self.assertTrue(notify.notice_decision("", task=True, failed=True, failed_only=True)["send"])

    def test_a_user_stopped_run_is_not_a_failure(self):
        # look() decides "failed"; an interrupted turn arrives here as failed=False, so failed_only stays quiet
        self.assertFalse(notify.notice_decision("", task=True, failed=False, failed_only=True)["send"])

    def test_an_empty_automation_answer_is_not_sent(self):
        got = notify.notice_decision("   ", task=True)
        self.assertFalse(got["send"])
        self.assertIn("没有回答", got["why"])
        self.assertTrue(notify.notice_decision("", task=False)["send"])

    def test_the_markers_still_win_on_a_failed_run(self):
        raw = "<heartbeat><decision>DONT_NOTIFY</decision></heartbeat>"
        self.assertFalse(notify.notice_decision(raw, task=True)["send"])
        # ... unless the setting only wants failures: that last rule overrides the answer's own mark
        self.assertTrue(notify.notice_decision(raw, task=True, failed=True, failed_only=True)["send"])


class Conversations(unittest.TestCase):
    def test_off_queries_only_the_normal_threads(self):
        calls = []

        def rows(where, args, limit):
            calls.append(where)
            return []

        with mock.patch.object(notify.chats, "_codex_rows", rows):
            CodexAgent().notify_conversations(30, "off")
        self.assertEqual(calls, [notify.CODEX_WHERE])

    def test_codex_and_failed_add_the_ten_newest_automation_threads(self):
        calls = []

        def rows(where, args, limit):
            calls.append((where, limit))
            if where == AUTOMATION_WHERE:
                return [{"app": "codex", "id": "auto-1", "title": "日报", "path": "x"}]
            return [{"app": "codex", "id": "talk-1", "title": "聊天", "path": "y"}]

        for mode in ("codex", "failed"):
            with self.subTest(mode=mode):
                calls.clear()
                with mock.patch.object(notify.chats, "_codex_rows", rows):
                    recent, full = CodexAgent().notify_conversations(30, mode)
                self.assertEqual(calls, [(notify.CODEX_WHERE, 30), (AUTOMATION_WHERE, 10)])
                self.assertEqual([row["id"] for row in recent], ["talk-1", "auto-1"])
                self.assertTrue(recent[1]["automation"])
                self.assertNotIn("automation", recent[0])
                self.assertEqual(full, [])

    def test_a_row_returned_by_both_queries_is_listed_once_and_kept_plain(self):
        row = {"app": "codex", "id": "same", "title": "聊天", "path": "y"}
        with mock.patch.object(notify.chats, "_codex_rows", lambda where, args, limit: [dict(row)]):
            recent, _ = CodexAgent().notify_conversations(30, "codex")
        self.assertEqual(len(recent), 1)
        self.assertNotIn("automation", recent[0])


class Routes(unittest.TestCase):
    def setUp(self):
        self.saved, self.logged = [], []
        self.cfg = {"token": "secret", "bind": "127.0.0.1", "allowed_logins": []}
        self.notifier = notify.Notifier(self.cfg, "家里电脑", self.logged.append,
                                        lambda: self.saved.append(dict(self.cfg)),
                                        clock=lambda: NOW, sender=lambda *a, **k: None,
                                        page_url=lambda: "https://pc.example.ts.net/")

    def call(self, method, path, body=None):
        handler = object.__new__(remote.Handler)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
        handler.path = path + ("&" if "?" in path else "?") + "t=secret"
        handler.headers = {"Content-Length": str(len(payload)), "Accept-Encoding": ""}
        handler.rfile = io.BytesIO(payload)
        handler.close_connection = False
        handler.server = SimpleNamespace(
            cfg=self.cfg, owner=SimpleNamespace(login=lambda: ""), machine={"name": "家里电脑", "voice": False},
            notifier=self.notifier, log=SimpleNamespace(write=lambda text: None),
        )
        sent = []
        handler._send = lambda code, data, ctype, extra=None: sent.append((code, json.loads(data.decode("utf-8"))))
        (handler.do_GET if method == "GET" else handler.do_POST)()
        return sent[0]

    def test_get_carries_the_setting_and_the_default_is_codex(self):
        code, data = self.call("GET", "/api/notify")
        self.assertEqual(code, 200)
        self.assertEqual(data["automations"], "codex")

    def test_post_keeps_a_valid_mode_and_writes_it_down(self):
        code, data = self.call("POST", "/api/notify/automations", {"mode": "failed"})
        self.assertEqual((code, data), (200, {"ok": True, "automations": "failed", "text": "已改成：只推失败的"}))
        self.assertEqual(self.cfg["automations"], "failed")
        self.assertTrue(self.saved)
        self.assertIn("只推失败的", "".join(self.logged))
        code, data = self.call("POST", "/api/notify/automations", {"mode": "codex"})
        self.assertEqual((code, data["automations"]), (200, "codex"))

    def test_post_refuses_anything_else_with_a_chinese_line(self):
        for mode in ("", "always", 1, None):
            with self.subTest(mode=mode):
                code, data = self.call("POST", "/api/notify/automations", {"mode": mode})
                self.assertEqual(code, 400)
                self.assertIn("三个选项", data["error"])
        self.assertNotIn("automations", self.cfg)


class Rollout(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "rollout.jsonl"
        self.sent, self.logged = [], []
        self.cfg = {"ntfy": True}
        self.item = {"app": "codex", "id": "a1", "title": "日报", "path": str(self.path), "automation": True}
        patches = [
            mock.patch.object(notify.chats, "CODEX_HOME", Path(self.dir.name)),  # never the real ~/.codex
            mock.patch.object(notify.chats, "conv_path", lambda item: Path(item["path"])),
            mock.patch.object(notify.chats, "claude_sessions", lambda limit: []),
            mock.patch.object(notify.chats, "_codex_rows",
                              lambda where, args, limit: [dict(self.item)] if where == AUTOMATION_WHERE else []),
            mock.patch("deepseek_control.catalog", lambda: []),
            mock.patch.dict(notify._AUTOMATION_POLICY, clear=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.notifier = notify.Notifier(self.cfg, "家里电脑", self.logged.append, lambda: None,
                                        clock=lambda: NOW, sender=lambda *a, **k: self.sent.append((a, k)),
                                        page_url=lambda: "https://pc.example.ts.net/")
        self.write(codex_line("task_started", TS, turn_id="t1"))  # the record on this PC starts the turn first
        self.write(json.dumps({"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text":
                "Automation: 日报\nAutomation ID: daily-1\nAutomation memory: …\nLast run: …\n\n写今天的日报"}]}}))

    def write(self, line):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def test_an_automation_run_reaches_the_phone_with_its_summary_and_its_mark(self):
        with self.notifier.relay.listener():
            self.notifier.look()  # running
            self.write(codex_line("task_complete", "2027-01-15T08:00:10Z", turn_id="t1",
                                  last_agent_message='日报写好了。\n::inbox-item{title="日报" summary="今天有三条要闻"}'))
            self.notifier.look()
        msg = self.notifier.feed.since("all")[-1]
        self.assertEqual(msg["title"], "日报")
        self.assertEqual(msg["message"], "Codex 定时任务 · 家里电脑 · 好了\n今天有三条要闻")
        done = [event for event in self.notifier.relay.since("all") if event.get("kind") == "done"][-1]
        self.assertTrue(done["automation"])
        self.assertEqual(self.sent, [])

    def test_an_error_event_makes_the_task_run_failed(self):
        self.notifier.cfg["automations"] = "failed"
        self.notifier.look()
        self.write(codex_line("error", "2027-01-15T08:00:05Z", message="context window exceeded"))
        self.write(codex_line("task_complete", "2027-01-15T08:00:10Z", turn_id="t1", last_agent_message=None))
        self.notifier.look()
        msg = self.notifier.feed.since("all")[-1]
        self.assertEqual(msg["message"].split("\n")[0], "Codex 定时任务 · 家里电脑 · 出错停了")
        self.assertEqual(msg["priority"], 4)

    def test_a_stream_error_is_not_a_failure(self):
        self.notifier.cfg["automations"] = "failed"
        self.notifier.look()
        self.write(codex_line("stream_error", "2027-01-15T08:00:05Z", message="reconnecting"))
        self.write(codex_line("task_complete", "2027-01-15T08:00:10Z", turn_id="t1", last_agent_message="好了"))
        self.notifier.look()
        self.assertEqual(self.notifier.feed.since("all"), [])

    def test_a_turn_aborted_for_another_reason_is_a_failure(self):
        self.notifier.look()
        self.write(codex_line("turn_aborted", "2027-01-15T08:00:10Z", turn_id="t1", reason="replaced"))
        self.notifier.look()
        msg = self.notifier.feed.since("all")[-1]
        self.assertEqual(msg["message"].split("\n")[0], "Codex 定时任务 · 家里电脑 · 出错停了")

    def test_a_user_stopped_automation_is_not_sent(self):
        self.notifier.look()
        self.write(codex_line("turn_aborted", "2027-01-15T08:00:10Z", turn_id="t1", reason="interrupted"))
        self.notifier.look()
        self.assertEqual(self.notifier.feed.since("all"), [])

    def test_a_quiet_decision_reaches_no_phone_but_the_island(self):
        sent = []
        notifier = make_notifier({"bark": {"server": "https://api.day.app", "key": KEY}, "ntfy": True}, sent)
        item = {"app": "codex", "id": "h9", "title": "日报对话"}  # a heartbeat turn in an ordinary conversation
        end = {"state": "done", "started": int(NOW) - 5, "ended": int(NOW), "text": "DONT_NOTIFY",
               "raw_text": "DONT_NOTIFY", "automation_id": "daily-1", "heartbeat": True, "automation": True}
        with notifier.relay.listener():
            notifier._tell(notifier.address(), item, end)
        self.assertEqual(sent, [])
        self.assertEqual(notifier.feed.since("all"), [])
        event = notifier.relay.since("all")[-1]
        self.assertTrue(event["quiet"])
        self.assertTrue(event["automation"])
        self.assertIn("没推：Codex 说这次不用提醒", notifier.public()["recent"][0]["text"])


class HeartbeatRollout(unittest.TestCase):
    BLOCK = ("<heartbeat>\n<automation_id>10-a</automation_id>\n"
             "<current_time_iso>2027-01-15T08:00:00Z</current_time_iso>\n"
             "<instructions>check the inbox</instructions>\n</heartbeat>")
    DONE = "<heartbeat>\n<decision>DONT_NOTIFY</decision>\n</heartbeat>"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "rollout.jsonl"
        self.sent, self.logged = [], []
        self.cfg = {"ntfy": True}
        self.item = {"app": "codex", "id": "h1", "title": "日报对话", "path": str(self.path)}  # a normal thread
        patches = [
            mock.patch.object(notify.chats, "CODEX_HOME", Path(self.dir.name)),
            mock.patch.object(notify.chats, "conv_path", lambda item: Path(item["path"])),
            mock.patch.object(notify.chats, "claude_sessions", lambda limit: []),
            mock.patch.object(notify.chats, "_codex_rows",
                              lambda where, args, limit: [dict(self.item)] if where == notify.CODEX_WHERE else []),
            mock.patch("deepseek_control.catalog", lambda: []),
            mock.patch.dict(notify._AUTOMATION_POLICY, clear=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.notifier = notify.Notifier(self.cfg, "家里电脑", self.logged.append, lambda: None,
                                        clock=lambda: NOW, sender=lambda *a, **k: self.sent.append((a, k)),
                                        page_url=lambda: "https://pc.example.ts.net/")
        self.write(codex_line("task_started", TS, turn_id="t1"))
        self.write(json.dumps({"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": self.BLOCK}]}}))

    def write(self, line):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def complete(self, text, kind="task_complete", **extra):
        self.write(codex_line(kind, "2027-01-15T08:00:10Z", turn_id="t1", last_agent_message=text, **extra))

    def test_a_quiet_heartbeat_is_not_sent_but_the_island_is_updated(self):
        with self.notifier.relay.listener():
            self.notifier.look()
            self.complete(self.DONE)
            self.notifier.look()
        self.assertEqual(self.notifier.feed.since("all"), [])
        done = [e for e in self.notifier.relay.since("all") if e.get("kind") == "done"][-1]
        self.assertTrue(done["automation"])
        self.assertTrue(done["quiet"])
        self.assertIn("没推：Codex 说这次不用提醒", self.notifier.public()["recent"][0]["text"])

    def test_a_heartbeat_turn_with_an_answer_is_sent_as_the_task(self):
        self.notifier.look()
        self.complete("处理完了")
        self.notifier.look()
        msg = self.notifier.feed.since("all")[-1]
        self.assertEqual(msg["message"], "Codex 定时任务 · 家里电脑 · 好了\n处理完了")
        self.assertEqual(msg["title"], "日报对话")

    def test_the_users_own_next_turn_is_not_a_heartbeat(self):
        self.notifier.look()
        self.complete(self.DONE)
        self.notifier.look()
        self.write(codex_line("task_started", "2027-01-15T08:01:00Z", turn_id="t2"))
        self.write(json.dumps({"timestamp": "2027-01-15T08:01:00Z", "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "帮我看看"}]}}))
        self.write(codex_line("task_complete", "2027-01-15T08:01:10Z", turn_id="t2", last_agent_message="看完了"))
        self.notifier.look()
        msg = self.notifier.feed.since("all")[-1]
        self.assertEqual(msg["message"], "Codex · 家里电脑 · 好了\n看完了")

    def test_off_keeps_following_but_says_nothing(self):
        self.notifier.cfg["automations"] = "off"
        with self.notifier.relay.listener():
            self.notifier.look()
            self.complete("处理完了")
            self.notifier.look()
        self.assertEqual(self.notifier.feed.since("all"), [])
        done = [e for e in self.notifier.relay.since("all") if e.get("kind") == "done"][-1]
        self.assertTrue(done["quiet"])
        self.assertTrue(done["automation"])
        self.assertIn("定时任务的通知已关掉", self.notifier.public()["recent"][0]["text"])

    def test_only_failed_pushes_a_heartbeat_error_run(self):
        self.notifier.cfg["automations"] = "failed"
        self.notifier.look()
        self.write(codex_line("error", "2027-01-15T08:00:05Z", message="boom"))
        self.complete(None)
        self.notifier.look()
        msg = self.notifier.feed.since("all")[-1]
        self.assertEqual(msg["message"].split("\n")[0], "Codex 定时任务 · 家里电脑 · 出错停了")
        self.assertEqual(msg["priority"], 4)

    def test_a_quiet_heartbeat_does_not_wait_for_an_answer(self):
        self.notifier.look()
        self.complete(None)  # a successful heartbeat with nothing to say
        self.notifier.look()
        self.assertEqual(self.notifier.feed.since("all"), [])


if __name__ == "__main__":
    unittest.main()
