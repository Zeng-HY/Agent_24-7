"""claude_hooks: Claude Code's PermissionRequest held open until the phone answers (10-27), the phone's prompt and taps
through claude_control.Controller, the service's hook address, and the hook in Claude's settings."""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats  # noqa: E402
import claude_control  # noqa: E402
import claude_hooks  # noqa: E402

ITEM = {"app": "claude", "id": "local_test", "title": "试验", "cli": "cli-1"}
QUESTIONS = [
    {"question": "Q1 Which fruit?", "header": "Fruit", "multiSelect": False,
     "options": [{"label": "Apple", "description": "red"}, {"label": "Banana", "description": "yellow"},
                 {"label": "Cherry", "description": "small"}]},
    {"question": "Q2 Which colors?", "header": "Colors", "multiSelect": True,
     "options": [{"label": "Red", "description": "r"}, {"label": "Green", "description": "g"},
                 {"label": "Blue", "description": "b"}]},
]
SUGGESTIONS = [
    {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "npm run lint"}], "behavior": "allow",
     "destination": "localSettings"},
    {"type": "addDirectories", "directories": ["D:\\x"], "destination": "session"},
    {"type": "setMode", "mode": "acceptEdits", "destination": "session"},
]


def request(tool="AskUserQuestion", data=None, session="cli-1", **extra):
    return {"session_id": session, "hook_event_name": "PermissionRequest", "tool_name": tool,
            "tool_input": data if data is not None else {"questions": QUESTIONS}, **extra}


class Held:
    """A Bridge with one request held on its own thread, as remote.Handler holds it."""

    def __init__(self, payload, record=None, gone=lambda: False):
        self.notes = []
        self.bridge = claude_hooks.Bridge(log=lambda text: None, notify=lambda item, text: self.notes.append(text),
                                          sessions=lambda: [ITEM], record=record or (lambda item: None))
        self.bridge.link_wait = 0
        self.result = "running"
        self.thread = threading.Thread(target=self._run, args=(payload, gone), daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 3
        while self.bridge.layout("local_test") is None and time.monotonic() < deadline and self.result == "running":
            time.sleep(.01)

    def _run(self, payload, gone):
        self.result = self.bridge.handle(payload, gone)

    def tap(self, do):
        ask_id, _, stamp = self.bridge.layout("local_test")
        return self.bridge.press("local_test", ask_id, do, stamp)

    def prompt(self):
        held = self.bridge.layout("local_test")
        return held[1] if held else None

    def finished(self, seconds=3):
        self.thread.join(seconds)
        return not self.thread.is_alive()


class Questions(unittest.TestCase):
    def test_one_tap_answers_a_one_choice_question_and_several_are_ticked_then_submitted(self):
        held = Held(request())
        first = held.prompt()
        self.assertEqual((first["title"], first["progress"]), ("Q1 Which fruit?", "1 / 2"))
        self.assertEqual([c["label"] for c in first["choices"]], ["Apple", "Banana", "Cherry"])
        self.assertEqual([n["name"] for n in first["nav"]], ["Skip"])
        self.assertEqual(held.tap(["pick", 1]), "已选：Banana")
        second = held.prompt()
        self.assertEqual((second["title"], second["progress"]), ("Q2 Which colors?", "2 / 2"))
        self.assertEqual([(n["label"], n.get("ready")) for n in second["nav"]], [("上一题", None), ("跳过", None), ("提交", False)])
        self.assertEqual(held.tap(["pick", 2]), "已勾选：Blue")
        held.tap(["pick", 0])
        ticked = held.prompt()
        # the phone apps do not mark ticks, so the label does; the order is the options' order
        self.assertEqual([c["label"] for c in ticked["choices"]], ["✓ Red", "Green", "✓ Blue"])
        self.assertTrue(ticked["nav"][-1]["ready"])
        self.assertEqual(held.tap(["next"]), "已选：Red、Blue，已提交")
        self.assertTrue(held.finished())
        decision = held.result["hookSpecificOutput"]["decision"]
        self.assertEqual(held.result["hookSpecificOutput"]["hookEventName"], "PermissionRequest")
        self.assertEqual(decision["behavior"], "allow")
        self.assertEqual(decision["updatedInput"]["questions"], QUESTIONS)  # sent back as asked
        self.assertEqual(decision["updatedInput"]["answers"], {"Q1 Which fruit?": "Banana", "Q2 Which colors?": "Red, Blue"})
        self.assertEqual(held.notes, ["问：Q1 Which fruit?"])
        self.assertIsNone(held.bridge.layout("local_test"))
        self.assertTrue(held.bridge.just_answered("local_test"))

    def test_back_shows_the_answer_given_and_a_stale_tap_is_refused(self):
        held = Held(request())
        ask_id, _, old = held.bridge.layout("local_test")
        held.tap(["pick", 0])
        with self.assertRaises(chats.ChatError):  # made on the first question, which is no longer shown
            held.bridge.press("local_test", ask_id, ["pick", 1], old)
        self.assertEqual(held.tap(["back"]), "回到上一题")
        again = held.prompt()
        self.assertEqual([c["pressed"] for c in again["choices"]], [True, False, False])
        held.tap(["pick", 2])
        held.tap(["skip"])
        self.assertTrue(held.finished())
        self.assertEqual(held.result["hookSpecificOutput"]["decision"]["updatedInput"]["answers"], {"Q1 Which fruit?": "Cherry"})

    def test_nothing_answered_is_told_as_such(self):
        held = Held(request(data={"questions": QUESTIONS[:1]}))
        self.assertIsNone(held.prompt()["progress"])
        self.assertEqual(held.tap(["skip"]), "跳过了这一题，都没答，已告诉 Claude")
        self.assertTrue(held.finished())
        self.assertEqual(held.result["hookSpecificOutput"]["decision"]["updatedInput"]["answers"], {})


class Permissions(unittest.TestCase):
    def test_a_command_is_allowed_refused_or_allowed_for_good_with_its_rule_only(self):
        payload = request("Bash", {"command": "npm run lint", "description": "Run the linter"}, permission_suggestions=SUGGESTIONS)
        held = Held(payload)
        prompt = held.prompt()
        self.assertEqual(prompt["title"], "Claude 想运行命令\nnpm run lint\nRun the linter")
        self.assertEqual([(c["label"], c["description"]) for c in prompt["choices"]],
                         [("允许", ""), ("允许，以后这类不再问", "Bash(npm run lint)"), ("拒绝", "")])
        self.assertEqual(held.tap(["always"]), "已允许，以后这类不再问")
        self.assertTrue(held.finished())
        # setMode would have switched the conversation to acceptEdits (seen 10-27): only the rule goes back
        self.assertEqual(held.result["hookSpecificOutput"]["decision"], {"behavior": "allow", "updatedPermissions": SUGGESTIONS[:1]})
        refused = Held(request("Write", {"file_path": "D:\\a.txt", "content": "x"}))
        self.assertEqual(refused.prompt()["title"], "Claude 想写文件\nD:\\a.txt")
        self.assertEqual([c["label"] for c in refused.prompt()["choices"]], ["允许", "拒绝"])
        refused.tap(["deny"])
        self.assertTrue(refused.finished())
        self.assertEqual(refused.result["hookSpecificOutput"]["decision"], {"behavior": "deny", "message": claude_hooks.DENIED})

    def test_left_to_the_desktop(self):
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [ITEM])
        bridge.link_wait = 0
        started = time.monotonic()
        self.assertIsNone(bridge.handle(request("ExitPlanMode", {})))  # a plan's approval: not tried
        self.assertIsNone(bridge.handle(request(session="someone-else")))  # Claude Code in a terminal
        self.assertIsNone(bridge.handle({**request(), "hook_event_name": "PreToolUse"}))
        self.assertIsNone(bridge.handle(request(data={"questions": [{"question": "no options"}]})))
        self.assertLess(time.monotonic() - started, 1)


class LetGo(unittest.TestCase):
    def test_claude_code_hanging_up_lets_the_request_go(self):
        hung = threading.Event()
        held = Held(request(), gone=hung.is_set)
        self.assertIsNotNone(held.prompt())
        hung.set()
        self.assertTrue(held.finished())
        self.assertIsNone(held.result)
        self.assertIsNone(held.bridge.layout("local_test"))
        self.assertFalse(held.bridge.just_answered("local_test"))

    def test_answered_on_the_pc_first(self):
        record = Path(tempfile.mkdtemp()) / "cli-1.jsonl"
        call = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_old", "name": "AskUserQuestion", "input": {"questions": QUESTIONS[:1]}},
            {"type": "tool_use", "id": "toolu_1", "name": "AskUserQuestion", "input": {"questions": QUESTIONS}}]}}
        old = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_old", "content": "x"}]}}
        record.write_text(json.dumps(call) + "\n" + json.dumps(old) + "\n", encoding="utf-8")
        held = Held(request(), record=lambda item: record)
        time.sleep(1.3)  # looked at once: the call is found, still unanswered
        self.assertIsNotNone(held.prompt())
        with record.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "answered"}]}}) + "\n")
        self.assertTrue(held.finished(4))
        self.assertIsNone(held.result)
        with self.assertRaises(chats.ChatError):
            held.bridge.press("local_test", "gone", ["pick", 0], [])


class Controller(unittest.TestCase):
    def test_the_phone_sees_the_held_question_and_its_tap_answers_it(self):
        held = Held(request())

        class Desktop:
            def run(self, fn, *args, **kwargs):
                return {"available": False, "reason": "电脑上显示的不是此 Claude 会话", "actions": [{"name": "Banana yellow", "token": "x"}],
                        "prompt": {"title": "from the desktop", "choices": [], "nav": [], "other": None}}

        c = claude_control.Controller(Desktop())
        c.hooks = held.bridge
        with patch.object(chats, "find", lambda app, tid: ITEM):
            state = c.state("local_test", True)
            self.assertEqual(state["prompt"]["title"], "Q1 Which fruit?")
            self.assertEqual(state["actions"], [])  # the desktop card's buttons are not offered beside it
            self.assertEqual(state["reason"], "电脑上显示的不是此 Claude 会话")  # shown whichever conversation the PC shows
            banana = state["prompt"]["choices"][1]
            self.assertNotIn("do", banana)
            result = c.choose("local_test", banana["token"])
            self.assertEqual(result["text"], "已选：Banana")
            self.assertEqual(result["state"]["prompt"]["progress"], "2 / 2")
            submit = result["state"]["prompt"]["nav"][-1]
            self.assertIsNone(submit["token"])  # nothing ticked yet
            red = result["state"]["prompt"]["choices"][0]["token"]
            ticked = c.choose("local_test", red)["state"]["prompt"]["nav"][-1]
            self.assertEqual(c.choose("local_test", ticked["token"])["text"], "已选：Red，已提交")
            self.assertTrue(held.finished())
            # the card the answer closes may still be read off the desktop for a moment: not offered again
            after = c.state("local_test", True)
            self.assertEqual((after["prompt"], after["actions"]), (None, []))


class Address(unittest.TestCase):
    def test_only_claude_code_with_the_hook_key_gets_in(self):
        import remote
        calls = []

        class Hooks:
            def handle(self, payload, gone):
                calls.append(payload)
                return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}} \
                    if payload.get("tool_name") == "Bash" else None

        server = remote.Server(("127.0.0.1", 0), remote.Handler)
        server.cfg = {"claude_hook_key": "k3y", "token": "tok", "bind": "127.0.0.1"}
        server.claude_hooks, server.verbose, server.log = Hooks(), False, remote.Log()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}{claude_hooks.PATH}"
        try:
            def post(key, body, headers=None):
                req = urllib.request.Request(base + key, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.status, r.read()
                except urllib.error.HTTPError as exc:
                    return exc.code, exc.read()
            self.assertEqual(post("k3y", {"tool_name": "Bash"}),
                             (200, json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}).encode()))
            self.assertEqual(post("k3y", {"tool_name": "Read"}), (200, b""))  # no decision
            self.assertEqual(post("wrong", {"tool_name": "Bash"})[0], 403)
            self.assertEqual(post("k3y", {"tool_name": "Bash"}, {"Tailscale-User-Login": "a@b.c"})[0], 403)
            self.assertEqual(len(calls), 2)
        finally:
            server.shutdown()
            server.server_close()


class Settings(unittest.TestCase):
    URL = "http://127.0.0.1:8765/api/claude/hook/k3y"

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "settings.json"
        self.notes = []

    def install(self, url=URL):
        return claude_hooks.install(url, self.notes.append, self.path)

    def ours_by_event(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return claude_hooks._find_ours(data)

    def test_put_in_all_seven_once_and_kept_up_to_date(self):
        self.assertTrue(self.install())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        expected_hooks = {}
        for ev, matcher, timeout in claude_hooks.MANAGED_HOOKS:
            group = {"hooks": [{"type": "http", "url": self.URL, "timeout": timeout}]}
            if matcher is not None:
                group = {"matcher": matcher, **group}
            expected_hooks[ev] = [group]
        self.assertEqual(data, {"hooks": expected_hooks})
        self.assertFalse(self.install())  # as it is: the file is not written again

        # Changing port or key updates all 7 entries cleanly
        new_url = "http://127.0.0.1:9000/api/claude/hook/new"
        self.assertTrue(self.install(new_url))
        ours = self.ours_by_event()
        self.assertEqual(set(ours.keys()), {ev for ev, _, _ in claude_hooks.MANAGED_HOOKS})
        for ev, entries in ours.items():
            self.assertEqual(len(entries), 1, ev)
            self.assertEqual(entries[0][1]["url"], new_url)
        self.assertFalse(self.path.with_name("settings.json.before-teleply").exists())  # there was no file before

    def test_upgrades_legacy_permission_only_install_to_all_seven(self):
        legacy = {"model": "opus", "hooks": {
            "PermissionRequest": [{"hooks": [{"type": "http", "url": self.URL, "timeout": 3600}]}]
        }}
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        self.assertTrue(self.install())
        ours = self.ours_by_event()
        self.assertEqual(set(ours.keys()), {ev for ev, _, _ in claude_hooks.MANAGED_HOOKS})
        self.assertEqual(ours["PermissionRequest"][0][1]["timeout"], 3600)
        self.assertEqual(ours["PreToolUse"][0][0], "*")
        self.assertEqual(ours["PreToolUse"][0][1]["timeout"], 10)
        self.assertEqual(ours["Stop"][0][1]["timeout"], 10)
        # Already had a Teleply hook before upgrade -> does not overwrite/create fresh before-teleply backup
        self.assertFalse(self.path.with_name("settings.json.before-teleply").exists())
        self.assertFalse(self.install())

    def test_the_rest_of_the_users_settings_stays_and_a_copy_is_kept(self):
        mine = {"model": "opus", "hooks": {
            "PermissionRequest": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-check"}]}],
            "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "my-guard"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "beep"}]}]}}
        original = json.dumps(mine, indent=4).encode()
        self.path.write_bytes(original)
        self.assertTrue(self.install())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["hooks"]["PermissionRequest"][0], mine["hooks"]["PermissionRequest"][0])
        self.assertEqual(data["hooks"]["PreToolUse"][0], mine["hooks"]["PreToolUse"][0])
        self.assertEqual(data["hooks"]["Stop"][0], mine["hooks"]["Stop"][0])
        self.assertEqual(len(self.ours_by_event()), 7)
        self.assertEqual(self.path.with_name("settings.json.before-teleply").read_bytes(), original)
        self.assertTrue(claude_hooks.remove(self.notes.append, self.path))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), mine)
        self.assertFalse(claude_hooks.remove(self.notes.append, self.path))

    def test_taken_out_whole_when_it_was_the_only_hook_and_via_claude_config_dir(self):
        import os
        import remote
        self.path.write_text('{"model": "opus"}', encoding="utf-8")
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.dir)}):
            cfg = {"port": 8765, "claude_hook_key": "k3y", "claude_hooks": True}
            remote.hook_settings(cfg, True, self.notes.append)
            self.assertEqual(len(self.ours_by_event()), 7)
            cfg["claude_hooks"] = False
            remote.hook_settings(cfg, True, self.notes.append)
            self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"model": "opus"})

    def test_a_file_it_cannot_read_is_left_alone(self):
        self.path.write_text('{"model": "opus", // a comment\n}', encoding="utf-8")
        self.assertFalse(self.install())
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"model": "opus", // a comment\n}')
        self.assertTrue(self.notes)

        # Bad structure inside one of the managed events is also left untouched
        bad = '{"hooks": {"PreToolUse": "not-a-list"}}'
        self.path.write_text(bad, encoding="utf-8")
        self.assertFalse(self.install())
        self.assertEqual(self.path.read_text(encoding="utf-8"), bad)


class FastEventsAndProcessTests(unittest.TestCase):
    EXE_OK = r"C:\Users\demo\AppData\Roaming\Claude\claude-code\2.1.330\claude.exe"
    EXE_OTHER = r"C:\Tools\other\claude.exe"

    def _bridge(self, *, sessions=None, tcp_map=None, exe_map=None, now_mono=None, now_wall=None,
                list_processes=None, kill_process=None, current_user="tester"):
        mono = now_mono or [100.0]
        wall = now_wall or [1767323000.0]
        changed = []
        bridge = claude_hooks.Bridge(
            log=lambda text: None,
            changed=changed.append,
            sessions=sessions or (lambda: [ITEM]),
            clock=lambda: mono[0],
            wall_clock=lambda: wall[0],
            tcp_owner=(lambda cp, sp: (tcp_map or {}).get((cp, sp), 0)),
            process_exe=(lambda pid: (exe_map or {}).get(pid, "")),
            list_processes=list_processes,
            kill_process=kill_process,
            current_user=current_user,
            server_port=8765,
        )
        return bridge, changed, mono, wall

    def test_each_fast_event_reply_state_and_never_allows(self):
        bridge, changed, mono, wall = self._bridge(
            tcp_map={(50101, 8765): 4200},
            exe_map={4200: self.EXE_OK},
        )
        bridge.refresh_sessions()

        # 1. UserPromptSubmit -> running, returns None
        r1 = bridge.handle({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1", "prompt": "测试"}, client_port=50101)
        self.assertIsNone(r1)
        self.assertTrue(bridge.is_active("local_test"))
        st = bridge.conv_state("local_test")
        self.assertTrue(st["running"])
        self.assertEqual(st["turn_started"], 1767323000)
        self.assertEqual(st["step"], "")
        self.assertEqual(st["pid"], 4200)
        self.assertEqual(bridge.session_pid("cli-1"), 4200)

        # 2. PreToolUse -> step from CLAUDE_STEPS, never returns allow
        wall[0] += 2.0
        r2 = bridge.handle({
            "hook_event_name": "PreToolUse", "session_id": "cli-1",
            "tool_name": "Bash", "tool_use_id": "toolu_1", "tool_input": {"command": "echo hi"},
        }, client_port=50101)
        self.assertIsNone(r2)
        st = bridge.conv_state("local_test")
        self.assertEqual((st["running"], st["step"], st["tool_name"], st["tool_use_id"]), (True, "run", "Bash", "toolu_1"))
        self.assertEqual(st["step_started_at"], 1767323002.0)

        # 3. PostToolUse -> clears current step, returns None
        wall[0] += 1.0
        r3 = bridge.handle({
            "hook_event_name": "PostToolUse", "session_id": "cli-1",
            "tool_name": "Bash", "tool_use_id": "toolu_1",
        }, client_port=50101)
        self.assertIsNone(r3)
        st = bridge.conv_state("local_test")
        self.assertEqual((st["running"], st["step"], st["tool_name"]), (True, "", ""))

        # 4. PreToolUse (Edit) + PostToolUseFailure -> clears step, returns None
        r4 = bridge.handle({
            "hook_event_name": "PreToolUse", "session_id": "cli-1",
            "tool_name": "Edit", "tool_use_id": "toolu_2", "tool_input": {},
        }, client_port=50101)
        self.assertIsNone(r4)
        self.assertEqual(bridge.conv_state("local_test")["step"], "edit")
        r5 = bridge.handle({
            "hook_event_name": "PostToolUseFailure", "session_id": "cli-1",
            "tool_name": "Edit", "tool_use_id": "toolu_2",
        }, client_port=50101)
        self.assertIsNone(r5)
        self.assertEqual(bridge.conv_state("local_test")["step"], "")

        # 5. Notification -> recorded, returns None
        r6 = bridge.handle({
            "hook_event_name": "Notification", "session_id": "cli-1",
            "notification_type": "idle_prompt", "message": "等待输入",
        }, client_port=50101)
        self.assertIsNone(r6)
        self.assertEqual(bridge.conv_state("local_test")["last_notification"]["type"], "idle_prompt")

        # 6. Stop -> idle, returns None
        wall[0] += 5.0
        r7 = bridge.handle({"hook_event_name": "Stop", "session_id": "cli-1"}, client_port=50101)
        self.assertIsNone(r7)
        st = bridge.conv_state("local_test")
        self.assertFalse(st["running"])
        self.assertEqual(st["turn_ended"], 1767323008)
        self.assertEqual(st["step"], "")
        self.assertGreaterEqual(len(changed), 6)

    def test_unknown_session_returns_empty_within_5ms_and_refreshes_in_background(self):
        scan_started = threading.Event()
        release_scan = threading.Event()

        def slow_sessions():
            scan_started.set()
            release_scan.wait(2.0)
            return [ITEM]

        bridge, _, _, _ = self._bridge(sessions=slow_sessions)
        # Cold cache -> unknown returns None immediately (<5 ms), never blocks on slow_sessions
        t0 = time.perf_counter()
        reply = bridge.handle({"hook_event_name": "PreToolUse", "session_id": "unknown-cli", "tool_name": "Bash"})
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertIsNone(reply)
        self.assertLess(elapsed_ms, 5.0, f"unknown session fast-path took {elapsed_ms:.3f} ms")
        self.assertTrue(scan_started.wait(1.0))
        release_scan.set()
        # Wait briefly for background refresh to finish populating cli-1
        deadline = time.monotonic() + 2.0
        while not bridge._session_map and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn("cli-1", bridge._session_map)

        # Warm cache miss for another terminal session: 50 calls stay well under 5 ms each
        for _ in range(50):
            t1 = time.perf_counter()
            self.assertIsNone(bridge.handle({"hook_event_name": "PreToolUse", "session_id": "terminal-only", "tool_name": "Bash"}))
            self.assertLess((time.perf_counter() - t1) * 1000.0, 5.0)

    def test_tcp_pid_only_recorded_for_claude_code_executable(self):
        bridge, _, _, _ = self._bridge(
            tcp_map={(51001, 8765): 9001, (51002, 8765): 9002},
            exe_map={9001: self.EXE_OTHER, 9002: self.EXE_OK},
        )
        bridge.refresh_sessions()
        bridge.handle({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1"}, client_port=51001)
        self.assertEqual(bridge.session_pid("cli-1"), 0)
        bridge.handle({"hook_event_name": "PreToolUse", "session_id": "cli-1", "tool_name": "Read"}, client_port=51002)
        self.assertEqual(bridge.session_pid("cli-1"), 9002)

    def test_stop_flag_applies_to_current_turn_only_and_never_allows(self):
        bridge, _, _, _ = self._bridge()
        bridge.refresh_sessions()
        bridge.handle({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1"})
        bridge.request_stop("local_test")

        # Next PreToolUse gets continue:false + deny (never allow)
        stopped = bridge.handle({"hook_event_name": "PreToolUse", "session_id": "cli-1", "tool_name": "Bash", "tool_use_id": "t1"})
        self.assertEqual(stopped, {
            "continue": False,
            "stopReason": claude_hooks.STOP_REASON,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": claude_hooks.STOP_DENY_REASON,
            },
        })
        self.assertNotIn("allow", json.dumps(stopped))
        self.assertFalse(bridge.conv_state("local_test")["running"])

        # Next turn's UserPromptSubmit clears stop flag -> PreToolUse returns None again
        self.assertIsNone(bridge.handle({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1"}))
        self.assertTrue(bridge.conv_state("local_test")["running"])
        self.assertIsNone(bridge.handle({"hook_event_name": "PreToolUse", "session_id": "cli-1", "tool_name": "Read", "tool_use_id": "t2"}))

        # Stop event also clears an unused stop flag
        bridge.request_stop("local_test")
        self.assertIsNone(bridge.handle({"hook_event_name": "Stop", "session_id": "cli-1"}))
        self.assertFalse(bridge.conv_state("local_test")["stop_requested"])
        self.assertIsNone(bridge.handle({"hook_event_name": "PreToolUse", "session_id": "cli-1", "tool_name": "Read", "tool_use_id": "t3"}))

    def test_http_endpoint_forwards_client_and_server_port_to_bridge(self):
        import remote
        seen_ports = []

        def fake_tcp(cp, sp):
            seen_ports.append((cp, sp))
            return 7777

        bridge, _, _, _ = self._bridge(tcp_map={}, exe_map={7777: self.EXE_OK})
        bridge._tcp_owner = fake_tcp
        bridge.refresh_sessions()

        server = remote.Server(("127.0.0.1", 0), remote.Handler)
        server.cfg = {"claude_hook_key": "k3y", "token": "tok", "bind": "127.0.0.1"}
        server.claude_hooks, server.verbose, server.log = bridge, False, remote.Log()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}{claude_hooks.PATH}k3y"
        try:
            req = urllib.request.Request(
                base,
                json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1"}).encode(),
                {"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual((resp.status, resp.read()), (200, b""))
            self.assertEqual(len(seen_ports), 1)
            self.assertGreater(seen_ports[0][0], 0)
            self.assertEqual(seen_ports[0][1], server.server_address[1])
            self.assertEqual(bridge.session_pid("cli-1"), 7777)
        finally:
            server.shutdown()
            server.server_close()


class FastEventCacheTests(unittest.TestCase):
    """The fast path must not scan the TCP table, the process list or every Claude session on every step."""
    EXE_OK = r"C:\Users\demo\AppData\Roaming\Claude\claude-code\2.1.330\claude.exe"
    EXE_GONE = ""

    def _bridge(self, *, tcp_owner=None, process_exe=None, list_processes=None):
        mono = [100.0]
        calls = {"tcp": [], "exe": []}

        def tcp(cp, sp):
            calls["tcp"].append((cp, sp))
            return tcp_owner(cp, sp) if tcp_owner else 4200

        def exe(pid):
            calls["exe"].append(pid)
            return process_exe(pid) if process_exe else self.EXE_OK

        bridge = claude_hooks.Bridge(
            log=lambda text: None,
            sessions=lambda: [ITEM],
            clock=lambda: mono[0],
            wall_clock=lambda: 1767323000.0 + mono[0],
            tcp_owner=tcp,
            process_exe=exe,
            list_processes=list_processes or (lambda: []),
            kill_process=lambda pid: True,
            current_user="tester",
            server_port=8765,
        )
        bridge.refresh_sessions()
        return bridge, calls, mono

    def _event(self, name, *, port=50101, tool=None):
        payload = {"hook_event_name": name, "session_id": "cli-1"}
        if tool:
            payload.update(tool_name=tool, tool_use_id="t1")
        return self._bridge_handle(payload, port)

    def _bridge_handle(self, payload, port):
        # set by each test to the current bridge
        return self.bridge.handle(payload, client_port=port)

    def test_pid_looked_up_once_then_rechecked_every_60_seconds(self):
        self.bridge, calls, mono = self._bridge()
        self._event("UserPromptSubmit")
        self.assertEqual((len(calls["tcp"]), len(calls["exe"])), (1, 1))
        # every later step within the minute: two dict lookups, no TCP scan and no process query
        self._event("PreToolUse", tool="Bash")
        self._event("PostToolUse", tool="Bash")
        self._event("PreToolUse", tool="Edit")
        self.assertEqual((len(calls["tcp"]), len(calls["exe"])), (1, 1))
        mono[0] += 59.9
        self._event("PostToolUse", port=50102)  # a new connection and still inside the minute: no query
        self.assertEqual((len(calls["tcp"]), len(calls["exe"])), (1, 1))
        mono[0] += 1.0  # past the minute: the PID's path is checked again, but not the TCP table
        self._event("PreToolUse", tool="Read")
        self.assertEqual((len(calls["tcp"]), len(calls["exe"])), (1, 2))
        self.assertEqual(self.bridge.session_pid("cli-1"), 4200)

    def test_a_pid_that_is_gone_is_dropped_and_looked_up_from_the_connection_again(self):
        self.bridge, calls, mono = self._bridge()
        self._event("UserPromptSubmit")
        self.assertEqual((len(calls["tcp"]), len(calls["exe"])), (1, 1))
        mono[0] += 61
        self.bridge._process_exe = lambda pid: (calls["exe"].append(pid), self.EXE_GONE)[1]
        self._event("PreToolUse", tool="Read", port=50109)
        # recheck fails; the connection's port is read from the table, then its path is checked and fails too
        self.assertEqual(len(calls["tcp"]), 2)
        self.assertEqual(calls["tcp"][-1], (50109, 8765))
        self.assertEqual(calls["exe"], [4200, 4200, 4200])
        self.assertEqual(self.bridge.session_pid("cli-1"), 0)

    def test_request_stop_checks_the_process_again_before_ending_a_command(self):
        self.bridge, calls, mono = self._bridge()
        self._event("UserPromptSubmit")
        self._event("PreToolUse", tool="Bash")
        self.assertEqual(len(calls["exe"]), 1)  # the first event recognised the process
        mono[0] += 1  # well within the minute: only request_stop must check again
        self.bridge.request_stop("local_test")
        self.assertEqual(len(calls["exe"]), 2)
        self.assertEqual(len(calls["tcp"]), 1)
        self.assertTrue(self.bridge.conv_state("local_test")["stop_requested"])

    def test_unknown_session_backs_off_per_session_from_2_to_60_seconds(self):
        mono = [0.0]
        started = []

        class FakeThread:
            def __init__(self, target=None, **kwargs):
                self.target = target

            def start(self):
                started.append(self.target)

        bridge = claude_hooks.Bridge(
            log=lambda text: None, sessions=lambda: [], clock=lambda: mono[0],
            wall_clock=lambda: 1767323000.0 + mono[0], server_port=8765,
        )

        def miss(at, session="terminal"):
            bridge._refreshing = False  # pretend the last background scan finished
            mono[0] = at
            self.assertIsNone(bridge.handle({"hook_event_name": "PreToolUse", "session_id": session, "tool_name": "Read"}))
            return len(started)

        with patch.object(claude_hooks.threading, "Thread", FakeThread):
            self.assertEqual(miss(0.0), 1)      # first miss: look at once
            self.assertEqual(miss(1.9), 1)      # then wait 2 s
            self.assertEqual(miss(2.0), 2)      # 2 s: look again, then wait 4 s
            self.assertEqual(miss(5.9), 2)
            self.assertEqual(miss(6.0), 3)      # 4 s later: 8 s
            self.assertEqual(miss(13.9), 3)
            self.assertEqual(miss(14.0), 4)     # 8 s later: 16 s
            self.assertEqual(miss(29.9), 4)
            self.assertEqual(miss(30.0), 5)     # 16 s later: 32 s
            self.assertEqual(miss(61.9), 5)
            self.assertEqual(miss(62.0), 6)     # 32 s later: 60 s (the cap)
            self.assertEqual(miss(121.9), 6)
            self.assertEqual(miss(122.0), 7)    # still 60 s, not more
            self.assertEqual(bridge._unknown_delay["terminal"], 60)
            # a second terminal session has its own backoff: it is not delayed by the first one's minute
            self.assertEqual(miss(122.1, "another-terminal"), 8)

    def test_a_known_session_clears_its_backoff(self):
        mono = [0.0]
        started = []

        class FakeThread:
            def __init__(self, target=None, **kwargs):
                self.target = target

            def start(self):
                started.append(self.target)

        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [ITEM], clock=lambda: mono[0],
                                     wall_clock=lambda: 1767323000.0, server_port=8765)
        bridge._refreshing = False
        with patch.object(claude_hooks.threading, "Thread", FakeThread):
            self.assertIsNone(bridge._lookup_fast_session("cli-1"))
            self.assertIn("cli-1", bridge._unknown_retry_at)
        bridge.register_session(ITEM)
        self.assertNotIn("cli-1", bridge._unknown_retry_at)
        self.assertNotIn("cli-1", bridge._unknown_delay)
        self.assertEqual(bridge._lookup_fast_session("cli-1")["id"], "local_test")


class KillSessionCommandTests(unittest.TestCase):
    CLAUDE_EXE = r"C:\Users\tester\AppData\Roaming\Claude\claude-code\2.1.330\claude.exe"

    def test_kills_only_newest_shell_tree_under_this_claude_and_never_matches_by_command_text(self):
        step_t = 1767323100.0
        procs = [
            # This conversation's claude.exe (must NEVER be killed)
            {"pid": 1000, "ppid": 500, "name": "claude.exe", "executable_path": self.CLAUDE_EXE, "created_at": step_t - 600, "owner": "PC\\tester"},
            # Old shell started BEFORE this step (must NOT be killed)
            {"pid": 1010, "ppid": 1000, "name": "bash.exe", "executable_path": r"C:\git\bash.exe", "created_at": step_t - 30, "owner": "PC\\tester"},
            # Current step's shell + nested children (MUST be killed, children first)
            {"pid": 1020, "ppid": 1000, "name": "bash.exe", "executable_path": r"C:\git\bash.exe", "created_at": step_t + 0.2, "owner": "PC\\tester"},
            {"pid": 1021, "ppid": 1020, "name": "conhost.exe", "executable_path": r"C:\Windows\conhost.exe", "created_at": step_t + 0.3, "owner": "PC\\tester"},
            {"pid": 1022, "ppid": 1020, "name": "ping.exe", "executable_path": r"C:\Windows\ping.exe", "created_at": step_t + 0.4, "owner": "PC\\tester", "cmdline": "ping -n 61 127.0.0.1"},
            # Unrelated process whose command line contains the EXACT same command text (must NEVER be touched!)
            {"pid": 2000, "ppid": 888, "name": "pwsh.exe", "executable_path": r"C:\pwsh.exe", "created_at": step_t + 0.1, "owner": "PC\\tester", "cmdline": "pwsh -c 'ping -n 61 127.0.0.1'"},
            # Another conversation's claude.exe and its shell (must NEVER be touched!)
            {"pid": 3000, "ppid": 500, "name": "claude.exe", "executable_path": self.CLAUDE_EXE, "created_at": step_t - 500, "owner": "PC\\tester"},
            {"pid": 3020, "ppid": 3000, "name": "bash.exe", "executable_path": r"C:\git\bash.exe", "created_at": step_t + 0.5, "owner": "PC\\tester", "cmdline": "ping -n 61 127.0.0.1"},
            # Child owned by another user under our shell (must NOT be killed)
            {"pid": 1029, "ppid": 1020, "name": "helper.exe", "executable_path": r"C:\helper.exe", "created_at": step_t + 0.5, "owner": "NT AUTHORITY\\SYSTEM"},
        ]
        killed = []
        result = claude_hooks.kill_session_command(
            1000,
            step_t,
            list_processes=lambda: procs,
            kill_process=lambda pid: killed.append(pid) or True,
            current_user="tester",
            log=lambda text: None,
        )
        self.assertEqual(result, [1022, 1021, 1020])
        self.assertEqual(killed, [1022, 1021, 1020])
        self.assertNotIn(1000, killed)  # claude.exe untouched
        self.assertNotIn(1010, killed)  # old shell untouched
        self.assertNotIn(2000, killed)  # matching cmdline elsewhere untouched
        self.assertNotIn(3000, killed)  # other conversation untouched
        self.assertNotIn(3020, killed)  # other conversation's shell untouched
        self.assertNotIn(1029, killed)  # other user's process untouched

    def test_refuses_non_claude_code_parent_and_triggers_from_request_stop(self):
        step_t = 1767323200.0
        bad_procs = [
            {"pid": 4000, "ppid": 1, "name": "claude.exe", "executable_path": r"C:\Other\claude.exe", "created_at": step_t - 10, "owner": "tester"},
            {"pid": 4001, "ppid": 4000, "name": "pwsh.exe", "executable_path": r"C:\pwsh.exe", "created_at": step_t + 1, "owner": "tester"},
        ]
        killed = []
        self.assertEqual(
            claude_hooks.kill_session_command(4000, step_t, list_processes=lambda: bad_procs, kill_process=killed.append, current_user="tester"),
            [],
        )
        self.assertEqual(killed, [])

        # End-to-end via Bridge.request_stop while running a Bash tool
        good_procs = [
            {"pid": 5000, "ppid": 1, "name": "claude.exe", "executable_path": self.CLAUDE_EXE, "created_at": step_t - 100, "owner": "tester"},
            {"pid": 5001, "ppid": 5000, "name": "pwsh.exe", "executable_path": r"C:\pwsh.exe", "created_at": step_t + 0.1, "owner": "tester"},
        ]
        bridge = claude_hooks.Bridge(
            log=lambda text: None,
            sessions=lambda: [ITEM],
            wall_clock=lambda: step_t,
            tcp_owner=lambda cp, sp: 5000,
            process_exe=lambda pid: self.CLAUDE_EXE,
            list_processes=lambda: good_procs,
            kill_process=lambda pid: killed.append(pid) or True,
            current_user="tester",
            server_port=8765,
        )
        bridge.refresh_sessions()
        bridge.handle({"hook_event_name": "PreToolUse", "session_id": "cli-1", "tool_name": "Bash", "tool_use_id": "t1"}, client_port=60000)
        res = bridge.request_stop("local_test")
        self.assertTrue(res["killed"])
        self.assertEqual(res["killed_pids"], [5001])
        self.assertEqual(killed, [5001])


class HookControlStateAndStopTests(unittest.TestCase):
    CLAUDE_EXE = r"C:\Users\tester\AppData\Roaming\Claude\claude-code\2.1.330\claude.exe"

    def _make_desktop(self, *, on_screen=False, stop_btn=None):
        unminimized = []
        opened = []

        class FakeDesktop:
            def run(self, fn, *args, **kwargs):
                return fn(*args)

            def _claude_unminimize(self):
                unminimized.append(1)

            def _claude_open(self, *args, **kwargs):
                opened.append(args)

            def _claude_where(self, ctrl):
                return (False, None)

            def _claude_ask(self, root, doc=None):
                return None

            def _find(self, scope, kind, name=None):
                if kind == "ButtonControl":
                    btns = [type("Btn", (), {"Name": "Model: Opus 5.5 High", "IsOffscreen": False, "IsEnabled": True})()]
                    if stop_btn is not None:
                        btns.append(stop_btn)
                    return btns
                return []

        return FakeDesktop(), unminimized, opened

    def test_hook_active_state_does_not_unminimize_and_exposes_available_step_and_stop_offscreen(self):
        wall = [1767323500.0]
        killed = []
        procs = [
            {"pid": 6000, "ppid": 1, "name": "claude.exe", "executable_path": self.CLAUDE_EXE, "created_at": wall[0] - 50, "owner": "tester"},
            {"pid": 6001, "ppid": 6000, "name": "bash.exe", "executable_path": r"C:\git\bash.exe", "created_at": wall[0] + 0.1, "owner": "tester"},
        ]
        bridge = claude_hooks.Bridge(
            log=lambda text: None,
            sessions=lambda: [ITEM],
            wall_clock=lambda: wall[0],
            tcp_owner=lambda cp, sp: 6000,
            process_exe=lambda pid: self.CLAUDE_EXE,
            list_processes=lambda: procs,
            kill_process=lambda pid: killed.append(pid) or True,
            current_user="tester",
            server_port=8765,
        )
        bridge.refresh_sessions()
        bridge.handle({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1"}, client_port=61000)
        bridge.handle({"hook_event_name": "PreToolUse", "session_id": "cli-1", "tool_name": "Bash", "tool_use_id": "t1"}, client_port=61000)

        desktop, unminimized, opened = self._make_desktop(on_screen=False)
        ctrl = claude_control.Controller(desktop)
        ctrl.hooks = bridge
        ctrl._document = lambda item, open_first=False: (_ for _ in ()).throw(chats.ChatError("电脑上显示的不是此 Claude 会话"))

        recorded = {"model": "claude-opus-5-5", "effort": "high", "mode": "auto", "recorded_at": 1}
        with patch("claude_control.chats.find", return_value=ITEM), \
             patch("claude_control.settings", return_value=recorded), \
             patch("claude_control.chats.conv_path", return_value=None), \
             patch("claude_control.chats.summary", return_value={"status": "unknown", "turn_started": 0, "turn_ended": 0, "step": ""}), \
             patch("claude_control.winctl.input_desktop_ready", return_value=False):  # even while PC is locked!
            state = ctrl.state("local_test", True)
            self.assertEqual(unminimized, [])  # must NOT unminimize when hooks are active
            self.assertTrue(state["available"])
            self.assertFalse(state["on_screen"])
            self.assertTrue(state["running"])
            self.assertEqual(state["step"], "run")
            self.assertEqual(state["settings"], recorded)
            self.assertTrue(state.get("stop_token"))

            # Pressing Stop while PC is locked & off-screen: sets stop flag, kills command, never switches window
            stop_res = ctrl.choose("local_test", state["stop_token"])
            self.assertTrue(stop_res["ok"])
            self.assertTrue(stop_res["killed"])
            self.assertEqual(killed, [6001])
            self.assertEqual(opened, [])
            self.assertTrue(bridge.conv_state("local_test")["stop_requested"])

        # After Stop hook -> running False, no stop_token
        bridge.handle({"hook_event_name": "Stop", "session_id": "cli-1"})
        with patch("claude_control.chats.find", return_value=ITEM), \
             patch("claude_control.settings", return_value=recorded), \
             patch("claude_control.chats.conv_path", return_value=None), \
             patch("claude_control.chats.summary", return_value={"status": "idle", "turn_started": 1767323500, "turn_ended": 1767323510, "step": ""}):
            idle_state = ctrl.state("local_test", True)
            self.assertTrue(idle_state["available"])
            self.assertFalse(idle_state["running"])
            self.assertEqual(idle_state["step"], "")
            self.assertNotIn("stop_token", idle_state)

    def test_hook_active_stop_also_clicks_visible_window_stop_when_unlocked_without_switching(self):
        wall = [1767323600.0]
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [ITEM], wall_clock=lambda: wall[0])
        bridge.refresh_sessions()
        bridge.handle({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1"})

        invoked = []
        stop_btn = type("StopBtn", (), {
            "Name": "Stop", "IsOffscreen": False, "IsEnabled": True,
            "GetInvokePattern": lambda self: type("P", (), {"Invoke": lambda s: invoked.append(1) or True})(),
        })()
        desktop, unminimized, opened = self._make_desktop(on_screen=True, stop_btn=stop_btn)
        ctrl = claude_control.Controller(desktop)
        ctrl.hooks = bridge
        ctrl._document = lambda item, open_first=False: (1, "root", "doc")

        with patch("claude_control.chats.find", return_value=ITEM), \
             patch("claude_control.settings", return_value={"model": "claude-opus-5-5", "effort": "high", "mode": "auto"}), \
             patch("claude_control.chats.conv_path", return_value=None), \
             patch("claude_control.chats.summary", return_value={"status": "running", "turn_started": 1767323600, "turn_ended": 0, "step": ""}), \
             patch("claude_control.winctl.input_desktop_ready", return_value=True):
            state = ctrl.state("local_test", True)
            res = ctrl.choose("local_test", state["stop_token"])
            self.assertTrue(res["ok"])
            self.assertEqual(invoked, [1])  # visible window Stop clicked too
            self.assertEqual(opened, [])    # never switched conversations
            self.assertEqual(unminimized, [])

    def test_hook_inactive_preserves_legacy_unminimize_and_offscreen_unavailable(self):
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [ITEM])
        desktop, unminimized, _ = self._make_desktop(on_screen=False)
        ctrl = claude_control.Controller(desktop)
        ctrl.hooks = bridge
        ctrl._document = lambda item, open_first=False: (_ for _ in ()).throw(chats.ChatError("电脑上显示的不是此 Claude 会话"))

        with patch("claude_control.chats.find", return_value=ITEM), \
             patch("claude_control.settings", return_value={"model": "claude-opus-5-5"}), \
             patch("claude_control.chats.conv_path", return_value=None), \
             patch("claude_control.chats.summary", return_value={"status": "idle", "turn_started": 0, "turn_ended": 0, "step": ""}):
            state = ctrl.state("local_test", True)
            self.assertEqual(len(unminimized), 1)  # legacy behavior preserved when hooks inactive
            self.assertFalse(state["available"])
            self.assertFalse(state["on_screen"])

    def test_hook_running_cross_checks_record_for_pc_manual_stop(self):
        wall = [1767323700.0]
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [ITEM], wall_clock=lambda: wall[0])
        bridge.refresh_sessions()
        bridge.handle({"hook_event_name": "UserPromptSubmit", "session_id": "cli-1"})
        # PC user clicked Stop -> Claude Code emits no Stop hook, but transcript shows idle ended at >= turn_started
        desktop, _, _ = self._make_desktop(on_screen=False)
        ctrl = claude_control.Controller(desktop)
        ctrl.hooks = bridge
        ctrl._document = lambda item, open_first=False: (_ for _ in ()).throw(chats.ChatError("不在前台"))
        with patch("claude_control.chats.find", return_value=ITEM), \
             patch("claude_control.settings", return_value={}), \
             patch("claude_control.chats.conv_path", return_value=None), \
             patch("claude_control.chats.summary", return_value={"status": "idle", "turn_started": 1767323700, "turn_ended": 1767323705, "step": ""}):
            state = ctrl.state("local_test", True)
            self.assertFalse(state["running"])
            self.assertNotIn("stop_token", state)


class ChatsHookRecordDisplayTests(unittest.TestCase):
    HOOK_URL = "http://127.0.0.1:8765/api/claude/hook/testkey"

    def test_teleply_stop_attachment_shows_stopped_and_ends_turn(self):
        lines = [
            json.dumps({"type": "user", "uuid": "u1", "timestamp": "2026-11-24T04:00:00Z",
                        "message": {"role": "user", "content": "跑个测试"}}, ensure_ascii=False).encode(),
            json.dumps({"type": "assistant", "uuid": "a1", "timestamp": "2026-11-24T04:00:01Z",
                        "message": {"role": "assistant", "stop_reason": "tool_use", "content": [
                            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "echo one"}}]}},
                       ensure_ascii=False).encode(),
            json.dumps({"type": "user", "uuid": "u2", "timestamp": "2026-11-24T04:00:02Z",
                        "message": {"role": "user", "content": [
                            {"type": "tool_result", "tool_use_id": "toolu_1",
                             "content": "PreToolUse:Bash hook error: 用户在手机上按了停止（遥应）。不要再调用任何工具。",
                             "is_error": True}]}}, ensure_ascii=False).encode(),
            json.dumps({"type": "attachment", "uuid": "att1", "timestamp": "2026-11-24T04:00:02Z",
                        "attachment": {"type": "hook_stopped_continuation",
                                       "message": "用户在手机上停止了这一轮（遥应）",
                                       "hookName": "PreToolUse:Bash", "toolUseID": "toolu_1",
                                       "hookEvent": "PreToolUse"}}, ensure_ascii=False).encode(),
        ]
        msgs, state = chats.parse_claude(lines)
        self.assertEqual([(m["role"], m["text"]) for m in msgs if m["role"] != "tool"], [
            ("user", "跑个测试"),
            ("event", "已在手机上停止"),
        ])
        self.assertIs(state["running"], False)
        self.assertEqual(state["turn_ended"], "2026-11-24T04:00:02Z")
        self.assertEqual(state["step"], "")

        # Also verify notify_turn_end recognizes Teleply hook stop
        from agents.claude import ClaudeAgent
        end = ClaudeAgent().notify_turn_end(lines)
        self.assertEqual(end["state"], "stopped")

    def test_teleply_hook_noise_hidden_and_third_party_stop_not_claimed(self):
        lines = [
            json.dumps({"type": "user", "uuid": "u1", "timestamp": "2026-11-24T04:01:00Z",
                        "message": {"role": "user", "content": "你好"}}, ensure_ascii=False).encode(),
            json.dumps({"type": "attachment", "uuid": "n1", "timestamp": "2026-11-24T04:01:01Z",
                        "attachment": {"type": "hook_non_blocking_error", "hookName": "UserPromptSubmit",
                                       "stderr": "connect ECONNREFUSED 127.0.0.1:8765", "stdout": "", "exitCode": 0}},
                       ensure_ascii=False).encode(),
            json.dumps({"type": "attachment", "uuid": "s1", "timestamp": "2026-11-24T04:01:02Z",
                        "attachment": {"type": "hook_success", "hookName": "PostToolUse:Bash",
                                       "command": self.HOOK_URL, "exitCode": 200}}, ensure_ascii=False).encode(),
            json.dumps({"type": "system", "uuid": "sys1", "subtype": "stop_hook_summary",
                        "timestamp": "2026-11-24T04:01:03Z",
                        "hookInfos": [{"command": self.HOOK_URL}],
                        "hookErrors": ["connect ECONNREFUSED 127.0.0.1:8765"]}, ensure_ascii=False).encode(),
            # Another tool's hook_stopped_continuation (no '（遥应）'): must NOT be labeled as Teleply phone stop
            json.dumps({"type": "attachment", "uuid": "other1", "timestamp": "2026-11-24T04:01:04Z",
                        "attachment": {"type": "hook_stopped_continuation", "message": "stopped by user script",
                                       "hookName": "PreToolUse:Bash", "hookEvent": "PreToolUse"}},
                       ensure_ascii=False).encode(),
        ]
        msgs, state = chats.parse_claude(lines)
        self.assertEqual([(m["role"], m["text"]) for m in msgs], [("user", "你好")])
        self.assertIs(state["running"], True)


if __name__ == "__main__":
    unittest.main()
