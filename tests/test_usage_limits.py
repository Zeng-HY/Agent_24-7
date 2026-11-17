"""Usage from the phone (usage_limits.py, 11-17): Codex's limits and reset credits, live from its own app-server and
from its conversations' records; Claude's from the button on its window; one Codex reset, confirmed on the phone.

Everything here is fake: the app-server (FakeServer), the conversations' records (a temporary state_5.sqlite and
rollout files), the desktop (FakeDesktop). Nothing is asked of the real Codex, so no reset is ever used."""
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archives
import remote
import usage_limits

REQUEST = "reset-request-0001"


# ---------------------------------------------------------------- the app-server, played

class FakeServer:
    """archives.CodexServer as usage_limits uses it: records every call and answers from `answers` (a value or a
    callable per method); a method in `refuse` answers with that error text, one in `errors` raises that exception."""
    calls, answers, refuse, errors = [], {}, {}, {}
    opens = 0

    def __init__(self):
        FakeServer.opens += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        FakeServer.calls.append(("close",))

    def call(self, method, params, timeout=40):
        FakeServer.calls.append((method, params))
        if method in FakeServer.errors:
            raise FakeServer.errors[method]
        if method in FakeServer.refuse:
            raise archives.CodexRefused(FakeServer.refuse[method])
        answer = FakeServer.answers.get(method)
        return answer() if callable(answer) else answer

    @classmethod
    def reset(cls):
        cls.calls, cls.answers, cls.refuse, cls.errors = [], {}, {}, {}
        cls.opens = 0


def live_reply(**changes):
    """account/rateLimits/read as 11-17 answered on this computer (a fake accountId); `changes` replaces top keys."""
    reply = {
        "rateLimitsByLimitId": {"codex": {
            "limitId": "codex", "limitName": None, "planType": "pro",
            "primary": {"usedPercent": 84.0, "windowDurationMins": 10080, "resetsAt": 1795006481},
            "secondary": None,
            "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
            "rateLimitReachedType": None}},
        "rateLimitResetCredits": {"availableCount": 1, "credits": [
            {"id": "credit-available", "title": "Full reset",
             "description": "Thanks for using Codex! You've been granted one free rate limit reset.",
             "grantedAt": 1794000000, "expiresAt": 1797000000, "status": "available", "resetType": "full"},
            {"id": "credit-redeemed", "title": "An old one", "description": "gone",
             "grantedAt": 1790000000, "expiresAt": None, "status": "redeemed", "resetType": "full"}]},
        "ordinaryUsageAllowed": True,
        "accountId": "account-secret-not-for-the-phone",
    }
    reply.update(changes)
    return reply


class Clock:
    """time.monotonic, moved by the test instead of by the clock."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t


class FakeDesktop:
    """chats.Desktop as usage_limits uses it: run() works on the calling thread and plays Windows' own part;
    `run_error` stands for its timeout."""
    def __init__(self, buttons=(), run_error=None, hwnd=1234, iconic=False):
        self.buttons = list(buttons)
        self.run_error = run_error
        self.hwnd = hwnd
        self.iconic = iconic
        self.ran = []

    def run(self, fn, *args, timeout=None):
        self.ran.append((fn, args, timeout))
        if self.run_error is not None:
            raise self.run_error
        with patch("chats.app_window", return_value=self.hwnd), \
             patch("usage_limits.win32gui.IsIconic", return_value=self.iconic):
            return fn(*args)

    def _need_auto(self):
        return SimpleNamespace(ControlFromHandle=lambda hwnd: "root")

    def _find(self, scope, kind, name=None):
        return self.buttons


# ---------------------------------------------------------------- the conversations' records, played

def threads_db(path, rows):
    """Codex's own thread table, only what codex_records reads: the rollout file and when it last moved."""
    con = sqlite3.connect(path)
    con.execute("create table threads(id text, rollout_path text, updated_at_ms integer)")
    con.executemany("insert into threads values(?,?,?)", rows)
    con.commit()
    con.close()


def token_count(stamp, used=84.0, minutes=10080, resets=1795006481, limit_id="codex", secondary=None, plan="pro"):
    """One line of a rollout file: what Codex writes after each of its answers."""
    return json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {
        "type": "token_count", "rate_limits": {
            "limit_id": limit_id, "limit_name": None,
            "primary": {"used_percent": used, "window_minutes": minutes, "resets_at": resets},
            "secondary": secondary, "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
            "plan_type": plan, "rate_limit_reached_type": None}}}, ensure_ascii=False) + "\n"


def ms(stamp):
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000)


class RecordTests(unittest.TestCase):
    """codex_records: the newest token_count of the conversations Codex last worked on (no network, no login)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.db = self.dir / "state_5.sqlite"
        self.patcher = patch("chats.codex_db", return_value=self.db)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def rollout(self, name, lines):
        path = self.dir / name
        path.write_text("".join(lines), encoding="utf-8")
        return str(path)

    def test_the_newest_token_count_wins_across_conversations(self):
        a = self.rollout("a.jsonl", [token_count("2026-11-17T01:00:00Z", used=50),
                                     token_count("2026-11-17T02:22:02.354Z", used=84)])
        b = self.rollout("b.jsonl", [token_count("2026-11-17T03:00:00Z", used=90)])
        threads_db(self.db, [("t-a", a, 3000), ("t-b", b, 2000)])
        got = usage_limits.codex_records()
        self.assertEqual(90, got["windows"][0]["used_percent"])
        self.assertEqual("records", got["source"])
        self.assertEqual(ms("2026-11-17T03:00:00Z"), got["as_of"])
        self.assertEqual("pro", got["plan"])
        self.assertIsNone(got["resets"])
        self.assertIsNone(got["reached"])
        self.assertIsNone(got["ordinary_usage_allowed"])

    def test_the_newest_line_of_one_conversation_wins(self):
        a = self.rollout("a.jsonl", [token_count("2026-11-17T01:00:00Z", used=50),
                                     token_count("2026-11-17T02:22:02.354Z", used=84)])
        threads_db(self.db, [("t-a", a, 3000)])
        got = usage_limits.codex_records()
        self.assertEqual(84, got["windows"][0]["used_percent"])
        self.assertEqual(ms("2026-11-17T02:22:02.354Z"), got["as_of"])
        self.assertEqual({"kind": "weekly", "minutes": 10080, "used_percent": 84,
                          "resets_at": 1795006481, "name": "每周"}, got["windows"][0])

    def test_another_limit_id_and_a_null_rate_limits_are_skipped(self):
        a = self.rollout("a.jsonl", [
            token_count("2026-11-17T01:00:00Z", used=77),
            token_count("2026-11-17T02:00:00Z", used=5, limit_id="other_bucket"),
            json.dumps({"timestamp": "2026-11-17T03:00:00Z", "type": "event_msg",
                        "payload": {"type": "token_count", "rate_limits": None}}) + "\n"])
        threads_db(self.db, [("t-a", a, 3000)])
        self.assertEqual(77, usage_limits.codex_records()["windows"][0]["used_percent"])

    def test_a_secondary_five_hour_window(self):
        a = self.rollout("a.jsonl", [token_count("2026-11-17T01:00:00Z", used=20, minutes=300,
                                                 secondary={"used_percent": 84, "window_minutes": 10080,
                                                            "resets_at": 1795006481})])
        threads_db(self.db, [("t-a", a, 3000)])
        got = usage_limits.codex_records()
        self.assertEqual(["5h", "weekly"], [w["kind"] for w in got["windows"]])
        self.assertEqual(["5 小时", "每周"], [w["name"] for w in got["windows"]])
        self.assertEqual(20, got["windows"][0]["used_percent"])

    def test_a_half_last_line_and_a_file_over_512_kb_are_read_from_the_tail(self):
        filler = "".join(json.dumps({"type": "event_msg", "payload": {"type": "other", "i": i}}) + "\n"
                         for i in range(12000))
        self.assertGreater(len(filler), 512 * 1024)
        a = self.rollout("a.jsonl", [token_count("2026-11-17T00:00:00Z", used=11), filler,
                                     token_count("2026-11-17T02:00:00Z", used=66),
                                     '{"timestamp":"2026-11-17T09:00:00Z","type":"event_m'])
        threads_db(self.db, [("t-a", a, 3000)])
        got = usage_limits.codex_records()
        self.assertEqual(66, got["windows"][0]["used_percent"])
        self.assertEqual(ms("2026-11-17T02:00:00Z"), got["as_of"])

    def test_a_line_older_than_the_tail_is_not_used(self):
        filler = "".join(json.dumps({"type": "event_msg", "payload": {"type": "other", "i": i}}) + "\n"
                         for i in range(12000))
        a = self.rollout("a.jsonl", [token_count("2026-11-17T00:00:00Z", used=11), filler])
        threads_db(self.db, [("t-a", a, 3000)])
        self.assertIsNone(usage_limits.codex_records())

    def test_no_conversation_with_usage_is_none(self):
        a = self.rollout("a.jsonl", [json.dumps({"type": "event_msg", "payload": {"type": "agent_message"}}) + "\n"])
        threads_db(self.db, [("t-a", a, 3000)])
        self.assertIsNone(usage_limits.codex_records())

    def test_an_unreadable_thread_table_is_none(self):
        self.db.write_text("not a database", encoding="utf-8")
        self.assertIsNone(usage_limits.codex_records())

    def test_the_table_without_updated_at_ms_orders_by_updated_at(self):
        con = sqlite3.connect(self.db)
        con.execute("create table threads(id text, rollout_path text, updated_at integer)")
        a = self.rollout("a.jsonl", [token_count("2026-11-17T01:00:00Z", used=42)])
        con.execute("insert into threads values(?,?,?)", ("t-a", a, 5))
        con.commit()
        con.close()
        self.assertEqual(42, usage_limits.codex_records()["windows"][0]["used_percent"])


class WindowTests(unittest.TestCase):
    """The window format the two apps share (3.1 item 4)."""

    def test_kinds_names_and_minutes(self):
        window = usage_limits.usage_window
        self.assertEqual(("5h", "5 小时"), (window(300, 10, None)["kind"], window(300, 10, None)["name"]))
        self.assertEqual(("weekly", "每周"), (window(10080, 10, None)["kind"], window(10080, 10, None)["name"]))
        self.assertEqual(("other", "1 天"), (window(1440, 10, None)["kind"], window(1440, 10, None)["name"]))
        self.assertEqual(("other", "3 天"), (window(4320, 10, None)["kind"], window(4320, 10, None)["name"]))
        self.assertEqual(("other", "2 小时"), (window(120, 10, None)["kind"], window(120, 10, None)["name"]))

    def test_used_percent_is_rounded_and_kept_within_0_and_100(self):
        window = usage_limits.usage_window
        self.assertEqual(84, window(10080, 83.6, None)["used_percent"])
        self.assertEqual(0, window(10080, -1, None)["used_percent"])
        self.assertEqual(100, window(10080, 130, None)["used_percent"])


class LiveTests(unittest.TestCase):
    """codex_live: one question to a Codex app-server of our own, closed again."""

    def setUp(self):
        FakeServer.reset()
        FakeServer.answers["account/rateLimits/read"] = live_reply()

    def test_what_the_phone_shows_and_what_it_never_gets(self):
        got = usage_limits.codex_live(FakeServer)
        self.assertEqual("live", got["source"])
        self.assertEqual("pro", got["plan"])
        self.assertEqual({"kind": "weekly", "minutes": 10080, "used_percent": 84,
                          "resets_at": 1795006481, "name": "每周"}, got["windows"][0])
        self.assertIsNone(got["reached"])
        self.assertIs(got["ordinary_usage_allowed"], True)
        self.assertNotIn("account-secret-not-for-the-phone", json.dumps(got))
        self.assertNotIn("accountId", json.dumps(got))
        self.assertEqual(1, got["resets"]["available"])
        self.assertEqual([{"id": "credit-available", "title": "Full reset",
                           "description": "Thanks for using Codex! You've been granted one free rate limit reset.",
                           "granted_at": 1794000000, "expires_at": 1797000000}], got["resets"]["items"])
        self.assertEqual("account/rateLimits/read", FakeServer.calls[0][0])
        self.assertEqual({"excludeResetCreditDetails": False}, FakeServer.calls[0][1])
        self.assertEqual(("close",), FakeServer.calls[-1])

    def test_credits_null_means_items_null_and_no_credits_means_no_resets(self):
        FakeServer.answers["account/rateLimits/read"] = live_reply(
            rateLimitResetCredits={"availableCount": 2, "credits": None})
        self.assertIsNone(usage_limits.codex_live(FakeServer)["resets"]["items"])
        FakeServer.answers["account/rateLimits/read"] = live_reply(rateLimitResetCredits=None)
        self.assertIsNone(usage_limits.codex_live(FakeServer)["resets"])

    def test_the_single_bucket_shape_works_too(self):
        reply = live_reply()
        reply["rateLimits"] = reply.pop("rateLimitsByLimitId")["codex"]
        FakeServer.answers["account/rateLimits/read"] = reply
        self.assertEqual(84, usage_limits.codex_live(FakeServer)["windows"][0]["used_percent"])

    def test_a_server_that_cannot_start_says_codex_is_unreachable(self):
        def refuse_to_start():
            raise archives.ArchiveError("没找到这台电脑上的 Codex", 503)
        with self.assertRaises(usage_limits.UsageError) as caught:
            usage_limits.codex_live(refuse_to_start)
        self.assertEqual((409, "codex_unreachable"), (caught.exception.status, caught.exception.code))
        self.assertEqual("读不到 Codex 的实时用量：没找到这台电脑上的 Codex", str(caught.exception))

    def test_a_codex_that_refuses_says_so_in_its_own_words(self):
        FakeServer.refuse["account/rateLimits/read"] = "unknown method: account/rateLimits/read"
        with self.assertRaises(usage_limits.UsageError) as caught:
            usage_limits.codex_live(FakeServer)
        self.assertEqual((409, "codex_refused"), (caught.exception.status, caught.exception.code))
        self.assertEqual("Codex 没给用量：unknown method: account/rateLimits/read", str(caught.exception))


class UsageReadTests(unittest.TestCase):
    """Usage.read: what the phone sees, the 30-second live cache, and falling back to the records."""

    def setUp(self):
        FakeServer.reset()
        FakeServer.answers["account/rateLimits/read"] = live_reply()
        self.logs = []
        self.records = Mock(return_value={"source": "records", "as_of": 1794882122354, "plan": "pro",
                                          "windows": [{"kind": "weekly", "minutes": 10080, "used_percent": 84,
                                                       "resets_at": 1795006481, "name": "每周"}],
                                          "reached": None, "resets": None, "ordinary_usage_allowed": None})
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def usage(self, apps=("codex", "claude"), **changes):
        options = dict(desktop=None, log=self.logs.append, apps=lambda: list(apps),
                       server_factory=FakeServer, records=self.records, data_dir=Path(self.temp.name))
        options.update(changes)
        return usage_limits.Usage(**options)

    @property
    def desktop(self):
        return FakeDesktop(buttons=[SimpleNamespace(Name="Usage: 35% of 5-hour limit, Resets at 12:20 PM")])

    def test_live_then_the_cache_for_thirty_seconds(self):
        clock = Clock()
        usage = self.usage()
        with patch("usage_limits.time.monotonic", clock):
            first = usage.read(True)["codex"]
            self.assertEqual(1, FakeServer.opens)
            clock.t += 29
            usage.read(True)
            self.assertEqual(1, FakeServer.opens)
            clock.t += 2
            usage.read(True)
            self.assertEqual(2, FakeServer.opens)
        self.assertEqual("live", first["source"])

    def test_a_live_read_that_fails_falls_back_to_the_records_with_its_reason(self):
        FakeServer.errors["account/rateLimits/read"] = archives.ArchiveError("Codex 后台进程意外退出了", 503)
        got = self.usage().read(True)["codex"]
        self.assertEqual("records", got["source"])
        self.assertTrue(got["available"])
        self.assertEqual("读不到 Codex 的实时用量：Codex 后台进程意外退出了", got["live_error"])
        self.assertEqual(["用量：读不到 Codex 的实时用量（codex_unreachable）"], self.logs)

    def test_a_refusal_is_logged_once_per_ten_minutes(self):
        FakeServer.refuse["account/rateLimits/read"] = "no such method"
        clock = Clock()
        usage = self.usage()
        with patch("usage_limits.time.monotonic", clock):
            for _ in range(3):
                usage.read(True)
                clock.t += 60
        self.assertEqual(["用量：读不到 Codex 的实时用量（codex_refused）"], self.logs)

    def test_neither_live_nor_records_says_there_is_no_usage_yet(self):
        FakeServer.errors["account/rateLimits/read"] = archives.ArchiveError("Codex 后台进程意外退出了", 503)
        self.records.return_value = None
        got = self.usage().read(True)["codex"]
        self.assertFalse(got["available"])
        self.assertEqual("电脑上还没有 Codex 的用量记录（用一次 Codex 就会有）", got["reason"])

    def test_a_read_without_live_uses_the_records(self):
        got = self.usage().read(False)["codex"]
        self.assertEqual("records", got["source"])
        self.assertEqual(0, FakeServer.opens)

    def test_a_computer_without_an_app_says_so(self):
        got = self.usage(apps=()).read(True)
        self.assertFalse(got["codex"]["available"])
        self.assertEqual("这台电脑没装 Codex", got["codex"]["reason"])
        self.assertEqual("这台电脑没装 Claude", got["claude"]["reason"])

    def test_claude_comes_from_its_window_and_a_timeout_says_so(self):
        got = self.usage(desktop=self.desktop).read(True)["claude"]
        self.assertEqual(35, got["windows"][0]["used_percent"])
        self.assertEqual("12:20", got["windows"][0]["resets_text"])
        self.assertIs(got["minimized"], False)
        timeout = self.usage(desktop=FakeDesktop(run_error=TimeoutError()))
        self.assertEqual("这会儿读不到 Claude 窗口，请稍后再试", timeout.read(True)["claude"]["reason"])

    def test_now_is_given_so_the_phone_need_not_trust_its_own_clock(self):
        got = self.usage().read(True)
        self.assertIsInstance(got["now"], int)
        self.assertGreater(got["now"], 1_700_000_000_000)


class RedeemTests(unittest.TestCase):
    """codex_redeem / Usage.redeem: one reset, only after the phone said so, retried with the same request id."""

    def setUp(self):
        FakeServer.reset()
        FakeServer.answers["account/rateLimitResetCredit/consume"] = {"outcome": "reset"}
        FakeServer.answers["account/rateLimits/read"] = live_reply()
        self.logs = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.records = Mock(return_value=None)

    def usage(self, apps=("codex", "claude"), **changes):
        options = dict(desktop=None, log=self.logs.append, apps=lambda: list(apps),
                       server_factory=FakeServer, records=self.records, data_dir=self.data)
        options.update(changes)
        return usage_limits.Usage(**options)

    def lines(self):
        path = self.data / "attachments" / "codex-resets.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_each_outcome_says_its_words_and_sends_the_request_id(self):
        expected = {"reset": "已用掉 1 次重置，Codex 用量恢复了",
                    "nothingToReset": "现在没有能重置的限额，这次没用掉",
                    "noCredit": "没有可用的重置次数，这次没用掉",
                    "alreadyRedeemed": "这次之前已经用成了，没有再用掉一次"}
        for outcome, text in expected.items():
            with self.subTest(outcome=outcome):
                FakeServer.calls = []
                FakeServer.answers["account/rateLimitResetCredit/consume"] = {"outcome": outcome}
                got = self.usage().redeem({"confirmed": True, "request_id": f"request-{outcome}",
                                           "credit_id": "credit-available"})
                self.assertTrue(got["ok"])
                self.assertEqual(outcome, got["outcome"])
                self.assertEqual(text, got["text"])
                self.assertEqual(
                    [("account/rateLimitResetCredit/consume",
                      {"idempotencyKey": f"request-{outcome}", "creditId": "credit-available"}),
                     ("account/rateLimits/read", {"excludeResetCreditDetails": False}), ("close",)],
                    FakeServer.calls)
                self.assertEqual("live", got["usage"]["source"])

    def test_no_credit_id_means_no_credit_id_in_the_call(self):
        got = self.usage().redeem({"confirmed": True, "request_id": "plain-request-1"})
        self.assertEqual({"idempotencyKey": "plain-request-1"},
                         [call for call in FakeServer.calls
                          if call[0] == "account/rateLimitResetCredit/consume"][0][1])
        self.assertEqual("已用掉 1 次重置，Codex 用量恢复了", got["text"])

    def test_two_record_lines_and_a_log_line_without_the_whole_request_id(self):
        self.usage().redeem({"confirmed": True, "request_id": REQUEST, "credit_id": "credit-available"})
        lines = self.lines()
        self.assertEqual(2, len(lines))
        self.assertEqual(("sending", REQUEST), (lines[0]["stage"], lines[0]["request_id"]))
        self.assertEqual("reset", lines[1]["outcome"])
        self.assertEqual(["Codex 重置：手机请求 reset-re → reset；之后可用 1 次"], self.logs)
        for word in (REQUEST, "credit-available", "Full reset"):
            self.assertNotIn(word, self.logs[0])

    def test_a_request_that_already_has_its_answer_is_not_sent_again(self):
        self.usage().redeem({"confirmed": True, "request_id": REQUEST})
        FakeServer.calls, FakeServer.opens = [], 0
        got = self.usage().redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual("reset", got["outcome"])
        self.assertEqual("已用掉 1 次重置，Codex 用量恢复了", got["text"])
        self.assertEqual(0, FakeServer.opens)
        self.assertEqual([], FakeServer.calls)

    def test_an_unanswered_reset_keeps_the_same_request_id_and_may_have_worked(self):
        FakeServer.errors["account/rateLimitResetCredit/consume"] = archives.ArchiveError(
            "Codex 没在 30 秒内答复，结果未确认；刷新列表看看", 504)
        with self.assertRaises(usage_limits.UsageError) as caught:
            self.usage().redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual((409, "reset_unconfirmed"), (caught.exception.status, caught.exception.code))
        self.assertEqual("没确认这次用成了没有。再点一次会用同一个编号重试，不会多用掉一次。", str(caught.exception))
        self.assertEqual("unconfirmed", self.lines()[-1]["stage"])
        self.assertEqual(["Codex 重置：手机请求 reset-re 没确认结果（ArchiveError）"], self.logs)
        # The same request id again: the app-server says the first try went through after all.
        FakeServer.errors = {}
        FakeServer.answers["account/rateLimitResetCredit/consume"] = {"outcome": "alreadyRedeemed"}
        got = self.usage().redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual("这次之前已经用成了，没有再用掉一次", got["text"])

    def test_a_server_that_cannot_start_uses_nothing_and_records_nothing(self):
        def refuse_to_start():
            raise archives.ArchiveError("没找到这台电脑上的 Codex", 503)
        with self.assertRaises(usage_limits.UsageError) as caught:
            self.usage(server_factory=refuse_to_start).redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual((409, "codex_unreachable"), (caught.exception.status, caught.exception.code))
        self.assertEqual("没用掉：连不上电脑上的 Codex（没找到这台电脑上的 Codex）", str(caught.exception))
        self.assertFalse((self.data / "attachments" / "codex-resets.jsonl").exists())

    def test_the_phone_has_to_say_yes_first(self):
        usage = self.usage()
        for body in ({}, {"confirmed": "true"}, {"confirmed": 1}, {"request_id": REQUEST}):
            with self.subTest(body=body), self.assertRaises(usage_limits.UsageError) as caught:
                usage.redeem(body)
            self.assertEqual((400, "not_confirmed"), (caught.exception.status, caught.exception.code))
            self.assertEqual("要先在手机上确认", str(caught.exception))
        self.assertEqual(0, FakeServer.opens)

    def test_a_request_id_that_is_short_or_odd_is_refused(self):
        usage = self.usage()
        for bad in ("short", "with space in it", "有中文的编号", "x" * 65, "", None, 12345678):
            with self.subTest(bad=bad), self.assertRaises(usage_limits.UsageError) as caught:
                usage.redeem({"confirmed": True, "request_id": bad})
            self.assertEqual((400, "bad_request"), (caught.exception.status, caught.exception.code))
            self.assertEqual("请求编号不对", str(caught.exception))
        self.assertEqual(0, FakeServer.opens)

    def test_a_reset_on_a_computer_without_codex_is_refused(self):
        with self.assertRaises(usage_limits.UsageError) as caught:
            self.usage(apps=("claude",)).redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual((409, "no_codex"), (caught.exception.status, caught.exception.code))
        self.assertEqual("这台电脑没装 Codex", str(caught.exception))

    def test_a_refusal_from_codex_says_its_words(self):
        FakeServer.refuse["account/rateLimitResetCredit/consume"] = "no available reset credit"
        with self.assertRaises(usage_limits.UsageError) as caught:
            self.usage().redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual((409, "codex_refused"), (caught.exception.status, caught.exception.code))
        self.assertEqual("Codex 没让用：no available reset credit", str(caught.exception))

    def test_an_outcome_nobody_knows_is_shown_as_it_came(self):
        FakeServer.answers["account/rateLimitResetCredit/consume"] = {"outcome": "someNewOutcome"}
        got = self.usage().redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual("Codex 回了不认识的结果（someNewOutcome），请到电脑上的 Codex 里看用量", got["text"])

    def test_the_new_usage_replaces_the_cached_one(self):
        usage = self.usage()
        self.assertEqual(84, usage.read(True)["codex"]["windows"][0]["used_percent"])
        after = live_reply()
        after["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 0
        FakeServer.answers["account/rateLimits/read"] = after
        usage.redeem({"confirmed": True, "request_id": REQUEST})
        self.assertEqual(0, usage.read(True)["codex"]["windows"][0]["used_percent"])


class ClaudeTextTests(unittest.TestCase):
    """The words on the button beside Claude's model, parsed (pure, no window)."""

    def test_the_five_hour_limit_with_its_reset_time(self):
        got = usage_limits.claude_text("Usage: 35% of 5-hour limit, Resets at 12:20 PM")
        self.assertEqual([{"kind": "5h", "label": "5-hour limit", "name": "5 小时", "used_percent": 35,
                           "resets_at": None, "resets_text": "12:20"}], got["windows"])

    def test_a_weekly_limit_with_another_reset_spelling(self):
        got = usage_limits.claude_text("Usage: Weekly · all models: 85%, Resets Fri 3:00 PM")
        self.assertEqual([{"kind": "weekly", "label": "Weekly · all models", "name": "每周（全部模型）",
                           "used_percent": 85, "resets_at": None, "resets_text": "Fri 3:00 PM"}], got["windows"])

    def test_a_weekly_limit_for_one_model_and_no_reset_time(self):
        got = usage_limits.claude_text("Usage: Weekly · Fable: 3%")
        self.assertEqual([{"kind": "weekly", "label": "Weekly · Fable", "name": "每周（Fable）",
                           "used_percent": 3, "resets_at": None}], got["windows"])

    def test_midnight_and_morning_are_twenty_four_hours(self):
        self.assertEqual("00:05", usage_limits.claude_text(
            "Usage: 9% of 5-hour limit, Resets at 12:05 AM")["windows"][0]["resets_text"])
        self.assertEqual("09:05", usage_limits.claude_text(
            "Usage: 9% of 5-hour limit, Resets at 9:05 AM")["windows"][0]["resets_text"])

    def test_words_it_does_not_know_leave_the_windows_empty_and_the_text_whole(self):
        for name in ("Plan usage unavailable", "Usage: something new", "Usage: ", "Usage: 5%"):
            with self.subTest(name=name):
                got = usage_limits.claude_text(name)
                self.assertEqual([], got["windows"])
                self.assertEqual(name, got["text"])


class ClaudeWindowTests(unittest.TestCase):
    """claude_window: read from Claude's window, never touched."""

    def setUp(self):
        self.button = SimpleNamespace(Name="Usage: 35% of 5-hour limit, Resets at 12:20 PM")

    def window(self, desktop):
        with patch("chats.app_window", return_value=desktop.hwnd), \
             patch("usage_limits.win32gui.IsIconic", return_value=desktop.iconic), \
             patch("chats.win32gui.ShowWindow") as show, \
             patch("chats.win32gui.SetWindowPos") as place, \
             patch("chats.winctl.focus") as focus:
            got = usage_limits.claude_window(desktop)
        show.assert_not_called()
        place.assert_not_called()
        focus.assert_not_called()
        return got

    def test_a_window_with_the_usage_button(self):
        got = self.window(FakeDesktop(buttons=[self.button]))
        self.assertTrue(got["available"])
        self.assertEqual("window", got["source"])
        self.assertEqual("Usage: 35% of 5-hour limit, Resets at 12:20 PM", got["text"])
        self.assertEqual(35, got["windows"][0]["used_percent"])
        self.assertIs(got["minimized"], False)
        self.assertIsInstance(got["as_of"], int)

    def test_a_minimised_window_is_only_said_to_be_minimised(self):
        got = self.window(FakeDesktop(buttons=[self.button], iconic=True))
        self.assertIs(got["minimized"], True)
        self.assertTrue(got["available"])

    def test_no_claude_window_says_so(self):
        self.assertEqual({"available": False, "reason": "电脑上 Claude 没开"},
                         self.window(FakeDesktop(buttons=[self.button], hwnd=0)))

    def test_a_window_without_the_button_says_what_to_open(self):
        self.assertEqual({"available": False, "reason": "Claude 窗口上没有用量（要开着一个 Code 对话）"},
                         self.window(FakeDesktop(buttons=[SimpleNamespace(Name="Plan usage unavailable")])))

    def test_a_window_that_cannot_be_read_at_all_is_not_an_error_on_the_phone(self):
        class Broken(FakeDesktop):
            def _find(self, scope, kind, name=None):
                raise OSError("the window went away")
        self.assertEqual({"available": False, "reason": "这会儿读不到 Claude 窗口，请稍后再试"},
                         self.window(Broken()))


class RemoteRouteTests(unittest.TestCase):
    """remote.py: GET /api/usage and POST /api/usage/codex-reset, and never a 503."""

    def get(self, path, read):
        handler = object.__new__(remote.Handler)
        handler.path = path
        handler._authorized = lambda: True
        handler.server = SimpleNamespace(usage=SimpleNamespace(read=read), log=SimpleNamespace(write=lambda text: None))
        answers = []
        handler._json = lambda body, code=200: answers.append((body, code))
        handler._get()
        return answers

    def post(self, path, body, redeem):
        handler = object.__new__(remote.Handler)
        handler.path = path
        handler._authorized = lambda: True
        handler._body = lambda: body
        handler.server = SimpleNamespace(usage=SimpleNamespace(read=Mock(), redeem=redeem),
                                         log=SimpleNamespace(write=lambda text: None))
        answers = []
        handler._json = lambda obj, code=200: answers.append((obj, code))
        handler._post()
        return answers

    def test_the_usage_route_asks_for_a_live_read_only_when_asked(self):
        read = Mock(return_value={"codex": {"available": True}, "claude": {"available": False}, "now": 1})
        self.assertEqual([({"codex": {"available": True}, "claude": {"available": False}, "now": 1}, 200)],
                         self.get("/api/usage?live=1", read))
        read.assert_called_once_with(True)
        read.reset_mock()
        self.get("/api/usage", read)
        read.assert_called_once_with(False)

    def test_a_usage_error_comes_back_with_its_code_and_status(self):
        def read(live):
            raise usage_limits.UsageError("读不到 Codex 的实时用量：没找到这台电脑上的 Codex", 409, "codex_unreachable")
        got = self.get("/api/usage", read)
        self.assertEqual([({"error": "读不到 Codex 的实时用量：没找到这台电脑上的 Codex",
                            "code": "codex_unreachable"}, 409)], got)
        self.assertNotEqual(503, got[0][1])

    def test_a_reset_is_answered_with_the_computers_words(self):
        redeem = Mock(return_value={"ok": True, "outcome": "reset", "text": "已用掉 1 次重置，Codex 用量恢复了",
                                    "usage": None})
        got = self.post("/api/usage/codex-reset", {"confirmed": True, "request_id": REQUEST}, redeem)
        self.assertEqual(({"ok": True, "outcome": "reset", "text": "已用掉 1 次重置，Codex 用量恢复了",
                           "usage": None}, 200), got[0])

    def test_a_reset_error_keeps_its_code_and_its_status(self):
        def redeem(body):
            raise usage_limits.UsageError("没确认这次用成了没有。再点一次会用同一个编号重试，不会多用掉一次。",
                                          409, "reset_unconfirmed")
        body, code = self.post("/api/usage/codex-reset", {"confirmed": True, "request_id": REQUEST}, redeem)[0]
        self.assertEqual(409, code)
        self.assertEqual("reset_unconfirmed", body["code"])
        self.assertEqual(body["error"], body["text"])
        self.assertFalse(body["ok"])

    def test_another_error_is_a_500_and_never_a_503(self):
        def redeem(body):
            raise RuntimeError("boom")
        body, code = self.post("/api/usage/codex-reset", {"confirmed": True, "request_id": REQUEST}, redeem)[0]
        self.assertEqual(500, code)
        self.assertNotEqual(503, code)
        self.assertEqual("电脑端出错，没确认这次用成了没有，请到电脑上的 Codex 里看用量", body["error"])


if __name__ == "__main__":
    unittest.main()
