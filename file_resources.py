"""Zip listings and a Markdown/HTML page's own resources (docs/handoff-file-preview.md §5.6, §5.7).

A page may use a file only when its own words name it, it stays under the page's folder,
it is an image, CSS, font (HTML may also use JS), and it passes file_policy.  The first
64 different references are the whole allowance; no counter is kept on the computer.
"""
from __future__ import annotations

import html
import ntpath
import os
import posixpath
import re
import threading
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

import file_policy

MAX_ZIP_ENTRIES = 2000
MAX_REFS = 64
MAX_RESOURCE = 8 << 20

PARSER = MarkdownIt("commonmark", {"html": True}).enable("table")
_TAG_ATTR = re.compile(r"""\b(?:src|href)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""", re.I)
_CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)'"\s]+))\s*\)""", re.I)

IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif",
         ".avif", ".svg"}
CSS = {".css"}
FONT = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
JS = {".js", ".mjs"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".gif": "image/gif", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff",
              ".heic": "image/heic", ".heif": "image/heic", ".avif": "image/avif"}
FONT_MIME = {".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
             ".eot": "application/vnd.ms-fontobject"}

_lock = threading.Lock()
_ref_cache: dict[tuple, list[tuple[str, str]]] = {}
_zip_cache: dict[tuple, dict] = {}
_CACHE_LIMIT = 256


class ResourceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def clear_cache() -> None:
    with _lock:
        _ref_cache.clear()
        _zip_cache.clear()


def _stat(path):
    try:
        return os.stat(path)
    except (OSError, ValueError):
        return None


def _zip_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except (UnicodeEncodeError, ValueError):
        return name
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError:
        return name


def _zip_time(info: zipfile.ZipInfo) -> int:
    try:
        return int(datetime(*info.date_time, tzinfo=timezone.utc).timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return 0


def zip_entries(path, st=None, max_entries: int = MAX_ZIP_ENTRIES) -> dict:
    """The zip's central directory only; no member is extracted or read."""
    st = st or _stat(path)
    if st is None:
        raise ResourceError("文件已移动或删除", 404)
    key = (ntpath.normcase(str(path)), st.st_size, st.st_mtime_ns)
    with _lock:
        cached = _zip_cache.get(key)
    if cached is not None:
        return cached
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile:
        raise ResourceError("这个压缩包读不了，可能已经损坏", 400) from None
    except (OSError, ValueError, RuntimeError):
        raise ResourceError("这个压缩包读不了", 400) from None
    entries = [{"name": _zip_name(info), "size": info.file_size, "packed": info.compress_size,
                "modified": _zip_time(info), "dir": info.is_dir()}
               for info in infos[:max_entries]]
    result = {"entries": entries, "total": len(infos), "truncated": len(infos) > max_entries}
    with _lock:
        if len(_zip_cache) >= _CACHE_LIMIT:
            _zip_cache.pop(next(iter(_zip_cache)))
        _zip_cache[key] = result
    return result


def _clean_ref(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    value = html.unescape(raw).strip()
    if len(value) >= 2 and value[0] == "<" and value[-1] == ">":
        value = value[1:-1]
    value = unquote(value).replace("\\", "/")
    value = value.split("#", 1)[0].split("?", 1)[0].strip()
    if not value or value.startswith(("/", "//")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return None
    value = unicodedata.normalize("NFC", value)
    value = posixpath.normpath(value)
    if value in ("", "."):
        return None
    return value


def _add_ref(refs, seen, raw):
    value = _clean_ref(raw)
    if value is None:
        return
    key = value.casefold()
    if key not in seen:
        seen.add(key)
        refs.append((key, value))


def _scan_html(text: str, refs, seen):
    for match in _TAG_ATTR.finditer(text):
        raw = next((group for group in match.groups() if group is not None), "")
        _add_ref(refs, seen, raw)
    for match in _CSS_URL.finditer(text):
        raw = next((group for group in match.groups() if group is not None), "")
        _add_ref(refs, seen, raw)


def _page_refs(path, st) -> list[tuple[str, str]]:
    key = (ntpath.normcase(str(path)), st.st_size, st.st_mtime_ns)
    with _lock:
        cached = _ref_cache.get(key)
    if cached is not None:
        return cached
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise ResourceError("这个文件读不了", 404) from None
    refs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for block in PARSER.parse(text):
        if block.type == "html_block" and block.content:
            _scan_html(block.content, refs, seen)
        for token in block.children or []:
            if token.type == "link_open":
                _add_ref(refs, seen, token.attrGet("href") or "")
            elif token.type == "image":
                _add_ref(refs, seen, token.attrGet("src") or "")
            elif token.type == "html_inline" and token.content:
                _scan_html(token.content, refs, seen)
    with _lock:
        if len(_ref_cache) >= _CACHE_LIMIT:
            _ref_cache.pop(next(iter(_ref_cache)))
        _ref_cache[key] = refs
    return refs


def _requested(raw) -> str | None:
    value = _clean_ref(raw)
    if value is None:
        return None
    if value.startswith(("../", "/")) or value == "..":
        raise ResourceError("这个地址跑到页面文件夹外面了", 403)
    return value


def _under(path: Path, folder: Path) -> bool:
    try:
        common = os.path.commonpath([str(path), str(folder)])
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(str(folder))


def _content_type(suffix: str) -> tuple[str, bool]:
    if suffix in IMAGE_MIME:
        return IMAGE_MIME[suffix], False
    if suffix == ".svg":
        return "application/octet-stream", True
    if suffix in CSS:
        return "text/css; charset=utf-8", False
    if suffix in JS:
        return "application/javascript; charset=utf-8", False
    if suffix in FONT_MIME:
        return FONT_MIME[suffix], False
    return "application/octet-stream", True


def resolve_resource(page_path, page_view: str, requested, st=None):
    """(path, mime, attachment, size) for a relative resource the page itself names."""
    if page_view not in ("markdown", "html"):
        raise ResourceError("只有 Markdown 或 HTML 页面能带附属资源", 400)
    st = st or _stat(page_path)
    if st is None:
        raise ResourceError("页面已移动或删除", 404)
    refs = _page_refs(page_path, st)
    wanted = _requested(requested)
    if wanted is None:
        raise ResourceError("资源地址无效", 400)
    by_norm = {norm: rel for norm, rel in refs}
    norm = wanted.casefold()
    if norm not in by_norm:
        raise ResourceError("这个页面没有引用这个文件", 403)
    allowed = {ref_norm for ref_norm, _ in refs[:MAX_REFS]}
    if norm not in allowed:
        raise ResourceError("这是页面引用的第 65 个及以后的资源，不提供", 403)
    relative = by_norm[norm]
    folder = Path(page_path).parent.resolve()
    try:
        target = (folder / relative).resolve()
    except (OSError, ValueError):
        raise ResourceError("资源地址无效", 400) from None
    if not _under(target, folder):
        raise ResourceError("这个地址跑到页面文件夹外面了", 403)
    reason, stat_result = file_policy.inspect(target, fresh=True)
    if reason == "missing":
        raise ResourceError("电脑上找不到这个文件", 404)
    if reason == "folder":
        raise ResourceError("这是文件夹，不是文件", 400)
    if reason == "not_local":
        raise ResourceError("这个文件不在本机磁盘上", 403)
    if reason == "denied":
        raise ResourceError("出于安全，遥应不让手机读这个文件", 403)
    suffix = target.suffix.lower()
    if not (suffix in IMAGE or suffix in CSS or suffix in FONT or (page_view == "html" and suffix in JS)):
        raise ResourceError("这种类型不能作为页面附属资源", 403)
    if stat_result is None or stat_result.st_size > MAX_RESOURCE:
        raise ResourceError("这个附属文件超过 8 MB", 413)
    mime, attachment = _content_type(suffix)
    return target, mime, attachment, stat_result.st_size
