"""Web UI manifest-driven rendering, generic panel, fallback, and notify-ui link tests (WebKit)."""
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
        ctype = {
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }.get(static_file.suffix, "application/octet-stream")
        route.fulfill(status=200, content_type=ctype, body=static_file.read_bytes())
        return True
    return False


class WebAgentsTests(unittest.TestCase):
    def setUp(self):
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.webkit.launch()
        self.addCleanup(self.browser.close)

    def _new_page(self, router):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route(ORIGIN + "/**", router)
        return page, errors

    def test_testing_agent_renders_generic_style_can_read_send_stop_and_legacy_unaffected(self):
        apps = ["codex", "claude", "deepseek", "testing"]
        manifests = agent_registry.manifests_for(apps, include_testing=True)
        machine = {
            "name": "测试电脑", "apps": apps, "voice": False, "version": "0.27.0-test",
            "agents": manifests, **agent_legacy.page_capabilities(apps),
        }
        testing_status = {"status": "running", "running": True}
        testing_msgs = [
            {"id": "m1", "role": "user", "time": NOW - 50000, "text": "跑一下测试"},
            {"id": "m2", "role": "assistant", "time": NOW - 40000, "text": "正在跑"},
        ]
        seen_calls = []

        def router(route, request):
            u = urlsplit(request.url)
            path, q = u.path, parse_qs(u.query)
            js = lambda obj, status=200: route.fulfill(
                status=status, content_type="application/json; charset=utf-8",
                body=json.dumps(obj, ensure_ascii=False),
            )
            if path == "/":
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(machine))
            if path == "/api/status":
                return js({"ok": True, "ui_version": "0.27.0-test", "protocol": 2})
            if path == "/api/chats":
                app = q.get("app", ["all"])[0]
                rows = [
                    {"app": "codex", "id": "c-1", "title": "Codex 对话", "folder": "proj", "cwd": "C:\\proj",
                     "updated": NOW - 1000, "created": NOW - 10000, "status": "idle", "preview": "ok"},
                    {"app": "testing", "id": "test-running", "title": "测试对话 A", "folder": "demo", "cwd": "C:\\demo",
                     "updated": NOW - 2000, "created": NOW - 20000, "status": testing_status["status"], "preview": "正在跑"},
                ]
                filtered = [r for r in rows if app == "all" or r["app"] == app]
                return js({"items": filtered, "total": len(filtered), "has_more": False, "next_cursor": ""})
            if path == "/api/chat":
                app, cid = q.get("app", [""])[0], q.get("id", [""])[0]
                if app == "testing":
                    return js({
                        "app": "testing", "id": cid, "title": "测试对话 A", "folder": "demo", "cwd": "C:\\demo",
                        "status": testing_status["status"], "size": len(testing_msgs), "note": "",
                        "has_more": False, "next_cursor": "", "runtime": {}, "messages": list(testing_msgs),
                    })
                return js({
                    "app": app, "id": cid, "title": "Codex 对话", "folder": "proj", "cwd": "C:\\proj",
                    "status": "idle", "size": 1, "note": "", "has_more": False, "next_cursor": "",
                    "runtime": {}, "messages": [{"id": "cm1", "role": "assistant", "time": NOW, "text": "Codex 回复"}],
                })
            if path == "/api/chat/projects":
                return js({
                    "now": NOW,
                    "apps": [
                        {"app": "codex", "name": "Codex", "count": 1, "projects": []},
                        {"app": "testing", "name": "测试助手", "count": 1, "projects": []},
                    ],
                })
            if path == "/api/agents/testing/state":
                return js({"available": True, "running": testing_status["running"], "status": testing_status["status"], "turn_id": "t-1"})
            if path == "/api/agents/testing/send":
                body = json.loads(request.post_data or "{}")
                seen_calls.append(("send", request.headers.get("x-teleply-protocol"), body))
                testing_msgs.append({"id": f"m{len(testing_msgs) + 1}", "role": "user", "time": NOW, "text": body["text"]})
                return js({"ok": True, "accepted": True, "request_id": body.get("request_id", ""), "text": "测试助手已接收"})
            if path == "/api/agents/testing/stop":
                body = json.loads(request.post_data or "{}")
                seen_calls.append(("stop", request.headers.get("x-teleply-protocol"), body))
                testing_status["status"] = "idle"
                testing_status["running"] = False
                return js({"ok": True, "text": "测试助手已停止"})
            if path == "/api/codex/state":
                return js({"available": True, "running": False, "status": "idle", "settings": {"model": "gpt-5", "effort": "high", "mode": "default"}, "catalog": {"models": []}, "questions": [], "queued": [], "images": []})
            if path == "/api/events":
                return js({}, 404)
            if path.startswith("/api/"):
                return js({})
            if serve_static(route, path):
                return
            route.fulfill(status=404, body="")

        page, errors = self._new_page(router)
        page.goto(ORIGIN, wait_until="load")
        page.wait_for_function("document.querySelectorAll('#convList .conv').length === 2")

        # Chips generated from manifest in order
        chips = page.evaluate("[...document.querySelectorAll('.conversation-home .chip[data-app]')].map(b => [b.dataset.app, b.textContent])")
        self.assertEqual(chips, [["all", "全部"], ["codex", "Codex"], ["claude", "Claude"], ["deepseek", "DeepSeek"], ["testing", "测试助手"]])

        # Badge uses manifest name and color (#7C3AED -> rgb(124, 58, 237))
        badge_info = page.evaluate("""() => {
            const b = document.querySelector('#convList .conv[data-key="testing:test-running"] .badge');
            return {text: b.textContent, bg: getComputedStyle(b).backgroundColor};
        }""")
        self.assertEqual(badge_info["text"], "测试助手")
        self.assertEqual(badge_info["bg"], "rgb(124, 58, 237)")

        # Sidebar renders generic SVG icon for testing agent
        page.evaluate("openSheet('navSheet'); window.sidebarUI?.load(true);")
        page.wait_for_function("document.querySelectorAll('#navSheet .tree-app').length === 2")
        self.assertTrue(page.evaluate("!!document.querySelector('#navSheet .tree-group[data-key=\"app:testing\"] svg.mark.generic')"))
        page.evaluate("dismissOverlays()")

        # Open testing conversation: generic panel + stop button shown, legacy panels hidden
        page.locator('#convList .conv[data-key="testing:test-running"]').click()
        page.wait_for_function("document.querySelectorAll('#cvMsgs .bub').length === 2")
        stop_btn = page.locator('.cv-top button[aria-label="停止当前轮"]')
        stop_btn.wait_for(state="visible")
        self.assertTrue(page.evaluate("document.getElementById('cvMeta').textContent.startsWith('测试助手')"))
        self.assertTrue(page.evaluate("document.getElementById('codexComposerTools').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('claudeComposerTools').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('deepseekComposerTools').hidden"))
        self.assertFalse(page.evaluate("document.getElementById('genericComposerTools').hidden"))

        # Send through unified /api/agents/testing/send with protocol 2 header
        page.locator("#cvText").fill("网页假助手消息")
        page.locator("#cvBtn").click()
        page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('网页假助手消息')")
        self.assertEqual(seen_calls[0][0], "send")
        self.assertEqual(seen_calls[0][1], "2")
        self.assertEqual(seen_calls[0][2]["text"], "网页假助手消息")

        # Stop through unified /api/agents/testing/stop and verify button hides
        stop_btn.click()
        stop_btn.wait_for(state="hidden")
        self.assertEqual(seen_calls[1][0], "stop")
        self.assertEqual(seen_calls[1][1], "2")

        # Legacy Codex conversation remains unaffected
        page.evaluate("closeConv(true)")
        page.locator('#convList .conv[data-key="codex:c-1"]').click()
        page.wait_for_function("!document.getElementById('codexComposerTools').hidden")
        self.assertTrue(page.evaluate("document.getElementById('genericComposerTools').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('cvMeta').textContent.startsWith('Codex')"))
        self.assertEqual(errors, [])

    def test_unknown_agent_uses_neutral_gray_generic_style_and_never_crashes(self):
        apps = ["codex", "claude", "deepseek"]
        machine = {
            "name": "测试电脑", "apps": apps, "voice": False, "version": "0.27.0-test",
            "agents": agent_registry.manifests_for(apps), **agent_legacy.page_capabilities(apps),
        }

        def router(route, request):
            u = urlsplit(request.url)
            path = u.path
            js = lambda obj, status=200: route.fulfill(
                status=status, content_type="application/json; charset=utf-8",
                body=json.dumps(obj, ensure_ascii=False),
            )
            if path == "/":
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(machine))
            if path == "/api/status":
                return js({"ok": True, "ui_version": "0.27.0-test", "protocol": 2})
            if path == "/api/chats":
                return js({"items": [
                    {"app": "mystery", "id": "m-1", "title": "未知助手对话", "folder": "lab", "cwd": "C:\\lab",
                     "updated": NOW, "created": NOW, "status": "idle", "preview": "来自未知助手"},
                ], "total": 1, "has_more": False, "next_cursor": ""})
            if path == "/api/chat":
                return js({
                    "app": "mystery", "id": "m-1", "title": "未知助手对话", "folder": "lab", "cwd": "C:\\lab",
                    "status": "idle", "size": 1, "note": "", "has_more": False, "next_cursor": "",
                    "runtime": {}, "messages": [{"id": "mm1", "role": "assistant", "time": NOW, "text": "可以正常阅读"}],
                })
            if path == "/api/events":
                return js({}, 404)
            if path.startswith("/api/"):
                return js({})
            if serve_static(route, path):
                return
            route.fulfill(status=404, body="")

        page, errors = self._new_page(router)
        page.goto(ORIGIN, wait_until="load")
        page.wait_for_function("document.querySelectorAll('#convList .conv').length === 1")

        # Unknown app shows its id with neutral gray (#6b7280 -> rgb(107, 114, 128)), never "Claude"
        badge = page.evaluate("""() => {
            const b = document.querySelector('#convList .conv[data-key="mystery:m-1"] .badge');
            return {text: b.textContent, bg: getComputedStyle(b).backgroundColor};
        }""")
        self.assertEqual(badge["text"], "mystery")
        self.assertEqual(badge["bg"], "rgb(107, 114, 128)")

        # Opening unknown conversation reads cleanly, disables send, hides open/stop
        page.locator('#convList .conv[data-key="mystery:m-1"]').click()
        page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('可以正常阅读')")
        self.assertTrue(page.evaluate("document.getElementById('cvMeta').textContent.startsWith('mystery')"))
        page.locator("#cvText").fill("尝试发送")
        self.assertTrue(page.evaluate("document.getElementById('cvBtn').disabled"))
        self.assertTrue(page.evaluate("document.getElementById('convOpenBtn').hidden"))
        self.assertTrue(page.evaluate("document.querySelector('.cv-top button[aria-label=\"停止当前轮\"]').hidden"))
        self.assertEqual(errors, [])

    def test_old_computer_without_agents_manifest_uses_three_legacy_fallback(self):
        # Old computer: MACHINE has apps but no agents array
        machine = {"name": "老电脑", "apps": ["codex", "claude"], "voice": False, "version": "0.27.0-old"}

        def router(route, request):
            path = urlsplit(request.url).path
            js = lambda obj: route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(obj))
            if path == "/":
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(machine))
            if path == "/api/chats":
                return js({"items": [], "total": 0, "has_more": False, "next_cursor": ""})
            if path.startswith("/api/"):
                return js({})
            if serve_static(route, path):
                return
            route.fulfill(status=404, body="")

        page, errors = self._new_page(router)
        page.goto(ORIGIN, wait_until="load")
        page.wait_for_function("!!window.Agents && !!window.newChatUI")
        self.assertTrue(page.evaluate("window.Agents.isFallback()"))
        self.assertEqual(page.evaluate("window.Agents.ids()"), ["codex", "claude"])
        chips = page.evaluate("[...document.querySelectorAll('.conversation-home .chip[data-app]')].map(b => b.dataset.app)")
        self.assertEqual(chips, ["all", "codex", "claude"])
        new_btns = page.evaluate("[...document.querySelectorAll('#newSheet .new-apps button')].map(b => b.id)")
        self.assertEqual(new_btns, ["newCodex", "newClaude"])
        self.assertEqual(errors, [])

    def test_notify_open_link_accepts_deepseek_and_testing_ids(self):
        apps = ["codex", "claude", "deepseek", "testing"]
        machine = {
            "name": "测试电脑", "apps": apps, "voice": False, "version": "0.27.0-test",
            "agents": agent_registry.manifests_for(apps, include_testing=True),
        }
        for app, cid, title in (("deepseek", "ds-1", "DeepSeek 通知对话"), ("testing", "test-running", "测试助手通知对话")):
            with self.subTest(app=app):
                def router(route, request, target_app=app, target_id=cid, target_title=title):
                    u = urlsplit(request.url)
                    path = u.path
                    js = lambda obj: route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(obj, ensure_ascii=False))
                    if path == "/":
                        return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(machine))
                    if path == "/api/chats":
                        return js({"items": [], "total": 0, "has_more": False, "next_cursor": ""})
                    if path == "/api/chat":
                        return js({
                            "app": target_app, "id": target_id, "title": target_title, "folder": "", "cwd": "",
                            "status": "idle", "size": 1, "note": "", "has_more": False, "next_cursor": "",
                            "runtime": {}, "messages": [{"id": "n1", "role": "assistant", "time": NOW, "text": "通知打开成功"}],
                        })
                    if path == "/api/events":
                        return route.fulfill(status=404, body="{}")
                    if path.startswith("/api/"):
                        return js({})
                    if serve_static(route, path):
                        return
                    route.fulfill(status=404, body="")

                page, errors = self._new_page(router)
                page.goto(f"{ORIGIN}/?open={app}:{cid}", wait_until="load")
                page.wait_for_function("document.getElementById('convView').style.display === 'flex'")
                self.assertEqual(page.evaluate("document.getElementById('cvTitle').textContent"), title)
                self.assertEqual(errors, [])

    def test_capability_flags_hide_disabled_controls(self):
        readonly_manifest = {
            "schema": 1, "id": "readonly_bot", "name": {"zh": "只读助手", "en": "ReadOnly"}, "order": 50,
            "color": "#0EA5E9", "color_dark": "#38BDF8", "icon": {"kind": "builtin", "key": "generic"},
            "legacy": False, "min_protocol": 2,
            "capabilities": {
                "list": True, "read": True, "search": False, "open": False, "stop": False,
                "queue": False, "steer": False, "approve": False, "answer": False, "new": False,
                "new_projectless": False, "new_permission": False, "archive": False, "restore": False,
                "delete": False, "usage": False, "waiting": False, "attachments": False, "slash_commands": False,
                "settings": [], "send_modes": [], "statuses": ["running", "idle", "unknown"],
            },
            "params": {"state_timeout_s": 5, "send_timeout_s": 5, "refresh_ms": 2000},
            "ui": {"card_layout": "generic.v1", "waiting_text": "等待处理"},
        }
        machine = {
            "name": "测试电脑", "apps": ["codex", "readonly_bot"], "voice": False, "version": "0.27.0-test",
            "agents": [*agent_registry.manifests_for(["codex"]), readonly_manifest],
        }

        def router(route, request):
            path = urlsplit(request.url).path
            js = lambda obj: route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(obj, ensure_ascii=False))
            if path == "/":
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(machine))
            if path == "/api/chats":
                return js({"items": [
                    {"app": "readonly_bot", "id": "ro-1", "title": "只读对话", "folder": "", "cwd": "",
                     "updated": NOW, "created": NOW, "status": "running", "preview": "只读内容"},
                ], "total": 1, "has_more": False, "next_cursor": ""})
            if path == "/api/chat":
                return js({
                    "app": "readonly_bot", "id": "ro-1", "title": "只读对话", "folder": "", "cwd": "",
                    "status": "running", "size": 1, "note": "", "has_more": False, "next_cursor": "",
                    "runtime": {}, "messages": [{"id": "r1", "role": "assistant", "time": NOW, "text": "只读输出"}],
                })
            if path == "/api/agents/readonly_bot/state":
                return js({"available": True, "running": True, "status": "running"})
            if path == "/api/events":
                return route.fulfill(status=404, body="{}")
            if path.startswith("/api/"):
                return js({})
            if serve_static(route, path):
                return
            route.fulfill(status=404, body="")

        page, errors = self._new_page(router)
        page.goto(ORIGIN, wait_until="load")
        page.wait_for_function("document.querySelectorAll('#convList .conv').length === 1")

        # Not offered in New Chat sheet because capabilities.new == false
        new_ids = page.evaluate("[...document.querySelectorAll('#newSheet .new-apps button')].map(b => b.dataset.app)")
        self.assertEqual(new_ids, ["codex"])

        page.locator('#convList .conv[data-key="readonly_bot:ro-1"]').click()
        page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('只读输出')")
        page.wait_for_timeout(150)
        self.assertTrue(page.evaluate("document.getElementById('genericComposerTools').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('convOpenBtn').hidden"))
        self.assertTrue(page.evaluate("document.querySelector('.cv-top button[aria-label=\"停止当前轮\"]').hidden"))
        page.locator("#cvText").fill("不可发")
        self.assertTrue(page.evaluate("document.getElementById('cvBtn').disabled"))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
