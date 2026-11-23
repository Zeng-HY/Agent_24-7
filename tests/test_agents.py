"""The agent list, its manifests, detection and the test-only assistant."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import remote
from agents import registry
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


if __name__ == "__main__":
    unittest.main()
