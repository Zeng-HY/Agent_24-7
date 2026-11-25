"""Which files an answer may offer to a phone (docs/handoff-file-preview.md §4, segment B).

Pure: no global state, no I/O except the injected ``stat``.  Network and foreign-system
paths are refused before any stat.  The drive list and home folder are injected by tests.
"""
from __future__ import annotations

import ntpath
import os
import re
import stat as stat_module
import threading
import time
from pathlib import Path

# §5.9: a drive list is asked of Windows once in 30 s; one path's check is reused for 5 s.
DRIVES_TTL = 30.0
INSPECT_TTL = 5.0
_CACHE_LIMIT = 4096
_drive_lock = threading.Lock()
_drive_cache: tuple[float, list[str] | None] = (0.0, None)
_inspect_lock = threading.Lock()
_inspect_cache: dict[tuple, tuple[float, str | None, object]] = {}

# Windows refuses these as file names even with an extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx")
_SECRET_NAMES = ("id_rsa", "id_ed25519")
_BROWSER_FILES = ("login data", "cookies", "local state")
_BROWSER_MARKERS = ("\\google\\chrome\\", "\\microsoft\\edge\\", "\\bravesoftware\\", "\\chromium\\",
                    "\\mozilla\\firefox\\", "\\user data\\", "\\opera software\\")


def _default_drives(clock=time.monotonic) -> list[str]:
    now = clock()
    with _drive_lock:
        at, found = _drive_cache
        if found is not None and now - at < DRIVES_TTL:
            return list(found)
    import pc_files
    found = list(pc_files.local_drives())  # never under the lock: a slow card reader must not block others
    with _drive_lock:
        globals()["_drive_cache"] = (now, list(found))
    return found


def clear_cache() -> None:
    """For tests and a fresh request after the drives changed; production relies on the TTLs."""
    global _drive_cache
    with _drive_lock:
        _drive_cache = (0.0, None)
    with _inspect_lock:
        _inspect_cache.clear()


def _path(value) -> str:
    try:
        return os.fspath(value)
    except TypeError:
        return ""


def _norm(value) -> str:
    return os.path.normcase(ntpath.normpath(_path(value).strip()))


def _under(path: str, root: str) -> bool:
    if not root:
        return False
    path, root = _norm(path), _norm(root).rstrip("\\/")
    return path == root or path.startswith(root + "\\") or path.startswith(root + "/")


def _deny_name(name: str) -> bool:
    low = name.casefold()
    if low in (".env",) or (low.startswith(".env.") and low not in (".env.example", ".env.sample")):
        return True
    if low == "remote_config.json" or any(low.startswith(name) for name in _SECRET_NAMES):
        return True
    if low.endswith(_SECRET_SUFFIXES):
        return True
    return low.split(".", 1)[0].upper() in _RESERVED


def _denied_places(path: str, home: str, data: str) -> bool:
    low = path.casefold().replace("/", "\\")
    if data and _under(path, data):
        return True
    if data and _under(path, os.path.join(data, "cache")):
        return True
    if home:
        places = [os.path.join(home, name) for name in
                  (".teleply-updates", ".android\\teleply-signing", ".ssh", ".gnupg", ".aws",
                   ".config\\gh")]
        places += [os.path.join(home, name) for name in
                   (".codex\\auth.json", ".claude\\.credentials.json", ".dsh\\.credentials.yaml",
                    ".kube\\config", ".docker\\config.json", ".git-credentials", ".npmrc", ".pypirc")]
        if any(_under(path, place) for place in places):
            return True
        gemini = os.path.join(home, ".gemini")
        if _under(path, gemini):
            allowed = (os.path.join(gemini, "antigravity", "brain"),
                       os.path.join(gemini, "antigravity-cli", "brain"))
            if not any(_under(path, place) for place in allowed):
                return True
    if "\\windows\\system32\\config\\" in low:
        return True
    if "\\appdata\\" in low and any(marker in low for marker in
                                    ("\\microsoft\\credentials\\", "\\microsoft\\protect\\")):
        return True
    if "\\appdata\\" in low and (low.endswith("\\microsoft\\credentials")
                                 or low.endswith("\\microsoft\\protect")):
        return True
    name = os.path.basename(path).casefold()
    if name in _BROWSER_FILES and any(marker in low for marker in _BROWSER_MARKERS):
        return True
    return False


def _decide(target: Path, allowed: set[str], home: str, data: str, stat) -> tuple[str | None, object]:
    if (target.drive + "\\").upper() not in {value + "\\" for value in allowed}:
        return "not_local", None  # another computer's drive, or a network drive that is not listed
    if ":" in str(target)[2:]:
        return "denied", None  # an alternate data stream
    if _deny_name(target.name):
        return "denied", None
    if _denied_places(str(target), home, data):
        return "denied", None
    try:
        st = stat(str(target))
    except (OSError, ValueError):
        return "missing", None
    try:
        if target.resolve() != target.absolute():
            return "denied", st  # a link or junction points somewhere else
    except (OSError, ValueError):
        return "denied", st
    if stat_module.S_ISDIR(st.st_mode):
        return "folder", st
    if not stat_module.S_ISREG(st.st_mode):
        return "denied", st
    return None, st


def inspect(path, *, drives=None, home=None, data=None, stat=os.stat, clock=time.monotonic,
            fresh=False):
    """(reason, stat_result): reason is one of missing/folder/not_local/denied, or None when allowed."""
    raw = _path(path).strip()
    if not raw or "\x00" in raw or len(raw) > 4096:
        return "denied", None
    if raw.startswith("\\\\?\\") and not raw[4:].lower().startswith("unc\\"):
        raw = raw[4:]  # a long local path, not a network share
    elif raw.startswith(("\\\\", "//")):
        return "not_local", None  # a network share, never stat it
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw):
        return "not_local", None  # a URL is not a path
    try:
        target = Path(ntpath.normpath(raw))
    except (OSError, ValueError):
        return "denied", None
    if not target.is_absolute() or not target.drive:
        return "not_local", None
    allowed = {str(d).rstrip("\\/").upper()
               for d in (list(drives) if drives is not None else _default_drives(clock))}
    home = _path(home) if home is not None else str(Path.home())
    if data is None:
        from app_paths import DATA
        data = str(DATA)
    data = _path(data)
    cacheable = stat is os.stat  # an injected guard must see every call
    key = (ntpath.normcase(str(target)), tuple(sorted(allowed)),
           ntpath.normcase(home), ntpath.normcase(data))
    now = clock()
    if cacheable and not fresh:
        with _inspect_lock:
            cached = _inspect_cache.get(key)
            if cached is not None and cached[0] > now:
                return cached[1], cached[2]
    reason, st = _decide(target, allowed, home, data, stat)
    if cacheable:
        with _inspect_lock:
            if len(_inspect_cache) >= _CACHE_LIMIT:
                _inspect_cache.pop(next(iter(_inspect_cache)))
            _inspect_cache[key] = (now + INSPECT_TTL, reason, st)
    return reason, st


def check(path, **options):
    """The reason this path may not be shown to a phone, or None when it may."""
    return inspect(path, **options)[0]
