"""Tests for dev.51: preventing Claude's 'Stop N nested sessions' and other non-question dock buttons
from turning into fake question cards on the phone (design.md section 1)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats  # noqa: E402
import claude_control  # noqa: E402
import claude_hooks  # noqa: E402

# Control types, names, tops, offscreen, enabled flags taken from research/dock-stop-nested-sessions.txt
# (Claude desktop 6.x approval-dock while idle with 2 nested sessions running).
NESTED_SESSION_DOCK = [
    (1, "ButtonControl", "Scroll to bottom", 900, False, True),
    (1, "StatusBarControl", "", 955, False, True),
    (1, "StatusBarControl", "", 955, False, True),
    (1, "StatusBarControl", "", 955, False, True),
    (1, "GroupControl", "", 955, False, True),
    (1, "StatusBarControl", "", 0, False, True),
    (1, "StatusBarControl", "", 955, False, True),
    (1, "StatusBarControl", "", 955, False, True),
    (2, "TextControl", "Chat mode", 956, True, True),
    (1, "StatusBarControl", "", 955, False, True),
    (1, "GroupControl", "", 956, False, True),
    (2, "GroupControl", "", 964, False, True),
    (3, "GroupControl", "", 964, False, True),
    (4, "GroupControl", "", 964, False, True),
    (5, "GroupControl", "", 964, False, True),
    (6, "EditControl", "Prompt", 967, False, True),
    (7, "GroupControl", "", 967, False, True),
    (6, "StatusBarControl", "", 964, False, True),
    (3, "GroupControl", "", 964, False, True),
    (4, "ButtonControl", "Add", 964, False, True),
    (4, "GroupControl", "", 964, False, True),
    (3, "GroupControl", "", 964, False, True),
    (4, "GroupControl", "", 964, False, True),
    (5, "GroupControl", "", 964, False, True),
    (6, "ButtonControl", "Stop 2 nested sessions", 964, False, True),
    (4, "ButtonControl", "Press and hold to record", 964, False, True),
    (1, "GroupControl", "", 992, False, True),
    (2, "ButtonControl", "Model: Opus 5.5 Max 3.5x or more usage", 1008, False, True),
    (3, "TextControl", "Opus 5.5", 1012, False, True),
    (3, "TextControl", "Max", 1012, False, True),
    (3, "ImageControl", "3.5x or more usage", 1014, False, True),
    (2, "ButtonControl", "Auto", 1008, False, True),
    (2, "ButtonControl", "Usage: Weekly · all models: 37%, Resets Sat 3:00 PM", 1008, False, True),
    (2, "StatusBarControl", "", 1019, False, True),
    (2, "StatusBarControl", "", 1019, False, True),
    (1, "StatusBarControl", "", 1031, False, True),
]

DOCK_CLASS = "group/approval-dock pointer-events-auto relative flex flex-col"
CARD_CLASS = "epitaxy-approval-card relative isolate flex flex-col"


class FakeRect:
    def __init__(self, top: int, width: int = 80, height: int = 28):
        self.top = top
        self._w = width
        self._h = height

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h


class FakeCtrl:
    def __init__(self, depth: int, kind: str, name: str, top: int, off: bool = False, enabled: bool = True):
        self.depth = depth
        self.ControlTypeName = kind
        self.Name = name
        self.IsOffscreen = off
        self.IsEnabled = enabled
        self.BoundingRectangle = FakeRect(top)
        self.invoked = 0

    def GetTogglePattern(self):
        return None

    def GetSelectionItemPattern(self):
        return None

    def GetInvokePattern(self):
        ctrl = self

        class Pattern:
            def Invoke(self):
                ctrl.invoked += 1
                return True

        return Pattern()


class FakeWalk:
    def __init__(self, rows):
        self._rows = rows

    def WalkControl(self, node, maxDepth=30):
        for row in self._rows:
            if isinstance(row, tuple) and len(row) == 2 and isinstance(row[0], FakeCtrl):
                yield row
            else:
                depth, kind, name, top, off, enabled = row
                yield FakeCtrl(depth, kind, name, top, off, enabled), depth


def make_controller(rows, dock_cls=DOCK_CLASS, hooks=None):
    dock = SimpleNamespace(ClassName=dock_cls)
    model_btn = SimpleNamespace(Name="Model: Opus 5.5 Max", IsOffscreen=False, IsEnabled=True)

    class Desktop:
        auto = FakeWalk(rows)

        def run(self, fn, *args, **kwargs):
            return fn(*args)

        def _claude_where(self, ctrl):
            return (False, dock)

        def _claude_unminimize(self):
            pass

        def _claude_ask(self, root, doc=None):
            return dock

        def _find(self, scope, kind, name=None):
            if kind == "ButtonControl":
                return [model_btn]
            return []

    ctrl = claude_control.Controller(Desktop())
    ctrl.hooks = hooks
    ctrl._document = lambda item, open_first=False: (1, "root", "doc")
    return ctrl, dock


def read_state(ctrl, transcript_path=None, tid="local_fake_1"):
    item = {"id": tid, "title": "测试对话"}
    recorded = {"model": "claude-opus-5-5", "effort": "max", "mode": "auto", "recorded_at": 1}
    with patch("claude_control.settings", return_value=recorded), \
         patch("claude_control.chats.conv_path", return_value=transcript_path), \
         patch("claude_control.chats.summary", return_value={"status": "idle"}):
        return ctrl._read_once(item)


class RecordedNestedSessionsTests(unittest.TestCase):
    def test_recorded_nested_session_dock_produces_no_prompt_or_actions(self):
        ctrl, dock = make_controller(NESTED_SESSION_DOCK, hooks=None)
        options, prompt = ctrl._dock_read(dock)
        self.assertEqual(options, [])
        self.assertIsNone(prompt)

        state = read_state(ctrl)
        self.assertIsNone(state["prompt"])
        self.assertEqual(state["actions"], [])

        ctrl.hooks = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [])
        state_with_hooks = read_state(ctrl)
        self.assertIsNone(state_with_hooks["prompt"])
        self.assertEqual(state_with_hooks["actions"], [])


class Layer1ComposerBlockTests(unittest.TestCase):
    def test_arbitrary_control_inside_composer_block_is_ignored(self):
        # Even if a composer button has an unknown name (not caught by Layer 2), Layer 1 excludes it.
        rows = [
            (1, "GroupControl", "", 956, False, True),
            (2, "GroupControl", "", 964, False, True),
            (3, "EditControl", "Prompt", 967, False, True),
            (3, "TextControl", "Draft hint", 960, False, True),
            (3, "ButtonControl", "Background subagents", 964, False, True),
            (1, "GroupControl", "", 992, False, True),
            (2, "ButtonControl", "Auto", 1008, False, True),
        ]
        ctrl, dock = make_controller(rows)
        self.assertEqual(ctrl._dock_read(dock), ([], None))

    def test_depth_zero_root_and_sibling_question_block_stay_separate(self):
        rows = [
            (0, "GroupControl", "", 900, False, True),
            (1, "GroupControl", "", 910, False, True),
            (2, "TextControl", "选哪一个？", 912, False, True),
            (2, "ButtonControl", "选项一", 920, False, True),
            (1, "GroupControl", "", 956, False, True),
            (2, "EditControl", "Prompt", 967, False, True),
            (2, "ButtonControl", "Composer mystery", 964, False, True),
            (1, "GroupControl", "", 992, False, True),
            (2, "TextControl", "Fast mode off", 1008, False, True),
        ]
        ctrl, dock = make_controller(rows)
        options, prompt = ctrl._dock_read(dock)
        self.assertEqual(options, [{"type": "ButtonControl", "name": "选项一"}])
        self.assertEqual(prompt["title"], "选哪一个？")
        self.assertEqual([c["name"] for c in prompt["choices"]], ["选项一"])


class Layer2SessionControlTests(unittest.TestCase):
    def test_claude_session_control_rules(self):
        for name in (
            "Stop",
            "Stop 1 nested session",
            "Stop 2 nested sessions",
            "Stop generating",
            "Cancel 2 Nested Sessions",
            "  stop 3 NESTED SESSION  ",
        ):
            self.assertTrue(chats.claude_session_control(name), name)
        for name in ("", "   ", "Stopwatch", "Stopped", "Allow", "Skip", "Submit", "Next"):
            self.assertFalse(chats.claude_session_control(name), name)

    def test_session_controls_outside_composer_block_are_filtered_in_dock_read(self):
        rows = [
            (1, "GroupControl", "", 900, False, True),
            (2, "ButtonControl", "Stop", 900, False, True),
            (2, "ButtonControl", "Stop 1 nested session", 905, False, True),
            (2, "ButtonControl", "Stop generating", 910, False, True),
            (2, "ButtonControl", "Abort 3 Nested Sessions", 915, False, True),
            (1, "GroupControl", "", 956, False, True),
            (2, "EditControl", "Prompt", 967, False, True),
        ]
        ctrl, dock = make_controller(rows)
        self.assertEqual(ctrl._dock_read(dock), ([], None))


class Layer3WaitingEvidenceTests(unittest.TestCase):
    LOOSE_DOCK = [
        (1, "GroupControl", "", 900, False, True),
        (2, "TextControl", "是否按这个方案执行？", 902, False, True),
        (2, "ButtonControl", "同意执行", 920, False, True),
        (2, "ButtonControl", "继续修改", 940, False, True),
        (1, "GroupControl", "", 960, False, True),
        (2, "EditControl", "Prompt", 967, False, True),
    ]

    def _write_transcript(self, folder: Path, records: list[dict]) -> Path:
        path = folder / "session.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        return path

    def test_held_hook_request_keeps_loose_dock_card(self):
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [])
        ask = claude_hooks.Ask(
            {"id": "local_fake_1", "title": "测试对话"},
            {"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
        )
        bridge.asks[ask.id] = ask
        ctrl, _ = make_controller(self.LOOSE_DOCK, hooks=bridge)
        state = read_state(ctrl, transcript_path=None, tid="local_fake_1")
        self.assertIsNotNone(state["prompt"])
        self.assertEqual([c["name"] for c in state["prompt"]["choices"]], ["同意执行", "继续修改"])
        self.assertEqual(state["actions"], [])

    def test_unanswered_ask_user_question_in_record_keeps_loose_dock_card(self):
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [])
        ctrl, _ = make_controller(self.LOOSE_DOCK, hooks=bridge)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(Path(tmp), [
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "toolu_q1", "name": "AskUserQuestion", "input": {"questions": []}},
                ]}},
            ])
            state = read_state(ctrl, transcript_path=path)
            self.assertIsNotNone(state["prompt"])
            self.assertEqual([c["name"] for c in state["prompt"]["choices"]], ["同意执行", "继续修改"])

            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_q1", "content": "answered"},
                ]}}) + "\n")
            after = read_state(ctrl, transcript_path=path)
            self.assertIsNone(after["prompt"])
            self.assertEqual(after["actions"], [])

    def test_unanswered_exit_plan_mode_in_record_keeps_loose_dock_card(self):
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [])
        ctrl, _ = make_controller(self.LOOSE_DOCK, hooks=bridge)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_transcript(Path(tmp), [
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "toolu_plan1", "name": "ExitPlanMode", "input": {}},
                ]}},
            ])
            state = read_state(ctrl, transcript_path=path)
            self.assertIsNotNone(state["prompt"])
            self.assertEqual([c["name"] for c in state["prompt"]["choices"]], ["同意执行", "继续修改"])

            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_plan1", "content": "approved"},
                ]}}) + "\n")
            after = read_state(ctrl, transcript_path=path)
            self.assertIsNone(after["prompt"])
            self.assertEqual(after["actions"], [])

    def test_no_hook_and_no_pending_record_suppresses_loose_card_but_keeps_action_revision(self):
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [])
        ctrl, dock = make_controller(self.LOOSE_DOCK, hooks=bridge)
        expected_options, _ = ctrl._dock_read(dock)
        with tempfile.TemporaryDirectory() as tmp:
            # Even an unfinished Bash call (not AskUserQuestion / ExitPlanMode) is not a pending prompt.
            path = self._write_transcript(Path(tmp), [
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "toolu_bash1", "name": "Bash", "input": {"command": "dir"}},
                ]}},
            ])
            stamp = (path.stat().st_size, path.stat().st_mtime_ns)
            state = read_state(ctrl, transcript_path=path, tid="local_fake_1")
            self.assertIsNone(state["prompt"])
            self.assertEqual(state["actions"], [])
            self.assertEqual(state["action_revision"], claude_control.signature(["local_fake_1", expected_options, stamp]))

    def test_question_card_is_kept_without_hook_or_record_evidence(self):
        bridge = claude_hooks.Bridge(log=lambda text: None, sessions=lambda: [])
        card_rows = [
            (1, "TextControl", "选一个？", 10, False, True),
            (1, "ButtonControl", "选项甲", 40, False, True),
            (1, "ButtonControl", "Next", 80, False, True),
        ]
        ctrl, _ = make_controller(card_rows, dock_cls=CARD_CLASS, hooks=bridge)
        state = read_state(ctrl, transcript_path=None)
        self.assertIsNotNone(state["prompt"])
        self.assertEqual([c["name"] for c in state["prompt"]["choices"]], ["选项甲"])

    def test_layer3_skipped_when_hooks_disabled(self):
        ctrl, _ = make_controller(self.LOOSE_DOCK, hooks=None)
        state = read_state(ctrl, transcript_path=None)
        self.assertIsNotNone(state["prompt"])
        self.assertEqual([c["name"] for c in state["prompt"]["choices"]], ["同意执行", "继续修改"])

    def test_has_pending_prompt_edge_cases(self):
        self.assertFalse(claude_control.has_pending_prompt(None))
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.jsonl"
            self.assertFalse(claude_control.has_pending_prompt(missing))
            path = Path(tmp) / "mixed.jsonl"
            path.write_text(
                "not valid json\n"
                + json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": {"questions": []}},
                ]}}) + "\n"
                + json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "t2", "name": "ExitPlanMode", "input": {}},
                ]}}) + "\n"
                + json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "t2", "content": "ok"},
                ]}}) + "\n",
                encoding="utf-8",
            )
            self.assertFalse(claude_control.has_pending_prompt(path))


class LegacyOptionsAndPressTests(unittest.TestCase):
    def _desktop_with_rows(self, rows, dock_cls=DOCK_CLASS):
        dock = SimpleNamespace(ClassName=dock_cls)
        desktop = object.__new__(chats.Desktop)
        desktop.auto = FakeWalk(rows)
        desktop.log = Mock()
        desktop._claude_root = Mock(return_value=(1, "root"))
        desktop._claude_title = Mock(return_value="测试对话")
        desktop._same_title = Mock(return_value=True)
        desktop._claude_ask = Mock(return_value=dock)
        desktop._claude_dock = Mock(return_value=dock)
        desktop._value = Mock(return_value="")
        return desktop

    def test_claude_options_excludes_composer_block_and_session_controls(self):
        rows = [
            (1, "GroupControl", "", 900, False, True),
            (2, "ButtonControl", "Stop 1 nested session", 900, False, True),
            (2, "ButtonControl", "Cancel Nested Session", 910, False, True),
            (2, "ButtonControl", "Allow", 920, False, True),
            (1, "GroupControl", "", 956, False, True),
            (2, "EditControl", "Prompt", 967, False, True),
            (2, "ButtonControl", "Add", 964, False, True),
            (2, "ButtonControl", "Stop", 964, False, True),
            (2, "ButtonControl", "Stop 2 nested sessions", 964, False, True),
            (2, "ButtonControl", "Composer mystery", 964, False, True),
        ]
        desktop = self._desktop_with_rows(rows)
        with patch("chats.find", return_value={"app": "claude", "id": "s1", "title": "测试对话"}), \
             patch("chats.conversation_title", return_value="测试对话"):
            result = desktop.claude_options("s1")
        self.assertTrue(result["on_screen"])
        self.assertTrue(result["running"])
        self.assertEqual(result["options"], [{"type": "Button", "name": "Allow", "nth": 0}])

    def test_claude_press_refuses_session_controls_without_touching_window(self):
        desktop = object.__new__(chats.Desktop)
        desktop._claude_root = Mock(side_effect=AssertionError("must not inspect Claude window"))
        desktop._claude_ask = Mock(side_effect=AssertionError("must not search controls"))
        desktop.auto = SimpleNamespace(WalkControl=Mock(side_effect=AssertionError("must not walk controls")))

        with patch("chats.find", side_effect=AssertionError("must fail before looking up session")):
            for bad_name in (
                "Stop",
                "Stop 1 nested session",
                "Stop 2 nested sessions",
                "Stop generating",
                "Kill 2 Nested Sessions",
            ):
                with self.assertRaises(chats.ChatError) as ctx:
                    desktop.claude_press("s1", {"type": "Button", "name": bad_name})
                self.assertEqual(str(ctx.exception), "这是 Claude 停止会话的按钮，不是提问，没有按")

        # Ordinary buttons still press normally on a fake control tree.
        allow_ctrl = FakeCtrl(2, "ButtonControl", "Allow", 920, False, True)
        ok_desktop = self._desktop_with_rows([(allow_ctrl, 2)])
        with patch("chats.find", return_value={"app": "claude", "id": "s1", "title": "测试对话"}), \
             patch("chats.conversation_title", return_value="测试对话"):
            pressed = ok_desktop.claude_press("s1", {"type": "Button", "name": "Allow", "nth": 0})
        self.assertTrue(pressed["ok"])
        self.assertEqual(allow_ctrl.invoked, 1)


if __name__ == "__main__":
    unittest.main()
