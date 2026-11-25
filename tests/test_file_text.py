"""file_text: content sniffing, decoding, truncation (docs/handoff-file-preview.md §5.4)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_text


@pytest.fixture(autouse=True)
def fresh_cache():
    file_text.clear_cache()
    yield
    file_text.clear_cache()


def write(tmp_path, name, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("name,data,encoding", [
    ("utf8.txt", "第一行\nsecond\n".encode("utf-8"), "utf-8"),
    ("utf8bom.txt", b"\xef\xbb\xbf" + "第一行\nsecond\n".encode("utf-8"), "utf-8-sig"),
    ("utf16.txt", "第一行\nsecond\n".encode("utf-16"), "utf-16"),
    ("gb.txt", "第一行\nsecond\n".encode("gb18030"), "gb18030"),
])
def test_probe_and_read_encodings(tmp_path, name, data, encoding):
    path = write(tmp_path, name, data)
    assert file_text.probe(path) == encoding
    made = file_text.read(path)
    assert made["encoding"] == encoding
    assert made["truncated"] is False
    assert made["total_size"] == len(data)
    assert "第一行" in made["text"] and "second" in made["text"]
    assert made["lines"] == 2


def test_gb18030_r_script_and_csv(tmp_path):
    r = write(tmp_path, "plot.R", "# 中文注释\nx <- 1\n".encode("gb18030"))
    csv = write(tmp_path, "数据.csv", "名称,数量\n苹果,2\n".encode("gb18030"))
    assert file_text.probe(r) == "gb18030" and "中文注释" in file_text.read(r)["text"]
    assert file_text.probe(csv) == "gb18030" and "苹果" in file_text.read(csv)["text"]


def test_non_text(tmp_path):
    for name, data in (("nulfile.bin", b"abc\x00def"), ("bad.bin", b"\xff\xff\xff\xff")):
        path = write(tmp_path, name, data)
        assert file_text.probe(path) is None
        assert file_text.read(path) is None


def test_empty_file_is_text(tmp_path):
    path = write(tmp_path, "empty.txt", b"")
    made = file_text.read(path)
    assert made["text"] == "" and made["lines"] == 0 and made["total_size"] == 0


def test_large_text_is_cut_at_a_line_end(tmp_path):
    line = "一段很长的文字" * 8 + "\n"
    data = (line * ((2 << 20) // len(line.encode("utf-8")) + 200)).encode("utf-8")
    path = write(tmp_path, "long.txt", data)
    made = file_text.read(path)
    assert made["truncated"] is True
    assert made["total_size"] == len(data)
    assert made["text"].endswith("\n")
    assert len(made["text"].encode("utf-8")) <= file_text.LIMIT
    assert 0 < made["lines"]


def test_probe_is_cached_for_five_seconds(tmp_path):
    path = write(tmp_path, "cache.txt", b"hello")
    before = path.stat()
    clock = [10.0]
    assert file_text.probe(path, clock=lambda: clock[0]) == "utf-8"
    path.write_bytes(b"h\x00llo")  # same size, then the same mtime: the cache key is unchanged
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert file_text.probe(path, clock=lambda: clock[0]) == "utf-8"
    clock[0] += 6
    assert file_text.probe(path, clock=lambda: clock[0]) is None


def test_language_table():
    assert file_text.lang_for(".r") == "r"
    assert file_text.lang_for("kt") == "kotlin"
    assert file_text.lang_for(".unknown") is None
