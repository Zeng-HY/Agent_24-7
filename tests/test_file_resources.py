"""E segment: zip directory and page resources (temporary files only)."""
import io
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_history
import file_resources
from remote import Handler


@pytest.fixture(autouse=True)
def fresh():
    file_resources.clear_cache()
    yield
    file_resources.clear_cache()


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


def with_page(root: Path, name: str, text: str):
    pages = [make(root, name, text.encode("utf-8"))]
    history = history_for(root, pages)
    row = history.list_files("codex", "c")["items"][0]
    return history, pages[0], row


def fake(history, query, sent):
    return SimpleNamespace(history=history, server=SimpleNamespace(files=None), headers={},
                           _query=lambda: query,
                           _json=lambda body, status=200: sent.append((status, body)),
                           _send=lambda code, body, ctype, extra=None: sent.append((code, body, ctype, extra)),
                           send_response=lambda x: None, send_header=lambda k, v: None,
                           end_headers=lambda: None, close_connection=False)


def get_json(history, query):
    sent = []
    Handler._reading_get(fake(history, query, sent), "/api/file/zip")
    return sent[-1]


def get_resource(history, query):
    sent = []
    Handler._reading_get(fake(history, query, sent), "/api/file/resource")
    return sent[-1]


def gbk_zip(root: Path, name_bytes: bytes) -> Path:
    placeholder = b"x" * len(name_bytes)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(placeholder.decode("ascii"), b"hello")
    raw = buffer.getvalue().replace(placeholder, name_bytes)
    path = root / "gbk.zip"
    path.write_bytes(raw)
    return path


def test_zip_lists_utf8_gbk_dirs_and_truncates(tmp_path):
    utf8 = tmp_path / "utf8.zip"
    with zipfile.ZipFile(utf8, "w") as archive:
        archive.writestr("目录/文件.txt", b"hello")
        archive.writestr("empty/", b"")
    listing = file_resources.zip_entries(utf8)
    assert listing["total"] == 2 and listing["truncated"] is False
    assert {entry["name"] for entry in listing["entries"]} == {"目录/文件.txt", "empty/"}
    assert any(entry["dir"] for entry in listing["entries"])

    gbk = gbk_zip(tmp_path, "中文说明.txt".encode("gb18030"))
    assert file_resources.zip_entries(gbk)["entries"][0]["name"] == "中文说明.txt"

    many = tmp_path / "many.zip"
    with zipfile.ZipFile(many, "w") as archive:
        for index in range(2001):
            archive.writestr(f"f{index}.txt", b"")
    listing = file_resources.zip_entries(many)
    assert listing["total"] == 2001 and len(listing["entries"]) == 2000 and listing["truncated"] is True


def test_zip_modified_time_is_the_local_wall_clock(tmp_path):
    path = tmp_path / "time.zip"
    stamp = (2024, 1, 2, 3, 4, 6)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("a.txt", stamp), b"hello")
    listing = file_resources.zip_entries(path)
    assert listing["entries"][0]["modified"] == int(datetime(*stamp).timestamp() * 1000)


def test_bad_zip_and_7z_routes(tmp_path):
    bad = make(tmp_path, "bad.zip", b"not a zip")
    with pytest.raises(file_resources.ResourceError):
        file_resources.zip_entries(bad)

    for name in ("thing.7z", "thing.rar"):
        path = make(tmp_path, name, b"archive")
        history = history_for(tmp_path, [path])
        row = history.list_files("codex", "c")["items"][0]
        status, body = get_json(history, {"app": "codex", "id": "c", "file": row["id"]})
        assert status == 400 and "只能下载" in body["error"]

    text = make(tmp_path, "notes.txt", b"text")
    history = history_for(tmp_path, [text])
    row = history.list_files("codex", "c")["items"][0]
    status, body = get_json(history, {"app": "codex", "id": "c", "file": row["id"]})
    assert status == 400 and "只能下载" in body["error"]


def test_zip_route_v_and_listing(tmp_path):
    archive = tmp_path / "files.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", b"hello")
    history = history_for(tmp_path, [archive])
    row = history.list_files("codex", "c")["items"][0]
    status, body = get_json(history, {"app": "codex", "id": "c", "file": row["id"]})
    assert status == 200 and body["total"] == 1 and body["entries"][0]["name"] == "a.txt"
    status, body = get_json(history, {"app": "codex", "id": "c", "file": row["id"], "v": "old"})
    assert status == 409


def test_page_resources_from_markdown_and_html(tmp_path):
    make(tmp_path, "img/a.png", b"\x89PNG\r\n\x1a\n")
    make(tmp_path, "css/style.css", b"body{}")
    make(tmp_path, "fonts/f.woff2", b"font")
    make(tmp_path, "js/app.js", b"alert(1)")
    make(tmp_path, "pic.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    page_text = (
        "![图](img/a.png)\n\n"
        "<link rel=\"stylesheet\" href=\"css/style.css\">\n"
        "<style>@font-face { src: url('fonts/f.woff2'); }</style>\n"
        "<script src=\"js/app.js\"></script>\n"
        "\n"
        "![svg](pic.svg)\n"
        "[说明](missing.txt)\n"
    )
    history, page, row = with_page(tmp_path, "doc.md", page_text)
    for path, expected in (("img/a.png", "image/png"), ("css/style.css", "text/css; charset=utf-8"),
                           ("fonts/f.woff2", "font/woff2")):
        code, body, ctype, extra = get_resource(history, {"app": "codex", "id": "c",
                                                          "file": row["id"], "path": path})
        assert code == 200 and ctype == expected, path
        assert extra["X-Content-Type-Options"] == "nosniff"
    code, body = get_resource(history, {"app": "codex", "id": "c", "file": row["id"],
                                        "path": "js/app.js"})
    assert code == 403
    result = get_resource(history, {"app": "codex", "id": "c",
                                    "file": row["id"], "path": "pic.svg"})
    assert len(result) == 4, result
    code, body, ctype, extra = result
    assert code == 200 and ctype == "application/octet-stream"
    assert extra["Content-Disposition"].startswith("attachment")
    assert extra["X-Content-Type-Options"] == "nosniff"

    html_page = tmp_path / "doc.html"
    html_page.write_text('<script src="js/app.js"></script><img src="img/a.png">', encoding="utf-8")
    history = history_for(tmp_path, [html_page])
    row = history.list_files("codex", "c")["items"][0]
    code, body, ctype, extra = get_resource(history, {"app": "codex", "id": "c",
                                                      "file": row["id"], "path": "js/app.js"})
    assert code == 200 and ctype == "application/javascript; charset=utf-8"


def test_resource_rejections(tmp_path):
    make(tmp_path, "img/a.png", b"png")
    make(tmp_path, "big.png", b"x" * ((8 << 20) + 1))
    make(tmp_path, ".env", b"SECRET=1")
    make(tmp_path, "notes.txt", b"text")
    make(tmp_path, "sub/ok.png", b"png")
    text = "\n".join([
        "![a](img/a.png)", "[t](notes.txt)", "[big](big.png)", "[env](.env)",
        "[sub](sub/ok.png)", "[outside](../secret.txt)", "[abs](C:/secret.txt)",
    ])
    history, page, row = with_page(tmp_path, "doc.md", text)
    for path, expected in (("notes.txt", 403), ("big.png", 413), (".env", 403),
                           ("../secret.txt", 403), ("C:/secret.txt", 400),
                           ("not-mentioned.png", 403), ("sub/../img/a.png", 200)):
        result = get_resource(history, {"app": "codex", "id": "c", "file": row["id"], "path": path})
        code = result[0]
        assert code == expected, (path, code, result[1])
    code, body, ctype, extra = get_resource(history, {"app": "codex", "id": "c",
                                                      "file": row["id"], "path": "sub/ok.png"})
    assert code == 200


def test_the_65th_reference_is_refused(tmp_path):
    for index in range(65):
        make(tmp_path, f"img/r{index}.png", b"png")
    text = "\n".join(f"![r](img/r{index}.png)" for index in range(65))
    history, page, row = with_page(tmp_path, "doc.md", text)
    first = get_resource(history, {"app": "codex", "id": "c", "file": row["id"], "path": "img/r63.png"})
    assert first[0] == 200
    last = get_resource(history, {"app": "codex", "id": "c", "file": row["id"], "path": "img/r64.png"})
    assert last[0] == 403 and "第 65" in last[1]["error"]


def test_page_parse_is_cached(tmp_path, monkeypatch):
    make(tmp_path, "img/a.png", b"png")
    history, page, row = with_page(tmp_path, "doc.md", "![a](img/a.png)")
    calls = []
    real = Path.read_text

    def counting(self, *args, **kwargs):
        if self == page:
            calls.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    for _ in range(2):
        code, body, ctype, extra = get_resource(history, {"app": "codex", "id": "c",
                                                          "file": row["id"], "path": "img/a.png"})
        assert code == 200
    assert len(calls) == 1
