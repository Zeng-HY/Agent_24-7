"""Files on this computer for the phone to attach (10-20): its folders to look through, and files sent up from the phone.

A file attached on the phone travels as its path on this computer, not as its bytes: Codex, Claude and DeepSeek run here
and open it themselves, so composer_references.py writes the paths under the message. A file from the phone is written
first to 下载\\手机传来的文件\\<date>\\ ("phone_files" in remote_config.json puts it elsewhere) and then goes the same way;
one never sent with a message is deleted after a week. Pictures still go as pictures (codex_control.Bridge.upload), so
the model sees them at once.

The phone sees names, sizes and times, never what a file holds. Every local disk can be looked through (the user's
choice, 10-20: what Codex and Claude here read anyway); network drives are left out, an unreachable one hangs the listing.
Hidden and system files and names starting with a dot are not listed.
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import stat
import string
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from app_paths import DATA

import chats

HERE = Path(__file__).resolve().parent
MAX_UPLOAD = 100 << 20          # one file sent up from the phone
MAX_PICTURE = 20 << 20          # a picture on this computer read in as a photo (codex_control.Bridge.upload takes 20 MB)
MAX_FILES = 20                  # files and folders attached to one message
KEEP_UNSENT = 7 * 86400         # a file sent up and never sent with a message is deleted after this
FORGET_SENT = 30 * 86400        # the record of one sent is dropped after this; the file stays
PAGE = 200                      # entries in one page of a listing
SCAN_LIMIT = 20000              # entries read from one folder at most
COUNT_LIMIT = 10000             # entries counted in an attached folder at most
INBOX_NAME = "手机传来的文件"

TYPES = {
    "pdf": (".pdf",),
    "word": (".doc", ".docx", ".rtf", ".odt"),
    "excel": (".xls", ".xlsx", ".xlsm", ".csv", ".tsv", ".ods"),
    "ppt": (".ppt", ".pptx", ".odp"),
    "image": (".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff", ".svg"),
    "text": (".txt", ".md", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".toml"),
    "code": (".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".sh", ".ps1", ".bat",
             ".cmd", ".sql", ".ipynb"),
    "archive": (".zip", ".rar", ".7z", ".tar", ".gz"),
    "audio": (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"),
    "video": (".mp4", ".mov", ".avi", ".mkv", ".webm"),
}
TYPE_OF = {suffix: kind for kind, suffixes in TYPES.items() for suffix in suffixes}
TYPE_NAMES = {"folder": "文件夹", "pdf": "PDF", "word": "Word", "excel": "表格", "ppt": "演示文稿", "image": "图片",
              "text": "文本", "code": "代码", "archive": "压缩包", "audio": "音频", "video": "视频", "other": "文件"}
PICTURES = (".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif")  # what the photo path reads; any other file goes as a path
# Windows known folders, found where the user moved them (Documents on D:, say); the home folder's ones otherwise
KNOWN = (("desktop", "桌面", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641", "Desktop"),
         ("downloads", "下载", "374DE290-123F-4565-9164-39C4925E467B", "Downloads"),
         ("documents", "文档", "FDD39AD0-238F-46AF-ADB4-6C85480369C7", "Documents"))
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class FileError(Exception):
    """Something the person can act on, with the HTTP status the listing or upload answers with."""

    def __init__(self, text: str, status: int = 400):
        super().__init__(text)
        self.status = status


class FileGone(chats.SendNotSubmitted):
    """An attached file is no longer where it was picked: the message is not sent and its draft stays."""
    code = "file_gone"


def type_of(name: str) -> str:
    return TYPE_OF.get(os.path.splitext(name)[1].lower(), "other")


def size_text(n: int) -> str:
    """85 KB, 1.2 MB, 150 MB, 2.3 GB."""
    if n < 1024:
        return f"{n} 字节"
    if n < 1024 ** 2:
        return f"{max(1, round(n / 1024))} KB"
    if n < 1024 ** 3:
        v = n / 1024 ** 2
        return f"{v:.1f} MB" if v < 100 else f"{v:.0f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold()


def natural(name: str) -> list:
    """Sort key: 第2章 before 第10章, letters regardless of case."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"([0-9]+)", normalize(name)) if t]


def hidden(name: str, st) -> bool:
    if name.startswith((".", "~$")):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def safe_name(name: str) -> str:
    """A file name from the phone as this computer can keep it: no folders, no characters Windows refuses."""
    name = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    if not name or set(name) <= {"."}:
        name = "文件"
    stem, suffix = os.path.splitext(name)
    if len(suffix) > 16:  # not a real extension
        stem, suffix = name, ""
    if stem.upper() in RESERVED:
        stem = "_" + stem
    if stem.startswith((".", "~$")):  # the listing would hide it
        stem = "_" + stem
    return stem[:max(1, 120 - len(suffix))] + suffix


_known_lock = threading.Lock()


def known_folder(guid: str) -> Path | None:
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        u = uuid.UUID(guid)
        g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        out = ctypes.c_wchar_p()
        with _known_lock:
            fn = ctypes.windll.shell32.SHGetKnownFolderPath
            fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
            fn.restype = ctypes.c_long
            if fn(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
                return None
        try:
            return Path(out.value) if out.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except (OSError, AttributeError, ValueError):
        return None


def known_place(guid: str, fallback: str) -> Path:
    return known_folder(guid) or Path.home() / fallback


def local_drives() -> list[str]:
    """C:\\, D:\\, …: fixed, removable and RAM disks that are there; network drives are left out."""
    if os.name != "nt":
        return ["/"]
    k32 = ctypes.windll.kernel32
    mask, out = k32.GetLogicalDrives(), []
    for i, letter in enumerate(string.ascii_uppercase):
        root = letter + ":\\"
        if mask >> i & 1 and k32.GetDriveTypeW(ctypes.c_wchar_p(root)) in (2, 3, 6) and os.path.isdir(root):
            out.append(root)
    return out


def describe(lines: list[dict]) -> str:
    """The block written under the message: one line per attached file or folder, with what it is."""
    out = ["附带的文件（都在这台电脑上，请直接打开）："]
    for v in lines:
        if v["kind"] == "folder":
            if v.get("more"):
                what = f"文件夹，超过 {COUNT_LIMIT} 项"
            elif not v["files"] and not v["folders"]:
                what = "文件夹，空的"
            else:
                what = "文件夹，" + "、".join(x for x in (f"{v['files']} 个文件" if v["files"] else "",
                                                       f"{v['folders']} 个子文件夹" if v["folders"] else "") if x)
        else:
            what = TYPE_NAMES[v["type"]] + "，" + size_text(v["size"]) + ("，从手机传来" if v.get("from_phone") else "")
        out.append(f"- {v['path']}（{what}）")
    return "\n".join(out)


class Files:
    def __init__(self, secret: str, inbox: str | Path | None = None, registry: str | Path | None = None,
                 drives=None, places=None):
        self.secret = (secret or "").encode("utf-8")
        self.inbox = Path(inbox) if inbox else known_place(KNOWN[1][2], KNOWN[1][3]) / INBOX_NAME
        self.registry_file = Path(registry) if registry else DATA / "attachments" / "phone-files.json"
        self.lock = threading.RLock()
        self._drives_fn = drives or local_drives
        self._drives = (0.0, [])
        self._known = places  # tests: [(kind, name, path)] in place of the Windows known folders
        self._swept = 0.0

    # -- where the phone may look

    def drives(self) -> list[str]:
        with self.lock:
            at, found = self._drives
            if time.monotonic() - at > 30 or not found:  # a USB disk plugged in shows within half a minute
                self._drives = (time.monotonic(), [d.upper() for d in self._drives_fn()])
            return list(self._drives[1])

    def _place(self, raw) -> Path:
        """An absolute path on one of this computer's own disks, as the phone went there (links not followed, so the
        crumbs read as it went), with . and .. taken out."""
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000 or "\0" in raw:
            raise FileError("位置无效")
        raw = raw.strip()
        if re.fullmatch(r"[A-Za-z]:", raw):
            raw += "\\"
        p = Path(os.path.normpath(raw))
        if not p.is_absolute():
            raise FileError("位置要从盘符开始，例如 D:\\")
        root = (p.drive + "\\").upper() if os.name == "nt" else "/"
        if root not in self.drives():
            raise FileError("只能看这台电脑自己的磁盘，网络盘和别的位置不行", 403)
        return p

    def _token(self, kind: str, path) -> str:
        """What makes an attached file one this service listed: the phone cannot name a path of its own."""
        text = kind + "\0" + os.path.normcase(str(path))
        return hmac.new(self.secret, text.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

    def entry(self, path: Path, st=None) -> dict:
        st = st or path.stat()
        folder = stat.S_ISDIR(st.st_mode)
        kind = "folder" if folder else "file"
        return {"kind": kind, "app": "pc", "id": self._token(kind, path), "name": path.name or str(path),
                "path": str(path), "size": None if folder else st.st_size, "modified": int(st.st_mtime * 1000),
                "type": "folder" if folder else type_of(path.name)}

    def places(self, folder: str = "") -> dict:
        """Where the sheet starts: the conversation's folder, files from the phone, Desktop, Downloads, Documents, disks."""
        out = []

        def add(name, path, kind):
            try:
                path = str(path)
                if not path or not os.path.isdir(path):
                    return
            except (OSError, ValueError):
                return
            if not any(os.path.normcase(v["path"]) == os.path.normcase(path) for v in out):
                out.append({"name": name, "path": path, "kind": kind})

        if folder:
            add("对话文件夹", chats._strip_unc(str(folder)), "conversation")
        add(INBOX_NAME, self.inbox, "inbox")
        for kind, name, guid, fallback in KNOWN:
            if self._known is None:
                add(name, known_place(guid, fallback), kind)
        for kind, name, path in self._known or []:
            add(name, path, kind)
        for root in self.drives():
            add(root.rstrip("\\/").replace(":", " 盘") if os.name == "nt" else root, root, "drive")
        return {"items": out}

    def listing(self, path, sort: str = "name", query: str = "", offset: int = 0) -> dict:
        folder = self._place(path)
        sort = sort if sort in ("name", "time") else "name"
        offset = offset if isinstance(offset, int) and offset >= 0 else 0
        rows, truncated = [], False
        try:
            with os.scandir(folder) as found:
                for e in found:
                    try:
                        if hidden(e.name, e.stat(follow_symlinks=False)):
                            continue
                        st = e.stat()  # a link counts as what it points to; a broken one is left out
                    except OSError:
                        continue
                    rows.append((e.name, stat.S_ISDIR(st.st_mode), st))
                    if len(rows) >= SCAN_LIMIT:
                        truncated = True
                        break
            here = folder.stat()
        except FileNotFoundError:
            raise FileError("这个文件夹不在了，可能被移走或删除了", 404) from None
        except NotADirectoryError:
            raise FileError("这不是文件夹", 400) from None
        except PermissionError:
            raise FileError("没有权限打开这个文件夹", 403) from None
        except OSError as exc:
            raise FileError(f"打不开这个文件夹：{exc.strerror or exc}", 400) from None
        words = normalize(query or "").split()
        if words:
            rows = [r for r in rows if all(w in normalize(r[0]) for w in words)]
        if sort == "time":  # newest first, folders among the files: a file just downloaded is at the top
            rows.sort(key=lambda r: (-r[2].st_mtime, natural(r[0])))
        else:
            rows.sort(key=lambda r: (not r[1], natural(r[0])))
        crumbs, node = [], folder
        while True:
            crumbs.append({"name": node.name or node.drive or str(node), "path": str(node)})
            if node.parent == node:
                break
            node = node.parent
        crumbs.reverse()
        page = rows[offset:offset + PAGE]
        return {"path": str(folder), "folder": self.entry(folder, here),
                "parent": str(folder.parent) if folder.parent != folder else None, "crumbs": crumbs,
                "items": [self.entry(folder / name, st) for name, _, st in page], "total": len(rows),
                "offset": offset, "next_offset": offset + len(page), "has_more": offset + len(page) < len(rows),
                "truncated": truncated, "sort": sort}

    # -- what a message carries

    def _checked(self, ref: dict, kind: str | None = None) -> tuple[Path, os.stat_result]:
        kind = kind or ref.get("kind")
        path, token = ref.get("path"), ref.get("id")
        if (ref.get("kind") != kind or kind not in ("file", "folder") or not isinstance(path, str)
                or not isinstance(token, str) or not hmac.compare_digest(token, self._token(kind, path))):
            raise chats.ChatError("文件引用无效，请去掉它再重新选择")
        p = Path(path)
        try:
            st = p.stat()
        except OSError:
            st = None
        if st is None or stat.S_ISDIR(st.st_mode) != (kind == "folder"):
            raise FileGone(f"「{p.name or path}」已经不在原处（移走、改名或删除了），尚未发送；请去掉它再重新选择")
        return p, st

    def resolve(self, ref: dict) -> dict:
        """One attached file or folder as it is now, for describe(); refused when it is gone or the reference forged."""
        p, st = self._checked(ref)
        if ref["kind"] == "folder":
            files = folders = 0
            more = False
            try:
                with os.scandir(p) as found:
                    for n, e in enumerate(found):
                        if n >= COUNT_LIMIT:
                            more = True
                            break
                        try:
                            if hidden(e.name, e.stat(follow_symlinks=False)):
                                continue
                            if e.is_dir():
                                folders += 1
                            else:
                                files += 1
                        except OSError:
                            continue
            except OSError:
                pass  # it exists; what is in it is for the agent to see
            return {"kind": "folder", "path": str(p), "name": p.name, "files": files, "folders": folders, "more": more}
        upload = ref.get("upload")
        return {"kind": "file", "path": str(p), "name": p.name, "type": type_of(p.name), "size": st.st_size,
                "from_phone": bool(upload) and self._known_upload(upload, p)}

    def picture(self, ref: dict) -> tuple[str, bytes]:
        """A picture picked on this computer, read for the photo path (codex_control.Bridge.upload)."""
        p, st = self._checked(ref, "file")
        if p.suffix.lower() not in PICTURES:
            raise FileError("这个文件不按图片发，会按文件路径发")
        if st.st_size > MAX_PICTURE:
            raise FileError(f"图片超过 {MAX_PICTURE >> 20} MB，改按文件路径发", 413)
        try:
            return p.name, p.read_bytes()
        except OSError as exc:
            raise FileError(f"读不了这张图片：{exc.strerror or exc}") from None

    # -- files from the phone

    def _registry(self) -> dict:
        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_registry(self, data: dict) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.registry_file.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.registry_file)

    def _known_upload(self, ident, path: Path) -> bool:
        with self.lock:
            item = self._registry().get(ident) if isinstance(ident, str) else None
        return bool(item) and os.path.normcase(item.get("path", "")) == os.path.normcase(str(path))

    def upload(self, name: str, read, size: int, app: str = "", thread: str = "") -> dict:
        """Write a file the phone sends (read(n) gives its bytes, size of them) into today's folder of the inbox."""
        if not 0 < size <= MAX_UPLOAD:
            raise FileError(f"单个文件最多 {MAX_UPLOAD >> 20} MB", 413)
        name = safe_name(name)
        self.cleanup()
        day = self.inbox / time.strftime("%Y-%m-%d")
        try:
            day.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FileError(f"电脑上建不了存放的文件夹：{exc.strerror or exc}") from None
        ident = uuid.uuid4().hex
        temp, got = day / f".{ident}.part", 0
        try:
            with temp.open("xb") as f:
                while got < size:
                    block = read(min(1 << 20, size - got))
                    if not block:
                        break
                    f.write(block)
                    got += len(block)
            if got != size:
                raise FileError("文件没有传完整，请重试")
            final = self._settle(temp, day, name)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        st = final.stat()
        with self.lock:
            data = self._registry()
            data[ident] = {"path": str(final), "size": st.st_size, "mtime": st.st_mtime_ns, "created": time.time(),
                           "used": False, "app": app, "thread": thread}
            self._save_registry(data)
        return {**self.entry(final, st), "upload": ident, "from_phone": True}

    @staticmethod
    def _settle(temp: Path, day: Path, name: str) -> Path:
        stem, suffix = os.path.splitext(name)
        for n in range(1, 1000):
            target = day / (name if n == 1 else f"{stem} ({n}){suffix}")
            if target.exists():
                continue
            try:
                os.rename(temp, target)  # Windows refuses to replace a file that is there
                return target
            except FileExistsError:
                continue
        raise FileError("同名的文件太多了，请改个名字再传")

    def mark_used(self, idents) -> None:
        """Files from the phone that went with a message: kept for good."""
        with self.lock:
            data = self._registry()
            changed = False
            for ident in idents or []:
                if isinstance(ident, str) and ident in data and not data[ident].get("used"):
                    data[ident]["used"] = True
                    changed = True
            if changed:
                self._save_registry(data)

    def remove_upload(self, ident) -> dict:
        """The phone took a file off its draft: deleted here unless a message already carried it."""
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise FileError("文件编号无效", 404)
        with self.lock:
            data = self._registry()
            item = data.get(ident)
            if not item:
                return {"ok": True, "gone": True}
            if item.get("used"):
                return {"ok": True, "retained": True}
            self._delete(item)
            data.pop(ident)
            self._save_registry(data)
        return {"ok": True}

    def _delete(self, item: dict) -> None:
        """Only the file this service wrote, as it wrote it: one changed since (opened and saved, say) stays."""
        p = Path(item.get("path", ""))
        try:
            st = p.stat()
            if p.is_file() and st.st_size == item.get("size") and st.st_mtime_ns == item.get("mtime"):
                p.unlink()
            p.parent.rmdir()  # the day's folder, when nothing else is in it
        except OSError:
            pass

    def cleanup(self, force: bool = False) -> None:
        """Files sent up a week ago and never sent with a message are deleted; at most every ten minutes."""
        with self.lock:
            if not force and time.monotonic() - self._swept < 600:
                return
            self._swept = time.monotonic()
            data, now, changed = self._registry(), time.time(), False
            for ident, item in list(data.items()):
                age = now - float(item.get("created") or 0)
                if not item.get("used") and age > KEEP_UNSENT:
                    self._delete(item)
                elif not (item.get("used") and age > FORGET_SENT):
                    continue
                data.pop(ident)
                changed = True
            if changed:
                self._save_registry(data)
