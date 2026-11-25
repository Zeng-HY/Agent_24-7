"""Reading a file as text for the phone (docs/handoff-file-preview.md §5.4, segment C).

The first 8 KB decide: no NUL and decodes as UTF-8 (with or without BOM), UTF-16 with
BOM, or GB18030.  The probe (encoding of the head) is cached for 5 s like the other file
information; the whole text is read only when a phone asks for it.
"""
from __future__ import annotations

import ntpath
import os
import threading
import time

HEAD = 8 << 10
LIMIT = 2 << 20
TTL = 5.0
_CACHE_LIMIT = 4096
_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[float, str | None]] = {}

LANGUAGE = {
    ".r": "r", ".py": "python", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".xml": "xml", ".sql": "sql", ".sh": "bash", ".ps1": "powershell", ".kt": "kotlin",
    ".kts": "kotlin", ".swift": "swift", ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".hpp": "cpp", ".cs": "csharp", ".go": "go", ".rs": "rust", ".css": "css", ".scss": "css",
    ".less": "css", ".md": "markdown", ".markdown": "markdown", ".ini": "ini", ".cfg": "ini",
    ".conf": "ini", ".toml": "ini", ".diff": "diff", ".patch": "diff", ".tex": "latex",
}


def lang_for(suffix: str) -> str | None:
    if not suffix:
        return None
    if not suffix.startswith("."):
        suffix = "." + suffix
    return LANGUAGE.get(suffix.lower())


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _stat(path):
    try:
        return os.stat(path)
    except (OSError, ValueError):
        return None


def _decodes(data: bytes, encoding: str) -> bool:
    if not data:
        return True
    cuts = (0, 1, 2, 3) if encoding in ("utf-8", "gb18030") else (0,)
    for cut in cuts:
        try:
            data[:len(data) - cut if cut else len(data)].decode(encoding)
            return True
        except (UnicodeDecodeError, ValueError):
            continue
    return False


def _detect(head: bytes) -> str | None:
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if b"\x00" in head:
        return None
    for encoding in ("utf-8", "gb18030"):
        if _decodes(head, encoding):
            return encoding
    return None


def _cache_set(key, encoding: str | None, expiry: float) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (expiry, encoding)


def probe(path, st=None, clock=time.monotonic) -> str | None:
    """The encoding of the file's first 8 KB, or None when it is not text."""
    st = st or _stat(path)
    if st is None:
        return None
    key = (ntpath.normcase(str(path)), st.st_size, st.st_mtime_ns)
    now = clock()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
    try:
        with open(path, "rb") as source:
            head = source.read(HEAD)
    except (OSError, ValueError):
        return None
    encoding = _detect(head)
    _cache_set(key, encoding, now + TTL)
    return encoding


def _decode(data: bytes, encoding: str, partial: bool):
    if not data:
        return ""
    cuts = (0, 1, 2, 3) if encoding in ("utf-8", "utf-8-sig", "gb18030") else (0, 2)
    for cut in cuts:
        body = data[:len(data) - cut] if cut else data
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            if not partial:
                continue
    return None


def read(path, st=None, clock=time.monotonic):
    """{text, encoding, truncated, total_size, lines} or None when this is not text."""
    st = st or _stat(path)
    if st is None:
        return None
    encoding = probe(path, st, clock)
    if encoding is None:
        return None
    size = st.st_size
    truncated = size > LIMIT
    want = min(size, LIMIT)
    try:
        with open(path, "rb") as source:
            data = source.read(want)
    except (OSError, ValueError):
        return None
    text = _decode(data, encoding, truncated)
    if text is None and encoding != "utf-16":
        # An English opening (valid UTF-8) can hide GBK Chinese later in the file: this is
        # the Chinese-Windows R script case.  Try GB18030 on the whole read and remember it.
        body = data[3:] if encoding == "utf-8-sig" and data.startswith(b"\xef\xbb\xbf") else data
        text = _decode(body, "gb18030", truncated)
        if text is not None:
            encoding = "gb18030"
            key = (ntpath.normcase(str(path)), st.st_size, st.st_mtime_ns)
            _cache_set(key, encoding, clock() + TTL)
    if text is None:
        return None
    if truncated:
        at = text.rfind("\n")
        if at >= 0:
            text = text[:at + 1]
    return {"text": text, "encoding": encoding, "truncated": truncated,
            "total_size": size, "lines": len(text.splitlines())}
