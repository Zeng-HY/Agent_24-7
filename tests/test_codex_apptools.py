"""Tests for Codex 26.1117+ app-tools route, route selection, queue, images, skills, and chats display.

All tests use fake pipes, fake transports, and temporary directories; never touches real Codex.
"""
from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
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
import composer_commands
import composer_references
import remote
from agents import registry

TID = "01000000-0000-7000-8000-000000000001"
OTHER_TID = "01000000-0000-7000-8000-000000000002"
TS1 = "2026-01-02T03:04:05Z"
TS2 = "2026-01-02T03:04:10Z"

VALID_TOOLS = [
    {
        "name": "send_message_to_thread",
        "namespace": "codex_app",
        "inputSchema": {
            "type": "object",
            "required": ["threadId", "prompt"],
            "properties": {"threadId": {}, "prompt": {}, "hostId": {}, "model": {}, "thinking": {}},
        },
    },
    {
        "name": "read_thread",
        "namespace": "codex_app",
        "inputSchema": {
            "type": "object",
            "required": ["threadId"],
            "properties": {"threadId": {}, "hostId": {}, "includeTurns": {}},
        },
    },
]


class FakeTransport:
    def __init__(self, handler, path: str) -> None:
        self._handler = handler
        self.path = path
        self.closed = False

    def request(self, payload: dict, timeout: float = 30.0) -> dict:
        # Exercise real framing pack/unpack on every request in tests
        framed = ca.pack_frame(payload)
        size = ca.unpack_frame_size(framed[:4])
        decoded = json.loads(framed[4:4 + size].decode("utf-8"))
        return self._handler(self.path, decoded)

    def close(self) -> None:
        self.closed = True


def _ok_tool(data: dict, req_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "success": True,
            "contentItems": [{"type": "inputText", "text": json.dumps(data, ensure_ascii=False)}],
        },
    }


def _call_http(server, method: str, path: str, body=None, protocol: int = 2):
    handler = object.__new__(remote.Handler)
    sent = []
    sep = "&" if "?" in path else "?"
    handler.path = f"{path}{sep}t=secret"
    headers = {"X-Teleply-Protocol": str(protocol)}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Length"] = str(len(payload))
    else:
        payload = b""
    handler.headers = headers
    handler.rfile = io.BytesIO(payload)
    handler.close_connection = False
    handler.server = server
    handler._send = lambda code, data, ctype, extra=None: sent.append((code, json.loads(data.decode("utf-8"))))
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    return sent[0]


class RouteSelectionTests(unittest.TestCase):
    def tearDown(self) -> None:
        ca.reset_route_cache()

    def test_route_detection_priority_cache_and_dynamic_manifest(self) -> None:
        now = [100.0]
        pipes = [["codex-ipc"]]
        with patch.object(ca, "_list_pipes", side_effect=lambda: list(pipes[0])):
            ca.reset_route_cache()
            self.assertEqual(ca.detect_route(clock=lambda: now[0]), ("legacy", "codex-ipc"))

            # Both present -> legacy wins
            pipes[0] = ["codex-ipc", "codex-app-tools-aaaa"]
            self.assertEqual(ca.detect_route(force=True, clock=lambda: now[0]), ("legacy", "codex-ipc"))

            # Switch to apptools, but within 2s cache still returns legacy
            pipes[0] = ["codex-app-tools-bbbb"]
            now[0] += 1.0
            self.assertEqual(ca.detect_route(clock=lambda: now[0]), ("legacy", "codex-ipc"))

            # After 2s cache expires -> apptools
            now[0] += 1.5
            self.assertEqual(ca.detect_route(clock=lambda: now[0]), ("apptools", "codex-app-tools-bbbb"))

            # Neither pipe -> none
            pipes[0] = ["unrelated-pipe"]
            now[0] += 2.5
            self.assertEqual(ca.detect_route(clock=lambda: now[0]), ("none", None))

    def test_manifest_and_commands_recompute_live_on_route_change(self) -> None:
        pipes = [["codex-ipc"]]
        with patch.object(ca, "_list_pipes", side_effect=lambda: list(pipes[0])):
            ca.reset_route_cache()
            agent = registry.get("codex")
            m_legacy = agent.manifest()
            self.assertTrue(m_legacy["capabilities"]["stop"])
            self.assertTrue(m_legacy["capabilities"]["slash_commands"])
            self.assertEqual(m_legacy["sources"]["control"], "ipc")
            self.assertEqual([c["name"] for c in composer_commands.catalog("codex", TID)["items"]], ["compact"])

            # Mid-run switch to apptools on the SAME agent instance
            pipes[0] = ["codex-app-tools-1111"]
            ca.reset_route_cache()
            m_new = agent.manifest()
            self.assertFalse(m_new["capabilities"]["stop"])
            self.assertFalse(m_new["capabilities"]["approve"])
            self.assertFalse(m_new["capabilities"]["answer"])
            self.assertFalse(m_new["capabilities"]["slash_commands"])
            self.assertTrue(m_new["capabilities"]["queue"])
            self.assertTrue(m_new["capabilities"]["steer"])
            self.assertTrue(m_new["capabilities"]["attachments"])
            self.assertEqual(m_new["capabilities"]["send_modes"], ["send", "steer", "queue"])
            self.assertEqual(m_new["sources"]["control"], "app-tools")
            self.assertEqual(composer_commands.catalog("codex", TID)["items"], [])

            # Mid-run switch to none (Codex closed)
            pipes[0] = []
            ca.reset_route_cache()
            m_none = agent.manifest()
            self.assertFalse(m_none["capabilities"]["queue"])
            self.assertFalse(m_none["capabilities"]["steer"])
            self.assertEqual(m_none["capabilities"]["send_modes"], [])
            self.assertEqual(m_none["sources"]["control"], "none")


class ClientProtocolTests(unittest.TestCase):
    def tearDown(self) -> None:
        ca.reset_route_cache()

    def test_frame_limits_and_error_translation(self) -> None:
        with self.assertRaises(ca.AppToolsError) as big:
            ca.pack_frame({"data": "x" * (ca.MAX_FRAME_BYTES + 10)})
        self.assertEqual(big.exception.code, "frame_too_large")
        with self.assertRaises(ca.AppToolsError):
            ca.unpack_frame_size(struct.pack("<I", 0))
        with self.assertRaises(ca.AppToolsError):
            ca.unpack_frame_size(struct.pack("<I", ca.MAX_FRAME_BYTES + 1))

        self.assertIn("窗口没准备好", str(ca.translate_error("No ready app window supports app tools")))
        self.assertIn("找不到这个对话", str(ca.translate_error("Thread not found")))
        self.assertIn("拒绝了本机连接", str(ca.translate_error("Unauthorized peer")))
        self.assertIn("超时", str(ca.translate_error("request timed out")))

    def test_tools_list_verification_disables_incompatible_schema_and_recovers_on_new_pipe(self) -> None:
        pipes = [["codex-app-tools-bad"]]
        bad_tools = [{"name": "send_message_to_thread", "namespace": "codex_app",
                      "inputSchema": {"required": ["threadId", "prompt", "newMandatoryToken"]}}]
        calls = []

        def handler(path, req):
            calls.append((path, req["method"]))
            if req["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": bad_tools if "bad" in path else VALID_TOOLS}}
            return _ok_tool({"thread": {"status": {"type": "idle"}}}, req["id"])

        client = ca.AppToolsClient(transport_factory=lambda p, t: FakeTransport(handler, p))
        with patch.object(ca, "_list_pipes", side_effect=lambda: list(pipes[0])):
            ca.reset_route_cache()
            with self.assertRaises(ca.AppToolsError) as caught:
                client.read_thread(TID)
            self.assertEqual(caught.exception.code, "protocol_incompatible")
            self.assertIn("升级了", str(caught.exception))
            # Second call on the same bad pipe does not hit tools/list again
            with self.assertRaises(ca.AppToolsError):
                client.read_thread(TID)
            self.assertEqual(len(calls), 1)

            # Codex restarted with a new UUID and valid schema -> re-verifies and succeeds
            pipes[0] = ["codex-app-tools-good"]
            ca.reset_route_cache()
            info = client.read_thread(TID)
            self.assertEqual(info["thread"]["status"]["type"], "idle")

    def test_window_not_ready_wakes_with_codex_link_and_retries_once(self) -> None:
        opened = []
        slept = []
        attempts = [0]

        def handler(path, req):
            if req["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": VALID_TOOLS}}
            attempts[0] += 1
            if attempts[0] == 1:
                return {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": "No ready app window supports app tools"}}
            return _ok_tool({"threadId": TID}, req["id"])

        client = ca.AppToolsClient(
            transport_factory=lambda p, t: FakeTransport(handler, p),
            opener=opened.append,
            sleep_fn=slept.append,
            wake_delay=2.0,
        )
        with patch.object(ca, "_list_pipes", return_value=["codex-app-tools-wake"]):
            ca.reset_route_cache()
            res = client.send_message_to_thread(TID, "测试唤醒", turn_id="turn-1")
        self.assertTrue(res["success"])
        self.assertEqual(opened, [f"codex://threads/{TID}"])
        self.assertEqual(slept, [2.0])
        self.assertEqual(attempts[0], 2)

    def test_window_not_ready_twice_reports_plain_chinese(self) -> None:
        def handler(path, req):
            if req["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": VALID_TOOLS}}
            return {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": "No ready app window supports app tools"}}

        client = ca.AppToolsClient(
            transport_factory=lambda p, t: FakeTransport(handler, p),
            opener=lambda url: None,
            sleep_fn=lambda s: None,
        )
        with patch.object(ca, "_list_pipes", return_value=["codex-app-tools-wake2"]):
            ca.reset_route_cache()
            with self.assertRaises(ca.AppToolsError) as caught:
                client.send_message_to_thread(TID, "测试", turn_id="turn-1")
            self.assertIn("窗口没准备好", str(caught.exception))
            self.assertTrue(caught.exception.not_submitted)

    def test_pipe_transport_skips_notifications_and_wrong_ids_until_match(self) -> None:
        import secrets
        import threading
        import win32file
        import win32pipe

        pipe_short = "codex-app-tools-idtest-" + secrets.token_hex(6)
        pipe_path = ca.PIPE_DIR + pipe_short
        ready = threading.Event()
        errors: list[Exception] = []

        def read_exact(handle, n: int) -> bytes:
            buf = bytearray()
            while len(buf) < n:
                _, chunk = win32file.ReadFile(handle, n - len(buf))
                if not chunk:
                    raise EOFError("pipe closed")
                buf.extend(chunk)
            return bytes(buf)

        def fake_server():
            handles = [
                win32pipe.CreateNamedPipe(
                    pipe_path, win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                    2, 65536, 65536, 0, None,
                )
                for _ in range(2)
            ]
            ready.set()
            try:
                for h in handles:  # 1: tools/list, 2: tools/call
                    try:
                        win32pipe.ConnectNamedPipe(h, None)
                        hdr = read_exact(h, 4)
                        size = struct.unpack("<I", hdr)[0]
                        req = json.loads(read_exact(h, size).decode("utf-8"))
                        rid = req["id"]
                        # 1) Server notification (no id)
                        win32file.WriteFile(h, ca.pack_frame({"jsonrpc": "2.0", "method": "notifications/ping", "params": {}}))
                        # 2) Response with a different id
                        win32file.WriteFile(h, ca.pack_frame({"jsonrpc": "2.0", "id": rid + 999, "result": {"wrong": True}}))
                        # 3) Server-initiated request with same id but no result/error
                        win32file.WriteFile(h, ca.pack_frame({"jsonrpc": "2.0", "id": rid, "method": "server/ping"}))
                        # 4) Matching response
                        if req["method"] == "tools/list":
                            reply = {"jsonrpc": "2.0", "id": rid, "result": {"tools": VALID_TOOLS}}
                        else:
                            reply = _ok_tool({"thread": {"id": TID, "status": {"type": "idle"}}}, rid)
                        win32file.WriteFile(h, ca.pack_frame(reply))
                        win32file.FlushFileBuffers(h)
                    finally:
                        try:
                            win32pipe.DisconnectNamedPipe(h)
                        except Exception:
                            pass
                        win32file.CloseHandle(h)
            except Exception as exc:
                errors.append(exc)

        th = threading.Thread(target=fake_server, daemon=True)
        th.start()
        ready.wait(timeout=2.0)

        client = ca.AppToolsClient()
        with patch.object(ca, "_list_pipes", return_value=[pipe_short]):
            ca.reset_route_cache()
            data = client.read_thread(TID, timeout=5.0)
        th.join(timeout=3.0)
        self.assertEqual(errors, [])
        self.assertEqual(data["thread"]["status"]["type"], "idle")

    def test_pipe_transport_times_out_when_id_never_matches(self) -> None:
        import secrets
        import threading
        import win32file
        import win32pipe

        pipe_short = "codex-app-tools-idtimeout-" + secrets.token_hex(6)
        pipe_path = ca.PIPE_DIR + pipe_short
        ready = threading.Event()
        stop_srv = threading.Event()

        def fake_server():
            h = win32pipe.CreateNamedPipe(
                pipe_path, win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                1, 65536, 65536, 0, None,
            )
            ready.set()
            try:
                win32pipe.ConnectNamedPipe(h, None)
                _, hdr = win32file.ReadFile(h, 4)
                size = struct.unpack("<I", hdr)[0]
                _, body = win32file.ReadFile(h, size)
                req = json.loads(body.decode("utf-8"))
                # Send only a notification and a mismatched id, then wait without answering req["id"]
                win32file.WriteFile(h, ca.pack_frame({"jsonrpc": "2.0", "method": "notifications/status"}))
                win32file.WriteFile(h, ca.pack_frame({"jsonrpc": "2.0", "id": req["id"] + 42, "result": {}}))
                win32file.FlushFileBuffers(h)
                stop_srv.wait(2.0)
            except Exception:
                pass
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(h)
                except Exception:
                    pass
                win32file.CloseHandle(h)

        th = threading.Thread(target=fake_server, daemon=True)
        th.start()
        ready.wait(timeout=2.0)
        try:
            transport = ca.WindowsPipeTransport(pipe_path, timeout=0.35)
            try:
                with self.assertRaises(ca.AppToolsError) as caught:
                    transport.request({"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}, timeout=0.35)
                self.assertEqual(caught.exception.code, "timeout")
                self.assertFalse(caught.exception.not_submitted)
                self.assertIn("结果未确认；不会自动重试", str(caught.exception))
            finally:
                transport.close()
        finally:
            stop_srv.set()
            th.join(timeout=3.0)


class AppToolsBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rollout = self.root / "rollout.jsonl"
        self.rollout.write_text(
            json.dumps({"timestamp": TS1, "type": "turn_context", "payload": {"turn_id": "turn-1", "model": "gpt-test", "effort": "medium"}}) + "\n"
            + json.dumps({"timestamp": TS1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}}) + "\n"
            + json.dumps({"timestamp": TS2, "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-1"}}) + "\n",
            encoding="utf-8",
        )
        self.item = {"app": "codex", "id": TID, "title": "测试对话", "cwd": str(self.root), "path": str(self.rollout)}

        self.pipe_status = {"type": "idle"}
        self.sent_calls: list[dict] = []

        def rpc_handler(path, req):
            if req["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": VALID_TOOLS}}
            params = req["params"]
            if params["tool"] == "read_thread":
                return _ok_tool({"thread": {"id": TID, "status": self.pipe_status}}, req["id"])
            if params["tool"] == "send_message_to_thread":
                self.sent_calls.append(params)
                return _ok_tool({"threadId": TID}, req["id"])
            raise AssertionError(f"unexpected tool {params['tool']}")

        self.legacy = codex_control.Bridge()
        self.legacy.data_root = self.root / "attachments"
        self.client = ca.AppToolsClient(transport_factory=lambda p, t: FakeTransport(rpc_handler, p))
        self.bridge = ca.AppToolsBridge(
            self.legacy, client=self.client, data_dir=self.root / "data", enable_background_drain=False
        )
        self.addCleanup(self.bridge.close)

        self.catalog = {"models": [{"id": "gpt-test", "name": "GPT Test", "efforts": ["low", "medium", "high"], "default_effort": "medium", "service_tiers": [], "images": True}]}
        for p in (
            patch.object(ca, "_list_pipes", return_value=["codex-app-tools-test"]),
            patch("chats.find", return_value=self.item),
            patch("codex_control.catalog", return_value=self.catalog),
        ):
            p.start()
            self.addCleanup(p.stop)
        ca.reset_route_cache()

    def test_idle_send_maps_model_thinking_and_upgrades_receipt_on_delegation_record(self) -> None:
        res = self.bridge.send({
            "id": TID,
            "request_id": "req-send-000001",
            "text": "你好，帮忙检查一下",
            "settings": {"model": "gpt-test", "effort": "high", "mode": "default"},
        })
        self.assertTrue(res["accepted"])
        self.assertEqual(res["delivery_state"], "accepted")
        self.assertEqual(res["text"], "已交给 Codex")
        self.assertEqual(len(self.sent_calls), 1)
        call = self.sent_calls[0]
        self.assertEqual(call["threadId"], TID)
        self.assertEqual(call["callerSource"], "codex")
        self.assertEqual(call["turnId"], "turn-1")
        self.assertEqual(call["arguments"]["model"], "gpt-test")
        self.assertEqual(call["arguments"]["thinking"], "high")
        self.assertEqual(call["arguments"]["prompt"], "你好，帮忙检查一下")

        # Idempotent replay returns same receipt without sending twice
        self.bridge.send({
            "id": TID,
            "request_id": "req-send-000001",
            "text": "你好，帮忙检查一下",
            "settings": {"model": "gpt-test", "effort": "high", "mode": "default"},
        })
        self.assertEqual(len(self.sent_calls), 1)

        # Once Codex writes the self-delegation into the rollout, receipt upgrades to 已送达 with message_id
        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": TS2,
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "FunctionCallOutput",
                        "id": "call-self-1",
                        "name": "send_message_to_thread",
                        "namespace": "codex_app",
                        "output": f"<codex_delegation><source_thread_id>{TID}</source_thread_id><input>你好，帮忙检查一下</input></codex_delegation>",
                    },
                },
            }, ensure_ascii=False) + "\n")
        rec = self.bridge.receipt(TID, "req-send-000001")
        self.assertEqual(rec["state"], "accepted")
        self.assertEqual(rec["result"]["text"], "已送达")
        self.assertEqual(rec["result"]["evidence"]["message_id"], "call-self-1")
        locs = self.bridge.delivery_locations(TID, ["req-send-000001"])
        self.assertEqual(locs["req-send-000001"]["message_id"], "call-self-1")

    def test_premature_idle_is_not_trusted_while_rollout_turn_is_still_open(self) -> None:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": now_iso, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-2"}}) + "\n")
        self.pipe_status = {"type": "idle"}
        st = self.bridge.status(TID, fresh=True)
        self.assertTrue(st["running"])
        self.assertEqual(st["active_turn_id"], "turn-2")

        # Once task_complete arrives, status becomes idle
        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": now_iso, "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-2"}}) + "\n")
        st2 = self.bridge.status(TID, fresh=True)
        self.assertFalse(st2["running"])
        self.assertEqual(st2["status"], "idle")

    def test_waiting_flags_and_system_error_status(self) -> None:
        self.pipe_status = {"type": "active", "activeFlags": ["waitingOnApproval"]}
        st = self.bridge.status(TID, fresh=True)
        self.assertTrue(st["running"])
        self.assertEqual(st["status"], "waiting")
        self.assertEqual(len(st["questions"]), 1)
        self.assertFalse(st["questions"][0]["answerable"])
        self.assertIn("批准", st["questions"][0]["question"])

        self.pipe_status = {"type": "active", "activeFlags": ["waitingOnUserInput"]}
        st_in = self.bridge.status(TID, fresh=True)
        self.assertIn("回答", st_in["questions"][0]["question"])

        self.pipe_status = {"type": "systemError"}
        st_err = self.bridge.status(TID, fresh=True)
        self.assertEqual(st_err["status"], "unknown")

    def test_steer_queue_persist_drain_promote_and_cancel(self) -> None:
        self.pipe_status = {"type": "active", "activeFlags": []}

        # Steer sends immediately
        steered = self.bridge.send({"id": TID, "request_id": "req-steer-00001", "text": "顺便看一下日志", "intent": "steer"})
        self.assertEqual(steered["intent"], "steer")
        self.assertEqual(len(self.sent_calls), 1)

        # Queue saves to disk and survives restart
        q1 = self.bridge.send({"id": TID, "request_id": "req-queue-00001", "text": "第一条排队", "intent": "queue"})
        q2 = self.bridge.send({"id": TID, "request_id": "req-queue-00002", "text": "第二条排队", "intent": "queue"})
        self.assertEqual(q1["delivery_state"], "queued")
        self.assertEqual(q2["delivery_state"], "queued")
        self.assertEqual(len(self.sent_calls), 1)

        # Recreate AppToolsBridge from same data_dir to verify persistence across restarts
        restarted = ca.AppToolsBridge(
            self.legacy, client=self.client, data_dir=self.root / "data", enable_background_drain=False
        )
        self.addCleanup(restarted.close)
        st = restarted.status(TID, fresh=True)
        self.assertEqual([q["id"] for q in st["queued"]], ["req-queue-00001", "req-queue-00002"])

        # Cancel second queued item
        cancelled = restarted.queue_action({"id": TID, "request_id": "req-cancel-0001", "message_id": "req-queue-00002", "action": "cancel"})
        self.assertEqual(cancelled["delivery_state"], "cancelled")
        self.assertEqual([q["id"] for q in restarted.queues.list_items(TID)], ["req-queue-00001"])

        # Promote first queued item -> sends immediately
        promoted = restarted.queue_action({"id": TID, "request_id": "req-promo-00001", "message_id": "req-queue-00001", "action": "promote"})
        self.assertEqual(promoted["delivery_state"], "accepted")
        self.assertEqual(len(self.sent_calls), 2)
        self.assertEqual(self.sent_calls[1]["arguments"]["prompt"], "第一条排队")

        # Enqueue another and verify polling drain fires once thread becomes idle
        restarted.send({"id": TID, "request_id": "req-queue-00003", "text": "空闲后自动发", "intent": "queue"})
        self.pipe_status = {"type": "idle"}
        st_idle = restarted.status(TID, fresh=True)
        self.assertTrue(st_idle["running"])
        self.assertEqual(len(self.sent_calls), 3)
        self.assertEqual(self.sent_calls[2]["arguments"]["prompt"], "空闲后自动发")
        self.assertEqual(restarted.queues.list_items(TID), [])

    def test_images_saved_to_codex_images_with_7_day_cleanup_and_skills_as_text(self) -> None:
        # Prepare a real tiny PNG uploaded through legacy.upload
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (255, 0, 0)).save(buf, format="PNG")
        uploaded = self.legacy.upload(TID, "sample.png", buf.getvalue(), "codex")

        # Create an expired (>7 days) image to verify cleanup
        stale_dir = self.bridge.images_root / TID
        stale_dir.mkdir(parents=True, exist_ok=True)
        stale_file = stale_dir / "old.png"
        stale_file.write_bytes(b"old")
        old_time = time.time() - 8 * 86400
        os.utime(stale_file, (old_time, old_time))

        # Prepare a fake skill in temporary home
        skill_file = self.root / ".codex" / "skills" / "demo-skill" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("---\nname: demo-skill\ndescription: 示例\n---\nBody\n", encoding="utf-8")
        refs = composer_references.References(SimpleNamespace(catalog=lambda: [self.item]), home=self.root)
        self.legacy.references = refs
        skill_row = refs.search("codex", TID, "skill")["items"][0]

        res = self.bridge.send({
            "id": TID,
            "request_id": "req-img-skill-01",
            "text": "请看图并用技能",
            "attachments": [uploaded["id"]],
            "references": [skill_row],
        })
        self.assertTrue(res["accepted"])
        prompt = self.sent_calls[-1]["arguments"]["prompt"]
        self.assertIn("请使用以下技能：demo-skill（说明文件：", prompt)
        self.assertIn("[附图] ", prompt)
        self.assertIn("codex-images", prompt)
        self.assertIn("请先用看图工具打开这张图片", prompt)
        self.assertFalse(stale_file.exists())
        saved_file = self.bridge.images_root / TID / f"{uploaded['id']}.png"
        self.assertTrue(saved_file.is_file())

    def test_unsupported_actions_return_plain_chinese_errors(self) -> None:
        with self.assertRaises(ca.AppToolsError) as compact_err:
            self.bridge.send({"id": TID, "request_id": "req-compact-001", "text": "/compact"})
        self.assertIn("/compact", str(compact_err.exception))
        self.assertTrue(compact_err.exception.not_submitted)

        with self.assertRaises(ca.AppToolsError) as stop_err:
            self.bridge.stop_turn({"id": TID, "turn_id": "turn-1"})
        self.assertIn("停止", str(stop_err.exception))

        with self.assertRaises(ca.AppToolsError) as ans_err:
            self.bridge.answer({"id": TID, "question_id": "q1", "answers": {}})
        self.assertIn("批准", str(ans_err.exception))

    def test_http_routes_report_codex_not_running_when_no_pipe_exists(self) -> None:
        server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": ["codex"], "voice": False},
            cfg={"token": "secret"},
            codex=self.legacy,
            log=SimpleNamespace(write=lambda t: None),
        )
        with patch.object(ca, "_list_pipes", return_value=[]):
            ca.reset_route_cache()
            code, state = _call_http(server, "GET", f"/api/codex/state?id={TID}")
            self.assertEqual(code, 200)
            self.assertFalse(state["available"])
            self.assertIn("Codex 没在运行", state["reason"])

            code, err = _call_http(server, "POST", "/api/codex/send", {"id": TID, "request_id": "req-none-00001", "text": "hello"})
            self.assertEqual(code, 409)
            self.assertIn("Codex 没在运行", err["error"])
            self.assertTrue(err["not_submitted"])


class ChatsDisplayStep1Tests(unittest.TestCase):
    def test_self_delegation_counts_as_own_message_and_other_chat_keeps_origin(self) -> None:
        def make_line(source_id: str, ident: str, text: str) -> bytes:
            return (json.dumps({
                "type": "event_msg",
                "timestamp": TS1,
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "FunctionCallOutput",
                        "id": ident,
                        "name": "send_message_to_thread",
                        "namespace": "codex_app",
                        "output": f"<codex_delegation><source_thread_id>{source_id}</source_thread_id><input>{text}</input></codex_delegation>",
                    },
                },
            }, ensure_ascii=False) + "\n").encode("utf-8")

        lines = [make_line(TID, "self-1", "手机发的测试"), make_line(OTHER_TID, "other-1", "别的对话发来的")]
        msgs, _ = chats.parse_codex(lines, thread_id=TID)
        self.assertEqual(len(msgs), 2)
        self.assertNotIn("origin", msgs[0])
        self.assertEqual(msgs[0]["text"], "手机发的测试")
        self.assertEqual(msgs[1]["origin"], "other_chat")
        self.assertEqual(msgs[1]["text"], "别的对话发来的")

        # Also works through chat_history.History and chats.summary
        with tempfile.TemporaryDirectory() as td:
            rollout = Path(td) / "rollout.jsonl"
            rollout.write_bytes(lines[0])
            item = {"app": "codex", "id": TID, "title": "自发测试", "cwd": td, "path": str(rollout)}
            with patch("chats.find", return_value=item):
                page = chat_history.History().conversation("codex", TID)
                self.assertNotIn("origin", page["messages"][0])
                summary = chats.summary(item)
                self.assertTrue(summary["preview"].startswith("你："), summary)

    def test_codex_images_attachment_line_extracted_into_images_list(self) -> None:
        img_id = "a" * 32
        img_path = rf"C:\FakeData\codex-images\{TID}\{img_id}.png"
        outside_path = r"C:\OtherFolder\pic.png"
        text_with_img = f"请看这张图\n\n[附图] {img_path}（请先用看图工具打开这张图片）"
        line = (json.dumps({
            "type": "event_msg",
            "timestamp": TS1,
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "FunctionCallOutput",
                    "id": "self-img-1",
                    "name": "send_message_to_thread",
                    "namespace": "codex_app",
                    "output": f"<codex_delegation><source_thread_id>{TID}</source_thread_id><input>{text_with_img}</input></codex_delegation>",
                },
            },
        }, ensure_ascii=False) + "\n").encode("utf-8")

        msgs, _ = chats.parse_codex([line], thread_id=TID)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["text"], "请看这张图")
        self.assertEqual(len(msgs[0]["images"]), 1)
        self.assertEqual(msgs[0]["images"][0]["id"], img_id)
        self.assertEqual(msgs[0]["images"][0]["url"], f"/api/codex/image?id={img_id}")

        # Outside codex-images folder is NOT stripped
        plain_text, plain_imgs = chats._extract_codex_images(f"看图\n[附图] {outside_path}（请打开）")
        self.assertEqual(plain_imgs, [])
        self.assertIn("[附图]", plain_text)


if __name__ == "__main__":
    unittest.main()
