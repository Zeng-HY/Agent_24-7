import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import remote
from chat_history import History, HistoryError


class CompatTests(unittest.TestCase):
    def handler(self, path, apps, protocol=None):
        handler = object.__new__(remote.Handler)
        sent = []
        handler.path = path
        handler.headers = {"X-Teleply-Protocol": str(protocol)} if protocol else {}
        handler.close_connection = False
        handler.server = SimpleNamespace(machine={"name": "公司电脑", "apps": apps, "voice": False},
                                        cfg={"token": "secret"})
        handler._send = lambda code, body, ctype, extra=None: sent.append((code, body))
        return handler, sent

    def test_reads_still_work_when_the_computer_does_not_list_that_app(self):
        # The phone may read a conversation even when `apps` is short: only the list and tree filter by it.
        apps = ["codex", "deepseek"]
        calls = []

        def conversation(*args, **kwargs):
            calls.append("chat"); return {"app": "claude", "messages": []}
        def children(*args, **kwargs):
            calls.append("children"); return {"items": []}
        def page(*args, **kwargs):
            calls.append("page"); return {"items": []}
        def folders(app):
            calls.append("folders"); return []
        def options(app):
            calls.append("options"); return {"models": []}
        def search(app, *args, **kwargs):
            calls.append("search"); return {"items": []}

        expected = {
            "/api/chat?app=claude&id=c&t=secret": "chat",
            "/api/chats/children?app=claude&id=c&t=secret": "children",
            "/api/chat/folders?app=claude&t=secret": "folders",
            "/api/chat/new/options?app=claude&t=secret": "options",
            "/api/composer/references?app=claude&t=secret": "search",
        }
        for path, name in expected.items():
            handler, sent = self.handler(path, apps)
            handler.server.history = SimpleNamespace(conversation=conversation, children=children,
                                                     catalog=lambda: [])
            handler.server.new_chats = SimpleNamespace(folders=folders, options=options)
            handler.server.references = SimpleNamespace(search=search)
            handler.server.deepseek = None
            handler.server.archives = SimpleNamespace(archived=lambda: {"items": [], "apps": [], "deletable": []})
            handler.do_GET()
            self.assertEqual(sent[0][0], 200, path)
            self.assertIn(name if not isinstance(name, tuple) else name[0], calls)

        handler, sent = self.handler("/api/chat/projects?app=claude&key=p&t=secret", apps)
        handler.server.history = SimpleNamespace(catalog=lambda: [], ungrouped=lambda: [])
        with patch.object(remote.chat_projects, "page", side_effect=page):
            handler.do_GET()
        self.assertEqual(sent[0][0], 200)
        self.assertIn("page", calls)

    def test_archive_filter_is_protocol_only_not_the_apps_list(self):
        apps = ["codex", "deepseek"]
        archived = {"items": [{"app": "claude", "id": "c1"}], "apps": ["claude"], "deletable": [], "problems": []}
        handler, sent = self.handler("/api/chat/archived?t=secret", apps)
        handler.server.archives = SimpleNamespace(archived=lambda: dict(archived))
        handler.do_GET()
        self.assertEqual(sent[0][0], 200)
        self.assertEqual([v["app"] for v in json.loads(sent[0][1])["items"]], ["claude"])

    def test_unknown_composer_commands_is_the_old_400(self):
        handler, sent = self.handler("/api/composer/commands?app=other&t=secret", ["codex"])
        handler.do_GET()
        self.assertEqual(sent[0][0], 400)
        self.assertEqual(json.loads(sent[0][1])["error"], "没有这个来源")

    def test_unknown_chat_is_the_old_400(self):
        handler, sent = self.handler("/api/chat?app=other&id=c&t=secret", ["codex"])
        handler.server.history = SimpleNamespace(conversation=Mock(side_effect=HistoryError("不认识的应用 other", 400)))
        handler.do_GET()
        self.assertEqual(sent[0][0], 400)
        self.assertEqual(json.loads(sent[0][1])["error"], "不认识的应用 other")

    def test_children_on_codex_keeps_the_old_400(self):
        with self.assertRaises(HistoryError) as caught:
            History().children("codex", "c")
        self.assertEqual((caught.exception.status, str(caught.exception)), (400, "只有 DeepSeek 对话有子对话"))


if __name__ == "__main__":
    unittest.main()
