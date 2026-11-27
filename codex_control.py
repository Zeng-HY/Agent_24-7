"""Local desktop follower bridge. Never starts or resumes an independent app-server.

Protocol verified against Codex Windows 26.1106.6628.0 and 26.1111.2228.0. 26.1111 only raised
thread-stream-state-changed's version, 11 to 13; the snapshot and patch shapes were unchanged. Both already wanted
the queue at 3 (set-queued-follow-ups-state and its changed broadcast), which Teleply only caught up with on 11-17
(see VERSIONS). A missing owner,
unknown snapshot version or disconnected pipe disables actions instead of falling back to blind keystrokes. Only the
narrow methods below are exposed to the phone.
"""
from __future__ import annotations

import copy
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import mmap
import queue
import re
import sqlite3
import struct
import threading
import time
import tomllib
import traceback
import uuid
from pathlib import Path
from app_paths import DATA
from datetime import datetime
from contextlib import contextmanager

import pc_clock

import pywintypes
import win32con
import win32event
import win32file
import win32pipe

import chats
import codex_question_dismiss
import composer_commands

HERE = Path(__file__).resolve().parent
# 26.1111.2228.0: 11-17 on this computer, asking for the owner, the v13 snapshot, reading status and confirm_open all
# worked (v13-snapshot-shape.txt, v13-trial.txt). A Codex newer than this is not trusted to behave the same.
TESTED_APP_VERSION = "26.1111.2228.0"
# 11-17: 26.1106 sends thread-stream-state-changed v11, 26.1111.2228.0 sends v13. Only the number changed: the
# snapshot {type, revision, conversationState} and patches {type, baseRevision, revision, patches} are the same, the
# receiving code is the same, and Immer's add/replace/remove patches match apply_patches. A version not here is still
# thrown away (a later format must not be read wrongly; confirm_open then says the state cannot be read).
STREAM_STATE_VERSIONS = (11, 13)
VERSIONS = {"initialize": 0, "thread-owner-discovery": 1,
            "thread-follower-read-model-settings": 1, "thread-follower-start-turn": 2,
            "thread-follower-steer-turn": 1, "thread-follower-submit-user-input": 1}
VERSIONS["thread-follower-interrupt-turn"] = 4
# 11-17: Codex 26.1106 and 26.1111 take set-queued-follow-ups-state only at v3 (the table in early-bootstrap.js). v1
# was answered request-version-mismatch, so from 11-15 on a message the phone sent while Codex was working never
# reached Codex and stayed 送达状态待确认. The params did not change ({conversationId, state, discardedMessageIds});
# v3's preparationMessageId is for a message Codex is still preparing itself (its Aj() throws for a plain one), so it
# is not sent. A number Codex does not take is refused before anything is done, so v1 is tried next for a Codex that
# has not updated yet. Its queue-changed broadcast went from v2 to v3 too ({conversationId, messages, hostId}).
VERSIONS.update({"thread-follower-set-queued-follow-ups-state": (3, 1),
                 "thread-follower-remove-queued-message": 1})
QUEUE_CHANGED_VERSIONS = (2, 3)
# 11-16: Codex's approval cards reach the phone. The owner answers over the same follower pipe as its questions
# (app.asar 26.1106: replyWithCommandExecutionApprovalDecision / replyWithFileChangeApprovalDecision).
VERSIONS["thread-follower-command-approval-decision"] = 1
VERSIONS["thread-follower-file-approval-decision"] = 1
# 0.6.6: the desktop's own /compact; its owner window runs thread/compact/start (app.asar 26.1021).
VERSIONS["thread-follower-compact-thread"] = 1


class ControlError(Exception):
    def __init__(self, message: str, status: int = 409, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code  # why, for the phone and the log: "no-client-found", "timeout", the desktop's own error


# 11-17: what Codex answers before it does anything at all (its IPC handleRequest checks the version number, then
# looks for a handler), and the router's "no window has this conversation". A request answered so was not carried
# out, so a send can be called not sent (未接收) instead of staying 送达状态待确认 for good.
REFUSED = ("request-version-mismatch", "no-handler-for-request")
UNTAKEN = REFUSED + ("no-client-found",)


def untaken(exc, codes=UNTAKEN):
    return isinstance(exc, ControlError) and (exc.code in codes or any(c in str(exc) for c in codes))


STUCK_AFTER = 600  # seconds: no send is still on its way to Codex this long after it began (relay and pipe give up first)

# A send's request number, as the delivery record takes it and as a receipt can be asked for it later. The phone's own
# numbers are 12-80 letters, digits, '-' or '_' (11-26: every Claude send keeps a record now, not only picture sends).
REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{12,80}")


def recordable(request_id) -> bool:
    """Whether this request number can go into the delivery record (and be looked up by it afterwards)."""
    return isinstance(request_id, str) and REQUEST_ID.fullmatch(request_id) is not None


def reject_delivery(bridge, request_id, exc) -> None:
    """11-26 P6: a send the desktop turned away before submitting anything is 未接收 (rejected) with the reason, instead
    of staying 'dispatching' for good. The same request number sent again then gets that answer back, never "这次请求
    已提交过，结果尚未确认". Never raises: the refusal itself is what the phone has to see."""
    if not recordable(request_id):
        return
    try:
        bridge._finish(str(request_id), {"ok": False, "delivery_state": "rejected",
                                         "request_id": str(request_id), "text": str(exc)[:350]})
    except Exception:
        pass


def record_missing(path, request_id, table="deliveries"):
    """11-26 P1/8.1: whether this assistant's delivery record file proves the phone's message was never received.

    True only when the file is there, can be read, and holds no row for this request id in any conversation. None when
    the file is not there or cannot be read - a wiped file that has no such table counts as unreadable - because then
    the receipt says plain "unknown" as it always did, and the phone keeps 送达状态待确认."""
    try:
        path = Path(path)
        if not path.is_file():
            return None
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    except (OSError, sqlite3.Error, ValueError):
        return None
    try:
        return con.execute(f"SELECT 1 FROM {table} WHERE id=? LIMIT 1", (request_id,)).fetchone() is None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def file_has(path, needle):
    """Whether the bytes appear anywhere in the file, looked for through a map rather than read into memory."""
    with open(path, "rb") as f:
        try:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as view:
                return view.find(needle) != -1
        except ValueError:  # an empty file cannot be mapped
            return False


class DesktopPipe:
    def __init__(self):
        self.client = "initializing-client"
        self.pending = {}
        self.snapshots = {}
        self.revisions = {}
        self.watches = {}
        self.follow_owners = {}
        self.queues = {}
        self.write_lock = threading.Lock()
        self.condition = threading.Condition()
        self.closed = False
        self.handle = win32file.CreateFile(r"\\.\pipe\codex-ipc", win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                          0, None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_OVERLAPPED, None)
        threading.Thread(target=self._read, name="codex-follower-read", daemon=True).start()
        try:
            self.client = self.call("initialize", {"clientType": "agent-remote"})["result"]["clientId"]
        except Exception:
            self.close()
            raise

    def _send(self, value):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if len(raw) > 32 << 20:
            raise ControlError("请求过大", 413)
        with self.write_lock:
            if self.closed:
                raise ControlError("Codex 控制连接已断开")
            ov = pywintypes.OVERLAPPED()
            ov.hEvent = win32event.CreateEvent(None, True, False, None)
            try:
                win32file.WriteFile(self.handle, struct.pack("<I", len(raw)) + raw, ov)
                if win32event.WaitForSingleObject(ov.hEvent, 10000) == win32event.WAIT_TIMEOUT:
                    self.close()
                    raise ControlError("Codex 请求传输超时，结果未确认")
                win32file.GetOverlappedResult(self.handle, ov, True)
            finally:
                ov.hEvent.Close()

    def _read(self):
        buf = b""
        try:
            while not self.closed:
                ov = pywintypes.OVERLAPPED()
                ov.hEvent = win32event.CreateEvent(None, True, False, None)
                try:
                    _, chunk = win32file.ReadFile(self.handle, 65536, ov)
                    size = win32file.GetOverlappedResult(self.handle, ov, True)
                    if not size:
                        break
                    buf += bytes(chunk[:size])
                finally:
                    ov.hEvent.Close()
                while len(buf) >= 4:
                    size = struct.unpack("<I", buf[:4])[0]
                    if not 0 < size <= 268435456:
                        raise ValueError("Invalid desktop frame")
                    if len(buf) < size + 4:
                        break
                    msg = json.loads(buf[4:size+4])
                    buf = buf[size+4:]
                    if msg.get("type") == "response":
                        waiter = self.pending.get(msg.get("requestId"))
                        if waiter:
                            waiter.put(msg)
                    elif msg.get("type") == "client-discovery-request":
                        self._send({"type": "client-discovery-response", "requestId": msg["requestId"],
                                    "response": {"canHandle": False}})
                    elif msg.get("type") == "broadcast" and msg.get("method") == "thread-queued-followups-changed":
                        params = msg.get("params") or {}
                        if msg.get("version") in QUEUE_CHANGED_VERSIONS and params.get("hostId", "local") == "local":
                            with self.condition:
                                self.queues[params.get("conversationId")] = (msg.get("sourceClientId"), params)
                                self.condition.notify_all()
                    elif msg.get("type") == "broadcast" and msg.get("method") == "thread-stream-state-changed":
                        params = msg.get("params") or {}
                        change = params.get("change") or {}
                        if params.get("hostId") == "local" and msg.get("version") not in STREAM_STATE_VERSIONS:
                            with self.condition:
                                tid=params.get("conversationId");self.snapshots.pop(tid,None);self.revisions.pop(tid,None);self.condition.notify_all()
                        if params.get("hostId") == "local" and msg.get("version") in STREAM_STATE_VERSIONS and change.get("type") == "snapshot":
                            state = change.get("conversationState") or {}
                            if state.get("id") == params.get("conversationId"):
                                with self.condition:
                                    self.snapshots[state["id"]] = (time.monotonic(), msg.get("sourceClientId"), state)
                                    self.revisions[state["id"]] = change.get("revision")
                                    if len(self.snapshots) > 8:
                                        oldest = min(self.snapshots, key=lambda k:self.snapshots[k][0])
                                        self.snapshots.pop(oldest, None)
                                    self.condition.notify_all()
                        elif params.get("hostId") == "local" and msg.get("version") in STREAM_STATE_VERSIONS and change.get("type") == "patches":
                            tid=params.get("conversationId")
                            with self.condition:
                                record=self.snapshots.get(tid)
                                if record and record[1]==msg.get("sourceClientId") and self.revisions.get(tid)==change.get("baseRevision"):
                                    try:
                                        apply_patches(record[2],change.get("patches") or [])
                                        self.snapshots[tid]=(time.monotonic(),record[1],record[2]);self.revisions[tid]=change.get("revision")
                                    except (KeyError,IndexError,ValueError,TypeError):self.snapshots.pop(tid,None)
                                else:self.snapshots.pop(tid,None)
                                self.condition.notify_all()
                    elif msg.get("type")=="broadcast" and msg.get("method")=="client-status-changed" and (msg.get("params") or {}).get("status")=="disconnected":
                        owner=msg["params"].get("clientId")
                        with self.condition:
                            for tid,record in list(self.snapshots.items()):
                                if record[1]==owner:self.snapshots.pop(tid,None)
        except Exception:
            pass
        finally:
            self.closed = True
            for waiter in list(self.pending.values()):
                waiter.put({"resultType": "error", "error": "connection-closed"})
            with self.condition:
                self.condition.notify_all()

    def call(self, method, params, owner=None, timeout=15):
        if method not in VERSIONS:
            raise ControlError("不支持这个操作")
        versions = VERSIONS[method] if isinstance(VERSIONS[method], tuple) else (VERSIONS[method],)
        for version in versions:
            try:
                return self._call(method, version, params, owner, timeout)
            except ControlError as exc:
                # Codex checks the number before it does anything, so trying the next one cannot do a thing twice.
                if exc.code != "request-version-mismatch" or version == versions[-1]:
                    raise

    def _call(self, method, version, params, owner, timeout):
        rid = str(uuid.uuid4())
        waiter = queue.Queue()
        self.pending[rid] = waiter
        request = {"type": "request", "requestId": rid, "sourceClientId": self.client,
                   "version": version, "method": method, "params": params, "timeoutMs": int(timeout*1000)}
        if owner:
            request["targetClientId"] = owner
        try:
            self._send(request)
            result = waiter.get(timeout=timeout+1)
            if result.get("resultType") != "success":
                error = str(result.get("error", "未知错误"))
                if error == "no-client-found":
                    raise ControlError("电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试", code="no-client-found")
                if error in REFUSED:
                    raise ControlError("电脑上的 Codex 升级了，遥应还不会这一步，没有执行", code=error)
                raise ControlError("Codex 未完成操作：" + error[:180], code=error[:80])
            if owner and result.get("handledByClientId") != owner:
                raise ControlError("对话持有者发生变化，结果未确认")
            return result
        except queue.Empty:
            raise ControlError("Codex 响应超时，结果未确认；不会自动重试", code="timeout") from None
        finally:
            self.pending.pop(rid, None)

    def broadcast(self, method, version, params):
        """To every window on the pipe, as the desktop's windows tell each other: thread-archived (v2) and
        thread-unarchived (v1) with {hostId, conversationId} after an archive made elsewhere (archives.py, 10-20)."""
        self._send({"type": "broadcast", "sourceClientId": self.client, "method": method, "version": version, "params": params})

    def follow(self, tid, owner, value):
        self._send({"type": "broadcast", "sourceClientId": self.client, "method": "thread-stream-following-changed",
                    "version": 1, "targetClientIds": [owner],
                    "params": {"conversationId": tid, "hostId": "local", "following": value}})
        with self.condition:
            if value:self.follow_owners[tid]=owner
            else:self.follow_owners.pop(tid,None)

    def snapshot(self, tid, timeout=15, timing=None):
        if timing:timing('owner_discovery','等待桌面对话持有者')
        owner = self.call("thread-owner-discovery", {"hostId": "local", "conversationId": tid}, timeout=timeout)["handledByClientId"]
        if timing:timing('owner_snapshot','等待桌面首次状态')
        started = time.monotonic()
        self.follow(tid, owner, True)
        try:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or (tid in self.snapshots and self.snapshots[tid][0] >= started), min(6,timeout))
                record = self.snapshots.get(tid)
                if self.closed or not record or record[0] < started or record[1] != owner:
                    raise ControlError("没有取得当前会话快照，请在电脑打开该对话后重试")
                state = copy.deepcopy(record[2])
            return owner, state
        finally:
            if not self.closed and tid not in self.watches:
                self.follow(tid, owner, False)

    def watch(self,tid):
        with self.condition:self.watches[tid]=self.watches.get(tid,0)+1
        try:return self.snapshot(tid)
        except Exception:self.unwatch(tid);raise

    def unwatch(self,tid):
        with self.condition:
            count=self.watches.get(tid,0)-1
            if count>0:self.watches[tid]=count;return
            self.watches.pop(tid,None);owner=self.follow_owners.get(tid)
        if owner and not self.closed:
            try:self.follow(tid,owner,False)
            except Exception:pass

    def close(self):
        self.closed = True
        try:
            ctypes.windll.kernel32.CancelIoEx(ctypes.c_void_p(int(self.handle)), None)
            win32file.CloseHandle(self.handle)
        except Exception:
            pass


def ordered_turns(state):
    history = (state.get("turnHistory") or {}).get("history") or {}
    values = list((history.get("entitiesByKey") or {}).values()) or state.get("turns", [])
    return sorted(values, key=lambda v: v.get("turnStartedAtMs") or 0)

def apply_patches(state,patches):
    """Apply only the JSON object/list operations used by the versioned desktop stream."""
    for patch in patches:
        path=patch.get('path');op=patch.get('op')
        if not isinstance(path,list) or op not in ('add','replace','remove'):raise ValueError('unsupported patch')
        if not path:
            if op not in ('add','replace') or not isinstance(patch.get('value'),dict):raise ValueError('invalid root')
            state.clear();state.update(patch['value']);continue
        parent=state
        for key in path[:-1]:parent=parent[key]
        key=path[-1]
        if isinstance(parent,list):
            if not isinstance(key,int) or key<0 or key>len(parent):raise ValueError('invalid array path')
            if op=='add':parent.insert(key,patch['value'])
            elif op=='replace':parent[key]=patch['value']
            else:parent.pop(key)
        elif isinstance(parent,dict):
            if op=='remove':del parent[key]
            else:parent[key]=patch['value']
        else:raise ValueError('invalid patch parent')


def normalize_settings(settings):
    result=dict(settings)
    tier=result.get('service_tier')
    result['service_tier']=None if tier in (None,'','default') else 'priority' if tier=='fast' else tier
    return result


def selected_settings(state):
    mode = state.get("latestCollaborationMode") or {}
    details = mode.get("settings") or {}
    recorded = state.get("latestThreadSettings") or {}
    return normalize_settings({"model": details.get("model") or state.get("latestModel"),
            "effort": details.get("reasoning_effort") or recorded.get("effort") or state.get("latestReasoningEffort"),
            "service_tier": 'priority' if recorded.get("serviceTier")=='fast' else recorded.get("serviceTier"),
            "mode": mode.get("mode") or "default"})


def is_running(state):
    turns = ordered_turns(state)
    return (state.get("threadRuntimeStatus") or {}).get("type") == "active" or bool(turns and turns[-1].get("status") == "inProgress")


def compacting_now(state):
    """A compaction under way (0.6.6), from /compact or from Codex running out of room: the running turn holds a
    contextCompaction item not completed yet, the desktop's own test (app.asar 26.1021)."""
    turns = ordered_turns(state)
    return bool(turns) and is_running(state) and any(
        isinstance(v, dict) and v.get("type") == "contextCompaction" and not v.get("completed")
        for v in turns[-1].get("items") or [])


def catalog():
    try:
        data = json.loads((chats.CODEX_HOME / "models_cache.json").read_text(encoding="utf-8"))
        models = [{"id": m["slug"], "name": m.get("display_name") or m["slug"],
                   "efforts": [v["effort"] for v in m.get("supported_reasoning_levels", [])],
                   "default_effort": m.get("default_reasoning_level"),
                   "service_tiers": m.get("service_tiers", []),
                   "images": "image" in m.get("input_modalities", [])}
                  for m in data.get("models", []) if m.get("visibility") == "list" and m.get("slug")]
        return {"models": models, "updated_at": data.get("fetched_at"), "source": "desktop_cache"}
    except (OSError, ValueError, KeyError):
        return {"models": [], "updated_at": None, "source": "unavailable"}


def _short(value: str) -> str:
    """A name inside a sentence the phone shows whole: at most 24 characters (11-17)."""
    return (value or "")[:24]


def version_newer(a: str, b: str) -> bool:
    """Whether Codex version [a] is newer than [b], comparing the numbers of its parts. Unknown on either side: False."""
    def parts(value):
        out = []
        for piece in str(value or "").split("."):
            if not piece.isdigit():
                return None
            out.append(int(piece))
        return out
    left, right = parts(a), parts(b)
    if not left or not right:
        return False
    width = max(len(left), len(right))
    return left + [0] * (width - len(left)) > right + [0] * (width - len(right))


def _codex_version_in_path(path: str) -> str:
    """The version in a Codex package folder:
    ...\\WindowsApps\\OpenAI.Codex_26.1106.6628.0_x64__2p2nqsd0c76g0\\app\\ChatGPT.exe -> 26.1106.6628.0 (11-17)."""
    match = re.search(r"OpenAI\.Codex_([^_\\/]+)", path or "")
    return match.group(1) if match else ""


def _image_path(pid: int) -> str:
    """The whole path of a process (winctl._process_name keeps only its name)."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def codex_version(pipe) -> str:
    """The version of the Codex at the other end of this pipe (11-17), "" when it cannot be read.
    Asked once per pipe connection: it cannot change while that connection lives."""
    cached = getattr(pipe, "_codex_app_version", None)
    if cached is not None:
        return cached
    version = ""
    try:
        pid = win32pipe.GetNamedPipeServerProcessId(pipe.handle)
        if pid:
            version = _codex_version_in_path(_image_path(pid))
    except Exception:
        version = ""
    try:
        pipe._codex_app_version = version
    except Exception:
        pass
    return version


def thread_provider(tid: str) -> str:
    """The model provider this Codex conversation was made with (state_*.sqlite threads.model_provider, 11-17);
    "" when that cannot be read or the conversation is not there."""
    try:
        db = chats.codex_db()
        if db is None:
            return ""
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3)
        try:
            row = con.execute("select model_provider from threads where id=?", (tid,)).fetchone()
        finally:
            con.close()
        return str(row[0] or "") if row else ""
    except (OSError, sqlite3.Error, ValueError):
        return ""


def current_provider() -> str:
    """The provider Codex uses now: the profile's model_provider, else the top-level one, else "openai" (11-17);
    "" when config.toml cannot be read or parsed, which means unknown and no conclusion is drawn from it."""
    try:
        data = tomllib.loads((chats.CODEX_HOME / "config.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return ""
    try:
        profile = data.get("profile")
        profiles = data.get("profiles")
        if isinstance(profile, str) and profile and isinstance(profiles, dict):
            chosen = profiles.get(profile)
            if isinstance(chosen, dict) and chosen.get("model_provider"):
                return str(chosen["model_provider"])
        if data.get("model_provider"):
            return str(data["model_provider"])
    except (AttributeError, TypeError):
        return ""
    return "openai"


class CodexNotTaken(chats.ChatError):
    """电脑上打开 asked Codex to show the conversation, but no Codex window took it (11-17). The phone shows the
    message as the reason and reads the state again."""
    code = "codex_not_taken"


APPROVAL_COMMAND = "item/commandExecution/requestApproval"
APPROVAL_FILE = "item/fileChange/requestApproval"
# 11-16: these ask too, but not with a choice this round can answer; the phone only says to use the computer.
APPROVAL_OTHER = ("item/permissions/requestApproval", "mcpServer/elicitation/request",
                  "item/tool/requestOptionPicker")
APPROVAL_METHODS = {APPROVAL_COMMAND: "command", APPROVAL_FILE: "file",
                    **{method: "other" for method in APPROVAL_OTHER}}
KNOWN_REQUESTS = {"item/tool/requestUserInput", *APPROVAL_METHODS}


def _command_line(command):
    """One line for the card: Codex sends a command as the words it will run, sometimes as a list of them."""
    if isinstance(command, (list, tuple)):
        return " ".join(str(v) for v in command if isinstance(v, (str, int, float)))
    return str(command or "").strip()


def _file_change_paths(state, turn_id, item_id):
    """The paths a file approval would change, from this turn's fileChange item (11-16)."""
    for turn in ordered_turns(state):
        if turn.get("turnId") != turn_id:
            continue
        for item in turn.get("items") or []:
            if item.get("type") == "fileChange" and str(item.get("id")) == str(item_id):
                return [str(change["path"]) for change in item.get("changes") or []
                        if isinstance(change, dict) and change.get("path")]
    return []


def native_approvals(state):
    """Approval requests waiting in the desktop's state, as cards the phone can answer (11-16).

    Each card also carries the `questions` field item/tool/requestUserInput uses, so a phone that has not been
    updated yet draws it with its existing Codex question card and answers it through the same codex/answer path.
    """
    cards = []
    for req in state.get("requests") or []:
        method = req.get("method")
        kind = APPROVAL_METHODS.get(method)
        if kind is None:
            continue
        params = req.get("params") or {}
        if params.get("threadId") != state.get("id") or not is_running(state):
            continue
        rid, turn_id = req.get("id"), params.get("turnId")
        reason = str(params.get("reason") or "").strip()
        command, files = "", []
        if kind == "command":
            command = _command_line(params.get("command"))
            prompt = "\n\n".join(v for v in (reason, command) if v)
        elif kind == "file":
            files = _file_change_paths(state, turn_id, params.get("itemId"))
            prompt = "\n\n".join([reason or "Codex 想修改这些文件", *files])
        else:
            prompt = "Codex 在电脑上等你处理，这种请求手机上还不能答。"
        card = {"id": "approval:" + str(turn_id) + ":" + str(rid), "request_id": rid, "kind": "approval",
                "turn_id": turn_id, "status": "pending", "approval_type": kind,
                "reason": reason, "command": command, "cwd": str(params.get("cwd") or ""), "files": files,
                "answerable": kind != "other", "question": prompt,
                "choices": ([{"id": "accept", "label": "允许一次"}, {"id": "decline", "label": "拒绝"}]
                            if kind != "other" else [])}
        if kind != "other":
            card["questions"] = [{"id": "decision",
                                  "header": "Codex 想运行命令" if kind == "command" else "Codex 想改文件",
                                  "question": prompt,
                                  "options": [{"label": "允许一次"}, {"label": "拒绝"}],
                                  "isOther": False}]
        cards.append(card)
    return cards


def native_questions(state):
    cards = []
    for req in state.get("requests", []):
        if req.get("method") != "item/tool/requestUserInput":
            continue
        params = req.get("params") or {}
        # Approval requests come through native_approvals() (11-16), not here.
        questions = params.get("questions") or []
        if not questions or len(questions) > 3:
            continue
        if params.get("threadId") != state.get("id") or not is_running(state):
            continue
        cards.append({"id": "native:" + str(params.get("turnId")) + ":" + str(req["id"]), "request_id": req["id"], "kind": "native",
                      "turn_id": params.get("turnId"), "questions": questions, "status": "pending"})
    pending_ids = {q["id"] for q in cards}
    history = []
    for turn in ordered_turns(state):
        for index,item in enumerate(turn.get("items", [])):
            if item.get("type") == "userInputResponse" and item.get("completed") and item.get("questions"):
                ident = "native:" + str(turn.get("turnId")) + ":" + str(item.get("requestId"))
                if ident not in pending_ids:
                    history.append({"id": ident, "request_id": item.get("requestId"), "kind": "native",
                                    "turn_id": turn.get("turnId"), "questions": item["questions"],
                                    "after_id": next((v.get("id") for v in reversed(turn.get("items", [])[:index]) if v.get("type") in ("agentMessage","userMessage") and v.get("id")), None),
                                    "before_id": next((v.get("id") for v in turn.get("items", [])[index+1:] if v.get("type") in ("agentMessage","userMessage") and v.get("id")), None),
                                    "answers": item.get("answers") or {}, "status": "answered"})
    return history[-4:] + cards


def latest_plan(state):
    turns = ordered_turns(state)
    found = None
    for turn in turns:
        for item in turn.get("items", []):
            if item.get("type") == "plan" and item.get("text"):
                found = {"id": item["id"], "turn_id": turn.get("turnId"), "text": item["text"],
                         "created_at": ((turn.get("turnStartedAtMs") or 0)+(turn.get("durationMs") or 1))/1000,
                         "ready": turn.get("status") == "completed" and turn is turns[-1] and not is_running(state)}
    return found


_async_index = {}
_async_index_lock = threading.RLock()


def _async_question_records(path):
    """Index typed questions across the whole rollout; subsequent polls read only appended bytes.

    Screenshots can push an unanswered question hundreds of MB behind the tail.
    Keep only small question/answer/turn records, never tool output or image data.
    An incomplete last JSONL line is retried on the next poll.
    """
    path = Path(path)
    key = str(path.resolve())
    with _async_index_lock:
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        entry = _async_index.get(key)
        if (entry is None or entry['identity'] != identity or stat.st_size < max(entry['size'],entry['offset'])
                or stat.st_size == entry['size'] and stat.st_mtime_ns != entry['mtime']):
            entry = {'identity': identity, 'size': 0, 'mtime': 0, 'offset': 0, 'records': []}
        with path.open('rb') as stream:
            stream.seek(entry['offset'])
            while True:
                raw = stream.readline()
                if not raw or not raw.endswith(b'\n'):
                    break
                entry['offset'] = stream.tell()
                if not any(marker in raw for marker in (b'turn_context', b'task_started',
                        b'request_user_input_async', b'<send_user_message_question_reply>')):
                    continue
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                payload = record.get('payload') or {}
                kind = record.get('type')
                if kind == 'turn_context' or kind == 'event_msg' and payload.get('type') == 'task_started':
                    record = {'type': kind, 'payload': {'type': payload.get('type'), 'turn_id': payload.get('turn_id')}}
                elif not (kind == 'response_item' and payload.get('type') == 'function_call'
                          and payload.get('name') in ('request_user_input_async', 'functions.request_user_input_async')
                          or b'<send_user_message_question_reply>' in raw and
                          (kind == 'event_msg' and payload.get('type') == 'user_message'
                           or kind == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user')):
                    continue
                record['_source_order']=entry['offset']
                entry['records'].append(record)
        entry.update(size=stat.st_size, mtime=stat.st_mtime_ns)
        _async_index.pop(key, None)
        _async_index[key] = entry
        while len(_async_index) > 16:
            _async_index.pop(next(iter(_async_index)))
        return list(entry['records'])


def async_questions(path, active_turn):
    """Read only typed async question calls; never turn arbitrary prose into a form."""
    turn_id, pending, answers, answer_locations = None, {}, {}, {}
    for rec in _async_question_records(path):
        p = rec.get("payload") or {}
        if rec.get("type") == "turn_context":
            turn_id = p.get("turn_id")
        if rec.get("type") == "event_msg" and p.get("type") == "task_started":
            turn_id = p.get("turn_id") or turn_id
        if rec.get("type") == "response_item" and p.get("type") == "function_call" and p.get("name") in ("request_user_input_async", "functions.request_user_input_async"):
            try:
                args = json.loads(p.get("arguments") or "{}")
            except ValueError:
                continue
            call_id = p.get("call_id")
            if call_id:
                qs = [{"id": str(i), "question": q.get("title", ""),
                       "options": [{"label": v, "description": ""} for v in q.get("options", [])], "isOther": True}
                      for i, q in enumerate(args.get("questions", []))]
                pending[call_id] = {"id": "async:" + call_id, "request_id": call_id, "kind": "async",
                                    "source_id":call_id,"source_order":rec.get('_source_order'),
                                    "turn_id": turn_id, "questions": qs, "status": "pending",
                                    "created_at": datetime.fromisoformat(rec["timestamp"]).timestamp() if rec.get("timestamp") else 0}
        text = ""
        if rec.get("type") == "event_msg" and p.get("type") == "user_message":
            text = p.get("message", "")
        elif rec.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
            text = chats._join_text(p.get("content"))
        for match in re.finditer(r"<send_user_message_question_reply>\s*([\s\S]*?)\s*</send_user_message_question_reply>", text):
            try:
                for a in json.loads(match[1]):
                    ident = json.loads(a["questionItemId"])
                    if ident[0] == "request_user_input_async":
                        key=(ident[1], str(ident[2]));value=[a.get("answer", "")]
                        if answers.get(key)!=value:
                            answer_locations[key]={'order':rec.get('_source_order'),'time':rec.get('timestamp')}
                        answers[key] = value
            except (ValueError, KeyError, IndexError, TypeError):
                continue
    out = []
    for call, q in pending.items():
        if not q["questions"]:
            continue
        if all((call, v["id"]) in answers for v in q["questions"]):
            q.update(status="answered", answers={v["id"]: answers[(call,v["id"])] for v in q["questions"]})
            q['answer_evidence']=[answer_locations[(call,v['id'])] for v in q['questions']]
            q['answer_order']=max((v.get('order') or 0 for v in q['answer_evidence']),default=0)
        elif q["turn_id"] != active_turn:
            continue
        out.append(q)
    return out


class Bridge:
    def __init__(self):
        self.pipe = None
        self.lock = threading.RLock()
        self.cache = {}
        self.delivery_evidence_cache = {}
        self.data_root = DATA / "attachments"
        self.references = None
        self.dismiss_manager = None
        self.log = None  # remote.Log's write, for failures that must not escape an interface (set by remote.py)
        self._dismiss_logged = {}  # tid -> when its last dismissal-read failure was written down
        self._unknown_requests = {}  # request id -> method, so a new Codex protocol writes one line, not every poll
        # 11-17: a 电脑上打开 no Codex window took says why through status() for ten minutes; and every conversation's
        # last being-sendable answer, so a change is written once and the log is not filled by the one-second poll.
        self._open_lock = threading.Lock()
        self._open_failed = {}  # tid -> (when, reason)
        self._sendable = {}  # tid -> (available, reason)
        # 11-17: confirm_open asks for the owner without self.lock (its wait must not block the one-second status
        # reads), so the pipe itself is made under its own small lock: two threads must not each open one.
        self._pipe_lock = threading.Lock()
        self._arrival_checked = {}  # request id -> when _never_arrived last looked through the whole record for it

    def _log(self, text):
        """One line in the service log, when remote.py has given this bridge one. Never raise from logging."""
        log = self.log
        if not callable(log):
            return
        try:
            log(text)
        except Exception:
            pass

    def _log_unknown_requests(self, state):
        """11-16: one line per request this bridge does not know, so a Codex protocol change shows up at once.
        The method and the keys of its params only, never the values (a command or a path may be anyone's)."""
        try:
            for req in state.get("requests") or []:
                method = req.get("method")
                if method in KNOWN_REQUESTS:
                    continue
                rid = str(req.get("id"))
                if self._unknown_requests.get(rid) == method:
                    continue
                self._unknown_requests[rid] = method
                params = req.get("params")
                keys = ",".join(sorted(params.keys())) if isinstance(params, dict) else ""
                self._log(f"Codex 发来不认识的请求：method={method} keys={keys}")
                while len(self._unknown_requests) > 64:
                    self._unknown_requests.pop(next(iter(self._unknown_requests)))
        except Exception:
            pass

    def _pipe(self):
        with self._pipe_lock:
            if self.pipe is None or self.pipe.closed:
                if self.pipe:
                    self.pipe.close()
                try:
                    self.pipe = DesktopPipe()
                except Exception as exc:
                    raise ControlError("无法连接 Codex 桌面，请确认客户端已打开") from exc
            return self.pipe

    def owner(self, tid, timeout=3):
        """The Codex window that has this conversation (thread-owner-discovery, 11-17), or None when no window has it.
        A window answers only after it resumed the thread and shows it (app.asar 26.1106); a version it does not know
        also answers nothing."""
        try:
            result = self._pipe().call("thread-owner-discovery", {"hostId": "local", "conversationId": tid}, timeout=timeout)
        except ControlError as exc:
            if exc.code == "no-client-found":
                return None
            raise
        return result.get("handledByClientId") or None

    def _app_version(self):
        """The running Codex's version, "" when it cannot be read."""
        try:
            return codex_version(self._pipe())
        except Exception:
            return ""

    def _remember_open_failure(self, tid, reason):
        now = time.monotonic()
        with self._open_lock:
            self._open_failed = {k: v for k, v in self._open_failed.items() if now - v[0] <= 600}
            self._open_failed[tid] = (now, reason)
            while len(self._open_failed) > 64:
                self._open_failed.pop(next(iter(self._open_failed)))

    def _forget_open_failure(self, tid):
        with self._open_lock:
            self._open_failed.pop(tid, None)

    def _open_failure(self, tid):
        """Why the last 电脑上打开 did not get this conversation taken, while that is less than ten minutes old."""
        now = time.monotonic()
        with self._open_lock:
            record = self._open_failed.get(tid)
            if not record:
                return None
            if now - record[0] > 600:
                self._open_failed.pop(tid, None)
                return None
            return record[1]

    def confirm_open(self, tid, seconds=10.0, step=0.5):
        """电脑上打开 for Codex (11-17): wait for a Codex window to take the conversation, then for its state to be
        readable, and tell the phone it can send. Otherwise say why, remember that for status() and write one line.
        The wait does not hold self.lock: the one-second status reads need it."""
        started = time.monotonic()
        owner, last_error, connected = None, None, False
        while True:
            try:
                owner = self.owner(tid)
                connected = True
            except ControlError as exc:
                owner, last_error = None, exc
            if owner or time.monotonic() - started >= seconds:
                break
            time.sleep(step)
        elapsed = time.monotonic() - started
        state = self.status(tid, fresh=True) if owner else None
        if state and state.get("available"):
            self._forget_open_failure(tid)
            title = chats.find("codex", tid)["title"]
            return {"ok": True, "text": f"电脑上已打开「{title}」，可以发了"}
        version = self._app_version()
        provider, current = thread_provider(tid), current_provider()
        if owner:
            if version_newer(version, TESTED_APP_VERSION):
                reason = f"Codex 已接手，但遥应读不到它的状态：电脑上的 Codex 是 {_short(version)}，遥应要更新"
                kind = "版本较新"
            else:
                reason = "Codex 已接手，但遥应还读不到它的状态，请稍后再点「电脑上打开」"
                kind = "读不到状态"
        elif not connected:
            reason = "连不上电脑上的 Codex，请确认 Codex 开着，再点「电脑上打开」"
            kind = "连不上"
        elif provider and current and provider != current:
            reason = f"Codex 没接手：这个对话用 {_short(provider)}，电脑上的 Codex 现在用 {_short(current)}，请在电脑上切回 {_short(provider)}"
            kind = "提供商不同"
        elif version_newer(version, TESTED_APP_VERSION):
            reason = f"Codex 没接手。电脑上的 Codex 是 {_short(version)}，比遥应测过的新，可能要更新遥应"
            kind = "版本较新"
        else:
            reason = "Codex 没接手这个对话。请看电脑上这个对话有没有提示，或重启 Codex 再试"
            kind = "原因不明"
        self._remember_open_failure(tid, reason)
        line = (f"Codex：电脑上打开 {tid[:8]} 后 {elapsed:.1f} 秒没接手（{kind}）；"
                f"Codex {version or '未知'}，遥应测过 {TESTED_APP_VERSION}；"
                f"这个对话的提供商 {_short(provider) or '未知'}，当前 {_short(current) or '未知'}")
        if owner and state:
            # 11-17: the state's own reason, so the log says more than "读不到状态".
            line += f"；状态：{str(state.get('reason') or '')[:80]}"
        if last_error is not None and getattr(last_error, "code", ""):
            line += f"；最后见到的错误 {last_error.code}"
        self._log(line)
        raise CodexNotTaken(reason)

    def _note_sendable(self, tid, result):
        """One line when a conversation stops being sendable from the phone, one when it can again (11-17).
        A conversation seen for the first time says nothing while it can send. Logging never changes the result."""
        try:
            available = bool(result.get("available"))
            reason = str(result.get("reason", ""))
            lines = []
            with self._open_lock:
                previous = self._sendable.get(tid)
                self._sendable[tid] = (available, reason)
                while len(self._sendable) > 64:
                    self._sendable.pop(next(iter(self._sendable)))
                if not available and (previous is None or previous[0] or previous[1] != reason):
                    lines.append(f"Codex 对话 {tid[:8]}：手机发不了（{reason}）")
                elif available and previous is not None and not previous[0]:
                    lines.append(f"Codex 对话 {tid[:8]}：手机又能发了")
            for line in lines:
                self._log(line)
        except Exception:
            pass

    def snapshot(self, tid, fresh=False, timeout=15):
        item = chats.find("codex", tid)
        with self.lock:
            if not fresh and self.pipe and not self.pipe.closed and tid in self.pipe.watches:
                with self.pipe.condition:
                    live=self.pipe.snapshots.get(tid)
                    if live:return item,live[1],copy.deepcopy(live[2])
            cached = self.cache.get(tid)
            if not fresh and cached and time.monotonic()-cached[0] < 2 and self.pipe and not self.pipe.closed:
                return item, cached[1], copy.deepcopy(cached[2])
            owner, state = self._pipe().snapshot(tid, timeout=timeout)
            if state.get("id") != tid or state.get("hostId") != "local":
                raise ControlError("会话身份不一致，操作已停止")
            self.cache[tid] = (time.monotonic(), owner, state)
            if len(self.cache) > 8:
                self.cache.pop(next(iter(self.cache)))
            return item, owner, copy.deepcopy(state)

    def watch(self,tid):
        chats.find('codex',tid)
        with self.lock:
            pipe=self._pipe();pipe.watch(tid);return pipe

    def _local_queue(self, tid):
        """Read the desktop's persisted queue; never write its storage directly."""
        try:
            data = json.loads((chats.CODEX_HOME / ".codex-global-state.json").read_text(encoding="utf-8"))
            rows = data.get("queued-follow-ups", {}).get(tid, [])
            if not isinstance(rows, list) or any(not isinstance(v, dict) or not v.get("id") for v in rows):
                raise ValueError("invalid queue")
            return rows
        except (OSError, ValueError, AttributeError):
            raise ControlError("无法核对桌面队列，内容已保留") from None

    def _steer(self, tid, rid, text, owner, turn_id, client_id=None, attached=None, skills=None, restore_message=None):
        client_id = client_id or rid
        # Recheck immediately before dispatch; never carry a correction across turns.
        _, current_owner, state = self.snapshot(tid, True)
        turns = ordered_turns(state)
        if current_owner != owner or not is_running(state) or not turns or turns[-1].get("turnId") != turn_id:
            result = {"ok": False, "delivery_state": "rejected", "request_id": rid,
                      "text": "当前轮次已变化，未提交；请恢复草稿后重新发送"}
            self._finish(rid, result)
            return result
        attached, skills = attached or [], skills or []
        inputs = ([{"type": "text", "text": text, "text_elements": []}] if text else [])
        inputs += [{"type": "localImage", "path": v["path"]} for v in attached]
        inputs += skills
        restore = copy.deepcopy(restore_message) if restore_message else {
            "id": client_id, "text": text, "context": {"prompt": text, "addedFiles": [], "fileAttachments": [],
            "imageAttachments": [{"src": v["path"], "localPath": v["path"], "filename": v["label"]} for v in attached]}}
        self._pipe().call("thread-follower-steer-turn", {
            "conversationId": tid, "input": inputs, "restoreMessage": restore,
            "attachments": attached, "clientUserMessageId": client_id}, owner, 30)
        result = {"ok": True, "accepted": True, "delivery_state": "accepted", "request_id": rid,
                  "client_id": client_id, "intent": "steer", "turn_id": turn_id,
                  "evidence": {"source": "desktop_steer_ack"}, "text": "已交给 Codex"}
        self._finish(rid, result)
        self.cache.pop(tid, None)
        return result

    def _enqueue(self, tid, rid, text, settings, attached, skills, owner, state):
        try:
            old = self._local_queue(tid)
        except ControlError as exc:
            result = {"ok": False, "request_id": rid, "delivery_state": "rejected", "text": str(exc)}
            self._finish(rid, result)
            return result
        if skills:
            text += "\n\n请使用以下选定技能完成本条请求：\n" + "\n".join(f"[{v['name']}](<{v['path']}>)" for v in skills)
        context = {"prompt": text, "addedFiles": [], "fileAttachments": [],
                   "imageAttachments": [{"src": v["path"], "localPath": v["path"], "filename": v["label"]} for v in attached],
                   "chatGptConversationContexts": [], "appshotContexts": [], "pastedTextAttachments": [],
                   "commentAttachments": [], "mcpAppModelContextAttachments": [], "selectedTextAttachments": [],
                   "threadReferences": [], "responseTextAnnotations": [], "pullRequestChecks": [],
                   "workspaceRoots": (state.get("currentPermissions") or {}).get("runtimeWorkspaceRoots") or [state.get("cwd")],
                   "turnTrigger": "composer"}
        # The native queue reconstructs input from serialized context, including skill references.
        if skills:
            context["skills"] = skills
        message = {"id": rid, "text": text, "context": context, "cwd": state.get("cwd"),
                   "createdAt": int(time.time()*1000), "submissionOptions": {
                       "collaborationMode": {"mode": settings["mode"], "settings": {"model": settings["model"], "reasoning_effort": settings["effort"], "developer_instructions": None}},
                       "serviceTier": settings.get("service_tier")},
                   "submission": {"hostId": "local", "status": "queued", "queueModeOverride": "queue"}}
        if self._local_queue(tid) != old:
            result = {"ok": False, "request_id": rid, "delivery_state": "rejected", "text": "桌面队列正在变化，未提交；请核对后重试"}
            self._finish(rid, result)
            return result
        self._pipe().call("thread-follower-set-queued-follow-ups-state", {
            "conversationId": tid, "state": {tid: old + [message]}, "discardedMessageIds": []}, owner, 20)
        result = {"ok": True, "accepted": True, "delivery_state": "queued", "request_id": rid,
                  "queue_message_id": rid, "intent": "queue", "text": "已排队",
                  "evidence": {"source": "desktop_queue_ack"}}
        self._finish(rid, result)
        return result

    def queue_action(self, body):
        tid, rid, mid = str(body.get("id", "")), str(body.get("request_id", "")), str(body.get("message_id", ""))
        action = body.get("action")
        if action not in ("promote", "cancel"):
            raise ControlError("无效队列操作", 400)
        with self.lock:
            if self.receipt(tid, rid)["state"] != "unknown":
                return self._begin(rid, tid, body)
            _, owner, state = self.snapshot(tid, True)
            message = next((v for v in self._local_queue(tid) if v["id"] == mid), None)
            if not message or message.get("submission", {}).get("status") not in (None, "queued"):
                raise ControlError("消息已离开队列或正在发送，请刷新核对")
            turn = ordered_turns(state)[-1].get("turnId") if is_running(state) else None
            if action == "promote":
                if not turn or body.get("expected_turn") != turn:
                    raise ControlError("运行轮次已变化，消息仍保留在队列")
                context = message.get("context") or {}
                attached = []
                for image in context.get("imageAttachments") or []:
                    path = image.get("localPath") or image.get("src")
                    if not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file():
                        raise ControlError("队列图片的本地文件不可用，消息仍保留在队列")
                    attached.append({"label": image.get("filename") or Path(path).name, "path": path, "fsPath": path, "isImageAttachment": True})
                skills = context.get("skills") or []
                if any(not isinstance(v, dict) or v.get("type") != "skill" or not v.get("name") or not v.get("path") for v in skills):
                    raise ControlError("队列引用格式不完整，消息仍保留在队列")
                if any(context.get(k) for k in ("addedFiles", "fileAttachments", "chatGptConversationContexts", "appshotContexts", "pastedTextAttachments", "commentAttachments", "mcpAppModelContextAttachments", "selectedTextAttachments", "threadReferences", "responseTextAnnotations", "pullRequestChecks")):
                    raise ControlError("这条桌面队列包含尚未支持的上下文，请在电脑上补充；消息仍保留在队列")
                with self._db() as con:
                    source = con.execute("SELECT data FROM deliveries WHERE thread=? AND id=?", (tid, mid)).fetchone()
                if source:
                    original = json.loads(source[0])
                    if original.get("settings") and normalize_settings(original["settings"]) != selected_settings(state):
                        raise ControlError("此消息修改了模型设置，请保留排队")
            self._begin(rid, tid, body)
            try:
                removed = self._pipe().call("thread-follower-remove-queued-message", {"conversationId": tid, "messageId": mid}, owner, 20)["result"].get("removed")
            except ControlError as exc:
                self._untaken(rid, exc)
                raise
            if not removed or removed.get("canRestore") is False:
                raise ControlError("未确认安全移出队列，已停止操作，请核对；不会重复发送")
            with self._db() as con:
                con.execute("UPDATE deliveries SET result=? WHERE id=?", (json.dumps({"phase": "removed", "client_id": mid, "message": removed.get("message", message)}, ensure_ascii=False), rid))
            if (removed.get("message", {}).get("submission") or {}).get("status") in ("sending", "pending", "outcome-unknown"):
                raise ControlError("桌面已开始处理这条消息，已停止提升；请核对原请求")
            cancelled = {"ok": True, "delivery_state": "cancelled", "request_id": mid, "text": "已取消排队"}
            self._finish(mid, cancelled)
            if action == "cancel":
                result = {**cancelled, "request_id": rid, "queue_message_id": mid}
                self._finish(rid, result)
                return result
            result = self._steer(tid, rid, message["text"], owner, turn, client_id=mid, attached=attached, skills=skills, restore_message=message)
            if result.get("accepted"):
                self._finish(mid, {**result, "request_id": mid})
            return result

    def status(self, tid, fresh=False):
        try:
            item, owner, state = self.snapshot(tid, fresh)
            turns = ordered_turns(state)
            self._log_unknown_requests(state)
            qs = native_questions(state) + native_approvals(state)
            qs += async_questions(Path(item["path"]), turns[-1].get("turnId") if is_running(state) and turns else None)
            active_turn = turns[-1].get("turnId") if is_running(state) and turns else None
            for q in qs:
                q["answer_revision"] = hashlib.sha256(json.dumps(q.get("answers", {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
                q["editable"] = q["kind"] == "async" and q["turn_id"] == active_turn
                if self.dismiss_manager:
                    # 11-12: this is only the extra note "did the PC close the card itself"; a ledger that cannot be
                    # read must not make the whole status unreadable (the phone showed 连接中断 / 502 for it).
                    try:
                        q["desktop_dismiss"] = self.dismiss_manager.latest(tid, q["id"])
                    except Exception:
                        q["desktop_dismiss"] = None
                        now = time.monotonic()
                        if now - self._dismiss_logged.get(tid, 0) >= 60:
                            self._dismiss_logged[tid] = now
                            self._log(f"读取 Codex 提问卡的自动关闭记录失败（{tid}）：\n" + traceback.format_exc())
            try:
                queued = [{"id": v["id"], "text": v.get("text", ""), "status": (v.get("submission") or {}).get("status", "queued")}
                          for v in self._local_queue(tid)]
                queue_available = True
            except ControlError:
                queued, queue_available = [], False
            self.reconcile_pending(tid)
            latest = turns[-1] if turns else {}
            started = int((latest.get("turnStartedAtMs") or 0) / 1000)
            ended = int(started + (latest.get("durationMs") or 0) / 1000) if started and latest.get("status") != "inProgress" else 0
            try:
                path = chats.conv_path(item)
                step = chats.tail_step("codex", path, started) if path and is_running(state) else ""
            except (OSError, chats.ChatError):step = ""
            compacting = compacting_now(state)  # 0.6.6: the phone says 正在压缩上下文 with the turn's timer
            result = {"available": True, "settings": selected_settings(state), "running": is_running(state),
                    "active_turn_id": turns[-1].get("turnId") if is_running(state) and turns else None,
                    "turn_started": started, "turn_ended": ended, "step": "compact" if compacting else step,
                    "compacting": compacting, "compact_started": started if compacting else 0,
                    "recent_turns": [{"id":t.get("turnId"),"status":t.get("status")} for t in turns[-4:]],
                    "questions": qs, "plan": latest_plan(state), "catalog": catalog(),
                    "queued": queued, "queue_available": queue_available,
                    "images": self.message_images(tid), "observed_at": int(time.time()*1000)}
        except (ControlError, chats.ChatError, OSError) as exc:
            reason = str(exc)
            # 11-17: a 电脑上打开 that Codex did not take says why for the next ten minutes, in the phone's own words.
            if isinstance(exc, ControlError) and exc.code == "no-client-found":
                reason = self._open_failure(tid) or reason
            result = {"available": False, "reason": reason, "questions": [], "plan": None,
                      "catalog": catalog(), "images": self.message_images(tid)}
        else:
            self._forget_open_failure(tid)
        self._note_sendable(tid, result)
        # 11-27: the phone counts a running turn (and a compaction) down from these two against its own now; on this
        # computer every comparison above used the record's own values.
        for key in ("turn_started", "turn_ended", "compact_started"):
            if key in result:
                result[key] = pc_clock.to_true_seconds(result[key])
        return result

    def delivery_locations(self,tid,request_ids):
        """Identity evidence only. Does not refresh receipts or change the ledger."""
        path=self.data_root/'delivery.sqlite'
        if not path.is_file():return {}
        out={}
        try:
            con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        except sqlite3.Error:
            return {}
        try:
            for rid in request_ids:
                row=con.execute('SELECT state,result FROM deliveries WHERE thread=? AND id=?',(tid,rid)).fetchone()
                if row:
                    result=json.loads(row[1] or '{}')
                    out[rid]={'state':row[0],'client_id':result.get('client_id'),'message_id':(result.get('evidence') or {}).get('message_id')}
        except sqlite3.Error:
            return {}  # 11-12: a wiped file with no deliveries table means "no records", not an error
        finally:con.close()
        return out

    @contextmanager
    def _db(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.data_root / "delivery.sqlite", timeout=15)
        try:
            with con:
                con.execute("CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, thread TEXT, fingerprint TEXT, state TEXT, result TEXT, data TEXT, created REAL)")
                # 11-12: the wiped file came back with only deliveries; the dismissed-question table must come back
                # with every open, or status()/the live stream fail on any conversation that ever showed a question card.
                codex_question_dismiss.ensure_schema(con)
                yield con
        finally:
            con.close()

    def _begin(self, rid, tid, body):
        if not recordable(rid):
            raise ControlError("无效的发送请求编号", 400)
        fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with self._db() as con:
            old = con.execute("SELECT thread,fingerprint,state,result FROM deliveries WHERE id=?", (rid,)).fetchone()
            if old:
                if old[0] != tid or old[1] != fingerprint:
                    raise ControlError("请求编号已用于其他内容")
                if old[2] in ("accepted", "queued", "cancelled", "rejected"):
                    return json.loads(old[3])
                raise ControlError("这次请求已提交过，结果尚未确认；请检查对话，不会重复发送")
            if body.get("question_id"):
                prior = con.execute("SELECT state FROM deliveries WHERE thread=? AND json_extract(data,'$.question_id')=? ORDER BY created DESC LIMIT 1",
                                    (tid, body["question_id"])).fetchone()
                if prior and prior[0] == "dispatching":
                    raise ControlError("上次答复结果仍待核对，不能再次提交")
            # Request fingerprint provides idempotency; question text/secret answers
            # need not be duplicated into the delivery ledger.
            stored = {k: v for k, v in body.items() if k != "answers"} if body.get("question_id") else body
            con.execute("INSERT INTO deliveries VALUES (?,?,?,?,?,?,?)", (rid, tid, fingerprint, "dispatching", "{}", json.dumps(stored,ensure_ascii=False), time.time()))
        return None

    def _finish(self, rid, result):
        with self._db() as con:
            row = con.execute("SELECT created FROM deliveries WHERE id=?", (rid,)).fetchone()
            con.execute("UPDATE deliveries SET state=?,result=? WHERE id=?", (result.get("delivery_state", "accepted"), json.dumps(result,ensure_ascii=False), rid))
        if self.dismiss_manager and result.get("delivery_state", "accepted") == "accepted":
            try:
                self.dismiss_manager.accepted(rid)
                dismiss = self.dismiss_manager.result(rid)
                if dismiss: result["desktop_dismiss"] = dismiss
            except Exception:
                result["desktop_dismiss"] = {"status": "retained", "reason": "dismiss_unavailable"}
        # No message bodies or credentials in transport diagnostics.
        if self.data_root == DATA / "attachments":
            try:
                with (DATA / "logs" / time.strftime("%Y%m%d.log")).open("a", encoding="utf-8") as log:
                    elapsed = round((time.time()-row[0])*1000) if row else 0
                    log.write(f"{time.strftime('%H:%M:%S')} codex request={rid} state={result.get('delivery_state','accepted')} intent={result.get('intent','')} turn={result.get('turn_id','')} elapsed_ms={elapsed}\n")
            except OSError:
                pass  # A log failure must not turn an acknowledged send into an error.

    def _untaken(self, rid, exc):
        """11-17: Codex turned the request away before doing anything, or no window had the conversation: the send is
        未接收 with the reason, so the phone offers 恢复草稿 / 移除 instead of 送达状态待确认 for good."""
        if untaken(exc):
            self._finish(rid, {"ok": False, "delivery_state": "rejected", "request_id": rid, "text": str(exc)})

    def _never_arrived(self, tid, rid, body, created):
        """11-17: a message still 'dispatching' ten minutes after it began and found nowhere: not in Codex's queue (its
        settings file, or the queue database 26.1111 also has), and its request id nowhere in the conversation's whole
        record. Two messages the phone queued while Codex worked (Codex refused the old request number) stayed
        送达状态待确认, and 核对 could never say more. Only a plain send is judged: answers, stops, queue moves and
        /compact leave no user message of their own to look for."""
        if time.time() - (created or 0) < STUCK_AFTER:
            return False
        if body.get("question_id") or body.get("action") or body.get("message_id") or "text" not in body:
            return False
        if composer_commands.parse(str(body.get("text", ""))):
            return False
        now = time.monotonic()
        last = self._arrival_checked.get(rid)
        if last is not None and now - last < 300:
            return False  # the whole record was read for it a moment ago; once in five minutes is enough
        self._arrival_checked[rid] = now
        try:
            if any(v["id"] == rid for v in self._local_queue(tid)):
                return False
        except ControlError:
            return False
        if self._in_server_queue(rid) is not False:
            return False
        try:
            return not file_has(Path(chats.find("codex", tid)["path"]), rid.encode())
        except (OSError, chats.ChatError, KeyError, TypeError, ValueError):
            return False

    def _in_server_queue(self, rid):
        """Codex 26.1111 also keeps a queue in its own database (queue_1.sqlite, table queued_items). True when an item
        there carries this id, False when none does or there is no such database, None when it cannot be read."""
        path = chats.CODEX_HOME / "queue_1.sqlite"
        if not path.is_file():
            return False
        try:
            con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
            try:
                return con.execute("SELECT 1 FROM queued_items WHERE id=? OR instr(payload_json, ?) > 0 LIMIT 1",
                                   (rid, rid)).fetchone() is not None
            finally:
                con.close()
        except sqlite3.Error:
            return None

    def receipt(self, tid, rid):
        path = self.data_root / "delivery.sqlite"
        if not path.exists():
            return {"state": "unknown"}
        # 11-26 P1: read before _db() makes the table, so a file with no deliveries table stays plain "unknown" (no
        # missing) instead of reading as an empty record that holds nothing.
        missing = record_missing(path, rid)
        with self._db() as con:
            row = con.execute("SELECT state,result,data,created FROM deliveries WHERE id=? AND thread=?", (rid,tid)).fetchone()
        if not row:
            # 8.1: the file reads and holds no row for this request id in ANY conversation: the message never arrived.
            return {"state": "unknown", "missing": True} if missing else {"state": "unknown"}
        body = json.loads(row[2])
        result = json.loads(row[1])
        status = row[0]
        question_id = str(body.get("question_id", ""))
        if status == "dispatching" and question_id.startswith("approval:"):
            # 11-16: the desktop's owner answers ok even for a request it no longer has, so absence means
            # "sent, probably handled" rather than proof; the wording says so.
            request_id = question_id.rsplit(":", 1)[-1]
            try:
                _, _, snapshot = self.snapshot(tid)
                gone = not any(str(v.get("id")) == request_id for v in snapshot.get("requests") or [])
            except (ControlError, chats.ChatError, OSError):
                gone = False
            if gone:
                result = {"ok": True, "accepted": True, "request_id": rid, "delivery_state": "accepted",
                          "text": "Codex 已收到；如果你已在电脑上处理过，以电脑为准",
                          "evidence": {"source": "desktop_approval_request_gone"}}
                self._finish(rid, result)
                status = "accepted"
        if status == "dispatching" and question_id.startswith("native:"):
            try:
                _, _, snapshot = self.snapshot(tid)
                done = next((q for q in native_questions(snapshot) if q["id"] == body["question_id"] and q["status"] == "answered"), None)
                if done:
                    result = {"ok": True, "accepted": True, "request_id": rid, "delivery_state": "accepted",
                              "text": "答案已交给 Codex", "evidence": {"source": "desktop_user_input_response"}}
                    self._finish(rid, result)
                    status = "accepted"
            except (ControlError, chats.ChatError, OSError):
                pass
        if status in ("dispatching", "queued") and body.get("intent") == "queue":
            try:
                found = next((v for v in self._local_queue(tid) if v["id"] == rid), None)
            except ControlError:
                found = None
            if found:
                result = {"ok": True, "accepted": True, "request_id": rid, "delivery_state": "queued",
                          "queue_message_id": rid, "text": "已排队", "evidence": {"source": "desktop_queue_record"}}
                if status != "queued":
                    self._finish(rid, result)
                status = "queued"
            elif status == "queued":
                # Absence alone cannot distinguish desktop cancellation from dispatch.
                status = "dispatching"
                result = {**result, "text": "消息已离开可见队列，结果待核对"}
        if status in ("dispatching", "queued") and body.get("action") != "stop":
            evidence = self.delivery_evidence(tid).get(result.get("client_id", rid))
            if evidence:
                result = {"ok": True, "accepted": True, "delivery_state": "accepted", "request_id": rid, "text": "已交给 Codex",
                          "evidence": evidence}
                self._finish(rid,result)
                status = "accepted"
        # Only a send that never got further than 'dispatching': one that was queued and has just left the queue may
        # be on its way into the record this very second.
        if row[0] == status == "dispatching" and self._never_arrived(tid, rid, body, row[3]):
            result = {"ok": False, "delivery_state": "rejected", "request_id": rid,
                      "text": "这条没有送到 Codex：它的排队里没有，对话记录里也没有；可以恢复草稿后再发"}
            self._finish(rid, result)
            status = "rejected"
        if status == "accepted" and not body.get("question_id"):
            result["submission"] = {k:body.get(k) for k in ("text","attachments","settings","plan_id","references")}
        if self.dismiss_manager:
            try:
                dismiss = self.dismiss_manager.result(rid)
                if dismiss: result["desktop_dismiss"] = dismiss
            except Exception: pass
        return {"state": status, "request_id": rid, "result": result}

    def delivery_evidence(self, tid):
        """Match the receiver's client_id exactly. Text similarity is not a receipt."""
        try:
            path = Path(chats.find("codex",tid)["path"])
            st = path.stat()
            key = (str(path),st.st_size,st.st_mtime_ns)
            old = self.delivery_evidence_cache.get(tid)
            if old and old[0] == key:
                return old[1]
            lines,_ = chats.read_tail(path,8 << 20)
            evidence = {}
            for raw in lines:
                if (b'"UserMessage"' not in raw and b'"user_message"' not in raw) or b'"client_id"' not in raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                p = rec.get("payload") or {}
                message = p.get("item") or {}
                if rec.get('type')=='event_msg' and p.get('type')=='user_message' and p.get('client_id'):
                    evidence[p['client_id']]={'source':'conversation_record','time':rec.get('timestamp')}
                if rec.get("type") == "event_msg" and p.get("type") == "item_completed" and message.get("type") == "UserMessage" and message.get("client_id"):
                    evidence[message["client_id"]] = {"source":"conversation_record","message_id":message.get("id"),
                                                     "turn_id":p.get("turn_id"),"time":rec.get("timestamp")}
            self.delivery_evidence_cache[tid] = (key,evidence)
            if len(self.delivery_evidence_cache) > 8:
                self.delivery_evidence_cache.pop(next(iter(self.delivery_evidence_cache)))
            return evidence
        except (OSError,chats.ChatError):
            return {}

    def reconcile_pending(self,tid):
        if not (self.data_root/"delivery.sqlite").exists():
            return
        with self._db() as con:
            rows = con.execute("SELECT id FROM deliveries WHERE thread=? AND state IN ('dispatching','queued') ORDER BY created DESC LIMIT 8",(tid,)).fetchall()
        for (rid,) in rows:
            self.receipt(tid,rid)

    def validate_settings(self, wanted, state, has_images):
        current = selected_settings(state)
        desired = normalize_settings({**current, **(wanted or {})})
        if set(desired) != {"model", "effort", "mode", "service_tier"} or desired["mode"] not in ("default", "plan"):
            raise ControlError("无效的会话设置", 400)
        models = catalog()["models"]
        if not models:
            raise ControlError("暂时无法读取电脑的模型目录，尚未发送消息；请稍后重试")
        model = next((m for m in models if m["id"] == desired["model"]), None)
        if not model:
            raise ControlError(f"电脑当前模型目录中没有 {desired['model'] or '所选模型'}，尚未发送消息；目录可能已变化，请刷新模型列表后重试")
        if desired["effort"] not in model["efforts"]:
            raise ControlError(f"{desired['model']} 不支持推理强度 {desired['effort'] or '空'}，尚未发送消息；可选：{', '.join(model['efforts'])}")
        if has_images and not model["images"]:
            raise ControlError("所选模型不支持图片")
        if desired['service_tier'] is not None and desired['service_tier'] not in [v['id'] for v in model.get('service_tiers', [])]:
            raise ControlError("速度选项不在当前模型目录中，请重新选择")
        return desired

    def stop_turn(self,body):
        tid=str(body.get("id", ""));rid=str(body.get("operation_id", ""));expected=str(body.get("turn_id", ""))
        operation={"action":"stop","id":tid,"turn_id":expected}
        with self.lock:
            if self.receipt(tid,rid)["state"]!="unknown":
                return self._begin(rid,tid,operation)
            _,owner,state=self.snapshot(tid,True)
            turns=ordered_turns(state);current=turns[-1] if turns else None
            if not expected or current is None or current.get("turnId")!=expected:
                raise ControlError("当前轮次已变化，未执行停止；请刷新后确认")
            if current.get("status")!="inProgress":
                return {"ok":True,"ended":True,"turn_id":expected,"text":"该轮已结束"}
            self._begin(rid,tid,operation)
            result=self._pipe().call("thread-follower-interrupt-turn",{"conversationId":tid,"expectedTurnId":expected,"mode":"user-stop"},owner,20)["result"]
            response={"ok":True,"accepted":True,"turn_id":expected,"text":"已请求停止，等待轮次状态确认","desktop_result":result}
            self._finish(rid,response);self.cache.pop(tid,None)
            return response

    def compact(self, body):
        """/compact typed on the phone (0.6.6, user 10-31): the desktop compacts the conversation as its own /compact
        does; sent as a message, the words only reached the model. Taken once per request id, like a send."""
        tid, rid = str(body.get("id", "")), str(body.get("request_id", ""))
        with self.lock:
            if self.receipt(tid, rid)["state"] != "unknown":
                return self._begin(rid, tid, body)
            chats.require_send_desktop()
            _, owner, state = self.snapshot(tid, True)
            if is_running(state):
                raise ControlError("Codex 这一轮还没结束，等它停下再压缩；草稿已保留")
            self._begin(rid, tid, body)
            try:
                self._pipe().call("thread-follower-compact-thread", {"conversationId": tid}, owner, 30)
            except ControlError as exc:
                if "结果未确认" not in str(exc):  # the desktop said no: nothing started, the phone may send again
                    self._finish(rid, {"ok": False, "delivery_state": "rejected", "request_id": rid, "text": str(exc)})
                raise
            result = {"ok": True, "accepted": True, "delivery_state": "accepted", "request_id": rid, "intent": "command",
                      "command": "/compact", "text": "已开始压缩"}
            self._finish(rid, result)
            self.cache.pop(tid, None)
            return result

    def send(self, body, timing=None):
        phase=timing or (lambda *args:None)
        phase('send_lock','等待 Codex 发送通道')
        tid, rid = str(body.get("id", "")), str(body.get("request_id", ""))
        text = str(body.get("text", "")).strip()
        ids = body.get("attachments") or []
        command = composer_commands.parse(text)
        if command and command[0] == "/compact" and not ids and not body.get("references") and not body.get("plan_id"):
            if command[1]:
                raise ControlError("Codex 的 /compact 不带说明，删掉后面的字再发；草稿已保留", 400)
            return self.compact(body)
        if not isinstance(ids, list) or len(ids) > 5 or len(set(ids)) != len(ids):
            raise ControlError("每条消息最多 5 张不同图片", 400)
        files = any(isinstance(v, dict) and v.get("kind") in ("file", "folder") for v in body.get("references") or [])
        if (not text and not ids and not files) or len(text) > chats.MAX_TEXT:  # files alone are a message (10-20)
            raise ControlError("请填写消息或添加图片，文字不能超过 20000 字", 400)
        with self.lock:
            prior = self.receipt(tid,rid)
            if prior["state"] != "unknown":
                return self._begin(rid,tid,body)
            chats.require_send_desktop()
            phase('send_snapshot','核对 Codex 最新状态')
            item, owner, state = self.snapshot(tid, True)
            phase('send_validate','核对设置、引用与附件')
            intent = body.get("intent", "auto")
            if intent not in ("auto", "steer", "queue"):
                raise ControlError("无效的发送方式", 400)
            running = is_running(state)
            turn_id = ordered_turns(state)[-1].get("turnId") if running else None
            if body.get("expected_turn") and body["expected_turn"] != turn_id:
                raise ControlError("当前轮次已变化，内容已保留；请重新发送")
            if intent == "steer" and (not turn_id or not body.get("expected_turn")):
                raise ControlError("立即补充需要核对当前运行轮次")
            if running and intent != "queue":
                if body.get("settings") and normalize_settings(body["settings"]) != selected_settings(state):
                    raise ControlError("新模型设置需要排队；内容已保留")
            expected = body.get("expected_settings")
            if expected and normalize_settings(expected) != selected_settings(state):
                raise ControlError("电脑端设置已变化，请重新打开模型面板确认后再发送")
            desired = self.validate_settings(body.get("settings"), state, bool(ids))
            images = [self.attachment(ident, tid) for ident in ids]
            if sum(v["original_size"] for v in images) > 50 << 20:
                raise ControlError("图片合计不能超过 50 MB", 413)
            plan_id = body.get("plan_id")
            if plan_id:
                plan = latest_plan(state)
                if not plan or not plan["ready"] or plan["id"] != plan_id:
                    raise ControlError("计划已更新或不再可执行，请刷新后查看最新计划")
                desired["mode"] = "default"
                text = "请按下面这份已确认计划开始实施：\n\n" + plan["text"]
            skill_inputs=[]
            if body.get('references'):
                if self.references is None:raise ControlError('引用服务不可用，请重新打开页面',503)
                text,skill_inputs=self.references.compose('codex',tid,text,body['references'])
            cm = {"mode": desired["mode"], "settings": {"model": desired["model"], "reasoning_effort": desired["effort"], "developer_instructions": None}}
            inp = ([{"type": "text", "text": text, "text_elements": []}] if text else [])
            inp += [{"type": "localImage", "path": v["path"]} for v in images]
            inp += skill_inputs
            attached = [{"label": v["name"], "path": v["path"], "fsPath": v["path"], "isImageAttachment": True} for v in images]
            request = {"threadId": tid, "input": inp, "clientUserMessageId": rid,
                       "model": desired["model"], "effort": desired["effort"], "serviceTier": desired.get('service_tier'), "collaborationMode": cm}
            operation = {"request": request, "context": {"inheritThreadSettings": True, "attachments": attached}}
            chats.require_send_desktop()
            self._begin(rid,tid,body)
            for v in images:
                v["used"] = True
                self._write_meta(v)
            try:
                if running and intent != "queue":
                    return self._steer(tid, rid, text, owner, turn_id, attached=attached, skills=skill_inputs)
                if intent == "queue" and running:
                    return self._enqueue(tid, rid, text, desired, attached, skill_inputs, owner, state)
                try:
                    phase('send_ack','提交消息并等待 Codex 回执')
                    result = self._pipe().call("thread-follower-start-turn", {"conversationId": tid, "turnStart": operation}, owner, 45)["result"]
                except ControlError:
                    receipt = self.receipt(tid,rid)
                    if receipt["state"] == "accepted":
                        self.cache.pop(tid,None)
                        return receipt["result"]
                    raise
            except ControlError as exc:
                self._untaken(rid, exc)  # turned away before anything was done: 未接收, not unknown
                raise
            response = {"ok": True, "accepted": True, "delivery_state": "accepted", "intent": "start", "request_id": rid, "text": "已交给 Codex", "settings": desired, "desktop_result": result}
            phase('receipt','保存送达回执')
            self._finish(rid,response)
            self.cache.pop(tid,None)
            return response

    def answer(self, body):
        tid, rid = str(body.get("id", "")), str(body.get("request_id", ""))
        with self.lock:
            if self.receipt(tid,rid)["state"] != "unknown":
                return self._begin(rid,tid,body)
            item, owner, state = self.snapshot(tid,True)
            cards = native_questions(state) + native_approvals(state)
            turns = ordered_turns(state)
            if is_running(state) and turns:
                cards += async_questions(Path(item["path"]),turns[-1].get("turnId"))
            card = next((q for q in cards if q["id"] == body.get("question_id") and
                         (q["status"] == "pending" or q["kind"] == "async" and is_running(state) and q["turn_id"] == turns[-1].get("turnId"))),None)
            if not card:
                raise ControlError("这个问题已回答或已失效，请刷新")
            revision = hashlib.sha256(json.dumps(card.get("answers", {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            if body.get("answer_revision", revision) != revision:
                raise ControlError("答案已在其他设备更新，请刷新核对后再修改")
            answers = body.get("answers") or {}
            if card["kind"] == "approval":
                decision = self._approval_decision(card, answers)
                self._begin(rid,tid,body)
                return self._answer_approval(tid, rid, owner, card, decision)
            if set(answers) != {str(q["id"]) for q in card["questions"]}:
                raise ControlError("请回答所有问题",400)
            for q in card["questions"]:
                vals = answers[str(q["id"])]
                if not isinstance(vals,list) or not vals or any(not isinstance(v,str) or not v.strip() or len(v)>8000 for v in vals):
                    raise ControlError("答案不能为空或过长",400)
                if not q.get("isMultiple") and len(vals)!=1:
                    raise ControlError("这个问题只允许选择一项",400)
            self._begin(rid,tid,body)
            if card["kind"] == "native":
                reply = {"answers": {key: {"answers": vals} for key,vals in answers.items()}}
                self._pipe().call("thread-follower-submit-user-input", {"conversationId":tid,"requestId":card["request_id"],"response":reply},owner)
            else:
                if self.dismiss_manager:
                    try: self.dismiss_manager.arm(rid, tid, card, answers)
                    except Exception: pass  # Cosmetic cleanup cannot block the answer.
                entries = [{"questionItemId": json.dumps(["request_user_input_async",card["request_id"],int(q["id"])],separators=(",",":")),
                            "question":q["question"],"answer":answers[q["id"]][0]} for q in card["questions"]]
                text = "<send_user_message_question_reply>\n"+json.dumps(entries,ensure_ascii=False)+"\n</send_user_message_question_reply>"
                return self._steer(tid, rid, text, owner, card["turn_id"])
            response = {"ok":True,"accepted": True,"text":"答案已交给 Codex","request_id":rid}
            self._finish(rid,response)
            self.cache.pop(tid,None)
            return response

    def _approval_decision(self, card, answers):
        """The two choices the phone is given, as the decision the desktop's card sends (11-16)."""
        if set(answers) != {"decision"}:
            raise ControlError("请选择「允许一次」或「拒绝」", 400)
        values = answers.get("decision")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
            raise ControlError("请选择「允许一次」或「拒绝」", 400)
        value = values[0].strip()
        if value in ("允许一次", "accept"):
            return "accept"
        if value in ("拒绝", "decline"):
            return "decline"
        raise ControlError("只能选择「允许一次」或「拒绝」", 400)

    def _answer_approval(self, tid, rid, owner, card, decision):
        """Send the decision over the owner's follower pipe, then re-read to see the request is gone (11-16).
        The owner answers a request that is already gone with ok too, so the reply is worded neutrally."""
        method = ("thread-follower-command-approval-decision" if card["approval_type"] == "command"
                  else "thread-follower-file-approval-decision")
        try:
            self._pipe().call(method, {"conversationId": tid, "requestId": card["request_id"],
                                       "decision": decision}, owner)
        except ControlError as exc:
            if untaken(exc, REFUSED):
                result = {"ok": False, "delivery_state": "rejected", "request_id": rid,
                          "text": "这个版本的 Codex 还不能从手机回答批准，请在电脑上处理"}
                self._finish(rid, result)
                return result
            raise
        try:
            _, _, after = self.snapshot(tid, True)
            gone = not any(str(v.get("id")) == str(card["request_id"]) for v in after.get("requests") or [])
        except (ControlError, chats.ChatError, OSError):
            gone = False
        response = {"ok": True, "accepted": True, "delivery_state": "accepted", "request_id": rid,
                    "text": "Codex 已收到；如果你已在电脑上处理过，以电脑为准" if gone else "已发给 Codex；如果还在等，请在电脑上处理",
                    "evidence": {"source": "desktop_approval_decision"}}
        self._finish(rid, response)
        self.cache.pop(tid, None)
        return response

    def attachment(self, ident, tid=None):
        if not isinstance(ident,str) or not re.fullmatch(r"[a-f0-9]{32}",ident):
            raise ControlError("无效图片编号",404)
        try:
            data=json.loads((self.data_root/ident/"meta.json").read_text(encoding="utf-8"))
        except (OSError,ValueError):
            raise ControlError("图片已移除或不存在",404) from None
        if tid is not None and data["thread"]!=tid:
            raise ControlError("图片不属于这个对话",403)
        if not data.get("used") and time.time()-data["created"]>7*86400:
            raise ControlError("图片草稿已过期，请重新选择",410)
        folder=(self.data_root/ident).resolve()
        if folder.parent != self.data_root.resolve() or data.get("id") != ident or data.get("file") != "image.png":
            raise ControlError("图片记录无效",404)
        data["path"]=str(folder/"image.png")
        return data

    def _write_meta(self, meta):
        p=self.data_root/meta["id"]/"meta.json"
        temp=p.with_suffix(".tmp")
        temp.write_text(json.dumps(meta,ensure_ascii=False),encoding="utf-8")
        temp.replace(p)

    def upload(self,tid,name,raw,app='codex',*,new_draft=False):
        import io
        from PIL import Image,ImageOps,UnidentifiedImageError
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        from agents import registry
        if app not in registry.ids():raise ControlError('未知客户端',400)
        if new_draft:
            if not re.fullmatch(r'new:[a-f0-9]{32}',tid):raise ControlError('新对话草稿无效',400)
        else:chats.find(app,tid)
        self.cleanup_drafts()
        if not 0<len(raw)<=20<<20:
            raise ControlError("单张图片不能超过 20 MB",413)
        try:
            with Image.open(io.BytesIO(raw)) as source:
                source_format=source.format
                frames=getattr(source,"n_frames",1)
                if source_format not in ("PNG","JPEG","MPO","WEBP","HEIF","HEIC"):
                    raise ControlError(f"识别到 {source_format or '未知'} 格式，暂不支持；支持 JPEG、PNG、WebP 和 HEIC/HEIF 照片",400)
                if source.width*source.height>50_000_000:
                    raise ControlError(f"照片尺寸为 {source.width}×{source.height}，超过 5000 万像素上限；请降低拍照分辨率或缩小后重试",400)
                # MPO and HEIF can contain a primary still photo plus additional images.
                # Both decoders open their primary image by default; do not seek to a gain map.
                if frames>1 and source_format not in ("MPO","HEIF","HEIC"):
                    raise ControlError("这是动画或多帧图片，请改发静态照片",400)
                image=ImageOps.exif_transpose(source).convert("RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB")
                image.info.clear()
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError) as exc:
            raise ControlError("无法读取图片，请转为 JPEG 或 PNG 后重试",400) from exc
        ident=uuid.uuid4().hex
        folder=self.data_root/ident
        folder.mkdir(parents=True)
        try:
            image.save(folder/"image.png",format="PNG")
            thumb=image.copy();thumb.thumbnail((320,320));thumb.save(folder/"thumb.png")
            meta={"id":ident,"thread":tid,"app":app,"name":Path(name.replace('\\','/')).name[:120] or "图片",
                  "file":"image.png","original_size":len(raw),"width":image.width,"height":image.height,
                  "created":time.time(),"used":False,"source_format":source_format,"source_images":frames}
            self._write_meta(meta)
        except Exception:
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()
            raise
        return self.public_attachment(meta)

    def cleanup_drafts(self):
        """Only delete expired, unused image folders created by this module."""
        if not self.data_root.exists():
            return
        with self.lock:
            for folder in self.data_root.iterdir():
                if not folder.is_dir() or folder.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}",folder.name):
                    continue
                try:
                    meta=json.loads((folder/"meta.json").read_text(encoding="utf-8"))
                    if meta.get("used") or time.time()-meta["created"] <= 7*86400:
                        continue
                    if folder.resolve().parent != self.data_root.resolve():
                        continue
                    for name in ("image.png","thumb.png","meta.json"):
                        (folder/name).unlink(missing_ok=True)
                    folder.rmdir()
                except (OSError,ValueError,KeyError):
                    continue

    @staticmethod
    def public_attachment(meta):
        return {k:meta[k] for k in ("id","name","original_size","width","height")}|{"url":"/api/codex/image?id="+meta["id"],"thumbnail":"/api/codex/image?thumb=1&id="+meta["id"]}

    def remove_attachment(self,tid,ident):
        with self.lock:
            meta=self.attachment(ident,tid)
            if meta.get("used"):
                return {"ok":True,"retained":True}
            folder=self.data_root/ident
            for name in ("image.png","thumb.png","meta.json"):
                (folder/name).unlink(missing_ok=True)
            folder.rmdir()
        return {"ok":True}

    def message_images(self,tid):
        if not (self.data_root/"delivery.sqlite").exists():
            return []
        with self._db() as con:
            rows=con.execute("SELECT id,data,created,state FROM deliveries WHERE thread=? ORDER BY created DESC LIMIT 60",(tid,)).fetchall()
        out=[]
        for rid,raw,created,status in reversed(rows):
            body=json.loads(raw);images=[]
            for ident in body.get("attachments",[]):
                try:images.append(self.public_attachment(self.attachment(ident,tid)))
                except ControlError:continue
            if images:out.append({"request_id":rid,"images":images,"text":body.get("text", ""),"created":created,"status":status})
        return out

    def close(self):
        if self.pipe:self.pipe.close()
