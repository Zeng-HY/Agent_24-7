"""How far this computer's clock is off the relay's, and the times the phone may add it to.

The phone turns a turn's start into "运行中 · N 分 N 秒" by subtracting it from its own now, which is right, so a
computer whose clock is behind shows every turn that much longer. It is behind on this PC: Windows' time service is
off (11-27: 46 s slow; 19 s on 11-17, so it keeps drifting). Every answer the relay sends carries an HTTP Date
header, and relay_agent's ClientSession reads it: one sample per answer is the relay's time minus this computer's
time when the answer arrived. The median of the newest SAMPLES is the offset; under DEAD_ZONE seconds it counts as
0, and it is only published once it moves by more than STEP. Date has whole seconds, so a sample is up to a second
out, which the dead zone swallows.

Nothing here opens a connection, reads a setting or changes the system clock. With no sample the offset is 0, and
every time goes out exactly as it did before.
"""
from __future__ import annotations

import collections
import statistics
import time
from email.utils import parsedate_to_datetime

SAMPLES = 15      # answers kept for the median
DEAD_ZONE = 3.0   # seconds; an offset smaller than this counts as 0
STEP = 2.0        # seconds; the published offset moves only by more than this


class Clock:
    """The samples taken so far and the offset they add up to."""

    def __init__(self, clock=time.time, log=None):
        self._clock = clock
        self.log = log
        self._samples: collections.deque = collections.deque(maxlen=SAMPLES)
        self.offset = 0.0

    def add(self, relay, local=None) -> None:
        """One sample: the relay's time (Unix seconds) and this computer's at the same moment."""
        try:
            sample = float(relay) - (self._clock() if local is None else float(local))
        except (TypeError, ValueError):
            return
        self._samples.append(sample)
        self._publish()

    def drop_samples(self) -> None:
        """Forget the samples and keep the published offset (what the next round is measured against)."""
        self._samples.clear()

    def _publish(self) -> None:
        found = statistics.median(self._samples) if self._samples else 0.0
        offset = 0.0 if abs(found) < DEAD_ZONE else float(found)
        if abs(offset - self.offset) <= STEP:
            return
        self.offset = offset
        if not callable(self.log):
            return
        seconds = int(round(abs(offset)))
        if offset > 0:
            line = f"时钟：这台电脑比中转慢 {seconds} 秒，发给手机的时间已校正"
        elif offset < 0:
            line = f"时钟：这台电脑比中转快 {seconds} 秒，发给手机的时间已校正"
        else:
            line = "时钟：和中转的时间对上了，不再校正"
        try:
            self.log(line)
        except Exception:
            pass  # a log line must never stop the connection


_CLOCK = Clock()


def clock() -> Clock:
    """The one clock this program keeps (tests replace it with reset())."""
    return _CLOCK


def reset(clock=time.time, log=None) -> Clock:
    """Forget every sample and the offset; tests hand in their own clock and log."""
    global _CLOCK
    _CLOCK = Clock(clock=clock, log=log)
    return _CLOCK


def set_log(write) -> None:
    """Where the one line about a changed offset goes (never a title or a message)."""
    _CLOCK.log = write


def offset() -> float:
    return _CLOCK.offset


def add(relay, local=None) -> None:
    _CLOCK.add(relay, local)


def to_true_seconds(value):
    """[value], Unix seconds, as the phone's clock reads it; 0, None and '' stay as they are."""
    return _shift(value, _CLOCK.offset)


def to_true_ms(value):
    """[value], Unix milliseconds, as the phone's clock reads it; 0, None and '' stay as they are."""
    return _shift(value, _CLOCK.offset * 1000)


def _shift(value, offset):
    if not offset or isinstance(value, bool) or not isinstance(value, (int, float)) or value == 0:
        return value
    shifted = value + offset
    return int(round(shifted)) if isinstance(value, int) else shifted


def http_date(value) -> float | None:
    """Unix seconds of an HTTP Date header, or None when it is not one."""
    try:
        found = parsedate_to_datetime(value)
        return None if found is None else found.timestamp()
    except Exception:
        return None


def sample_response(response, received=None) -> None:
    """One sample from an answer's Date header; [received] is this computer's time (tests pass a fixed one)."""
    try:
        headers = response.headers
    except Exception:
        return
    try:
        value = headers.get("Date") or headers.get("date")
    except Exception:
        return
    relay = http_date(value)
    if relay is not None:
        _CLOCK.add(relay, received)


async def on_request_end(session, context, params) -> None:
    """aiohttp TraceConfig callback: every relay answer is one sample. Never raises into the session."""
    try:
        sample_response(params.response)
    except Exception:
        pass
