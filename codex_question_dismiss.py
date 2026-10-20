"""Once-only, evidence-bound UIA dismissal. Never sends an answer or activates a window."""
from __future__ import annotations

import hashlib
import json
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERIFIED_VERSION = "26.1007.2314.0"
TIMEOUT = 5.0


def answer_hash(answer):
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def evidence(state, job):
    """Read accepted structured replies from the desktop snapshot, not an HTTP ack."""
    if state.get("id") != job["thread"] or state.get("hostId") != "local":
        return None, "identity_changed"
    history = (state.get("turnHistory") or {}).get("history") or {}
    turns = list((history.get("entitiesByKey") or {}).values()) or state.get("turns", [])
    if isinstance(turns, dict): turns = list(turns.values())
    turn = next((t for t in turns if t.get("turnId") == job["turn_id"]), None)
    if not turn: return None, "turn_unavailable"
    call = job["question_id"].removeprefix("async:")
    item = next((i for i in turn.get("items", []) if i.get("type") == "agentMessage" and i.get("id") == call), None)
    if not item or len(item.get("questions", [])) != 1: return None, "unsupported_question"
    question = item["questions"][0]
    if any(i.get("id") != call and any(q.get("title") == question.get("title") for q in (i.get("questions") or [])) for t in turns for i in t.get("items", [])):
        return None, "ambiguous_question"
    latest, identities = None, {}
    for i in turn.get("items", []):
        kind = i.get("type")
        if kind == "steeringUserMessage":
            if i.get("status") != "accepted": continue
            content = i.get("input", [])
            client = i.get("clientUserMessageId")
            if i.get("serverUserMessageId"): identities[i["serverUserMessageId"]] = client
        elif kind == "userMessage":
            content = i.get("content", [])
            client = i.get("clientId") or identities.get(i.get("id"))
        else: continue
        if len(content) != 1 or content[0].get("type") != "text": continue
        text = content[0].get("text", "").strip()
        match = re.fullmatch(r"<send_user_message_question_reply>\s*([\s\S]*?)\s*</send_user_message_question_reply>", text)
        if not match: continue
        try:
            for reply in json.loads(match[1]):
                if json.loads(reply["questionItemId"]) == ["request_user_input_async", call, 0]:
                    latest = (client, reply["answer"])
        except (ValueError, KeyError, TypeError): continue
    if not latest: return None, "awaiting_desktop_evidence"
    if latest[0] != job["request_id"] or answer_hash(latest[1]) != job["answer_hash"]:
        return None, "answer_superseded"
    return {"title": state.get("title", ""), "question": question["title"],
            "options": question.get("options", []), "answer": latest[1]}, None


def assess(view, spec):
    """Pure eligibility checks, also exercised with hostile/ambiguous UI fixtures."""
    if not view.get("identity_ok"): return "identity_unverified"
    if not view.get("visible"): return "window_not_visible"
    if not view.get("foreground", True): return "window_not_foreground"
    if view.get("card_count") == 0: return "not_present"
    if view.get("card_count") != 1: return "ambiguous_card"
    if view.get("question") != spec["question"] or view.get("options") != spec["options"]: return "card_changed"
    if not view.get("invoke_supported"): return "invoke_unavailable"
    if view.get("focused"): return "editing"
    if not view.get("selection_readable") or not view.get("editor_readable"): return "draft_unreadable"
    selected, draft = view.get("selected", []), view.get("draft", "")
    actual = selected[0] if len(selected) == 1 and not draft else draft if not selected else None
    if not view.get("has_submitted") and not selected and not draft: return "answer_not_rendered"
    if actual != spec["answer"] or not view.get("has_submitted"): return "unsubmitted_draft"
    return None


class DismissManager:
    def __init__(self, bridge, enabled=False, verified_version="", log=None):
        self.bridge, self.enabled, self.version, self.log = bridge, enabled, verified_version, log
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="codex-dismiss")
        self.lock = threading.Lock()
        with bridge._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS desktop_dismiss (request_id TEXT PRIMARY KEY, thread TEXT, turn_id TEXT, question_id TEXT, answer_hash TEXT, created REAL, status TEXT, reason TEXT, windows TEXT)")
            db.execute("UPDATE desktop_dismiss SET status=CASE WHEN status='invoking' THEN 'unconfirmed' ELSE 'retained' END,reason='service_restarted' WHERE status IN ('pending','invoking')")

    def arm(self, rid, tid, card, answers):
        supported = card.get("kind") == "async" and len(card.get("questions", [])) == 1 and not card["questions"][0].get("isSecret")
        reason = "unsupported_question" if not supported else "disabled" if not self.enabled else "version_unverified" if self.version != VERIFIED_VERSION else ""
        answer = next(iter(answers.values()))[0]
        with self.bridge._db() as db:
            db.execute("INSERT OR IGNORE INTO desktop_dismiss VALUES(?,?,?,?,?,?,?,?,?)", (rid, tid, card.get("turn_id"), card["id"], answer_hash(answer), time.time(), "retained" if reason else "armed", reason, "{}"))

    def result(self, rid):
        with self.bridge._db() as db:
            row = db.execute("SELECT status,reason,windows FROM desktop_dismiss WHERE request_id=?", (rid,)).fetchone()
        if not row: return None
        return {"status": "pending" if row[0] in ("armed", "invoking") else row[0], "reason": row[1], "windows": json.loads(row[2])}

    def latest(self, tid, qid):
        with self.bridge._db() as db:
            row = db.execute("SELECT request_id FROM desktop_dismiss WHERE thread=? AND question_id=? ORDER BY created DESC LIMIT 1", (tid, qid)).fetchone()
        return self.result(row[0]) if row else None

    def accepted(self, rid):
        with self.bridge._db() as db:
            changed = db.execute("UPDATE desktop_dismiss SET status='pending' WHERE request_id=? AND status='armed'", (rid,)).rowcount
        if changed: self.pool.submit(self._run, rid, time.monotonic()+TIMEOUT)

    def _save(self, rid, status, reason="", windows=None):
        with self.bridge._db() as db:
            db.execute("UPDATE desktop_dismiss SET status=?,reason=?,windows=COALESCE(?,windows) WHERE request_id=?", (status, reason, json.dumps(windows) if windows is not None else None, rid))

    def _proof(self, job):
        _, _, state = self.bridge.snapshot(job["thread"], True, timeout=1)
        spec, reason = evidence(state, job)
        if spec:
            import chats
            path = chats.codex_db()
            if not path: return None, "title_unverified"
            with sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=.3) as db:
                columns = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
                title = "COALESCE(NULLIF(name,''),title)" if "name" in columns else "title"
                rows = db.execute(f"SELECT id FROM threads WHERE {title}=? LIMIT 2", (spec["title"],)).fetchall()
            if len(rows) != 1 or rows[0][0] != job["thread"]: return None, "title_not_unique"
        return spec, reason

    def _run(self, rid, deadline=None):
        started = time.monotonic(); deadline = deadline or started+TIMEOUT
        proc = None; windows = {}; outcome = "retained"; reason = "probe_failed"
        try:
            with self.bridge._db() as db:
                db.row_factory = sqlite3.Row
                job = dict(db.execute("SELECT * FROM desktop_dismiss WHERE request_id=?", (rid,)).fetchone())
            spec = None
            for attempt in range(3):
                if time.monotonic() >= deadline: break
                spec, reason = self._proof(job)
                if spec or reason != "awaiting_desktop_evidence": break
                time.sleep(.15)
            if not spec: return
            spec.update(version=self.version, expires=time.time()+max(0, deadline-time.monotonic()))
            python = Path(__file__).parent/".venv/Scripts/python.exe"
            proc = subprocess.Popen([str(python), "-X", "utf8", str(Path(__file__).resolve()), "--worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
            inbox = queue.Queue()
            def read():
                for line in proc.stdout:
                    try: inbox.put(json.loads(line))
                    except ValueError: pass
                inbox.put({"event": "eof"})
            threading.Thread(target=read, daemon=True).start()
            proc.stdin.write(json.dumps(spec, ensure_ascii=False)+"\n"); proc.stdin.flush()
            while time.monotonic() < deadline:
                event = inbox.get(timeout=max(.01, deadline-time.monotonic()))
                if event["event"] == "ready":
                    key = event["window"]
                    fresh, why = self._proof(job)
                    permit = fresh is not None and key not in windows and time.monotonic() < deadline
                    if permit:
                        windows[key] = {"status": "unconfirmed", "reason": "invocation_started"}
                        self._save(rid, "invoking", windows=windows)
                    proc.stdin.write(json.dumps({"invoke": permit})+"\n"); proc.stdin.flush()
                    if not permit: reason = why or "expired"
                elif event["event"] == "result":
                    windows[event["window"]] = {"status": event["status"], "reason": event.get("reason", "")}
                elif event["event"] in ("done", "eof"):
                    reason = event.get("reason") or "no_matching_window"
                    break
            statuses = {v["status"] for v in windows.values()}
            outcome = "unconfirmed" if "unconfirmed" in statuses else "retained" if "retained" in statuses else "closed" if "closed" in statuses else "not_present" if statuses == {"not_present"} else "retained"
            if windows: reason = next((v["reason"] for v in windows.values() if v["reason"]), "")
        except Exception:
            outcome = "unconfirmed" if any(v["status"] in ("closed", "unconfirmed") for v in windows.values()) else "retained"
            reason = "timeout_or_probe_error"
        finally:
            if proc:
                if proc.poll() is None: proc.kill()
                proc.wait(timeout=1)
                for stream in (proc.stdin, proc.stdout): stream.close()
            self._save(rid, outcome, reason or ("" if windows else "evidence_unavailable"), windows)
            if self.log: self.log(f"codex-dismiss request={rid} status={outcome} reason={reason or 'none'} elapsed_ms={round((time.monotonic()-started)*1000)}")


def worker():
    """Private stdin/stdout protocol; no generic UI action endpoint."""
    import ctypes
    import win32api
    import win32gui
    import win32process
    import uiautomation as auto
    from uiautomation import uiautomation as core
    spec = json.loads(sys.stdin.readline())
    auto.InitializeUIAutomationInCurrentThread()
    auto.SetGlobalSearchTimeout(.2)
    uia = core._AutomationClient.instance().IUIAutomation
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint)]
    def emit(value): print(json.dumps(value), flush=True)
    def alive(): return time.time() < spec["expires"]
    def find(root, kind, name=None):
        c = uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, getattr(auto.ControlType, kind))
        if name is not None: c = uia.CreateAndCondition(c, uia.CreatePropertyCondition(auto.PropertyId.NameProperty, name))
        rows = root.Element.FindAll(4, c)
        return [auto.Control.CreateControlFromElement(rows.GetElement(i)) for i in range(rows.Length)]
    def identity(hwnd):
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        handle = win32api.OpenProcess(0x1000, False, pid)
        try:
            buf = ctypes.create_unicode_buffer(32768); size = ctypes.c_uint(len(buf))
            if not k32.QueryFullProcessImageNameW(int(handle), 0, buf, ctypes.byref(size)): return None
            expected = f"\\windowsapps\\openai.codex_{spec['version']}_x64__2p2nqsd0c76g0\\app\\chatgpt.exe"
            return pid if buf.value.casefold().endswith(expected) else None
        finally: handle.Close()
    def observe(hwnd):
        visible = win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd)
        pid = identity(hwnd)
        view = {"identity_ok": False, "visible": visible, "foreground": win32gui.GetForegroundWindow() == hwnd, "card_count": 0}
        if not visible or not pid: return view, None
        root = auto.ControlFromHandle(hwnd)
        docs = [d for d in find(root, "DocumentControl") if d.Name == spec["title"] and not d.IsOffscreen]
        if len(docs) != 1: return view, None
        doc = docs[0]
        bars = find(doc, "ToolBarControl", "Chat toolbar")
        if len(bars) != 1 or not any(t.Name == spec["title"] for t in find(bars[0], "TextControl")): return view, None
        view["identity_ok"] = True
        cards = []
        for button in find(doc, "ButtonControl", "Dismiss"):
            p = button.GetParentControl()
            if "@container/request-card" in p.ClassName and any(t.Name == spec["question"] for t in find(p, "TextControl")):
                cards.append((p, button))
        view["card_count"] = len(cards)
        if len(cards) != 1: return view, None
        card, button = cards[0]
        radios = find(card, "RadioButtonControl")
        patterns = [r.GetPattern(auto.PatternId.SelectionItemPattern) for r in radios]
        edits = find(card, "EditControl")
        draft = None
        if len(edits) == 1:
            pat = edits[0].GetPattern(auto.PatternId.ValuePattern)
            if pat:
                draft = pat.Value
                placeholders = [v for v in edits[0].GetChildren() if v.ClassName == "placeholder"]
                if placeholders and draft.strip() == edits[0].Name: draft = ""
                else: draft = draft.rstrip("\r\n")
        updates = find(card, "ButtonControl", "Send update")
        children = card.Element.FindAll(4, uia.CreateTrueCondition())
        focused = any(auto.Control.CreateControlFromElement(children.GetElement(i)).HasKeyboardFocus for i in range(children.Length))
        view.update(question=spec["question"], options=[r.Name for r in radios], selection_readable=all(patterns),
                    selected=[r.Name for r, p in zip(radios, patterns) if p and p.IsSelected],
                    editor_readable=draft is not None, draft=draft, focused=focused,
                    has_submitted=len(updates) == 1,
                    invoke_supported=bool(button.GetPattern(auto.PatternId.InvokePattern)) and button.IsEnabled and not button.IsOffscreen,
                    runtime=list(button.GetRuntimeId()), card_runtime=list(card.GetRuntimeId()), pid=pid)
        return view, button
    windows = []
    win32gui.EnumWindows(lambda h, _: windows.append(h) if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == "ChatGPT" else None, None)
    for hwnd in windows:
        if not alive(): break
        view, button = observe(hwnd)
        if not view["identity_ok"]: continue
        key = f"{hwnd}:{view.get('pid',0)}"
        reason = assess(view, spec)
        # Chromium may expose the previous selection briefly after the accepted
        # reply. Re-read only; never infer a clean draft from the transport ack.
        for delay in (.15, .25):
            if reason not in ("unsubmitted_draft", "answer_not_rendered") or not alive(): break
            time.sleep(delay)
            view, button = observe(hwnd)
            reason = assess(view, spec)
        if reason:
            emit({"event": "result", "window": key, "status": "not_present" if reason == "not_present" else "retained", "reason": reason})
            continue
        foreground = win32gui.GetForegroundWindow()
        emit({"event": "ready", "window": key})
        permit = json.loads(sys.stdin.readline())
        if not permit.get("invoke") or not alive(): break
        latest, current_button = observe(hwnd)
        if assess(latest, spec) or latest != view or win32gui.GetForegroundWindow() != foreground:
            emit({"event": "result", "window": key, "status": "retained", "reason": "changed_before_invoke"}); continue
        if not alive(): break
        current_button.GetPattern(auto.PatternId.InvokePattern).Invoke()
        after, _ = observe(hwnd)
        success = after["identity_ok"] and after["card_count"] == 0 and win32gui.GetForegroundWindow() == foreground
        if not success and alive():
            time.sleep(.08)
            after, _ = observe(hwnd)
            success = after["identity_ok"] and after["card_count"] == 0 and win32gui.GetForegroundWindow() == foreground
        emit({"event": "result", "window": key, "status": "closed" if success else "unconfirmed", "reason": "" if success else "postcheck_failed"})
    emit({"event": "done"})


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    worker()
