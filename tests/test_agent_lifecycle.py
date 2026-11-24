"""Per-assistant server lifecycle (batch 3): services live in server.agent_services.

Everything here is fake: no real named pipes, no real settings files, no desktop apps.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import claude_hooks
import codex_apptools
import codex_hooks
import codex_question_dismiss
import deepseek_control
import relay_desktop
import remote
from agents import registry
from agents.claude import ClaudeAgent
from agents.codex import CodexAgent
from agents.deepseek import DeepSeekAgent
from agents.testing import TestingAgent as FakeTestingAgent
from relay_controller import DesktopController


class ServiceSlotTests(unittest.TestCase):
    def test_the_slot_is_created_on_demand_and_one_per_assistant(self):
        agent = FakeTestingAgent()
        server = SimpleNamespace()
        marker = object()
        self.assertIsNone(agent.service(server))
        self.assertIs(agent.set_service(server, marker), marker)
        self.assertIs(agent.service(server), marker)
        self.assertIs(server.agent_services["testing"], marker)


class FakeAgent:
    def __init__(self, ident, calls, *, fail_close=False):
        self.id = ident
        self.calls = calls
        self.fail_close = fail_close

    def on_server_start(self, cfg, apps, log):
        self.calls.append((self.id, "start", tuple(apps), log))

    def on_server_init(self, server):
        self.calls.append((self.id, "init", server))

    def on_server_close(self, server):
        self.calls.append((self.id, "close", server))
        if self.fail_close:
            raise RuntimeError("fake close failure")


class StartCloseTests(unittest.TestCase):
    def test_every_listed_agent_is_started_initialised_and_closed(self):
        calls = []
        agents = [FakeAgent("one", calls), FakeAgent("two", calls)]
        server = SimpleNamespace(machine={"apps": ["one", "two"]})
        notes = []
        with patch.object(registry, "load", return_value=agents):
            remote.start_agents(server, {"x": 1}, notes.append)
            remote.close_agents(server)
        self.assertEqual([c[1] for c in calls], ["start", "init", "start", "init", "close", "close"])
        self.assertEqual(calls[0][2], ("one", "two"))
        self.assertEqual(calls[0][3], notes.append)
        self.assertIs(calls[1][2], server)
        self.assertIs(calls[4][2], server)

    def test_one_failing_close_does_not_skip_the_rest(self):
        calls = []
        agents = [FakeAgent("one", calls, fail_close=True), FakeAgent("two", calls)]
        with patch.object(registry, "load", return_value=agents):
            remote.close_agents(SimpleNamespace())
        self.assertEqual([c[0] for c in calls], ["one", "two"])


class FakeBridge:
    def __init__(self, log, notify=None, changed=None):
        self.log = log
        self.notify = notify
        self.changed = changed
        self.server_port = None

    def refresh_sessions(self):
        pass


class ClaudeServiceTests(unittest.TestCase):
    def _server(self, cfg=None):
        return SimpleNamespace(
            agent_services={},
            cfg=dict(cfg or {}),
            notifier=SimpleNamespace(asking=lambda *a: None),
            claude=SimpleNamespace(cache={"tid": "cached"}),
            log=SimpleNamespace(write=lambda _t: None),
            server_address=("127.0.0.1", 54321),
        )

    def test_the_hook_bridge_is_created_by_the_module_and_put_in_the_slot(self):
        server = self._server()
        with patch.object(claude_hooks, "Bridge", FakeBridge):
            ClaudeAgent().on_server_init(server)
        bridge = server.claude_hooks
        self.assertIsInstance(bridge, FakeBridge)
        self.assertIs(server.claude.hooks, bridge)
        self.assertIs(server.agent_services["claude"], bridge)
        self.assertEqual(bridge.server_port, 54321)
        self.assertEqual(bridge.notify, server.notifier.asking)
        bridge.changed("tid")
        self.assertEqual(server.claude.cache, {})

    def test_turning_hooks_off_leaves_the_controller_without_a_bridge(self):
        server = self._server({"claude_hooks": False})
        with patch.object(claude_hooks, "Bridge", FakeBridge):
            ClaudeAgent().on_server_init(server)
        self.assertIsNone(server.claude.hooks)
        self.assertIs(server.agent_services["claude"], server.claude_hooks)


class FakeEvents:
    def __init__(self):
        self.started = 0
        self.closed = 0

    def start(self):
        self.started += 1

    def close(self):
        self.closed += 1


class DeepSeekServiceTests(unittest.TestCase):
    def test_events_start_only_with_its_folder_and_close_on_exit(self):
        with tempfile.TemporaryDirectory() as td:
            events = FakeEvents()
            server = SimpleNamespace(deepseek=SimpleNamespace(events=events), agent_services={})
            with patch.object(deepseek_control, "HOME", Path(td)):
                agent = DeepSeekAgent()
                agent.on_server_init(server)
                self.assertEqual(events.started, 1)
                self.assertIs(server.agent_services["deepseek"], events)
                agent.on_server_close(server)
                self.assertEqual(events.closed, 1)

    def test_events_do_not_start_without_the_folder(self):
        with tempfile.TemporaryDirectory() as td:
            events = FakeEvents()
            server = SimpleNamespace(deepseek=SimpleNamespace(events=events), agent_services={})
            with patch.object(deepseek_control, "HOME", Path(td) / "missing"):
                DeepSeekAgent().on_server_init(server)
            self.assertEqual(events.started, 0)


class FakeDismiss:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kw = kwargs


class FakeHookServer:
    def __init__(self, **kwargs):
        self.kw = kwargs

    def close(self):
        pass


class CodexServiceTests(unittest.TestCase):
    def test_the_dismiss_manager_is_created_with_the_same_config_values(self):
        apptools = SimpleNamespace(
            pop_queued_for_stop_hook=lambda tid: None,
            queues=SimpleNamespace(has_any=lambda: False),
            _status_cache={},
            hooks=None,
        )
        cfg = {"codex_auto_dismiss_answered_questions": True, "codex_dismiss_verified_version": "1.2.3"}
        log = SimpleNamespace(write=lambda _t: None)
        bridge = SimpleNamespace(log=log.write)
        server = SimpleNamespace(cfg=cfg, machine={"apps": []}, log=log, codex=bridge)
        with patch.object(CodexAgent, "_apptools_for", lambda self, b: apptools), \
                patch.object(codex_hooks, "CodexHookServer", FakeHookServer), \
                patch.object(codex_question_dismiss, "DismissManager", FakeDismiss):
            CodexAgent().on_server_init(server)
        manager = bridge.dismiss_manager
        self.assertIsInstance(manager, FakeDismiss)
        self.assertIs(manager.args[0], bridge)
        self.assertTrue(manager.kw["enabled"])
        self.assertEqual(manager.kw["verified_version"], "1.2.3")
        self.assertIs(manager.kw["log"], log.write)


class HookAddressTests(unittest.TestCase):
    def setUp(self):
        self.server = remote.Server(("127.0.0.1", 0), remote.Handler)
        self.server.cfg = {"claude_hook_key": "k3y", "token": "tok", "bind": "127.0.0.1"}
        self.server.claude_hooks = None
        self.server.verbose = False
        self.server.log = remote.Log()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, path, body, headers=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}", json.dumps(body).encode(),
            {"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_claude_hook_keeps_the_same_status_and_bytes(self):
        reply = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
        with patch.object(claude_hooks, "dispatch", return_value=reply):
            self.assertEqual(
                self.post(claude_hooks.PATH + "k3y", {"tool_name": "Bash"}),
                (200, json.dumps(reply, ensure_ascii=False).encode()))

    def test_claude_hook_refuses_a_bad_key_or_tailscale_header(self):
        self.assertEqual(self.post(claude_hooks.PATH + "wrong", {})[0], 403)
        self.assertEqual(self.post(claude_hooks.PATH + "k3y", {}, {"Tailscale-User-Login": "a@b.c"})[0], 403)

    def test_a_fake_agent_receives_a_request_on_its_own_hook_path(self):
        with patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"}):
            code, body = self.post("/api/testing/hook/abc", {"hello": "world"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body),
                         {"ok": True, "path": "/api/testing/hook/abc", "body": {"hello": "world"}})

    def test_other_paths_still_go_through_the_token(self):
        self.assertEqual(self.post("/api/nothing", {})[0], 403)


class FakeUninstallAgent:
    def __init__(self, ident, calls, *, result=True, fail=False):
        self.id = ident
        self.calls = calls
        self.result = result
        self.fail = fail

    def uninstall(self, log):
        self.calls.append(self.id)
        if self.fail:
            raise RuntimeError("fake uninstall failure")
        return self.result


class UninstallSwitchTests(unittest.TestCase):
    def _run(self, flag, agents):
        with patch.object(registry, "load", return_value=agents), patch.object(sys, "argv", ["AgentRemote.exe", flag]):
            return relay_desktop.main()

    def test_remove_agent_hooks_calls_every_agent_and_reports_a_failure(self):
        calls = []
        agents = [FakeUninstallAgent("one", calls), FakeUninstallAgent("two", calls, fail=True),
                  FakeUninstallAgent("three", calls)]
        self.assertEqual(self._run("--remove-agent-hooks", agents), 1)
        self.assertEqual(calls, ["one", "two", "three"])

    def test_a_false_result_is_a_failure_too(self):
        calls = []
        self.assertEqual(self._run("--remove-agent-hooks", [FakeUninstallAgent("one", calls, result=False)]), 1)

    def test_both_old_switches_do_the_same_thing(self):
        for flag in ("--remove-claude-hook", "--remove-codex-hook"):
            calls = []
            agents = [FakeUninstallAgent("one", calls), FakeUninstallAgent("two", calls)]
            self.assertEqual(self._run(flag, agents), 0)
            self.assertEqual(calls, ["one", "two"])


class AgentUninstallTests(unittest.TestCase):
    def test_claude_takes_out_only_its_own_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            settings = Path(td) / "settings.json"
            user = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "beep"}]}]}}
            settings.write_text(json.dumps(user), encoding="utf-8")
            notes = []
            claude_hooks.install("http://127.0.0.1:8765" + claude_hooks.PATH + "k3y", notes.append, settings)
            with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": td}):
                self.assertTrue(ClaudeAgent().uninstall(notes.append))
            self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), user)

    def test_codex_takes_out_only_its_own_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "codex"
            home.mkdir()
            user = {"hooks": {"Stop": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "beep.exe", "timeout": 10}]}]}}
            (home / "hooks.json").write_text(json.dumps(user), encoding="utf-8")
            codex_hooks.install_hooks(Path(td) / "TeleplyCodexHook.exe", codex_home=home, log=lambda _t: None)
            original = codex_hooks.default_codex_home()
            codex_hooks.set_default_codex_home_override(home)
            try:
                self.assertTrue(CodexAgent().uninstall(lambda _t: None))
            finally:
                codex_hooks.set_default_codex_home_override(original)
            self.assertEqual(json.loads((home / "hooks.json").read_text(encoding="utf-8")), user)


class FakeHintAgent:
    def __init__(self, ident, hint="", *, fail=False):
        self.id = ident
        self.hint = hint
        self.fail = fail
        self.asked = 0

    def status_hint(self, cfg):
        self.asked += 1
        if self.fail:
            raise RuntimeError("fake hint failure")
        return self.hint


class StatusHintTests(unittest.TestCase):
    def _controller(self):
        controller = DesktopController.__new__(DesktopController)
        controller.online = True
        controller.cfg = {}
        return controller

    def test_the_first_non_empty_hint_wins_and_a_failure_is_skipped(self):
        controller = self._controller()
        first = FakeHintAgent("one")
        broken = FakeHintAgent("two", fail=True)
        hint = FakeHintAgent("three", "去信任钩子")
        with patch.object(registry, "load", return_value=[first, broken, hint]):
            self.assertEqual(controller._agent_hint(), "去信任钩子")
        self.assertEqual([a.asked for a in (first, broken, hint)], [1, 1, 1])

    def test_not_online_shows_nothing_and_asks_nobody(self):
        controller = self._controller()
        controller.online = False
        agent = FakeHintAgent("one", "去信任钩子")
        with patch.object(registry, "load", return_value=[agent]):
            self.assertEqual(controller._agent_hint(), "")
        self.assertEqual(agent.asked, 0)


class CodexStatusHintTests(unittest.TestCase):
    def test_pending_trust_on_the_apptools_route_shows_the_trust_hint(self):
        with patch.object(codex_apptools, "current_route", return_value="apptools"), \
                patch.object(codex_hooks, "read_trust_status", return_value="pending_trust"):
            self.assertEqual(CodexAgent().status_hint({}), codex_hooks.TRUST_HINT)

    def test_other_states_and_the_off_switch_show_nothing(self):
        cases = [("legacy", "pending_trust", {}), ("apptools", "enabled", {}),
                 ("apptools", "pending_trust", {"codex_hooks": False})]
        for route, trust, cfg in cases:
            with patch.object(codex_apptools, "current_route", return_value=route), \
                    patch.object(codex_hooks, "read_trust_status", return_value=trust):
                self.assertEqual(CodexAgent().status_hint(cfg), "")


    def test_nothing_to_remove_is_still_success(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": td}):
                self.assertTrue(ClaudeAgent().uninstall(lambda _t: None))
            original = codex_hooks.default_codex_home()
            codex_hooks.set_default_codex_home_override(Path(td) / "empty-codex")
            try:
                self.assertTrue(CodexAgent().uninstall(lambda _t: None))
            finally:
                codex_hooks.set_default_codex_home_override(original)


if __name__ == "__main__":
    unittest.main()
