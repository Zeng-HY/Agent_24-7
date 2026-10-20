"""10-15: a Claude review run wrote its progress only as thinking lines and kept a checklist (update_plan); the phone
showed neither, only 已执行 N 步操作."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats  # noqa: E402


def record(*blocks, stop="tool_use", mid="m1"):
    return json.dumps({"type": "assistant", "timestamp": "2026-10-15T00:00:00Z", "isSidechain": False,
                       "message": {"id": mid, "stop_reason": stop, "content": list(blocks)}}, ensure_ascii=False).encode()


PLAN = {"type": "tool_use", "name": "mcp__ccd_turn__update_plan",
        "input": {"scope": "first_task", "items": [{"content": "读记录，摸清格式", "status": "completed"},
                                                   {"content": "核对完整记录", "status": "in_progress"},
                                                   {"content": "汇总", "status": "pending"}]}}


class ThinkingAndPlan(unittest.TestCase):
    def test_thinking_with_words_is_a_progress_note_and_empty_thinking_stays_hidden(self):
        msgs, _ = chats.parse_claude([record({"type": "thinking", "thinking": "", "signature": "x"}),
                                      record({"type": "thinking", "thinking": "找到笔记文件了，先看运行目录。", "signature": "y"}),
                                      record({"type": "tool_use", "name": "Bash", "input": {"command": "dir"}})])
        self.assertEqual([(m["role"], m.get("phase"), m.get("thinking")) for m in msgs],
                         [("assistant", "commentary", True), ("tool", None, None)])
        self.assertEqual(msgs[0]["text"], "找到笔记文件了，先看运行目录。")

    def test_the_checklist_is_a_card_of_its_own(self):
        msgs, _ = chats.parse_claude([record({"type": "tool_use", "name": "Read", "input": {"file_path": "a.md"}}), record(PLAN)])
        self.assertEqual([m["role"] for m in msgs], ["tool", "plan"])
        self.assertEqual(msgs[1]["items"], [{"text": "读记录，摸清格式", "status": "completed"}, {"text": "核对完整记录", "status": "in_progress"},
                                            {"text": "汇总", "status": "pending"}])
        self.assertTrue(msgs[1]["text"].startswith("计划 1/3："))

    def test_claude_codes_todo_list_and_other_tools(self):
        todo = {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [{"content": "改代码", "status": "pending", "activeForm": "改代码中"}]}}
        msgs, _ = chats.parse_claude([record(todo), record({"type": "tool_use", "name": "update_plan_x", "input": {}})])
        self.assertEqual([m["role"] for m in msgs], ["plan", "tool"])

    def test_the_turn_is_still_running_after_a_thinking_line(self):
        _, state = chats.parse_claude([record({"type": "thinking", "thinking": "想一下", "signature": "y"}, stop=None)])
        self.assertTrue(state["running"])
        _, state = chats.parse_claude([record({"type": "thinking", "thinking": "好了", "signature": "y"}, {"type": "text", "text": "完成"}, stop="end_turn")])
        self.assertFalse(state["running"])


if __name__ == "__main__":
    unittest.main()
