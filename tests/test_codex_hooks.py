"""Tests for Codex 26.1117+ hooks server, TeleplyCodexHook.exe, hooks.json merge/trust, and chats display.

All tests use temporary directories, fake pipes, fake process lists, and fake kill callbacks.
Never connects to real Codex, never reads or writes the real ~/.codex, and never kills real processes.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import chat_history
import chats
import codex_apptools as ca
import codex_control
import codex_hooks as ch
from agents import registry

TID = "01000000-0000-7000-8000-000000000010"
OTHER_TID = "01000000-0000-7000-8000-000000000011"
TS1 = "2026-01-02T03:04:05Z"
TS2 = "2026-01-02T03:04:09Z"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
HOOK_CS = ROOT / "deploy/windows/TeleplyCodexHook.cs"


def _recent_input() -> tuple[int, int]:
    """Someone just used the keyboard/mouse: the PC is never 'away'."""
    return (200_000, 200_000)


def _away_input() -> tuple[int, int]:
    """Nobody touched the keyboard/mouse for 3 minutes."""
    return (200_000, 200_000 - 180_000)


class HookServerCoreTests(unittest.TestCase):
    def test_fast_path_and_disabled_server_return_empty_immediately(self) -> None:
        server = ch.CodexHookServer(pipe_name=r"\\.\pipe\teleply-unused", input_ticks=_recent_input)
        t0 = time.perf_counter()
        self.assertEqual(server.handle_event("PreToolUse", {"session_id": TID, "tool_name": "Bash"}), "")
        self.assertEqual(server.handle_event("PermissionRequest", {"session_id": TID, "tool_name": "Bash"}), "")
        self.assertEqual(server.handle_event("Stop", {"session_id": TID, "stop_hook_active": False}), "{}")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(elapsed_ms, 50.0)

        # Even when watching, disabled server immediately returns empty / {}
        server.note_phone_viewing(TID)
        server.enabled = False
        self.assertEqual(server.handle_event("PermissionRequest", {"session_id": TID, "tool_name": "Bash"}), "")
        self.assertEqual(server.handle_event("Stop", {"session_id": TID, "stop_hook_active": False}), "{}")

    def test_permission_request_allow_deny_timeout_and_unwatched(self) -> None:
        now = [100.0]
        waiting_calls = []
        server = ch.CodexHookServer(
            pipe_name=r"\\.\pipe\teleply-unused",
            clock=lambda: now[0],
            approval_timeout=0.35,
            input_ticks=_recent_input,
            on_waiting=lambda tid, card: waiting_calls.append((tid, card)),
        )

        # Unwatched -> immediate empty (hands back to desktop)
        self.assertEqual(
            server.handle_event("PermissionRequest", {"session_id": TID, "turn_id": "t1", "tool_name": "Bash", "tool_input": {"command": "echo hi"}}),
            "",
        )
        self.assertEqual(waiting_calls, [])

        # Watching -> waits for phone, allow returns strict schema without forbidden fields
        server.note_phone_viewing(TID)
        out = []

        def run_hook(payload):
            out.append(server.handle_event("PermissionRequest", payload))

        payload = {"session_id": TID, "turn_id": "t1", "tool_name": "Bash", "cwd": r"C:\demo", "tool_input": {"command": "pytest -q"}}
        th = threading.Thread(target=run_hook, args=(payload,), daemon=True)
        th.start()
        deadline = time.monotonic() + 2.0
        while not server.pending_cards(TID) and time.monotonic() < deadline:
            time.sleep(0.01)
        cards = server.pending_cards(TID)
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["kind"], "approval")
        self.assertEqual(card["approval_type"], "command")
        self.assertTrue(card["answerable"])
        self.assertEqual(card["questions"][0]["id"], "decision")
        self.assertFalse(card["questions"][0]["isOther"])
        self.assertIn("pytest -q", card["question"])

        ack = server.submit_answer(TID, {
            "id": TID,
            "request_id": "req-app-1",
            "question_id": card["id"],
            "answer_revision": card["answer_revision"],
            "answers": {"decision": ["允许一次"]},
        })
        self.assertTrue(ack["ok"])
        th.join(timeout=2.0)
        self.assertEqual(len(out), 1)
        parsed = json.loads(out[0])
        decision = parsed["hookSpecificOutput"]["decision"]
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "PermissionRequest")
        self.assertEqual(decision, {"behavior": "allow"})
        for forbidden in ("interrupt", "updatedInput", "updatedPermissions"):
            self.assertNotIn(forbidden, decision)

        # Deny flow via phone-initiated turn (even after watch window expires)
        now[0] += 60.0
        server.note_phone_turn(TID)
        out.clear()
        th2 = threading.Thread(target=run_hook, args=({
            "session_id": TID, "turn_id": "t2", "tool_name": "mcp__codex_app__create_thread",
            "tool_input": {"title": "示例"},
        },), daemon=True)
        th2.start()
        deadline = time.monotonic() + 2.0
        while not server.pending_cards(TID) and time.monotonic() < deadline:
            time.sleep(0.01)
        card2 = server.pending_cards(TID)[0]
        server.submit_answer(TID, {
            "id": TID, "request_id": "req-app-2", "question_id": card2["id"],
            "answer_revision": card2["answer_revision"], "answers": {"decision": ["拒绝"]},
        })
        th2.join(timeout=2.0)
        parsed2 = json.loads(out[0])
        self.assertEqual(parsed2["hookSpecificOutput"]["decision"]["behavior"], "deny")
        self.assertIn("拒绝", parsed2["hookSpecificOutput"]["decision"]["message"])

        # Timeout -> returns empty string (NEVER auto-approves)
        out.clear()
        th3 = threading.Thread(target=run_hook, args=(payload,), daemon=True)
        th3.start()
        th3.join(timeout=2.0)
        self.assertEqual(out, [""])

    def test_pre_tool_use_request_user_input_answer_timeout_and_unwatched(self) -> None:
        server = ch.CodexHookServer(pipe_name=r"\\.\pipe\teleply-unused", question_timeout=0.3)
        rui_payload = {
            "session_id": TID,
            "turn_id": "t-plan",
            "tool_name": "request_user_input",
            "tool_input": {
                "questions": [
                    {
                        "id": "color",
                        "header": "颜色偏好",
                        "question": "你更喜欢哪种颜色？",
                        "options": [{"label": "红色", "description": "红"}, {"label": "蓝色", "description": "蓝"}],
                    },
                    {
                        "id": "size",
                        "header": "尺寸",
                        "question": "选哪个尺寸？",
                        "options": [{"label": "小号", "description": "S"}, {"label": "大号", "description": "L"}],
                    },
                ]
            },
        }
        # Unwatched -> empty (desktop shows question card)
        self.assertEqual(server.handle_event("PreToolUse", rui_payload), "")

        # Watching -> card exposed, phone answers, PreToolUse returns deny with formatted answers
        server.note_phone_viewing(TID)
        out = []
        th = threading.Thread(target=lambda: out.append(server.handle_event("PreToolUse", rui_payload)), daemon=True)
        th.start()
        deadline = time.monotonic() + 2.0
        while not server.pending_cards(TID) and time.monotonic() < deadline:
            time.sleep(0.01)
        card = server.pending_cards(TID)[0]
        self.assertEqual(card["kind"], "native")
        self.assertEqual([q["id"] for q in card["questions"]], ["color", "size"])

        ack = server.submit_answer(TID, {
            "id": TID,
            "request_id": "req-q-1",
            "question_id": card["id"],
            "answer_revision": card["answer_revision"],
            "answers": {"color": ["蓝色"], "size": ["大号"]},
        })
        self.assertTrue(ack["ok"])
        th.join(timeout=2.0)
        parsed = json.loads(out[0])
        hso = parsed["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("用户在手机上回答了：color=蓝色；size=大号。按这个继续，不要再问。", hso["permissionDecisionReason"])

        # Timeout -> empty
        out.clear()
        th2 = threading.Thread(target=lambda: out.append(server.handle_event("PreToolUse", rui_payload)), daemon=True)
        th2.start()
        th2.join(timeout=2.0)
        self.assertEqual(out, [""])

    def test_stop_flag_immediate_fake_process_kill_and_safety_filters(self) -> None:
        killed: list[int] = []
        fake_procs = [
            {"pid": 100, "ppid": 4, "name": "ChatGPT.exe", "cmdline": "ChatGPT.exe Start-Sleep 30", "owner": r"PC\alice"},
            {"pid": 200, "ppid": 100, "name": "codex.exe", "cmdline": "codex.exe Start-Sleep 30", "owner": r"PC\alice"},
            # Target: Full Access user-owned pwsh.exe under codex.exe with codex-primary-runtime + matching cmd
            {
                "pid": 301,
                "ppid": 200,
                "name": "pwsh.exe",
                "cmdline": r'"C:\Apps\codex-primary-runtime\pwsh.exe" -Command "try { [Console]::OutputEncoding=UTF8 } catch {}' + "\nStart-Sleep 30\"",
                "owner": r"PC\alice",
            },
            # Default permission sandbox process -> MUST NOT be killed
            {
                "pid": 302,
                "ppid": 200,
                "name": "pwsh.exe",
                "cmdline": r'"C:\Apps\codex-primary-runtime\pwsh.exe" -NoProfile -Command "Start-Sleep 30"',
                "owner": r"PC\CodexSandboxOffline",
            },
            # Unrelated user terminal pwsh.exe (not under codex.exe / no codex-primary-runtime) -> MUST NOT be killed
            {
                "pid": 303,
                "ppid": 999,
                "name": "pwsh.exe",
                "cmdline": 'pwsh.exe -Command "Start-Sleep 30"',
                "owner": r"PC\alice",
            },
            # Different command under codex.exe -> MUST NOT be killed
            {
                "pid": 304,
                "ppid": 200,
                "name": "pwsh.exe",
                "cmdline": r'"C:\Apps\codex-primary-runtime\pwsh.exe" -Command "git status"',
                "owner": r"PC\alice",
            },
        ]

        server = ch.CodexHookServer(
            pipe_name=r"\\.\pipe\teleply-unused",
            list_processes=lambda: list(fake_procs),
            kill_process=lambda pid: killed.append(pid) or True,
            current_user="alice",
        )
        server.note_phone_viewing(TID)
        # PreToolUse records the running command
        self.assertEqual(
            server.handle_event("PreToolUse", {
                "session_id": TID, "turn_id": "turn-stop", "tool_name": "Bash",
                "permission_mode": "bypassPermissions", "tool_input": {"command": "Start-Sleep 30"},
            }),
            "",
        )

        # Request stop -> kills ONLY pid 301 and activates deny flag
        stop_res = server.request_stop(TID, turn_id="turn-stop")
        self.assertTrue(stop_res["ok"])
        self.assertTrue(stop_res["killed"])
        self.assertEqual(killed, [301])

        # Next PreToolUse in this turn is denied
        denied = json.loads(server.handle_event("PreToolUse", {
            "session_id": TID, "turn_id": "turn-stop", "tool_name": "Bash",
            "tool_input": {"command": "echo second"},
        }))
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("停止", denied["hookSpecificOutput"]["permissionDecisionReason"])

        # Stop event clears the stop flag
        self.assertEqual(server.handle_event("Stop", {"session_id": TID, "turn_id": "turn-stop", "stop_hook_active": False}), "{}")
        self.assertEqual(
            server.handle_event("PreToolUse", {
                "session_id": TID, "turn_id": "turn-next", "tool_name": "Bash",
                "tool_input": {"command": "echo ok"},
            }),
            "",
        )

    def test_stop_hook_queue_handoff_and_stop_hook_active_loop_guard(self) -> None:
        queue = [{"id": "q1", "prompt": "请继续做下一步"}, {"id": "q2", "prompt": "最后再检查一遍"}]
        server = ch.CodexHookServer(
            pipe_name=r"\\.\pipe\teleply-unused",
            has_queued=lambda tid: tid == TID and bool(queue),
            pop_queued=lambda tid: queue.pop(0) if tid == TID and queue else None,
        )

        # First Stop (stop_hook_active=False) pops q1 even if phone wasn't actively polling
        out1 = json.loads(server.handle_event("Stop", {"session_id": TID, "stop_hook_active": False}))
        self.assertEqual(out1, {"decision": "block", "reason": "请继续做下一步"})
        self.assertEqual(len(queue), 1)
        self.assertTrue(server.is_watching(TID))  # handed-off turn stays phone-initiated

        # Recursive Stop with stop_hook_active=True MUST NOT pop q2 (prevents infinite loop)
        out2 = json.loads(server.handle_event("Stop", {"session_id": TID, "stop_hook_active": True}))
        self.assertEqual(out2, {})
        self.assertEqual(len(queue), 1)

    def test_realtime_progress_events_and_wait_change_wakeup(self) -> None:
        seen = []
        server = ch.CodexHookServer(
            pipe_name=r"\\.\pipe\teleply-unused",
            on_progress=lambda tid, rec: seen.append((tid, rec)),
        )
        server.note_phone_viewing(TID)

        woken = []
        waiter = threading.Thread(target=lambda: woken.append(server.wait_change(TID, 2.0)), daemon=True)
        waiter.start()
        time.sleep(0.05)

        long_cmd = "python -m pytest " + "a" * 120
        server.handle_event("PreToolUse", {
            "session_id": TID, "turn_id": "t-prog", "tool_name": "Bash",
            "tool_input": {"command": long_cmd},
        })
        waiter.join(timeout=1.0)
        self.assertEqual(woken, [True])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1]["tool"], "Bash")
        self.assertEqual(len(seen[0][1]["command"]), 80)
        self.assertEqual(server.latest_progress_step(TID), "run")

        server.handle_event("Stop", {"session_id": TID, "turn_id": "t-prog", "stop_hook_active": False})
        self.assertEqual(server.latest_progress_step(TID), "")
        self.assertEqual(server.latest_progress(TID)["event"], "Stop")


def _wait_for_card(server, tid: str = TID, timeout: float = 2.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cards = server.pending_cards(tid)
        if cards:
            return cards[0]
        time.sleep(0.01)
    return None


class AwayApprovalTests(unittest.TestCase):
    """11-24 night: an approval on a PC nobody is at is held for the phone — until the phone answers,
    the person touches the keyboard/mouse, the turn is stopped, or Codex's hook timeout comes near."""

    payload = {
        "session_id": TID, "turn_id": "t-away", "tool_name": "Bash", "cwd": r"C:\demo",
        "tool_input": {"command": "python -m pytest -q"},
    }

    def _server(self, **kwargs) -> ch.CodexHookServer:
        kwargs.setdefault("pipe_name", r"\\.\pipe\teleply-unused")
        kwargs.setdefault("input_ticks", _away_input)
        kwargs.setdefault("approval_timeout", 5.0)
        kwargs.setdefault("hold_poll", 0.02)
        return ch.CodexHookServer(**kwargs)

    def test_idle_seconds_is_wrap_safe(self) -> None:
        self.assertEqual(ch.idle_seconds((200_000, 70_000)), 130.0)
        self.assertEqual(ch.idle_seconds((1_000, 1_000)), 0.0)
        self.assertIsNone(ch.idle_seconds(None))
        # GetTickCount wraps every ~49.7 days: last input just before the wrap, now just after it.
        self.assertAlmostEqual(ch.idle_seconds((5_000, 0xFFFF0000)), 70.536, places=3)
        # Windows cannot say -> never treat the PC as empty.
        self.assertFalse(self._server(input_ticks=lambda: None).is_desktop_away())

    def test_away_without_watching_holds_an_answerable_card_for_allow_and_deny(self) -> None:
        waiting: list[tuple[str, dict]] = []
        server = self._server(on_waiting=lambda tid, card: waiting.append((tid, card)))

        out: list[str] = []
        thread = threading.Thread(
            target=lambda: out.append(server.handle_event("PermissionRequest", dict(self.payload))), daemon=True)
        thread.start()
        card = _wait_for_card(server)
        self.assertIsNotNone(card, "an empty desk must keep the approval for the phone")
        self.assertEqual(card["kind"], "approval")
        self.assertTrue(card["answerable"])
        self.assertIn("pytest", card["question"])
        # The phone's existing "在等你" notice already rides on on_waiting: nobody had to add a channel.
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0][0], TID)
        self.assertEqual(waiting[0][1]["id"], card["id"])

        server.submit_answer(TID, {
            "id": TID, "request_id": "req-away-1", "question_id": card["id"],
            "answer_revision": card["answer_revision"], "answers": {"decision": ["允许一次"]},
        })
        thread.join(timeout=3.0)
        self.assertEqual(len(out), 1)
        parsed = json.loads(out[0])
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "PermissionRequest")
        self.assertEqual(parsed["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        self.assertEqual(server.pending_cards(TID), [])

        # Deny travels back exactly as before too.
        out.clear()
        thread = threading.Thread(
            target=lambda: out.append(server.handle_event("PermissionRequest", dict(self.payload))), daemon=True)
        thread.start()
        card = _wait_for_card(server)
        self.assertIsNotNone(card)
        server.submit_answer(TID, {
            "id": TID, "request_id": "req-away-2", "question_id": card["id"],
            "answer_revision": card["answer_revision"], "answers": {"decision": ["拒绝"]},
        })
        thread.join(timeout=3.0)
        decision = json.loads(out[0])["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["behavior"], "deny")
        self.assertIn("拒绝", decision["message"])

    def test_someone_at_the_pc_gets_the_desktop_dialog_at_once(self) -> None:
        server = self._server(input_ticks=_recent_input)
        started = time.perf_counter()
        self.assertEqual(server.handle_event("PermissionRequest", dict(self.payload)), "")
        self.assertLess((time.perf_counter() - started) * 1000.0, 200.0)
        self.assertEqual(server.pending_cards(TID), [])

    def test_other_events_stay_instant_while_away(self) -> None:
        server = self._server()
        question = {"session_id": TID, "turn_id": "t-away", "tool_name": "request_user_input",
                    "tool_input": {"questions": [{"id": "color", "question": "哪种颜色？",
                                                  "options": [{"label": "红色"}]}]}}
        started = time.perf_counter()
        self.assertEqual(server.handle_event("PreToolUse", question), "")
        self.assertLess((time.perf_counter() - started) * 1000.0, 200.0)
        self.assertEqual(server.pending_cards(TID), [])

    def test_keyboard_input_during_the_hold_hands_the_approval_back_to_the_desktop(self) -> None:
        ticks = [(200_000, 200_000 - 180_000)]
        server = self._server(input_ticks=lambda: ticks[0], approval_timeout=10.0)
        out: list[str] = []
        thread = threading.Thread(
            target=lambda: out.append(server.handle_event("PermissionRequest", dict(self.payload))), daemon=True)
        thread.start()
        self.assertIsNotNone(_wait_for_card(server))

        ticks[0] = (200_500, 200_500)  # the person types: last input is now after the hold began
        thread.join(timeout=3.0)
        self.assertEqual(out, [""])
        self.assertEqual(server.pending_cards(TID), [])

    def test_watching_also_hands_back_when_the_desktop_gets_input(self) -> None:
        ticks = [(200_000, 200_000)]
        server = self._server(input_ticks=lambda: ticks[0], approval_timeout=10.0)
        server.note_phone_viewing(TID)
        out: list[str] = []
        thread = threading.Thread(
            target=lambda: out.append(server.handle_event("PermissionRequest", dict(self.payload))), daemon=True)
        thread.start()
        self.assertIsNotNone(_wait_for_card(server))
        ticks[0] = (201_000, 201_000)
        thread.join(timeout=3.0)
        self.assertEqual(out, [""])

    def test_stop_during_the_hold_releases_without_approving(self) -> None:
        server = self._server(approval_timeout=10.0)
        out: list[str] = []
        thread = threading.Thread(
            target=lambda: out.append(server.handle_event("PermissionRequest", dict(self.payload))), daemon=True)
        thread.start()
        self.assertIsNotNone(_wait_for_card(server))
        server.request_stop(TID)
        thread.join(timeout=3.0)
        self.assertEqual(out, [""])
        self.assertEqual(server.pending_cards(TID), [])

    def test_hold_ends_sixty_seconds_before_the_hook_timeout_and_never_approves(self) -> None:
        # Full-size numbers first: 24 h allowed by Codex, our hold stops at 24 h minus 60 s.
        self.assertEqual(ch.PERMISSION_HOOK_TIMEOUT_SECONDS, 86400.0)
        self.assertEqual(ch.APPROVAL_HOLD_SECONDS, 86400.0 - 60.0)
        self.assertEqual(ch.CodexHookServer(pipe_name=r"\\.\pipe\teleply-unused",
                                          input_ticks=_recent_input)._approval_hold_limit(), 86340.0)

        # The same rule, scaled down so the test runs in a second: stop 0.6 s before a 1.6 s hook timeout.
        server = self._server(hook_timeout=1.6, approval_margin=0.6, approval_timeout=60.0)
        started = time.monotonic()
        out = server.handle_event("PermissionRequest", dict(self.payload))
        elapsed = time.monotonic() - started
        self.assertEqual(out, "")  # empty, never an approval
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 1.55)
        self.assertEqual(server.pending_cards(TID), [])


def _trust_toml(home: Path, data: dict) -> str:
    """config.toml entries Codex itself would write after the user trusts these hooks.json contents."""
    lines: list[str] = []
    hooks_file = home / "hooks.json"
    for event, groups in data.get("hooks", {}).items():
        label = ch.HOOK_STATE_EVENT_NAMES.get(event, (event,))[0]
        for group_idx, group in enumerate(groups):
            handlers = group.get("hooks") if isinstance(group, dict) else None
            for handler_idx, handler in enumerate(handlers or []):
                if not ch.is_teleply_handler(handler):
                    continue
                digest = ch.command_hook_trusted_hash(event, handler, group.get("matcher"))
                if digest is None:
                    continue
                lines.append(
                    f"[hooks.state.'{hooks_file}:{label}:{group_idx}:{handler_idx}']\ntrusted_hash = \"{digest}\"\n")
    return "".join(lines)


class TrustHashTests(unittest.TestCase):
    def test_hash_matches_the_published_codex_digests(self) -> None:
        # Ground truth from two independent reproductions of codex-rs command_hook_hash.
        self.assertEqual(
            ch.command_hook_trusted_hash("session_start", {"type": "command", "command": "/abs/path/forwarder", "timeout": 600}),
            "sha256:7052f4cf46032e30d7b56d23cd91adf72fcbdcba1d143b76d900f53e3cf84fc1",
        )
        self.assertEqual(
            ch.command_hook_trusted_hash("permission_request", {"type": "command", "command": "/abs/path/forwarder", "timeout": 600}),
            "sha256:354fce909e5e514e42327261e05b9b423f9fff69cde54db155fabada5db9cfda",
        )
        self.assertEqual(
            ch.command_hook_trusted_hash("session_start", {"type": "command", "command": "/private/tmp/rev-hook.sh"}),
            "sha256:932ff9c435e0eb610421fc8bcb41e0de2d9a213ca6dc6fef60eaf00bd4bcdd6e",
        )

    def test_changed_content_is_detected_in_every_accepted_shape(self) -> None:
        handler = {"type": "command", "command": '"C:\\x\\TeleplyCodexHook.exe" PermissionRequest',
                   "timeout": 86400}
        hashes = ch.command_hook_trusted_hashes("PermissionRequest", handler, "*")
        self.assertIn(ch.command_hook_trusted_hash("PermissionRequest", handler, "*"), hashes)
        self.assertEqual(len(hashes), 2)  # with and without the matcher in the identity
        with_async = dict(handler, **{"async": True})
        self.assertGreaterEqual(len(ch.command_hook_trusted_hashes("PermissionRequest", with_async, "*")), 3)
        self.assertFalse(hashes & ch.command_hook_trusted_hashes("PermissionRequest",
                                                                dict(handler, timeout=90), "*"))
        self.assertFalse(hashes & ch.command_hook_trusted_hashes("PermissionRequest",
                                                                dict(handler, command='"C:\\y\\TeleplyCodexHook.exe" PermissionRequest'), "*"))
        self.assertNotEqual(ch.command_hook_trusted_hash("PermissionRequest", handler, "*"),
                            ch.command_hook_trusted_hash("PermissionRequest", handler, "Bash"))

    def test_stale_hash_after_a_content_change_reads_as_pending_trust(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "codex_home"
            home.mkdir()
            exe = Path(td) / "TeleplyCodexHook.exe"
            self.assertTrue(ch.install_hooks(exe, codex_home=home, log=lambda _t: None))
            current = json.loads((home / "hooks.json").read_text(encoding="utf-8"))
            (home / "config.toml").write_text(_trust_toml(home, current), encoding="utf-8")
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=home), "enabled")

            # What the previous release left in every PC's config.toml: PermissionRequest timeout 90.
            stale = json.loads(json.dumps(current))
            for group in stale["hooks"]["PermissionRequest"]:
                for handler in group["hooks"]:
                    handler["timeout"] = 90
            (home / "config.toml").write_text(_trust_toml(home, stale), encoding="utf-8")
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=home), "pending_trust")

    def test_plain_legacy_trusted_hash_keeps_the_presence_only_check(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "codex_home"
            home.mkdir()
            exe = Path(td) / "TeleplyCodexHook.exe"
            ch.install_hooks(exe, codex_home=home, log=lambda _t: None)
            hooks_file = home / "hooks.json"
            (home / "config.toml").write_text(
                f"[hooks.state.'{hooks_file}:pre_tool_use:0:0']\ntrusted_hash = \"abc123\"\n"
                f"[hooks.state.'{hooks_file}:permission_request:0:0']\ntrusted_hash = \"def456\"\n"
                f"[hooks.state.'{hooks_file}:stop:0:0']\ntrusted_hash = \"ghi789\"\n",
                encoding="utf-8",
            )
            ch.reset_trust_cache()
            # No sha256: prefix -> an older/unknown recipe: report trusted as before, never worse.
            self.assertEqual(ch.read_trust_status(codex_home=home), "enabled")


class PermissionHookTimeoutConfigTests(unittest.TestCase):
    def test_existing_ninety_second_permission_hook_is_upgraded_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "codex_home"
            home.mkdir()
            hooks_file = home / "hooks.json"
            hooks_file.write_text(json.dumps({"hooks": {"PermissionRequest": [{"matcher": "*", "hooks": [
                {"type": "command", "command": r'"C:\old\TeleplyCodexHook.exe" PermissionRequest',
                 "timeout": 90}]}]}}), encoding="utf-8")
            self.assertTrue(ch.install_hooks(Path(td) / "TeleplyCodexHook.exe", codex_home=home,
                                             log=lambda _t: None))
            merged = json.loads(hooks_file.read_text(encoding="utf-8"))
            handlers = merged["hooks"]["PermissionRequest"]
            self.assertEqual(len(handlers), 1)  # the old entry is replaced, not duplicated
            self.assertEqual(handlers[0]["hooks"][0]["timeout"], 86400)

    def test_csharp_hook_program_waits_a_full_day_for_permission_replies(self) -> None:
        source = HOOK_CS.read_text(encoding="utf-8")
        permission_ms = int(re.search(r"PERMISSION_READ_TIMEOUT_MS\s*=\s*(\d+)", source).group(1))
        self.assertGreaterEqual(permission_ms, 86_400_000 - 20_000)
        self.assertLessEqual(permission_ms, 86_400_000)
        # Fast events (PreToolUse, Stop) keep their fast read wait.
        self.assertIn("DEFAULT_READ_TIMEOUT_MS = 155000", source)
        self.assertIn("ResolveReadTimeoutMs(eventName)", source)
        self.assertIn("RemainingMs(deadline)", source)


class HookInstallerAndTrustTests(unittest.TestCase):
    def test_install_preserves_user_hooks_is_idempotent_never_writes_config_toml_and_reads_trust(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_home = Path(td) / "codex_home"
            fake_home.mkdir()
            hooks_file = fake_home / "hooks.json"
            cfg_file = fake_home / "config.toml"
            exe = Path(td) / "TeleplyCodexHook.exe"

            # Pre-existing user hooks on PreToolUse and PostToolUse
            user_initial = {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-audit.exe", "timeout": 15}]}
                    ],
                    "PostToolUse": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": "my-post.exe", "timeout": 10}]}
                    ],
                }
            }
            hooks_file.write_text(json.dumps(user_initial, indent=2), encoding="utf-8")
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "not_installed")

            # Install Teleply hooks -> writes once, creates backup, preserves user hooks, does NOT create config.toml
            self.assertTrue(ch.install_hooks(exe, codex_home=fake_home, log=lambda _t: None))
            self.assertTrue((fake_home / "hooks.json.before-teleply").is_file())
            self.assertFalse(cfg_file.exists())

            merged = json.loads(hooks_file.read_text(encoding="utf-8"))
            # User's PreToolUse entry stays at index 0; Teleply's is at index 1
            self.assertEqual(merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "my-audit.exe")
            self.assertIn("TeleplyCodexHook.exe", merged["hooks"]["PreToolUse"][1]["hooks"][0]["command"])
            self.assertEqual(merged["hooks"]["PreToolUse"][1]["hooks"][0]["timeout"], 150)
            self.assertEqual(merged["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"], 86400)
            self.assertEqual(merged["hooks"]["Stop"][0]["hooks"][0]["timeout"], 10)
            self.assertEqual(merged["hooks"]["PostToolUse"], user_initial["hooks"]["PostToolUse"])

            # Idempotent second install does not rewrite
            self.assertFalse(ch.install_hooks(exe, codex_home=fake_home, log=lambda _t: None))
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "pending_trust")

            # Real Codex config.toml format: single-quoted literal path, snake_case event names, only trusted_hash (no enabled key)
            hooks_literal = str(hooks_file)
            cfg_real = (
                f"[hooks.state.'{hooks_literal}:pre_tool_use:1:0']\ntrusted_hash = \"abc123\"\n"
                f"[hooks.state.'{hooks_literal}:permission_request:0:0']\ntrusted_hash = \"def456\"\n"
                f"[hooks.state.'{hooks_literal}:stop:0:0']\ntrusted_hash = \"ghi789\"\n"
            )
            cfg_file.write_text(cfg_real, encoding="utf-8")
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "enabled")

            # Path case, forward slashes, and \\?\ extended prefix all match
            hooks_slash_upper = str(hooks_file).replace("\\", "/").upper()
            hooks_ext = r"\\?\\"[:-1] + str(hooks_file).lower()
            cfg_file.write_text(
                f"[hooks.state.'{hooks_slash_upper}:pre_tool_use:1:0']\ntrusted_hash = \"abc123\"\n"
                f"[hooks.state.'{hooks_ext}:permission_request:0:0']\ntrusted_hash = \"def456\"\n"
                f"[hooks.state.'{hooks_literal.lower()}:stop:0:0']\ntrusted_hash = \"ghi789\"\n",
                encoding="utf-8",
            )
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "enabled")

            # Explicit enabled = false disables even when trusted_hash is present
            cfg_file.write_text(
                f"[hooks.state.'{hooks_literal}:pre_tool_use:1:0']\ntrusted_hash = \"abc123\"\n"
                f"[hooks.state.'{hooks_literal}:permission_request:0:0']\ntrusted_hash = \"def456\"\n"
                f"[hooks.state.'{hooks_literal}:stop:0:0']\nenabled = false\ntrusted_hash = \"ghi789\"\n",
                encoding="utf-8",
            )
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "pending_trust")

            # Missing one of the 3 hooks in config.toml -> pending_trust
            cfg_file.write_text(
                f"[hooks.state.'{hooks_literal}:pre_tool_use:1:0']\ntrusted_hash = \"abc123\"\n"
                f"[hooks.state.'{hooks_literal}:permission_request:0:0']\ntrusted_hash = \"def456\"\n",
                encoding="utf-8",
            )
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "pending_trust")

            # Empty trusted_hash -> pending_trust
            cfg_file.write_text(
                f"[hooks.state.'{hooks_literal}:pre_tool_use:1:0']\ntrusted_hash = \"abc123\"\n"
                f"[hooks.state.'{hooks_literal}:permission_request:0:0']\ntrusted_hash = \"\"\n"
                f"[hooks.state.'{hooks_literal}:stop:0:0']\ntrusted_hash = \"ghi789\"\n",
                encoding="utf-8",
            )
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "pending_trust")

            # Legacy/explicit PascalCase + enabled = true format remains supported
            hooks_str = str(hooks_file).replace("\\", "\\\\")
            cfg_file.write_text(
                f'[hooks.state."{hooks_str}:PreToolUse:1:0"]\nenabled = true\ntrusted_hash = "abc123"\n'
                f'[hooks.state."{hooks_str}:PermissionRequest:0:0"]\nenabled = true\ntrusted_hash = "def456"\n'
                f'[hooks.state."{hooks_str}:Stop:0:0"]\nenabled = false\ntrusted_hash = "ghi789"\n',
                encoding="utf-8",
            )
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "pending_trust")

            cfg_content = (
                f'[hooks.state."{hooks_str}:PreToolUse:1:0"]\nenabled = true\ntrusted_hash = "abc123"\n'
                f'[hooks.state."{hooks_str}:PermissionRequest:0:0"]\nenabled = true\ntrusted_hash = "def456"\n'
                f'[hooks.state."{hooks_str}:Stop:0:0"]\nenabled = true\ntrusted_hash = "ghi789"\n'
            )
            cfg_file.write_text(cfg_content, encoding="utf-8")
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "enabled")

            # Missing one of the 3 hooks in hooks.json -> not_installed (even if config.toml has all 3)
            partial_hooks = json.loads(hooks_file.read_text(encoding="utf-8"))
            partial_hooks["hooks"].pop("Stop", None)
            hooks_file.write_text(json.dumps(partial_hooks, indent=2), encoding="utf-8")
            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "not_installed")
            # Restore full install before testing uninstall
            self.assertTrue(ch.install_hooks(exe, codex_home=fake_home, log=lambda _t: None))

            # Uninstall removes ONLY Teleply entries and leaves config.toml byte-identical
            self.assertTrue(ch.remove_hooks(codex_home=fake_home, log=lambda _t: None))
            after = json.loads(hooks_file.read_text(encoding="utf-8"))
            self.assertEqual(after, user_initial)
            self.assertEqual(cfg_file.read_text(encoding="utf-8"), cfg_content)
            self.assertEqual(ch.read_trust_status(codex_home=fake_home), "not_installed")

    def test_read_trust_status_caches_for_two_seconds_per_home_and_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home_a = Path(td) / "home_a"
            home_b = Path(td) / "home_b"
            home_a.mkdir()
            home_b.mkdir()
            exe = Path(td) / "TeleplyCodexHook.exe"
            now = [100.0]

            ch.reset_trust_cache()
            self.assertEqual(ch.read_trust_status(codex_home=home_a, clock=lambda: now[0]), "not_installed")
            # install_hooks clears cache immediately
            self.assertTrue(ch.install_hooks(exe, codex_home=home_a, log=lambda _t: None))
            self.assertEqual(ch.read_trust_status(codex_home=home_a, clock=lambda: now[0]), "pending_trust")
            # Separate home_b has its own cache entry
            self.assertEqual(ch.read_trust_status(codex_home=home_b, clock=lambda: now[0]), "not_installed")

            # Write trusted config.toml; within 2s cache still returns pending_trust
            hp = home_a / "hooks.json"
            (home_a / "config.toml").write_text(
                f"[hooks.state.'{hp}:pre_tool_use:0:0']\ntrusted_hash = \"h1\"\n"
                f"[hooks.state.'{hp}:permission_request:0:0']\ntrusted_hash = \"h2\"\n"
                f"[hooks.state.'{hp}:stop:0:0']\ntrusted_hash = \"h3\"\n",
                encoding="utf-8",
            )
            now[0] += 1.0
            self.assertEqual(ch.read_trust_status(codex_home=home_a, clock=lambda: now[0]), "pending_trust")
            # After 2s cache expires -> enabled
            now[0] += 1.5
            self.assertEqual(ch.read_trust_status(codex_home=home_a, clock=lambda: now[0]), "enabled")
            # remove_hooks clears cache immediately
            self.assertTrue(ch.remove_hooks(codex_home=home_a, log=lambda _t: None))
            self.assertEqual(ch.read_trust_status(codex_home=home_a, clock=lambda: now[0]), "not_installed")


class HookExeTests(unittest.TestCase):
    exe_path: Path | None = None
    _tmpdir: tempfile.TemporaryDirectory | None = None

    @classmethod
    def setUpClass(cls) -> None:
        if not CSC.is_file():
            return
        cls._tmpdir = tempfile.TemporaryDirectory()
        out = Path(cls._tmpdir.name) / "TeleplyCodexHook.exe"
        proc = subprocess.run(
            [str(CSC), "/nologo", "/target:exe", "/optimize+", f"/out:{out}", str(HOOK_CS)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise AssertionError(f"csc.exe failed: {proc.stdout}\n{proc.stderr}")
        cls.exe_path = out

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._tmpdir is not None:
            cls._tmpdir.cleanup()

    def _run_hook(self, event: str, stdin_bytes: bytes, pipe_name: str, extra_env: dict[str, str] | None = None):
        if self.exe_path is None:
            self.skipTest("csc.exe 未找到，跳过 C# 钩子小程序测试")
        env = os.environ.copy()
        env["TELEPLY_CODEX_HOOK_PIPE"] = pipe_name
        if extra_env:
            env.update(extra_env)
        t0 = time.perf_counter()
        res = subprocess.run(
            [str(self.exe_path), event],
            input=stdin_bytes,
            capture_output=True,
            env=env,
            timeout=15,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        # Iron law #1: NEVER exit with code 2 under any circumstance
        self.assertNotEqual(res.returncode, 2, f"Hook exited with forbidden code 2! stderr={res.stderr!r}")
        self.assertEqual(res.returncode, 0, f"Hook exited with {res.returncode}: stderr={res.stderr!r}")
        return res.stdout.decode("utf-8"), elapsed_ms

    def test_missing_pipe_and_bad_stdin_always_exit_0(self) -> None:
        missing = r"\\.\pipe\teleply-codex-hooks-missing-" + secrets.token_hex(6)
        out_stop, _ = self._run_hook("Stop", b'{"session_id":"t1"}', missing)
        self.assertEqual(out_stop, "{}")
        out_pre, _ = self._run_hook("PreToolUse", b'{"session_id":"t1"}', missing)
        self.assertEqual(out_pre, "")
        out_perm, _ = self._run_hook("PermissionRequest", b'{"session_id":"t1"}', missing)
        self.assertEqual(out_perm, "")
        # Malformed / empty stdin
        out_bad, _ = self._run_hook("Stop", b"{not-json", missing)
        self.assertEqual(out_bad, "{}")
        out_empty, _ = self._run_hook("PreToolUse", b"", missing)
        self.assertEqual(out_empty, "")

    def test_real_named_pipe_roundtrip_fast_empty_and_decisions(self) -> None:
        pipe = r"\\.\pipe\teleply-codex-hooks-test-" + secrets.token_hex(6)
        queue = [{"id": "q1", "prompt": "下一条排队任务"}]
        server = ch.CodexHookServer(
            pipe_name=pipe,
            has_queued=lambda tid: tid == TID and bool(queue),
            pop_queued=lambda tid: queue.pop(0) if tid == TID and queue else None,
            list_processes=lambda: [],
        )
        server.start()
        self.addCleanup(server.close)
        time.sleep(0.08)

        # Fast-path empty reply (warm run)
        out1, _ = self._run_hook("PreToolUse", json.dumps({"session_id": OTHER_TID, "tool_name": "Bash"}).encode(), pipe)
        self.assertEqual(out1, "")
        out_stop, elapsed_ms = self._run_hook("Stop", json.dumps({"session_id": OTHER_TID, "stop_hook_active": False}).encode(), pipe)
        self.assertEqual(out_stop, "{}")
        # Keep generous CI margin under load; idle benchmark is recorded separately in REPORT-2.md
        self.assertLess(elapsed_ms, 500.0)

        # Malformed stdin over live pipe -> exit 0, Stop still gets {}
        out_bad, _ = self._run_hook("Stop", b"{{{broken", pipe)
        self.assertEqual(out_bad, "{}")

        # Stop flag -> PreToolUse returns exact deny JSON via exe stdout
        server.note_phone_viewing(TID)
        server.request_stop(TID, turn_id="t-1")
        out_deny, _ = self._run_hook(
            "PreToolUse",
            json.dumps({"session_id": TID, "turn_id": "t-1", "tool_name": "Bash", "tool_input": {"command": "dir"}}).encode(),
            pipe,
        )
        parsed_deny = json.loads(out_deny)
        self.assertEqual(parsed_deny["hookSpecificOutput"]["permissionDecision"], "deny")

        # Stop hook hands off queued item via exe stdout
        out_q, _ = self._run_hook("Stop", json.dumps({"session_id": TID, "stop_hook_active": False}).encode(), pipe)
        self.assertEqual(json.loads(out_q), {"decision": "block", "reason": "下一条排队任务"})

    def test_read_timeout_and_disconnect_never_exit_2(self) -> None:
        if self.exe_path is None:
            self.skipTest("csc.exe 未找到，跳过 C# 钩子小程序测试")
        pipe = r"\\.\pipe\teleply-codex-hooks-hang-" + secrets.token_hex(6)
        import win32file
        import win32pipe

        def hang_server():
            h = win32pipe.CreateNamedPipe(
                pipe, win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                1, 4096, 4096, 0, None,
            )
            try:
                win32pipe.ConnectNamedPipe(h, None)
                time.sleep(0.6)
            except Exception:
                pass
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(h)
                except Exception:
                    pass
                try:
                    win32file.CloseHandle(h)
                except Exception:
                    pass

        th = threading.Thread(target=hang_server, daemon=True)
        th.start()
        time.sleep(0.05)
        out_stop, _ = self._run_hook(
            "Stop",
            b'{"session_id":"t1"}',
            pipe,
            extra_env={"TELEPLY_CODEX_HOOK_READ_TIMEOUT_MS": "150"},
        )
        self.assertEqual(out_stop, "{}")
        th.join(timeout=2.0)


class IntegrationAndChatsStep2Tests(unittest.TestCase):
    def test_manifest_status_cards_and_desktop_pending_trust_hint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_home = Path(td) / "codex_home"
            fake_home.mkdir()
            exe = Path(td) / "TeleplyCodexHook.exe"
            ch.install_hooks(exe, codex_home=fake_home, log=lambda _t: None)

            rollout = Path(td) / "rollout.jsonl"
            rollout.write_text(
                json.dumps({"timestamp": TS1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}}) + "\n",
                encoding="utf-8",
            )
            item = {"app": "codex", "id": TID, "title": "测试", "cwd": td, "path": str(rollout)}

            class _FakeClient:
                def read_thread(self, tid, **kw):
                    return {"thread": {"id": tid, "status": {"type": "active", "activeFlags": ["waitingOnApproval"]}}}

            legacy = codex_control.Bridge()
            legacy.data_root = Path(td) / "att"
            hooks = ch.CodexHookServer(pipe_name=r"\\.\pipe\teleply-unused", codex_home=fake_home)
            bridge = ca.AppToolsBridge(legacy, client=_FakeClient(), data_dir=Path(td) / "data", hooks=hooks, enable_background_drain=False)
            self.addCleanup(bridge.close)

            with patch.object(ca, "_list_pipes", return_value=["codex-app-tools-step2"]), \
                 patch("chats.find", return_value=item), \
                 patch("codex_control.catalog", return_value={"models": []}):
                ca.reset_route_cache()
                ch.set_default_codex_home_override(fake_home)

                # Pending trust: static manifest stays fixed; capabilities_now disables stop/approve/answer
                agent = registry.get("codex")
                m_pending = agent.manifest()
                self.assertTrue(m_pending["capabilities"]["stop"])
                self.assertTrue(m_pending["capabilities"]["approve"])
                self.assertTrue(m_pending["capabilities"]["answer"])
                self.assertEqual(m_pending["sources"]["control"], "ipc")
                now_pending = agent.capabilities_now(None, TID)
                self.assertFalse(now_pending["capabilities"]["stop"])
                self.assertFalse(now_pending["capabilities"]["approve"])
                self.assertFalse(now_pending["capabilities"]["answer"])
                self.assertEqual(now_pending["notes"]["stop"], ch.TRUST_HINT)

                st_pending = bridge.status(TID, fresh=True)
                self.assertEqual(st_pending["hook_status"], "pending_trust")
                self.assertIn("打开并信任 3 个遥应钩子", st_pending["hook_notice"])
                self.assertIn("打开并信任 3 个遥应钩子", st_pending["questions"][0]["question"])

                from relay_controller import DesktopController
                dc = DesktopController.__new__(DesktopController)
                dc.binding = {"device": "dev1"}
                dc.cfg = {"name": "测试电脑"}
                dc.state = "已连接"
                dc.detail = ""
                dc.online = True
                dc.migration_flash_until = 0
                dc.version = "0.27.0-dev.47"
                dc.startup = True
                dc.settings_open = False
                dc.auth_active = False
                dc.update = None
                dc.update_title = ""
                dc.update_notes = ""
                dc.downloading = False
                dc.installer = None
                dc.percent = 0
                self.assertIn("打开并信任 3 个遥应钩子", dc.view()["detail"])

                # Now trust all 3 hooks using real Codex config.toml format (snake_case + trusted_hash only)
                # -> capabilities_now flips True, desktop & phone trust hints disappear while manifest remains fixed
                hp_literal = str(fake_home / "hooks.json")
                (fake_home / "config.toml").write_text(
                    f"[hooks.state.'{hp_literal}:pre_tool_use:0:0']\ntrusted_hash = \"h1\"\n"
                    f"[hooks.state.'{hp_literal}:permission_request:0:0']\ntrusted_hash = \"h2\"\n"
                    f"[hooks.state.'{hp_literal}:stop:0:0']\ntrusted_hash = \"h3\"\n",
                    encoding="utf-8",
                )
                hooks._trust_cache = None
                ch.reset_trust_cache()
                m_enabled = agent.manifest()
                self.assertEqual(m_enabled, m_pending)
                now_enabled = agent.capabilities_now(None, TID)
                self.assertTrue(now_enabled["capabilities"]["stop"])
                self.assertTrue(now_enabled["capabilities"]["approve"])
                self.assertTrue(now_enabled["capabilities"]["answer"])
                self.assertNotIn("stop", now_enabled["notes"])
                self.assertEqual(dc.view()["detail"], "")
                st_enabled = bridge.status(TID, fresh=True)
                self.assertEqual(st_enabled["hook_status"], "enabled")
                self.assertNotIn("hook_notice", st_enabled)
                self.assertNotIn("打开并信任 3 个遥应钩子", st_enabled["questions"][0]["question"])

                # Disabling one hook with enabled = false turns hints back on and disables capabilities_now
                (fake_home / "config.toml").write_text(
                    f"[hooks.state.'{hp_literal}:pre_tool_use:0:0']\ntrusted_hash = \"h1\"\n"
                    f"[hooks.state.'{hp_literal}:permission_request:0:0']\nenabled = false\ntrusted_hash = \"h2\"\n"
                    f"[hooks.state.'{hp_literal}:stop:0:0']\ntrusted_hash = \"h3\"\n",
                    encoding="utf-8",
                )
                hooks._trust_cache = None
                ch.reset_trust_cache()
                m_disabled = agent.manifest()
                self.assertEqual(m_disabled, m_pending)
                now_disabled = agent.capabilities_now(None, TID)
                self.assertFalse(now_disabled["capabilities"]["stop"])
                self.assertFalse(now_disabled["capabilities"]["approve"])
                self.assertFalse(now_disabled["capabilities"]["answer"])
                self.assertEqual(now_disabled["notes"]["stop"], ch.TRUST_HINT)
                self.assertIn("打开并信任 3 个遥应钩子", dc.view()["detail"])
                st_disabled = bridge.status(TID, fresh=True)
                self.assertEqual(st_disabled["hook_status"], "pending_trust")
                self.assertIn("打开并信任 3 个遥应钩子", st_disabled["hook_notice"])

    def test_sse_stream_updates_capabilities_now_mid_stream_for_protocol_two_only(self) -> None:
        import io
        from unittest.mock import Mock
        import live_events

        with tempfile.TemporaryDirectory() as td:
            fake_home = Path(td) / "codex_home"
            fake_home.mkdir()
            exe = Path(td) / "TeleplyCodexHook.exe"
            ch.install_hooks(exe, codex_home=fake_home, log=lambda _t: None)

            rollout = Path(td) / "rollout.jsonl"
            rollout.write_text(
                json.dumps({"timestamp": TS1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}}) + "\n",
                encoding="utf-8",
            )
            item = {"app": "codex", "id": TID, "title": "测试流", "cwd": td, "path": str(rollout)}

            class _FakeClient:
                def read_thread(self, tid, **kw):
                    return {"thread": {"id": tid, "status": {"type": "active", "activeFlags": []}}}

            legacy = codex_control.Bridge()
            legacy.data_root = Path(td) / "att"
            hooks = ch.CodexHookServer(pipe_name=r"\\.\pipe\teleply-unused", codex_home=fake_home)
            bridge = ca.AppToolsBridge(legacy, client=_FakeClient(), data_dir=Path(td) / "data", hooks=hooks, enable_background_drain=False)
            self.addCleanup(bridge.close)
            legacy._apptools_bridge = bridge
            legacy._codex_hooks = hooks

            entry = SimpleNamespace(lock=threading.RLock(), messages=[], by_id={}, offset=0, state={"running": True, "current_turn_id": "t1"})
            page = {"id": TID, "status": "running", "runtime": {}, "title": "测试流", "folder": "", "activity_turns": [], "activity_current": None, "messages": []}
            history = SimpleNamespace(transcript=lambda *a: (item, entry), conversation=lambda *a, **k: dict(page))

            def run_stream(protocol: int, flip_trust: bool) -> list[dict]:
                buf = io.BytesIO()
                handler = SimpleNamespace(
                    send_response=Mock(),
                    send_header=Mock(),
                    end_headers=Mock(),
                    connection=Mock(),
                    wfile=buf,
                    server=SimpleNamespace(codex=legacy),
                    _client_protocol=lambda: protocol,
                )
                ticks = []

                def on_wait(_tid, _timeout):
                    ticks.append(1)
                    if len(ticks) == 1:
                        if flip_trust:
                            hp = str(fake_home / "hooks.json")
                            (fake_home / "config.toml").write_text(
                                f"[hooks.state.'{hp}:pre_tool_use:0:0']\ntrusted_hash = \"h1\"\n"
                                f"[hooks.state.'{hp}:permission_request:0:0']\ntrusted_hash = \"h2\"\n"
                                f"[hooks.state.'{hp}:stop:0:0']\ntrusted_hash = \"h3\"\n",
                                encoding="utf-8",
                            )
                            hooks._trust_cache = None
                            ch.reset_trust_cache()
                            bridge._status_cache.clear()
                        return True
                    raise ConnectionError("done")

                with patch.object(ca, "_list_pipes", return_value=["codex-app-tools-sse"]), \
                     patch("chats.find", return_value=item), \
                     patch("codex_control.catalog", return_value={"models": []}), \
                     patch("live_events.select.select", return_value=([], [], [])), \
                     patch.object(hooks, "wait_change", side_effect=on_wait):
                    ca.reset_route_cache()
                    ch.set_default_codex_home_override(fake_home)
                    ch.reset_trust_cache()
                    hooks._trust_cache = None
                    bridge._status_cache.clear()
                    live_events.stream(handler, history, legacy, None, "codex", TID)
                return [json.loads(line[6:]) for line in buf.getvalue().decode("utf-8").splitlines() if line.startswith("data: ")]

            # Protocol 1 never receives capabilities_now or capability_notes
            p1_events = run_stream(protocol=1, flip_trust=False)
            self.assertEqual(len(p1_events), 1)
            self.assertNotIn("capabilities_now", p1_events[0]["control"])
            self.assertNotIn("capability_notes", p1_events[0]["control"])

            # Protocol 2 gets snapshot with stop=False, then mid-stream update with stop=True once trusted
            p2_events = run_stream(protocol=2, flip_trust=True)
            self.assertEqual(len(p2_events), 2)
            self.assertEqual(p2_events[0]["type"], "snapshot")
            self.assertFalse(p2_events[0]["control"]["capabilities_now"]["stop"])
            self.assertEqual(p2_events[0]["control"]["capability_notes"]["stop"], ch.TRUST_HINT)
            self.assertEqual(p2_events[1]["type"], "update")
            self.assertTrue(p2_events[1]["control"]["capabilities_now"]["stop"])
            self.assertNotIn("stop", p2_events[1]["control"]["capability_notes"])

    def test_chats_hook_prompt_and_request_user_input_qa_display(self) -> None:
        img_id = "b" * 32
        img_path = rf"C:\FakeData\codex-images\{TID}\{img_id}.png"
        hook_msg_text = f"排队发的图文消息\n\n[附图] {img_path}（请先用看图工具打开这张图片）"
        lines = [
            # Both UserMessage with <hook_prompt> and HookPrompt item at same ts -> deduplicated to 1 user message
            (json.dumps({
                "type": "event_msg", "timestamp": TS1,
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "UserMessage", "id": "u-hook-1",
                        "content": [{"text": f'<hook_prompt hook_run_id="stop:2:C:\\fake\\hooks.json">{hook_msg_text}</hook_prompt>'}],
                    },
                },
            }, ensure_ascii=False) + "\n").encode("utf-8"),
            (json.dumps({
                "type": "event_msg", "timestamp": TS1,
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "HookPrompt", "id": "hp-1",
                        "fragments": [{"text": hook_msg_text}],
                    },
                },
            }, ensure_ascii=False) + "\n").encode("utf-8"),
            # request_user_input function_call + PreToolUse hook-blocked function_call_output
            (json.dumps({
                "type": "response_item", "timestamp": TS1,
                "payload": {
                    "type": "function_call", "name": "request_user_input", "call_id": "call-rui-1",
                    "arguments": json.dumps({
                        "questions": [
                            {"id": "color", "header": "颜色偏好", "question": "你更喜欢哪种颜色？",
                             "options": [{"label": "红色"}, {"label": "蓝色"}]}
                        ]
                    }, ensure_ascii=False),
                },
            }, ensure_ascii=False) + "\n").encode("utf-8"),
            (json.dumps({
                "type": "response_item", "timestamp": TS2,
                "payload": {
                    "type": "function_call_output", "call_id": "call-rui-1",
                    "output": "Tool call blocked by PreToolUse hook: 用户在手机上回答了：color=蓝色。按这个继续，不要再问。. Tool: request_user_input",
                },
            }, ensure_ascii=False) + "\n").encode("utf-8"),
        ]

        msgs, _ = chats.parse_codex(lines, thread_id=TID)
        self.assertEqual(len(msgs), 3)
        # 1) Hook prompt user message (clean text + image attachment, no <hook_prompt> tags, no duplicate)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["text"], "排队发的图文消息")
        self.assertEqual(len(msgs[0]["images"]), 1)
        self.assertEqual(msgs[0]["images"][0]["id"], img_id)
        # 2) Question bubble + 3) Phone answer bubble
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertIn("你更喜欢哪种颜色", msgs[1]["text"])
        self.assertEqual(msgs[2]["role"], "user")
        self.assertEqual(msgs[2]["text"], "你在手机上的回答：蓝色")

        # Also works incrementally via chat_history.History and find_delegation_delivery
        with tempfile.TemporaryDirectory() as td:
            rollout = Path(td) / "rollout.jsonl"
            rollout.write_bytes(b"".join(lines))
            item = {"app": "codex", "id": TID, "title": "测试", "cwd": td, "path": str(rollout)}
            with patch("chats.find", return_value=item):
                page = chat_history.History().conversation("codex", TID)
                self.assertEqual([m["text"] for m in page["messages"]], [
                    "排队发的图文消息",
                    msgs[1]["text"],
                    "你在手机上的回答：蓝色",
                ])
            delivered = ca.find_delegation_delivery(rollout, TID, hook_msg_text)
            self.assertIsNotNone(delivered)
            self.assertEqual(delivered["message_id"], "u-hook-1")


if __name__ == "__main__":
    unittest.main()
