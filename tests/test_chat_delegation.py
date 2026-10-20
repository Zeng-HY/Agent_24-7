"""Public cross-chat input must survive indexing without exposing arbitrary tool output."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats
from chat_history import History

SOURCE = "01a128f4-1de3-7f02-a73e-7c7ce5be8328"


def event(ident="delegation-1", text="原任务", name="create_thread", namespace="codex_app"):
    return {"type": "event_msg", "timestamp": "2026-10-11T03:16:59Z", "payload": {
        "type": "item_completed", "item": {"type": "FunctionCallOutput", "id": ident,
        "name": name, "namespace": namespace,
        "output": f"<codex_delegation>\n<source_thread_id>{SOURCE}</source_thread_id>\n<input>{text}</input>\n</codex_delegation>"}}}


def raw(value):
    return (json.dumps(value, ensure_ascii=False) + "\n").encode()


class DelegationTest(unittest.TestCase):
    def test_public_message_and_exact_unescaping(self):
        for name in ("create_thread", "send_message_to_thread"):
            messages, _ = chats.parse_codex([raw(event(text="x &lt; y &amp; &amp;lt;\n第二行", name=name))])
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["text"], "x < y & &lt;\n第二行")
            self.assertEqual(messages[0]["origin"], "other_chat")
            self.assertEqual(messages[0]["source_thread_id"], SOURCE)
            self.assertEqual(messages[0]["source_id"], "delegation-1")
            self.assertNotIn("client_request_id", messages[0])

    def test_ordinary_outputs_and_internal_records_stay_hidden(self):
        cases = [event(name="exec_command"), event(namespace="unrelated")]
        for output in ("ordinary tool output", "prefix " + event()["payload"]["item"]["output"],
                       "<codex_delegation><input>missing source</input></codex_delegation>", {},
                       event(text="")["payload"]["item"]["output"]):
            value = event(); value["payload"]["item"]["output"] = output; cases.append(value)
        cases += [{"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"text": "private instructions"}]}},
                  {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "Reasoning", "raw_content": "private reasoning"}}}]
        self.assertEqual(chats.parse_codex([raw(v) for v in cases])[0], [])

    def test_history_search_full_text_and_incremental_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            logfile = Path(directory) / "rollout.jsonl"
            incoming = event(text="任务\n" + "正文" * 3300 + "全文末尾")
            mirror = {"type": "response_item", "payload": {**incoming["payload"]["item"], "type": "function_call_output"}}
            answer = {"type": "event_msg", "timestamp": "2026-10-11T03:17:01Z", "payload": {"type": "item_completed",
                "item": {"type": "AgentMessage", "id": "answer", "content": [{"text": "开始处理。"}], "phase": "commentary"}}}
            logfile.write_bytes(raw(mirror) + raw(incoming) + raw(answer))
            item = {"app": "codex", "id": "fixture", "path": str(logfile), "title": "测试", "cwd": directory}
            with patch("chats.find", return_value=item):
                history = History(); page = history.conversation("codex", "fixture")
                self.assertEqual([m["id"] for m in page["messages"]], ["delegation-1", "answer"])
                self.assertTrue(page["messages"][0]["truncated"])
                self.assertTrue(history.message("codex", "fixture", "delegation-1")["text"].endswith("全文末尾"))
                hit = history.search("codex", "fixture", "全文末尾")["items"][0]
                self.assertEqual(hit["origin"], "other_chat")
                with logfile.open("ab") as out:
                    out.write(raw(incoming)); out.write(raw(event("delegation-2", "补发任务", "send_message_to_thread")))
                self.assertEqual([m["id"] for m in history.conversation("codex", "fixture")["messages"]],
                                 ["delegation-1", "answer", "delegation-2"])
                self.assertTrue(chats.summary(item)["preview"].startswith("来自其他对话："))


if __name__ == "__main__":
    unittest.main()
