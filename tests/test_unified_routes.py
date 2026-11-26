"""Unified /api/agents/<id>/... route contract tests (all 13 routes + protocol filtering)."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import chats
import composer_references
import new_conversations
import remote
import usage_limits


def call_api(server, method: str, path: str, body=None, raw_body: bytes | None = None, protocol: int | None = 2):
    handler = object.__new__(remote.Handler)
    sent = []
    sep = "&" if "?" in path else "?"
    handler.path = f"{path}{sep}t=secret"
    headers = {}
    if protocol is not None:
        headers["X-Teleply-Protocol"] = str(protocol)
    if raw_body is not None:
        payload = raw_body
        headers["Content-Length"] = str(len(payload))
    elif body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(payload))
    else:
        payload = b""
    handler.headers = headers
    handler.rfile = io.BytesIO(payload)
    handler.close_connection = False
    handler.server = server
    handler._send = lambda code, data, ctype, extra=None: sent.append((code, data, ctype))
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    code, data, ctype = sent[0]
    parsed = json.loads(data.decode("utf-8")) if ctype.startswith("application/json") else data
    return code, parsed


class UnifiedRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proj = self.root / "proj"
        self.proj.mkdir()

        self.codex = Mock()
        self.codex.status.return_value = {"available": True, "running": True, "status": "running", "turn_id": "t1"}
        self.codex.receipt.return_value = {"state": "accepted", "id": "c1", "request_id": "r1"}
        self.codex.send.return_value = {"ok": True, "accepted": True, "request_id": "r1", "text": "已交给 Codex"}
        self.codex.stop_turn.return_value = {"ok": True, "text": "已请求停止"}
        self.codex.queue_action.return_value = {"ok": True}
        self.codex.answer.return_value = {"ok": True}
        self.codex.confirm_open.return_value = {"ok": True, "text": "已打开 Codex"}
        self.codex.upload.side_effect = lambda tid, name, raw, app="codex", **kw: {"id": "att1", "name": name, "size": len(raw), "app": app}
        self.codex.message_images.return_value = []

        self.claude = Mock()
        self.claude.state.return_value = {"available": True, "running": True, "stop_token": "tok-1"}
        self.claude.choose.return_value = {"ok": True, "text": "已操作"}
        self.claude.send_steer.return_value = {"ok": True, "steer_requested": True, "offset": 42, "text": "已补充"}
        self.claude.next_step.return_value = {"ok": True, "text": "下一步"}
        self.claude.task_step.return_value = {"ok": True, "text": "任务"}
        self.claude.new_options.return_value = {"models": [{"id": "Sonnet", "label": "Sonnet", "efforts": [], "default_effort": None}], "note": ""}

        self.deepseek = Mock()
        self.deepseek.state.return_value = {"available": True, "running": True, "turn_id": "dt1"}
        self.deepseek.receipt.return_value = {"state": "accepted", "id": "d1", "request_id": "rd1"}
        self.deepseek.send.return_value = {"accepted": True, "text": "已交给 DeepSeek"}
        self.deepseek.stop.return_value = {"ok": True}
        self.deepseek.queue_action.return_value = {"ok": True}
        self.deepseek.answer.return_value = {"ok": True}
        self.deepseek.events = Mock()
        self.deepseek.events.answer.return_value = {"ok": True, "approved": True}
        self.deepseek.find.return_value = {"app": "deepseek", "id": "d1"}
        self.deepseek.commands.return_value = [{"name": "compact", "description": "Compact", "hint": ""}]
        self.deepseek.models.return_value = {"groups": [{"id": "ds", "name": "DeepSeek", "models": [{"id": "chat", "name": "Chat"}]}]}

        self.desktop = Mock()
        self.desktop.run.side_effect = lambda fn, *args, timeout=None: fn(*args)
        self.desktop.send.return_value = {"ok": True, "pressed": True, "offset": 1, "running": False, "text": "已提交"}
        self.desktop.open.return_value = {"ok": True, "text": "已打开"}
        self.desktop.claude_press.return_value = {"ok": True, "text": "已点按钮"}

        self.history = SimpleNamespace(catalog=lambda: [{"app": "codex", "id": "c1", "cwd": str(self.proj), "folder": "proj", "updated": 1}])
        self.references = composer_references.References(self.history, home=self.root)
        self.new_chats = new_conversations.NewConversations(self.history, self.references, self.codex, self.desktop, root=self.root / "new")
        self.new_chats.claude = self.claude
        self.usage = usage_limits.Usage(
            self.desktop, log=lambda t: None, apps=lambda: ["codex", "claude", "deepseek"],
            records=lambda: {"source": "records", "as_of": 1000, "plan": "pro", "windows": [], "reached": None, "resets": None, "ordinary_usage_allowed": None},
            data_dir=self.root,
        )

        self.server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": ["codex", "claude", "deepseek"], "voice": False},
            cfg={"token": "secret"},
            log=SimpleNamespace(write=lambda t: None),
            desktop=self.desktop,
            codex=self.codex,
            claude=self.claude,
            claude_reads=[],
            deepseek=self.deepseek,
            history=self.history,
            references=self.references,
            new_chats=self.new_chats,
            usage=self.usage,
            tasks=Mock(),
        )

    def test_codex_unified_routes(self):
        with patch("chats.find", return_value={"app": "codex", "id": "c1", "cwd": str(self.proj)}), \
             patch("codex_control.catalog", return_value={"models": [{"id": "gpt-test", "name": "GPT", "efforts": ["high"], "default_effort": "high"}]}), \
             patch("new_conversations.threading.Thread"):
            code, body = call_api(self.server, "GET", "/api/agents/codex/state?id=c1&fresh=1")
            self.assertEqual((code, body["turn_id"]), (200, "t1"))
            self.assertIn("capabilities_now", body)
            self.assertIn("capability_notes", body)
            self.server.tasks.observe.assert_called_once()
            # tasks.observe receives original state without capabilities_now
            self.assertNotIn("capabilities_now", self.server.tasks.observe.call_args.args[1])

            code_p1, body_p1 = call_api(self.server, "GET", "/api/agents/codex/state?id=c1", protocol=1)
            self.assertEqual(code_p1, 200)
            self.assertNotIn("capabilities_now", body_p1)
            self.assertNotIn("capability_notes", body_p1)

            code, body = call_api(self.server, "GET", "/api/agents/codex/receipt?id=c1&request_id=r1")
            self.assertEqual((code, body["state"]), (200, "accepted"))

            code, body = call_api(self.server, "GET", "/api/agents/codex/options")
            self.assertEqual((code, body["models"][0]["id"]), (200, "gpt-test"))

            code, body = call_api(self.server, "GET", "/api/agents/codex/commands?id=c1")
            self.assertEqual((code, body["items"][0]["name"]), (200, "compact"))

            code, body = call_api(self.server, "GET", "/api/agents/codex/usage")
            self.assertEqual((code, body["available"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/codex/send", {"id": "c1", "text": "hello", "request_id": "r1"})
            self.assertEqual((code, body["accepted"]), (200, True))
            self.assertIn("accepted_at", body)

            code, body = call_api(self.server, "POST", "/api/agents/codex/stop", {"id": "c1", "expected_turn": "t1"})
            self.assertEqual((code, body["ok"]), (200, True))
            self.assertEqual(self.codex.stop_turn.call_args.args[0]["turn_id"], "t1")

            code, body = call_api(self.server, "POST", "/api/agents/codex/queue", {"id": "c1", "item_id": "q1", "action": "steer"})
            self.assertEqual((code, body["ok"]), (200, True))
            self.assertEqual(self.codex.queue_action.call_args.args[0]["message_id"], "q1")
            self.assertEqual(self.codex.queue_action.call_args.args[0]["action"], "promote")

            code, body = call_api(self.server, "POST", "/api/agents/codex/answer", {"id": "c1", "request_id": "q1", "answers": {}})
            self.assertEqual((code, body["ok"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/codex/open", {"id": "c1"})
            self.assertEqual((code, body["ok"]), (200, True))
            self.codex.confirm_open.assert_called_once_with("c1")

            rid = self.new_chats.create_draft()["request_id"]
            code, body = call_api(self.server, "POST", "/api/agents/codex/create", {
                "request_id": rid, "folder": str(self.proj), "text": "hi", "attachments": [], "references": [],
            })
            self.assertEqual((code, body["state"]), (200, "creating"))

            code, body = call_api(self.server, "GET", f"/api/agents/codex/create/state?request_id={rid}")
            self.assertEqual((code, body["app"]), (200, "codex"))

            # Wrong agent on create/state is rejected
            code, _ = call_api(self.server, "GET", f"/api/agents/claude/create/state?request_id={rid}")
            self.assertEqual(code, 400)

            code, body = call_api(self.server, "POST", "/api/agents/codex/upload?id=c1&name=a.png", raw_body=b"1234")
            self.assertEqual((code, body["app"], body["size"]), (200, "codex", 4))

    def test_claude_unified_routes_and_unsupported_queue(self):
        with patch("chats.find", return_value={"app": "claude", "id": "cl1", "cwd": str(self.proj)}), \
             patch("usage_limits.claude_window", return_value={"available": True, "source": "window", "windows": []}):
            code, body = call_api(self.server, "GET", "/api/agents/claude/state?id=cl1")
            self.assertEqual((code, body["stop_token"]), (200, "tok-1"))
            self.assertNotIn("capabilities_now", body)
            self.assertNotIn("capability_notes", body)

            self.codex.receipt.return_value = {"state": "unknown"}
            code, body = call_api(self.server, "GET", "/api/agents/claude/receipt?id=cl1&request_id=r1")
            self.assertEqual((code, body["state"]), (200, "unknown"))

            # 11-26 P1/8.1: "missing": true travels to the phone with the same state; the phone then says 电脑没收到
            self.codex.receipt.return_value = {"state": "unknown", "missing": True}
            code, body = call_api(self.server, "GET", "/api/agents/claude/receipt?id=cl1&request_id=r1")
            self.assertEqual((code, body["state"], body["missing"], body["id"], body["request_id"]),
                             (200, "unknown", True, "cl1", "r1"))

            code, body = call_api(self.server, "GET", "/api/agents/claude/options")
            self.assertEqual((code, body["models"][0]["id"]), (200, "Sonnet"))

            code, body = call_api(self.server, "GET", "/api/agents/claude/commands?id=cl1")
            self.assertEqual(code, 200)
            self.assertTrue(any(v["name"] == "compact" for v in body["items"]))

            code, body = call_api(self.server, "GET", "/api/agents/claude/usage")
            self.assertEqual((code, body["available"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/claude/send", {"id": "cl1", "text": "hello"})
            self.assertEqual((code, body["ok"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/claude/send", {
                "id": "cl1", "text": "steer", "intent": "steer", "expected_turn": "anc1", "request_id": "steer-123456",
            })
            # 11-24: a steer says where to look for it, as a queued send does; without that the phone never asks again
            self.assertEqual((code, body["steer_requested"], body["pressed"], body["offset"], body["check_text"]),
                             (200, True, True, 42, "steer"))

            code, body = call_api(self.server, "POST", "/api/agents/claude/stop", {"id": "cl1", "token": "tok-1"})
            self.assertEqual((code, body["ok"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/claude/queue", {"id": "cl1", "item_id": "q1", "action": "remove"})
            self.assertEqual((code, body["code"]), (400, "unsupported"))

            code, body = call_api(self.server, "POST", "/api/agents/claude/answer", {"id": "cl1", "token": "tok-2", "value": 1})
            self.assertEqual((code, body["ok"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/claude/open", {"id": "cl1"})
            self.assertEqual((code, body["ok"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/claude/upload?id=cl1&name=b.png", raw_body=b"12345")
            self.assertEqual((code, body["app"], body["size"]), (200, "claude", 5))

    def test_deepseek_unified_routes_and_unsupported_usage(self):
        with patch("deepseek_control.bridge", return_value=self.deepseek), \
             patch("remote.os.startfile") as startfile:
            code, body = call_api(self.server, "GET", "/api/agents/deepseek/state?id=d1")
            self.assertEqual((code, body["turn_id"]), (200, "dt1"))
            self.assertNotIn("capabilities_now", body)
            self.assertNotIn("capability_notes", body)

            code, body = call_api(self.server, "GET", "/api/agents/deepseek/receipt?id=d1&request_id=rd1")
            self.assertEqual((code, body["state"]), (200, "accepted"))

            code, body = call_api(self.server, "GET", "/api/agents/deepseek/options")
            self.assertEqual((code, body["models"][0]["id"]), (200, "ds/chat"))

            code, body = call_api(self.server, "GET", "/api/agents/deepseek/commands?id=d1")
            self.assertEqual((code, body["items"][0]["name"]), (200, "compact"))

            code, body = call_api(self.server, "GET", "/api/agents/deepseek/usage")
            self.assertEqual((code, body["code"]), (400, "unsupported"))

            code, body = call_api(self.server, "POST", "/api/agents/deepseek/send", {"id": "d1", "text": "hi", "intent": "auto"})
            self.assertEqual((code, body["accepted"]), (200, True))
            self.assertEqual(self.deepseek.send.call_args.args[0]["intent"], "steer")

            code, body = call_api(self.server, "POST", "/api/agents/deepseek/stop", {"id": "d1", "turn_id": "dt1"})
            self.assertEqual((code, body["ok"]), (200, True))
            self.deepseek.stop.assert_called_once_with("d1", "dt1")

            code, body = call_api(self.server, "POST", "/api/agents/deepseek/queue", {"id": "d1", "message_id": "m1", "action": "promote"})
            self.assertEqual((code, body["ok"]), (200, True))
            self.deepseek.queue_action.assert_called_once_with("d1", "m1", "steer")

            code, body = call_api(self.server, "POST", "/api/agents/deepseek/answer", {"id": "d1", "event_id": "e1", "choice": "allow"})
            self.assertEqual((code, body["approved"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/deepseek/answer", {"id": "d1", "call_id": "c1", "answers": {"a": "b"}})
            self.assertEqual((code, body["ok"]), (200, True))

            code, body = call_api(self.server, "POST", "/api/agents/deepseek/open", {"id": "d1"})
            self.assertEqual((code, body["ok"]), (200, True))
            startfile.assert_called_once_with("dsh://open")

    def test_protocol_filtering_and_unknown_agent(self):
        code, _ = call_api(self.server, "GET", "/api/agents/nope/state?id=x", protocol=2)
        self.assertEqual(code, 404)
        code, _ = call_api(self.server, "GET", "/api/agents/codex/unknown", protocol=2)
        self.assertEqual(code, 404)
        code, _ = call_api(self.server, "POST", "/api/agents/codex/unknown", {}, protocol=2)
        self.assertEqual(code, 404)

        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            # Protocol 1 cannot see legacy=False agent on any unified route
            for method, path, body in (
                ("GET", "/api/agents/testing/state?id=test-running", None),
                ("GET", "/api/agents/testing/usage", None),
                ("POST", "/api/agents/testing/send", {"id": "test-running", "text": "x"}),
                ("POST", "/api/agents/testing/stop", {"id": "test-running"}),
                ("POST", "/api/agents/testing/upload?id=test-running&name=a.png", None),
            ):
                code, _ = call_api(
                    self.server, method, path, body=body,
                    raw_body=b"123" if path.endswith("a.png") else None, protocol=1,
                )
                self.assertEqual(code, 404, (method, path))

            # /api/usage protocol 1 has only legacy keys; protocol 2 adds agents dict
            self.server.machine["apps"] = ["codex", "claude", "deepseek", "testing"]
            with patch("usage_limits.claude_window", return_value={"available": True, "source": "window", "windows": []}):
                code1, u1 = call_api(self.server, "GET", "/api/usage", protocol=1)
                self.assertEqual(code1, 200)
                self.assertEqual(set(u1.keys()), {"codex", "claude", "now"})

                code2, u2 = call_api(self.server, "GET", "/api/usage", protocol=2)
                self.assertEqual(code2, 200)
                self.assertIn("agents", u2)
                self.assertEqual(set(u2["agents"].keys()), {"codex", "claude", "antigravity", "testing"})

            # Testing agent returns None from capabilities_now -> no capabilities_now/capability_notes on protocol 2
            code_ts, ts_state = call_api(self.server, "GET", "/api/agents/testing/state?id=test-running", protocol=2)
            self.assertEqual(code_ts, 200)
            self.assertNotIn("capabilities_now", ts_state)
            self.assertNotIn("capability_notes", ts_state)


if __name__ == "__main__":
    unittest.main()
