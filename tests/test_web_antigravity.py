"""The web page with Antigravity in the list: it lists, opens and reads, and offers no sending or stopping.

Both engines are checked, as the other web tests do; the three legacy agents' pages keep their look.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import remote  # noqa: E402
from agents import legacy as agent_legacy, registry as agent_registry  # noqa: E402

ORIGIN = "https://teleply.local"
NOW = 1767323050000


def render_page(machine: dict) -> bytes:
    page = remote.stamp_page(remote.PAGE_FILE.read_bytes())
    facts = json.dumps(machine, ensure_ascii=False).replace("<", "\\u003c")
    return page.replace(b"<!--machine-->", f"<script>window.MACHINE={facts};</script>".encode("utf-8"), 1)


def serve_static(route, path: str) -> bool:
    static_file = ROOT / "static" / path.lstrip("/")
    if path != "/" and static_file.is_file():
        ctype = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".png": "image/png", ".svg": "image/svg+xml"}.get(static_file.suffix, "application/octet-stream")
        route.fulfill(status=200, content_type=ctype, body=static_file.read_bytes())
        return True
    return False


class WebAntigravityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.webkit = self.pw.webkit.launch()
        self.addCleanup(self.webkit.close)

    def _router_for(self, state: dict):
        def router(route, request):
            u = urlsplit(request.url)
            path, q = u.path, parse_qs(u.query)
            js = lambda obj, status=200: route.fulfill(
                status=status, content_type="application/json; charset=utf-8",
                body=json.dumps(obj, ensure_ascii=False),
            )
            if path == "/":
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(state))
            if path == "/api/status":
                return js({"ok": True, "ui_version": "0.27.0-test", "protocol": 2})
            if path == "/api/chats":
                app = q.get("app", ["all"])[0]
                rows = [
                    {"app": "codex", "id": "c-1", "title": "Codex 对话", "folder": "proj", "cwd": "C:\\proj",
                     "updated": NOW - 1000, "created": NOW - 10000, "status": "idle", "preview": "ok"},
                    {"app": "antigravity", "id": "ag-1", "title": "Antigravity 对话", "folder": "测试项目",
                     "cwd": "C:\\测试\\项目", "updated": NOW - 2000, "created": NOW - 20000,
                     "status": "idle", "preview": "看完了"},
                ]
                return js({"items": [row for row in rows if app == "all" or row["app"] == app],
                           "total": 2, "has_more": False, "next_cursor": ""})
            if path == "/api/chat":
                app, cid = q.get("app", [""])[0], q.get("id", [""])[0]
                if app == "antigravity":
                    return js({
                        "app": "antigravity", "id": cid, "title": "Antigravity 对话", "folder": "测试项目",
                        "cwd": "C:\\测试\\项目", "status": "idle", "size": 2, "note": "",
                        "has_more": False, "next_cursor": "", "runtime": {},
                        "messages": [
                            {"id": "a1", "role": "user", "time": NOW - 9000, "text": "看看这个文件"},
                            {"id": "a2", "role": "assistant", "time": NOW - 8000, "text": "看完了，没有问题。"},
                            {"id": "a3", "role": "tool", "time": NOW - 7000, "text": "read_file：C:\\测试\\a.txt"},
                        ],
                    })
                return js({
                    "app": app, "id": cid, "title": "Codex 对话", "folder": "proj", "cwd": "C:\\proj",
                    "status": "idle", "size": 1, "note": "", "has_more": False, "next_cursor": "",
                    "runtime": {}, "messages": [{"id": "cm1", "role": "assistant", "time": NOW, "text": "Codex 回复"}],
                })
            if path == "/api/agents/antigravity/state":
                return js({"available": True, "running": False, "status": "idle", "questions": [],
                           "settings": {}, "queued": [], "queue_available": False})
            if path == "/api/codex/state":
                return js({"available": True, "running": False, "status": "idle",
                           "settings": {"model": "gpt-5", "effort": "high", "mode": "default"},
                           "catalog": {"models": []}, "questions": [], "queued": [], "images": []})
            if path == "/api/events":
                return js({}, 404)
            if path.startswith("/api/"):
                return js({})
            if serve_static(route, path):
                return
            route.fulfill(status=404, body="")
        return router

    def test_antigravity_lists_opens_reads_and_never_sends_in_both_engines(self):
        apps = ["codex", "antigravity"]
        manifests = agent_registry.manifests_for(apps)
        machine = {"name": "测试电脑", "apps": apps, "voice": False, "version": "0.27.0-test",
                   "agents": manifests, **agent_legacy.page_capabilities(apps)}
        for engine in ("webkit", "chromium"):
            with self.subTest(engine=engine):
                browser = self.webkit if engine == "webkit" else self.pw.chromium.launch(channel="chrome", headless=True)
                try:
                    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
                    try:
                        page = ctx.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.route(ORIGIN + "/**", self._router_for(machine))
                        page.goto(ORIGIN, wait_until="load")
                        page.wait_for_function("document.querySelectorAll('#convList .conv').length === 2")

                        chips = page.evaluate(
                            "[...document.querySelectorAll('.conversation-home .chip[data-app]')].map(b => b.dataset.app)")
                        self.assertEqual(chips, ["all", "codex", "antigravity"])

                        page.locator('#convList .conv[data-key="antigravity:ag-1"]').click()
                        page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('看完了，没有问题。')")
                        self.assertTrue(page.evaluate("document.getElementById('cvMeta').textContent.startsWith('Antigravity')"))
                        self.assertTrue(page.evaluate("document.getElementById('genericComposerTools').hidden"))
                        self.assertTrue(page.evaluate("document.querySelector('.cv-top button[aria-label=\"停止当前轮\"]').hidden"))
                        page.locator("#cvText").fill("只读助手不能发")
                        self.assertTrue(page.evaluate("document.getElementById('cvBtn').disabled"))

                        page.evaluate("closeConv(true)")
                        page.locator('#convList .conv[data-key="codex:c-1"]').click()
                        page.wait_for_function("!document.getElementById('codexComposerTools').hidden")
                        self.assertTrue(page.evaluate("document.getElementById('genericComposerTools').hidden"))
                        self.assertTrue(page.evaluate("document.getElementById('cvMeta').textContent.startsWith('Codex')"))
                        self.assertEqual(errors, [])
                    finally:
                        ctx.close()
                finally:
                    if engine != "webkit":
                        browser.close()


if __name__ == "__main__":
    unittest.main()
