"""Protocol and client headers forwarded through relay_transport and relay_agent to remote.py."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import relay_transport
import remote
from relay_agent import Agent
from relay_identity import Identity
from relay_service import COOKIE, Service


async def wait_until(predicate, timeout=8):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


class _RecordingHandler(remote.Handler):
    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self):
        self.server.seen_headers.append({k.lower(): v for k, v in self.headers.items()})
        super().do_GET()


class RelayProtocolHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runners = []
        self.runs = []

        # Local remote.py HTTP server on a random loopback port.
        self.local_token = "local-secret"
        self.local_server = remote.Server(("127.0.0.1", 0), _RecordingHandler)
        self.local_server.cfg = {"bind": "127.0.0.1", "token": self.local_token, "allowed_logins": []}
        self.local_server.machine = {"name": "测试电脑", "apps": ["codex", "claude", "deepseek"], "voice": False}
        self.local_server.owner = types.SimpleNamespace(login=lambda: "")
        self.local_server.log = types.SimpleNamespace(write=lambda *args, **kwargs: None)
        self.local_server.verbose = False
        self.local_server.seen_headers = []
        self.local_port = self.local_server.server_address[1]
        self.local_thread = threading.Thread(target=self.local_server.serve_forever, daemon=True)
        self.local_thread.start()

        # Relay service + relay_agent tunnel connected to the local remote.py server.
        self.store = Identity(Path(self.tmp.name) / "state.sqlite3")
        self.service = Service("https://relay.test", self.store, types.SimpleNamespace(send=lambda *args: None))
        runner = web.AppRunner(self.service.app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        self.runners.append(runner)
        port = site._server.sockets[0].getsockname()[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.service.origin = self.origin
        self.service.authority = f"127.0.0.1:{port}"
        self.client = ClientSession(timeout=ClientTimeout(total=20))

        await asyncio.to_thread(self.store.register, "alice", "password-for-alice", self.store.grant("invite"))
        self.token = await asyncio.to_thread(self.store.login, "alice", "password-for-alice")
        self.key = "a" * 43
        self.device = self.store.approve(self.token, self.store.start_authorization(self.key, "alice"))

        self.agent = Agent(self.origin, self.key, self.local_port, self.local_token, test_http=True)
        self.runs.append(asyncio.create_task(self.agent.run()))
        self.assertTrue(await wait_until(lambda: self.device in self.service.hub.connections))

    async def asyncTearDown(self):
        for task in self.runs:
            task.cancel()
        await asyncio.gather(*self.runs, return_exceptions=True)
        await self.client.close()
        for runner in reversed(self.runners):
            await runner.cleanup()
        self.local_server.shutdown()
        self.local_server.server_close()
        self.local_thread.join(timeout=5)
        self.tmp.cleanup()

    def _auth_headers(self, extra=None):
        headers = {"Cookie": f"{COOKIE}={self.token}", "Origin": self.origin}
        if extra:
            headers.update(extra)
        return headers

    def test_request_headers_allowlist_includes_protocol_and_client(self):
        self.assertEqual(
            relay_transport.REQUEST_HEADERS,
            (
                "Content-Type",
                "Accept",
                "Accept-Encoding",
                "Range",
                "If-Range",
                "Last-Event-ID",
                "User-Agent",
                "X-Teleply-Protocol",
                "X-Teleply-Client",
            ),
        )

    async def test_tunnel_forwards_protocol_2_and_client_headers_to_remote(self):
        url = f"{self.origin}/d/{self.device}/api/agents"
        async with self.client.get(
            url,
            headers=self._auth_headers(
                {
                    "X-Teleply-Protocol": "2",
                    "X-Teleply-Client": "android/0.7.0",
                    "X-Unlisted-Header": "must-not-pass",
                    "Tailscale-User-Login": "spoof@example.com",
                }
            ),
        ) as resp:
            self.assertEqual(resp.status, 200)
            data = await resp.json()

        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["protocol"], 2)
        self.assertEqual([a["id"] for a in data["agents"]], ["codex", "claude", "deepseek"])

        seen = self.local_server.seen_headers[-1]
        self.assertEqual(seen.get("x-teleply-protocol"), "2")
        self.assertEqual(seen.get("x-teleply-client"), "android/0.7.0")
        self.assertNotIn("x-unlisted-header", seen)
        self.assertNotIn("tailscale-user-login", seen)

    async def test_tunnel_without_protocol_header_stays_protocol_1(self):
        url = f"{self.origin}/d/{self.device}/api/agents"
        async with self.client.get(
            url,
            headers=self._auth_headers({"X-Extra-Noise": "drop-me"}),
        ) as resp:
            self.assertEqual(resp.status, 404)
            data = await resp.json()

        self.assertIn("error", data)
        seen = self.local_server.seen_headers[-1]
        self.assertNotIn("x-teleply-protocol", seen)
        self.assertNotIn("x-extra-noise", seen)

    async def test_relay_agent_stream_filters_unlisted_headers_directly(self):
        """Even if a tunnel peer includes unlisted headers in metadata, relay_agent drops them."""
        chunks = self.service.hub.fetch(
            self.device,
            "/api/agents",
            headers={
                "Accept-Encoding": "identity",
                "X-Teleply-Protocol": "2",
                "X-Teleply-Client": "web/0.27.0",
                "X-Injected-Header": "blocked",
                "Tailscale-User-Login": "spoof@example.com",
            },
        )
        body = b""
        try:
            async for chunk in chunks:
                body += chunk
        finally:
            await chunks.aclose()

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["protocol"], 2)
        seen = self.local_server.seen_headers[-1]
        self.assertEqual(seen.get("x-teleply-protocol"), "2")
        self.assertEqual(seen.get("x-teleply-client"), "web/0.27.0")
        self.assertNotIn("x-injected-header", seen)
        self.assertNotIn("tailscale-user-login", seen)


if __name__ == "__main__":
    unittest.main()
