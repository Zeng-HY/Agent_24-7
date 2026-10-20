"""Conversations grouped the way the desktop apps' sidebars group them: by app, then by project.

Codex: the projects of Codex desktop. Its threads database (state_5.sqlite) has a projects table with each project's
name and folders; a conversation's project is threads.project_id or, until Codex has moved those over (10-12 none
had), the global state file's thread-project-assignments. Conversations in projectless-thread-ids were started outside
any project. A conversation with neither belongs to the project whose folder holds its working folder, else to
其他对话. Runs of `codex exec` (automated) are not in Codex desktop's sidebar and are left out here too.

Claude: by the conversation's folder (originCwd, which for a worktree is the repository it came from), named as Claude
desktop names it: a git repository after its origin remote (a folder cloned from …/tools.git shows as tools), any other
folder by its own name; Claude's scratch folders ("No folder" on the desktop) are 其他对话.

Projects are listed most recently used first, 其他对话 last; conversations newest first.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

import chats

OTHER_KEY, OTHER_NAME = "other", "其他对话"
FIRST = 10  # conversations sent per project with the tree; 显示更多 asks for the rest
RECENT_MS = 6 * 3600 * 1000  # whether a conversation is running is read only for ones active this recently

_lock = threading.Lock()
_layout_cache: dict = {}
_state_cache: dict = {}
_git_cache: dict[str, tuple[float, str]] = {}


def _strip(path: str | None) -> str:
    return chats._strip_unc(path or "")


def _under(path: str, root: str) -> bool:
    p, r = path.casefold().rstrip("\\/"), root.casefold().rstrip("\\/")
    return bool(p) and bool(r) and (p == r or p.startswith(r + "\\") or p.startswith(r + "/"))


# ---------------------------------------------------------------- Codex


def _global_state() -> dict:
    path = chats.CODEX_HOME / ".codex-global-state.json"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    hit = _state_cache.get("state")
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return hit[1] if hit else {}
    data = data if isinstance(data, dict) else {}
    _state_cache["state"] = (mtime, data)
    return data


def codex_layout() -> tuple[dict, dict, set, set]:
    """({project key: {name, roots}}, {thread id: project key}, projectless thread ids, exec thread ids); kept 10 s."""
    with _lock:
        hit = _layout_cache.get("codex")
        if hit and time.monotonic() - hit[0] < 10:
            return hit[1]
    projects: dict[str, dict] = {}
    by_thread: dict[str, str] = {}
    exec_ids: set[str] = set()
    db = chats.codex_db()
    if db is not None:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3)
        try:
            tables = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
            if "projects" in tables:
                for pid, name in con.execute("select id, name from projects"):
                    projects[pid] = {"name": (name or "").strip(), "roots": []}
                if "project_roots" in tables:
                    for pid, path in con.execute("select project_id, path from project_roots order by position"):
                        if pid in projects and path:
                            projects[pid]["roots"].append(_strip(path))
            cols = {r[1] for r in con.execute("pragma table_info(threads)")}
            project_col = "project_id" if "project_id" in cols else "null"
            for tid, pid, source in con.execute(f"select id, {project_col}, source from threads where archived = 0"):
                if source == "exec":
                    exec_ids.add(tid)
                elif pid in projects:
                    by_thread[tid] = pid
        finally:
            con.close()
    state = _global_state()
    moved: dict[str, str] = {}  # the desktop's own project ids -> the database's
    for per_host in (state.get("app-server-project-id-by-legacy-project-id-by-host") or {}).values():
        if isinstance(per_host, dict):
            moved.update(per_host)
    legacy: dict[str, str] = {}
    for lid, v in (state.get("local-projects") or {}).items():
        if not isinstance(v, dict):
            continue
        key = moved.get(lid)
        if key not in projects:  # not in the database (yet): the desktop's own record
            key = lid
            projects.setdefault(lid, {"name": str(v.get("name") or "").strip(),
                                      "roots": [_strip(p) for p in v.get("rootPaths") or [] if isinstance(p, str)]})
        legacy[lid] = key
    for tid, a in (state.get("thread-project-assignments") or {}).items():
        if isinstance(a, dict):
            key = legacy.get(a.get("projectId")) or moved.get(a.get("projectId"))
            if key in projects:
                by_thread.setdefault(tid, key)
    for p in projects.values():
        if not p["name"]:
            p["name"] = Path(p["roots"][0]).name if p["roots"] else OTHER_NAME
    value = (projects, by_thread, set(state.get("projectless-thread-ids") or []), exec_ids)
    with _lock:
        _layout_cache["codex"] = (time.monotonic(), value)
    return value


def codex_group(item: dict, layout: tuple) -> tuple[str, str] | None:
    """(project key, folder shown under the title) of a Codex conversation, or None when Codex desktop does not list it.
    Only conversations in 其他对话 that were started in a folder of their own show that folder; the ones started outside
    any project live in Codex's own dated scratch folders, whose names say nothing."""
    projects, by_thread, projectless, exec_ids = layout
    tid = item["id"]
    if tid in exec_ids:
        return None
    if tid in by_thread:
        return by_thread[tid], ""
    if tid in projectless:
        return OTHER_KEY, ""
    cwd, best = _strip(item.get("cwd")), None
    for key, p in projects.items():
        for root in p["roots"]:
            if _under(cwd, root) and (best is None or len(root) > best[1]):
                best = (key, len(root))
    if best:
        return best[0], ""
    return OTHER_KEY, "" if _under(cwd, str(chats.HOME / "Documents" / "Codex")) else Path(cwd).name


# ---------------------------------------------------------------- Claude


def _origin_name(config: Path) -> str:
    """The repository name in the url of [remote "origin"] of a git config file, or ''."""
    section = ""
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        elif section == '[remote "origin"]' and line.split("=", 1)[0].strip() == "url" and "=" in line:
            url = line.split("=", 1)[1].strip().rstrip("/")
            name = re.split(r"[/:\\]", url)[-1]
            return name[:-4] if name.endswith(".git") else name
    return ""


def git_name(folder: str) -> str:
    """Name of the git repository holding folder, after its origin remote, as Claude desktop shows it; '' if none."""
    key, now = folder.casefold(), time.monotonic()
    hit = _git_cache.get(key)
    if hit and now - hit[0] < 600:
        return hit[1]
    name = ""
    try:
        start = Path(folder)
        for d in (start, *start.parents):
            git = d / ".git"
            if git.is_dir():
                config = git / "config"
            elif git.is_file():  # a worktree: .git names its folder inside the main repository's .git
                text = git.read_text(encoding="utf-8", errors="replace").strip()
                if not text.startswith("gitdir:"):
                    break
                gitdir = Path(text[7:].strip())
                gitdir = gitdir if gitdir.is_absolute() else d / gitdir
                common = gitdir / "commondir"
                config = (gitdir / common.read_text(encoding="utf-8").strip() if common.is_file() else gitdir) / "config"
            else:
                continue
            if config.is_file():
                name = _origin_name(config)
            break
    except (OSError, ValueError):
        name = ""
    _git_cache[key] = (now, name)
    return name


def claude_group(item: dict) -> tuple[str, str]:
    folder = _strip(item.get("origin") or item.get("cwd"))
    parts = [p.casefold() for p in re.split(r"[\\/]+", folder)]
    if not folder or "scratch-workspaces" in parts:
        return OTHER_KEY, OTHER_NAME
    name = git_name(folder) or Path(folder).name or folder
    return "f:" + name.casefold(), name


# ---------------------------------------------------------------- the tree


def _groups(catalog: list[dict]) -> dict[tuple[str, str], dict]:
    """(app, key) -> {key, name, items: [(conversation, folder shown under its title)]}; newest first, as the catalog."""
    layout = codex_layout()
    groups: dict[tuple[str, str], dict] = {}
    for item in catalog:
        app = item.get("app")
        if app == "codex":
            placed = codex_group(item, layout)
            if placed is None:
                continue
            key, place = placed
            name = OTHER_NAME if key == OTHER_KEY else layout[0][key]["name"]
        elif app == "claude":
            key, name = claude_group(item)
            place = ""
        elif app == 'deepseek':
            # as the Harness sidebar: by workspace, sessions in none under 其他对话 (10-20; before, every folder was a
            # project, and each one-shot session a script starts in its own folder made one more)
            place = ''
            if item.get('ungrouped'):
                key, name = OTHER_KEY, OTHER_NAME
            elif isinstance(item.get('workspace'), dict):
                key, name = 'w:' + item['workspace']['id'], item['workspace']['name'] or item.get('folder') or OTHER_NAME
            else:  # no workspace table: by folder, as before
                key, name = item.get('cwd') or OTHER_KEY, item.get('folder') or OTHER_NAME
        else:
            continue
        groups.setdefault((app, key), {"key": key, "name": name, "items": []})["items"].append((item, place))
    return groups


def _row(entry: tuple[dict, str], status, now_ms: int) -> dict:
    item, place = entry
    out = {k: item.get(k) for k in ("app", "id", "title", "folder", "cwd", "updated")}
    if place:
        out["place"] = place
    recent = now_ms - int(item.get("updated") or 0) < RECENT_MS
    try:
        out["status"] = status(item) if recent else "idle"
    except Exception:
        out["status"] = "unknown"
    return out


def _new_folder(app: str, group: dict, layout: tuple) -> str:
    """Where the project's ＋ starts a conversation: a Codex project's own folder, for Claude the folder of the
    project's latest conversation (a Claude project is a folder name; two folders of that name are one group)."""
    if group["key"] == OTHER_KEY:
        return ""
    if app == "codex":
        roots = layout[0].get(group["key"], {}).get("roots") or []
        return roots[0] if roots else ""
    item = group["items"][0][0]
    if app == "deepseek" and isinstance(item.get("workspace"), dict) and item["workspace"].get("path"):
        return item["workspace"]["path"]
    return _strip(item.get("origin") or item.get("cwd"))


def tree(catalog: list[dict], status, first: int = FIRST, more: dict | None = None) -> dict:
    """Both apps, each with its projects (most recently used first, 其他对话 last) and their first conversations.
    more: {(app, key): n} sends n more of that project (what the phone had opened with 显示更多 before a refresh).
    Each project carries what its ＋ needs: folder, or projectless for 其他对话 (a conversation in no project)."""
    now_ms = int(time.time() * 1000)
    groups, more, layout = _groups(catalog), more or {}, codex_layout()
    apps = []
    for app, label in (("codex", "Codex"), ("claude", "Claude"), ('deepseek','DeepSeek')):
        mine = [g for (a, _), g in groups.items() if a == app]
        mine.sort(key=lambda g: (g["key"] == OTHER_KEY, -int(g["items"][0][0].get("updated") or 0)))
        projects = []
        for g in mine:
            n = first + max(0, min(300, int(more.get((app, g["key"]), 0))))
            projects.append({"key": g["key"], "name": g["name"], "count": len(g["items"]), "updated": g["items"][0][0].get("updated"),
                             "folder": _new_folder(app, g, layout), "projectless": g["key"] == OTHER_KEY,
                             "items": [_row(e, status, now_ms) for e in g["items"][:n]]})
        if not projects or projects[-1]["key"] != OTHER_KEY:  # always there: its ＋ starts a conversation in no project
            projects.append({"key": OTHER_KEY, "name": OTHER_NAME, "count": 0, "updated": None, "folder": "", "projectless": True, "items": []})
        apps.append({"app": app, "name": label, "count": sum(p["count"] for p in projects), "projects": projects})
    return {"apps": apps, "now": now_ms}


def page(catalog: list[dict], app: str, key: str, offset: int, limit: int, status) -> dict:
    """More conversations of one project, for 显示更多."""
    offset, limit = max(0, offset), max(1, min(100, limit))
    group = _groups(catalog).get((app, key))
    items = group["items"] if group else []
    now_ms = int(time.time() * 1000)
    return {"app": app, "key": key, "count": len(items), "offset": offset,
            "items": [_row(e, status, now_ms) for e in items[offset:offset + limit]]}
