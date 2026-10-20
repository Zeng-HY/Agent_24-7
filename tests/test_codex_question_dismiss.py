import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_control as cc
import codex_question_dismiss as d


def fixtures():
    job = {"thread": "thread", "turn_id": "turn", "question_id": "async:call", "request_id": "request-00000001", "answer_hash": d.answer_hash("5")}
    question = {"type": "agentMessage", "id": "call", "questions": [{"title": "Test", "options": ["10", "5"]}]}
    text = "<send_user_message_question_reply>\n"+json.dumps([{"questionItemId": json.dumps(["request_user_input_async", "call", 0]), "question": "Test", "answer": "5"}])+"\n</send_user_message_question_reply>"
    reply = {"type": "steeringUserMessage", "status": "accepted", "clientUserMessageId": job["request_id"], "serverUserMessageId": "server-message", "input": [{"type": "text", "text": text}]}
    state = {"id": "thread", "hostId": "local", "title": "Unique", "turns": [{"turnId": "turn", "items": [question, reply]}]}
    view = {"identity_ok": True, "visible": True, "card_count": 1, "question": "Test", "options": ["10", "5"], "invoke_supported": True, "focused": False, "selection_readable": True, "editor_readable": True, "selected": ["5"], "draft": "", "has_submitted": True}
    return job, state, view


class EvidenceTests(unittest.TestCase):
    def test_accepted_reply_and_server_echo(self):
        job, state, view = fixtures(); spec, reason = d.evidence(state, job)
        self.assertIsNone(reason); self.assertIsNone(d.assess(view, spec))
        reply = state["turns"][0]["items"][1]
        state["turns"][0]["items"].append({"type": "userMessage", "id": "server-message", "content": reply["input"]})
        self.assertIsNone(d.evidence(state, job)[1])

    def test_real_normalized_history_and_null_question_fields(self):
        job, state, _ = fixtures(); turns = state.pop("turns")
        turns[0]["items"].append({"type": "agentMessage", "questions": None})
        state["turnHistory"] = {"history": {"entitiesByKey": {"key": turns[0]}}}
        self.assertIsNone(d.evidence(state, job)[1])

    def test_http_ack_or_pending_steer_is_not_enough(self):
        job, state, _ = fixtures(); state["turns"][0]["items"][1]["status"] = "pending"
        self.assertEqual(d.evidence(state, job)[1], "awaiting_desktop_evidence")

    def test_new_answer_identity_supersedes_even_identical_text(self):
        job, state, _ = fixtures(); state["turns"][0]["items"][1]["clientUserMessageId"] = "newer"
        self.assertEqual(d.evidence(state, job)[1], "answer_superseded")

    def test_duplicate_question_and_multi_question_rejected(self):
        job, state, _ = fixtures(); question = state["turns"][0]["items"][0]
        other = copy.deepcopy(question); other["id"] = "other"
        state["turns"][0]["items"].append(other)
        self.assertEqual(d.evidence(state, job)[1], "ambiguous_question")
        state["turns"][0]["items"].pop(); question["questions"] *= 2
        self.assertEqual(d.evidence(state, job)[1], "unsupported_question")

    def test_wrong_thread_or_turn_is_rejected(self):
        job, state, _ = fixtures(); state["id"] = "other"
        self.assertEqual(d.evidence(state, job)[1], "identity_changed")
        state["id"] = "thread"; job["turn_id"] = "other"
        self.assertEqual(d.evidence(state, job)[1], "turn_unavailable")

    def test_draft_focus_selection_and_scope_guards(self):
        job, state, view = fixtures(); spec, _ = d.evidence(state, job)
        cases = [({"identity_ok": False}, "identity_unverified"), ({"visible": False}, "window_not_visible"), ({"foreground": False}, "window_not_foreground"),
                 ({"card_count": 0}, "not_present"), ({"card_count": 2}, "ambiguous_card"),
                 ({"question": "Other"}, "card_changed"), ({"options": ["5"]}, "card_changed"),
                 ({"invoke_supported": False}, "invoke_unavailable"), ({"focused": True}, "editing"),
                 ({"selection_readable": False}, "draft_unreadable"), ({"editor_readable": False}, "draft_unreadable"),
                 ({"selected": ["10"]}, "unsubmitted_draft"), ({"draft": "20"}, "unsubmitted_draft"),
                 ({"has_submitted": False}, "unsubmitted_draft"), ({"selected": []}, "unsubmitted_draft")]
        for changes, expected in cases:
            with self.subTest(changes=changes): self.assertEqual(d.assess({**view, **changes}, spec), expected)
        self.assertIsNone(d.assess({**view, "selected": [], "draft": "5"}, spec))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.bridge = cc.Bridge(); self.bridge.data_root = Path(self.tmp.name)
        self.manager = d.DismissManager(self.bridge, True, d.VERIFIED_VERSION)
        self.manager.pool.shutdown(); self.manager.pool = Mock()
        self.card = {"id": "async:call", "kind": "async", "turn_id": "turn", "questions": [{"id": "0"}]}
        self.rid = "request-00000001"

    def arm(self): self.manager.arm(self.rid, "thread", self.card, {"0": ["sensitive-answer"]})

    def test_only_first_accepted_transition_schedules(self):
        self.arm(); self.manager.accepted(self.rid); self.manager.accepted(self.rid)
        self.manager.pool.submit.assert_called_once()

    def test_historical_and_unsupported_answers_never_schedule(self):
        self.manager.accepted("old-request"); self.manager.pool.submit.assert_not_called()
        self.card["questions"] *= 2; self.arm(); self.manager.accepted(self.rid)
        self.manager.pool.submit.assert_not_called()

    def test_disabled_and_unverified_version_never_schedule(self):
        for enabled, version in [(False, d.VERIFIED_VERSION), (True, "future")]:
            self.manager.enabled, self.manager.version = enabled, version
            self.rid += "x"; self.arm(); self.manager.accepted(self.rid)
        self.manager.pool.submit.assert_not_called()

    def test_ledger_never_contains_answers_and_restart_does_not_retry(self):
        self.arm(); self.manager._save(self.rid, "invoking", windows={"window": {"status": "unconfirmed"}})
        fresh = d.DismissManager(self.bridge, True, d.VERIFIED_VERSION); fresh.pool.shutdown(); fresh.pool = Mock()
        fresh.accepted(self.rid); fresh.pool.submit.assert_not_called()
        self.assertEqual(fresh.result(self.rid)["status"], "unconfirmed")
        with self.bridge._db() as db:
            rows = db.execute("SELECT * FROM desktop_dismiss").fetchall()
        self.assertNotIn("sensitive-answer", str(rows))

    def test_reopened_panel_is_not_retried(self):
        self.arm(); self.manager._save(self.rid, "closed"); self.manager.accepted(self.rid)
        self.manager.pool.submit.assert_not_called()

    def test_windows_have_independent_results(self):
        self.arm(); windows = {"a": {"status": "closed"}, "b": {"status": "retained", "reason": "editing"}}
        self.manager._save(self.rid, "retained", "editing", windows)
        self.assertEqual(self.manager.result(self.rid)["windows"], windows)


if __name__ == "__main__": unittest.main()
