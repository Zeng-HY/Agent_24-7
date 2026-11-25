"""Web stage B: the picture viewer, SVG, tables and the code page, against the real file APIs.

Fixtures are files in a temporary folder and a fabricated message; the thumbnail and text responses are
made by the computer's own ``file_renders.thumbnail`` / ``file_text.read``, not canned bytes.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import chat_history  # noqa: E402
import file_renders  # noqa: E402
import file_text  # noqa: E402
import remote  # noqa: E402
from agents import legacy as agent_legacy, registry as agent_registry  # noqa: E402
import motion_check as fake  # noqa: E402
from test_answer_files_web import ORIGIN, render_page, serve_static  # noqa: E402

NOW = 1767323050000
CONV = "fixture-preview-b"
SCRIPT = "# 示例脚本\n" + "\n".join(f"x <- {i}  # 第 {i} 行" for i in range(1, 20)) + "\n"
BIG = ("一段示例代码 # 行号 " + "x" * 180 + "\n") * 1200
HUGE = ("x" * 100000 + "\n") * 25


def make_png(path: Path, size=(320, 240), color=(210, 70, 70)):
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, size[0] - 20, size[1] - 20), outline=(20, 20, 20), width=3)
    image.save(path, "PNG")


def make_files(root: Path):
    make_png(root / "chart.png")
    make_png(root / "presented.png", (64, 64), (60, 90, 200))
    (root / "diagram.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100" viewBox="0 0 160 100">'
        '<rect x="5" y="5" width="150" height="90" fill="#d24a4a"/><circle cx="80" cy="50" r="24" fill="#fff"/>'
        '</svg>', encoding="utf-8")
    (root / "data.csv").write_bytes(
        ('name,note,amount\r\n"A, Inc.","line one\r\nline two",12\r\nB,"say ""hi""",34\r\n')
        .encode("utf-8"))
    (root / "gbk.csv").write_bytes("名称,说明\r\n表格,中文内容\r\n".encode("gb18030"))
    many = "编号,名称,说明\n" + "".join(f'{i},"名称,{i}","第 {i} 行"\n' for i in range(1, 5006))
    (root / "many.csv").write_bytes(many.encode("utf-8"))
    (root / "script.R").write_bytes(SCRIPT.encode("utf-8"))
    (root / "big.txt").write_bytes(BIG.encode("utf-8"))
    (root / "huge.txt").write_bytes(HUGE.encode("utf-8"))


def history_for(root: Path, paths):
    links = " ".join(
        f"[{p.name}](<{p.as_posix()}{':12' if p.name == 'script.R' else ''}>)" + "`" + p.as_posix() + "`"
        for p in paths)
    message = {"id": "m1", "role": "assistant", "text": links, "time": "2026-11-25T03:00:00Z",
               "activity_turn": "turn-1"}
    entry = SimpleNamespace(messages=[message], by_id={"m1": message}, state={"running": False},
                            offset=0, size=0, mtime=0, lock=threading.RLock(), context={},
                            path=root / "record.jsonl", cwd=str(root), app="codex", tid="c")
    item = {"app": "codex", "id": "c", "title": "预览示例 B", "folder": root.name, "cwd": str(root), "updated": 0}
    history = chat_history.History(secret="test-only")
    history.transcript = lambda app, tid: (item, entry)
    return history


class AnswerFilesPreview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.thumbs = self.root / "thumbs"
        self.thumbs.mkdir()
        file_text.clear_cache()
        make_files(self.root)
        self.chart = self.root / "chart.png"
        self.presented = self.root / "presented.png"
        self.svg = self.root / "diagram.svg"
        self.csv = self.root / "data.csv"
        self.gbk = self.root / "gbk.csv"
        self.many = self.root / "many.csv"
        self.script = self.root / "script.R"
        self.big = self.root / "big.txt"
        self.huge = self.root / "huge.txt"
        self.paths = [self.chart, self.svg, self.csv, self.gbk, self.many, self.script, self.big, self.huge,
                      self.presented]
        self.history = history_for(self.root, self.paths)
        self.rows = self.history.list_files("codex", "c")["items"]
        self.by_id = {row["id"]: row for row in self.rows}
        self.by_name = {Path(row["path"]).name: row for row in self.rows}
        self.assertEqual(len(self.rows), len(self.paths))
        self.assertTrue(file_renders.available())
        self.thumb_calls: list[tuple[str, int, bytes]] = []
        self.text_calls: list[str] = []

        text = "\n\n".join([
            "这是第二段的编造回答。",
            f"![图表](<{self.chart.as_posix()}>)",
            f"![矢量](<{self.svg.as_posix()}>)",
            f"[表格](<{self.csv.as_posix()}>)",
            f"[GBK 表格](<{self.gbk.as_posix()}>)",
            f"[很多行](<{self.many.as_posix()}>)",
            f"[R 脚本](<{self.script.as_posix()}:12>)",
            f"[大文本](<{self.big.as_posix()}>)",
            f"[超大文本](<{self.huge.as_posix()}>)",
            f"[展示图](<{self.presented.as_posix()}>)",
        ])
        self.message = {"id": "preview-message", "role": "assistant", "time": NOW, "text": text,
                        "files": self.rows}
        self.tool_message = {"id": "preview-tool", "role": "tool", "time": NOW - 1000,
                             "text": "把展示图给用户", "files": [self.by_name["presented.png"]]}
        self.machine = {"name": "测试电脑", "apps": ["codex"], "voice": False, "version": "0.27.0-test",
                        "agents": agent_registry.manifests_for(["codex"]),
                        **agent_legacy.page_capabilities(["codex"])}
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.webkit.launch()
        self.addCleanup(self.browser.close)

    def tearDown(self):
        file_text.clear_cache()

    def chat(self):
        return {"app": "codex", "id": CONV, "title": "预览示例 B", "folder": "示例项目",
                "cwd": str(self.root), "status": "idle", "size": 2, "note": "", "has_more": False,
                "next_cursor": "", "runtime": {}, "messages": [self.tool_message, self.message]}

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
            rows = [{"app": "codex", "id": CONV, "title": "预览示例 B", "folder": "示例项目",
                     "cwd": str(self.root), "updated": NOW, "created": NOW - 9000,
                     "status": "idle", "preview": "第二段示例"}]
            return js({"items": rows, "total": 1, "has_more": False, "next_cursor": ""})
        if path == "/api/chat":
            return js(self.chat())
        if path == "/api/chat/files":
            return js({"items": self.rows, "scope": "fixture"})
        if path == "/api/file/thumb":
            fid = q.get("file", [""])[0]
            row = self.by_id.get(fid)
            if not row:
                return js({"error": "unknown fixture"}, 404)
            meta = self.history.file("codex", "c", fid)
            if q.get("v") and q["v"][0] != meta["v"]:
                return js({"error": "文件已变化"}, 409)
            try:
                width = int(q.get("w", ["0"])[0])
                body = file_renders.thumbnail(meta["path"], row["view"], width, cache_dir=self.thumbs)
            except Exception as exc:
                return js({"error": str(exc)}, 400)
            self.thumb_calls.append((fid, width, body[:12]))
            return route.fulfill(status=200, content_type="image/webp", body=body,
                                 headers={"X-Content-Type-Options": "nosniff"})
        if path == "/api/file/text":
            fid = q.get("file", [""])[0]
            row = self.by_id.get(fid)
            if not row:
                return js({"error": "unknown fixture"}, 404)
            meta = self.history.file("codex", "c", fid)
            made = file_text.read(meta["path"])
            if made is None:
                return js({"error": "这个文件不提供文本预览"}, 400)
            self.text_calls.append(fid)
            return js({**made, "name": Path(meta["path"]).name, "lang": row.get("lang"),
                       "line": row.get("line")})
        if path == "/api/file/meta":
            fid = q.get("file", [""])[0]
            row = self.by_id.get(fid)
            if not row:
                return js({"error": "unknown fixture"}, 404)
            meta = self.history.file("codex", "c", fid)
            return js({"name": Path(meta["path"]).name, "size": meta["size"], "kind": meta["kind"],
                       "state": "current", "updated": False, "modified": meta.get("mtime"),
                       "v": meta.get("v"), "view": meta.get("view"), "mime": meta.get("mime"),
                       "lang": row.get("lang")})
        if path == "/api/file":
            fid = q.get("file", [""])[0]
            row = self.by_id.get(fid)
            if not row:
                return js({"error": "unknown fixture"}, 404)
            meta = self.history.file("codex", "c", fid)
            body = Path(meta["path"]).read_bytes()
            ctype = meta.get("mime") or "application/octet-stream"
            if Path(meta["path"]).suffix.lower() in (".svg", ".html", ".htm", ".xml", ".js", ".mjs"):
                ctype = "application/octet-stream"
            return route.fulfill(status=200, content_type=ctype, body=body)
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
        ctx.add_init_script("""window.__opened=[];window.open=(...a)=>{window.__opened.push(a);return null};
          window.__copied=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async t=>{window.__copied.push(t)}}});
          window.__revoked=[];const revoke=URL.revokeObjectURL.bind(URL);URL.revokeObjectURL=u=>{window.__revoked.push(u);revoke(u)};""")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route(ORIGIN + "/**", self.router)
        page.goto(ORIGIN + "/", wait_until="load")
        page.wait_for_function("!!window.readingUI && document.querySelectorAll('#convList .conv').length === 1")
        page.locator(f'#convList .conv[data-key="codex:{CONV}"]').click()
        page.wait_for_function("document.querySelector('#cvMsgs')?.innerText.includes('第二段的编造回答')")
        page.wait_for_function("document.querySelectorAll('#cvMsgs .bub.assistant').length === 1")
        return ctx, page, errors

    def close_artifact(self, page):
        page.get_by_role("button", name="返回聊天").click()
        page.locator(".artifact-panel").wait_for(state="detached")

    def test_pictures_svg_viewer_table_and_code_page(self):
        ctx, page, errors = self.open_page()
        shots = os.environ.get("AR_PREVIEW_SHOTS")
        page.locator("#cvMsgs").evaluate("e=>e.scrollTop=0")
        page.wait_for_function("document.querySelectorAll('.msg-image.loaded').length === 2")
        page.locator(".bub.assistant .answer-files").scroll_into_view_if_needed()
        page.wait_for_function("()=>[...document.querySelectorAll('.answer-file-thumb')].some(n=>n.complete&&n.naturalWidth>0)")

        # Real thumbnails: the two pictures in the message and the picture card in the strip.
        widths = {width for _, width, _ in self.thumb_calls}
        self.assertTrue({640, 320} <= widths, widths)
        self.assertTrue(all(body[:4] == b"RIFF" and body[8:12] == b"WEBP" for _, _, body in self.thumb_calls))
        self.assertTrue(any(fid == self.by_name["chart.png"]["id"] for fid, _, _ in self.thumb_calls))
        self.assertTrue(any(fid == self.by_name["diagram.svg"]["id"] for fid, _, _ in self.thumb_calls))
        self.assertEqual(page.locator(".msg-image img").first.get_attribute("src").split("?")[0], "/api/file/thumb")
        self.assertEqual(page.locator(".msg-image").nth(1).locator("img").get_attribute("src").split("?")[0],
                         "/api/file/thumb")
        presented_card = page.locator(".bub.assistant .answer-files .answer-file", has_text="presented.png")
        self.assertEqual(presented_card.locator("img").get_attribute("src").split("?")[0], "/api/file/thumb")

        # The viewer: order is the message's own picture order, arrows move, Escape closes.
        page.locator(".msg-image").first.click()
        page.locator(".image-viewer").wait_for(state="visible")
        self.assertEqual(page.locator(".viewer-count").inner_text(), "1/3")
        page.wait_for_function("document.querySelector('.viewer-picture')?.getAttribute('src')?.includes('/api/file?')")
        self.assertIn(1280, {width for _, width, _ in self.thumb_calls})
        if shots:
            page.screenshot(path=str(Path(shots) / "b-viewer.png"))
        save = page.locator(".viewer-actions a")
        self.assertTrue(save.get_attribute("href").endswith("&download=1"))
        self.assertIsNotNone(save.get_attribute("download"))
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.locator(".viewer-count").inner_text(), "2/3")
        page.wait_for_function("document.querySelector('.viewer-picture')?.getAttribute('src')?.startsWith('blob:')")
        self.assertEqual(page.evaluate("window.__opened.length"), 0)
        self.assertEqual(page.evaluate("document.querySelectorAll('a[href^=\"blob:\"]').length"), 0)
        self.assertEqual(page.evaluate("document.querySelectorAll('.viewer-stage object,.viewer-stage iframe,.viewer-stage svg').length"), 0)
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.locator(".viewer-count").inner_text(), "3/3")
        page.keyboard.press("ArrowLeft")
        self.assertEqual(page.locator(".viewer-count").inner_text(), "2/3")

        # Zoomed, an arrow pans; it does not turn the page. A double click returns to original size.
        page.locator(".viewer-stage").hover(position={"x": 100, "y": 200})
        page.keyboard.down("Control")
        page.mouse.wheel(0, -700)
        page.keyboard.up("Control")
        scale = page.evaluate("()=>{const t=getComputedStyle(document.querySelector('.viewer-picture')).transform;return t}")
        self.assertNotEqual(scale, "none")
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.locator(".viewer-count").inner_text(), "2/3")
        page.mouse.dblclick(195, 420)
        page.wait_for_timeout(250)
        self.assertIn("scale(1)", page.evaluate("document.querySelector('.viewer-picture').style.transform"))
        blob = page.evaluate("document.querySelector('.viewer-picture').src")
        page.keyboard.press("Escape")
        page.locator(".image-viewer").wait_for(state="detached")
        self.assertIn(blob, page.evaluate("window.__revoked"))

        # "Open in file page" from the viewer.
        page.locator(".msg-image").first.click()
        page.locator(".image-viewer").wait_for(state="visible")
        page.get_by_role("button", name="文件页").click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".artifact-image").wait_for(state="visible")
        self.close_artifact(page)

        # Table: quotes, a comma and a newline inside a quote, sticky header, raw switch.
        page.get_by_role("link", name="表格", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".table-view").wait_for(state="visible")
        self.assertEqual(page.locator(".table-view thead th").all_text_contents(), ["name", "note", "amount"])
        self.assertEqual(page.locator(".table-view tbody tr").count(), 2)
        cells = page.locator(".table-view tbody td").all_text_contents()
        self.assertIn("A, Inc.", cells)
        self.assertIn("say \"hi\"", cells)
        self.assertTrue(any("line one" in cell and "line two" in cell for cell in cells))
        self.assertEqual(page.locator(".table-view thead th").first.evaluate("e=>getComputedStyle(e).position"),
                         "sticky")
        if shots:
            page.screenshot(path=str(Path(shots) / "b-table.png"))
        page.locator(".code-tool", has_text="查看原文").click()
        self.assertTrue(page.locator(".artifact-source").is_visible())
        self.assertFalse(page.locator(".table-scroll").is_visible())
        self.close_artifact(page)

        # More than 5000 data rows: 5000 shown and a note.
        page.get_by_role("link", name="很多行", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".table-view").wait_for(state="visible")
        self.assertEqual(page.locator(".table-view tbody tr").count(), 5000)
        self.assertIn("只显示了前 5000 行（共 5005 行）", page.locator(".artifact-panel").inner_text())
        self.close_artifact(page)

        # A GB18030 table is decoded by the computer before it reaches the page.
        page.get_by_role("link", name="GBK 表格", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".table-view").wait_for(state="visible")
        self.assertIn("名称", page.locator(".table-view").inner_text())
        self.assertIn("中文内容", page.locator(".table-view").inner_text())
        self.close_artifact(page)

        # Code page: highlighted, line numbers, jump to the line the answer named, wrap, find, copy.
        page.get_by_role("link", name="R 脚本", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".code-view").wait_for(state="visible")
        page.wait_for_function("document.querySelectorAll('.code-view [class*=\"hljs-\"]').length > 0")
        self.assertGreater(page.evaluate("document.querySelectorAll('.code-view [class*=\"hljs-\"]').length"), 0)
        self.assertIn("jump", page.locator(".code-line[data-line='12']").get_attribute("class") or "")
        self.assertEqual(page.locator(".code-line .ln").first.inner_text(), "1")
        if shots:
            page.screenshot(path=str(Path(shots) / "b-code.png"))
        page.locator(".code-tool", has_text="自动换行").click()
        self.assertTrue(page.locator(".code-view.wrap").is_visible())
        page.locator(".code-find").fill("x <-")
        page.wait_for_function("!!document.querySelector('.code-line.find-hit')")
        self.assertIn("/", page.locator(".code-hits").inner_text())
        page.locator(".code-tool", has_text="复制全部").click()
        page.wait_for_function("window.__copied.length > 0")
        self.assertEqual(page.evaluate("window.__copied.at(-1)"), SCRIPT)
        self.close_artifact(page)

        # Dark theme loads the dark highlight theme; over 200 KB there is no highlighting, only line numbers.
        page.evaluate("TeleplyTheme.set('dark')")
        page.get_by_role("link", name="R 脚本", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".code-view").wait_for(state="visible")
        page.wait_for_function("document.querySelectorAll('.code-view [class*=\"hljs-\"]').length > 0")
        self.assertIn("code-dark.css", page.locator("#code-theme").get_attribute("href"))
        self.close_artifact(page)
        page.evaluate("TeleplyTheme.set('light')")
        page.get_by_role("link", name="大文本", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".code-view").wait_for(state="visible")
        self.assertEqual(page.evaluate("document.querySelectorAll('.code-view [class*=\"hljs-\"]').length"), 0)
        self.assertGreater(page.locator(".code-line").count(), 1000)
        self.assertIn("没有语法高亮", page.locator(".artifact-panel").inner_text())
        self.close_artifact(page)

        # Truncated text says how much is shown.
        page.get_by_role("link", name="超大文本", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".code-view").wait_for(state="visible")
        self.assertIn("只显示了开头", page.locator(".artifact-panel").inner_text())
        self.close_artifact(page)

        # A tool row that carries files before any answer shows its strip too.
        page.evaluate("""()=>{const g=document.querySelector('.activity-group');
          const body=g?.querySelector('.activity-body');if(body?.hidden)g.querySelector('.activity-heading')?.click();}""")
        page.locator(".activity-item summary").first.click()
        self.assertGreaterEqual(page.locator(".activity-item .answer-files .answer-file").count(), 1)

        self.assertEqual(errors, [])

    def test_real_file_routes_for_thumb_and_text(self):
        class Fake:
            def __init__(self, query):
                self.query = query
                self.sent = []
                self.history = self_history
            def _query(self):
                return self.query
            def _app_visible(self, app):
                return True
            def _json(self, body, status=200):
                self.sent.append(("json", status, body))
            def _send(self, code, body, ctype, extra=None):
                self.sent.append(("send", code, body, ctype))

        self_history = self.history
        chart = self.by_name["chart.png"]
        with patch.object(file_renders, "_cache_root", lambda cache_dir=None: self.thumbs):
            fake = Fake({"app": "codex", "id": "c", "file": chart["id"], "w": "640", "v": chart["v"]})
            remote.Handler._reading_get(fake, "/api/file/thumb")
            kind, status, body, ctype = fake.sent[-1]
            self.assertEqual((kind, status, ctype), ("send", 200, "image/webp"))
            self.assertEqual(body[:4], b"RIFF")
            self.assertEqual(body[8:12], b"WEBP")
            fake = Fake({"app": "codex", "id": "c", "file": chart["id"], "w": "640", "v": "stale"})
            remote.Handler._reading_get(fake, "/api/file/thumb")
            self.assertEqual(fake.sent[-1][1], 409)
            fake = Fake({"app": "codex", "id": "c", "file": chart["id"], "w": "999"})
            remote.Handler._reading_get(fake, "/api/file/thumb")
            self.assertEqual(fake.sent[-1][1], 400)
        script = self.by_name["script.R"]
        fake = Fake({"app": "codex", "id": "c", "file": script["id"]})
        remote.Handler._reading_get(fake, "/api/file/text")
        kind, status, body = fake.sent[-1]
        self.assertEqual((kind, status), ("json", 200))
        self.assertEqual(body["text"], SCRIPT)
        self.assertEqual(body["encoding"], "utf-8")
        self.assertEqual((body["lang"], body["line"]), ("r", 12))

    def test_vendor_lock_matches_the_files(self):
        entries = json.loads((ROOT / "static/vendor-lock.json").read_text(encoding="utf-8"))
        files = [e for e in entries if e.get("package") == "@highlightjs/cdn-assets"]
        self.assertEqual(len(files), 8)
        self.assertTrue(all(e["version"] == "11.12.0" and "registry.npmjs.org" in e["source"] for e in files))
        import hashlib
        for entry in files:
            payload = (ROOT / "static" / entry["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"], entry["file"])
            if entry["file"].endswith(".js") or entry["file"].endswith(".css"):
                self.assertIn("/highlight/" + Path(entry["file"]).name, remote.STATIC_FILES)
        self.assertTrue((ROOT / "static/highlight.js.LICENSE").is_file())


if __name__ == "__main__":
    unittest.main()


