"""Which files an answer may offer to a phone (docs/handoff-file-preview.md §4, segment B).

Pure: no global state, no I/O except the injected ``stat``.  Network and foreign-system
paths are refused before any stat.  The drive list and home folder are injected by tests.
"""
from __future__ import annotations

import ntpath
import os
import re
import stat as stat_module
from pathlib import Path

# Windows refuses these as file names even with an extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx")
_SECRET_NAMES = ("id_rsa", "id_ed25519")
_BROWSER_FILES = ("login data", "cookies", "local state")
_BROWSER_MARKERS = ("\\google\\chrome\\", "\\microsoft\\edge\\", "\\bravesoftware\\", "\\chromium\\",
                    "\\mozilla\\firefox\\", "\\user data\\", "\\opera software\\")


def _default_drives() -> list[str]:
    import pc_files
    return pc_files.local_drives()


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
                  (".teleply-updates", ".android\\teleply-signing", ".ssh", ".gnupg", ".aws", ".gemini",
                   ".config\\gh")]
        places += [os.path.join(home, name) for name in
                   (".codex\\auth.json", ".claude\\.credentials.json", ".dsh\\.credentials.yaml",
                    ".kube\\config", ".docker\\config.json", ".git-credentials", ".npmrc", ".pypirc")]
        if any(_under(path, place) for place in places):
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


def inspect(path, *, drives=None, home=None, data=None, stat=os.stat):
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
    allowed = {str(d).rstrip("\\/").upper() for d in (drives if drives is not None else _default_drives())}
    if (target.drive + "\\").upper() not in {value + "\\" for value in allowed}:
        return "not_local", None  # another computer's drive, or a network drive that is not listed
    if ":" in str(target)[2:]:
        return "denied", None  # an alternate data stream
    if _deny_name(target.name):
        return "denied", None
    home = _path(home) if home is not None else str(Path.home())
    if data is None:
        from app_paths import DATA
        data = str(DATA)
    if _denied_places(str(target), home, _path(data)):
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


def check(path, **options):
    """The reason this path may not be shown to a phone, or None when it may."""
    return inspect(path, **options)[0]
