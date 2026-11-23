"""Usage from the phone (11-17): how much of Codex's and Claude's limits is used and when each resets, and using one of
Codex's own reset credits — without touching either app's login.

Where the numbers come from:

- Codex, live (codex_live): a codex.exe app-server of our own, started for one question and closed again, the way
  archives.py already talks to Codex when a conversation is archived. The pipe 遥应 shares with Codex (codex-ipc) has
  conversation methods only: account/rateLimits/read and account/rateLimitResetCredit/consume are not among them. Codex's
  own app-server holds the login and does the asking, so this file never reads ~/.codex/auth.json and never calls
  chatgpt.com itself.
- Codex, as of its last answer (codex_records): every answer in a rollout file (~/.codex/sessions/YYYY/MM/DD/
  rollout-*.jsonl) writes one token_count line whose rate_limits carry the weekly and the 5-hour window with when they
  reset. It is only as new as the desktop's last answer; usage spent elsewhere shows up at the next one.
- Claude (claude_window): the button beside its model reads "Usage: 35% of 5-hour limit, Resets at 12:20 PM". It is read
  with UI Automation, read-only — nothing is clicked, hovered, restored or brought to the front, so a minimised window
  may still show old numbers (the phone says so). Claude's fuller set is only behind a hover card.

The reset credit is the user's: the phone always confirms first, and the request id makes a retry reuse the idempotency
key, so an answer that never arrived cannot use a second one.

11-17 on this computer (Codex 26.1106.6628.0, Claude 5.11492.5.0): one read of account/rateLimits/read answered in
1.9 s, its app-server exited cleanly and ~/.codex/auth.json was untouched; Claude's window said "Usage: 35% of
5-hour limit, Resets at 12:20 PM". The one reset credit this computer has (expires 12-13) was never used here: the
tests and the hand-off's checks only ever ask the real Codex to read.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import archives
import chats
import win32gui
from app_paths import DATA

# One at a time: a live read and a reset share the Codex app-server's login on this computer. Re-entrant, because
# Usage.read holds it while codex_live takes it again for the same call.
_LOCK = threading.RLock()

TAIL_BYTES = 512 * 1024  # how much of the end of a rollout file is read
CONVERSATIONS = 8  # the conversations Codex worked on last, one of them last had a token_count
CACHE_SECONDS = 30  # a live read is the same question within this
LIVE_ERROR_SECONDS = 600  # the same live-read failure is logged once in this many seconds
RECORD_LINES = 200  # codex-resets.jsonl keeps this many lines
CONFIRM_TEXT = "要先在手机上确认"
USAGE_PREFIX = "Usage: "

RESET_TEXTS = {
    "reset": "已用掉 1 次重置，Codex 用量恢复了",
    "nothingToReset": "现在没有能重置的限额，这次没用掉",
    "noCredit": "没有可用的重置次数，这次没用掉",
    "alreadyRedeemed": "这次之前已经用成了，没有再用掉一次",
}
REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


class UsageError(chats.ChatError):
    """What the phone shows, and the status and code it answers with (never 503: the phones read that as offline)."""

    def __init__(self, text: str, status: int = 409, code: str = ""):
        super().__init__(text)
        self.status = status
        self.code = code


# ---------------------------------------------------------------- the window format both apps share


def _window_name(kind: str, minutes: int) -> str:
    if kind == "5h":
        return "5 小时"
    if kind == "weekly":
        return "每周"
    if minutes <= 0:
        return "用量"
    if minutes % 1440 == 0:
        return f"{minutes // 1440} 天"
    if minutes % 60 == 0:
        return f"{minutes // 60} 小时"
    return f"{minutes / 60:.1f} 小时"


def usage_window(minutes, used_percent, resets_at) -> dict:
    """One limit: 5 hours (300 minutes), the week (10080), or another length Codex may report."""
    minutes = int(minutes) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) else 0
    kind = "5h" if minutes == 300 else "weekly" if minutes == 10080 else "other"
    percent = 0 if used_percent is None else int(round(float(used_percent)))
    return {"kind": kind, "minutes": minutes, "used_percent": max(0, min(100, percent)),
            "resets_at": _seconds(resets_at), "name": _window_name(kind, minutes)}


def _seconds(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _stamp_ms(stamp):
    """A rollout line's timestamp ("2026-11-17T02:22:02.354Z") in milliseconds."""
    try:
        return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _say(log, text: str) -> None:
    """A line in the day's log; a log that cannot be written must not change the answer."""
    if log is None:
        return
    try:
        log(text)
    except Exception:
        pass


# ---------------------------------------------------------------- Codex: the records of its answers


def codex_records(now=None) -> dict | None:
    """The newest token_count of the conversations Codex last answered in. `now` is accepted for symmetry with
    codex_live and is not used: the time is the line's own."""
    db = chats.codex_db()
    if db is None:
        return None
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3)
        try:
            columns = {row[1] for row in con.execute("pragma table_info(threads)")}
            order = "updated_at_ms" if "updated_at_ms" in columns else "updated_at"
            rows = con.execute(f"select rollout_path from threads order by {order} desc limit ?",
                               (CONVERSATIONS,)).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        return None
    best = None
    for (path,) in rows:
        if not path:
            continue
        found = _last_token_count(Path(chats._strip_unc(str(path))))
        if found is None:
            continue
        moment, limits = found
        if best is None or moment > best[0]:
            best = (moment, limits)
    if best is None:
        return None
    moment, limits = best
    return {"source": "records", "as_of": moment, "plan": limits.get("plan_type"),
            "windows": _windows(limits, "used_percent", "window_minutes", "resets_at"),
            "reached": limits.get("rate_limit_reached_type"), "resets": None,
            "ordinary_usage_allowed": None}


def _last_token_count(path: Path) -> tuple[int, dict] | None:
    """The last line of a rollout file that carries a usage snapshot, and when it was written (milliseconds)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - TAIL_BYTES)
            f.seek(start)
            data = f.read(size - start)
    except OSError:
        return None
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]  # the first one may be half a line
    for raw in reversed(lines):
        try:
            line = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if not isinstance(line, dict) or line.get("type") != "event_msg":
            continue
        payload = line.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        limits = payload.get("rate_limits")
        if not isinstance(limits, dict) or limits.get("limit_id") not in ("codex", None):
            continue
        moment = _stamp_ms(line.get("timestamp"))
        if moment is None:
            continue
        return moment, limits
    return None


def _windows(limits: dict, used_key: str, minutes_key: str, resets_key: str) -> list[dict]:
    windows = []
    for side in ("primary", "secondary"):
        window = limits.get(side)
        if isinstance(window, dict):
            windows.append(usage_window(window.get(minutes_key), window.get(used_key), window.get(resets_key)))
    return windows


# ---------------------------------------------------------------- Codex: the app-server, one question at a time


def codex_live(server_factory) -> dict:
    """account/rateLimits/read through an app-server of our own, closed straight after."""
    with _LOCK:
        try:
            with server_factory() as server:
                reply = server.call("account/rateLimits/read", {"excludeResetCreditDetails": False}, 20)
        except UsageError:
            raise
        except archives.CodexRefused as exc:
            raise UsageError("Codex 没给用量：" + str(exc)[:120], 409, "codex_refused") from None
        except archives.ArchiveError as exc:
            raise UsageError("读不到 Codex 的实时用量：" + str(exc), 409, "codex_unreachable") from None
        except Exception as exc:  # an OSError, a program that would not start: the phone falls back to the records
            raise UsageError("读不到 Codex 的实时用量：" + type(exc).__name__, 409, "codex_unreachable") from None
    return _live_snapshot(reply)


def _live_snapshot(reply) -> dict:
    """The reply of account/rateLimits/read as the phone shows it. Never accountId or the upsell."""
    if not isinstance(reply, dict):
        raise UsageError("Codex 没给用量：读不懂它回的用量", 409, "codex_refused")
    by_id = reply.get("rateLimitsByLimitId")
    snapshot = by_id.get("codex") if isinstance(by_id, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = reply.get("rateLimits")
    if not isinstance(snapshot, dict):
        raise UsageError("Codex 没给用量：回的用量里没有 Codex 这一桶", 409, "codex_refused")
    resets = None
    credits = reply.get("rateLimitResetCredits")
    if isinstance(credits, dict):
        listed, items = credits.get("credits"), None
        if isinstance(listed, list):
            items = [{"id": credit.get("id"), "title": credit.get("title"),
                      "description": credit.get("description"), "granted_at": _seconds(credit.get("grantedAt")),
                      "expires_at": _seconds(credit.get("expiresAt"))}
                     for credit in listed
                     if isinstance(credit, dict) and credit.get("status") == "available"]
        resets = {"available": credits.get("availableCount"), "items": items}
    return {"source": "live", "as_of": _now_ms(), "plan": snapshot.get("planType"),
            "windows": _windows(snapshot, "usedPercent", "windowDurationMins", "resetsAt"),
            "reached": snapshot.get("rateLimitReachedType"), "resets": resets,
            "ordinary_usage_allowed": reply.get("ordinaryUsageAllowed")}


# ---------------------------------------------------------------- Codex: one reset credit


def reset_text(outcome) -> str:
    return RESET_TEXTS.get(outcome) or f"Codex 回了不认识的结果（{outcome}），请到电脑上的 Codex 里看用量"


def codex_redeem(request_id, credit_id, server_factory, data_dir=None, log=None, cached=None) -> dict:
    """Use one of Codex's reset credits. The request id is the idempotency key: the same one again never uses a second
    credit, whether the first answer arrived or not. `cached` is the phone's last live read, for an answer that was
    already given before."""
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise UsageError("请求编号不对", 400, "bad_request")
    if credit_id is not None and (not isinstance(credit_id, str) or len(credit_id) > 200):
        raise UsageError("重置编号不对", 400, "bad_request")
    directory = Path(data_dir) if data_dir is not None else DATA
    record = directory / "attachments" / "codex-resets.jsonl"
    with _LOCK:
        for entry in reversed(_records(record)):
            if entry.get("request_id") == request_id and entry.get("outcome") in RESET_TEXTS:
                return {"ok": True, "outcome": entry["outcome"], "text": reset_text(entry["outcome"]),
                        "usage": cached}
        try:
            server = server_factory()
        except Exception as exc:  # no app-server: nothing was sent
            raise UsageError("没用掉：连不上电脑上的 Codex（" + str(exc) + "）", 409, "codex_unreachable") \
                from None
        try:
            with server:
                _record(record, {"request_id": request_id, "at": _now_ms(), "stage": "sending"})
                params = {"idempotencyKey": request_id}
                if credit_id:
                    params["creditId"] = credit_id
                reply = server.call("account/rateLimitResetCredit/consume", params, 30)
                if not isinstance(reply, dict):
                    raise ValueError("读不懂 Codex 回的用量重置结果")
                outcome = reply.get("outcome")
                try:
                    usage = _live_snapshot(server.call("account/rateLimits/read",
                                                       {"excludeResetCreditDetails": False}, 20))
                except Exception:
                    usage = None  # the reset stands; the phone reads the usage again
        except archives.CodexRefused as exc:
            raise UsageError("Codex 没让用：" + str(exc)[:120], 409, "codex_refused") from None
        except UsageError:
            raise
        except Exception as exc:  # sent, and no answer: it may or may not have gone through
            _record(record, {"request_id": request_id, "at": _now_ms(), "stage": "unconfirmed"})
            _say(log, f"Codex 重置：手机请求 {request_id[:8]} 没确认结果（{type(exc).__name__}）")
            raise UsageError("没确认这次用成了没有。再点一次会用同一个编号重试，不会多用掉一次。",
                             409, "reset_unconfirmed") from None
        _record(record, {"request_id": request_id, "at": _now_ms(), "outcome": outcome})
        available = (usage or {}).get("resets")
        left = available.get("available") if isinstance(available, dict) else None
        _say(log, f"Codex 重置：手机请求 {request_id[:8]} → {outcome}；"
                  f"之后可用 {left if isinstance(left, int) else '未知'} 次")
        return {"ok": True, "outcome": outcome, "text": reset_text(outcome),
                "usage": {"available": True, **usage} if usage else None}


def _records(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _record(path: Path, entry: dict) -> None:
    """One more line, keeping the last RECORD_LINES. A record that cannot be written must not stop the reset."""
    try:
        lines = [line for line in _records(path)] if path.exists() else []
        lines.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines[-RECORD_LINES:]) + "\n",
                        encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- Claude: the button on its window


def claude_text(name: str) -> dict:
    """The button's words, parsed: one window (Claude shows its tightest one) and when it resets."""
    windows, resets_text = [], None
    parts = name[len(USAGE_PREFIX):].split(", ") if name.startswith(USAGE_PREFIX) else []
    for index, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if part.startswith("Resets "):
            if resets_text is None:
                resets_text = _reset_time(part[len("Resets "):])
            continue
        if index != 0:
            continue  # only the first part is the limit Claude picked
        label = percent = None
        match = re.fullmatch(r"(\d+)% of (.+)", part) or None
        if match:
            percent, label = int(match.group(1)), match.group(2)
        else:
            match = re.fullmatch(r"(.+): (\d+)%", part)
            if match:
                label, percent = match.group(1), int(match.group(2))
        if label is None or percent is None:
            continue
        kind, shown = _claude_kind(label)
        windows.append({"kind": kind, "label": label, "name": shown,
                        "used_percent": max(0, min(100, percent)), "resets_at": None})
    if resets_text:
        for window in windows:
            window["resets_text"] = resets_text
    return {"text": name, "windows": windows}


def _claude_kind(label: str) -> tuple[str, str]:
    if "5-hour" in label:
        return "5h", "5 小时"
    if label.startswith("Weekly"):
        rest = label[len("Weekly"):].strip()
        rest = rest[1:].strip() if rest.startswith("·") else rest
        if not rest:
            return "weekly", "每周"
        return "weekly", "每周（" + ("全部模型" if rest == "all models" else rest) + "）"
    return "other", label


def _reset_time(text: str) -> str:
    """'at 12:20 PM' as 24 hours; anything else ("Fri 3:00 PM") as Claude wrote it."""
    text = text.strip()
    match = re.fullmatch(r"at (\d{1,2}):(\d{2}) (AM|PM)", text)
    if not match:
        return text
    hour, minute, half = int(match.group(1)), match.group(2), match.group(3)
    hour = hour % 12 + 12 if half == "PM" else hour % 12
    return f"{hour:02d}:{minute}"


def claude_window(desktop) -> dict:
    """Claude's own button, read on the desktop's UI Automation thread. Read-only: the window is never clicked,
    hovered, restored or brought forward."""
    try:
        auto = desktop._need_auto()
        hwnd = chats.app_window(chats.CLAUDE_PROCESS)
        if not hwnd:
            return {"available": False, "reason": "电脑上 Claude 没开"}
        root = auto.ControlFromHandle(hwnd)
        name = ""
        for button in desktop._find(root, "ButtonControl"):
            text = getattr(button, "Name", "") or ""
            if text.startswith(USAGE_PREFIX):
                name = text
                break
        if not name:
            return {"available": False, "reason": "Claude 窗口上没有用量（要开着一个 Code 对话）"}
        return {"available": True, "source": "window", "as_of": _now_ms(), **claude_text(name),
                "minimized": _minimized(hwnd)}
    except Exception:
        return {"available": False, "reason": "这会儿读不到 Claude 窗口，请稍后再试"}


def _minimized(hwnd) -> bool:
    try:
        return bool(win32gui.IsIconic(hwnd))
    except Exception:
        return False


# ---------------------------------------------------------------- both, for the phone


class Usage:
    """remote.py's server.usage: GET /api/usage and POST /api/usage/codex-reset."""

    def __init__(self, desktop, log, apps, server_factory=archives.CodexServer, records=codex_records,
                 data_dir=DATA):
        self.desktop = desktop
        self.log = log
        self.apps = apps  # read late: remote.py sets server.machine after this object (archives does the same)
        self.server_factory = server_factory
        self.records = records
        self.data_dir = Path(data_dir)
        self._cache = None  # (monotonic time, the codex part of a read)
        self._live_errors = {}  # code -> when it was last logged

    def read(self, live: bool, *, include_agents: bool = False) -> dict:
        from agents import registry
        apps = list(self.apps() or [])
        out: dict = {}
        by_agent: dict = {}
        for agent in registry.load():
            if not agent.can("usage"):
                continue
            data = agent.read_usage(self, bool(live)) if agent.id in apps else agent.usage_not_installed()
            by_agent[agent.id] = data
            if agent.manifest().get("legacy"):
                out[agent.id] = data
        out["now"] = _now_ms()
        if include_agents:
            out["agents"] = by_agent
        return out

    def read_agent(self, app: str, live: bool = False) -> dict:
        from agents import registry
        from agents.base import Unsupported
        agent = registry.get(app)
        if not agent.can("usage"):
            raise Unsupported("这个助手没有用量")
        apps = list(self.apps() or [])
        if agent.id not in apps:
            return agent.usage_not_installed()
        return agent.read_usage(self, bool(live))

    def redeem(self, body: dict) -> dict:
        from agents import registry
        if body.get("confirmed") is not True:
            raise UsageError(CONFIRM_TEXT, 400, "not_confirmed")
        apps = list(self.apps() or [])
        agent = next((a for a in registry.load() if a.can_reset_usage), None)
        if agent is None or agent.id not in apps:
            label = agent.manifest()["name"]["zh"] if agent is not None else "Codex"
            code = f"no_{agent.id}" if agent is not None else "no_agent"
            raise UsageError(f"这台电脑没装 {label}", 409, code)
        return agent.redeem_usage(self, body)

    # -- the codex part, with the 30-second cache and the fallback to the records

    def _codex(self, live: bool) -> dict:
        with _LOCK:
            if self._cache is not None and time.monotonic() - self._cache[0] < CACHE_SECONDS:
                # A records-only read is no answer to a live question: ask Codex itself instead of handing it back.
                if not live or _came_from_live(self._cache[1]):
                    return self._cache[1]
            result = self._live() if live else self._from_records()
            self._cache = (time.monotonic(), result)
            return result

    def _from_records(self) -> dict:
        found = self.records()
        if not found:
            return {"available": False, "reason": "电脑上还没有 Codex 的用量记录（用一次 Codex 就会有）"}
        return {"available": True, **found}

    def _live(self) -> dict:
        try:
            return {"available": True, **codex_live(self.server_factory)}
        except UsageError as exc:
            self._note_live_error(exc.code)
            return {**self._from_records(), "live_error": str(exc)}

    def _note_live_error(self, code: str) -> None:
        now = time.monotonic()
        last = self._live_errors.get(code)
        if last is not None and now - last < LIVE_ERROR_SECONDS:
            return
        self._live_errors[code] = now
        _say(self.log, f"用量：读不到 Codex 的实时用量（{code}）")


def _came_from_live(result: dict) -> bool:
    """Whether a read asked Codex itself: a live answer, or the records with the reason it could not be had."""
    return result.get("source") == "live" or "live_error" in result
