"""Web stage A of answer files: images in place, the file strip, reasons and plain links.

Fabricated conversation only: invented names, invented paths, no real account or record is read.
The page is the real remote.html and the real static scripts, served by a fake router.
"""
from __future__ import annotations

import base64
import json
import os
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
import motion_check as fake  # noqa: E402

ORIGIN = "https://teleply.local"
NOW = 1767323050000
BASE = "D:\\TeleplyFixtures\\示例输出"
CONV = "fixture-answer-files"
OLD = "fixture-old-pc"
EMPTY = "fixture-new-no-files"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAMCAYAAABr5z2BAAAAF0lEQVR4nGO4Y2PznxLMMGrAqAHDwwAA2PW+UDw0VJMAAAAASUVORK5CYII="
)


def frow(fid, name, index, view, *, kind="text", ext=None, size=1000, via=("link",), **extra):
    row = {
        "id": fid, "index": index, "name": name, "path": BASE + "\\" + name,
        "kind": kind, "view": view, "ext": ext or name.rsplit(".", 1)[-1].lower(),
        "mime": "application/octet-stream", "size": size, "modified": NOW,
        "state": "current", "v": "v-" + fid, "line": None, "lang": None,
        "via": list(via), "thumb": False,
    }
    row.update(extra)
    return row


FILES = [
    frow("f-chart", "chart.png", 0, "image", kind="image", size=120000, via=("image", "link"),
         w=800, h=600, mime="image/png"),
    frow("f-photo", "photo no size.png", 1, "image", kind="image", size=90000, via=("image",),
         mime="image/png"),
    frow("f-thumb", "thumb-image.png", 2, "image", kind="image", size=70000, via=("image",),
         w=640, h=480, thumb=True, mime="image/png"),
    frow("f-huge", "huge.png", 3, "image", kind="image", size=20 << 20, via=("image",),
         w=4000, h=3000, mime="image/png"),
    frow("f-svg", "diagram.svg", 4, "svg", kind="download", size=5000, via=("image",),
         mime="image/svg+xml"),
    frow("f-pdf", "报告.pdf", 5, "pdf", kind="pdf", size=220000, mime="application/pdf"),
    frow("f-r", "分析.R", 6, "code", kind="text", size=3400, lang="r", line=12),
    frow("f-xlsx", "数据.xlsx", 7, "office", kind="download", size=88000),
    frow("f-a", "附件甲.txt", 8, "text", size=1100, state="updated"),
    frow("f-b", "附件乙.txt", 9, "text", size=1200, state="missing"),
    frow("f-c", "附件丙.txt", 10, "text", size=1300),
    frow("f-d", "附件丁.txt", 11, "text", size=1400),
    frow("f-note", "笔记.txt", 1001, "text", size=900, via=("code",),
         texts=["D:\\TeleplyFixtures\\示例输出\\笔记.txt"]),
    frow("f-csv", "结果.csv", 1002, "table", size=1500, via=("path",),
         texts=["D:\\TeleplyFixtures\\示例输出\\结果.csv"]),
    frow("f-pres1", "presented-one.png", 1003, "image", kind="image", size=30000,
         via=("presented",), mime="image/png"),
    frow("f-pres2", "presented-two.png", 1004, "image", kind="image", size=31000,
         via=("presented",), mime="image/png"),
]

TEXT = """这是一条编造的回答，用来看消息里的文件怎么显示。

![趋势图](<D:/TeleplyFixtures/示例输出/chart.png>)

![无尺寸](<D:/TeleplyFixtures/示例输出/photo no size.png>)

![缩略图](<D:/TeleplyFixtures/示例输出/thumb-image.png>)

![太大](<D:/TeleplyFixtures/示例输出/huge.png>)

![示意图](<D:/TeleplyFixtures/示例输出/diagram.svg>)

[报告](<D:/TeleplyFixtures/示例输出/报告.pdf>)
[R 源码](<D:/TeleplyFixtures/示例输出/分析.R:12>)
[数据表](<D:/TeleplyFixtures/示例输出/数据.xlsx>)
[附件甲](<D:/TeleplyFixtures/示例输出/附件甲.txt>)
[附件乙](<D:/TeleplyFixtures/示例输出/附件乙.txt>)
[附件丙](<D:/TeleplyFixtures/示例输出/附件丙.txt>)
[附件丁](<D:/TeleplyFixtures/示例输出/附件丁.txt>)

[缺失的相对文件](<out/old file.png>)
[网络上的报告](/home/fixture/report.pdf)
[页内目录](#answer-files)
[写信](mailto:fixture@example.com)
[本机一](http://localhost:8123/preview)
[本机二](http://127.0.0.1:8123/preview)
[本机三](http://[::1]:8123/preview)

行内代码路径：`D:\\TeleplyFixtures\\示例输出\\笔记.txt`

正文路径：D:\\TeleplyFixtures\\示例输出\\结果.csv"""

NEW_MESSAGE = {
    "id": "answer-files-message", "role": "assistant", "time": NOW,
    "text": TEXT, "files": FILES,
    "file_notes": [
        {"href": "out/old file.png", "reason": "not_found", "text": "电脑上没找到这个文件"},
        {"href": "/home/fixture/report.pdf", "reason": "not_local",
         "text": "文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘"},
    ],
}

OLD_TEXT = ("旧电脑的回答。\n\n![旧图](<D:/TeleplyFixtures/旧图.png>)\n\n"
            "[旧文件](<D:/TeleplyFixtures/旧文件.txt>)")
OLD_MESSAGE = {"id": "old-message", "role": "assistant", "time": NOW - 5000, "text": OLD_TEXT}
EMPTY_MESSAGE = {"id": "empty-message", "role": "assistant", "time": NOW - 2000, "files": [],
                 "text": "新电脑，这条回答没有文件。\n\n[没有列出的文件](<D:/TeleplyFixtures/空.txt>)"}
OLD_ITEMS = [
    {"id": "old-image", "index": 0, "name": "旧图.png", "kind": "image", "size": 1000,
     "modified": NOW, "state": "current", "path": "D:\\TeleplyFixtures\\旧图.png"},
    {"id": "old-text", "index": 1, "name": "旧文件.txt", "kind": "text", "size": 120,
     "modified": NOW, "state": "current", "path": "D:\\TeleplyFixtures\\旧文件.txt"},
]

META = {f["id"]: {"name": f["name"], "kind": f["kind"], "size": f["size"],
                  "state": f["state"], "updated": False} for f in FILES}
META.update({
    "old-image": {"name": "旧图.png", "kind": "image", "size": 1000},
    "old-text": {"name": "旧文件.txt", "kind": "text", "size": 120},
})
IMAGE_IDS = {f["id"] for f in FILES if f["kind"] == "image"} | {"old-image"}
BODY = {
    "f-note": b"fixture note text\n",
    "f-csv": b"name,value\nfixture,1\n",
    "f-r": b'print("fixture")\n',
    "old-text": b"old fixture\n",
}


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


class AnswerFilesWeb(unittest.TestCase):
    def setUp(self) -> None:
        apps = ["codex"]
        self.machine = {"name": "测试电脑", "apps": apps, "voice": False, "version": "0.27.0-test",
                        "agents": agent_registry.manifests_for(apps),
                        **agent_legacy.page_capabilities(apps)}
        self.chat_files_calls: list[dict] = []
        self.meta_calls: list[str] = []
        self.file_calls: list[str] = []
        self.thumb_calls: list[dict] = []
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.webkit.launch()
        self.addCleanup(self.browser.close)

    def chat(self, cid: str, messages: list[dict]) -> dict:
        return {"app": "codex", "id": cid, "title": "文件预览示例", "folder": "示例项目",
                "cwd": "D:/TeleplyFixtures", "status": "idle", "size": len(messages), "note": "",
                "has_more": False, "next_cursor": "", "runtime": {}, "messages": messages}

    def router(self, route, request):
        u = urlsplit(request.url)
        path, q = u.path, parse_qs(u.query)
        js = lambda obj, status=200: route.fulfill(
            status=status, content_type="application/json; charset=utf-8",
            body=json.dumps(obj, ensure_ascii=False))
        if path == "/":
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=render_page(self.machine))
        if path == "/api/status":
            return js({"ok": True, "ui_version": "0.27.0-test", "protocol": 2})
        if path == "/api/chat/projects":
            return js(fake.fake_tree())
        if path == "/api/chats":
            app = q.get("app", ["all"])[0]
            rows = [
                {"app": "codex", "id": CONV, "title": "文件预览示例", "folder": "示例项目",
                 "cwd": "D:/TeleplyFixtures", "updated": NOW, "created": NOW - 9000,
                 "status": "idle", "preview": "带文件的回答"},
                {"app": "codex", "id": OLD, "title": "旧电脑示例", "folder": "示例项目",
                 "cwd": "D:/TeleplyFixtures", "updated": NOW - 1000, "created": NOW - 9000,
                 "status": "idle", "preview": "没有 files 的回答"},
                {"app": "codex", "id": EMPTY, "title": "空文件列表示例", "folder": "示例项目",
                 "cwd": "D:/TeleplyFixtures", "updated": NOW - 500, "created": NOW - 9000,
                 "status": "idle", "preview": "files 是空的回答"},
            ]
            rows = [r for r in rows if app in ("all", r["app"])]
            return js({"items": rows, "total": len(rows), "has_more": False, "next_cursor": ""})
        if path == "/api/chat":
            cid = q.get("id", [""])[0]
            messages = [OLD_MESSAGE] if cid == OLD else [EMPTY_MESSAGE] if cid == EMPTY else [NEW_MESSAGE]
            return js(self.chat(cid, messages))
        if path == "/api/chat/files":
            self.chat_files_calls.append(q)
            mid = q.get("message", [""])[0]
            return js({"items": OLD_ITEMS if mid == "old-message" else [], "scope": "fixture"})
        if path == "/api/file/meta":
            fid = q.get("file", [""])[0]
            self.meta_calls.append(fid)
            meta = META.get(fid)
            return js(meta) if meta else js({"error": "unknown fixture"}, 404)
        if path == "/api/file/thumb":
            self.thumb_calls.append(q)
            return route.fulfill(status=200, content_type="image/png", body=PNG)
        if path == "/api/file/text":
            fid = q.get("file", [""])[0]
            data = BODY.get(fid)
            if data is None:
                return js({"error": "这个文件不提供文本预览"}, 400)
            text = data.decode("utf-8")
            return js({"text": text, "name": META.get(fid, {}).get("name", fid), "encoding": "utf-8",
                       "truncated": False, "total_size": len(data), "lines": len(text.splitlines()),
                       "lang": None, "line": None})
        if path == "/api/file":
            fid = q.get("file", [""])[0]
            self.file_calls.append(fid)
            data = PNG if fid in IMAGE_IDS else BODY.get(fid)
            if data is None:
                return js({"error": "unknown fixture"}, 404)
            return route.fulfill(status=200, content_type="image/png" if fid in IMAGE_IDS else "text/plain",
                                 body=data)
        if path == "/api/codex/state":
            return js({"available": True, "running": False, "status": "idle", "settings": {},
                       "catalog": {"models": []}, "questions": [], "queued": [], "images": []})
        if path == "/api/claude/state":
            return js({"settings": {}, "available": True, "actions": []})
        if path == "/api/events":
            return js({"error": "fixture"}, 404)
        if path.startswith("/api/"):
            return js({})
        if serve_static(route, path):
            return
        route.fulfill(status=404, body="")

    def open_page(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route(ORIGIN + "/**", self.router)
        page.goto(ORIGIN + "/", wait_until="load")
        page.wait_for_function("!!window.readingUI && document.querySelectorAll('#convList .conv').length === 3")
        return page, errors

    def open_conversation(self, page, cid: str, marker: str):
        if page.locator("#convView").is_visible():
            page.get_by_role("button", name="返回对话列表").click()
        page.locator(f'#convList .conv[data-key="codex:{cid}"]').wait_for(state="visible")
        page.locator(f'#convList .conv[data-key="codex:{cid}"]').click()
        page.wait_for_function("m=>document.querySelector('#cvMsgs')?.innerText.includes(m)", arg=marker)
        page.wait_for_function("document.querySelectorAll('#cvMsgs .bub.assistant').length === 1")
        page.wait_for_function("!!document.querySelector('.reply-text')")

    def close_artifact(self, page):
        page.get_by_role("button", name="返回聊天").click()
        page.locator(".artifact-panel").wait_for(state="detached")
        if page.evaluate("history.state?.filePreview") == "file":
            page.wait_for_function("history.state?.filePreview!=='file'")

    def close_answer_dialog(self, page):
        page.locator(".answer-dialog-close").click()
        page.locator(".answer-dialog[open]").wait_for(state="detached")

    def test_images_strip_links_reasons_and_old_computer(self):
        page, errors = self.open_page()
        self.open_conversation(page, CONV, "这是一条编造的回答")

        # The three images a new computer can draw are in place; the too-large one and the SVG are cards.
        page.wait_for_function("document.querySelectorAll('.msg-image').length === 3")
        page.wait_for_function("document.querySelectorAll('.msg-image.loaded').length === 3")
        self.assertEqual(page.locator(".msg-file-card").count(), 2)
        self.assertTrue(page.locator(".msg-file-card", has_text="huge.png").is_visible())
        self.assertTrue(page.locator(".msg-file-card", has_text="diagram.svg").is_visible())
        self.assertEqual(page.locator(".msg-image img").first.get_attribute("src").split("?")[0], "/api/file")
        chart_query = parse_qs(urlsplit(page.locator(".msg-image img").first.get_attribute("src")).query)
        self.assertEqual(chart_query["file"], ["f-chart"])
        self.assertEqual(chart_query["v"], ["v-f-chart"])
        thumb_src = page.locator(".msg-image").nth(2).locator("img").get_attribute("src")
        self.assertTrue(thumb_src.startswith("/api/file/thumb?"))
        thumb_query = parse_qs(urlsplit(thumb_src).query)
        self.assertEqual(thumb_query["w"], ["640"])
        self.assertEqual(thumb_query["file"], ["f-thumb"])
        self.assertEqual(thumb_query["v"], ["v-f-thumb"])

        # Full bubble width, whole picture in a box no taller than about 360 px; w/h (or 4:3) reserves the place.
        sizing = page.evaluate("""()=>{
          const reply=document.querySelector('.reply-text').getBoundingClientRect();
          const boxes=[...document.querySelectorAll('.msg-image')].map(n=>{
            const r=n.getBoundingClientRect(),img=n.querySelector('img');
            return {width:r.width,height:r.height,aspect:n.style.aspectRatio,max:getComputedStyle(n).maxHeight,
                    fit:getComputedStyle(img).objectFit};
          });
          return {reply:reply.width,boxes};
        }""")
        self.assertLessEqual(abs(sizing["boxes"][0]["width"] - sizing["reply"]), 2)
        self.assertEqual(sizing["boxes"][0]["aspect"].replace(" ", ""), "800/600")
        self.assertEqual(sizing["boxes"][1]["aspect"].replace(" ", ""), "4/3")
        self.assertLessEqual(sizing["boxes"][0]["height"], 361)
        self.assertEqual(sizing["boxes"][0]["max"], "360px")
        self.assertEqual(sizing["boxes"][0]["fit"], "contain")
        shots = os.environ.get("AR_ANSWER_FILES_SHOTS")
        if shots:
            page.locator("#cvMsgs").evaluate("e=>e.scrollTop=0")
            page.screenshot(path=str(Path(shots) / "answer-files-message.png"))

        # Tapping a picture opens the full-screen viewer, not the message menu or the whole-conversation list.
        before = len(self.chat_files_calls)
        page.locator(".msg-image").first.click()
        page.locator(".image-viewer").wait_for(state="visible")
        self.assertEqual(page.locator(".viewer-count").inner_text(), "1/7")
        self.assertEqual(len(self.chat_files_calls), before)
        page.keyboard.press("Escape")
        page.locator(".image-viewer").wait_for(state="detached")
        page.wait_for_function("history.state?.filePreview!=='image'")

        # The strip: the nine files not drawn in place, eight cards and the rest behind one button.
        self.assertEqual(page.locator(".answer-files .answer-file").count(), 8)
        self.assertEqual(page.locator(".answer-more").inner_text(), "还有 1 个")
        names = page.locator(".answer-files .answer-file-name").all_text_contents()
        self.assertIn("报告.pdf", names)
        self.assertIn("分析.R", names)
        self.assertIn("数据.xlsx", names)
        self.assertIn("presented-one.png", names)
        self.assertNotIn("presented-two.png", names)
        self.assertNotIn("chart.png", names)
        strip_text = page.locator(".answer-files").inner_text()
        self.assertIn("已更新", strip_text)
        self.assertIn("已删除", strip_text)
        page.locator(".answer-more").click()
        page.locator(".answer-dialog[open]").wait_for(state="visible")
        self.assertIn("这条消息的文件", page.locator(".answer-dialog").inner_text())
        self.assertIn("presented-two.png", page.locator(".answer-dialog").inner_text())
        self.close_answer_dialog(page)

        # A link that matches files[] opens that exact file, never the whole-conversation list.
        before = len(self.chat_files_calls)
        page.locator(".reply-text a", has_text="R 源码").click()
        page.locator(".artifact-panel").wait_for(state="visible")
        self.assertEqual(self.meta_calls[-1], "f-r")
        self.assertEqual(len(self.chat_files_calls), before)
        page.wait_for_function("document.querySelector('.artifact-panel')?.innerText.includes('fixture')")
        self.assertIn('print("fixture")', page.locator(".artifact-panel").inner_text())
        self.close_artifact(page)

        # A download-only card (xlsx) goes straight to the download page and fetches no bytes.
        before = len(self.file_calls)
        page.locator(".answer-files .answer-file", has_text="数据.xlsx").click()
        page.locator(".artifact-panel").wait_for(state="visible")
        self.assertEqual(self.meta_calls[-1], "f-xlsx")
        page.wait_for_function("document.querySelector('.artifact-panel')?.innerText.includes('此文件可下载')")
        self.assertIn("此文件可下载", page.locator(".artifact-panel").inner_text())
        self.assertEqual(len(self.file_calls), before)
        self.close_artifact(page)

        # Inline code and a path in the words both open their file.
        page.locator(".reply-text a.inline-file", has_text="笔记.txt").click()
        page.locator(".artifact-panel").wait_for(state="visible")
        self.assertEqual(self.meta_calls[-1], "f-note")
        self.close_artifact(page)
        page.locator(".reply-text a.inline-file", has_text="结果.csv").click()
        page.locator(".artifact-panel").wait_for(state="visible")
        self.assertEqual(self.meta_calls[-1], "f-csv")
        self.close_artifact(page)

        # A link that could not be given keeps its words, with a short grey reason that opens the full one.
        self.assertIn("（找不到文件）", page.locator(".file-note-short").first.inner_text())
        page.locator(".file-note-short", has_text="找不到文件").click()
        page.locator(".answer-dialog[open]").wait_for(state="visible")
        self.assertTrue(page.locator(".msg-menu").is_hidden())
        self.assertIn("电脑上没找到这个文件（回答写的是相对位置，在对话文件夹里没找到）",
                      page.locator(".answer-dialog").inner_text())
        self.close_answer_dialog(page)
        page.locator(".file-note-short", has_text="网络位置").click()
        page.locator(".answer-dialog[open]").wait_for(state="visible")
        self.assertIn("文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘",
                      page.locator(".answer-dialog").inner_text())
        self.close_answer_dialog(page)

        # Page anchors, mail and other schemes are only words; a localhost address says why the phone cannot open it.
        self.assertIsNone(page.locator(".reply-text a", has_text="页内目录").get_attribute("href"))
        self.assertIsNone(page.locator(".reply-text a", has_text="写信").get_attribute("href"))
        self.assertEqual(page.locator(".web-local-note").count(), 3)
        for note in page.locator(".web-local-note").all():
            self.assertEqual(note.inner_text(), "（电脑本机网址，手机打不开）")

        # An old computer: the old placeholder and index lookup, and no strip at all.
        self.open_conversation(page, OLD, "旧电脑的回答")
        self.assertEqual(page.locator(".answer-files").count(), 0)
        self.assertEqual(page.locator(".local-image").count(), 1)
        page.wait_for_function("!!document.querySelector('.local-image img')?.getAttribute('src')")
        before = len(self.chat_files_calls)
        page.locator(".reply-text a", has_text="旧文件").click()
        page.locator(".artifact-panel").wait_for(state="visible")
        self.assertEqual(self.meta_calls[-1], "old-text")
        self.assertGreater(len(self.chat_files_calls), before)
        self.assertEqual(self.chat_files_calls[-1].get("message"), ["old-message"])
        self.close_artifact(page)

        # A new computer with an empty files list also never falls back to the old index lookup.
        self.open_conversation(page, EMPTY, "新电脑，这条回答没有文件")
        self.assertEqual(page.locator(".answer-files").count(), 0)
        empty_link = page.locator(".reply-text a", has_text="没有列出的文件")
        self.assertEqual(empty_link.get_attribute("href"), "#")
        before = len(self.chat_files_calls)
        empty_link.click()
        self.assertEqual(len(self.chat_files_calls), before)
        self.assertEqual(page.locator(".artifact-panel").count(), 0)
        self.assertEqual(page.locator(".answer-dialog[open]").count(), 0)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
