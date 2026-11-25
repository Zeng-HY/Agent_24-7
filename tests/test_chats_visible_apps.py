"""Protocol 1's /api/chats pages: an assistant an old phone cannot read must not shorten its page.

An old phone sees only the three legacy assistants. The list used to take the newest rows of every assistant
and hide the others afterwards, so its first page could hold fewer rows than it asked for (even none). Now the
hidden ones are left out before the page, its cursor and its total are counted. Protocol 2 is unchanged.

All conversations here are made up; no real records are read.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

import chat_history
import remote

APPS = ["codex", "claude", "deepseek", "antigravity"]  # the four this made-up computer has
OLD_PHONE = ["codex", "claude", "deepseek"]  # what its protocol 1 can read


def row(app: str, ident: str, updated: int) -> dict:
    return {"app": app, "id": ident, "title": f"{app} 的对话 {ident}", "folder": "", "cwd": "",
            "updated": updated, "created": updated, "pinned": False, "status": "idle", "preview": ""}


def rows() -> list[dict]:
    """14 Antigravity conversations newer than 12 Codex ones: the shape that made an old phone's page short."""
    found = [row("antigravity", f"anti-{index}", 3000 + index) for index in range(14)]
    found += [row("codex", f"codex-{index}", 2000 + index) for index in range(12)]
    return found


class HistoryFilterTests(unittest.TestCase):
    """chat_history.conversations: filtering before the page and the total."""

    def history(self, found, stray=None) -> chat_history.History:
        history = chat_history.History()
        history._load = lambda: (list(found), list(stray or []))
        return history

    def test_the_hidden_assistant_is_left_out_before_the_page_and_the_total(self):
        page = self.history(rows()).conversations("all", 5, apps=OLD_PHONE)
        self.assertEqual([v["app"] for v in page["items"]], ["codex"] * 5)
        self.assertEqual(page["total"], 12)
        self.assertTrue(page["has_more"])

    def test_turning_the_pages_finds_every_visible_conversation_once(self):
        history = self.history(rows())
        seen, cursor, pages = [], "", []
        while True:
            page = history.conversations("all", 5, cursor, apps=OLD_PHONE)
            pages.append(len(page["items"]))
            seen += [v["id"] for v in page["items"]]
            self.assertEqual(page["total"], 12)
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        self.assertEqual(pages, [5, 5, 2])
        self.assertEqual(sorted(seen), sorted(f"codex-{index}" for index in range(12)))
        self.assertEqual(len(set(seen)), len(seen))

    def test_without_a_filter_every_assistant_is_still_listed(self):
        page = self.history(rows()).conversations("all", 5)
        self.assertEqual([v["app"] for v in page["items"]], ["antigravity"] * 5)
        self.assertEqual(page["total"], 26)

    def test_search_and_the_ungrouped_row_leave_the_hidden_assistant_out_too(self):
        found = rows()
        found[0]["title"] = "共同的关键字"   # the newest Antigravity row
        found[14]["title"] = "共同的关键字"  # the newest Codex row
        stray = [row("antigravity", "ungrouped-antigravity", 4000)]
        history = self.history(found, stray)
        page = history.conversations("all", 40, query="共同的关键字", apps=OLD_PHONE)
        self.assertEqual([v["app"] for v in page["items"]], ["codex"])
        self.assertEqual(page["total"], 1)
        page = history.conversations("all", 40, apps=OLD_PHONE)
        self.assertEqual(page["total"], 12)
        self.assertNotIn("ungrouped-antigravity", [v["id"] for v in page["items"]])


class RouteTests(unittest.TestCase):
    """remote.py's /api/chats: which assistants reach history.conversations, and what each protocol gets back."""

    def call(self, path: str, protocol: int | None = None, history=None):
        handler = object.__new__(remote.Handler)
        sent = []
        handler.path = path
        handler.headers = {"X-Teleply-Protocol": str(protocol)} if protocol else {}
        handler.close_connection = False
        handler._responded = False
        handler.server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": list(APPS), "voice": False},
            cfg={"token": "secret"},
            tasks=SimpleNamespace(apply_status=lambda items: items),
            history=history or chat_history.History(),
            log=SimpleNamespace(write=lambda _text: None),
        )
        handler._send = lambda code, body, ctype, extra=None: sent.append((code, body))
        handler.do_GET()
        self.assertEqual(len(sent), 1)
        return sent[0][0], json.loads(sent[0][1])

    def history(self) -> chat_history.History:
        history = chat_history.History()
        history._load = lambda: (rows(), [])
        return history

    def test_an_old_phone_gets_a_full_page_and_a_total_of_what_it_can_read(self):
        code, body = self.call("/api/chats?app=all&limit=10&t=secret", history=self.history())
        self.assertEqual(code, 200)
        self.assertEqual([v["app"] for v in body["items"]], ["codex"] * 10)
        self.assertEqual(body["total"], 12)
        self.assertTrue(body["has_more"])

    def test_protocol_two_is_exactly_what_it_was(self):
        history = self.history()
        code, body = self.call("/api/chats?app=all&limit=10&t=secret", protocol=2, history=history)
        self.assertEqual(code, 200)
        expected = history.conversations("all", 10, "", "", "updated", "all", lambda items: items)
        body.pop("now")
        expected.pop("now")
        self.assertEqual(body, expected)
        self.assertEqual(body["total"], 26)


if __name__ == "__main__":
    unittest.main()
