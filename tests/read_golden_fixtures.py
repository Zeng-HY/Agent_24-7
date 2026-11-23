"""Build the fixed read-only golden bundle (test data only, no real conversations)."""

from __future__ import annotations

import json
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chats
import chat_history
import chat_projects
import live_events
from types import SimpleNamespace

TS = "2026-01-02T03:04:05Z"
TS2 = "2026-01-02T03:04:06Z"


def event(payload, ts=TS):
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": payload}, ensure_ascii=False).encode() + b"\n"


def codex_lines():
    return [
        event({"type": "task_started", "turn_id": "turn-1"}),
        event({"type": "item_completed", "item": {
            "type": "UserMessage", "id": "user-1", "content": [{"text": "你好"}]}}),
        event({"type": "item_completed", "item": {
            "type": "AgentMessage", "id": "answer-1", "phase": "final_answer",
            "content": [{"text": "你好，我在"}]}}),
        event({"type": "task_complete", "turn_id": "turn-1"}, TS2),
    ]


def claude_lines():
    return [
        json.dumps({"type": "user", "uuid": "u-1", "timestamp": TS,
                    "message": {"role": "user", "content": [{"type": "text", "text": "帮我看看"}]}},
                   ensure_ascii=False).encode() + b"\n",
        json.dumps({"type": "assistant", "uuid": "a-1", "timestamp": TS2,
                    "message": {"role": "assistant", "model": "claude-test",
                                "usage": {"input_tokens": 10, "output_tokens": 2},
                                "content": [{"type": "text", "text": "好的"}]}},
                   ensure_ascii=False).encode() + b"\n",
    ]


def normalize_summary(value):
    out = dict(value)
    out["modified"] = 0
    return out


def build():
    base = Path(tempfile.mkdtemp(prefix="teleply-golden-"))
    codex_path = base / "codex.jsonl"
    claude_path = base / "claude.jsonl"
    codex_path.write_bytes(b"".join(codex_lines()))
    claude_path.write_bytes(b"".join(claude_lines()))

    codex_item = {"app": "codex", "id": "codex-1", "title": "测试对话 A", "path": str(codex_path),
                  "cwd": "C:\\测试\\项目", "folder": "项目", "updated": 1767323045000,
                  "created": 1767323040000, "pinned": False}
    claude_item = {"app": "claude", "id": "claude-1", "title": "测试对话 B",
                   "cwd": "C:\\测试\\另一个", "folder": "另一个", "updated": 1767323046000,
                   "created": 1767323041000, "pinned": False}
    deepseek_item = {"app": "deepseek", "id": "deepseek-1", "title": "测试对话 C",
                     "cwd": "C:\\测试\\工作区", "folder": "工作区", "updated": 1767323047000,
                     "created": 1767323042000, "pinned": False, "status": "waiting",
                     "preview": "等你选择"}

    parsed_codex = chats.parse_codex(codex_lines())
    parsed_claude = chats.parse_claude(claude_lines())

    with ExitStack() as stack:
        stack.enter_context(patch.object(chats, "STALE_SECONDS", 10 ** 12))
        stack.enter_context(patch.object(chats, "claude_transcript", return_value=claude_path))
        summary = {
            "codex": normalize_summary(chats.summary(codex_item)),
            "claude": normalize_summary(chats.summary(claude_item)),
            "deepseek": chats.summary(deepseek_item),
        }
        codex_transcript = chat_history.Transcript(codex_path, "codex", "C:\\测试\\项目").refresh()
        claude_transcript = chat_history.Transcript(claude_path, "claude", "C:\\测试\\另一个").refresh()
        transcript = {
            "codex": {"messages": codex_transcript.messages, "state": codex_transcript.state},
            "claude": {"messages": claude_transcript.messages, "state": claude_transcript.state},
        }
        stack.enter_context(patch.object(chats, "codex_threads", return_value=[dict(codex_item)]))
        stack.enter_context(patch.object(chats, "claude_sessions", return_value=[dict(claude_item)]))
        listed = chats.list_conversations("all", 10)
        for row in listed:
            row["updated"] = 0
        listed.sort(key=lambda row: (row["app"], row["id"]))

    rows = [
        {"app": "codex", "id": "codex-1", "title": "测试对话 A", "folder": "项目",
         "cwd": "C:\\测试\\项目", "updated": 1767323045000},
        {"app": "claude", "id": "claude-1", "title": "测试对话 B", "folder": "另一个",
         "cwd": "C:\\测试\\另一个", "origin": "C:\\测试\\另一个", "updated": 1767323046000},
        {"app": "deepseek", "id": "deepseek-1", "title": "测试对话 C", "folder": "工作区",
         "cwd": "C:\\测试\\工作区", "workspace": {"id": "w1", "name": "工作区", "path": "C:\\测试\\工作区"},
         "updated": 1767323047000},
    ]
    with patch.object(chat_projects, "codex_layout", return_value=({}, {}, set(), set())):
        tree = chat_projects.tree(rows, lambda item: "idle")
    tree["now"] = 0

    page = {"id": "codex-1", "messages": [
        {"id": "answer-1", "role": "assistant", "phase": "final_answer", "text": "旧回答", "turn_id": "turn-1", "order": 10, "time": TS},
    ]}
    entry = SimpleNamespace(
        messages=[{"id": "answer-1", "role": "assistant", "phase": "final_answer", "text": "旧回答",
                   "turn_id": "turn-1", "order": 10, "time": TS}],
        by_id={"answer-1": {"id": "answer-1", "role": "assistant", "phase": "final_answer",
                            "text": "旧回答", "turn_id": "turn-1", "order": 10, "time": TS}},
        state={"running": True, "current_turn_id": "turn-1"}, offset=10, lock=__import__("threading").RLock())
    state = {"id": "codex-1", "turns": [{"turnId": "turn-1", "status": "inProgress", "turnStartedAtMs": 1000,
                                         "items": [{"id": "live-1", "type": "agentMessage",
                                                    "phase": "commentary", "text": "正在做"}]}]}
    live, live_ids = live_events.merge_live_messages(page, entry, state)

    return {
        "parse_codex": [parsed_codex[0], parsed_codex[1]],
        "parse_claude": [parsed_claude[0], parsed_claude[1]],
        "summary": summary,
        "transcript": transcript,
        "list_conversations": listed,
        "tree": tree,
        "live": {"messages": live, "live_ids": live_ids},
    }


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/fixtures/read-golden.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
