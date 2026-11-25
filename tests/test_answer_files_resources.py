"""Web stage C: audio/video, zip listings, page resources and the back gesture.

Fixtures are files in a temporary folder and a fabricated message.  A small real HTTP server serves the
page and the computer's own endpoints, because WebKit's media requests do not go through Playwright's route
interception; the thumbnail/text/zip/resource work is still done by the real computer-side functions.
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import sys
import tempfile
import threading
import unittest
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlsplit

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import chat_history  # noqa: E402
import file_renders  # noqa: E402
import file_resources  # noqa: E402
import file_text  # noqa: E402
import remote  # noqa: E402
from agents import legacy as agent_legacy, registry as agent_registry  # noqa: E402
import motion_check as fake  # noqa: E402
from test_answer_files_web import render_page  # noqa: E402

NOW = 1767323050000
CONV = "fixture-preview-c"


def make_png(path: Path, size=(320, 240), color=(210, 70, 70)):
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, size[0] - 20, size[1] - 20), outline=(20, 20, 20), width=3)
    image.save(path, "PNG")


def make_wav(path: Path):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000)


def gbk_zip(path: Path, name: bytes):
    placeholder = b"x" * len(name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(placeholder.decode("ascii"), b"hello")
    path.write_bytes(buffer.getvalue().replace(placeholder, name))


def make_files(root: Path):
    make_png(root / "chart.png")
    make_png(root / "presented.png", (64, 64), (60, 90, 200))
    (root / "diagram.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100" viewBox="0 0 160 100">'
        '<rect x="5" y="5" width="150" height="90" fill="#d24a4a"/></svg>', encoding="utf-8")
    make_wav(root / "beep.wav")
    (root / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2")
    (root / "unsupported.mkv").write_bytes(b"\x1aE\xdf\xa3")
    with zipfile.ZipFile(root / "files.zip", "w") as archive:
        archive.writestr("folder/", b"")
        archive.writestr("folder/说明.txt", b"hello")
        archive.writestr("a.txt", b"a")
    gbk_zip(root / "gbk.zip", "中文说明.txt".encode("gb18030"))
    with zipfile.ZipFile(root / "many.zip", "w") as archive:
        for index in range(2001):
            archive.writestr(f"f{index}.txt", b"")
    (root / "bad.zip").write_bytes(b"not a zip")
    (root / "thing.7z").write_bytes(b"7z")
    outside = root / "outside.png"
    make_png(outside, (64, 64), (30, 160, 80))
    pages = root / "pages"
    (pages / "img").mkdir(parents=True)
    (pages / "sub").mkdir()
    (pages / "img" / "a.png").write_bytes((root / "chart.png").read_bytes())
    (pages / "sub" / "b.png").write_bytes((root / "presented.png").read_bytes())
    (pages / "secret.pem").write_bytes(b"secret")
    (pages / "style.css").write_text("h1{color:rgb(1, 2, 3)} body{background:rgb(250, 250, 250)}", encoding="utf-8")
    (pages / "evil.js").write_text("window.PWNED=1", encoding="utf-8")
    (pages / "note.md").write_text(
        "# 页面\n\n![一](img/a.png)\n\n![二](sub/b.png)\n\n![外](../outside.png)\n\n"
        "![密钥](secret.pem)\n\n![缺](nope.png)\n", encoding="utf-8")
    (pages / "page.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css">'
        '<style>body{background-image:url("img/a.png")}</style></head>'
        '<body><h1>HTML 页面</h1><img src="img/a.png"><script src="evil.js"></script></body></html>',
        encoding="utf-8")


def history_for(root: Path, paths):
    links = " ".join(f"[{p.name}](<{p.as_posix()}>)`{p.as_posix()}`" for p in paths)
    message = {"id": "m1", "role": "assistant", "text": links, "time": "2026-11-25T03:00:00Z",
               "activity_turn": "turn-1"}
    entry = SimpleNamespace(messages=[message], by_id={"m1": message}, state={"running": False},
                            offset=0, size=0, mtime=0, lock=threading.RLock(), context={},
                            path=root / "record.jsonl", cwd=str(root), app="codex", tid="c")
    item = {"app": "codex", "id": "c", "title": "预览示例 C", "folder": root.name, "cwd": str(root), "updated": 0}
    history = chat_history.History(secret="test-only")
    history.transcript = lambda app, tid: (item, entry)
    return history


class AnswerFilesResources(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.thumbs = self.root / "thumbs"
        self.thumbs.mkdir()
        file_text.clear_cache()
        file_resources.clear_cache()
        make_files(self.root)
        self.chart = self.root / "chart.png"
        self.presented = self.root / "presented.png"
        self.svg = self.root / "diagram.svg"
        self.audio = self.root / "beep.wav"
        self.video = self.root / "clip.mp4"
        self.mkv = self.root / "unsupported.mkv"
        self.zip = self.root / "files.zip"
        self.gbk_zip = self.root / "gbk.zip"
        self.many_zip = self.root / "many.zip"
        self.bad_zip = self.root / "bad.zip"
        self.seven = self.root / "thing.7z"
        self.note_md = self.root / "pages" / "note.md"
        self.page_html = self.root / "pages" / "page.html"
        self.paths = [self.chart, self.svg, self.presented, self.audio, self.video, self.mkv, self.zip,
                      self.gbk_zip, self.many_zip, self.bad_zip, self.seven, self.note_md, self.page_html]
        self.history = history_for(self.root, self.paths)
        self.rows = self.history.list_files("codex", "c")["items"]
        self.by_id = {row["id"]: row for row in self.rows}
        self.by_name = {Path(row["path"]).name: row for row in self.rows}
        self.assertEqual(len(self.rows), len(self.paths))
        self.thumb_calls: list[tuple[str, int, bytes]] = []
        self.text_calls: list[str] = []
        self.zip_calls: list[str] = []
        self.resource_calls: list[str] = []
        self.chat_files_calls: list[str] = []
        text = "\n\n".join([
            "这是第三段的编造回答。",
            f"![图表](<{self.chart.as_posix()}>)",
            f"![矢量](<{self.svg.as_posix()}>)",
            f"[展示图](<{self.presented.as_posix()}>)",
            f"[音频](<{self.audio.as_posix()}>)",
            f"[视频](<{self.video.as_posix()}>)",
            f"[不支持的视频](<{self.mkv.as_posix()}>)",
            f"[压缩包](<{self.zip.as_posix()}>)",
            f"[GBK 压缩包](<{self.gbk_zip.as_posix()}>)",
            f"[很多项](<{self.many_zip.as_posix()}>)",
            f"[坏压缩包](<{self.bad_zip.as_posix()}>)",
            f"[7z 包](<{self.seven.as_posix()}>)",
            f"[Markdown 页面](<{self.note_md.as_posix()}>)",
            f"[HTML 页面](<{self.page_html.as_posix()}>)",
        ])
        self.message = {"id": "preview-message", "role": "assistant", "time": NOW, "text": text,
                        "files": self.rows}
        self.machine = {"name": "测试电脑", "apps": ["codex"], "voice": False, "version": "0.27.0-test",
                        "agents": agent_registry.manifests_for(["codex"]),
                        **agent_legacy.page_capabilities(["codex"])}
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.webkit.launch()
        self.addCleanup(self.browser.close)

    def tearDown(self):
        file_text.clear_cache()
        file_resources.clear_cache()

    def chat(self):
        return {"app": "codex", "id": CONV, "title": "预览示例 C", "folder": "示例项目",
                "cwd": str(self.root), "status": "idle", "size": 1, "note": "", "has_more": False,
                "next_cursor": "", "runtime": {}, "messages": [self.message]}

    def response(self, path, q, headers=None):
        headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        def js(obj, status=200):
            return status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode(), {}
        if path == "/":
            return 200, "text/html; charset=utf-8", render_page(self.machine), {}
        if path.startswith("/api/"):
            if path == "/api/status":
                return js({"ok": True, "ui_version": "0.27.0-test", "protocol": 2})
            if path == "/api/chat/projects":
                return js(fake.fake_tree())
            if path == "/api/chats":
                row = {"app": "codex", "id": CONV, "title": "预览示例 C", "folder": "示例项目",
                       "cwd": str(self.root), "updated": NOW, "created": NOW - 9000,
                       "status": "idle", "preview": "第三段示例"}
                return js({"items": [row], "total": 1, "has_more": False, "next_cursor": ""})
            if path == "/api/chat":
                return js(self.chat())
            if path == "/api/chat/files":
                self.chat_files_calls.append(q.get("message", ""))
                return js({"items": self.rows, "scope": "fixture"})
            if path == "/api/file/thumb":
                fid = q.get("file", "")
                row = self.by_id.get(fid)
                if not row:
                    return js({"error": "unknown fixture"}, 404)
                meta = self.history.file("codex", "c", fid)
                if q.get("v") and q["v"] != meta["v"]:
                    return js({"error": "文件已变化"}, 409)
                try:
                    width = int(q.get("w", "0"))
                    body = file_renders.thumbnail(meta["path"], row["view"], width, cache_dir=self.thumbs)
                except Exception as exc:
                    return js({"error": str(exc)}, 400)
                self.thumb_calls.append((fid, width, body[:12]))
                return 200, "image/webp", body, {"X-Content-Type-Options": "nosniff"}
            if path == "/api/file/text":
                fid = q.get("file", "")
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
            if path == "/api/file/zip":
                fid = q.get("file", "")
                row = self.by_id.get(fid)
                if not row:
                    return js({"error": "unknown fixture"}, 404)
                meta = self.history.file("codex", "c", fid)
                if q.get("v") and q["v"] != meta["v"]:
                    return js({"error": "文件已变化"}, 409)
                if row.get("view") != "archive" or Path(meta["path"]).suffix.lower() != ".zip":
                    return js({"error": "这种压缩包只能下载"}, 400)
                self.zip_calls.append(fid)
                try:
                    return js(file_resources.zip_entries(meta["path"]))
                except file_resources.ResourceError as exc:
                    return js({"error": str(exc)}, exc.status)
            if path == "/api/file/resource":
                fid = q.get("file", "")
                row = self.by_id.get(fid)
                if not row:
                    return js({"error": "unknown fixture"}, 404)
                meta = self.history.file("codex", "c", fid)
                requested = q.get("path", "")
                self.resource_calls.append(requested)
                try:
                    target, mime, attachment, size = file_resources.resolve_resource(
                        meta["path"], row.get("view"), requested)
                except file_resources.ResourceError as exc:
                    return js({"error": str(exc)}, exc.status)
                extra = {"X-Content-Type-Options": "nosniff"}
                if attachment:
                    extra["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(target.name)
                return 200, mime, target.read_bytes(), extra
            if path == "/api/file/meta":
                fid = q.get("file", "")
                row = self.by_id.get(fid)
                if not row:
                    return js({"error": "unknown fixture"}, 404)
                meta = self.history.file("codex", "c", fid)
                return js({"name": Path(meta["path"]).name, "size": meta["size"], "kind": meta["kind"],
                           "state": "current", "updated": False, "modified": meta.get("mtime"),
                           "v": meta.get("v"), "view": meta.get("view"), "mime": meta.get("mime"),
                           "lang": row.get("lang")})
            if path == "/api/file":
                fid = q.get("file", "")
                row = self.by_id.get(fid)
                if not row:
                    return js({"error": "unknown fixture"}, 404)
                meta = self.history.file("codex", "c", fid)
                body = Path(meta["path"]).read_bytes()
                ctype = meta.get("mime") or "application/octet-stream"
                if Path(meta["path"]).suffix.lower() in (".svg", ".html", ".htm", ".xml", ".js", ".mjs"):
                    ctype = "application/octet-stream"
                extra = {"Accept-Ranges": "bytes"}
                requested = headers.get("range")
                if requested:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                    if match and any(match.groups()):
                        size = len(body)
                        start = int(match.group(1)) if match.group(1) else 0
                        end = int(match.group(2)) if match.group(2) else size - 1
                        end = min(end, size - 1)
                        extra["Content-Range"] = f"bytes {start}-{end}/{size}"
                        return 206, ctype, body[start:end + 1], extra
                return 200, ctype, body, extra
            if path == "/api/codex/state":
                return js({"available": True, "running": False, "status": "idle", "settings": {},
                           "catalog": {"models": []}, "questions": [], "queued": [], "images": []})
            if path == "/api/claude/state":
                return js({"settings": {}, "available": True, "actions": []})
            if path == "/api/events":
                return js({"error": "fixture"}, 404)
            return js({})
        file = ROOT / "static" / path.lstrip("/")
        if path != "/" and file.is_file():
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            return 200, ctype, file.read_bytes(), {}
        return 404, "text/plain", b"Not found", {}

    def local_server(self):
        if getattr(self, "_server", None):
            return self._server, self._server.server_address[1]
        owner = self
        class Local(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def do_GET(self):
                u = urlsplit(self.path)
                q = {key: values[-1] for key, values in parse_qs(u.query).items()}
                status, ctype, body, extra = owner.response(u.path, q, dict(self.headers))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for key, value in extra.items():
                    self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            do_HEAD = do_GET
        server = ThreadingHTTPServer(("127.0.0.1", 0), Local)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, name="preview-fixture", daemon=True)
        thread.start()
        self._server = server
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, server.server_address[1]

    def open_page(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        self.addCleanup(ctx.close)
        ctx.add_init_script("""window.__opened=[];window.open=(...a)=>{window.__opened.push(a);return null};
          window.__copied=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async t=>{window.__copied.push(t)}}});
          window.__revoked=[];const revoke=URL.revokeObjectURL.bind(URL);URL.revokeObjectURL=u=>{window.__revoked.push(u);revoke(u)};""")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _, port = self.local_server()
        page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
        page.wait_for_function("!!window.readingUI && document.querySelectorAll('#convList .conv').length === 1")
        page.locator(f'#convList .conv[data-key="codex:{CONV}"]').click()
        page.wait_for_function("document.querySelector('#cvMsgs')?.innerText.includes('第三段的编造回答')")
        page.wait_for_function("document.querySelectorAll('#cvMsgs .bub.assistant').length === 1")
        return ctx, page, errors

    def close_artifact(self, page):
        page.get_by_role("button", name="返回聊天").click()
        page.locator(".artifact-panel").wait_for(state="detached")
        if page.evaluate("history.state?.filePreview") == "file":
            page.wait_for_function("history.state?.filePreview!=='file'")

    def test_audio_video_zip_pages(self):
        ctx, page, errors = self.open_page()

        page.get_by_role("link", name="音频", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".artifact-panel audio").wait_for(state="visible")
        audio = page.locator(".artifact-panel audio")
        src = audio.get_attribute("src")
        self.assertTrue(src.startswith("/api/file?"))
        query = parse_qs(urlsplit(src).query)
        self.assertEqual(query["file"], [self.by_name["beep.wav"]["id"]])
        self.assertEqual(query["v"], [self.by_name["beep.wav"]["v"]])
        self.assertNotIn("download", query)
        page.wait_for_function("()=>{const a=document.querySelector('.artifact-panel audio');return !!a&&a.duration>0}")
        handle = audio.element_handle()
        self.close_artifact(page)
        self.assertIsNone(handle.evaluate("e=>e.getAttribute('src')"))

        page.get_by_role("link", name="视频", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.evaluate("()=>{HTMLMediaElement.prototype.load=function(){};}")
        page.locator(".artifact-panel video").wait_for(state="visible")
        video = page.locator(".artifact-panel video")
        src = video.get_attribute("src")
        self.assertTrue(src.startswith("/api/file?"))
        self.assertNotIn("download", parse_qs(urlsplit(src).query))
        self.close_artifact(page)

        page.evaluate("""()=>{const original=HTMLMediaElement.prototype.canPlayType;
          HTMLMediaElement.prototype.canPlayType=function(type){return type==='video/x-matroska'?'':original.call(this,type);};}""")
        page.get_by_role("link", name="不支持的视频", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".artifact-file").wait_for(state="visible")
        self.assertIn("这个格式浏览器放不了，请下载后用其他应用打开", page.locator(".artifact-panel").inner_text())
        self.assertEqual(page.locator(".artifact-panel video,.artifact-panel audio").count(), 0)
        self.close_artifact(page)

        page.get_by_role("link", name="压缩包", exact=True).click()
        page.locator(".zip-list").wait_for(state="visible")
        self.assertTrue(page.locator(".zip-summary").inner_text().startswith("共 3 项，解压后"))
        self.assertEqual(page.locator(".zip-row").count(), 3)
        self.assertIn("dir", page.locator(".zip-row").first.get_attribute("class"))
        self.assertIn("folder/", page.locator(".zip-row").first.inner_text())
        self.assertTrue(any("a.txt" in name for name in page.locator(".zip-name").all_text_contents()))
        self.assertRegex(page.locator(".zip-time").nth(1).inner_text(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.close_artifact(page)

        page.get_by_role("link", name="GBK 压缩包", exact=True).click()
        page.locator(".zip-list").wait_for(state="visible")
        self.assertIn("中文说明.txt", page.locator(".zip-name").all_text_contents())
        self.close_artifact(page)

        page.get_by_role("link", name="很多项", exact=True).click()
        page.locator(".zip-list").wait_for(state="visible")
        self.assertEqual(page.locator(".zip-row").count(), 2000)
        self.assertIn("只列了前 2000 项", page.locator(".artifact-panel").inner_text())
        self.close_artifact(page)

        page.get_by_role("link", name="坏压缩包", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".artifact-file").wait_for(state="visible")
        self.assertIn("这个压缩包读不了", page.locator(".artifact-panel").inner_text())
        self.close_artifact(page)

        page.get_by_role("link", name="7z 包", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        page.locator(".artifact-file").wait_for(state="visible")
        self.assertIn("这种压缩包只能下载", page.locator(".artifact-panel").inner_text())
        self.close_artifact(page)
        self.assertEqual(errors, [])

    def test_resources_and_history(self):
        ctx, page, errors = self.open_page()
        url = page.url

        before = len(self.chat_files_calls)
        page.get_by_role("link", name="Markdown 页面", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        frame = page.frame_locator("iframe.artifact-frame")
        frame.locator("h1").wait_for(state="visible")
        self.assertEqual(frame.locator("h1").inner_text(), "页面")
        self.assertEqual(frame.locator("img[src^='data:']").count(), 2)
        self.assertIn("部分资源未提供", page.locator(".artifact-panel").inner_text())
        self.assertEqual(len(self.chat_files_calls), before)
        self.close_artifact(page)

        page.get_by_role("link", name="HTML 页面", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        frame = page.frame_locator("iframe.artifact-frame")
        frame.locator("h1").wait_for(state="visible")
        self.assertEqual(frame.locator("h1").inner_text(), "HTML 页面")
        self.assertEqual(frame.locator("h1").evaluate("e=>getComputedStyle(e).color"), "rgb(1, 2, 3)")
        self.assertTrue(frame.locator("body").evaluate("e=>getComputedStyle(e).backgroundImage").startswith('url("data:image/png'))
        self.assertEqual(frame.locator("img[src^='data:']").count(), 1)
        children = [item for item in page.frames if item != page.main_frame]
        self.assertTrue(children)
        self.assertIsNone(children[-1].evaluate("()=>window.PWNED"))
        self.assertFalse(any(path.endswith("evil.js") for path in self.resource_calls))
        self.assertEqual(len(self.chat_files_calls), before)
        self.close_artifact(page)

        base_state = page.evaluate("history.state")
        page.locator(".msg-image").first.click()
        page.locator(".image-viewer").wait_for(state="visible")
        self.assertEqual(page.evaluate("history.state?.filePreview"), "image")
        page.evaluate("history.back()")
        page.locator(".image-viewer").wait_for(state="detached")
        page.wait_for_function("history.state?.filePreview!=='image'")
        self.assertEqual(page.url, url)

        page.locator(".msg-image").first.click()
        page.locator(".image-viewer").wait_for(state="visible")
        page.locator('.viewer-bar button[aria-label="返回"]').click()
        page.locator(".image-viewer").wait_for(state="detached")
        page.wait_for_function("history.state?.filePreview!=='image'")
        self.assertEqual(page.url, url)
        self.assertEqual(page.evaluate("history.state"), base_state)

        page.get_by_role("link", name="音频", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        self.assertEqual(page.evaluate("history.state?.filePreview"), "file")
        page.evaluate("history.back()")
        page.locator(".artifact-panel").wait_for(state="detached")
        page.wait_for_function("history.state?.filePreview!=='file'")
        self.assertEqual(page.url, url)

        page.get_by_role("link", name="音频", exact=True).click()
        page.locator(".artifact-panel").wait_for(state="visible")
        self.close_artifact(page)
        page.wait_for_function("history.state?.filePreview!=='file'")
        self.assertEqual(page.url, url)
        self.assertEqual(page.evaluate("history.state"), base_state)
        self.assertEqual(errors, [])

    def test_real_zip_and_resource_routes(self):
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
                self.sent.append(("send", code, body, ctype, extra))

        self_history = self.history
        row = self.by_name["files.zip"]
        fake = Fake({"app": "codex", "id": "c", "file": row["id"]})
        remote.Handler._reading_get(fake, "/api/file/zip")
        kind, status, body = fake.sent[-1]
        self.assertEqual((kind, status), ("json", 200))
        self.assertEqual(body["total"], 3)
        fake = Fake({"app": "codex", "id": "c", "file": row["id"], "v": "stale"})
        remote.Handler._reading_get(fake, "/api/file/zip")
        self.assertEqual(fake.sent[-1][1], 409)
        seven = self.by_name["thing.7z"]
        fake = Fake({"app": "codex", "id": "c", "file": seven["id"]})
        remote.Handler._reading_get(fake, "/api/file/zip")
        self.assertEqual(fake.sent[-1][1], 400)
        self.assertIn("只能下载", fake.sent[-1][2]["error"])
        bad = self.by_name["bad.zip"]
        fake = Fake({"app": "codex", "id": "c", "file": bad["id"]})
        remote.Handler._reading_get(fake, "/api/file/zip")
        self.assertEqual(fake.sent[-1][1], 400)
        self.assertIn("压缩包读不了", fake.sent[-1][2]["error"])

        page = self.by_name["note.md"]
        fake = Fake({"app": "codex", "id": "c", "file": page["id"], "path": "img/a.png"})
        remote.Handler._reading_get(fake, "/api/file/resource")
        kind, status, body, ctype, extra = fake.sent[-1]
        self.assertEqual((kind, status, ctype), ("send", 200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))
        for path, code in (("../outside.png", 403), ("secret.pem", 403), ("nope.png", 404)):
            fake = Fake({"app": "codex", "id": "c", "file": page["id"], "path": path})
            remote.Handler._reading_get(fake, "/api/file/resource")
            self.assertEqual(fake.sent[-1][1], code, path)
        html = self.by_name["page.html"]
        fake = Fake({"app": "codex", "id": "c", "file": html["id"], "path": "style.css"})
        remote.Handler._reading_get(fake, "/api/file/resource")
        self.assertEqual(fake.sent[-1][1], 200)
        self.assertEqual(fake.sent[-1][3], "text/css; charset=utf-8")


if __name__ == "__main__":
    unittest.main()
