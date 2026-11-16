"""Codex approval requests reach the phone: cards, decisions, receipts and the 在等你 notification (11-16)."""
import copy
import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import activity
import codex_control as cc
import notify

TURN = "turn-one"


def revision(card):
    return hashlib.sha256(json.dumps(card.get("answers", {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def command_state(**overrides):
    state = {"id": "test-thread", "hostId": "local", "cwd": "C:/work",
             "threadRuntimeStatus": {"type": "active"},
             "turns": [{"turnId": TURN, "status": "inProgress", "items": [
                 {"type": "fileChange", "id": "item-file", "changes": [{"path": "a.py"}, {"path": "b.py"}]}]}],
             "requests": [{"id": "req-1", "method": "item/commandExecution/requestApproval",
                           "params": {"threadId": "test-thread", "turnId": TURN, "itemId": "item-cmd",
                                      "reason": "要装依赖", "command": ["npm", "install", "left-pad"],
                                      "cwd": "C:/work"}}]}
    state.update(overrides)
    return state


class CardTests(unittest.TestCase):
    def test_a_command_approval_card_answers_with_two_choices(self):
        cards = cc.native_approvals(command_state())
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["id"], "approval:turn-one:req-1")
        self.assertEqual((card["kind"], card["approval_type"], card["status"]), ("approval", "command", "pending"))
        self.assertEqual((card["reason"], card["command"], card["cwd"]), ("要装依赖", "npm install left-pad", "C:/work"))
        self.assertTrue(card["answerable"])
        self.assertEqual([v["label"] for v in card["choices"]], ["允许一次", "拒绝"])
        # The field older phones already draw as a Codex question card, and its two labels.
        question = card["questions"][0]
        self.assertEqual(question["id"], "decision")
        self.assertFalse(question["isOther"])
        self.assertEqual([v["label"] for v in question["options"]], ["允许一次", "拒绝"])
        self.assertIn("npm install left-pad", question["question"])

    def test_a_file_approval_takes_its_paths_from_the_turn(self):
        state = command_state(requests=[{"id": 7, "method": "item/fileChange/requestApproval",
                                         "params": {"threadId": "test-thread", "turnId": TURN,
                                                    "itemId": "item-file", "grantRoot": None}}])
        card = cc.native_approvals(state)[0]
        self.assertEqual((card["id"], card["approval_type"], card["files"]), ("approval:turn-one:7", "file", ["a.py", "b.py"]))
        self.assertIn("a.py", card["questions"][0]["question"])

    def test_other_requests_are_not_answerable_and_other_cases_are_not_cards(self):
        state = command_state(requests=[
            {"id": "r-perm", "method": "item/permissions/requestApproval", "params": {"threadId": "test-thread", "turnId": TURN}},
            {"id": "r-elsewhere", "method": "item/commandExecution/requestApproval",
             "params": {"threadId": "another-thread", "turnId": TURN, "command": "dir"}},
            {"id": "r-tool", "method": "item/tool/requestUserInput", "params": {"threadId": "test-thread", "turnId": TURN}},
        ])
        cards = cc.native_approvals(state)
        self.assertEqual(len(cards), 1)
        self.assertFalse(cards[0]["answerable"])
        self.assertEqual((cards[0]["choices"], cards[0]["approval_type"]), ([], "other"))
        self.assertNotIn("questions", cards[0])
        over = command_state()
        over["turns"][0]["status"] = "completed"
        over["threadRuntimeStatus"] = {"type": "idle"}
        self.assertEqual(cc.native_approvals(over), [])

    def test_an_unknown_request_is_written_down_once_with_keys_not_values(self):
        with tempfile.TemporaryDirectory() as td:
            bridge = cc.Bridge()
            bridge.data_root = Path(td)
            self.logged = []
            bridge.log = self.logged.append
            state = command_state(requests=[{"id": "r-new", "method": "item/somethingNew",
                                             "params": {"threadId": "test-thread", "reason": "秘密", "turnId": TURN}}])
            bridge._log_unknown_requests(state)
            bridge._log_unknown_requests(state)
        self.assertEqual(len(self.logged), 1)
        self.assertIn("item/somethingNew", self.logged[0])
        self.assertIn("reason", self.logged[0])
        self.assertNotIn("秘密", self.logged[0])


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rollout = Path(self.tmp.name) / "rollout.jsonl"
        self.rollout.write_text("", encoding="utf-8")
        self.bridge = cc.Bridge()
        self.bridge.data_root = Path(self.tmp.name)
        self.state = command_state()
        self.bridge.snapshot = Mock(side_effect=lambda *a, **kw: ({"path": str(self.rollout)}, "owner", copy.deepcopy(self.state)))
        self.pipe = Mock()
        self.pipe.call.return_value = {"result": {}}
        self.bridge._pipe = Mock(return_value=self.pipe)
        self.body = {"id": "test-thread", "request_id": "test-approval-0001",
                     "question_id": "approval:turn-one:req-1", "answer_revision": revision({}),
                     "answers": {"decision": ["允许一次"]}}

    def take(self):
        self.state = {**self.state, "requests": []}

    def test_accept_sends_the_command_decision_and_reads_the_state_again(self):
        handled = {**self.state, "requests": []}
        item = {"path": str(self.rollout)}
        self.bridge.snapshot = Mock(side_effect=[(item, "owner", copy.deepcopy(self.state)),
                                                 (item, "owner", copy.deepcopy(handled))])
        result = self.bridge.answer(copy.deepcopy(self.body))
        self.assertEqual((result["delivery_state"], result["ok"]), ("accepted", True))
        self.assertEqual(self.pipe.call.call_args.args[0], "thread-follower-command-approval-decision")
        self.assertEqual(self.pipe.call.call_args.args[1],
                         {"conversationId": "test-thread", "requestId": "req-1", "decision": "accept"})
        self.assertEqual(self.pipe.call.call_args.args[2], "owner")
        self.assertIn("电脑上处理过", result["text"])
        # Replayed with the same request id: its receipt, not a second decision.
        self.assertEqual(self.bridge.answer(copy.deepcopy(self.body)), result)
        self.assertEqual(self.pipe.call.call_count, 1)

    def test_decline_and_a_file_approval_use_their_own_method(self):
        self.state["requests"] = [{"id": "req-file", "method": "item/fileChange/requestApproval",
                                   "params": {"threadId": "test-thread", "turnId": TURN, "itemId": "item-file"}}]
        card = cc.native_approvals(self.state)[0]
        body = {**self.body, "question_id": card["id"], "answers": {"decision": ["拒绝"]}}
        result = self.bridge.answer(body)
        self.assertTrue(result["ok"])
        self.assertEqual(self.pipe.call.call_args.args[0], "thread-follower-file-approval-decision")
        self.assertEqual(self.pipe.call.call_args.args[1]["decision"], "decline")

    def test_free_words_are_refused_without_a_ledger_row(self):
        for answers in ({"decision": ["随便"]}, {"decision": ["允许一次", "拒绝"]}, {"other": ["允许一次"]}, {}):
            with self.assertRaises(cc.ControlError) as raised:
                self.bridge.answer({**self.body, "answers": answers})
            self.assertEqual(raised.exception.status, 400)
        self.pipe.call.assert_not_called()
        self.assertEqual(self.bridge.receipt("test-thread", self.body["request_id"])["state"], "unknown")

    def test_a_request_that_is_already_gone_is_refused_and_not_replayed(self):
        self.take()
        with self.assertRaises(cc.ControlError):
            self.bridge.answer(copy.deepcopy(self.body))
        self.pipe.call.assert_not_called()
        self.assertEqual(self.bridge.receipt("test-thread", self.body["request_id"])["state"], "unknown")

    def test_an_old_codex_is_recorded_as_rejected_and_told_to_use_the_computer(self):
        self.pipe.call.side_effect = cc.ControlError("Codex 未完成操作：request-version-mismatch")
        result = self.bridge.answer(copy.deepcopy(self.body))
        self.assertEqual((result["ok"], result["delivery_state"]), (False, "rejected"))
        self.assertIn("在电脑上处理", result["text"])
        receipt = self.bridge.receipt("test-thread", self.body["request_id"])
        self.assertEqual(receipt["state"], "rejected")
        self.assertEqual(receipt["result"]["text"], result["text"])

    def test_a_dispatching_answer_whose_request_is_gone_reads_as_accepted(self):
        self.bridge._begin(self.body["request_id"], "test-thread", self.body)
        self.take()
        receipt = self.bridge.receipt("test-thread", self.body["request_id"])
        self.assertEqual(receipt["state"], "accepted")
        self.assertIn("电脑上处理过", receipt["result"]["text"])

    def test_status_lists_the_approval_card(self):
        with patch.object(cc.chats, "conv_path", lambda item: None):
            status = self.bridge.status("test-thread")
        cards = [q for q in status["questions"] if q["kind"] == "approval"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["approval_type"], "command")
        self.assertEqual(cards[0]["answer_revision"], revision({}))

    def test_the_task_center_counts_a_waiting_approval_as_pending(self):
        center = activity.TaskCenter(None)
        center.observe("test-thread", {"available": True, "running": True, "observed_at": int(time.time() * 1000),
                                       "questions": cc.native_approvals(command_state())})
        self.assertEqual(center.live["test-thread"]["pending"], 1)


class FakeBridge:
    def __init__(self, state):
        self.state = state
        self.lock = threading.Lock()

    def snapshot(self, tid, timeout=15):
        return {"path": ""}, "owner", copy.deepcopy(self.state)


class WaitingTests(unittest.TestCase):
    """11-16: the record never holds an approval, so the notification has to read the desktop."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.now = 1_800_000_000.0
        self.sent, self.logged = [], []
        self.record = Path(self.dir.name) / "rollout.jsonl"
        self.write("task_started", "2027-01-15T08:00:00Z")
        self.items = [{"app": "codex", "id": "x1", "title": "装依赖", "path": str(self.record)}]
        self.state = command_state(id="x1")
        self.state["requests"][0]["params"]["threadId"] = "x1"
        self.bridge = FakeBridge(self.state)
        patches = [patch.object(notify.chats, "_codex_rows", lambda where, args, limit: [dict(i) for i in self.items]),
                   patch.object(notify.chats, "claude_sessions", lambda limit: []),
                   patch.object(notify.chats, "conv_path", lambda item: Path(item["path"])),
                   patch("deepseek_control.catalog", lambda: [])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.notifier = notify.Notifier({"bark": {"server": "https://api.day.app", "key": "test-key"}}, "家里电脑", self.logged.append, lambda: None, clock=lambda: self.now,
                                        sender=lambda *a, **k: self.sent.append((a, k)), page_url=lambda: "",
                                        bridge=self.bridge)

    def write(self, kind, ts, turn_id="turn-one"):
        with self.record.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "event_msg", "timestamp": ts,
                                "payload": {"type": kind, "turn_id": turn_id}}) + "\n")

    def test_waiting_is_told_once_and_kept_even_when_the_record_looks_stale(self):
        self.notifier.look()  # the started record is read as the turn it is
        self.assertIn(("codex", "x1"), self.notifier.waiting)
        self.now += 25 * 60  # 20 minutes without a new record line
        self.notifier.look()
        self.notifier.look()
        self.now += 1
        self.notifier.look()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0][1], "装依赖")
        self.assertIn("在等你选", self.sent[0][1]["subtitle"])
        self.assertIn(("codex", "x1"), self.notifier.waiting)
        self.assertNotIn(("codex", "x1"), self.notifier.running)

    def test_the_turn_is_reported_running_again_once_the_request_is_gone(self):
        self.notifier.look()
        self.now += 30
        self.notifier.look()
        self.assertEqual(len(self.sent), 1)
        self.bridge.state = {**self.state, "requests": []}
        self.now += notify.APPROVAL_EVERY + 1
        self.notifier.look()
        self.assertNotIn(("codex", "x1"), self.notifier.waiting)
        self.assertIn(("codex", "x1"), self.notifier.running)
        self.assertNotIn(("codex", "x1"), self.notifier.reported_running)


if __name__ == "__main__":
    unittest.main()



