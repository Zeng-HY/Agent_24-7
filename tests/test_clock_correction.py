"""11-27: the times the phone subtracts its own "now" from go out against the relay's clock (pc_clock), and a turn's
length must not change: its start and its end are shifted together. This checks the places they leave by: the list
rows, the control state (and the live stream's control), the task rows, the activity card's clock (the web page counts
it from these milliseconds), and the events the relay turns into a notice and an island.

Everything here is made up: a made-up rollout file, a made-up desktop state, a made-up notifier. No real record,
log, config or running app is read.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_history  # noqa: E402
import chats  # noqa: E402
import codex_control  # noqa: E402
import notify  # noqa: E402
import pc_clock  # noqa: E402

NOW = 1_000_000.0  # this computer's made-up time (Unix seconds)
SLOW = 46.0        # how far behind the relay it is on 11-27
STARTED, ENDED = 1767323050, 1767323110


def unix(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def offset_by(seconds: float) -> pc_clock.Clock:
    """The state a run is in after the relay's answers say it is [seconds] ahead (negative: behind)."""
    clock = pc_clock.reset(clock=lambda: NOW)
    clock.add(NOW + seconds, NOW)
    return clock


def event(ts: str, **payload) -> str:
    return json.dumps({"type": "event_msg", "timestamp": ts, "payload": payload}) + "\n"


def reply(ts: str, **payload) -> str:
    return json.dumps({"type": "response_item", "timestamp": ts, "payload": payload}) + "\n"


# One Codex turn: it starts, waits 20 s for the user's answer, and completes 5 s after the answer came back.
STARTED_AT, ASKED_AT, ANSWERED_AT, ENDED_AT = (
    unix("2026-11-27T" + at + "Z") for at in ("05:00:00", "05:00:05", "05:00:25", "05:00:30"))
FINISHED = [event("2026-11-27T05:00:00Z", type="task_started", turn_id="t1"),
            reply("2026-11-27T05:00:05Z", type="function_call", name="request_user_input", call_id="q"),
            reply("2026-11-27T05:00:25Z", type="function_call_output", call_id="q"),
            event("2026-11-27T05:00:30Z", type="task_complete", turn_id="t1")]
WAITING = FINISHED[:2]  # the answer never came: the turn is paused, not ended


class ListRowTests(unittest.TestCase):
    """The list's rows: /api/chats builds them in chat_history.conversations."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(pc_clock.reset)
        started, ended = "2026-11-27T05:00:00Z", "2026-11-27T05:01:00Z"
        self.started, self.ended = unix(started), unix(ended)
        path = Path(self.temp.name) / "rollout.jsonl"
        path.write_text(
            json.dumps({"type": "event_msg", "timestamp": started, "payload": {"type": "task_started"}}) + "\n"
            + json.dumps({"type": "event_msg", "timestamp": ended, "payload": {"type": "task_complete"}}) + "\n",
            encoding="utf-8")
        conv = mock.patch.object(chats, "conv_path", lambda item: path)
        conv.start()
        self.addCleanup(conv.stop)
        self.item = {"app": "codex", "id": "c1", "title": "改一行", "folder": "", "cwd": "",
                     "updated": 1767323000000, "created": 1767322900000, "pinned": False}

    def row(self) -> dict:
        history = chat_history.History()
        history._load = lambda: ([dict(self.item)], [])
        return history.conversations("all", 10)["items"][0]

    def test_with_no_offset_the_row_is_exactly_what_it_was(self):
        pc_clock.reset(clock=lambda: NOW)
        expected = {"app": "codex", "id": "c1", "title": "改一行", "folder": "", "cwd": "",
                    "updated": 1767323000000, "created": 1767322900000, "pinned": False,
                    "status": "idle", "preview": "", "turn_started": self.started,
                    "turn_ended": self.ended, "step": ""}
        self.assertEqual(json.dumps(self.row(), ensure_ascii=False, sort_keys=True),
                         json.dumps(expected, ensure_ascii=False, sort_keys=True))

    def test_with_a_slow_clock_both_times_move_by_the_offset(self):
        offset_by(SLOW)
        row = self.row()
        self.assertEqual(row["turn_started"], self.started + 46)
        self.assertEqual(row["turn_ended"], self.ended + 46)
        self.assertEqual(row["turn_ended"] - row["turn_started"], 60)

    def test_the_other_list_rows_are_shifted_too(self):
        """chats.list_conversations builds the task summary's rows (they carry turn_started/turn_ended as well)."""
        from agents import registry
        item = {"app": "codex", "id": "c1", "title": "改一行", "folder": "", "cwd": "",
                "updated": 1, "created": 1, "pinned": False, "status": "running", "preview": "",
                "turn_started": self.started, "turn_ended": self.ended, "step": ""}
        agent = SimpleNamespace(id="codex", home_list=True, catalog_entries=lambda limit: [dict(item)],
                                summary=lambda row: {**row})
        offset_by(SLOW)
        with mock.patch.object(registry, "load", lambda *a, **k: [agent]), \
                mock.patch.object(registry, "get", lambda app, *a, **k: agent):
            rows = chats.list_conversations("codex", 10)
        self.assertEqual((rows[0]["turn_started"], rows[0]["turn_ended"]),
                         (self.started + 46, self.ended + 46))
        self.assertEqual(rows[0]["turn_ended"] - rows[0]["turn_started"], 60)


class ActivityClockTests(unittest.TestCase):
    """The web page's activity card (static/interaction-ui.js, line 91) counts its duration up from started_at — or
    down to ended_at / paused_at — against Date.now(), and each pause up from its own start. These are the same
    family as turn_started, in milliseconds, so they move by the same offset and the card's duration does not."""

    def setUp(self) -> None:
        self.addCleanup(pc_clock.reset)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rollout.jsonl"
        item = {"app": "codex", "id": "c1", "title": "改一行", "folder": "", "cwd": "",
                "updated": 1767323000000, "created": 1767322900000, "pinned": False}
        for patcher in (mock.patch.object(chats, "find", lambda app, tid: dict(item)),
                        mock.patch.object(chats, "conv_path", lambda row: self.path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.history = chat_history.History()
        self.history._load = lambda: ([dict(item)], [])

    def clock(self, lines: list[str], offset: float = 0.0) -> dict:
        """The page's activity clock for this made-up record, read with [offset] seconds of clock difference."""
        self.path.write_text("".join(lines), encoding="utf-8")
        if offset:
            offset_by(offset)
        else:
            pc_clock.reset(clock=lambda: NOW)
        page = self.history.conversation("codex", "c1", 10)
        return page["activity_turns"]["t1"]

    def test_with_no_offset_the_clock_is_exactly_what_it_was(self):
        clock = self.clock(FINISHED)
        self.assertEqual((clock["started_at"], clock["ended_at"]), (STARTED_AT * 1000, ENDED_AT * 1000))
        self.assertEqual(clock["pauses"], [[ASKED_AT * 1000, ANSWERED_AT * 1000]])
        self.assertEqual(clock["paused_ms"], 20_000)

    def test_a_slow_clock_moves_every_time_and_keeps_the_duration(self):
        before = self.clock(FINISHED)
        clock = self.clock(FINISHED, SLOW)
        self.assertEqual(clock["started_at"], STARTED_AT * 1000 + 46_000)
        self.assertEqual(clock["ended_at"], ENDED_AT * 1000 + 46_000)
        self.assertEqual(clock["pauses"], [[ASKED_AT * 1000 + 46_000, ANSWERED_AT * 1000 + 46_000]])
        self.assertEqual(clock["paused_ms"], before["paused_ms"])  # a duration: it does not move
        self.assertEqual(clock["ended_at"] - clock["started_at"] - clock["paused_ms"],
                         before["ended_at"] - before["started_at"] - before["paused_ms"])
        self.assertEqual(clock["status"], "completed")

    def test_a_waiting_turn_moves_its_pause_too(self):
        self.assertEqual(self.clock(WAITING)["paused_at"], ASKED_AT * 1000)
        clock = self.clock(WAITING, SLOW)
        self.assertEqual(clock["paused_at"], ASKED_AT * 1000 + 46_000)
        self.assertEqual(clock["started_at"], STARTED_AT * 1000 + 46_000)
        self.assertNotIn("ended_at", clock)


class ControlStateTests(unittest.TestCase):
    """The control state a phone reads every second (and the live stream's `control`): codex_control.Bridge.status."""

    def setUp(self) -> None:
        self.addCleanup(pc_clock.reset)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rollout.jsonl"
        self.path.write_text("", encoding="utf-8")

    @staticmethod
    def state(started_ms: int, status: str = "inProgress", duration_ms: int = 0, compacting: bool = False) -> dict:
        turn = {"turnId": "t1", "turnStartedAtMs": started_ms, "status": status, "items": []}
        if duration_ms:
            turn["durationMs"] = duration_ms
        if compacting:
            turn["items"] = [{"type": "contextCompaction", "completed": False}]
        return {"turnHistory": {"history": {"entitiesByKey": {"t1": turn}}},
                "threadRuntimeStatus": {"type": "active" if status == "inProgress" else "idle"}}

    def status(self, state: dict) -> dict:
        bridge = codex_control.Bridge()
        item = {"app": "codex", "id": "t1", "title": "改一行", "path": str(self.path)}
        with mock.patch.object(bridge, "snapshot", lambda tid, fresh=False: (item, "owner", state)), \
                mock.patch.object(chats, "conv_path", lambda row: None), \
                mock.patch.object(codex_control, "catalog", lambda: {"models": []}):
            return bridge.status("t1")

    def test_with_no_offset_the_state_is_exactly_what_it_was(self):
        pc_clock.reset(clock=lambda: NOW)
        state = self.status(self.state(STARTED * 1000))
        self.assertEqual(state["turn_started"], STARTED)
        self.assertEqual(state["turn_ended"], 0)
        self.assertEqual(state["compact_started"], 0)

    def test_a_running_turn_moves_and_a_finished_one_keeps_its_length(self):
        offset_by(SLOW)
        running = self.status(self.state(STARTED * 1000))
        self.assertEqual(running["turn_started"], STARTED + 46)
        self.assertEqual(running["turn_ended"], 0)
        done = self.status(self.state(STARTED * 1000, status="completed", duration_ms=8000))
        self.assertEqual(done["turn_started"], STARTED + 46)
        self.assertEqual(done["turn_ended"], STARTED + 8 + 46)
        self.assertEqual(done["turn_ended"] - done["turn_started"], 8)

    def test_a_compaction_starts_at_the_same_moment_as_the_turn(self):
        offset_by(SLOW)
        state = self.status(self.state(STARTED * 1000, compacting=True))
        self.assertTrue(state["compacting"])
        self.assertEqual(state["step"], "compact")
        self.assertEqual(state["compact_started"], STARTED + 46)
        self.assertEqual(state["compact_started"], state["turn_started"])


class NotifyEventTests(unittest.TestCase):
    """What notify.py sends to the relay: the phone's notice and its island count from started/ended/since."""

    def setUp(self) -> None:
        self.addCleanup(pc_clock.reset)
        self.log = []
        self.config = {"token": "secret"}
        self.notifier = notify.Notifier(self.config, "这台电脑", self.log.append, lambda: None,
                                        clock=lambda: NOW, sender=lambda *a, **k: None,
                                        page_url=lambda: "https://pc.example.ts.net/")
        self.notifier.relay.listening = 1  # the relay is reading this computer's events
        self.item = {"app": "codex", "id": "t1", "title": "改一行"}

    def test_with_no_offset_the_events_are_exactly_what_they_were(self):
        pc_clock.reset(clock=lambda: NOW)
        self.notifier._tell(None, self.item, {"state": "done", "key": "k", "text": "",
                                              "started": STARTED, "ended": ENDED})
        event = self.notifier.relay.messages[-1][1]
        self.assertEqual((event["started"], event["ended"]), (STARTED, ENDED))
        self.notifier._running(self.item, {"started": iso(STARTED), "key": "k"})
        running = self.notifier.relay.messages[-1][1]
        self.assertEqual((running["started"], running["since"]), (STARTED, STARTED))

    def test_a_finished_turn_moves_both_times_and_keeps_its_length(self):
        offset_by(SLOW)
        self.notifier._tell(None, self.item, {"state": "done", "key": "k", "text": "",
                                              "started": STARTED, "ended": ENDED})
        event = self.notifier.relay.messages[-1][1]
        self.assertEqual((event["started"], event["ended"]), (STARTED + 46, ENDED + 46))
        self.assertEqual(event["ended"] - event["started"], 60)

    def test_a_running_turn_and_a_step_carry_the_offset(self):
        offset_by(SLOW)
        self.notifier._running(self.item, {"started": iso(STARTED), "key": "k"})
        running = self.notifier.relay.messages[-1][1]
        self.assertEqual((running["started"], running["since"]), (STARTED + 46, STARTED + 46))
        self.notifier._step(self.item, {"action": "run"}, True)
        step = self.notifier.relay.fresh[-1][1]
        self.assertEqual(step["since"], STARTED + 46)

    def test_the_snapshot_of_what_runs_carries_the_offset(self):
        offset_by(SLOW)
        self.notifier.running[("codex", "t1")] = {"since": STARTED, "title": "改一行", "item": self.item}
        self.notifier.waiting[("codex", "t2")] = {"since": STARTED - 51, "title": "等你", "item": self.item}
        self.notifier._snapshot(force=True)
        items = self.notifier.relay.fresh[-1][1]["items"]
        self.assertEqual([(row["chat"], row["started"], row["since"]) for row in items],
                         [("t1", STARTED + 46, STARTED + 46), ("t2", STARTED - 5, STARTED - 5)])


if __name__ == "__main__":
    unittest.main()
