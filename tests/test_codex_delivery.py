"""Identity-bound sends, question revisions and queue removal failure boundaries."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_control as cc


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = cc.Bridge()
        self.bridge.data_root = Path(self.tmp.name)
        self.settings = {"model": "test", "effort": "medium", "mode": "default", "service_tier": None}
        self.state = {"id": "test-thread", "hostId": "local", "cwd": self.tmp.name,
                      "turns": [{"turnId": "turn-one", "status": "inProgress", "items": []}]}
        self.bridge.snapshot = Mock(side_effect=lambda *a, **kw: ({"path": str(Path(self.tmp.name)/"rollout.jsonl")}, "owner", copy.deepcopy(self.state)))
        self.pipe = Mock()
        self.pipe.call.return_value = {"result": {"result": {}}}
        self.bridge._pipe = Mock(return_value=self.pipe)
        self.bridge.delivery_evidence = Mock(return_value={})
        for target, value in [("chats.require_send_desktop", None), ("selected_settings", self.settings)]:
            p = patch("codex_control." + target, return_value=value)
            p.start(); self.addCleanup(p.stop)
        self.bridge.validate_settings = Mock(return_value=self.settings)
        self.body = {"id": "test-thread", "request_id": "test-request-0001", "text": "same text", "intent": "auto", "expected_turn": "turn-one"}

    def test_running_auto_steers_once_and_replays_receipt(self):
        r = self.bridge.send(self.body)
        self.assertEqual(r["delivery_state"], "accepted")
        self.assertEqual(self.bridge.send(self.body), r)
        self.assertEqual(self.pipe.call.call_count, 1)
        self.assertEqual(self.pipe.call.call_args.args[0], "thread-follower-steer-turn")

    def test_same_text_two_intentional_requests_have_distinct_ids(self):
        self.bridge.send(self.body)
        self.bridge.send({**self.body, "request_id": "test-request-0002"})
        self.assertEqual(self.pipe.call.call_count, 2)
        ids = [c.args[1]["clientUserMessageId"] for c in self.pipe.call.call_args_list]
        self.assertEqual(len(set(ids)), 2)

    def test_timeout_never_replays_send_and_exact_evidence_recovers(self):
        self.pipe.call.side_effect = cc.ControlError("timeout")
        with self.assertRaises(cc.ControlError): self.bridge.send(self.body)
        with self.assertRaises(cc.ControlError): self.bridge.send(self.body)
        self.assertEqual(self.pipe.call.call_count, 1)
        self.bridge.delivery_evidence.return_value = {self.body["request_id"]: {"source": "conversation_record"}}
        self.assertEqual(self.bridge.receipt("test-thread", self.body["request_id"])["state"], "accepted")

    def test_changed_turn_and_running_attachments_do_not_dispatch(self):
        with self.assertRaises(cc.ControlError): self.bridge.send({**self.body, "expected_turn": "old"})
        with self.assertRaises(cc.ControlError): self.bridge.send({**self.body, "attachments": ["image"]})
        self.pipe.call.assert_not_called()

    def test_idle_auto_starts(self):
        self.state["turns"][0]["status"] = "completed"
        self.bridge.send({**self.body, "expected_turn": None})
        self.assertEqual(self.pipe.call.call_args.args[0], "thread-follower-start-turn")

    def test_enqueue_preserves_existing_desktop_messages(self):
        old = {"id": "desktop-message", "text": "keep", "context": {}}
        self.bridge._local_queue = Mock(return_value=[old])
        r = self.bridge.send({**self.body, "intent": "queue"})
        self.assertEqual(r["delivery_state"], "queued")
        self.assertEqual(self.pipe.call.call_args.args[1]["state"]["test-thread"][0], old)

    def test_missing_removal_ack_never_steers(self):
        self.bridge._local_queue = Mock(return_value=[{"id": "queued-id", "text": "keep"}])
        self.pipe.call.return_value = {"result": {"removed": None}}
        b = {"id": "test-thread", "request_id": "queue-action-0001", "message_id": "queued-id", "action": "promote", "expected_turn": "turn-one"}
        with self.assertRaises(cc.ControlError): self.bridge.queue_action(b)
        with self.assertRaises(cc.ControlError): self.bridge.queue_action(b)
        self.assertEqual(self.pipe.call.call_count, 1)

    def test_concurrent_queue_change_rejects_before_desktop_write(self):
        self.bridge._local_queue = Mock(side_effect=[[], [{"id": "new-desktop-message"}]])
        r = self.bridge.send({**self.body, "intent": "queue"})
        self.assertEqual(r["delivery_state"], "rejected")
        self.pipe.call.assert_not_called()

    def test_lost_queue_response_recovers_after_restarting_bridge(self):
        self.bridge._local_queue = Mock(return_value=[])
        self.pipe.call.side_effect = cc.ControlError("lost response")
        with self.assertRaises(cc.ControlError): self.bridge.send({**self.body, "intent": "queue"})
        recovered = cc.Bridge(); recovered.data_root = self.bridge.data_root
        recovered._local_queue = Mock(return_value=[{"id": self.body["request_id"]}])
        recovered.delivery_evidence = Mock(return_value={})
        self.assertEqual(recovered.receipt("test-thread", self.body["request_id"])["state"], "queued")
        recovered._pipe = Mock(side_effect=AssertionError("must not resend"))
        self.assertEqual(recovered.send({**self.body, "intent": "queue"})["delivery_state"], "queued")

    def test_removal_racing_with_dispatch_never_steers(self):
        self.bridge._local_queue = Mock(return_value=[{"id": "queued-id", "text": "keep"}])
        self.pipe.call.return_value = {"result": {"removed": {"message": {"id": "queued-id", "submission": {"status": "sending"}}}}}
        b = {"id": "test-thread", "request_id": "queue-action-0002", "message_id": "queued-id", "action": "promote", "expected_turn": "turn-one"}
        with self.assertRaises(cc.ControlError): self.bridge.queue_action(b)
        self.assertEqual(self.pipe.call.call_count, 1)

    def test_native_lost_reply_ack_reconciles_without_resubmitting(self):
        b = {"question_id": "native:turn-one:7", "answers": {"q": ["secret"]}}
        self.bridge._begin("native-answer-0001", "test-thread", b)
        with patch.object(cc, "native_questions", return_value=[{"id": b["question_id"], "status": "answered"}]):
            self.assertEqual(self.bridge.receipt("test-thread", "native-answer-0001")["state"], "accepted")
        with self.bridge._db() as con:
            stored = con.execute("SELECT data FROM deliveries WHERE id='native-answer-0001'").fetchone()[0]
        self.assertNotIn("secret", stored)
        self.pipe.call.assert_not_called()

    def test_async_answer_can_be_revised_but_stale_revision_rejected(self):
        card = {"id": "async:call-test", "request_id": "call-test", "kind": "async", "turn_id": "turn-one", "status": "pending", "questions": [{"id": "0", "question": "test"}]}
        with patch.object(cc, "async_questions", return_value=[card]):
            b = {"id": "test-thread", "request_id": "answer-request-001", "question_id": card["id"], "answers": {"0": ["10"]}}
            self.bridge.answer(b)
            card.update(status="answered", answers={"0": ["10"]})
            self.bridge.answer({**b, "request_id": "answer-request-002", "answers": {"0": ["5"]}})
            with self.assertRaises(cc.ControlError): self.bridge.answer({**b, "request_id": "answer-request-003", "answer_revision": "stale"})
        self.assertEqual(self.pipe.call.call_count, 2)


if __name__ == "__main__": unittest.main()
