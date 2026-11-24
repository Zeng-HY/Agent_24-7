"""The web page with Antigravity: reading, sending a message to an idle conversation, and phone approvals.

Both engines are checked, as the other web tests do. The app's local service is a fake HTTP server on
127.0.0.1 and `language_server.exe` is replaced, so nothing here touches the real Antigravity.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import machines  # noqa: E402
import remote  # noqa: E402
from agents import antigravity, legacy as agent_legacy, registry as agent_registry  # noqa: E402
import antigravity_fixtures as fake  # noqa: E402

ORIGIN = "https://teleply.local"
NOW = 1767323050000
TRANSCRIPT = [fake.record(1, "USER_INPUT", "USER_EXPLICIT", "看看这个文件"),
              fake.record(2, "PLANNER_RESPONSE", "MODEL", "看完了，没有问题。")]


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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        start = patch.object(machines, "HOME", self.home)
        start.start()
        self.addCleanup(start.stop)

        self.hub = fake.FakeHub(self.home, steps=[])
        self.hub.__enter__()
        self.addCleanup(self.hub.__exit__, None, None, None)
        self.runner = fake.FakeAgentapi()
        patcher = patch.object(antigravity, "_run_language_server", self.runner)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.sent: list[dict] = []
        self.answered: list[dict] = []
        self.folder_queries: list[str] = []
        self.build_scene()
        antigravity.reset()

        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.webkit = self.pw.webkit.launch()
        self.addCleanup(self.webkit.close)

    def build_scene(self, status: str = "CASCADE_RUN_STATUS_IDLE", steps: list[dict] | None = None) -> None:
        fake.write(self.home, [fake.row("a", title="测试对话 A", status=status)], transcripts={"a": TRANSCRIPT})
        self.hub.steps = list(steps or [])
        antigravity.reset()

    def machine(self) -> dict:
        apps = ["codex", "antigravity"]
        return {"name": "测试电脑", "apps": apps, "voice": False, "version": "0.27.0-test",
                "agents": agent_registry.manifests_for(apps), **agent_legacy.page_capabilities(apps)}

    def state_payload(self, conv_id: str) -> dict:
        agent = antigravity.AGENT()
        data = agent.state(conv_id)
        now = agent.capabilities_now(None, conv_id)
        if now:
            merged = dict(agent.manifest()["capabilities"])
            merged.update(now.get("capabilities") or {})
            data["capabilities_now"] = merged
            data["capability_notes"] = now.get("notes") or {}
        return data

    def router(self, route, request):
        u = urlsplit(request.url)
        path, q = u.path, parse_qs(u.query)
        js = lambda obj, status=200: route.fulfill(
            status=status, content_type="application/json; charset=utf-8",
            body=json.dumps(obj, ensure_ascii=False),
        )
        if path == "/":
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(self.machine()))
        if path == "/api/status":
            return js({"ok": True, "ui_version": "0.27.0-test", "protocol": 2})
        if path == "/api/chats":
            agent = antigravity.AGENT()
            rows = agent.catalog(limit=100)["items"]
            app = q.get("app", ["all"])[0]
            return js({"items": [row for row in rows if app == "all" or row["app"] == app],
                       "total": len(rows), "has_more": False, "next_cursor": ""})
        if path == "/api/chat":
            cid = q.get("id", [""])[0]
            return js(antigravity.AGENT().read(cid, limit=100))
        if path == "/api/chat/folders":
            self.folder_queries.append(q.get("app", [""])[0])
            return js({"items": [{"path": str(self.home / "Personal"), "name": "Personal",
                                  "sources": ["Antigravity 项目"]}]})
        if path == "/api/agents/antigravity/state":
            return js(self.state_payload(q.get("id", [""])[0]))
        if path == "/api/agents/antigravity/send":
            body = json.loads(request.post_data or "{}")
            self.sent.append(body)
            try:
                result = antigravity.AGENT().send(body)
            except antigravity.ControlError as exc:
                return js({"error": str(exc)}, exc.status)
            with (fake.data_root(self.home) / "brain" / body["id"] / ".system_generated" / "logs"
                  / "transcript.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(fake.record(9, "USER_INPUT", "USER_EXPLICIT", body["text"]),
                                      ensure_ascii=False) + "\n")
            return js(result)
        if path == "/api/agents/antigravity/answer":
            body = json.loads(request.post_data or "{}")
            self.answered.append(body)
            try:
                return js(antigravity.AGENT().answer(body))
            except antigravity.ControlError as exc:
                return js({"error": str(exc)}, exc.status)
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

    def page_for(self, browser):
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(ORIGIN + "/**", self.router)
        page.goto(ORIGIN, wait_until="load")
        page.wait_for_function("document.querySelectorAll('#convList .conv').length === 1")
        return page, errors

    def engines(self):
        for engine in ("webkit", "chromium"):
            with self.subTest(engine=engine):
                browser = self.webkit if engine == "webkit" else self.pw.chromium.launch(channel="chrome", headless=True)
                try:
                    self.build_scene()
                    self.sent.clear()
                    self.answered.clear()
                    self.runner.calls.clear()
                    yield engine, browser
                finally:
                    if engine != "webkit":
                        browser.close()

    def test_an_idle_conversation_sends_a_message_from_the_page(self):
        for _engine, browser in self.engines():
            self.build_scene(status="CASCADE_RUN_STATUS_IDLE")
            page, errors = self.page_for(browser)
            page.locator('#convList .conv[data-key="antigravity:a"]').click()
            page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('看完了，没有问题。')")
            self.assertFalse(page.evaluate("document.getElementById('genericComposerTools').hidden"))
            self.assertTrue(page.evaluate("document.querySelector('.cv-top button[aria-label=\"停止当前轮\"]').hidden"))

            page.locator("#cvText").fill("手机发来的消息")
            page.locator("#cvBtn").click()
            page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('手机发来的消息')")
            self.assertEqual(self.sent[-1]["id"], "a")
            self.assertEqual(self.sent[-1]["text"], "手机发来的消息")
            self.assertEqual(self.runner.calls, [])
            body = self.hub.calls("SendUserCascadeMessage")[-1]["body"]
            self.assertEqual(body["items"], [{"text": "手机发来的消息"}])
            self.assertEqual(errors, [])

    def test_the_new_sheet_asks_for_antigravity_projects(self):
        for _engine, browser in self.engines():
            page, errors = self.page_for(browser)
            page.evaluate("openNewSheet({app:'antigravity'})")
            page.wait_for_selector("#newSheet", state="visible")
            page.wait_for_function("document.getElementById('newFolderName').textContent === 'Personal'")
            self.assertEqual(self.folder_queries[-1], "antigravity")
            self.assertEqual(errors, [])

    def test_a_running_conversation_takes_a_queued_message(self):
        for _engine, browser in self.engines():
            self.build_scene(status="CASCADE_RUN_STATUS_RUNNING")
            page, errors = self.page_for(browser)
            page.locator('#convList .conv[data-key="antigravity:a"]').click()
            page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('看完了，没有问题。')")
            page.wait_for_function("document.getElementById('cvMeta').textContent.includes('运行中')")

            page.locator("#cvText").fill("现在能发吗")
            page.locator("#cvBtn").click()
            page.wait_for_function("document.getElementById('cvMsgs').textContent.includes('现在能发吗')")
            self.assertEqual(self.sent[-1]["text"], "现在能发吗")
            self.assertEqual(self.runner.calls, [])
            body = self.hub.calls("SendUserCascadeMessage")[-1]["body"]
            self.assertEqual(body["deliveryStrategy"], "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE")
            self.assertEqual(errors, [])

    def test_an_approval_card_is_answered_with_the_fake_service(self):
        for _engine, browser in self.engines():
            self.build_scene(status="CASCADE_RUN_STATUS_RUNNING", steps=[fake.waiting_step()])
            page, errors = self.page_for(browser)
            page.locator('#convList .conv[data-key="antigravity:a"]').click()
            page.wait_for_function("document.querySelectorAll('#cvOpts .gc-wrap .codex-card').length === 1")

            card = page.locator("#cvOpts .gc-wrap .codex-card").first
            self.assertEqual(card.locator(".card-title").evaluate("n => n.firstChild.textContent"),
                             "Antigravity 想运行命令")
            self.assertEqual(card.locator(".gc-detail").text_content(), "npm test")
            self.assertEqual([text.strip() for text in card.locator(".card-actions button").all_text_contents()],
                             ["允许一次", "本对话里这条都允许", "拒绝"])

            card.get_by_role("button", name="允许一次", exact=True).click()
            page.wait_for_function("document.querySelectorAll('#cvOpts .gc-wrap .codex-card').length === 0")
            body = self.hub.calls("HandleCascadeUserInteraction")[-1]["body"]
            self.assertEqual(body["cascadeId"], "a")
            self.assertEqual(body["interaction"], {
                "trajectoryId": "traj-1", "stepIndex": 3,
                "permission": {"allow": True, "scope": "PERMISSION_SCOPE_ONCE"}})
            self.assertEqual(self.answered[-1]["question_id"], "traj-1:3")
            self.assertEqual(self.answered[-1]["answers"], {"decision": ["允许一次"]})
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
