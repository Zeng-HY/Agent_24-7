"""Recognize the files an answer names and rewrite their links for the phones.

This is segment A of docs/handoff-file-preview.md §3: a pure function, no I/O except the
injected ``stat`` (never called for network or foreign-system paths).  It does not decide
whether a file may be shown to the phone; that is segment B (file_policy.py).

``scan(text, bases, presented=(), stat=os.stat)`` returns:

- ``text``: the answer with recognized Markdown link/image addresses rewritten to
  ``<D:/a/b.png>`` (forward slashes, line number kept as ``:12``);
- ``files``: one entry per file, in order of first appearance, ``via`` merged;
- ``notes``: file-like addresses that cannot be given, ``not_found`` or ``not_local``.
"""
from __future__ import annotations

import html
import ntpath
import os
import re
import stat as stat_module
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.common.utils import normalizeReference, unescapeAll

MAX_FILES = 50

# markdown-it refuses file: by default and turns the whole link into text.  Keep refusing
# the script-bearing schemes, allow file: (and everything else CommonMark allows).
PARSER = MarkdownIt("commonmark", {"html": True}).enable("table")
_BAD_SCHEME = re.compile(r"^(?:javascript|vbscript|data):", re.I)
PARSER.validateLink = lambda url: not _BAD_SCHEME.match(url or "")

_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_POSIX_ROOTS = ("/home/", "/users/", "/tmp/", "/var/", "/etc/", "/root/", "/opt/",
                "/usr/", "/srv/", "/private/", "/volumes/", "/system/", "/mnt/")

# A link's destination in the source, as CommonMark reads it (balanced parentheses, escapes).
_DESTINATION = re.compile(
    r"\]\(\s*(<(?:[^<>\n\\]|\\.)*>|(?:[^\s()<>\\]|\\.|\((?:[^\s()<>\\]|\\.)*\))+)")
_CODE_SPAN = re.compile(r"(`+)[\s\S]*?(?<!`)\1(?!`)")
_DEFINITION = re.compile(
    r"^[ \t]{0,3}\[((?:[^\\\[\]\n]|\\.)+)\]:[ \t]*(<[^<>\n]*>|[^\s]+)", re.M)
_TAG = re.compile(r"<!--[\s\S]*?-->|</?[A-Za-z][^<>]*>")
_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I | re.S)
_A_TAG = re.compile(r"<a\b[^>]*>", re.I | re.S)
_ATTR = re.compile(r"\b(src|href)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))", re.I)
_CITATION = re.compile(r":codex-file-citation\{((?:[^{}\"]|\"[^\"]*\")*)\}")
_CITATION_PATH = re.compile(r'(?:^|\s)path\s*=\s*"([^"]*)"')

# A drive path in body text: quoted, in 「」, or bare up to whitespace / Chinese punctuation.
_BODY_PATH = re.compile(
    r'(?<![A-Za-z0-9_:/\\])'
    r'(?:"([A-Za-z]:[\\/][^"\n]*)"'
    r"|'([A-Za-z]:[\\/][^'\n]*)'"
    r'|「([A-Za-z]:[\\/][^」\n]*)」'
    r'|([A-Za-z]:[\\/][^\s，。；：、！？」』）】》〈〉…—·"\'<>`]*))')

_TRAILING = ".,;:)]}'\""
_COLON_LINE = re.compile(r":(\d+)(?::\d+)?(?:-\d+)?$")
_HASH_LINE = re.compile(r"#L(\d+)(?:C\d+)?(?:-L?\d+)?$", re.I)
_EXTENDING = re.compile(r"\.[A-Za-z0-9]{1,12}$")

_PRE_FILTER = ("](", "]:", ":\\", ":/", "file:", "<img", "<a ", "~/", "~\\", "`")

_NOT_LOCAL = object()


@dataclass
class Scan:
    text: str
    files: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)


def _pct(value: str) -> str:
    """%-decode UTF-8; an invalid sequence (100%.txt, %FF) stays exactly as written."""
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return value


def _normalize_dest(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == "<" and s[-1] == ">":
        s = s[1:-1]
    # Every backslash is a separator, including the one CommonMark reads as an escape
    # (D:\a\.claude\f.md) and would otherwise drop.
    s = s.replace("\\", "/")
    return unicodedata.normalize("NFC", _pct(s))


def _href_text(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == "<" and s[-1] == ">":
        s = s[1:-1]
    return s


def _dest_text(path: str, line: int | None) -> str:
    s = path.replace("\\", "/").replace("%", "%25")  # 100%.txt must survive decodeURIComponent
    if line is not None:
        s += ":" + str(line)
    return "<" + s + ">"


def _home() -> str:
    return os.path.expanduser("~")


def _key_for(raw: str) -> str:
    """The href a Markdown parser makes from this destination (used to match raw spans to tokens)."""
    s = _href_text(raw)
    return PARSER.normalizeLink(unescapeAll(s))


def _split_colon_line(s: str) -> tuple[str, int | None]:
    match = _COLON_LINE.search(s)
    if not match:
        return s, None
    return s[:match.start()], int(match.group(1))


def _line_spans(text: str) -> tuple[list[str], list[int]]:
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    return lines, starts


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _line_end(text: str, pos: int) -> int:
    end = text.find("\n", pos)
    return len(text) if end < 0 else end


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted((a, b) for a, b in ranges if a < b):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _inside(pos: int, ranges: Sequence[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start > pos:
            return False
        if start <= pos < end:
            return True
    return False


def _is_image(text: str, close: int) -> bool:
    """True when the ] at [close] closes an image label (a ![ before its opening [)."""
    depth = 1
    i = close - 1
    while i >= 0:
        char = text[i]
        if char == "\\":
            i -= 2
            continue
        if char == "]":
            depth += 1
        elif char == "[":
            depth -= 1
            if depth == 0:
                return i > 0 and text[i - 1] == "!"
        i -= 1
    return False


def _local_base(value) -> str | None:
    """A base folder we may stat: a Windows drive path, never a network or foreign one."""
    s = str(value).replace("\\", "/")
    if re.match(r"^/[A-Za-z]:/", s):
        s = s[1:]
    if not _DRIVE.match(s) or s.startswith("//"):
        return None
    return ntpath.normpath(s)


def _make_lookup(stat_fn: Callable) -> Callable[[str], tuple[bool, bool]]:
    cache: dict[str, tuple[bool, bool]] = {}

    def lookup(path: str) -> tuple[bool, bool]:
        key = ntpath.normcase(path)
        got = cache.get(key)
        if got is not None:
            return got
        try:
            st = stat_fn(path)
        except (OSError, ValueError):
            st = None
        is_dir = bool(st is not None and stat_module.S_ISDIR(getattr(st, "st_mode", 0) or 0))
        got = (st is not None, is_dir)
        cache[key] = got
        return got

    return lookup


def _ok(path: str, line: int | None, found: tuple[bool, bool]):
    return ("ok", path, line, found[0], found[1])


def _absolute(s: str, lookup: Callable) -> tuple:
    path, line = _split_colon_line(s)
    path = ntpath.normpath(path)
    found = lookup(path)
    if not found[0]:
        hash_line = _HASH_LINE.search(path)
        if hash_line and hash_line.start() > 2:  # keep the drive colon; only a missing full name is stripped
            bare = path[:hash_line.start()]
            if line is None:
                line = int(hash_line.group(1))
            return _ok(bare, line, lookup(bare))
    return _ok(path, line, found)


def _relative(s: str, bases: Sequence[str], lookup: Callable) -> tuple:
    path, line = _split_colon_line(s)
    if not path:
        return ("ignore",)
    file_like = "/" in path or bool(_EXTENDING.search(path.rsplit("/", 1)[-1]))
    for base in bases:
        candidate = ntpath.normpath(ntpath.join(base, path))
        found = lookup(candidate)
        if found[0]:
            return _ok(candidate, line, found)
    hash_line = _HASH_LINE.search(path)
    if hash_line and hash_line.start() > 0:
        bare = path[:hash_line.start()]
        for base in bases:
            candidate = ntpath.normpath(ntpath.join(base, bare))
            found = lookup(candidate)
            if found[0]:
                return _ok(candidate, line if line is not None else int(hash_line.group(1)), found)
        return ("not_found",) if file_like else ("ignore",)
    if line is not None:
        file_like = True
    return ("not_found",) if file_like else ("ignore",)


def _file_rest(s: str):
    """The path inside a file: URL, or _NOT_LOCAL for a network host."""
    rest = s[5:]
    if rest.startswith("//"):
        host, _, tail = rest[2:].partition("/")
        if re.fullmatch(r"[A-Za-z]:", host):
            return host + "/" + tail if tail else host + "/"
        if host and host.lower() != "localhost":
            return _NOT_LOCAL
        rest = "/" + tail
    return rest


def _recognize_form(s: str, bases: Sequence[str], lookup: Callable, depth: int = 0) -> tuple:
    if depth > 3:
        return ("ignore",)
    if s.startswith("//?/"):
        s = s[4:]
        if s.lower().startswith("unc/"):
            return ("not_local",)
    if s.startswith("//"):
        return ("not_local",)  # \\server\share, \\wsl$\..., \\wsl.localhost\...
    if re.match(r"(?i)^file:", s):
        rest = _file_rest(s)
        if rest is _NOT_LOCAL:
            return ("not_local",)
        return _recognize_form(rest, bases, lookup, depth + 1)
    if re.match(r"^/[A-Za-z]:/", s):
        s = s[1:]
    elif s.startswith("/mnt/") and len(s) > 6 and s[5].isalpha() and s[6] == "/":
        s = s[5].upper() + ":" + s[6:]
    if _DRIVE.match(s):
        return _absolute(s, lookup)
    if s.startswith("~/"):
        home = _home().replace("\\", "/").rstrip("/")
        return _absolute(home + s[1:], lookup)
    if s.startswith("/"):
        return ("not_local",) if s.lower().startswith(_POSIX_ROOTS) else ("ignore",)
    if _SCHEME.match(s):
        # filename.ext:line is a file with a line number, not a URL scheme (message_files.py:28).
        colon = _COLON_LINE.search(s)
        if colon and _EXTENDING.search(s[:colon.start()].rsplit("/", 1)[-1]):
            return _relative(s, bases, lookup)
        return ("ignore",)
    return _relative(s, bases, lookup)


def _recognize(raw: str, bases: Sequence[str], lookup: Callable) -> tuple:
    s = _normalize_dest(raw)
    if not s or s.startswith("#") or s.startswith("?"):
        return ("ignore",)
    return _recognize_form(s, bases, lookup)


def _code_content(match: re.Match) -> str:
    raw = match.group(0)
    ticks = match.group(1)
    content = raw[len(ticks):-len(ticks)]
    if len(content) >= 2 and content[0] == " " and content[-1] == " " and content.strip():
        content = content[1:-1]
    return content.replace("\n", " ")


def _code_file(content: str, bases: Sequence[str], lookup: Callable):
    s = content.strip()
    if not s:
        return None
    info = _recognize(s, bases, lookup)
    if info[0] != "ok":
        return None
    # An absolute path that no longer exists is still a reference; a path with spaces is
    # only one path when it really names an existing file (a command is not a path).
    if any(char.isspace() for char in s) and not info[3]:
        return None
    return info


def _attr(tag: str, name: str) -> str | None:
    for match in _ATTR.finditer(tag):
        if match.group(1).lower() == name:
            return next((value for value in match.groups()[1:] if value is not None), None)
    return None


def _occurrence(pos: int, via: Sequence[str], src: str, info: tuple,
                text: str | None = None) -> dict:
    return {"pos": pos, "via": list(via), "src": src, "info": info, "text": text}


def _note(notes: list, seen: set, href: str, reason: str, pos: int) -> None:
    if (href, reason) in seen:
        return
    seen.add((href, reason))
    notes.append((pos, {"href": href, "reason": reason}))


def scan(text: str, bases: Sequence[str] = (), *, presented: Iterable[str] = (),
         stat: Callable = os.stat) -> Scan:
    source = text or ""
    if isinstance(bases, (str, os.PathLike)):
        bases = (bases,)
    if isinstance(presented, (str, os.PathLike)):
        presented = (presented,)
    presented = tuple(os.fspath(p) for p in (presented or ())
                      if isinstance(p, (str, os.PathLike)) and os.fspath(p))
    if not presented and not any(marker in source for marker in _PRE_FILTER):
        return Scan(source, [], [])
    bases = tuple(b for b in (_local_base(value) for value in (bases or ())) if b)
    lookup = _make_lookup(stat)

    env: dict = {}
    tokens = PARSER.parse(source, env)
    hrefs: set[str] = set()
    href_vias: dict[str, list[str]] = {}
    for block in tokens:
        for token in block.children or []:
            if token.type == "link_open":
                href = token.attrGet("href")
                via = "link"
            elif token.type == "image":
                href = token.attrGet("src")
                via = "image"
            else:
                continue
            if not href:
                continue
            hrefs.add(href)
            vias = href_vias.setdefault(href, [])
            if via not in vias:
                vias.append(via)

    lines, starts = _line_spans(source)
    block_ranges = [(starts[block.map[0]], starts[min(block.map[1], len(lines))])
                    for block in tokens
                    if block.type in ("fence", "code_block") and block.map]
    span_ranges = [match.span() for match in _CODE_SPAN.finditer(source)] if "`" in source else []
    code_ranges = _merge_ranges(block_ranges + span_ranges)
    tag_ranges = _merge_ranges(match.span() for match in _TAG.finditer(source)) if "<" in source else []
    tag_starts = {start for start, _ in tag_ranges}
    comment_ranges = (_merge_ranges(match.span() for match in _COMMENT.finditer(source))
                      if "<!--" in source else [])
    definition_ranges = (_merge_ranges(
        (_line_start(source, match.start()), _line_end(source, match.end()))
        for match in _DEFINITION.finditer(source)) if "]:" in source else [])

    occurrences: list[dict] = []
    notes: list[tuple[int, dict]] = []
    seen_notes: set[tuple[str, str]] = set()
    edits: list[tuple[int, int, str]] = []

    # Markdown links and images, each read from the source so backslashes survive.
    for match in _DESTINATION.finditer(source):
        raw = match.group(1)
        start, end = match.span(1)
        if _inside(start, code_ranges) or _inside(match.start(), definition_ranges):
            continue
        if _inside(start, tag_ranges) and start not in tag_starts:
            continue  # a Markdown-looking address inside an HTML tag's attribute is not a link
        key = _key_for(raw)
        if key not in hrefs:
            continue
        info = _recognize(raw, bases, lookup)
        if info[0] == "ok":
            occurrences.append(_occurrence(match.start(), ["image" if _is_image(source, match.start())
                                                          else "link"], "markdown", info))
            edits.append((start, end, _dest_text(info[1], info[2])))
        elif info[0] in ("not_found", "not_local"):
            _note(notes, seen_notes, _href_text(raw), info[0], start)

    # Reference-style links: the address lives on the definition line.
    references = env.get("references") or {}
    for match in (_DEFINITION.finditer(source) if references else ()):
        if _inside(match.start(), code_ranges):
            continue
        label = normalizeReference(match.group(1))
        if label not in references:
            continue
        raw = match.group(2)
        key = _key_for(raw)
        if key not in hrefs:
            continue
        info = _recognize(raw, bases, lookup)
        if info[0] == "ok":
            occurrences.append(_occurrence(match.start(), href_vias.get(key, ["link"]),
                                           "markdown", info))
            start, end = match.span(2)
            edits.append((start, end, _dest_text(info[1], info[2])))
        elif info[0] in ("not_found", "not_local"):
            _note(notes, seen_notes, _href_text(raw), info[0], match.start())

    # HTML tags are recognized but never rewritten (the old apps show HTML as text).
    if "<" in source:
        for pattern, via, attr in ((_IMG_TAG, "image", "src"), (_A_TAG, "link", "href")):
            for match in pattern.finditer(source):
                if _inside(match.start(), code_ranges) or _inside(match.start(), comment_ranges):
                    continue
                value = _attr(match.group(0), attr)
                if value is None:
                    continue
                value = html.unescape(value)
                if _BAD_SCHEME.match(value):
                    continue
                info = _recognize(value, bases, lookup)
                if info[0] == "ok":
                    occurrences.append(_occurrence(match.start(), [via], "html", info))
                elif info[0] in ("not_found", "not_local"):
                    _note(notes, seen_notes, value, info[0], match.start())

    # Codex file citations, already turned into links by chats.codex_answer in the live path.
    for match in (_CITATION.finditer(source) if ":codex-file-citation{" in source else ()):
        if _inside(match.start(), code_ranges):
            continue
        path = _CITATION_PATH.search(match.group(1))
        if not path:
            continue
        info = _recognize(path.group(1), bases, lookup)
        if info[0] == "ok":
            occurrences.append(_occurrence(match.start(), ["citation"], "citation", info))

    # Inline code that holds exactly one path: recorded in texts, never rewritten.
    for match in (_CODE_SPAN.finditer(source) if "`" in source else ()):
        if _inside(match.start(), block_ranges):
            continue
        content = _code_content(match)
        info = _code_file(content, bases, lookup)
        if info:
            occurrences.append(_occurrence(match.start(), ["code"], "code", info, content))

    body_ranges = _merge_ranges(
        code_ranges + list(tag_ranges) + list(definition_ranges)
        + [match.span(1) for match in _DESTINATION.finditer(source)]
        + [match.span() for match in _CITATION.finditer(source)]
        + list(comment_ranges))

    # Absolute paths in body text: only when the file really exists.
    for match in _BODY_PATH.finditer(source):
        if _inside(match.start(), body_ranges):
            continue
        raw = next((group for group in match.groups() if group is not None), "")
        raw = raw.strip().rstrip(_TRAILING)
        if not raw:
            continue
        info = _recognize(raw, bases, lookup)
        if info[0] == "ok" and info[3]:
            occurrences.append(_occurrence(match.start(), ["path"], "path", info, raw))

    # Files the assistant explicitly presented (Claude SendUserFile, DeepSeek deliverables).
    for index, value in enumerate(presented):
        info = _recognize(value, bases, lookup)
        if info[0] == "ok":
            occurrences.append(_occurrence(len(source) + 1 + index, ["presented"], "presented", info))

    occurrences.sort(key=lambda item: item["pos"])
    files: list[dict] = []
    by_key: dict[str, dict] = {}
    for occurrence in occurrences:
        info = occurrence["info"]
        if info[0] != "ok":
            continue
        path, line, exists, is_dir = info[1], info[2], info[3], info[4]
        key = path.replace("/", "\\").casefold()
        row = by_key.get(key)
        if row is None:
            if len(files) >= MAX_FILES:
                continue
            row = {"path": path, "line": line, "index": 0, "indexes": [], "via": [],
                   "exists": exists, "is_dir": is_dir}
            files.append(row)
            by_key[key] = row
        for via in occurrence["via"]:
            if via not in row["via"]:
                row["via"].append(via)
        if row["line"] is None and line is not None:
            row["line"] = line
        if occurrence["text"]:
            texts = row.setdefault("texts", [])
            if occurrence["text"] not in texts:
                texts.append(occurrence["text"])

    # index: old-web numbering over the rewritten text.  Every local Markdown link/image
    # takes a number (folder and missing files too); HTML/code/path/presented start at 1000.
    new_text = _apply_edits(source, edits)
    if any(occurrence["src"] == "markdown" for occurrence in occurrences):
        counter = 0
        for block in PARSER.parse(new_text):
            for token in block.children or []:
                if token.type == "link_open":
                    href = token.attrGet("href")
                elif token.type == "image":
                    href = token.attrGet("src")
                else:
                    continue
                if not href:
                    continue
                decoded = _pct(href)
                if not _DRIVE.match(decoded):
                    continue
                path, _ = _split_colon_line(decoded.replace("\\", "/"))
                key = ntpath.normpath(path).replace("/", "\\").casefold()
                row = by_key.get(key)
                if row is not None and counter not in row["indexes"]:
                    row["indexes"].append(counter)
                counter += 1
    extra = 1000
    for row in files:
        if not row["indexes"]:
            row["indexes"].append(extra)
            extra += 1
        row["index"] = row["indexes"][0]

    notes.sort(key=lambda item: item[0])
    return Scan(new_text, files, [note for _, note in notes])


def _apply_edits(text: str, edits: Sequence[tuple[int, int, str]]) -> str:
    if not edits:
        return text
    out: list[str] = []
    at = 0
    for start, end, replacement in sorted(edits):
        if start < at:
            continue
        out.append(text[at:start])
        out.append(replacement)
        at = end
    if not out:
        return text
    out.append(text[at:])
    return "".join(out)
