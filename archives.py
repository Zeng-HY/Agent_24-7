"""Archive from the phone (10-20): a left swipe on a conversation archives it on this computer, 撤销 brings it back, and
设置 → 已归档对话 lists the archived ones to restore or delete. Deleting happens only there, never on the main list.

Codex (archive, restore, delete): a codex.exe app-server of our own, the way a new conversation is made
(new_conversations), closed again straight after, so it never keeps hold of a conversation the desktop wants:
thread/archive, thread/unarchive, thread/delete. Then the desktop is told on its pipe, as the desktop tells its other
windows after archiving (thread-archived v2, thread-unarchived v1, params {hostId: 'local', conversationId}), and its
sidebar follows at once. A conversation the desktop has open, or had open a moment ago, cannot be archived from
outside: the desktop's own app-server is its writer ("already has an active writer") until it lets go some minutes
later. 10-20 on a throwaway conversation: archive 0.06 s, restore 2-5 s, delete 1.8 s (plus about 1 s to start the
app-server); delete takes the record file and the database row for good.

DeepSeek (archive, restore): workspace/archiveSession and workspace/unarchiveSession on its local interface; a running
conversation is refused (workspace/session-active) rather than stopped. DeepSeek has no delete: it keeps session files
until something outside removes them and has no interface for that (its storage notes, 10-20).

Claude: not yet; its archive works differently.
"""
from __future__ import annotations

import json
import queue
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import chats

APPS = ("codex", "deepseek")  # what the phone may archive; Claude comes later
DELETABLE = ("codex",)
WRITER = ("already has an active writer", "already has a live local writer")


class ArchiveError(chats.ChatError):
    def __init__(self, text: str, status: int = 409):
        super().__init__(text)
        self.status = status


class CodexRefused(ArchiveError):
    """Codex's app-server answered with an error; the text is its own."""


class CodexServer:
    """codex.exe app-server of our own for one batch of calls: the desktop's pipe has no archive. Closed when done, so it
    never stays the writer of a conversation the desktop opens next."""

    def __init__(self, timeout: float = 30):
        import new_conversations
        cli = new_conversations.codex_cli()
        if not cli:
            raise ArchiveError("没找到这台电脑上的 Codex", 503)
        self.p = subprocess.Popen([str(cli), "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.replies: queue.Queue = queue.Queue()
        self.next = 1
        threading.Thread(target=self._read, name="codex-archive-read", daemon=True).start()
        try:
            self.call("initialize", {"clientInfo": {"name": "agent_remote", "version": "archive"},
                                     "capabilities": {"experimentalApi": True}}, timeout)
            self._write({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def _read(self) -> None:
        try:
            for line in self.p.stdout:
                try:
                    self.replies.put(json.loads(line))
                except ValueError:
                    pass
        finally:
            self.replies.put(None)

    def _write(self, message: dict) -> None:
        try:
            self.p.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.p.stdin.flush()
        except OSError:
            raise ArchiveError("Codex 后台进程意外退出了", 503) from None

    def call(self, method: str, params: dict, timeout: float = 40):
        ident = self.next
        self.next += 1
        self._write({"id": ident, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ArchiveError(f"Codex 没在 {timeout:.0f} 秒内答复，结果未确认；刷新列表看看", 504)
            try:
                reply = self.replies.get(timeout=left)
            except queue.Empty:
                continue
            if reply is None:
                raise ArchiveError("Codex 后台进程意外退出了", 503)
            if reply.get("id") != ident:
                continue  # notifications (account, models, remote control) and nothing else
            if "error" in reply:
                error = reply["error"]
                raise CodexRefused(str(error.get("message") if isinstance(error, dict) else error)[:300])
            return reply.get("result")

    def close(self) -> None:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def codex_rows(where: str, args: tuple = (), limit: int = 500) -> list[dict]:
    """Codex conversations as the lists show them (subagents, guardian reviews and codex exec runs left out), archived
    or not, with when they were archived."""
    db = chats.codex_db()
    if db is None:
        return []
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3)
    try:
        cols = {r[1] for r in con.execute("pragma table_info(threads)")}
        col = lambda name, fallback: name if name in cols else fallback
        filters = ["coalesce(thread_source, '') not in ('subagent', 'guardian_review')"]
        if "source" in cols:
            filters.append("coalesce(source, '') != 'exec'")
        rows = con.execute(
            "select id, " + col("name", "''") + ", title, cwd, " + col("updated_at_ms", "updated_at * 1000") + ", archived, "
            + col("archived_at", "0") + " from threads where " + " and ".join(filters + [where])
            + " order by " + col("archived_at", "updated_at") + " desc limit ?", args + (limit,)).fetchall()
    finally:
        con.close()
    out = []
    for tid, name, title, cwd, updated, archived, archived_at in rows:
        cwd = chats._strip_unc(cwd or "")
        label = (name or "").strip()
        if not label:
            first = chats.clean_codex_user(title or "").strip().splitlines()
            label = chats.one_line(first[0], 60) if first else ""
        out.append({"app": "codex", "id": tid, "title": label or "（无标题）", "cwd": cwd, "folder": Path(cwd).name if cwd else "",
                    "updated": int(updated or 0), "archived": bool(archived), "archived_at": int(archived_at or 0) * 1000})
    return out


def deepseek_reason(exc) -> str:
    """What DeepSeek said when it refused: its own words and code (deepseek_control.Client keeps them), or ours."""
    detail, code = getattr(exc, "detail", ""), getattr(exc, "code", "")
    return (detail or str(exc)) + (f"（{code}）" if code else "")


def codex_row(tid: str) -> dict | None:
    rows = codex_rows("id = ?", (tid,), 1)
    return rows[0] if rows else None


def deepseek_archived(ds) -> list[dict]:
    """DeepSeek's archived conversations (subagents and empty ones left out), newest first: from the running Harness,
    or from its stored summaries while it is closed."""
    import deepseek_control
    archived = [str(v) for v in deepseek_control.workspace_meta().get("archivedSessionIds", []) if isinstance(v, str)]
    if not archived:
        return []
    wanted, out = set(archived), {}
    try:
        data = ds.client.call("session/list", {"_request": {}})
        for row in (data or {}).get("items") or []:
            sid = str((row or {}).get("sessionId") or "")
            if sid not in wanted or row.get("blank") or row.get("origin") == "subagent":
                continue
            values = (row.get("projections") or {}).get("values") or {}
            cwd = str(row.get("cwd") or values.get("workingDirectory") or "")
            out[sid] = {"app": "deepseek", "id": sid, "title": str(values.get("title") or "") or "新对话", "cwd": cwd,
                        "folder": Path(cwd).name if cwd else "", "updated": int(row.get("updatedAt") or 0), "archived": True}
    except Exception:  # the Harness closed: what it stored about each one
        for sid in archived:
            path = deepseek_control.HOME / "storages/session_projcache/sessions" / f"{sid}.json"
            try:
                record = json.loads(path.read_text(encoding="utf-8"))["record"]
                found, identity = record["rows"], record["identity"]
                title = (found.get("title") or {}).get("val")
                if not title or (found.get("subagent") or {}).get("val"):
                    continue
                cwd = str(identity.get("cwd") or "")
                out[sid] = {"app": "deepseek", "id": sid, "title": str(title), "cwd": cwd, "folder": Path(cwd).name if cwd else "",
                            "updated": int(path.stat().st_mtime * 1000), "archived": True}
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
    order = {sid: i for i, sid in enumerate(archived)}  # DeepSeek adds an archived one at the end
    return sorted(out.values(), key=lambda v: -order.get(v["id"], -1))


class Archives:
    def __init__(self, codex_bridge=None, history=None, log=None, server=CodexServer, deepseek=None, apps=None):
        self.codex_bridge = codex_bridge  # codex_control.Bridge: its pipe to the desktop, for the broadcasts
        self.history = history
        self.log = log or (lambda text: None)
        self.server = server
        self._deepseek = deepseek
        self.apps = apps or (lambda: list(APPS))  # the apps this computer has (remote.py: MACHINE.apps)
        self.lock = threading.Lock()  # one app-server of ours at a time

    def deepseek(self):
        if self._deepseek is not None:
            return self._deepseek
        import deepseek_control
        return deepseek_control.bridge()

    def _changed(self) -> None:
        """The lists read again at once instead of in up to 10 s."""
        if self.history is not None:
            self.history.invalidate()
        try:
            self.deepseek().cache = (0, None)
        except Exception:
            pass

    def _tell_desktop(self, method: str, version: int, tid: str) -> None:
        """Codex desktop's sidebar follows at once, as its windows tell each other; without it, at its next refresh."""
        try:
            self.codex_bridge._pipe().broadcast(method, version, {"hostId": "local", "conversationId": tid})
        except Exception as exc:
            self.log(f"没能告诉 Codex 桌面版 {method}（{tid}）：{exc}")

    @staticmethod
    def _check(app: str, tid) -> None:
        if app == "claude":
            raise ArchiveError("Claude 的对话还不能从手机归档", 400)
        if app not in APPS:
            raise ArchiveError("不认识这个软件", 400)
        if not isinstance(tid, str) or not tid or len(tid) > 200:
            raise ArchiveError("对话编号无效", 400)

    # -- archive and restore

    def archive(self, app: str, tid: str) -> dict:
        self._check(app, tid)
        if app == "codex":
            item = chats.find("codex", tid)  # an archived or unknown one is not found
            if chats.summary(item).get("status") == "running":
                raise ArchiveError("这个对话正在运行，先停止这一轮再归档")
            with self.lock, self.server() as server:
                try:
                    server.call("thread/archive", {"threadId": tid})
                except CodexRefused as exc:
                    if any(w in str(exc).lower() for w in WRITER):
                        raise ArchiveError("电脑上的 Codex 正开着这个对话（或刚开过），这段记录被它占着，现在归档不了。"
                                           "过几分钟再试，或者在电脑上归档。") from None
                    raise ArchiveError("Codex 没有归档：" + str(exc)) from None
            self._tell_desktop("thread-archived", 2, tid)
        else:
            import deepseek_control
            ds = self.deepseek()
            ds.find(tid)
            try:
                ds.client.call("workspace/archiveSession", {"request": {"sessionId": tid}})
            except deepseek_control.DeepSeekError as exc:
                if getattr(exc, "code", "") == "workspace/session-active":
                    raise ArchiveError("这个对话正在运行，先停止这一轮再归档") from None
                raise ArchiveError("DeepSeek 没有归档：" + deepseek_reason(exc)) from None
        self._changed()
        self.log(f"手机上归档了 {app} 对话 {tid}")
        return {"ok": True, "app": app, "id": tid, "archived": True}

    def unarchive(self, app: str, tid: str) -> dict:
        self._check(app, tid)
        if app == "codex":
            row = codex_row(tid)
            if row is None:
                raise ArchiveError("找不到这个 Codex 对话（可能已经删掉了）", 404)
            if row["archived"]:
                with self.lock, self.server() as server:
                    try:
                        server.call("thread/unarchive", {"threadId": tid}, 60)
                    except CodexRefused as exc:
                        raise ArchiveError("Codex 没有恢复：" + str(exc)) from None
                self._tell_desktop("thread-unarchived", 1, tid)
        else:
            import deepseek_control
            try:
                self.deepseek().client.call("workspace/unarchiveSession", {"request": {"sessionId": tid}})
            except deepseek_control.DeepSeekError as exc:
                raise ArchiveError("DeepSeek 没有恢复：" + deepseek_reason(exc)) from None
        self._changed()
        self.log(f"手机上恢复了 {app} 对话 {tid}")
        return {"ok": True, "app": app, "id": tid, "archived": False}

    # -- the archived list, and deleting from it

    def archived(self) -> dict:
        items, problems, apps = [], [], self.apps()
        if "codex" in apps:
            try:
                items += [dict(v, can_delete=True) for v in codex_rows("archived = 1")]
            except (sqlite3.Error, OSError) as exc:
                problems.append(f"Codex：{exc}")
        if "deepseek" in apps:
            try:
                items += [dict(v, can_delete=False) for v in deepseek_archived(self.deepseek())]
            except Exception as exc:
                problems.append(f"DeepSeek：{str(exc)[:120]}")
        return {"items": items, "problems": problems, "apps": [a for a in APPS if a in apps],
                "deletable": [a for a in DELETABLE if a in apps]}

    def delete(self, items) -> dict:
        """Deletes archived Codex conversations for good; anything else is left alone and said so."""
        if not isinstance(items, list) or not items or len(items) > 200:
            raise ArchiveError("没有选要删除的对话", 400)
        results, codex = [], []
        for v in items:
            app, tid = (v.get("app"), v.get("id")) if isinstance(v, dict) else (None, None)
            if app == "codex" and isinstance(tid, str) and tid:
                row = codex_row(tid)
                if row is None:
                    results.append({"app": app, "id": tid, "ok": True, "gone": True})
                elif not row["archived"]:
                    results.append({"app": app, "id": tid, "ok": False, "error": "只能删除已归档的对话"})
                else:
                    codex.append(tid)
            else:
                results.append({"app": app, "id": tid, "ok": False,
                                "error": "DeepSeek 没有删除对话的功能，只能恢复" if app == "deepseek" else "这种对话还不能删除"})
        if codex:
            with self.lock, self.server() as server:
                for tid in codex:
                    try:
                        server.call("thread/delete", {"threadId": tid}, 60)
                        results.append({"app": "codex", "id": tid, "ok": True})
                    except CodexRefused as exc:
                        results.append({"app": "codex", "id": tid, "ok": False, "error": str(exc)[:160]})
            for r in results:
                if r["app"] == "codex" and r.get("ok") and not r.get("gone"):
                    self._tell_desktop("thread-archived", 2, r["id"])  # the desktop reads its archived list again
                    self.log(f"手机上删除了 Codex 对话 {r['id']}")
        self._changed()
        return {"ok": all(r.get("ok") for r in results), "results": results,
                "deleted": sum(1 for r in results if r.get("ok") and not r.get("gone"))}
