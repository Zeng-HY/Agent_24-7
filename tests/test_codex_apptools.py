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


def _call_http_raw(server, method: str, path: str, body=None, protocol: int = 2):
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
    handler._send = lambda code, data, ctype, extra=None: sent.append((code, data, ctype, extra))
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    return sent[0]


def _call_http(server, method: str, path: str, body=None, protocol: int = 2):
    code, data, _ctype, _extra = _call_http_raw(server, method, path, body=body, protocol=protocol)
    return code, json.loads(data.decode("utf-8"))


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
            self.assertEqual(m_legacy["capabilities"]["settings"], ["model", "effort", "mode"])
            self.assertEqual(m_legacy["sources"]["control"], "ipc")
            now_legacy = agent.capabilities_now(None, TID)
            self.assertEqual(now_legacy["capabilities"], m_legacy["capabilities"])
            self.assertEqual(now_legacy["notes"], {})
            self.assertEqual([c["name"] for c in composer_commands.catalog("codex", TID)["items"]], ["compact"])

            # Mid-run switch to apptools on the SAME agent instance: manifest stays fixed, capabilities_now follows route
            pipes[0] = ["codex-app-tools-1111"]
            ca.reset_route_cache()
            m_new = agent.manifest()
            self.assertEqual(m_new, m_legacy)
            now_new = agent.capabilities_now(None, TID)
            self.assertFalse(now_new["capabilities"]["stop"])
            self.assertFalse(now_new["capabilities"]["approve"])
            self.assertFalse(now_new["capabilities"]["answer"])
            self.assertFalse(now_new["capabilities"]["slash_commands"])
            self.assertTrue(now_new["capabilities"]["queue"])
            self.assertTrue(now_new["capabilities"]["steer"])
            self.assertTrue(now_new["capabilities"]["attachments"])
            self.assertEqual(now_new["capabilities"]["settings"], ["model", "effort"])
            self.assertEqual(now_new["capabilities"]["send_modes"], ["send", "steer", "queue"])
            self.assertIn("slash_commands", now_new["notes"])
            self.assertIn("mode", now_new["notes"])
            self.assertEqual(composer_commands.catalog("codex", TID)["items"], [])

            # Mid-run switch to none (Codex closed): manifest stays fixed, capabilities_now narrows
            pipes[0] = []
            ca.reset_route_cache()
            m_none = agent.manifest()
            self.assertEqual(m_none, m_legacy)
            now_none = agent.capabilities_now(None, TID)
            self.assertFalse(now_none["capabilities"]["queue"])
            self.assertFalse(now_none["capabilities"]["steer"])
            self.assertEqual(now_none["capabilities"]["settings"], [])
            self.assertEqual(now_none["capabilities"]["send_modes"], [])
            self.assertEqual(now_none["notes"]["send"], ca.NOT_RUNNING_REASON)


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
        self.tool_calls: list[str] = []

        def rpc_handler(path, req):
            if req["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": VALID_TOOLS}}
            params = req["params"]
            self.tool_calls.append(params["tool"])
            if params["tool"] == "read_thread":
                return _ok_tool({"thread": {"id": TID, "status": self.pipe_status}}, req["id"])
            if params["tool"] == "send_message_to_thread":
                self.sent_calls.append(params)
                return _ok_tool({"threadId": TID}, req["id"])
            raise AssertionError(f"unexpected tool {params['tool']}")

        self.legacy = codex_control.Bridge()
        self.legacy.data_root = self.root / "attachments"
        self.data_dir = self.root / "data"
        ca.set_default_data_dir_override(self.data_dir)
        self.addCleanup(ca.set_default_data_dir_override, None)
        self.client = ca.AppToolsClient(transport_factory=lambda p, t: FakeTransport(rpc_handler, p))
        self.bridge = ca.AppToolsBridge(
            self.legacy, client=self.client, data_dir=self.data_dir,
            enable_background_drain=False, enable_background_watch=False,
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
            self.legacy, client=self.client, data_dir=self.root / "data",
            enable_background_drain=False, enable_background_watch=False,
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

    def test_protocol_one_and_two_capabilities_now_routes_commands_and_untrusted_actions(self) -> None:
        import codex_hooks as ch

        server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": ["codex"], "voice": False},
            cfg={"token": "secret"},
            codex=self.legacy,
            references=None,
            deepseek=None,
            log=SimpleNamespace(write=lambda t: None),
        )
        self.legacy._apptools_bridge = self.bridge
        manifest_caps = registry.get("codex").manifest()["capabilities"]

        def assert_never_wider(now_caps: dict) -> None:
            self.assertEqual(set(now_caps.keys()), set(manifest_caps.keys()))
            for k, mval in manifest_caps.items():
                nval = now_caps[k]
                self.assertIs(type(nval), type(mval), k)
                if isinstance(mval, bool) and not mval:
                    self.assertFalse(nval, k)
                elif isinstance(mval, list):
                    self.assertTrue(set(nval) <= set(mval), (k, nval, mval))

        # 1) Legacy route: protocol 1 omits capabilities_now; protocol 2 includes full legacy capabilities & empty notes
        with patch.object(ca, "_list_pipes", return_value=["codex-ipc"]), \
             patch.object(self.legacy, "status", return_value={"available": True, "running": False, "status": "idle"}):
            ca.reset_route_cache()
            code1, st1 = _call_http(server, "GET", f"/api/codex/state?id={TID}", protocol=1)
            self.assertEqual(code1, 200)
            self.assertNotIn("capabilities_now", st1)
            self.assertNotIn("capability_notes", st1)
            code1u, st1u = _call_http(server, "GET", f"/api/agents/codex/state?id={TID}", protocol=1)
            self.assertEqual(code1u, 200)
            self.assertEqual(st1u, st1)

            code2, st2 = _call_http(server, "GET", f"/api/agents/codex/state?id={TID}", protocol=2)
            self.assertEqual(code2, 200)
            self.assertEqual(st2["capabilities_now"], manifest_caps)
            self.assertEqual(st2["capability_notes"], {})
            assert_never_wider(st2["capabilities_now"])

            code_cmd, cmd_body = _call_http(server, "GET", f"/api/agents/codex/commands?id={TID}", protocol=2)
            self.assertEqual(code_cmd, 200)
            self.assertEqual([c["name"] for c in cmd_body["items"]], ["compact"])

        # 2) Apptools route across not_installed, pending_trust, enabled
        fake_home = self.root / "fake_codex_home"
        fake_home.mkdir()
        ch.set_default_codex_home_override(fake_home)
        ch.reset_trust_cache()
        with patch.object(ca, "_list_pipes", return_value=["codex-app-tools-caps"]):
            ca.reset_route_cache()
            # 2a) not_installed
            code, st_ni = _call_http(server, "GET", f"/api/agents/codex/state?id={TID}", protocol=2)
            self.assertEqual(code, 200)
            assert_never_wider(st_ni["capabilities_now"])
            self.assertFalse(st_ni["capabilities_now"]["stop"])
            self.assertFalse(st_ni["capabilities_now"]["approve"])
            self.assertFalse(st_ni["capabilities_now"]["answer"])
            self.assertFalse(st_ni["capabilities_now"]["slash_commands"])
            self.assertEqual(st_ni["capabilities_now"]["settings"], ["model", "effort"])
            self.assertIn("还没装上", st_ni["capability_notes"]["stop"])
            self.assertEqual(st_ni["capability_notes"]["approve"], st_ni["capability_notes"]["stop"])
            self.assertEqual(st_ni["capability_notes"]["answer"], st_ni["capability_notes"]["stop"])
            self.assertEqual(st_ni["capability_notes"]["slash_commands"], "新版 Codex 不能从手机压缩对话（/compact）")
            self.assertEqual(st_ni["capability_notes"]["mode"], "新版 Codex 从手机发的消息跟着电脑上当前的模式走，手机上不能切换")

            # Protocol 1 on apptools still omits both fields
            code_p1, st_p1 = _call_http(server, "GET", f"/api/codex/state?id={TID}", protocol=1)
            self.assertEqual(code_p1, 200)
            self.assertNotIn("capabilities_now", st_p1)
            self.assertNotIn("capability_notes", st_p1)

            # http_commands returns 400 unsupported on apptools
            code_cmd, cmd_err = _call_http(server, "GET", f"/api/agents/codex/commands?id={TID}", protocol=2)
            self.assertEqual(code_cmd, 400)
            self.assertEqual(cmd_err, {"error": "这个助手还没有斜杠命令", "code": "unsupported"})

            # Untrusted stop & answer over HTTP return 409 with Chinese reason (never 500)
            for path, payload in (
                ("/api/codex/stop", {"id": TID, "turn_id": "turn-1"}),
                ("/api/agents/codex/stop", {"id": TID, "turn_id": "turn-1"}),
                ("/api/codex/answer", {"id": TID, "question_id": "q1", "answers": {}}),
                ("/api/agents/codex/answer", {"id": TID, "question_id": "q1", "answers": {}}),
            ):
                code_act, err_act = _call_http(server, "POST", path, payload, protocol=2)
                self.assertEqual(code_act, 409, (path, err_act))
                self.assertEqual(err_act["code"], "hooks_not_trusted")
                self.assertTrue(err_act["not_submitted"])

            # 2b) pending_trust
            ch.install_hooks(self.root / "TeleplyCodexHook.exe", codex_home=fake_home, log=lambda _t: None)
            code, st_pt = _call_http(server, "GET", f"/api/agents/codex/state?id={TID}", protocol=2)
            self.assertEqual(code, 200)
            assert_never_wider(st_pt["capabilities_now"])
            self.assertFalse(st_pt["capabilities_now"]["stop"])
            self.assertEqual(st_pt["capability_notes"]["stop"], ch.TRUST_HINT)
            self.assertEqual(st_pt["capability_notes"]["approve"], ch.TRUST_HINT)
            self.assertEqual(st_pt["capability_notes"]["answer"], ch.TRUST_HINT)

            # 2c) enabled (trusted)
            hp = fake_home / "hooks.json"
            (fake_home / "config.toml").write_text(
                f"[hooks.state.'{hp}:pre_tool_use:0:0']\ntrusted_hash = \"h1\"\n"
                f"[hooks.state.'{hp}:permission_request:0:0']\ntrusted_hash = \"h2\"\n"
                f"[hooks.state.'{hp}:stop:0:0']\ntrusted_hash = \"h3\"\n",
                encoding="utf-8",
            )
            ch.reset_trust_cache()
            code, st_en = _call_http(server, "GET", f"/api/agents/codex/state?id={TID}", protocol=2)
            self.assertEqual(code, 200)
            assert_never_wider(st_en["capabilities_now"])
            self.assertTrue(st_en["capabilities_now"]["stop"])
            self.assertTrue(st_en["capabilities_now"]["approve"])
            self.assertTrue(st_en["capabilities_now"]["answer"])
            self.assertFalse(st_en["capabilities_now"]["slash_commands"])
            self.assertEqual(st_en["capabilities_now"]["settings"], ["model", "effort"])
            self.assertEqual(
                set(st_en["capability_notes"].keys()),
                {"slash_commands", "mode"},
            )

        # 3) None route (Codex not running)
        with patch.object(ca, "_list_pipes", return_value=[]):
            ca.reset_route_cache()
            code, st_no = _call_http(server, "GET", f"/api/agents/codex/state?id={TID}", protocol=2)
            self.assertEqual(code, 200)
            assert_never_wider(st_no["capabilities_now"])
            self.assertEqual(st_no["capabilities_now"]["send_modes"], [])
            self.assertEqual(st_no["capabilities_now"]["settings"], [])
            self.assertFalse(st_no["capabilities_now"]["attachments"])
            for k in ("send", "steer", "queue", "stop", "approve", "answer", "attachments"):
                self.assertEqual(st_no["capability_notes"][k], ca.NOT_RUNNING_REASON)
            code_cmd, _ = _call_http(server, "GET", f"/api/agents/codex/commands?id={TID}", protocol=2)
            self.assertEqual(code_cmd, 400)

    def test_plan_mode_note_on_apptools_send_and_new_chat_only(self) -> None:
        from unittest.mock import Mock
        import new_conversations

        expected_text = "已交给 Codex。新版 Codex 从手机发的消息跟着电脑上当前的模式走，这次选的「计划模式」没有生效。"

        # 1) Normal send on apptools with mode="plan" carries explanation
        res_plan = self.bridge.send({
            "id": TID,
            "request_id": "req-plan-00001",
            "text": "请先出计划",
            "settings": {"model": "gpt-test", "effort": "high", "mode": "plan"},
        })
        self.assertTrue(res_plan["accepted"])
        self.assertEqual(res_plan["text"], expected_text)

        # 2) Normal send on apptools with mode="default" does NOT carry explanation
        res_default = self.bridge.send({
            "id": TID,
            "request_id": "req-plan-00002",
            "text": "普通执行消息",
            "settings": {"model": "gpt-test", "effort": "high", "mode": "default"},
        })
        self.assertTrue(res_default["accepted"])
        self.assertEqual(res_default["text"], "已交给 Codex")

        # 3) Queued send while running with mode="plan" also notes it
        self.pipe_status = {"type": "active", "activeFlags": []}
        res_queued = self.bridge.send({
            "id": TID,
            "request_id": "req-plan-00003",
            "text": "排队计划",
            "intent": "queue",
            "settings": {"model": "gpt-test", "effort": "high", "mode": "plan"},
        })
        self.assertEqual(res_queued["delivery_state"], "queued")
        self.assertIn(ca.PLAN_MODE_IGNORED_NOTE, res_queued["text"])
        self.pipe_status = {"type": "idle"}

        # 4) New conversation first message on apptools: mode="plan" carries explanation, default does not
        proj = self.root / "new_proj"
        proj.mkdir()
        history = SimpleNamespace(catalog=lambda: [{"app": "codex", "id": TID, "cwd": str(proj), "folder": "new_proj", "updated": 1}])
        refs = composer_references.References(history, home=self.root)
        self.legacy._apptools_bridge = self.bridge
        svc = new_conversations.NewConversations(history, refs, self.legacy, Mock(), root=self.root / "new_db")

        def run_new_case(mode: str, rid_tag: str) -> dict:
            rid = svc.create_draft()["request_id"]
            body = {
                "request_id": rid,
                "app": "codex",
                "folder": str(proj),
                "text": f"新建消息 {rid_tag}",
                "attachments": [],
                "references": [],
                "settings": {"model": "gpt-test", "effort": "high", "mode": mode},
            }
            with patch("new_conversations.codex_control.catalog", return_value=self.catalog), \
                 patch("new_conversations.threading.Thread"):
                svc.submit(body)
            with patch("new_conversations.chats.require_send_desktop"), \
                 patch("new_conversations.os.startfile"), \
                 patch.object(svc, "_empty_codex", side_effect=lambda _r, d: d.update(id=TID, title="新建测试", default_model="gpt-test", default_effort="medium")), \
                 patch("new_conversations.codex_control.catalog", return_value=self.catalog):
                svc._run(rid)
            return svc.status(rid)

        st_new_plan = run_new_case("plan", "plan")
        self.assertEqual(st_new_plan["state"], "accepted")
        self.assertEqual(st_new_plan["message"], expected_text)

        st_new_default = run_new_case("default", "default")
        self.assertEqual(st_new_default["state"], "accepted")
        self.assertEqual(st_new_default["message"], "首条消息已送达")

        # 5) Legacy route new chat does NOT add the apptools plan-mode explanation
        with patch.object(ca, "_list_pipes", return_value=["codex-ipc"]):
            ca.reset_route_cache()
            rid_legacy = svc.create_draft()["request_id"]
            with patch("new_conversations.codex_control.catalog", return_value=self.catalog), \
                 patch("new_conversations.threading.Thread"):
                svc.submit({
                    "request_id": rid_legacy,
                    "app": "codex",
                    "folder": str(proj),
                    "text": "老路线新建计划",
                    "attachments": [],
                    "references": [],
                    "settings": {"model": "gpt-test", "effort": "high", "mode": "plan"},
                })
            fake_pipe = SimpleNamespace(snapshot=lambda tid, _t, timing=None: ("owner", {"id": tid}))
            with patch("new_conversations.chats.require_send_desktop"), \
                 patch("new_conversations.os.startfile"), \
                 patch.object(svc, "_empty_codex", side_effect=lambda _r, d: d.update(id=TID, title="老路线新建", default_model="gpt-test", default_effort="medium")), \
                 patch.object(self.legacy, "_pipe", return_value=fake_pipe), \
                 patch("new_conversations.codex_control.selected_settings", return_value={"model": "gpt-test", "effort": "high", "mode": "default", "service_tier": None}), \
                 patch("new_conversations.codex_control.catalog", return_value=self.catalog), \
                 patch.object(self.legacy, "send", return_value={"accepted": True, "text": "已交给 Codex"}):
                svc._run(rid_legacy)
            st_legacy = svc.status(rid_legacy)
            self.assertEqual(st_legacy["state"], "accepted")
            self.assertEqual(st_legacy["message"], "首条消息已送达")
            self.assertNotIn(ca.PLAN_MODE_IGNORED_NOTE, st_legacy["message"])


class TimingAndStatusCacheTests(AppToolsBridgeTests):
    """11-27 S4: one numbers-only timing line per request, and no second read_thread when a fresh
    pipe reading and an unchanged rollout file already answer "is it running"."""

    def setUp(self) -> None:
        super().setUp()
        self.logs: list[str] = []
        self.legacy.log = self.logs.append

    def _send(self, rid: str, text: str = "你好", intent: str | None = None) -> dict:
        body = {"id": TID, "request_id": rid, "text": text}
        if intent:
            body["intent"] = intent
        return self.bridge.send(body)

    def _timing_lines(self) -> list[str]:
        return [line for line in self.logs if line.startswith("codex timing request=")]

    def _read_calls(self) -> int:
        return self.tool_calls.count("read_thread")

    def test_timing_line_has_the_agreed_shape_and_a_truncated_request_id(self) -> None:
        self._send("req-send-000001")
        lines = self._timing_lines()
        self.assertEqual(len(lines), 1)
        self.assertRegex(
            lines[0],
            r"^codex timing request=req-send read_ms=\d+ send_ms=\d+ other_ms=\d+ total_ms=\d+$",
        )

    def test_recent_status_reading_and_unchanged_file_skip_the_send_read(self) -> None:
        self.assertTrue(self.bridge.status(TID, fresh=True)["running"] is False)
        before = self._read_calls()
        self._send("req-send-skip01")
        self.assertEqual(self._read_calls(), before)  # reused the status read
        self.assertEqual(len(self.sent_calls), 1)

    def test_rollout_change_after_the_cached_reading_asks_the_pipe_again(self) -> None:
        self.bridge.status(TID, fresh=True)
        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": TS2, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-2"}}) + "\n")
        before = self._read_calls()
        self._send("req-send-ask001")
        self.assertEqual(self._read_calls(), before + 1)

    def test_no_recent_status_reading_asks_the_pipe(self) -> None:
        self._send("req-send-ask002")
        self.assertEqual(self._read_calls(), 1)

    def test_queue_decision_never_trusts_a_cached_not_running_reading(self) -> None:
        self.bridge.status(TID, fresh=True)  # caches running=False
        before = self._read_calls()
        res = self._send("req-queue-safe1", intent="queue")
        self.assertEqual(self._read_calls(), before + 1)
        self.assertEqual(res["delivery_state"], "accepted")  # the pipe still said idle, so it sent

    def test_queue_decision_may_reuse_a_cached_running_reading(self) -> None:
        self.pipe_status = {"type": "active", "activeFlags": []}
        self.bridge.status(TID, fresh=True)
        before = self._read_calls()
        res = self._send("req-queue-safe2", intent="queue")
        self.assertEqual(self._read_calls(), before)
        self.assertEqual(res["delivery_state"], "queued")
        self.assertEqual(len(self.sent_calls), 0)

    def test_expired_status_reading_asks_the_pipe(self) -> None:
        self.bridge.status(TID, fresh=True)
        cached = self.bridge._status_cache[TID]
        self.bridge._status_cache[TID] = (cached[0] - ca.SEND_STATUS_CACHE_TTL - 1.0, cached[1], cached[2])
        before = self._read_calls()
        self._send("req-send-old01")
        self.assertEqual(self._read_calls(), before + 1)

    def test_queue_promote_and_drain_each_write_one_timing_line(self) -> None:
        self.pipe_status = {"type": "active", "activeFlags": []}
        self._send("req-q-timing1", intent="queue")
        self.logs.clear()
        self.bridge.queue_action({
            "id": TID, "request_id": "req-act-00001", "message_id": "req-q-timing1", "action": "promote",
        })
        promote_lines = self._timing_lines()
        self.assertEqual(len(promote_lines), 1)
        self.assertIn("request=req-act-", promote_lines[0])

        self.pipe_status = {"type": "active", "activeFlags": []}
        self._send("req-q-drain1", intent="queue")
        self.logs.clear()
        self.pipe_status = {"type": "idle"}
        self.assertTrue(self.bridge.drain_if_idle(TID))
        drain_lines = self._timing_lines()
        self.assertEqual(len(drain_lines), 1)
        self.assertIn("request=req-q-dr", drain_lines[0])


class DeliveryWatcherTests(AppToolsBridgeTests):
    """11-27 S5: an accepted send is marked 已送达 on the next rollout change, without anyone reading state."""

    def _raw_delivery(self, rid: str) -> tuple[str, dict]:
        with self.legacy._db() as con:
            row = con.execute(
                "SELECT state,result FROM deliveries WHERE id=? AND thread=?", (rid, TID)
            ).fetchone()
        return row[0], json.loads(row[1] or "{}")

    def _append_delegation(self, message_id: str, text: str) -> None:
        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": TS2,
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "FunctionCallOutput",
                        "id": message_id,
                        "name": "send_message_to_thread",
                        "namespace": "codex_app",
                        "output": f"<codex_delegation><source_thread_id>{TID}</source_thread_id><input>{text}</input></codex_delegation>",
                    },
                },
            }, ensure_ascii=False) + "\n")

    def test_next_rollout_change_marks_delivered_without_reading_state(self) -> None:
        rid = "req-watch-0001"
        res = self.bridge.send({"id": TID, "request_id": rid, "text": "插话一下", "intent": "steer"})
        self.assertEqual(res["delivery_state"], "accepted")
        self.assertIn(TID, self.bridge._pending_deliveries)

        self._append_delegation("call-watch-1", "插话一下")
        self.bridge._reconcile_pending_once()

        state, result = self._raw_delivery(rid)
        self.assertEqual(state, "accepted")
        self.assertEqual(result["text"], "已送达")
        self.assertEqual(result["evidence"]["message_id"], "call-watch-1")
        self.assertNotIn(TID, self.bridge._pending_deliveries)

    def test_no_pending_sends_means_nothing_is_scanned(self) -> None:
        self.assertEqual(self.bridge._reconcile_pending_once(), 0)
        self.assertIsNone(self.bridge._reconcile_thread)
        with patch.object(self.bridge, "reconcile_deliveries", side_effect=AssertionError("must not scan")):
            self.assertEqual(self.bridge._reconcile_pending_once(), 0)

    def test_queued_send_alone_is_not_watched_until_it_is_handed_over(self) -> None:
        self.pipe_status = {"type": "active", "activeFlags": []}
        res = self.bridge.send({"id": TID, "request_id": "req-watch-q001", "text": "排队", "intent": "queue"})
        self.assertEqual(res["delivery_state"], "queued")
        self.assertEqual(self.bridge._pending_deliveries, {})

        popped = self.bridge.pop_queued_for_stop_hook(TID)
        self.assertIsNotNone(popped)
        self.assertIn(TID, self.bridge._pending_deliveries)
        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": TS2,
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "UserMessage",
                        "id": "um-watch-q001",
                        "content": [{"type": "text", "text": f'<hook_prompt id="hp1">{popped["prompt"]}</hook_prompt>'}],
                    },
                },
            }, ensure_ascii=False) + "\n")
        self.bridge._reconcile_pending_once()
        _state, result = self._raw_delivery("req-watch-q001")
        self.assertEqual(result["evidence"]["message_id"], "um-watch-q001")
        self.assertNotIn(TID, self.bridge._pending_deliveries)

    def test_fifteen_minutes_without_evidence_stops_the_automatic_scan(self) -> None:
        rid = "req-watch-1501"
        self.bridge.send({"id": TID, "request_id": rid, "text": "插话超时", "intent": "steer"})
        entry = self.bridge._pending_deliveries[TID]
        entry["deadline"] = self.bridge._clock() - 1.0

        self._append_delegation("call-watch-late", "插话超时")
        self.bridge._reconcile_pending_once()

        _state, result = self._raw_delivery(rid)
        self.assertNotIn("message_id", result.get("evidence") or {})
        self.assertNotIn(TID, self.bridge._pending_deliveries)

    def test_the_shared_watcher_marks_it_on_its_own(self) -> None:
        watched = ca.AppToolsBridge(
            self.legacy, client=self.client, data_dir=self.data_dir, enable_background_drain=False,
        )
        self.addCleanup(watched.close)
        rid = "req-watch-auto1"
        watched.send({"id": TID, "request_id": rid, "text": "自动标上", "intent": "steer"})
        self._append_delegation("call-auto-1", "自动标上")
        deadline = time.monotonic() + 3.0
        result: dict = {}
        while time.monotonic() < deadline:
            _state, result = self._raw_delivery(rid)
            if (result.get("evidence") or {}).get("message_id") == "call-auto-1":
                break
            time.sleep(0.05)
        self.assertEqual((result.get("evidence") or {}).get("message_id"), "call-auto-1")
        self.assertNotIn(TID, watched._pending_deliveries)

    def test_a_rollout_that_changes_again_is_scanned_again(self) -> None:
        rid = "req-watch-2001"
        self.bridge.send({"id": TID, "request_id": rid, "text": "插话两次", "intent": "steer"})
        self._append_delegation("call-watch-unrelated", "别的消息")
        self.bridge._reconcile_pending_once()
        self.assertIn(TID, self.bridge._pending_deliveries)
        self._append_delegation("call-watch-2", "插话两次")
        self.bridge._reconcile_pending_once()
        _state, result = self._raw_delivery(rid)
        self.assertEqual(result["evidence"]["message_id"], "call-watch-2")


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

        # Compressed .jpg path inside codex-images also maps back to image id and /api/codex/image?id=
        jpg_path = rf"C:\FakeData\codex-images\{TID}\{img_id}.jpg"
        cleaned_jpg, jpg_imgs = chats._extract_codex_images(f"看压缩图\n\n[附图] {jpg_path}（请先用看图工具打开这张图片）")
        self.assertEqual(cleaned_jpg, "看压缩图")
        self.assertEqual(len(jpg_imgs), 1)
        self.assertEqual(jpg_imgs[0]["id"], img_id)
        self.assertEqual(jpg_imgs[0]["url"], f"/api/codex/image?id={img_id}")
        self.assertEqual(jpg_imgs[0]["thumbnail"], f"/api/codex/image?thumb=1&id={img_id}")


class ImageCompressionAndPairingTests(AppToolsBridgeTests):
    """Tests for dev.48: new-route image compression and message source_id <-> request_id pairing."""

    @staticmethod
    def _make_textured_rgb(width: int, height: int, seed: int = 42):
        import random
        from PIL import Image

        rng = random.Random(seed)
        # Build a detailed 256x256 tile with gradients + fine noise, then tile & blend for fast multi-MP generation
        tw, th = min(width, 256), min(height, 256)
        raw = bytearray(tw * th * 3)
        idx = 0
        for y in range(th):
            for x in range(tw):
                raw[idx] = (x * 3 + y + rng.randint(0, 48)) & 255
                raw[idx + 1] = (y * 2 + rng.randint(0, 64)) & 255
                raw[idx + 2] = ((x ^ y) + rng.randint(0, 56)) & 255
                idx += 3
        tile = Image.frombytes("RGB", (tw, th), bytes(raw))
        img = Image.new("RGB", (width, height))
        for oy in range(0, height, th):
            for ox in range(0, width, tw):
                img.paste(tile, (ox, oy))
        return img

    @staticmethod
    def _make_tall_screenshot_png(width: int, height: int):
        from PIL import Image, ImageDraw

        # Realistic long screenshot with alternating cards, stripes, and gradient header
        img = Image.new("RGB", (width, height), (245, 247, 250))
        draw = ImageDraw.Draw(img)
        for y in range(0, height, 120):
            tone = (y // 120) % 5
            bg = [(255, 255, 255), (238, 244, 255), (246, 252, 244), (255, 248, 236), (248, 244, 255)][tone]
            draw.rectangle([80, y + 12, width - 80, min(height - 1, y + 108)], fill=bg, outline=(190, 200, 215), width=3)
            for bar in range(3):
                by = y + 28 + bar * 22
                if by + 10 < height:
                    draw.rectangle([120, by, min(width - 140, 600 + ((y + bar * 173) % (width - 800))), by + 10], fill=(40 + tone * 20, 60, 90))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _make_large_transparent_png(width: int, height: int):
        import random
        from PIL import Image

        rng = random.Random(7)
        tw, th = 256, 256
        raw = bytearray(tw * th * 4)
        idx = 0
        for y in range(th):
            for x in range(tw):
                raw[idx] = (x * 2 + rng.randint(0, 40)) & 255
                raw[idx + 1] = (y * 2 + rng.randint(0, 40)) & 255
                raw[idx + 2] = ((x + y) + rng.randint(0, 40)) & 255
                raw[idx + 3] = 0 if (x + y) % 11 == 0 else (180 if (x % 17 < 4) else 255)
                idx += 4
        tile = Image.frombytes("RGBA", (tw, th), bytes(raw))
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for oy in range(0, height, th):
            for ox in range(0, width, tw):
                img.paste(tile, (ox, oy))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_store_codex_image_compresses_large_images_preserves_small_and_serves_http(self) -> None:
        from PIL import Image

        server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": ["codex"], "voice": False},
            cfg={"token": "secret"},
            codex=self.legacy,
            log=SimpleNamespace(write=lambda t: None),
        )

        # 1) 4000x3000 large photo (uploaded as JPEG -> stored as large PNG in legacy.data_root)
        photo_img = self._make_textured_rgb(4000, 3000, seed=11)
        photo_buf = io.BytesIO()
        photo_img.save(photo_buf, format="JPEG", quality=92)
        up_photo = self.legacy.upload(TID, "big-photo.jpg", photo_buf.getvalue(), "codex")
        meta_photo = self.legacy.attachment(up_photo["id"], TID)
        saved_photo = ca.store_codex_image(self.bridge.images_root, TID, meta_photo)
        self.assertEqual(saved_photo.stem, up_photo["id"])
        self.assertEqual(saved_photo.suffix, ".jpg")
        self.assertLessEqual(saved_photo.stat().st_size, ca.CODEX_IMAGE_MAX_BYTES)
        with Image.open(saved_photo) as out_im:
            self.assertEqual(out_im.format, "JPEG")
            self.assertLessEqual(max(out_im.width, out_im.height), 1600)

        # 2) 3000x6000 tall PNG screenshot
        tall_bytes = self._make_tall_screenshot_png(3000, 6000)
        up_tall = self.legacy.upload(TID, "tall-screen.png", tall_bytes, "codex")
        meta_tall = self.legacy.attachment(up_tall["id"], TID)
        saved_tall = ca.store_codex_image(self.bridge.images_root, TID, meta_tall)
        self.assertEqual(saved_tall.stem, up_tall["id"])
        self.assertEqual(saved_tall.suffix, ".jpg")
        self.assertLessEqual(saved_tall.stat().st_size, ca.CODEX_IMAGE_MAX_BYTES)
        with Image.open(saved_tall) as out_im:
            self.assertLessEqual(max(out_im.width, out_im.height), 1600)
            self.assertGreater(out_im.height, out_im.width)

        # 3) Large transparent PNG (2400x1800 RGBA with alpha) -> stays PNG, keeps alpha, <=1600 & <=400 KB
        alpha_bytes = self._make_large_transparent_png(2400, 1800)
        up_alpha = self.legacy.upload(TID, "alpha-big.png", alpha_bytes, "codex")
        meta_alpha = self.legacy.attachment(up_alpha["id"], TID)
        saved_alpha = ca.store_codex_image(self.bridge.images_root, TID, meta_alpha)
        self.assertEqual(saved_alpha.stem, up_alpha["id"])
        self.assertEqual(saved_alpha.suffix, ".png")
        self.assertLessEqual(saved_alpha.stat().st_size, ca.CODEX_IMAGE_MAX_BYTES)
        with Image.open(saved_alpha) as out_im:
            self.assertEqual(out_im.format, "PNG")
            self.assertLessEqual(max(out_im.width, out_im.height), 1600)
            lo, _ = out_im.convert("RGBA").getchannel("A").getextrema()
            self.assertLess(lo, 255)

        # 4) 200x200 small image -> copied verbatim without re-encoding
        small_buf = io.BytesIO()
        Image.new("RGB", (200, 200), (40, 120, 200)).save(small_buf, format="PNG")
        up_small = self.legacy.upload(TID, "small.png", small_buf.getvalue(), "codex")
        meta_small = self.legacy.attachment(up_small["id"], TID)
        saved_small = ca.store_codex_image(self.bridge.images_root, TID, meta_small)
        self.assertEqual(saved_small.stem, up_small["id"])
        self.assertEqual(saved_small.suffix, ".png")
        self.assertEqual(saved_small.read_bytes(), Path(meta_small["path"]).read_bytes())

        # 5) EXIF orientation=6 (90 deg rotated) is transposed upright when compressing
        rot_src = self.root / "rotated.jpg"
        rot_img = self._make_textured_rgb(2000, 1000, seed=99)
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 CW
        rot_img.save(rot_src, format="JPEG", quality=90, exif=exif.tobytes())
        saved_rot = ca.store_codex_image(self.bridge.images_root, TID, {"id": "b" * 32, "path": str(rot_src)})
        self.assertLessEqual(saved_rot.stat().st_size, ca.CODEX_IMAGE_MAX_BYTES)
        with Image.open(saved_rot) as out_im:
            self.assertGreater(out_im.height, out_im.width)
            self.assertLessEqual(max(out_im.width, out_im.height), 1600)

        # 6) All uploaded attachments remain fetchable via /api/codex/image?id= and ?thumb=1&id=
        for up in (up_photo, up_tall, up_alpha, up_small):
            code, raw_full, ctype, _ = _call_http_raw(server, "GET", f"/api/codex/image?id={up['id']}")
            self.assertEqual(code, 200)
            self.assertTrue(ctype.startswith("image/"))
            self.assertGreater(len(raw_full), 100)
            code_t, raw_thumb, ctype_t, _ = _call_http_raw(server, "GET", f"/api/codex/image?thumb=1&id={up['id']}")
            self.assertEqual(code_t, 200)
            self.assertTrue(ctype_t.startswith("image/"))
            self.assertGreater(len(raw_thumb), 100)

    def test_direct_image_send_persists_message_and_request_id_pairing_across_restart(self) -> None:
        from PIL import Image

        buf = io.BytesIO()
        self._make_textured_rgb(2000, 1500, seed=5).save(buf, format="JPEG", quality=90)
        uploaded = self.legacy.upload(TID, "pic.jpg", buf.getvalue(), "codex")

        rid = "req-img-pair-0001"
        res = self.bridge.send({
            "id": TID,
            "request_id": rid,
            "text": "请看看这张截图",
            "attachments": [uploaded["id"]],
        })
        self.assertTrue(res["accepted"])
        sent_prompt = self.sent_calls[-1]["arguments"]["prompt"]
        self.assertIn(f"{uploaded['id']}.jpg", sent_prompt)

        # Codex writes self-delegation into the rollout file
        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": TS2,
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "FunctionCallOutput",
                        "id": "call-img-direct-1",
                        "name": "send_message_to_thread",
                        "namespace": "codex_app",
                        "output": f"<codex_delegation><source_thread_id>{TID}</source_thread_id><input>{sent_prompt}</input></codex_delegation>",
                    },
                },
            }, ensure_ascii=False) + "\n")

        # Simulate SSE race: transcript is read BEFORE status/receipt reconciles delivery
        history = chat_history.History()
        page_before = history.conversation("codex", TID)
        self.assertIsNone(page_before["messages"][-1].get("client_request_id"))

        # Status reconciles delivery, records link on disk, and enriches control.images with message_id
        st = self.bridge.status(TID, fresh=True)
        img_rec = next(v for v in st["images"] if v["request_id"] == rid)
        self.assertEqual(img_rec["message_id"], "call-img-direct-1")

        # Same History instance immediately attaches client_request_id without rollout changing
        page_after = history.conversation("codex", TID)
        user_msg = page_after["messages"][-1]
        self.assertEqual(user_msg["source_id"], "call-img-direct-1")
        self.assertEqual(user_msg["client_request_id"], rid)
        self.assertEqual(user_msg["text"], "请看看这张截图")

        # Legacy chats.conversation() helper also attaches client_request_id
        with patch("chats.codex_thread", return_value=self.item):
            conv_direct = chats.conversation("codex", TID)
        self.assertEqual(conv_direct["messages"][-1]["client_request_id"], rid)

        # Survives restart (fresh AppToolsBridge + fresh History reading from disk)
        restarted = ca.AppToolsBridge(
            self.legacy, client=self.client, data_dir=self.data_dir,
            enable_background_drain=False, enable_background_watch=False,
        )
        self.addCleanup(restarted.close)
        st2 = restarted.status(TID, fresh=True)
        img_rec2 = next(v for v in st2["images"] if v["request_id"] == rid)
        self.assertEqual(img_rec2["message_id"], "call-img-direct-1")
        page2 = chat_history.History().conversation("codex", TID)
        self.assertEqual(page2["messages"][-1]["client_request_id"], rid)

    def test_queued_hook_prompt_image_send_pairs_client_request_id_and_message_id(self) -> None:
        from PIL import Image

        self.pipe_status = {"type": "active", "activeFlags": []}

        # Case A: queued with text + image, delivered via Stop hook <hook_prompt> UserMessage
        buf1 = io.BytesIO()
        Image.new("RGB", (120, 120), (10, 80, 160)).save(buf1, format="PNG")
        up1 = self.legacy.upload(TID, "q1.png", buf1.getvalue(), "codex")
        rid1 = "req-img-hook-0001"
        q1 = self.bridge.send({
            "id": TID,
            "request_id": rid1,
            "text": "排队发的图",
            "attachments": [up1["id"]],
            "intent": "queue",
        })
        self.assertEqual(q1["delivery_state"], "queued")
        popped1 = self.bridge.pop_queued_for_stop_hook(TID)
        self.assertIsNotNone(popped1)
        prompt1 = popped1["prompt"]

        # Case B: queued image-only (empty text), delivered via Stop hook HookPrompt item
        buf2 = io.BytesIO()
        Image.new("RGB", (100, 100), (180, 40, 20)).save(buf2, format="PNG")
        up2 = self.legacy.upload(TID, "q2.png", buf2.getvalue(), "codex")
        rid2 = "req-img-hook-0002"
        q2 = self.bridge.send({
            "id": TID,
            "request_id": rid2,
            "text": "",
            "attachments": [up2["id"]],
            "intent": "queue",
        })
        self.assertEqual(q2["delivery_state"], "queued")
        popped2 = self.bridge.pop_queued_for_stop_hook(TID)
        self.assertIsNotNone(popped2)
        prompt2 = popped2["prompt"]

        with self.rollout.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": TS2,
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "UserMessage",
                        "id": "um-hook-img-1",
                        "content": [{"type": "text", "text": f'<hook_prompt id="hp1">{prompt1}</hook_prompt>'}],
                    },
                },
            }, ensure_ascii=False) + "\n")
            f.write(json.dumps({
                "timestamp": "2026-01-02T03:04:15Z",
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "HookPrompt",
                        "id": "hp-hook-img-2",
                        "fragments": [{"text": prompt2}],
                    },
                },
            }, ensure_ascii=False) + "\n")

        rec1 = self.bridge.receipt(TID, rid1)
        self.assertEqual(rec1["result"]["text"], "已送达")
        self.assertEqual(rec1["result"]["evidence"]["message_id"], "um-hook-img-1")

        st = self.bridge.status(TID, fresh=True)
        by_req = {v["request_id"]: v for v in st["images"]}
        self.assertEqual(by_req[rid1]["message_id"], "um-hook-img-1")
        self.assertEqual(by_req[rid2]["message_id"], "hp-hook-img-2")

        page = chat_history.History().conversation("codex", TID)
        by_src = {m.get("source_id"): m for m in page["messages"]}
        self.assertEqual(by_src["um-hook-img-1"]["client_request_id"], rid1)
        self.assertEqual(by_src["hp-hook-img-2"]["client_request_id"], rid2)
        self.assertEqual(by_src["hp-hook-img-2"]["text"], "")


class AppToolsReceiptMissingTests(unittest.TestCase):
    """11-26 P1/8.1: the app-tools route answers "missing": true from the same delivery record as the old one."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.legacy = codex_control.Bridge()
        self.legacy.data_root = Path(self.tmp.name) / "attachments"
        self.bridge = object.__new__(ca.AppToolsBridge)
        self.bridge.legacy = self.legacy

    def test_a_record_that_reads_but_holds_no_such_request_says_missing(self) -> None:
        self.legacy._begin("recorded-request-0001", TID, {"id": TID, "text": "test"})
        self.assertEqual(self.bridge.receipt(TID, "unknown-request-0001"), {"state": "unknown", "missing": True})

    def test_a_request_it_holds_is_not_called_missing(self) -> None:
        self.legacy._begin("recorded-request-0001", TID, {"id": TID, "text": "test"})
        self.legacy._finish("recorded-request-0001", {"ok": False, "delivery_state": "rejected",
                                                      "request_id": "recorded-request-0001", "text": "未接收"})
        rec = self.bridge.receipt(TID, "recorded-request-0001")
        self.assertEqual(rec["state"], "rejected")
        self.assertNotIn("missing", rec)

    def test_without_a_record_file_the_answer_is_plain_unknown(self) -> None:
        self.assertEqual(self.bridge.receipt(TID, "any-request-000001"), {"state": "unknown"})


if __name__ == "__main__":
    unittest.main()
