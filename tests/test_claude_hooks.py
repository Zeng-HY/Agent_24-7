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
        self.path = Path(tempfile.mkdtemp()) / "settings.json"
        self.notes = []

    def install(self, url=URL):
        return claude_hooks.install(url, self.notes.append, self.path)

    def ours(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [h for g in data.get("hooks", {}).get("PermissionRequest", []) for h in g["hooks"] if claude_hooks._ours(h)]

    def test_put_in_once_and_kept_up_to_date(self):
        self.assertTrue(self.install())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"hooks": {"PermissionRequest": [{"hooks": [{"type": "http", "url": self.URL, "timeout": 3600}]}]}})
        self.assertFalse(self.install())  # as it is: the file is not written again
        self.assertTrue(self.install("http://127.0.0.1:9000/api/claude/hook/new"))  # another port or key replaces it
        self.assertEqual([h["url"] for h in self.ours()], ["http://127.0.0.1:9000/api/claude/hook/new"])
        self.assertFalse(self.path.with_name("settings.json.before-teleply").exists())  # there was no file before

    def test_the_rest_of_the_users_settings_stays_and_a_copy_is_kept(self):
        mine = {"model": "opus", "hooks": {
            "PermissionRequest": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-check"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "beep"}]}]}}
        original = json.dumps(mine, indent=4).encode()
        self.path.write_bytes(original)
        self.assertTrue(self.install())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["hooks"]["Stop"], mine["hooks"]["Stop"])
        self.assertEqual(data["hooks"]["PermissionRequest"][0], mine["hooks"]["PermissionRequest"][0])
        self.assertEqual(len(self.ours()), 1)
        self.assertEqual(self.path.with_name("settings.json.before-teleply").read_bytes(), original)
        self.assertTrue(claude_hooks.remove(self.notes.append, self.path))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), mine)
        self.assertFalse(claude_hooks.remove(self.notes.append, self.path))

    def test_taken_out_whole_when_it_was_the_only_hook(self):
        self.path.write_text('{"model": "opus"}', encoding="utf-8")
        self.install()
        claude_hooks.remove(self.notes.append, self.path)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"model": "opus"})

    def test_a_file_it_cannot_read_is_left_alone(self):
        self.path.write_text('{"model": "opus", // a comment\n}', encoding="utf-8")
        self.assertFalse(self.install())
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"model": "opus", // a comment\n}')
        self.assertTrue(self.notes)


if __name__ == "__main__":
    unittest.main()
