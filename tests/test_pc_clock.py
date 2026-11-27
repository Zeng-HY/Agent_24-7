"""11-27: this computer's clock runs slow (Windows' time service is off), so the relay's own clock is the one that
counts. Every answer the relay sends carries a Date header; pc_clock keeps the median of the newest ones as the
offset, ignores anything under three seconds, and moves only when it changes by more than two.

Nothing here talks to the relay or the network beyond a made-up aiohttp server on 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from email.utils import formatdate
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aiohttp import ClientSession, ClientTimeout, TraceConfig, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pc_clock  # noqa: E402
import relay_agent  # noqa: E402

NOW = 1_000_000.0  # this computer's made-up time (Unix seconds)
SLOW = 46.0        # how far behind the relay it is on 11-27
STARTED, ENDED = 1767323050, 1767323110


def offset_by(seconds: float, log=None) -> pc_clock.Clock:
    """The state a run is in after the answers say the relay is [seconds] ahead (negative: behind)."""
    clock = pc_clock.reset(clock=lambda: NOW, log=log)
    clock.add(NOW + seconds, NOW)
    return clock


class OffsetTests(unittest.TestCase):
    def tearDown(self) -> None:
        pc_clock.reset()

    def test_no_sample_is_no_offset(self):
        pc_clock.reset(clock=lambda: NOW)
        self.assertEqual(pc_clock.offset(), 0)
        self.assertEqual(pc_clock.to_true_seconds(STARTED), STARTED)
        self.assertEqual(pc_clock.to_true_ms(STARTED * 1000), STARTED * 1000)

    def test_the_median_of_the_newest_samples(self):
        clock = pc_clock.reset(clock=lambda: NOW)
        for value in (40.2, 46.4, 46.1, 45.9, 100.0):  # one answer on a slow link is no reason to move the clock
            clock.add(NOW + value, NOW)
        self.assertAlmostEqual(clock.offset, 46.1, delta=0.01)

    def test_under_three_seconds_is_no_offset(self):
        clock = pc_clock.reset(clock=lambda: NOW)
        for value in (1.0, 2.0, 2.5):
            clock.add(NOW + value, NOW)
        self.assertEqual(clock.offset, 0)

    def test_the_offset_moves_only_by_more_than_two_seconds(self):
        clock = offset_by(SLOW)
        self.assertEqual(clock.offset, SLOW)
        clock.drop_samples()  # the samples below are the newest ones; the published offset stays
        for _ in range(5):
            clock.add(NOW + 47.5, NOW)
        self.assertEqual(clock.offset, SLOW)  # 1.5 s further: not worth a change
        clock.drop_samples()
        for _ in range(5):
            clock.add(NOW + 48.5, NOW)
        self.assertAlmostEqual(clock.offset, 48.5, delta=0.01)  # 2.5 s further: it moves

    def test_a_drift_back_inside_the_dead_zone_stops_the_correction(self):
        clock = offset_by(SLOW)
        clock.drop_samples()
        for _ in range(3):
            clock.add(NOW + 0.5, NOW)
        self.assertEqual(clock.offset, 0)

    def test_one_line_per_change_and_only_numbers(self):
        lines = []
        clock = offset_by(SLOW, log=lines.append)
        self.assertEqual(lines, ["时钟：这台电脑比中转慢 46 秒，发给手机的时间已校正"])
        for _ in range(5):
            clock.add(NOW + SLOW, NOW)
        self.assertEqual(len(lines), 1)
        clock.drop_samples()
        clock.add(NOW - 30.0, NOW)
        self.assertEqual(lines[-1], "时钟：这台电脑比中转快 30 秒，发给手机的时间已校正")
        clock.drop_samples()
        clock.add(NOW + 0.2, NOW)
        self.assertEqual(lines[-1], "时钟：和中转的时间对上了，不再校正")

    def test_a_log_that_raises_does_not_stop_the_clock(self):
        def broken(_text):
            raise OSError("no log today")

        clock = offset_by(SLOW, log=broken)
        self.assertEqual(clock.offset, SLOW)

    def test_zero_empty_and_other_values_are_left_alone(self):
        offset_by(SLOW)
        self.assertEqual(pc_clock.to_true_seconds(0), 0)
        self.assertEqual(pc_clock.to_true_seconds(None), None)
        self.assertEqual(pc_clock.to_true_seconds(""), "")
        self.assertEqual(pc_clock.to_true_seconds(str(STARTED)), str(STARTED))
        self.assertEqual(pc_clock.to_true_ms(0), 0)
        self.assertEqual(pc_clock.to_true_ms(None), None)

    def test_a_start_and_an_end_keep_their_difference(self):
        offset_by(SLOW)
        self.assertEqual(pc_clock.to_true_seconds(STARTED), STARTED + 46)
        self.assertEqual(pc_clock.to_true_seconds(ENDED), ENDED + 46)
        self.assertEqual(pc_clock.to_true_seconds(ENDED) - pc_clock.to_true_seconds(STARTED), ENDED - STARTED)
        self.assertEqual(pc_clock.to_true_ms(STARTED * 1000), (STARTED + 46) * 1000)
        self.assertEqual(pc_clock.to_true_ms(ENDED * 1000) - pc_clock.to_true_ms(STARTED * 1000),
                         (ENDED - STARTED) * 1000)


class DateHeaderTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        pc_clock.reset()

    async def test_the_handler_reads_the_date_header(self):
        pc_clock.reset(clock=lambda: NOW)
        response = SimpleNamespace(headers={"Date": formatdate(NOW + SLOW, usegmt=True)})
        await pc_clock.on_request_end(None, None, SimpleNamespace(response=response))
        self.assertAlmostEqual(pc_clock.offset(), SLOW, delta=1.0)

    async def test_an_answer_without_a_date_header_is_no_sample(self):
        pc_clock.reset(clock=lambda: NOW)
        for headers in ({}, {"Date": "not a date"}, {"Date": ""}, None):
            response = SimpleNamespace(headers=headers) if headers is not None else SimpleNamespace()
            await pc_clock.on_request_end(None, None, SimpleNamespace(response=response))
        self.assertEqual(pc_clock.offset(), 0)
        self.assertEqual(len(pc_clock.clock()._samples), 0)

    async def test_a_real_answer_through_the_session_the_agent_uses(self):
        """The same TraceConfig signature relay_agent builds, against a real aiohttp server whose Date is 46 s ahead."""
        calls = []

        async def answer(_request):
            calls.append(1)
            return web.Response(text="ok", headers={"Date": formatdate(NOW + SLOW, usegmt=True)})

        app = web.Application()
        app.router.add_get("/tunnel/connect", answer)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        pc_clock.reset(clock=lambda: NOW)
        trace = TraceConfig()
        trace.on_request_end.append(pc_clock.on_request_end)
        try:
            async with ClientSession(timeout=ClientTimeout(total=10), trace_configs=[trace]) as client:
                async with client.get(f"http://127.0.0.1:{port}/tunnel/connect") as response:
                    await response.read()
        finally:
            await runner.cleanup()
        self.assertTrue(calls)
        self.assertAlmostEqual(pc_clock.offset(), SLOW, delta=1.0)

    def test_the_device_agent_builds_a_session_with_the_hook(self):
        seen = {}

        class FakeSession:
            def __init__(self, *args, **kwargs):
                seen.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def ws_connect(self, *args, **kwargs):
                raise OSError("no relay here")

        agent = relay_agent.Agent("http://relay.test", "k" * 43, 1, "local", test_http=True)

        async def run():
            with mock.patch.object(relay_agent, "ClientSession", FakeSession), \
                    mock.patch.object(relay_agent.asyncio, "sleep", side_effect=asyncio.CancelledError):
                await agent.run()

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(run())
        self.assertEqual(list(seen["trace_configs"][0].on_request_end), [pc_clock.on_request_end])


if __name__ == "__main__":
    unittest.main()
