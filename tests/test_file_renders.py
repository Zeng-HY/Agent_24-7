"""D segment: thumbnails, image sizes and the thumb route (temporary files only)."""
import io
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_history
import file_renders
from remote import Handler

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pillow_heif = None


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    file_renders.clear(tmp_path / "thumbs")
    yield
    file_renders.clear(tmp_path / "thumbs")


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


def image(root, name, size=(40, 20), color=(255, 0, 0, 128)):
    path = root / name
    Image.new("RGBA", size, color).save(path)
    return path


def test_sizes_and_thumbnails_for_common_formats(tmp_path):
    png = image(tmp_path, "a.png")
    jpg = tmp_path / "b.jpg"
    Image.new("RGB", (40, 20), (10, 20, 30)).save(jpg)
    gif = tmp_path / "c.gif"
    frames = [Image.new("RGB", (30, 10), (255, 0, 0)), Image.new("RGB", (30, 10), (0, 255, 0))]
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
    webp = tmp_path / "d.webp"
    Image.new("RGB", (25, 15), (0, 0, 255)).save(webp, "WEBP")

    for path in (png, jpg, gif, webp):
        assert file_renders.size(path, "image")[2] is True, path.name
        data = file_renders.thumbnail(path, "image", 320, cache_dir=tmp_path / "thumbs")
        with Image.open(io.BytesIO(data)) as made:
            assert made.format == "WEBP"
            assert max(made.size) <= 320

    if pillow_heif is not None:
        heic = tmp_path / "e.heic"
        Image.new("RGB", (30, 12), (1, 2, 3)).save(heic, format="HEIF")
        assert file_renders.size(heic, "image")[2] is True
        data = file_renders.thumbnail(heic, "image", 320, cache_dir=tmp_path / "thumbs")
        with Image.open(io.BytesIO(data)) as made:
            assert made.format == "WEBP"


def test_exif_orientation_is_applied(tmp_path):
    jpg = tmp_path / "rotated.jpg"
    im = Image.new("RGB", (40, 20), (200, 100, 50))
    exif = Image.Exif()
    exif[274] = 6  # rotate 90° clockwise for display
    im.save(jpg, exif=exif)
    width, height, thumb = file_renders.size(jpg, "image")
    assert (width, height, thumb) == (20, 40, True)
    data = file_renders.thumbnail(jpg, "image", 320, cache_dir=tmp_path / "thumbs")
    with Image.open(io.BytesIO(data)) as made:
        assert made.size == (20, 40)


def test_broken_and_too_large_images(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    assert file_renders.size(broken, "image") == (None, None, False)
    with pytest.raises(file_renders.RenderError):
        file_renders.thumbnail(broken, "image", 320, cache_dir=tmp_path / "thumbs")

    big = image(tmp_path, "big.png", (100, 100))
    assert file_renders.size(big, "image", max_pixels=10) == (100, 100, False)
    with pytest.raises(file_renders.RenderError):
        file_renders.thumbnail(big, "image", 320, cache_dir=tmp_path / "thumbs", max_pixels=10)


def test_svg_size_and_external_references_are_not_loaded(tmp_path, monkeypatch):
    svg = tmp_path / "pic.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        '<rect width="40" height="20" fill="red"/>'
        '<image href="http://example.test/evil.png" width="10" height="10"/>'
        '<use href="#shape"/>'
        '</svg>', encoding="utf-8")
    assert file_renders.size(svg, "svg") == (40, 20, True)
    seen = []
    real = file_renders.resvg_py.svg_to_bytes

    def fake(**kwargs):
        seen.append(kwargs["svg_string"])
        return real(**kwargs)

    monkeypatch.setattr(file_renders.resvg_py, "svg_to_bytes", fake)
    data = file_renders.thumbnail(svg, "svg", 320, cache_dir=tmp_path / "thumbs")
    assert data.startswith(b"RIFF") and seen
    assert "example.test" not in seen[0]
    assert "#shape" in seen[0]
    big = file_renders.thumbnail(svg, "svg", 4096, cache_dir=tmp_path / "thumbs")
    assert big.startswith(b"RIFF")


def test_bad_svg_and_large_svg(tmp_path):
    bad = tmp_path / "bad.svg"
    bad.write_text("<svg><broken>", encoding="utf-8")
    assert file_renders.size(bad, "svg") == (None, None, False)
    with pytest.raises(file_renders.RenderError):
        file_renders.thumbnail(bad, "svg", 320, cache_dir=tmp_path / "thumbs")

    svg = tmp_path / "big.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>', encoding="utf-8")
    assert file_renders.size(svg, "svg", max_svg=1) == (None, None, False)


def test_thumbnail_is_cached(tmp_path, monkeypatch):
    path = image(tmp_path, "cached.png")
    calls = []
    real = file_renders._render_image

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(file_renders, "_render_image", counting)
    first = file_renders.thumbnail(path, "image", 320, cache_dir=tmp_path / "thumbs")
    second = file_renders.thumbnail(path, "image", 320, cache_dir=tmp_path / "thumbs")
    assert first == second and len(calls) == 1
    assert file_renders.cache_path(path, 320, tmp_path / "thumbs").is_file()


def test_cache_cleanup_removes_the_oldest(tmp_path):
    cache = tmp_path / "thumbs"
    cache.mkdir()
    for index in range(3):
        entry = cache / f"{index}.webp"
        entry.write_bytes(b"x" * 10)
        entry.touch()
        import os
        os.utime(entry, (1000 + index, 1000 + index))
    file_renders.prune(cache, max_total=15)
    left = sorted(entry.name for entry in cache.iterdir())
    assert left == ["2.webp"]


def test_width_and_missing_validations(tmp_path):
    path = image(tmp_path, "a.png")
    for width in (100, 256, 4096):
        with pytest.raises(file_renders.RenderError):
            file_renders.thumbnail(path, "image", width, cache_dir=tmp_path / "thumbs")
    with pytest.raises(file_renders.RenderError):
        file_renders.thumbnail(tmp_path / "missing.png", "image", 320, cache_dir=tmp_path / "thumbs")


def test_history_rows_get_size_and_thumb(tmp_path):
    png = image(tmp_path, "a.png", (40, 20))
    svg = tmp_path / "a.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="30" height="10"/>', encoding="utf-8")
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"nope")
    history = history_for(tmp_path, [png, svg, broken])
    rows = {Path(row["path"]): row for row in history.list_files("codex", "c")["items"]}
    assert (rows[png]["w"], rows[png]["h"], rows[png]["thumb"]) == (40, 20, True)
    assert (rows[svg]["w"], rows[svg]["h"], rows[svg]["thumb"]) == (30, 10, True)
    assert rows[broken]["thumb"] is False and "w" not in rows[broken] and "h" not in rows[broken]


def fake_thumb_handler(history, query):
    sent = []
    fake = SimpleNamespace(history=history, server=SimpleNamespace(files=None), headers={},
                           _query=lambda: query,
                           _json=lambda body, status=200: sent.append((status, body)),
                           _send=lambda code, body, ctype, extra=None: sent.append((code, body, ctype, extra)),
                           send_response=lambda x: None, send_header=lambda k, v: None,
                           end_headers=lambda: None, close_connection=False)
    return fake, sent


def test_thumb_route_v_width_and_content_type(tmp_path, monkeypatch):
    monkeypatch.setattr(file_renders, "_cache_root", lambda cache_dir=None: tmp_path / "thumbs")
    png = image(tmp_path, "a.png")
    history = history_for(tmp_path, [png])
    row = history.list_files("codex", "c")["items"][0]
    fake, sent = fake_thumb_handler(history, {"app": "codex", "id": "c", "file": row["id"],
                                              "w": "320", "v": row["v"]})
    Handler._reading_get(fake, "/api/file/thumb")
    code, body, ctype, extra = sent[-1]
    assert code == 200 and ctype == "image/webp" and body.startswith(b"RIFF")
    assert extra == {"X-Content-Type-Options": "nosniff"}

    fake, sent = fake_thumb_handler(history, {"app": "codex", "id": "c", "file": row["id"],
                                              "w": "320", "v": "old"})
    Handler._reading_get(fake, "/api/file/thumb")
    assert sent[-1] == (409, {"error": "文件已变化"})

    fake, sent = fake_thumb_handler(history, {"app": "codex", "id": "c", "file": row["id"], "w": "999"})
    Handler._reading_get(fake, "/api/file/thumb")
    assert sent[-1][0] == 400 and "宽度" in sent[-1][1]["error"]

    text = tmp_path / "a.txt"
    text.write_text("hello", encoding="utf-8")
    history = history_for(tmp_path, [text])
    row = history.list_files("codex", "c")["items"][0]
    fake, sent = fake_thumb_handler(history, {"app": "codex", "id": "c", "file": row["id"], "w": "320"})
    Handler._reading_get(fake, "/api/file/thumb")
    assert sent[-1][0] == 400 and "缩略图" in sent[-1][1]["error"]
