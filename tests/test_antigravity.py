"""Antigravity, read-only: the summaries list, the transcript reader, its notices and the shared routes.

All data is invented in a temporary folder; the isolation fixture in conftest.py keeps the real
Antigravity folder out of every test.
"""

from __future__ import annotations

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

    def test_the_manifest_is_read_only(self):
        manifest = registry.get("antigravity").manifest()
        self.assertEqual((manifest["id"], manifest["order"], manifest["legacy"], manifest["min_protocol"]),
                         ("antigravity", 40, False, 2))
        self.assertEqual((manifest["name"]["zh"], manifest["name"]["en"]), ("Antigravity", "Antigravity"))
        self.assertEqual((manifest["color"], manifest["color_dark"], manifest["icon"]),
                         ("#4285F4", "#8AB4F8", {"kind": "builtin", "key": "generic"}))
        self.assertEqual(manifest["ui"], {"card_layout": "generic.v1", "waiting_text": "等待你处理"})
        self.assertEqual(manifest["sources"], {"catalog": "sqlite", "transcript": "jsonl",
                                               "control": "none", "live": "file-poll"})
        capabilities = manifest["capabilities"]
        self.assertTrue(capabilities["list"] and capabilities["read"] and capabilities["search"])
        for name in ("open", "stop", "queue", "steer", "approve", "answer", "new", "archive", "restore",
                     "delete", "usage", "waiting", "attachments", "slash_commands", "skills"):
            self.assertFalse(capabilities[name], name)
        self.assertEqual((capabilities["send_modes"], capabilities["settings"]), ([], []))
        self.assertEqual(capabilities["statuses"], ["running", "idle", "unknown"])


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
                            {"name": "finish", "args": {"result": fake.FINISH_FULL}},
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
        # finish's result is the turn's summary, not a step.
        self.assertIn(("assistant", fake.FINISH_FULL), shown)
        self.assertNotIn(("assistant", fake.FINISH_CUT), shown)
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
        self.assertEqual([message["role"] for message in page["messages"]].count("tool"), 4)

    def test_a_tool_output_is_never_shown_as_an_answer(self):
        page = self.page(limit=100)
        texts = [message["text"] for message in page["messages"]]
        self.assertNotIn(fake.TOOL_OUTPUT, texts)
        self.assertFalse(any(text.startswith("工具输出") for text in texts))
        self.assertNotIn(fake.TOOL_OUTPUT, " ".join(texts))

    def test_a_finish_result_kept_as_an_object_is_serialized_in_full(self):
        # The real full file keeps finish's result as an object; its compact JSON is the text the transcript cut.
        self.assertEqual(antigravity._result_text({"items": [{"verdict": "pass"}]}),
                         '{"items":[{"verdict":"pass"}]}')

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
        self.assertEqual(sent[0][0], 400)
        self.assertEqual(json.loads(sent[0][1])["code"], "unsupported")

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


if __name__ == "__main__":
    unittest.main()
