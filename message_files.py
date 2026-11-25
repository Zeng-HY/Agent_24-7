"""Compatibility wrappers over answer_files (docs/handoff-file-preview.md §3.4, segment B).

The phone's file list and the public messages now use answer_files.scan directly; these two
names stay for callers that only need the old answers (the desktop's self check, tests).
"""
from answer_files import scan


def references(text):
    """Paths named by Markdown links/images, HTML tags, inline code and body paths, forward slashes."""
    if not isinstance(text, str) or not text:
        return []
    return [row["path"].replace("\\", "/") for row in scan(text, ()).files]


def absolute_links(text, cwd):
    """The answer with its file links rewritten to <D:/…> against this working folder."""
    if not isinstance(text, str) or not text:
        return text
    return scan(text, (cwd,) if cwd else ()).text
