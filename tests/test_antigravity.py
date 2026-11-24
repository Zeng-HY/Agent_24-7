"""Antigravity: the summaries list, the transcript reader, sending, approving, stopping, new conversations,
pictures and the shared routes.

All data is invented in a temporary folder; a fake hub on 127.0.0.1 stands in for the app's local service and
the isolation fixture in conftest.py keeps the real Antigravity folder out of every test.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import chat_history
import chat_projects
import machines
import remote
from agents import antigravity, claude as claude_agent, codex as codex_agent, deepseek as deepseek_agent, registry
from agents.base import NotFound
import antigravity_fixtures as fake

WORKSPACE = '["file:///c%3A/%E6%B5%8B%E8%AF%95/%E9%A1%B9%E7%9B%AE"]'
NEWEST = "2026-11-20 12:00:00.1234567+08:00"
OLDER = "2026-11-20 11:00:00.1234567+08:00"
OLDEST = "2026-11-20 10:00:00.1234567+08:00"


def epoch(text: str) -> int:
    return int(datetime.fromisoformat(text[:26] + text[-6:]).timestamp())


def millis(text: str) -> int:
    return int(datetime.fromisoformat(text[:26] + text[-6:]).timestamp() * 1000)


class FakeNotifier:
    """The parts of notify.Notifier an Antigravity poll touches, without a phone or a relay."""

    def __init__(self) -> None:
        self.clock = lambda: 1_800_000_000.0
        self.ended: dict = {}
        self.running: dict = {}
        self.waiting: dict = {}
        self.reported_running: set = set()
        self.told: list[dict] = []
        self.steps: list[str] = []
        self.ran: list[dict] = []

    def relay_on(self) -> bool:
        return False

    def _running(self, item, scan) -> None:
        self.running[(item["app"], item["id"])] = {"since": int(item.get("turn_started") or self.clock()),
                                                   "title": item.get("title", ""), "item": item}
        self.ran.append(scan)

    def _step(self, item, scan, on) -> None:
        self.steps.append(scan.get("action", ""))

    def _tell(self, found, item, end) -> None:
        self.told.append(end)


class FakeUploadHandler:
    """The bits of remote.Handler an upload touches, without a socket."""

    def __init__(self, codex, raw: bytes = b"", tid: str = "a", draft: bool = False, size: int | None = None):
        self.server = SimpleNamespace(codex=codex)
        self.raw = raw
        self.headers = {"Content-Length": str(len(raw) if size is None else size)}
        self.rfile = io.BytesIO(raw)
        self.sent: list[tuple[int, dict]] = []
        self.query = {"id": tid, "name": "图.png"}
        if draft:
            self.query["draft"] = "1"
        self.close_connection = False

    def _query(self) -> dict:
        return self.query

    def _json(self, obj, code: int = 200) -> None:
        self.sent.append((code, obj))


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        start = patch.object(machines, "HOME", self.home)
        start.start()
        self.addCleanup(start.stop)
        antigravity.reset()
        self.addCleanup(antigravity.reset)

    def build(self, rows=None, transcripts=None, full=None, columns=fake.COLUMNS):
        root = fake.write(self.home, rows, transcripts, full, columns)
        antigravity.reset()
        return root


class DetectTests(Base):
    def test_detect_only_looks_for_the_summaries_database(self):
        agent = registry.get("antigravity")
        self.assertFalse(agent.detect())
        fake.write(self.home, [])
        self.assertTrue(agent.detect())

    def test_the_manifest_sends_and_approves_from_the_phone(self):
        manifest = registry.get("antigravity").manifest()
        self.assertEqual((manifest["id"], manifest["order"], manifest["legacy"], manifest["min_protocol"]),
                         ("antigravity", 40, False, 2))
        self.assertEqual((manifest["name"]["zh"], manifest["name"]["en"]), ("Antigravity", "Antigravity"))
        self.assertEqual((manifest["color"], manifest["color_dark"], manifest["icon"]),
                         ("#4285F4", "#8AB4F8", {"kind": "builtin", "key": "generic"}))
        self.assertEqual(manifest["ui"], {"card_layout": "generic.v1", "waiting_text": "等待你处理"})
        self.assertEqual(manifest["sources"], {"catalog": "sqlite", "transcript": "jsonl",
                                               "control": "local-api", "live": "file-poll"})
        capabilities = manifest["capabilities"]
        self.assertTrue(capabilities["list"] and capabilities["read"] and capabilities["search"])
        self.assertEqual(capabilities["send_modes"], ["send"])
        self.assertTrue(capabilities["approve"] and capabilities["waiting"])
        self.assertTrue(capabilities["stop"] and capabilities["new"] and capabilities["attachments"])
        self.assertEqual(capabilities["statuses"], ["running", "waiting", "idle", "unknown"])
        for name in ("open", "queue", "steer", "answer", "archive", "restore",
                     "delete", "usage", "slash_commands", "skills"):
            self.assertFalse(capabilities[name], name)
        self.assertEqual(capabilities["settings"], [])
        self.assertEqual(manifest["params"]["max_images"], 5)
        self.assertEqual(manifest["params"]["max_image_bytes"], 20 << 20)


class CatalogTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.build(
            rows=[
                fake.row("a", title="测试对话 A", preview="第一个", last_modified_time=NEWEST,
                         status="CASCADE_RUN_STATUS_RUNNING", workspace_uris=WORKSPACE),
                fake.row("b", title="", preview="另一个 Test 对话的预览内容", last_modified_time=OLDER,
                         workspace_uris=""),
                fake.row("c", title="子对话", preview="子对话的内容", last_modified_time=NEWEST,
                         nesting_depth=1, parent_conversation_id="a"),
                fake.row("d", title="输掉的", preview="battle 里输掉的", last_modified_time=OLDEST,
                         battle_id="battle-1", winning_conversation_id="e"),
                fake.row("e", title="赢的", preview="battle 里赢的", last_modified_time=OLDEST,
                         battle_id="battle-1", winning_conversation_id="e"),
            ],
            transcripts={
                "a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "你好"),
                      fake.record(2, "PLANNER_RESPONSE", "MODEL", None,
                                  tool_calls=[{"name": "edit_file", "args": {"Path": "C:\\测试\\a.py"}}]),
                      fake.record(3, "GENERIC", "MODEL", "工具输出：a.py 已修改")],
            },
        )

    def test_rows_newest_first_and_children_and_lost_battles_left_out(self):
        page = antigravity.AGENT().catalog()
        self.assertEqual([row["id"] for row in page["items"]], ["a", "b", "e"])
        self.assertEqual(page["total"], 3)
        self.assertEqual({row["app"] for row in page["items"]}, {"antigravity"})

    def test_paging_keeps_a_cursor_and_a_total(self):
        agent = antigravity.AGENT()
        first = agent.catalog(limit=2)
        self.assertEqual([row["id"] for row in first["items"]], ["a", "b"])
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_cursor"], "2")
        second = agent.catalog(limit=2, cursor=first["next_cursor"])
        self.assertEqual([row["id"] for row in second["items"]], ["e"])
        self.assertFalse(second["has_more"])

    def test_catalog_entries_is_not_capped_at_a_page(self):
        """The shared list and project tree ask for every recent row with a very large limit."""
        entries = antigravity.AGENT().catalog_entries(1000000)
        self.assertEqual([row["id"] for row in entries], ["a", "b", "e"])
        self.assertNotIn("_nesting_depth", entries[0])

    def test_search_reads_title_and_preview_without_case(self):
        agent = antigravity.AGENT()
        self.assertEqual([row["id"] for row in agent.catalog(query="test")["items"]], ["b"])
        self.assertEqual([row["id"] for row in agent.catalog(query="预览")["items"]], ["b"])
        self.assertEqual(agent.catalog(query="没有这个")["items"], [])

    def test_status_filter_and_three_values(self):
        agent = antigravity.AGENT()
        self.assertEqual([row["id"] for row in agent.catalog(status="running")["items"]], ["a"])
        self.assertEqual(agent.catalog(status="unknown")["items"], [])
        rows = [fake.row("r", status="CASCADE_RUN_STATUS_RUNNING"),
                fake.row("i", status="CASCADE_RUN_STATUS_IDLE"),
                fake.row("u", status="CASCADE_RUN_STATUS_SOMETHING_NEW")]
        self.build(rows)
        self.assertEqual({row["id"]: row["status"] for row in agent.catalog()["items"]},
                         {"r": "running", "i": "idle", "u": "unknown"})

    def test_a_seven_digit_time_with_a_timezone_and_a_title_fallback(self):
        agent = antigravity.AGENT()
        rows = {row["id"]: row for row in agent.catalog()["items"]}
        self.assertEqual(rows["a"]["updated"], millis(NEWEST))
        self.assertEqual(rows["a"]["turn_started"], epoch("2026-11-20 09:59:00.0000001+08:00"))
        self.assertEqual(rows["b"]["title"], "另一个 Test 对话的预览内容")
        self.build([fake.row("x", title="", preview="")])
        self.assertEqual(agent.catalog()["items"][0]["title"], "Antigravity 对话")

    def test_project_group_decodes_the_folder_and_has_an_other_bucket(self):
        agent = antigravity.AGENT()
        rows = {row["id"]: row for row in agent.catalog()["items"]}
        self.assertEqual(rows["a"]["cwd"], "c:\\测试\\项目")
        self.assertEqual(rows["a"]["folder"], "项目")
        self.assertEqual(agent.project_group(rows["a"]), ("f:" + "c:\\测试\\项目".casefold(), "项目", ""))
        self.assertEqual(agent.project_group(rows["b"]), (chat_projects.OTHER_KEY, chat_projects.OTHER_NAME, ""))

    def test_find_knows_a_child_but_a_child_is_never_listed(self):
        agent = antigravity.AGENT()
        self.assertEqual(agent.find("c")["title"], "子对话")
        with self.assertRaises(NotFound):
            agent.find("nope")


class ErrorTests(Base):
    def test_a_corrupt_database_returns_nothing_instead_of_raising(self):
        root = self.build([])
        (root / "conversation_summaries.db").write_bytes(b"this is not a database")
        antigravity.reset()
        self.assertEqual(antigravity.AGENT().catalog()["items"], [])

    def test_a_locked_database_returns_nothing_instead_of_raising(self):
        self.build([fake.row("a")])
        with patch.object(antigravity.sqlite3, "connect",
                          side_effect=sqlite3.OperationalError("database is locked")):
            self.assertEqual(antigravity.AGENT().catalog()["items"], [])

    def test_a_missing_column_and_a_bad_row_are_read_as_empty_values(self):
        root = self.build([fake.row("a", title="只有标题")], columns=("conversation_id", "title", "status"))
        self.assertEqual(antigravity.AGENT().catalog()["items"][0]["cwd"], "")
        antigravity.reset()
        self.build([fake.row("b", workspace_uris="not json", last_modified_time="bad time",
                             status="CASCADE_RUN_STATUS_IDLE")])
        item = antigravity.AGENT().catalog()["items"][0]
        self.assertEqual((item["cwd"], item["updated"], item["status"]), ("", 0, "idle"))


class ReadTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.build(
            rows=[fake.row("a", title="测试对话 A", workspace_uris=WORKSPACE),
                  fake.row("empty", title="没有记录文件")],
            transcripts={"a": fake.real_transcript()},
            full={"a": [fake.record(13, "USER_INPUT", "USER_EXPLICIT", "完整的截断内容"),
                        fake.record(14, "PLANNER_RESPONSE", "MODEL", None, tool_calls=[
                            {"name": "finish", "args": {"result": fake.STRUCTURED_FULL}},
                        ]),
                        fake.record(16, "PLANNER_RESPONSE", "MODEL", None, tool_calls=[
                            {"name": "finish", "args": {"result": fake.PLAIN_FULL}},
                        ])]},
        )
        # One line the reader cannot parse: it is skipped, and the rest still reads.
        with (fake.data_root(self.home) / "brain" / "a" / ".system_generated" / "logs"
              / "transcript.jsonl").open("ab") as file:
            file.write(b"{not json at all\n")

    def page(self, **changes):
        return antigravity.AGENT().read("a", **changes)

    def test_each_step_type_is_shown_the_way_the_table_says(self):
        page = self.page(limit=100)
        shown = [(message["role"], message["text"]) for message in page["messages"]]
        self.assertIn(("user", "帮我看看这个文件"), shown)
        self.assertIn(("assistant", "看过了，没有问题。"), shown)
        self.assertIn(("assistant", "补充一句"), shown)
        self.assertIn(("event", "出错：被限流了"), shown)
        self.assertIn(("user", "[图片]"), shown)
        self.assertIn(("user", "完整的截断内容"), shown)
        # A structured result is one step, never JSON; a plain result is the answer and gets completed.
        self.assertIn(("tool", "finish：交回了结构化结果"), shown)
        self.assertIn(("assistant", fake.PLAIN_FULL), shown)
        self.assertNotIn(("assistant", fake.PLAIN_CUT), shown)
        self.assertNotIn("内部提示", [text for _role, text in shown])
        self.assertNotIn("检查点", [text for _role, text in shown])
        self.assertTrue(any(role == "tool" and text.startswith("read_file：C:\\测试\\a.txt")
                            for role, text in shown))
        self.assertTrue(any(role == "tool" and text == "run_command：跑登录页的测试"
                            for role, text in shown))
        self.assertTrue(any(role == "tool" and text.startswith("edit_file：C:\\测试\\b.py")
                            for role, text in shown))
        self.assertTrue(any(role == "tool" and text.startswith("edit_file：C:\\测试\\c.py")
                            for role, text in shown))
        self.assertEqual([message["role"] for message in page["messages"]].count("tool"), 5)

    def test_a_structured_finish_result_never_shows_its_json(self):
        page = self.page(limit=100)
        texts = [message["text"] for message in page["messages"]]
        self.assertFalse(any("{" in text for text in texts))
        self.assertNotIn("batch", " ".join(texts))
        self.assertNotIn(fake.STRUCTURED_CUT, texts)
        step = next(message for message in page["messages"] if message["text"] == "finish：交回了结构化结果")
        self.assertEqual(step["role"], "tool")

    def test_a_structured_finish_result_does_not_read_the_full_file(self):
        seen = []
        real = antigravity._full_records

        def spy(path, steps):
            seen.append(set(steps))
            return real(path, steps)

        with patch.object(antigravity, "_full_records", spy):
            self.page(limit=100)
        self.assertTrue(seen)
        self.assertNotIn(14, seen[0])  # the structured finish step
        self.assertIn(13, seen[0])     # the cut user message
        self.assertIn(16, seen[0])     # the cut plain finish result

    def test_a_tool_output_is_never_shown_as_an_answer(self):
        page = self.page(limit=100)
        texts = [message["text"] for message in page["messages"]]
        self.assertNotIn(fake.TOOL_OUTPUT, texts)
        self.assertFalse(any(text.startswith("工具输出") for text in texts))
        self.assertNotIn(fake.TOOL_OUTPUT, " ".join(texts))

    def test_a_picture_is_marked_and_no_file_is_offered(self):
        page = self.page(limit=100)
        picture = next(message for message in page["messages"] if message["text"] == "[图片]")
        self.assertNotIn("images", picture)
        self.assertNotIn("file", picture)

    def test_paging_by_limit_before_and_around(self):
        agent = antigravity.AGENT()
        last = agent.read("a", limit=3)
        self.assertEqual(len(last["messages"]), 3)
        self.assertTrue(last["has_more"])
        earlier = agent.read("a", limit=3, before=last["next_cursor"])
        self.assertTrue(earlier["has_newer"])
        self.assertTrue(earlier["messages"])
        self.assertFalse(last["has_newer"])
        around = agent.read("a", limit=4, around=last["messages"][1]["id"])
        self.assertTrue(around["messages"])
        missing = agent.read("a", limit=3, before="not-a-message")
        self.assertTrue(missing["reset"])

    def test_a_conversation_without_a_record_file_says_so(self):
        page = antigravity.AGENT().read("empty")
        self.assertEqual(page["messages"], [])
        self.assertIn("没找到", page["note"])

    def test_the_page_reports_the_running_step_and_times(self):
        page = self.page(limit=100)
        self.assertEqual(page["status"], "idle")
        self.assertEqual(page["total"], len(page["messages"]))
        self.assertGreater(page["size"], 0)


class SummaryStateTests(Base):
    def test_a_running_conversation_reports_its_island_step(self):
        self.build(rows=[fake.row("a", status="CASCADE_RUN_STATUS_RUNNING", last_modified_time=NEWEST)],
                   transcripts={"a": [fake.record(1, "PLANNER_RESPONSE", "MODEL", None,
                                                  tool_calls=[{"name": "run_command", "args": {"CommandLine": "pytest"}}]),
                                      fake.record(2, "GENERIC", "MODEL", "工具输出：测试通过")]})
        agent = antigravity.AGENT()
        item = agent.find("a")
        self.assertEqual(agent.summary(item)["status"], "running")
        self.assertEqual(agent.summary(item)["step"], "run")
        self.assertEqual(agent.state("a")["step"], "run")
        self.assertTrue(agent.state("a")["running"])

    def test_an_idle_conversation_has_no_step(self):
        self.build(rows=[fake.row("a", status="CASCADE_RUN_STATUS_IDLE")])
        agent = antigravity.AGENT()
        self.assertEqual(agent.summary(agent.find("a"))["step"], "")
        self.assertFalse(agent.state("a")["running"])


class NotifyTests(Base):
    def test_an_idle_conversation_at_startup_is_not_announced(self):
        self.build(rows=[fake.row("a", status="CASCADE_RUN_STATUS_IDLE")])
        agent = antigravity.AGENT()
        notifier = FakeNotifier()
        recent, _full = agent.notify_conversations(10)
        agent.notify_poll(notifier, None, recent[0])
        self.assertEqual(notifier.told, [])

    def test_a_child_and_a_lost_battle_are_not_watched(self):
        self.build(rows=[fake.row("a"), fake.row("c", nesting_depth=1, parent_conversation_id="a"),
                         fake.row("d", battle_id="b", winning_conversation_id="e")])
        recent, full = antigravity.AGENT().notify_conversations(10)
        self.assertEqual([item["id"] for item in recent], ["a"])
        self.assertEqual([item["id"] for item in full], ["a"])

    def test_a_running_turn_then_idle_announces_done_once(self):
        root = self.build(rows=[fake.row("a", status="CASCADE_RUN_STATUS_RUNNING", last_modified_time=NEWEST)])
        agent = antigravity.AGENT()
        notifier = FakeNotifier()
        item = agent.notify_conversations(10)[0][0]
        agent.notify_poll(notifier, None, item)
        self.assertEqual(notifier.ran[0]["action"], "")
        self.assertIn(("antigravity", "a"), notifier.running)
        fake.write(self.home, [fake.row("a", status="CASCADE_RUN_STATUS_IDLE", last_modified_time=OLDER)])
        antigravity.reset()
        item = agent.notify_conversations(10)[0][0]
        agent.notify_poll(notifier, None, item)
        self.assertEqual([end["state"] for end in notifier.told], ["done"])
        self.assertEqual(notifier.told[0]["started"], epoch("2026-11-20 09:59:00.0000001+08:00"))
        agent.notify_poll(notifier, None, item)
        self.assertEqual(len(notifier.told), 1)

    def test_a_turn_whose_last_step_is_an_error_says_failed(self):
        self.build(rows=[fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")],
                   transcripts={"a": [fake.record(1, "PLANNER_RESPONSE", "MODEL", "开始"),
                                      fake.record(2, "ERROR_MESSAGE", "SYSTEM", None, error="出错")]})
        agent = antigravity.AGENT()
        notifier = FakeNotifier()
        agent.notify_poll(notifier, None, agent.notify_conversations(10)[0][0])
        fake.write(self.home, [fake.row("a", status="CASCADE_RUN_STATUS_IDLE")],
                   transcripts={"a": [fake.record(1, "PLANNER_RESPONSE", "MODEL", "开始"),
                                      fake.record(2, "ERROR_MESSAGE", "SYSTEM", None, error="出错")]})
        antigravity.reset()
        agent.notify_poll(notifier, None, agent.notify_conversations(10)[0][0])
        self.assertEqual([end["state"] for end in notifier.told], ["failed"])

    def test_a_running_turn_reports_the_last_tool_as_the_island_step(self):
        self.build(rows=[fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")],
                   transcripts={"a": [fake.record(1, "PLANNER_RESPONSE", "MODEL", None,
                                                  tool_calls=[{"name": "read_file", "args": {"Path": "a"}}]),
                                      fake.record(2, "PLANNER_RESPONSE", "MODEL", None,
                                                  tool_calls=[{"name": "edit_file", "args": {"Path": "b"}}])]})
        agent = antigravity.AGENT()
        notifier = FakeNotifier()
        agent.notify_poll(notifier, None, agent.notify_conversations(10)[0][0])
        self.assertEqual(notifier.steps, ["edit"])
        self.assertEqual(notifier.ran[0]["action"], "edit")


class RouteTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.build(rows=[fake.row("a", title="测试对话 A", status="CASCADE_RUN_STATUS_IDLE")],
                   transcripts={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "你好"),
                                      fake.record(2, "PLANNER_RESPONSE", "MODEL", "你也好")]})

    def handler(self, path: str, apps: list[str], protocol: int | None = None):
        handler = object.__new__(remote.Handler)
        sent = []
        handler.path = path
        handler.headers = {"X-Teleply-Protocol": str(protocol)} if protocol else {}
        handler.close_connection = False
        handler._responded = False
        handler.server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": list(apps), "voice": False},
            cfg={"token": "secret"},
            log=SimpleNamespace(write=lambda _text: None),
            tasks=SimpleNamespace(apply_status=lambda items: items),
            history=chat_history.History(),
        )
        handler._send = lambda code, body, ctype, extra=None: sent.append((code, body))
        return handler, sent

    def test_protocol_two_lists_reads_and_refuses_send(self):
        apps = ["codex", "claude", "deepseek", "antigravity"]
        with patch.object(codex_agent.CodexAgent, "catalog_entries", return_value=[]), \
             patch.object(claude_agent.ClaudeAgent, "catalog_entries", return_value=[]), \
             patch.object(deepseek_agent.DeepSeekAgent, "catalog_entries", return_value=[]):
            handler, sent = self.handler("/api/agents?t=secret", apps, protocol=2)
            handler.do_GET()
            self.assertEqual(sent[0][0], 200)
            self.assertIn("antigravity", [agent["id"] for agent in json.loads(sent[0][1])["agents"]])

            handler, sent = self.handler("/api/chats?app=all&t=secret", apps, protocol=2)
            handler.do_GET()
            body = json.loads(sent[0][1])
            self.assertEqual([row["app"] for row in body["items"]], ["antigravity"])

            handler, sent = self.handler("/api/chat?app=antigravity&id=a&t=secret", apps, protocol=2)
            handler.do_GET()
            body = json.loads(sent[0][1])
            self.assertEqual([message["text"] for message in body["messages"]], ["你好", "你也好"])

            # The list's search looks in the preview too (the shared route asks each assistant whether it should).
            handler, sent = self.handler("/api/chats?app=all&query=%E6%B5%8B%E8%AF%95%E5%86%85%E5%AE%B9&t=secret",
                                         apps, protocol=2)
            handler.do_GET()
            self.assertEqual([row["app"] for row in json.loads(sent[0][1])["items"]], ["antigravity"])

        handler, sent = self.handler("/api/agents/antigravity/send?t=secret", apps, protocol=2)
        handler.rfile = io.BytesIO(json.dumps({"id": "a", "text": "hi"}).encode())
        handler.headers["Content-Length"] = str(len(handler.rfile.getvalue()))
        handler.do_POST()
        self.assertEqual(sent[0][0], 409)
        self.assertIn("没开", json.loads(sent[0][1])["error"])

        handler, sent = self.handler("/api/agents/antigravity/answer?t=secret", apps, protocol=2)
        handler.rfile = io.BytesIO(json.dumps({"id": "a", "question_id": "traj:1",
                                               "answers": {"decision": ["允许一次"]}}).encode())
        handler.headers["Content-Length"] = str(len(handler.rfile.getvalue()))
        handler.do_POST()
        self.assertEqual(sent[0][0], 409)
        self.assertIn("没开", json.loads(sent[0][1])["error"])

    def test_protocol_two_sends_and_answers_through_the_unified_routes(self):
        apps = ["codex", "claude", "deepseek", "antigravity"]
        with fake.FakeHub(self.home, steps=[fake.waiting_step()]) as hub:
            antigravity.reset()
            handler, sent = self.handler("/api/agents/antigravity/send?t=secret", apps, protocol=2)
            handler.rfile = io.BytesIO(json.dumps({"id": "a", "text": "从手机发的"}).encode())
            handler.headers["Content-Length"] = str(len(handler.rfile.getvalue()))
            handler.do_POST()
            self.assertEqual(sent[0][0], 200)
            self.assertEqual(json.loads(sent[0][1])["text"], "已交给 Antigravity")
            self.assertEqual(hub.calls("SendUserCascadeMessage")[-1]["body"],
                             {"cascadeId": "a", "items": [{"text": "从手机发的"}]})

            handler, sent = self.handler("/api/agents/antigravity/answer?t=secret", apps, protocol=2)
            handler.rfile = io.BytesIO(json.dumps(
                {"id": "a", "question_id": "traj-1:3", "answers": {"decision": ["拒绝"]}}).encode())
            handler.headers["Content-Length"] = str(len(handler.rfile.getvalue()))
            handler.do_POST()
            self.assertEqual(sent[0][0], 200)
            self.assertEqual(json.loads(sent[0][1]), {"ok": True, "accepted": True, "text": "已拒绝"})

    def test_protocol_one_never_sees_the_new_assistant(self):
        apps = ["codex", "claude", "deepseek", "antigravity"]
        with patch.object(codex_agent.CodexAgent, "catalog_entries", return_value=[]), \
             patch.object(claude_agent.ClaudeAgent, "catalog_entries", return_value=[]), \
             patch.object(deepseek_agent.DeepSeekAgent, "catalog_entries", return_value=[]):
            handler, sent = self.handler("/api/chats?app=all&t=secret", apps)
            handler.do_GET()
            self.assertEqual(json.loads(sent[0][1])["items"], [])
        handler, sent = self.handler("/api/agents/antigravity/state?id=a&t=secret", apps)
        handler.do_GET()
        self.assertEqual(sent[0][0], 404)


class ControlBase(Base):
    """Fake data, a fake local service and a fake agentapi: never the real Antigravity."""

    def hub(self, steps=None, token=fake.TOKEN, clear=True):
        found = fake.FakeHub(self.home, token=token, steps=steps)
        found.__enter__()
        self.addCleanup(found.__exit__, None, None, None)
        if clear:
            antigravity.reset()
        return found

    def agentapi(self, **changes):
        runner = fake.FakeAgentapi(**changes)
        patcher = patch.object(antigravity, "_run_language_server", runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        return runner

    def transcript_path(self, conv_id: str = "a") -> Path:
        return (fake.data_root(self.home) / "brain" / conv_id / ".system_generated" / "logs"
                / "transcript.jsonl")

    def append_user_input(self, text: str, conv_id: str = "a", step: int = 9) -> None:
        with self.transcript_path(conv_id).open("a", encoding="utf-8") as file:
            file.write(json.dumps(fake.record(step, "USER_INPUT", "USER_EXPLICIT", text),
                                  ensure_ascii=False) + "\n")


class CapabilitiesTests(ControlBase):
    def test_no_running_antigravity_says_so_for_sending_approving_and_stopping(self):
        self.build([fake.row("a")])
        now = antigravity.AGENT().capabilities_now(None, "a")
        self.assertEqual(now["capabilities"], {"send_modes": [], "approve": False, "stop": False})
        self.assertEqual(now["notes"], {"send": antigravity.NOT_OPEN, "approve": antigravity.NOT_OPEN,
                                        "stop": antigravity.NOT_OPEN})

    def test_open_but_idle_can_send_and_approve_but_not_stop(self):
        self.build([fake.row("a")])
        self.hub()
        now = antigravity.AGENT().capabilities_now(None, "a")
        self.assertEqual(now, {"capabilities": {"stop": False}, "notes": {"stop": antigravity.NOT_RUNNING}})

    def test_open_and_running_can_send_and_stop(self):
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")])
        self.hub()
        self.assertIsNone(antigravity.AGENT().capabilities_now(None, "a"))

    def test_a_waiting_conversation_can_still_send_and_stop(self):
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")])
        self.hub([fake.waiting_step()])
        self.assertIsNone(antigravity.AGENT().capabilities_now(None, "a"))

    def test_the_check_is_kept_two_seconds(self):
        self.build([fake.row("a")])
        clock = {"t": 1000.0}
        with patch.object(antigravity, "_now", lambda: clock["t"]):
            first = antigravity.AGENT().capabilities_now(None, "a")
            self.assertEqual(first["capabilities"]["stop"], False)
            self.hub(clear=False)  # the app appears, but the answer is kept for two seconds
            self.assertEqual(antigravity.AGENT().capabilities_now(None, "a")["capabilities"]["stop"], False)
            clock["t"] += 2.1
            self.assertEqual(antigravity.AGENT().capabilities_now(None, "a")["notes"]["stop"],
                             antigravity.NOT_RUNNING)


class SendTests(ControlBase):
    def setUp(self) -> None:
        super().setUp()
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_IDLE")],
                   transcripts={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "旧消息")]})

    def test_an_idle_conversation_takes_the_message_through_the_app(self):
        hub = self.hub()
        result = antigravity.AGENT().send({"id": "a", "text": "  帮我看看  ", "request_id": "r-1"})
        self.assertTrue(result["ok"] and result["accepted"])
        self.assertEqual(result["text"], "已交给 Antigravity")
        self.assertEqual(result["request_id"], "r-1")
        self.assertEqual(len(hub.calls("UpdateConversationAnnotations")), 1)
        annotations = hub.calls("UpdateConversationAnnotations")[0]["body"]
        self.assertEqual(annotations["cascadeId"], "a")
        self.assertEqual(annotations["annotations"], {"permissionPreset": "AGENT_PERMISSION_PRESET_TURBO"})
        self.assertIs(annotations["mergeAnnotations"], True)
        body = hub.calls("SendUserCascadeMessage")[-1]["body"]
        self.assertEqual(body, {"cascadeId": "a", "items": [{"text": "  帮我看看  "}]})
        self.assertNotIn("conversationId", body)
        self.assertNotIn("deliveryStrategy", body)
        self.assertNotIn(fake.TOKEN, json.dumps(result, ensure_ascii=False))

    def test_full_auto_is_turned_on_before_the_message(self):
        hub = self.hub()
        antigravity.AGENT().send({"id": "a", "text": "在吗"})
        order = [row["method"] for row in hub.requests
                 if row["method"] in ("UpdateConversationAnnotations", "SendUserCascadeMessage")]
        self.assertEqual(order, ["UpdateConversationAnnotations", "SendUserCascadeMessage"])

    def test_an_already_full_auto_conversation_is_not_set_again(self):
        hub = self.hub()
        annotations = fake.data_root(self.home) / "annotations"
        annotations.mkdir(parents=True)
        (annotations / "a.pbtxt").write_text("permission_preset:AGENT_PERMISSION_PRESET_TURBO", encoding="utf-8")
        antigravity.AGENT().send({"id": "a", "text": "在吗"})
        self.assertEqual(hub.calls("UpdateConversationAnnotations"), [])
        self.assertEqual(len(hub.calls("SendUserCascadeMessage")), 1)

    def test_a_running_conversation_takes_the_message_when_idle(self):
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")])
        hub = self.hub()
        result = antigravity.AGENT().send({"id": "a", "text": "在吗"})
        self.assertEqual(result["text"], antigravity.QUEUED_SEND)
        self.assertEqual(result["delivery_state"], "queued")
        body = hub.calls("SendUserCascadeMessage")[-1]["body"]
        self.assertEqual(body["deliveryStrategy"], "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE")
        self.assertEqual(body["items"], [{"text": "在吗"}])

    def test_media_rides_with_the_message(self):
        hub = self.hub()
        media = [{"mimeType": "image/png", "inlineData": "AAAA"}]
        antigravity.AGENT().send({"id": "a", "text": "看图", "media": media})
        self.assertEqual(hub.calls("SendUserCascadeMessage")[-1]["body"]["media"], media)

    def test_no_antigravity_is_refused(self):
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().send({"id": "a", "text": "在吗"})
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("没开", str(caught.exception))

    def test_empty_and_over_long_text_are_refused(self):
        self.hub()
        for text in ("", "   \n  "):
            with self.assertRaises(antigravity.ControlError) as caught:
                antigravity.AGENT().send({"id": "a", "text": text})
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().send({"id": "a", "text": "字" * 20001})
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("20,000", str(caught.exception))

    def test_a_send_that_the_app_refuses_is_502_and_never_carries_the_token(self):
        hub = self.hub()
        hub.fail = "SendUserCascadeMessage"
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().send({"id": "a", "text": "在吗"})
        self.assertEqual(caught.exception.status, 502)
        self.assertIn("没接受", str(caught.exception))
        self.assertNotIn(fake.TOKEN, str(caught.exception))

    def test_a_receipt_is_confirmed_when_a_new_user_input_appears(self):
        self.hub()
        agent = antigravity.AGENT()
        agent.send({"id": "a", "text": "帮我看看这个文件"})
        self.assertFalse(agent.check("a", 0, "帮我看看这个文件")["delivered"])
        self.append_user_input("帮我看看这个文件，谢谢")
        self.assertTrue(agent.check("a", 0, "帮我看看这个文件")["delivered"])
        self.assertFalse(agent.check("a", 0, "另一句话")["delivered"])


class StopTests(ControlBase):
    def test_a_running_conversation_can_be_stopped(self):
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")])
        hub = self.hub()
        result = antigravity.AGENT().stop({"id": "a"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "已让 Antigravity 停下")
        body = hub.calls("CancelCascadeInvocation")[-1]["body"]
        self.assertEqual(body, {"cascadeId": "a", "killBackgroundTasks": True})

    def test_a_waiting_conversation_can_be_stopped(self):
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")])
        hub = self.hub([fake.waiting_step()])
        antigravity.AGENT().state("a")
        antigravity.AGENT().stop({"id": "a"})
        self.assertEqual(len(hub.calls("CancelCascadeInvocation")), 1)

    def test_an_idle_conversation_cannot_be_stopped(self):
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_IDLE")])
        self.hub()
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().stop({"id": "a"})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(str(caught.exception), antigravity.NOT_RUNNING)

    def test_no_antigravity_cannot_be_stopped(self):
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING")])
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().stop({"id": "a"})
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("没开", str(caught.exception))



class ApprovalTests(ControlBase):
    def setUp(self) -> None:
        super().setUp()
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING", title="测试对话 A")],
                   transcripts={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "跑一下测试")]})

    def test_a_waiting_step_becomes_a_generic_approval_card(self):
        self.hub([fake.waiting_step()])
        state = antigravity.AGENT().state("a")
        self.assertEqual(state["status"], "waiting")
        self.assertTrue(state["running"])
        card = state["questions"][0]
        self.assertEqual((card["id"], card["kind"], card["status"]), ("traj-1:3", "approval", "pending"))
        self.assertEqual(card["title"], "Antigravity 想运行命令")
        self.assertEqual(card["detail"], "npm test")
        self.assertEqual(card["expires_at"], 0)
        question = card["questions"][0]
        self.assertEqual((question["id"], question["isMultiple"], question["isOther"]), ("decision", False, False))
        self.assertEqual([option["label"] for option in question["options"]],
                         ["允许一次", "本对话里这条都允许", "拒绝"])

    def test_a_non_command_step_has_its_own_words(self):
        self.hub([fake.waiting_step(action="read_file", target="C:\\测试\\说明.txt")])
        card = antigravity.AGENT().state("a")["questions"][0]
        self.assertEqual(card["title"], "Antigravity 想读文件")
        self.assertEqual(card["questions"][0]["question"], "允许读取这个文件吗？")

    def test_an_unknown_action_still_asks(self):
        self.hub([fake.waiting_step(action="future_thing")])
        card = antigravity.AGENT().state("a")["questions"][0]
        self.assertEqual(card["title"], "Antigravity 等你批准")
        self.assertEqual(card["questions"][0]["question"], "允许这一步吗？")

    def test_a_very_long_target_is_cut_at_four_thousand(self):
        self.hub([fake.waiting_step(target="x" * 5000)])
        detail = antigravity.AGENT().state("a")["questions"][0]["detail"]
        self.assertLessEqual(len(detail), 4000)
        self.assertTrue(detail.endswith("…"))

    def test_the_three_answers_send_the_documented_request(self):
        expected = {
            "允许一次": (True, "PERMISSION_SCOPE_ONCE", "已允许"),
            "本对话里这条都允许": (True, "PERMISSION_SCOPE_CONVERSATION", "已允许（本对话里这条都允许）"),
            "拒绝": (False, "PERMISSION_SCOPE_ONCE", "已拒绝"),
        }
        hub = self.hub([fake.waiting_step()])
        agent = antigravity.AGENT()
        for label, (allow, scope, text) in expected.items():
            hub.steps = [fake.waiting_step()]
            antigravity._forget_waiting("a")
            result = agent.answer({"id": "a", "question_id": "traj-1:3",
                                   "answers": {"decision": [label]}})
            self.assertEqual(result, {"ok": True, "accepted": True, "text": text})
            body = hub.calls("HandleCascadeUserInteraction")[-1]["body"]
            self.assertEqual(body["cascadeId"], "a")
            self.assertNotIn("conversationId", body)
            self.assertEqual(body["interaction"], {
                "trajectoryId": "traj-1", "stepIndex": 3,
                "permission": {"allow": allow, "scope": scope}})

    def test_a_card_that_is_gone_is_409(self):
        hub = self.hub([fake.waiting_step()])
        antigravity.AGENT().state("a")
        hub.steps = []
        antigravity._forget_waiting("a")
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().answer({"id": "a", "question_id": "traj-1:3",
                                        "answers": {"decision": ["允许一次"]}})
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("已经处理过", str(caught.exception))

    def test_an_unknown_option_is_400(self):
        self.hub([fake.waiting_step()])
        for answers in ({"decision": ["也许"]}, {"decision": []}, {}, {"other": ["允许一次"]}):
            with self.assertRaises(antigravity.ControlError) as caught:
                antigravity.AGENT().answer({"id": "a", "question_id": "traj-1:3", "answers": answers})
            self.assertEqual(caught.exception.status, 400)
            self.assertIn("选项不存在", str(caught.exception))

    def test_no_antigravity_cannot_answer(self):
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().answer({"id": "a", "question_id": "traj-1:3",
                                        "answers": {"decision": ["允许一次"]}})
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("没开", str(caught.exception))


class WaitingNoticeTests(ControlBase):
    def setUp(self) -> None:
        super().setUp()
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING", title="测试对话 A")],
                   transcripts={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "跑一下测试")]})

    def test_the_same_card_is_told_once_then_the_turn_is_running_again(self):
        hub = self.hub([fake.waiting_step()])
        agent = antigravity.AGENT()
        notifier = FakeNotifier()
        item = agent.notify_conversations(10)[0][0]
        agent.notify_poll(notifier, None, item)
        self.assertIn(("antigravity", "a"), notifier.waiting)
        self.assertEqual([end.get("asks") for end in notifier.told], [True])
        agent.notify_poll(notifier, None, item)
        self.assertEqual(len(notifier.told), 1)

        hub.steps = []
        antigravity._forget_waiting("a")
        agent.notify_poll(notifier, None, item)
        self.assertNotIn(("antigravity", "a"), notifier.waiting)
        self.assertIn(("antigravity", "a"), notifier.running)
        self.assertEqual(len(notifier.told), 1)

    def test_a_finished_turn_after_waiting_still_says_done(self):
        hub = self.hub([fake.waiting_step()])
        agent = antigravity.AGENT()
        notifier = FakeNotifier()
        agent.notify_poll(notifier, None, agent.notify_conversations(10)[0][0])
        hub.steps = []
        antigravity._forget_waiting("a")
        fake.write(self.home, [fake.row("a", status="CASCADE_RUN_STATUS_IDLE")],
                   transcripts={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "跑一下测试")]})
        antigravity.reset()
        agent.notify_poll(notifier, None, agent.notify_conversations(10)[0][0])
        self.assertEqual([end["state"] for end in notifier.told], ["done", "done"])


class TokenLeakTests(ControlBase):
    def test_the_token_never_appears_in_results_errors_or_logs(self):
        secret = "secret-" + fake.TOKEN
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_RUNNING"),
                    fake.row("b", status="CASCADE_RUN_STATUS_IDLE")],
                   transcripts={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "跑一下测试")],
                                "b": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "旧消息")]})
        hub = self.hub([fake.waiting_step()], token=secret)
        agent = antigravity.AGENT()
        logs: list[str] = []
        agent.on_server_start({}, [], logs.append)
        self.addCleanup(lambda: antigravity._LOG_WRITER.__setitem__(0, None))

        state_text = json.dumps(agent.state("a"), ensure_ascii=False)
        self.assertNotIn(secret, state_text)

        hub.steps = [fake.waiting_step()]
        antigravity._forget_waiting("a")
        answer_text = json.dumps(agent.answer({"id": "a", "question_id": "traj-1:3",
                                               "answers": {"decision": ["拒绝"]}}), ensure_ascii=False)
        self.assertNotIn(secret, answer_text)

        hub.fail = "GetCascadeTrajectorySteps"
        antigravity._forget_waiting("a")
        agent.state("a")
        hub.fail = "HandleCascadeUserInteraction"
        hub.steps = [fake.waiting_step()]
        antigravity._forget_waiting("a")
        with self.assertRaises(antigravity.ControlError) as caught:
            agent.answer({"id": "a", "question_id": "traj-1:3", "answers": {"decision": ["允许一次"]}})
        self.assertNotIn(secret, str(caught.exception))

        hub.fail = "SendUserCascadeMessage"
        with self.assertRaises(antigravity.ControlError) as caught:
            agent.send({"id": "b", "text": "在吗"})
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, "\n".join(logs))


class DisplayTextTests(Base):
    def test_a_user_request_shows_only_the_words_between_the_tags(self):
        self.build(rows=[fake.row("a")], transcripts={"a": [
            fake.record(1, "USER_INPUT", "USER_EXPLICIT",
                        "<USER_REQUEST>\n帮我看看登录页\n</USER_REQUEST>\n"
                        "<ADDITIONAL_METADATA>\n时间：今天\n</ADDITIONAL_METADATA>"),
            fake.record(2, "USER_INPUT", "USER_EXPLICIT", "没有标签的旧格式"),
        ]})
        texts = [message["text"] for message in antigravity.AGENT().read("a", limit=100)["messages"]]
        self.assertIn("帮我看看登录页", texts)
        self.assertIn("没有标签的旧格式", texts)
        joined = " ".join(texts)
        self.assertNotIn("<USER_REQUEST>", joined)
        self.assertNotIn("ADDITIONAL_METADATA", joined)
        self.assertNotIn("时间：今天", joined)

    def test_an_old_agentapi_system_message_is_shown_as_the_user(self):
        self.build(rows=[fake.row("a")], transcripts={"a": [
            fake.record(1, "SYSTEM_MESSAGE", "SYSTEM",
                        "The following is a <SYSTEM_MESSAGE> not actually sent by the user.\n"
                        "[Message] timestamp=2026-11-24T10:00:00Z sender=system priority=MESSAGE_PRIORITY_HIGH "
                        "content=帮我看看这个文件</SYSTEM_MESSAGE>"),
            fake.record(2, "SYSTEM_MESSAGE", "SYSTEM",
                        "[Message] timestamp=2026-11-24T10:01:00Z sender=abc/task-9 priority=HIGH "
                        "content=后台命令做完了</SYSTEM_MESSAGE>"),
        ]})
        messages = antigravity.AGENT().read("a", limit=100)["messages"]
        self.assertEqual([(message["role"], message["text"]) for message in messages],
                         [("user", "帮我看看这个文件")])

    def test_a_cut_user_request_is_completed_then_stripped(self):
        self.build(
            rows=[fake.row("a")],
            transcripts={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "<USER_REQUEST>短的",
                                           truncated_fields=["content"])]},
            full={"a": [fake.record(1, "USER_INPUT", "USER_EXPLICIT",
                                    "<USER_REQUEST>完整的原话</USER_REQUEST>\n"
                                    "<ADDITIONAL_METADATA>时间</ADDITIONAL_METADATA>")]},
        )
        texts = [message["text"] for message in antigravity.AGENT().read("a", limit=100)["messages"]]
        self.assertEqual(texts, ["完整的原话"])

    def test_the_list_search_and_preview_use_the_stripped_words(self):
        self.build([fake.row("a", preview="<USER_REQUEST>找登录页</USER_REQUEST>"
                                        "<ADDITIONAL_METADATA>时间</ADDITIONAL_METADATA>")])
        agent = antigravity.AGENT()
        self.assertEqual([row["id"] for row in agent.catalog(query="登录页")["items"]], ["a"])
        self.assertEqual(agent.catalog(query="ADDITIONAL")["items"], [])
        self.assertEqual(agent.catalog()["items"][0]["preview"], "找登录页")


class WarmUpDisplayTests(Base):
    def test_the_first_warm_up_pair_is_hidden(self):
        self.build(rows=[fake.row("a")], transcripts={"a": [
            fake.record(1, "USER_INPUT", "USER_EXPLICIT", antigravity.WARM_UP),
            fake.record(2, "PLANNER_RESPONSE", "MODEL", "好的。"),
            fake.record(3, "USER_INPUT", "USER_EXPLICIT", "真正的话"),
            fake.record(4, "PLANNER_RESPONSE", "MODEL", "回答"),
        ]})
        texts = [message["text"] for message in antigravity.AGENT().read("a", limit=100)["messages"]]
        self.assertEqual(texts, ["真正的话", "回答"])

    def test_the_same_words_later_are_still_shown(self):
        self.build(rows=[fake.row("a")], transcripts={"a": [
            fake.record(1, "USER_INPUT", "USER_EXPLICIT", "第一句"),
            fake.record(2, "PLANNER_RESPONSE", "MODEL", "回答"),
            fake.record(3, "USER_INPUT", "USER_EXPLICIT", antigravity.WARM_UP),
        ]})
        texts = [message["text"] for message in antigravity.AGENT().read("a", limit=100)["messages"]]
        self.assertEqual(texts, ["第一句", "回答", antigravity.WARM_UP])


class NewConversationTests(ControlBase):
    def setUp(self) -> None:
        super().setUp()
        self.personal = self.home / "Personal"
        self.work = self.home / "Work"
        self.personal.mkdir()
        self.work.mkdir()
        self.projects = self.home / ".gemini" / "config" / "projects"
        self.projects.mkdir(parents=True)
        (self.projects / "personal.json").write_text(json.dumps({
            "id": "proj-personal", "name": "Personal",
            "projectResources": {"resources": [{"folderUri": self.personal.as_uri()}]}}), encoding="utf-8")
        (self.projects / "work.json").write_text(json.dumps({
            "id": "proj-work", "name": "Work",
            "projectResources": {"resources": [{"folderUri": self.work.as_uri()}]}}), encoding="utf-8")

    def test_the_new_panel_lists_projects_with_personal_first(self):
        agent = antigravity.AGENT()
        folders = agent.new_own_folders(None)
        self.assertEqual([(Path(path).name, name, label) for path, name, label in folders],
                         [("Personal", "Antigravity 项目", "Personal"), ("Work", "Antigravity 项目", "Work")])
        options = agent.new_options(None)
        self.assertEqual(options["models"], [])
        self.assertIn(antigravity.MODEL, options["note"])
        self.assertEqual(options["default_project"], "proj-personal")
        self.assertEqual([project["name"] for project in options["projects"]], ["Personal", "Work"])

    def test_create_sends_the_warm_up_waits_turns_on_full_auto_then_sends_the_words(self):
        self.build([fake.row("new-1", status="CASCADE_RUN_STATUS_IDLE")])
        hub = self.hub()
        runner = self.agentapi(stdout=json.dumps(
            {"response": {"newConversation": {"conversationId": "new-1"}}}))
        result = antigravity.AGENT().create({
            "request_id": "req-1", "text": "帮我看登录页的测试", "folder": str(self.personal)})
        self.assertEqual((result["state"], result["id"], result["title"]),
                         ("accepted", "new-1", "帮我看登录页的测试"))
        call = runner.calls[0]
        self.assertEqual(call["args"], ["new-conversation", f"--model={antigravity.MODEL}",
                                        "--title=帮我看登录页的测试", antigravity.WARM_UP])
        self.assertEqual(call["env"]["ANTIGRAVITY_PROJECT_ID"], "proj-personal")
        order = [row["method"] for row in hub.requests
                 if row["method"] in ("UpdateConversationAnnotations", "SendUserCascadeMessage")]
        self.assertEqual(order, ["UpdateConversationAnnotations", "SendUserCascadeMessage"])
        self.assertEqual(hub.calls("SendUserCascadeMessage")[-1]["body"]["items"],
                         [{"text": "帮我看登录页的测试"}])
        self.assertEqual(antigravity.AGENT().create_status("req-1")["id"], "new-1")

    def test_without_a_folder_the_personal_project_is_used(self):
        self.build([fake.row("new-1", status="CASCADE_RUN_STATUS_IDLE")])
        self.hub()
        runner = self.agentapi(stdout=json.dumps(
            {"response": {"newConversation": {"conversationId": "new-1"}}}))
        antigravity.AGENT().create({"text": "你好"})
        self.assertEqual(runner.calls[0]["env"]["ANTIGRAVITY_PROJECT_ID"], "proj-personal")

    def test_a_warm_up_that_never_finishes_in_time_is_an_error(self):
        self.build([fake.row("new-1", status="CASCADE_RUN_STATUS_RUNNING")])
        self.hub()
        self.agentapi(stdout=json.dumps({"response": {"newConversation": {"conversationId": "new-1"}}}))
        with patch.object(antigravity, "NEW_WAIT_SECONDS", 0.0):
            with self.assertRaises(antigravity.ControlError) as caught:
                antigravity.AGENT().create({"text": "你好", "folder": str(self.personal)})
        self.assertEqual(caught.exception.status, 502)
        self.assertIn("没有空闲", str(caught.exception))

    def test_a_folder_that_is_not_a_project_is_refused(self):
        self.build([fake.row("new-1", status="CASCADE_RUN_STATUS_IDLE")])
        self.hub()
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().create({"text": "你好", "folder": str(self.home / "别处")})
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("不属于", str(caught.exception))

    def test_no_project_cannot_make_a_conversation(self):
        self.build([fake.row("new-1", status="CASCADE_RUN_STATUS_IDLE")])
        self.hub()
        with patch.object(antigravity, "_projects", lambda: []):
            with self.assertRaises(antigravity.ControlError) as caught:
                antigravity.AGENT().create({"text": "你好", "folder": str(self.personal)})
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("没有 Antigravity 项目", str(caught.exception))

    def test_a_new_conversation_takes_no_pictures(self):
        self.build([fake.row("new-1", status="CASCADE_RUN_STATUS_IDLE")])
        with self.assertRaises(antigravity.ControlError) as caught:
            antigravity.AGENT().create({"text": "你好", "attachments": ["a" * 32]})
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("不支持带图片", str(caught.exception))


class PictureTests(ControlBase):
    def setUp(self) -> None:
        super().setUp()
        self.build([fake.row("a", status="CASCADE_RUN_STATUS_IDLE")])
        self.app_hub = self.hub()
        self.codex = fake.FakeAttachments(self.home / "attachments")
        self.handler = SimpleNamespace(server=SimpleNamespace(codex=self.codex), sent=[])
        self.handler._json = lambda obj, status=200: self.handler.sent.append((status, obj))

    def store(self, raw: bytes, name: str = "图.png") -> dict:
        return antigravity.AGENT()._upload_for_chat(self.handler, "a", name, raw)

    def test_an_oversized_upload_is_400(self):
        handler = FakeUploadHandler(self.codex, raw=b"", size=antigravity.MAX_PICTURE_BYTES + 1)
        antigravity.AGENT().http_upload(handler)
        self.assertEqual(handler.sent[-1][0], 400)
        self.assertIn("20 MB", handler.sent[-1][1]["error"])
        self.assertTrue(handler.close_connection)

    def test_a_normal_upload_goes_through_the_unified_address(self):
        raw = fake.picture("PNG", 4, 6)
        handler = FakeUploadHandler(self.codex, raw=raw)
        antigravity.AGENT().http_upload(handler)
        self.assertEqual(handler.sent[-1][0], 200)
        self.assertEqual((handler.sent[-1][1]["width"], handler.sent[-1][1]["height"]), (4, 6))

    def test_a_good_png_and_jpeg_are_stored_as_png(self):
        for fmt in ("PNG", "JPEG"):
            with self.subTest(fmt=fmt):
                meta = self.store(fake.picture(fmt, 5, 7), "图." + fmt.lower())
                stored = (self.codex.data_root / meta["id"] / "image.png").read_bytes()
                self.assertTrue(stored.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual((meta["width"], meta["height"]), (5, 7))

    def test_a_bad_picture_is_refused_before_it_is_stored(self):
        for raw in (b"", b"not a picture at all", b"\x89PNG\r\n\x1a\nbroken"):
            with self.subTest(raw=raw[:12]):
                with self.assertRaises(antigravity.ControlError) as caught:
                    self.store(raw, "坏图.png")
                self.assertEqual(caught.exception.status, 400)
                self.assertIn(antigravity.BAD_PICTURE, str(caught.exception))
        self.assertEqual(self.codex.metas, {})

    def test_a_picture_must_be_within_the_side_and_size_limits(self):
        with self.assertRaises(antigravity.ControlError):
            self.store(fake.picture("PNG", 8001, 2))
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (antigravity.MAX_PICTURE_BYTES + 1)
        with self.assertRaises(antigravity.ControlError) as caught:
            self.store(big, "太大.png")
        self.assertIn("20 MB", str(caught.exception))

    def test_a_picture_message_sends_inline_png_data(self):
        first = self.store(fake.picture("PNG", 3, 4))
        second = self.store(fake.picture("JPEG", 5, 6))
        self.handler.sent.clear()
        antigravity.AGENT().http_send(self.handler, {
            "id": "a", "text": "看看这两张", "attachments": [first["id"], second["id"]]})
        self.assertEqual(self.handler.sent[0][0], 200)
        body = self.app_hub.calls("SendUserCascadeMessage")[-1]["body"]
        self.assertEqual(body["items"], [{"text": "看看这两张"}])
        self.assertEqual(len(body["media"]), 2)
        for item in body["media"]:
            self.assertEqual(item["mimeType"], "image/png")
            self.assertTrue(base64.b64decode(item["inlineData"]).startswith(b"\x89PNG\r\n\x1a\n"))

    def test_one_bad_picture_stops_the_whole_message(self):
        good = self.store(fake.picture("PNG"))
        broken = "b" * 32
        folder = self.codex.data_root / broken
        folder.mkdir(parents=True)
        (folder / "image.png").write_bytes(b"this is not a picture")
        self.codex.metas[broken] = {"id": broken, "thread": "a", "app": "antigravity", "name": "坏图",
                                    "file": "image.png", "original_size": 22, "width": 1, "height": 1,
                                    "created": 1.0, "used": False}
        before = len(self.app_hub.calls("SendUserCascadeMessage"))
        antigravity.AGENT().http_send(self.handler, {
            "id": "a", "text": "看看", "attachments": [good["id"], broken]})
        self.assertEqual(self.handler.sent[-1][0], 400)
        self.assertIn(antigravity.BAD_PICTURE, self.handler.sent[-1][1]["error"])
        self.assertEqual(len(self.app_hub.calls("SendUserCascadeMessage")), before)

    def test_more_than_five_pictures_are_refused(self):
        ids = []
        for _index in range(5):
            ids.append(self.store(fake.picture("PNG"))["id"])
        before = len(self.app_hub.calls("SendUserCascadeMessage"))
        antigravity.AGENT().http_send(self.handler, {
            "id": "a", "text": "六张", "attachments": ids + ["c" * 32]})
        self.assertEqual(self.handler.sent[-1][0], 400)
        self.assertIn("最多发 5 张", self.handler.sent[-1][1]["error"])
        self.assertEqual(len(self.app_hub.calls("SendUserCascadeMessage")), before)

    def test_a_file_that_only_looks_like_a_png_is_refused_before_anything_is_sent(self):
        good = self.store(fake.picture("PNG"))
        broken = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (2).to_bytes(4, "big") + (2).to_bytes(4, "big") \
            + b"\x08\x02\x00\x00\x00" + b"garbage" * 20
        (self.codex.data_root / good["id"] / "image.png").write_bytes(broken)
        before = len(self.app_hub.calls("SendUserCascadeMessage"))
        antigravity.AGENT().http_send(self.handler, {
            "id": "a", "text": "坏图", "attachments": [good["id"]]})
        self.assertEqual(self.handler.sent[-1][0], 400)
        self.assertIn(antigravity.BAD_PICTURE, self.handler.sent[-1][1]["error"])
        self.assertEqual(len(self.app_hub.calls("SendUserCascadeMessage")), before)
        self.assertEqual(self.app_hub.requests, [])

    def test_a_big_picture_is_sent_as_a_smaller_jpeg(self):
        from PIL import Image
        noise = Image.effect_noise((3200, 2400), 60).convert("RGB")
        buffer = io.BytesIO()
        noise.save(buffer, format="PNG")
        meta = self.store(buffer.getvalue(), "大图.png")
        stored_size = (self.codex.data_root / meta["id"] / "image.png").stat().st_size
        self.handler.sent.clear()
        antigravity.AGENT().http_send(self.handler, {
            "id": "a", "text": "大图", "attachments": [meta["id"]]})
        self.assertEqual(self.handler.sent[0][0], 200)
        item = self.app_hub.calls("SendUserCascadeMessage")[-1]["body"]["media"][0]
        raw = base64.b64decode(item["inlineData"])
        self.assertEqual(item["mimeType"], "image/jpeg")
        self.assertEqual(antigravity.picture_info(raw), ("image/jpeg", 3072, 2304))
        self.assertLess(len(raw), stored_size)

    def test_a_phone_media_field_is_never_sent(self):
        antigravity.AGENT().http_send(self.handler, {
            "id": "a", "text": "没有附件",
            "media": [{"mimeType": "image/png", "inlineData": "AAAA"}]})
        self.assertEqual(self.handler.sent[0][0], 200)
        self.assertNotIn("media", self.app_hub.calls("SendUserCascadeMessage")[-1]["body"])

    def test_picture_info_reads_each_header(self):
        png = fake.picture("PNG", 11, 13)
        jpeg = fake.picture("JPEG", 17, 19)
        gif = fake.picture("GIF", 21, 23)
        webp = fake.picture("WEBP", 25, 27)
        self.assertEqual(antigravity.picture_info(png), ("image/png", 11, 13))
        self.assertEqual(antigravity.picture_info(jpeg), ("image/jpeg", 17, 19))
        self.assertEqual(antigravity.picture_info(gif), ("image/gif", 21, 23))
        self.assertEqual(antigravity.picture_info(webp), ("image/webp", 25, 27))


if __name__ == "__main__":
    unittest.main()
