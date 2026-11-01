"""11-01: every send result carries accepted_at, the computer's own clock (milliseconds), so the phone can compare
Claude's and DeepSeek's record times (also this computer's clock) with it instead of the phone's clock, which was 13 s
fast here."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote  # noqa: E402


class SendAcceptedAt(unittest.TestCase):
    def handler(self):
        handler = object.__new__(remote.Handler)
        handler.json = []
        handler._json = lambda body, status=200: handler.json.append((body, status))
        return handler

    def test_claude_and_deepseek_sends_say_when_they_were_taken(self):
        with mock.patch("remote.time.time", return_value=1_700_000_000.123):
            claude = self.handler()
            claude.server = SimpleNamespace(desktop=SimpleNamespace(
                send=lambda *a, **k: {"ok": True, "offset": 7, "pressed": True}))
            taken = claude._send_with_references({"app": "claude", "id": "s", "text": "你好"})
            deepseek = self.handler()
            deepseek.server = SimpleNamespace(deepseek=SimpleNamespace(send=lambda body: {"accepted": True}))
            deepseek._query = lambda: {}
            deepseek._deepseek("/api/deepseek/send", {"id": "d"})
        self.assertEqual((taken["accepted_at"], deepseek.json[0][0]["accepted_at"]),
                         (1_700_000_000_123, 1_700_000_000_123))

    def test_a_codex_send_says_when_it_was_taken(self):
        handler = self.handler()
        handler.server = SimpleNamespace(codex=SimpleNamespace(
            send=lambda body: {"accepted": True, "request_id": "r", "delivery_state": "accepted"}))
        with mock.patch("remote.time.time", return_value=1_700_000_000.123):
            handler._codex_post("/api/codex/send", {"id": "t", "request_id": "r"})
        self.assertEqual(handler.json[0][0]["accepted_at"], 1_700_000_000_123)


if __name__ == "__main__":
    unittest.main()
