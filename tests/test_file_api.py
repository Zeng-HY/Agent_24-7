"""C segment: text endpoint, content types, /api/file headers and v (temporary files only)."""
import io
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_history
import file_text
from remote import Handler


@pytest.fixture(autouse=True)
def fresh_caches():
    file_text.clear_cache()
    yield
    file_text.clear_cache()


def make(root: Path, name: str, data: bytes = b"fixture") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def history_for(root: Path, paths):
    links = " ".join(f"[{p.name}](<{p.as_posix()}>)" for p in paths)
    message = {"id": "m1", "role": "assistant", "text": links,
               "time": "2026-11-25T03:00:00Z", "activity_turn": "turn-1"}
    entry = SimpleNamespace(messages=[message], by_id={"m1": message}, state={"running": False},
                            offset=0, size=0, mtime=0, lock=threading.RLock(), context={},
                            path=root / "record.jsonl", cwd=str(root), app="codex", tid="c")
    item = {"app": "codex", "id": "c", "title": "测试", "folder": root.name,
            "cwd": str(root), "updated": 0}
    history = chat_history.History(secret="test-only")
    history.transcript = lambda app, tid: (item, entry)
    return history


def row_for(root: Path, path: Path):
    history = history_for(root, [path])
    rows = history.list_files("codex", "c")["items"]
    assert len(rows) == 1
    return history, rows[0]


def fake_handler(history, query):
    sent = []
    fake = SimpleNamespace(history=history, server=SimpleNamespace(files=None), headers={},
                           wfile=io.BytesIO(), sent=sent,
                           _query=lambda: query,
                           _json=lambda body, status=200: sent.append((status, body)),
                           send_response=lambda x: None,
                           send_header=lambda k, v: None, end_headers=lambda: None,
                           close_connection=False)
    fake._serve_result_file = lambda meta, download=False: sent.append(
        ("SERVED", {"meta": meta, "download": download}))
    return fake


def test_kind_and_view_follow_suffix_and_content(tmp_path):
    r_script = make(tmp_path, "plot.R", "# 注释\nx <- 1\n".encode("gb18030"))
    plain = make(tmp_path, "notes.foo", "hello\n".encode("utf-8"))
    binary = make(tmp_path, "blob.foo", b"abc\x00def")
    svg = make(tmp_path, "pic.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    gif = make(tmp_path, "anim.gif", b"GIF89a" + b"\x00" * 16)
    kotlin = make(tmp_path, "Main.kt", "fun main() {}\n".encode("utf-8"))
    xhtml = make(tmp_path, "page.xhtml", b"<html><body>x</body></html>")
    png = make(tmp_path, "chart.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    pdf = make(tmp_path, "doc.pdf", b"%PDF-1.7\n")
    archive = make(tmp_path, "bundle.zip", b"PK\x03\x04")

    expected = {
        r_script: ("text", "code", "r", "text/plain; charset=utf-8"),
        plain: ("text", "text", None, "text/plain; charset=utf-8"),
        binary: ("download", "none", None, "application/octet-stream"),
        svg: ("download", "svg", None, "application/octet-stream"),
        gif: ("download", "image", None, "image/gif"),
        kotlin: ("text", "code", "kotlin", "text/plain; charset=utf-8"),
        xhtml: ("text", "html", None, "application/octet-stream"),
        png: ("image", "image", None, "image/png"),
        pdf: ("pdf", "pdf", None, "application/pdf"),
        archive: ("download", "archive", None, "application/octet-stream"),
    }
    history = history_for(tmp_path, list(expected))
    rows = {Path(row["path"]): row for row in history.list_files("codex", "c")["items"]}
    for path, (kind, view, lang, mime) in expected.items():
        row = rows[path]
        assert (row["kind"], row["view"], row["lang"], row["mime"]) == (kind, view, lang, mime), path.name
        assert row["thumb"] is False


def test_large_text_keeps_code_view_but_not_text_kind(tmp_path):
    line = "x <- 1 # 中文\n"
    data = (line * ((2 << 20) // len(line.encode("gb18030")) + 200)).encode("gb18030")
    path = make(tmp_path, "big.R", data)
    history, row = row_for(tmp_path, path)
    assert row["kind"] == "download"
    assert row["view"] == "code" and row["lang"] == "r"


def test_file_text_route_encodings_and_truncation(tmp_path):
    utf8 = make(tmp_path, "a.txt", "第一行\nsecond\n".encode("utf-8"))
    bom = make(tmp_path, "b.txt", b"\xef\xbb\xbf" + "第一行\nsecond\n".encode("utf-8"))
    utf16 = make(tmp_path, "c.txt", "第一行\nsecond\n".encode("utf-16"))
    gb = make(tmp_path, "d.R", "# 中文注释\nx <- 1\n".encode("gb18030"))
    long = make(tmp_path, "long.txt",
                (("一段很长的文字" * 8 + "\n") * 80000).encode("utf-8"))
    binary = make(tmp_path, "e.bin", b"abc\x00def")

    for path, encoding in ((utf8, "utf-8"), (bom, "utf-8-sig"), (utf16, "utf-16"), (gb, "gb18030")):
        history = history_for(tmp_path, [path])
        fid = history.list_files("codex", "c")["items"][0]["id"]
        fake = fake_handler(history, {"app": "codex", "id": "c", "file": fid})
        Handler._reading_get(fake, "/api/file/text")
        status, body = fake.sent[-1]
        assert status == 200
        assert body["encoding"] == encoding and body["truncated"] is False
        assert body["text"] and body["name"] == path.name
        assert body["total_size"] == path.stat().st_size and body["lines"] > 0
        if path == gb:
            assert body["lang"] == "r"

    history = history_for(tmp_path, [long])
    fid = history.list_files("codex", "c")["items"][0]["id"]
    fake = fake_handler(history, {"app": "codex", "id": "c", "file": fid})
    Handler._reading_get(fake, "/api/file/text")
    status, body = fake.sent[-1]
    assert status == 200 and body["truncated"] is True
    assert body["total_size"] == long.stat().st_size
    assert body["text"].endswith("\n") and len(body["text"].encode("utf-8")) <= 2 << 20

    history = history_for(tmp_path, [binary])
    fid = history.list_files("codex", "c")["items"][0]["id"]
    fake = fake_handler(history, {"app": "codex", "id": "c", "file": fid})
    Handler._reading_get(fake, "/api/file/text")
    status, body = fake.sent[-1]
    assert status == 400 and "预览" in body["error"]


def test_meta_has_v_view_mime_lang(tmp_path):
    path = make(tmp_path, "Main.kt", "fun main() {}\n".encode("utf-8"))
    history, row = row_for(tmp_path, path)
    fake = fake_handler(history, {"app": "codex", "id": "c", "file": row["id"]})
    Handler._reading_get(fake, "/api/file/meta")
    status, body = fake.sent[-1]
    assert status == 200
    assert body["v"] == row["v"] and body["v"]
    assert body["view"] == "code" and body["lang"] == "kotlin"
    assert body["mime"] == "text/plain; charset=utf-8"


def test_executable_types_are_always_attachments(tmp_path):
    html = make(tmp_path, "page.html", b"<html>hi</html>")
    svg = make(tmp_path, "pic.svg", b"<svg></svg>")
    js = make(tmp_path, "app.js", b"alert(1)")
    xml = make(tmp_path, "data.xml", b"<x/>")
    png = make(tmp_path, "chart.png", b"\x89PNG\r\n\x1a\n")
    audio = make(tmp_path, "sound.mp3", b"ID3")
    text = make(tmp_path, "a.txt", b"hello")
    history = history_for(tmp_path, [html, svg, js, xml, png, audio, text])
    rows = {Path(row["path"]): row for row in history.list_files("codex", "c")["items"]}
    for path in (html, svg, js, xml, png, audio, text):
        meta = history.file("codex", "c", rows[path]["id"])
        headers = {}
        handler = SimpleNamespace(headers={}, wfile=io.BytesIO(), send_response=lambda x: None,
                                  send_header=lambda k, v: headers.update({k: v}),
                                  end_headers=lambda: None)
        Handler._serve_result_file(handler, meta)
        if path in (html, svg, js, xml):
            assert headers["Content-Type"] == "application/octet-stream", path.name
            assert headers["Content-Disposition"].startswith("attachment"), path.name
        elif path in (png, audio, text):
            assert headers["Content-Disposition"].startswith("inline"), path.name


def test_stale_v_is_409(tmp_path):
    path = make(tmp_path, "a.txt", b"hello")
    history, row = row_for(tmp_path, path)
    fake = fake_handler(history, {"app": "codex", "id": "c", "file": row["id"], "v": "stale"})
    Handler._reading_get(fake, "/api/file")
    assert fake.sent[-1] == (409, {"error": "文件已变化"})
    fake = fake_handler(history, {"app": "codex", "id": "c", "file": row["id"], "v": row["v"]})
    Handler._reading_get(fake, "/api/file")
    assert fake.sent[-1][0] == "SERVED"
