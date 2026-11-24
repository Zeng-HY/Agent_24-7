"""The agent list, its manifests, detection and the test-only assistant."""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import archives
import chat_history
import notify
import remote
import usage_limits
from agents import claude as claude_agent, codex as codex_agent, deepseek as deepseek_agent, registry, testing
from agents.base import UnknownAgent


class ManifestTests(unittest.TestCase):
    def test_the_three_production_agents_in_manifest_order(self):
        self.assertEqual([a.id for a in registry.load()], ["codex", "claude", "deepseek"])

    def test_every_manifest_has_the_same_shape(self):
        for agent in registry.load():
            manifest = agent.manifest()
            self.assertEqual(manifest["schema"], 1)
            self.assertEqual(manifest["id"], agent.id)
            self.assertEqual(manifest["name"]["zh"], manifest["name"]["en"])
            self.assertTrue(manifest["color"].startswith("#"))
            self.assertIn(manifest["icon"]["kind"], ("builtin", "url"))
            self.assertIn("capabilities", manifest)
            self.assertIn("params", manifest)
            self.assertIn("statuses", manifest["capabilities"])
            self.assertEqual(set(manifest["params"]), {
                "state_timeout_s", "send_timeout_s", "open_timeout_s", "new_timeout_s",
                "refresh_ms", "max_images", "max_image_bytes", "max_text"})
            json.dumps(manifest, ensure_ascii=False)  # must be JSON, not a Python object tree

    def test_orders_are_unique(self):
        orders = [a.manifest()["order"] for a in registry.load()]
        self.assertEqual(len(orders), len(set(orders)))

    def test_three_are_legacy_and_the_test_assistant_is_not(self):
        self.assertTrue(all(a.manifest()["legacy"] for a in registry.load()))
        self.assertFalse(registry.load(include_testing=True)[-1].manifest()["legacy"])

    def test_unknown_id_is_refused(self):
        with self.assertRaises(UnknownAgent):
            registry.get("nope")

    def test_codex_manifest_is_fixed_and_never_probes_route_or_trust(self):
        import codex_apptools
        import codex_hooks

        def _boom(*_args, **_kwargs):
            raise AssertionError("manifest must not probe route or hook trust")

        with patch.object(codex_apptools, "detect_route", side_effect=_boom), \
             patch.object(codex_hooks, "read_trust_status", side_effect=_boom):
            loaded = registry.load()
            self.assertEqual([a.id for a in loaded], ["codex", "claude", "deepseek"])
            manifest = registry.get("codex").manifest()
            self.assertIn("mode", manifest["capabilities"]["settings"])

        manifests = []
        for pipes in (["codex-ipc"], ["codex-app-tools-0000"], []):
            with patch.object(codex_apptools, "_list_pipes", return_value=pipes):
                codex_apptools.reset_route_cache()
                manifests.append(codex_agent.CodexAgent().manifest())
        self.assertEqual(manifests[0], manifests[1])
        self.assertEqual(manifests[1], manifests[2])

    def test_registry_get_is_fast_on_apptools_route_with_trusted_hooks(self):
        import codex_apptools
        import codex_hooks

        with tempfile.TemporaryDirectory() as td:
            fake_home = Path(td) / "codex_home"
            fake_home.mkdir()
            codex_hooks.install_hooks(r"C:\Fake\TeleplyCodexHook.exe", codex_home=fake_home, log=lambda _t: None)
            hp = fake_home / "hooks.json"
            (fake_home / "config.toml").write_text(
                f"[hooks.state.'{hp}:pre_tool_use:0:0']\ntrusted_hash = \"h1\"\n"
                f"[hooks.state.'{hp}:permission_request:0:0']\ntrusted_hash = \"h2\"\n"
                f"[hooks.state.'{hp}:stop:0:0']\ntrusted_hash = \"h3\"\n",
                encoding="utf-8",
            )
            codex_hooks.set_default_codex_home_override(fake_home)
            codex_hooks.reset_trust_cache()
            with patch.object(codex_apptools, "_list_pipes", return_value=["codex-app-tools-0000"]):
                codex_apptools.reset_route_cache()
                self.assertEqual(codex_hooks.read_trust_status(), "enabled")
                t0 = time.perf_counter()
                for _ in range(1000):
                    registry.get("claude")
                elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 1.0, f"1000x registry.get('claude') took {elapsed:.3f}s")


class DetectionTests(unittest.TestCase):
    def test_empty_computer_has_no_apps(self):
        with tempfile.TemporaryDirectory() as temp:
            local, roaming = Path(temp) / "Local", Path(temp) / "Roaming"
            local.mkdir(); roaming.mkdir()
            with patch.object(registry, "load", wraps=registry.load):
                with patch("machines.LOCALAPPDATA", local), patch("machines.APPDATA", roaming):
                    import machines
                    self.assertEqual(machines.installed_apps(), [])

    def test_codex_claude_and_deepseek_are_found_by_their_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            local, roaming = Path(temp) / "Local", Path(temp) / "Roaming"
            (local / "Packages" / "OpenAI.Codex_2p2nqsd0c76g0").mkdir(parents=True)
            (roaming / "Claude").mkdir(parents=True)
            (roaming / "@deepseek-ai" / "dsh-desktop").mkdir(parents=True)
            with patch("machines.LOCALAPPDATA", local), patch("machines.APPDATA", roaming):
                import machines
                self.assertEqual(machines.installed_apps(), ["codex", "claude", "deepseek"])

    def test_a_command_line_dsh_alone_is_not_the_desktop_app(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / ".dsh").mkdir()
            with patch("machines.LOCALAPPDATA", home / "Local"), patch("machines.APPDATA", home / "Roaming"):
                import machines
                self.assertEqual(machines.installed_apps(), [])


class TestingAgentTests(unittest.TestCase):
    def setUp(self):
        testing.reset()
        self.addCleanup(testing.reset)

    def agent(self):
        return registry.get("testing", include_testing=True)

    def test_the_test_assistant_only_appears_when_asked(self):
        self.assertNotIn("testing", registry.ids())
        self.assertIn("testing", registry.ids(include_testing=True))

    def test_a_frozen_build_ignores_the_test_switch(self):
        with patch.object(registry.sys, "frozen", True, create=True), \
             patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            self.assertNotIn("testing", registry.ids())
            self.assertEqual(registry.ids(), ["codex", "claude", "deepseek"])

    def test_catalog_reads_and_count(self):
        agent = self.agent()
        page = agent.catalog()
        self.assertEqual(len(page["items"]), 2)
        self.assertEqual({v["app"] for v in page["items"]}, {"testing"})
        self.assertEqual(agent.catalog(status="running")["items"][0]["id"], "test-running")
        read = agent.read("test-running")
        self.assertEqual(read["app"], "testing")
        self.assertEqual([m["role"] for m in read["messages"]], ["user", "assistant"])
        self.assertEqual(agent.state("test-running")["status"], "running")

    def test_send_stop_archive_restore_delete(self):
        agent = self.agent()
        sent = agent.send({"id": "test-running", "text": "验收测试", "request_id": "r1"})
        self.assertTrue(sent["accepted"])
        self.assertTrue(agent.check("test-running", 0, "验收测试")["delivered"])
        self.assertTrue(agent.stop({"id": "test-running"})["ok"])
        self.assertEqual(agent.state("test-running")["status"], "idle")
        self.assertTrue(agent.archive("test-waiting")["archived"])
        self.assertNotIn("test-waiting", [v["id"] for v in agent.catalog()["items"]])
        self.assertFalse(agent.restore("test-waiting")["archived"])
        agent.archive("test-waiting")
        self.assertTrue(agent.delete("test-waiting")["gone"])

    def test_usage_and_commands(self):
        agent = self.agent()
        self.assertTrue(agent.usage()["available"])
        self.assertEqual(agent.commands("test-running")[0]["name"], "test")

    def test_the_test_assistant_can_be_listed_and_read(self):
        from chat_history import History
        history = History()
        row = {"app": "testing", "id": "test-running", "title": "测试对话 A", "folder": "C:\\测试\\项目",
               "cwd": "C:\\测试\\项目", "updated": 1767323045000, "created": 1767323040000, "pinned": False,
               "status": "running", "preview": "正在跑测试"}
        history._load = lambda: ([row], [])
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            page = history.conversations("all")
            self.assertEqual([v["app"] for v in page["items"]], ["testing"])
            read = history.conversation("testing", "test-running")
            self.assertEqual(read["app"], "testing")
            self.assertEqual([m["role"] for m in read["messages"]], ["user", "assistant"])
            self.assertEqual(history.message("testing", "test-running", "m1")["text"], "跑一下测试")


class EndpointTests(unittest.TestCase):
    def handler(self, path, apps, protocol=None):
        handler = object.__new__(remote.Handler)
        sent = []
        handler.path = path
        handler.headers = {"X-Teleply-Protocol": str(protocol)} if protocol else {}
        handler.close_connection = False
        handler.server = SimpleNamespace(machine={"name": "公司电脑", "apps": apps, "voice": False},
                                        cfg={"token": "secret"})
        handler._send = lambda code, body, ctype, extra=None: sent.append((code, body))
        return handler, sent

    def test_api_agents_lists_the_computers_manifests(self):
        handler, sent = self.handler("/api/agents?t=secret", ["codex", "claude"], protocol=2)
        handler.do_GET()
        self.assertEqual(sent[0][0], 200)
        body = json.loads(sent[0][1])
        self.assertEqual(body["schema"], 1)
        self.assertEqual(body["protocol"], 2)
        self.assertEqual([a["id"] for a in body["agents"]], ["codex", "claude"])

    def test_api_agents_is_not_exposed_to_protocol_one(self):
        handler, sent = self.handler("/api/agents?t=secret", ["codex"])
        handler.do_GET()
        self.assertEqual(sent[0][0], 404)

    def test_chats_hides_a_non_legacy_agent_from_protocol_one(self):
        rows = [{"app": app, "id": app + "1", "title": app} for app in ("codex", "claude", "deepseek", "testing")]
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            handler, sent = self.handler("/api/chats?app=all&t=secret",
                                         ["codex", "claude", "deepseek", "testing"])
            handler.server.history = SimpleNamespace(
                conversations=lambda *args, **kwargs: {"items": list(rows), "has_more": False,
                                                        "next_cursor": "", "total": len(rows), "now": 0})
            handler.server.tasks = SimpleNamespace(apply_status=lambda items: items)
            handler.do_GET()
            self.assertEqual([v["app"] for v in json.loads(sent[0][1])["items"]],
                             ["codex", "claude", "deepseek"])
            handler, sent = self.handler("/api/chats?app=all&t=secret",
                                         ["codex", "claude", "deepseek", "testing"], protocol=2)
            handler.server.history = SimpleNamespace(
                conversations=lambda *args, **kwargs: {"items": list(rows), "has_more": False,
                                                        "next_cursor": "", "total": len(rows), "now": 0})
            handler.server.tasks = SimpleNamespace(apply_status=lambda items: items)
            handler.do_GET()
            self.assertEqual([v["app"] for v in json.loads(sent[0][1])["items"]],
                             ["codex", "claude", "deepseek", "testing"])

    def test_a_non_legacy_agent_cannot_be_read_by_protocol_one(self):
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            handler, sent = self.handler("/api/chat?app=testing&id=t1&t=secret", ["testing"])
            handler.server.history = SimpleNamespace(conversation=lambda *args, **kwargs: {"app": "testing"})
            handler.do_GET()
            self.assertEqual(sent[0][0], 404)

    def test_project_tree_and_archive_hide_a_non_legacy_agent_from_protocol_one(self):
        apps = ["codex", "claude", "deepseek", "testing"]
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            handler, sent = self.handler("/api/chat/projects?t=secret", apps)
            handler.server.history = SimpleNamespace(catalog=lambda: [], ungrouped=lambda: [])
            tree = {"apps": [{"app": app, "name": app, "projects": []} for app in apps], "now": 0}
            with patch.object(remote.chat_projects, "tree", return_value=tree):
                handler.do_GET()
            self.assertEqual([a["app"] for a in json.loads(sent[0][1])["apps"]],
                             ["codex", "claude", "deepseek"])

            archived = {"items": [{"app": app, "id": app} for app in apps], "apps": apps,
                        "deletable": ["codex"], "problems": []}
            handler, sent = self.handler("/api/chat/archived?t=secret", apps)
            handler.server.archives = SimpleNamespace(archived=lambda: dict(archived))
            handler.do_GET()
            body = json.loads(sent[0][1])
            self.assertEqual([v["app"] for v in body["items"]], ["codex", "claude", "deepseek"])
            self.assertEqual(body["apps"], ["codex", "claude", "deepseek"])

    def test_api_agents_needs_the_token(self):
        handler, sent = self.handler("/api/agents", [])
        handler.do_GET()
        self.assertEqual(sent[0][0], 403)

    def test_api_agents_can_include_the_test_assistant_when_asked(self):
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            handler, sent = self.handler("/api/agents?t=secret", ["codex", "testing"], protocol=2)
            handler.do_GET()
        self.assertEqual([a["id"] for a in json.loads(sent[0][1])["agents"]], ["codex", "testing"])


class TestingAgentEndToEndTests(unittest.TestCase):
    """Full-chain test for the fake assistant through remote.Handler and shared services."""

    def setUp(self):
        testing.reset()
        self.addCleanup(testing.reset)

    def _make_server(self):
        apps = ["testing"]
        history = chat_history.History()
        arch = archives.Archives(history=history, apps=lambda: list(apps), log=lambda _msg: None)
        usage = usage_limits.Usage(apps=lambda: list(apps), desktop=None, log=lambda _msg: None)
        return SimpleNamespace(
            machine={"name": "测试电脑", "apps": list(apps), "voice": False},
            cfg={"token": "secret"},
            history=history,
            archives=arch,
            usage=usage,
            tasks=SimpleNamespace(apply_status=lambda items: items),
            references=None,
            deepseek=None,
            new_chats=None,
            log=SimpleNamespace(write=lambda _msg: None),
        )

    def _call(self, server, method: str, path: str, *, protocol=None, body=None, raw: bytes | None = None):
        handler = object.__new__(remote.Handler)
        sent = []
        handler.path = path
        handler.server = server
        handler.close_connection = False
        handler._responded = False
        headers = {}
        if protocol is not None:
            headers["X-Teleply-Protocol"] = str(protocol)
        if raw is not None:
            headers["Content-Length"] = str(len(raw))
            handler.rfile = io.BytesIO(raw)
        elif body is not None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Length"] = str(len(encoded))
            handler.rfile = io.BytesIO(encoded)
        else:
            headers["Content-Length"] = "0"
            handler.rfile = io.BytesIO(b"")
        handler.headers = headers
        handler._send = lambda code, payload, ctype, extra=None: sent.append((code, json.loads(payload) if payload else None))
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        self.assertEqual(len(sent), 1, f"expected one response for {method} {path}, got {sent}")
        return sent[0]

    def test_testing_agent_excluded_from_production_and_hidden_from_protocol_one(self):
        self.assertNotIn("testing", registry.ids())
        server = self._make_server()
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}), \
             patch.object(codex_agent.CodexAgent, "catalog_entries", return_value=[]), \
             patch.object(claude_agent.ClaudeAgent, "catalog_entries", return_value=[]), \
             patch.object(deepseek_agent.DeepSeekAgent, "catalog_entries", return_value=[]):
            code, _ = self._call(server, "GET", "/api/agents?t=secret")
            self.assertEqual(code, 404)
            code, body = self._call(server, "GET", "/api/chats?app=all&t=secret")
            self.assertEqual(code, 200)
            self.assertEqual(body["items"], [])
            for method, path, payload in (
                ("GET", "/api/chat?app=testing&id=test-running&t=secret", None),
                ("GET", "/api/agents/testing/state?id=test-running&t=secret", None),
                ("POST", "/api/agents/testing/send?t=secret", {"id": "test-running", "text": "hi"}),
                ("POST", "/api/agents/testing/stop?t=secret", {"id": "test-running"}),
                ("POST", "/api/agents/testing/answer?t=secret", {"id": "test-waiting", "choice": "A"}),
                ("POST", "/api/chat/archive?t=secret", {"app": "testing", "id": "test-waiting"}),
                ("POST", "/api/chat/unarchive?t=secret", {"app": "testing", "id": "test-waiting"}),
                ("POST", "/api/chat/delete?t=secret", {"confirmed": True, "items": [{"app": "testing", "id": "test-waiting"}]}),
            ):
                code, _ = self._call(server, method, path, body=payload)
                self.assertEqual(code, 404, f"protocol 1 should not reach {method} {path}")

    def test_testing_agent_full_chain_protocol_two(self):
        server = self._make_server()
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}), \
             patch.object(codex_agent.CodexAgent, "catalog_entries", return_value=[]), \
             patch.object(claude_agent.ClaudeAgent, "catalog_entries", return_value=[]), \
             patch.object(deepseek_agent.DeepSeekAgent, "catalog_entries", return_value=[]):
            # 1. Discover manifest
            code, body = self._call(server, "GET", "/api/agents?t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual([a["id"] for a in body["agents"]], ["testing"])
            self.assertFalse(body["agents"][0]["legacy"])
            self.assertEqual(body["agents"][0]["min_protocol"], 2)

            # 2. List and read
            code, body = self._call(server, "GET", "/api/chats?app=testing&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual({row["id"] for row in body["items"]}, {"test-running", "test-waiting"})

            code, body = self._call(server, "GET", "/api/chat?app=testing&id=test-running&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual(len(body["messages"]), 2)

            # 3. Send and verify persistence across separate registry.get("testing") calls
            code, body = self._call(server, "POST", "/api/agents/testing/send?t=secret", protocol=2,
                                    body={"id": "test-running", "text": "全链路验证", "request_id": "req-e2e"})
            self.assertEqual(code, 200)
            self.assertTrue(body["accepted"])

            code, body = self._call(server, "GET", "/api/chat?app=testing&id=test-running&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual(body["messages"][-1]["text"], "全链路验证")

            # 4. Stop and check state
            code, body = self._call(server, "POST", "/api/agents/testing/stop?t=secret", protocol=2,
                                    body={"id": "test-running"})
            self.assertEqual(code, 200)
            self.assertTrue(body["ok"])

            code, body = self._call(server, "GET", "/api/agents/testing/state?id=test-running&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual(body["status"], "idle")
            self.assertFalse(body["running"])

            # 5. Approve / answer waiting conversation (two generic cards, design §3)
            code, body = self._call(server, "POST", "/api/agents/testing/answer?t=secret", protocol=2,
                                    body={"id": "test-waiting", "question_id": "approval-7",
                                          "answers": {"decision": ["允许一次"]}})
            self.assertEqual(code, 200)
            self.assertTrue(body["ok"])
            self.assertEqual(body["text"], "已允许本次操作")

            code, body = self._call(server, "GET", "/api/agents/testing/state?id=test-waiting&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual([card["id"] for card in body["questions"]], ["question-8"])

            code, body = self._call(server, "POST", "/api/agents/testing/answer?t=secret", protocol=2,
                                    body={"id": "test-waiting", "question_id": "question-8",
                                          "answers": {"plan": ["方案 A"], "files": ["a.py", "b.py"]},
                                          "answer_revision": "rev-1"})
            self.assertEqual(code, 200)
            self.assertEqual(body["text"], "答案已提交")

            code, body = self._call(server, "GET", "/api/agents/testing/state?id=test-waiting&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual(body["questions"], [])
            self.assertEqual(body["status"], "idle")

            # 6. Archive -> listed in archived & hidden from catalog -> restore -> archive -> delete
            code, body = self._call(server, "POST", "/api/chat/archive?t=secret", protocol=2,
                                    body={"app": "testing", "id": "test-waiting"})
            self.assertEqual(code, 200)
            self.assertTrue(body["archived"])

            code, body = self._call(server, "GET", "/api/chats?app=testing&t=secret", protocol=2)
            self.assertEqual([row["id"] for row in body["items"]], ["test-running"])

            code, body = self._call(server, "GET", "/api/chat/archived?t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual([row["id"] for row in body["items"]], ["test-waiting"])

            code, body = self._call(server, "POST", "/api/chat/unarchive?t=secret", protocol=2,
                                    body={"app": "testing", "id": "test-waiting"})
            self.assertEqual(code, 200)
            self.assertFalse(body["archived"])

            code, body = self._call(server, "GET", "/api/chats?app=testing&t=secret", protocol=2)
            self.assertEqual({row["id"] for row in body["items"]}, {"test-running", "test-waiting"})

            self._call(server, "POST", "/api/chat/archive?t=secret", protocol=2,
                       body={"app": "testing", "id": "test-waiting"})
            code, body = self._call(server, "POST", "/api/chat/delete?t=secret", protocol=2,
                                    body={"confirmed": True, "items": [{"app": "testing", "id": "test-waiting"}]})
            self.assertEqual(code, 200)
            self.assertTrue(body["ok"])
            code, body = self._call(server, "GET", "/api/chat/archived?t=secret", protocol=2)
            self.assertEqual(body["items"], [])

            # 7. Create + create/state + upload + commands + usage
            code, body = self._call(server, "POST", "/api/agents/testing/create?t=secret", protocol=2,
                                    body={"request_id": "new-1", "text": "新建测试对话"})
            self.assertEqual(code, 200)
            self.assertEqual(body["id"], "test-new-1")

            code, body = self._call(server, "GET", "/api/agents/testing/create/state?request_id=new-1&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual(body["id"], "test-new-1")

            code, body = self._call(server, "POST", "/api/agents/testing/upload?id=test-running&name=demo.png&t=secret",
                                    protocol=2, raw=b"\x89PNG\r\n")
            self.assertEqual(code, 200)
            self.assertEqual(body["app"], "testing")
            self.assertEqual(body["name"], "demo.png")

            code, body = self._call(server, "GET", "/api/agents/testing/commands?id=test-running&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual(body["items"][0]["name"], "test")

            code, body = self._call(server, "GET", "/api/agents/testing/usage?t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertTrue(body["available"])

    def test_testing_agent_full_chain_to_relay_push_without_extra_fields(self):
        """Step 7 full chain: /api/agents -> /api/chats -> actions -> relay push events.

        Verifies:
        - Production registry excludes testing and never emits testing push events.
        - Protocol 1 hides testing everywhere.
        - Protocol 2 flows through /api/agents, /api/chats, send/stop and notify.Notifier -> relay.
        - Relay push events carry zero new fields (no app_name, min_protocol, app_color, app_icon).
        """
        forbidden_fields = {"app_name", "min_protocol", "app_color", "app_icon"}
        now_box = [time.time()]

        def make_notifier():
            n = notify.Notifier(
                cfg={},
                name="测试电脑",
                log=lambda _msg: None,
                save=lambda: None,
                clock=lambda: now_box[0],
                page_url=lambda: "",
            )
            n.relay.listening = 1
            n.since = now_box[0] - 60
            return n

        def relay_events(n):
            return [m for _, m in sorted((*n.relay.messages, *n.relay.fresh), key=lambda pair: pair[0])]

        # 1. Production list has no testing and emits zero testing events
        self.assertNotIn("testing", registry.ids())
        with patch.object(codex_agent.CodexAgent, "notify_conversations", return_value=([], [])), \
             patch.object(claude_agent.ClaudeAgent, "notify_conversations", return_value=([], [])), \
             patch.object(deepseek_agent.DeepSeekAgent, "notify_conversations", return_value=([], [])):
            prod_notifier = make_notifier()
            prod_notifier.look()
            for ev in relay_events(prod_notifier):
                self.assertNotEqual(ev.get("app"), "testing")
                for snap_item in ev.get("items", []):
                    self.assertNotEqual(snap_item.get("app"), "testing")

        # 2. Full chain under TELEPLY_TEST_AGENTS=1: protocol 1 hidden, protocol 2 -> relay push
        server = self._make_server()
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}), \
             patch.object(codex_agent.CodexAgent, "catalog_entries", return_value=[]), \
             patch.object(claude_agent.ClaudeAgent, "catalog_entries", return_value=[]), \
             patch.object(deepseek_agent.DeepSeekAgent, "catalog_entries", return_value=[]), \
             patch.object(codex_agent.CodexAgent, "notify_conversations", return_value=([], [])), \
             patch.object(claude_agent.ClaudeAgent, "notify_conversations", return_value=([], [])), \
             patch.object(deepseek_agent.DeepSeekAgent, "notify_conversations", return_value=([], [])):
            # Protocol 1 cannot see testing
            code, _ = self._call(server, "GET", "/api/agents?t=secret")
            self.assertEqual(code, 404)
            code, chats_p1 = self._call(server, "GET", "/api/chats?app=all&t=secret")
            self.assertEqual(code, 200)
            self.assertEqual(chats_p1["items"], [])

            # Protocol 2 discovers manifest and lists conversations
            code, agents_body = self._call(server, "GET", "/api/agents?t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual([a["id"] for a in agents_body["agents"]], ["testing"])

            code, chats_p2 = self._call(server, "GET", "/api/chats?app=all&t=secret", protocol=2)
            self.assertEqual(code, 200)
            self.assertEqual({row["id"] for row in chats_p2["items"]}, {"test-running", "test-waiting"})

            # Send a message then poll notify -> running, step, waiting, snapshot reach relay
            code, send_body = self._call(server, "POST", "/api/agents/testing/send?t=secret", protocol=2,
                                         body={"id": "test-running", "text": "推进推送验证", "request_id": "req-push"})
            self.assertEqual(code, 200)
            self.assertTrue(send_body["accepted"])

            notifier = make_notifier()
            notifier.look()
            first_batch = relay_events(notifier)
            first_kinds = {ev.get("kind") for ev in first_batch}
            self.assertTrue({"running", "step", "waiting", "snapshot"} <= first_kinds, first_batch)
            self.assertTrue(any(ev.get("kind") == "running" and ev.get("app") == "testing"
                                and ev.get("chat") == "test-running" for ev in first_batch))
            self.assertTrue(any(ev.get("kind") == "waiting" and ev.get("app") == "testing"
                                and ev.get("chat") == "test-waiting" for ev in first_batch))

            # Stop the running conversation then poll notify -> done event reaches relay
            code, stop_body = self._call(server, "POST", "/api/agents/testing/stop?t=secret", protocol=2,
                                         body={"id": "test-running"})
            self.assertEqual(code, 200)
            self.assertTrue(stop_body["ok"])
            now_box[0] += 5.0
            notifier.look()

            all_events = relay_events(notifier)
            self.assertTrue(any(ev.get("kind") == "done" and ev.get("app") == "testing"
                                and ev.get("chat") == "test-running" for ev in all_events))

            # Verify zero new fields (app_name / min_protocol / app_color / app_icon) added to any push event
            for ev in all_events:
                self.assertEqual(forbidden_fields & set(ev.keys()), set(), f"unexpected fields in push event: {ev}")
                for snap_item in ev.get("items", []):
                    self.assertEqual(
                        forbidden_fields & set(snap_item.keys()), set(),
                        f"unexpected fields in snapshot item: {snap_item}",
                    )


if __name__ == "__main__":
    unittest.main()
