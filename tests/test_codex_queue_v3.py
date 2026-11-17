"""11-17: Codex 26.1106 and 26.1111 take the queue request only at v3. v1 was refused before anything was done, so every message
the phone sent while Codex worked never reached Codex, stayed 送达状态待确认, and 核对 could not say more."""
import copy
import json
import queue
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_control as cc

QUEUE = "thread-follower-set-queued-follow-ups-state"
OK = {"resultType": "success", "handledByClientId": "owner", "result": {"ok": True}}
MISMATCH = {"resultType": "error", "error": "request-version-mismatch"}


def answering(*replies):
    """A pipe whose Codex answers each request with the next reply, at once; what was sent is kept."""
    pipe = object.__new__(cc.DesktopPipe)
    pipe.client, pipe.pending, pipe.closed, sent = "teleply-test", {}, False, []

    def send(request):
        sent.append(request)
        pipe.pending[request["requestId"]].put({"type": "response", "requestId": request["requestId"], **replies[len(sent) - 1]})
    pipe._send = send
    return pipe, sent


class VersionTests(unittest.TestCase):
    def test_the_queue_goes_at_v3_the_number_codex_26_1111_takes(self):
        pipe, sent = answering(OK)
        pipe.call(QUEUE, {"conversationId": "t", "state": {"t": []}, "discardedMessageIds": []}, "owner")
        self.assertEqual([r["version"] for r in sent], [3])
        self.assertNotIn("preparationMessageId", sent[0]["params"])  # only for a message Codex prepares itself

    def test_an_older_codex_is_asked_again_at_v1(self):
        pipe, sent = answering(MISMATCH, OK)
        pipe.call(QUEUE, {}, "owner")
        self.assertEqual([r["version"] for r in sent], [3, 1])

    def test_no_number_taken_is_a_plain_refusal(self):
        pipe, sent = answering(MISMATCH, MISMATCH)
        with self.assertRaises(cc.ControlError) as caught:
            pipe.call(QUEUE, {}, "owner")
        self.assertEqual(caught.exception.code, "request-version-mismatch")
        self.assertIn("Codex 升级了", str(caught.exception))
        self.assertTrue(cc.untaken(caught.exception))
        self.assertEqual(len(sent), 2)

    def test_any_other_error_is_not_tried_again(self):
        pipe, sent = answering({"resultType": "error", "error": "This window no longer owns the thread"})
        with self.assertRaises(cc.ControlError) as caught:
            pipe.call(QUEUE, {}, "owner")
        self.assertEqual(len(sent), 1)
        self.assertFalse(cc.untaken(caught.exception))

    def test_a_method_with_one_number_is_asked_once(self):
        pipe, sent = answering({"resultType": "error", "error": "no-handler-for-request"})
        with self.assertRaises(cc.ControlError) as caught:
            pipe.call("thread-follower-steer-turn", {}, "owner")
        self.assertEqual([r["version"] for r in sent], [1])
        self.assertTrue(cc.untaken(caught.exception, cc.REFUSED))

    def test_the_queue_changed_broadcast_v3_is_kept(self):
        self.assertIn(3, cc.QUEUE_CHANGED_VERSIONS)


class SendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bridge = cc.Bridge()
        self.bridge.data_root = root / "data"
        self.settings = {"model": "test", "effort": "medium", "mode": "default", "service_tier": None}
        self.state = {"id": "test-thread", "hostId": "local", "cwd": self.tmp.name,
                      "turns": [{"turnId": "turn-one", "status": "inProgress", "items": []}]}
        self.record = root / "rollout.jsonl"
        self.record.write_text('{"type":"event_msg","payload":{"type":"task_started"}}\n', encoding="utf-8")
        self.bridge.snapshot = Mock(side_effect=lambda *a, **kw: ({"path": str(self.record)}, "owner", copy.deepcopy(self.state)))
        self.pipe = Mock()
        self.pipe.call.return_value = {"result": {"result": {}}}
        self.bridge._pipe = Mock(return_value=self.pipe)
        self.bridge.delivery_evidence = Mock(return_value={})
        self.bridge._local_queue = Mock(return_value=[])
        self.bridge.validate_settings = Mock(return_value=self.settings)
        self.home = root / "codex-home"
        self.home.mkdir()
        for target, value in [("chats.require_send_desktop", None), ("selected_settings", self.settings),
                              ("chats.find", {"path": str(self.record)})]:
            p = patch("codex_control." + target, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(cc.chats, "CODEX_HOME", self.home)
        p.start(); self.addCleanup(p.stop)
        self.body = {"id": "test-thread", "request_id": "test-request-0001", "text": "这个项目在已完成的列表里了",
                     "intent": "queue", "expected_turn": "turn-one"}

    def refused(self, code="request-version-mismatch"):
        return cc.ControlError("电脑上的 Codex 升级了，遥应还不会这一步，没有执行", code=code)

    def age(self, rid, seconds):
        with self.bridge._db() as con:
            con.execute("UPDATE deliveries SET created=? WHERE id=?", (time.time() - seconds, rid))

    def stuck(self, seconds=660, body=None):
        """A send whose call never came back, as the two of 11-17 were left: 'dispatching', with no result."""
        body = body or self.body
        self.bridge._begin(body["request_id"], "test-thread", body)
        self.age(body["request_id"], seconds)
        return body["request_id"]

    def test_a_queue_codex_refuses_is_not_sent_and_says_why(self):
        self.pipe.call.side_effect = self.refused()
        with self.assertRaises(cc.ControlError):
            self.bridge.send(self.body)
        receipt = self.bridge.receipt("test-thread", self.body["request_id"])
        self.assertEqual(receipt["state"], "rejected")  # remote.py: not_submitted, so the phone shows 未接收
        self.assertIn("Codex 升级了", receipt["result"]["text"])

    def test_a_running_send_with_no_window_for_the_conversation_is_not_sent(self):
        self.pipe.call.side_effect = cc.ControlError("电脑端尚未打开这个对话", code="no-client-found")
        with self.assertRaises(cc.ControlError):
            self.bridge.send({**self.body, "intent": "steer"})
        self.assertEqual(self.bridge.receipt("test-thread", self.body["request_id"])["state"], "rejected")

    def test_a_start_codex_refuses_is_not_sent(self):
        self.state["turns"][0]["status"] = "completed"
        self.pipe.call.side_effect = self.refused("no-handler-for-request")
        with self.assertRaises(cc.ControlError):
            self.bridge.send({**self.body, "intent": "auto", "expected_turn": None})
        self.assertEqual(self.bridge.receipt("test-thread", self.body["request_id"])["state"], "rejected")

    def test_a_queue_with_no_answer_stays_unknown(self):
        self.pipe.call.side_effect = cc.ControlError("Codex 响应超时，结果未确认；不会自动重试", code="timeout")
        with self.assertRaises(cc.ControlError):
            self.bridge.send(self.body)
        self.assertEqual(self.bridge.receipt("test-thread", self.body["request_id"])["state"], "dispatching")

    def test_a_queue_codex_takes_is_queued(self):
        self.assertEqual(self.bridge.send(self.body)["delivery_state"], "queued")
        name, params = self.pipe.call.call_args.args[:2]
        self.assertEqual(name, QUEUE)
        message = params["state"]["test-thread"][-1]
        self.assertEqual((message["id"], message["submission"]["status"]), (self.body["request_id"], "queued"))

    def test_a_withdrawal_codex_refuses_is_not_done(self):
        self.bridge._local_queue.return_value = [{"id": "queued-id", "text": "keep", "submission": {"status": "queued"}}]
        self.pipe.call.side_effect = self.refused()
        body = {"id": "test-thread", "request_id": "queue-cancel-0001", "message_id": "queued-id", "action": "cancel"}
        with self.assertRaises(cc.ControlError):
            self.bridge.queue_action(body)
        self.assertEqual(self.bridge.receipt("test-thread", "queue-cancel-0001")["state"], "rejected")

    def test_a_stuck_send_found_nowhere_is_called_not_delivered(self):
        rid = self.stuck()
        receipt = self.bridge.receipt("test-thread", rid)
        self.assertEqual(receipt["state"], "rejected")
        self.assertIn("没有送到 Codex", receipt["result"]["text"])
        self.assertEqual(self.bridge.receipt("test-thread", rid)["state"], "rejected")  # kept, not judged again

    def test_a_stuck_send_whose_id_is_in_the_record_is_left_alone(self):
        rid = self.stuck()
        with self.record.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "item": {"client_id": rid}}}) + "\n")
        self.assertEqual(self.bridge.receipt("test-thread", rid)["state"], "dispatching")

    def test_a_stuck_send_in_codexs_queue_database_is_left_alone(self):
        rid = self.stuck()
        con = sqlite3.connect(self.home / "queue_1.sqlite")
        con.execute("CREATE TABLE queued_items (id TEXT PRIMARY KEY NOT NULL, thread_id TEXT NOT NULL, payload_json TEXT NOT NULL,"
                    " queue_order INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL)")
        con.execute("INSERT INTO queued_items VALUES ('server-id','test-thread',?,0,0,0)", (json.dumps({"clientUserMessageId": rid}),))
        con.commit(); con.close()
        self.assertEqual(self.bridge.receipt("test-thread", rid)["state"], "dispatching")

    def test_a_stuck_send_still_in_the_desktop_queue_is_queued(self):
        rid = self.stuck()
        self.bridge._local_queue.return_value = [{"id": rid, "text": self.body["text"]}]
        self.assertEqual(self.bridge.receipt("test-thread", rid)["state"], "queued")

    def test_a_young_send_is_not_judged_and_the_record_not_read(self):
        rid = self.stuck(seconds=60)
        with patch.object(cc, "file_has", side_effect=AssertionError("must not read the record")):
            self.assertEqual(self.bridge.receipt("test-thread", rid)["state"], "dispatching")

    def test_a_queued_send_that_just_left_the_queue_is_not_judged(self):
        rid = self.stuck()
        self.bridge._finish(rid, {"ok": True, "accepted": True, "delivery_state": "queued", "request_id": rid})
        receipt = self.bridge.receipt("test-thread", rid)
        self.assertEqual(receipt["state"], "dispatching")  # may be on its way into the record this second
        self.assertIn("离开可见队列", receipt["result"]["text"])

    def test_answers_stops_and_compact_are_never_judged(self):
        for body in ({"id": "test-thread", "request_id": "answer-request-01", "question_id": "async:x", "answers": {}},
                     {"id": "test-thread", "request_id": "stop-request-001", "action": "stop", "turn_id": "turn-one"},
                     {"id": "test-thread", "request_id": "compact-request-1", "text": "/compact", "intent": "auto"}):
            rid = self.stuck(body=body)
            self.assertEqual(self.bridge.receipt("test-thread", rid)["state"], "dispatching", body)

    def test_an_unreadable_desktop_queue_is_not_taken_as_empty(self):
        rid = self.stuck()
        self.bridge._local_queue.side_effect = cc.ControlError("无法核对桌面队列，内容已保留")
        self.assertEqual(self.bridge.receipt("test-thread", rid)["state"], "dispatching")


if __name__ == "__main__":
    unittest.main()
