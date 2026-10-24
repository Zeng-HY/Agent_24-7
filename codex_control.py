"""Local desktop follower bridge. Never starts or resumes an independent app-server.

Protocol verified against Codex Windows 26.1007.2314.0. A missing owner, unknown
snapshot version or disconnected pipe disables actions instead of falling back to
blind keystrokes. Only the narrow methods below are exposed to the phone.
"""
from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import queue
import re
import sqlite3
import struct
import threading
import time
import uuid
from pathlib import Path
from app_paths import DATA
from datetime import datetime
from contextlib import contextmanager

import pywintypes
import win32con
import win32event
import win32file

import chats

HERE = Path(__file__).resolve().parent
TESTED_APP_VERSION = "26.1007.2314.0"
VERSIONS = {"initialize": 0, "thread-owner-discovery": 1,
            "thread-follower-read-model-settings": 1, "thread-follower-start-turn": 2,
            "thread-follower-steer-turn": 1, "thread-follower-submit-user-input": 1}
VERSIONS["thread-follower-interrupt-turn"] = 4
VERSIONS.update({"thread-follower-set-queued-follow-ups-state": 1,
                 "thread-follower-remove-queued-message": 1})


class ControlError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


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
                        if msg.get("version") == 2 and params.get("hostId", "local") == "local":
                            with self.condition:
                                self.queues[params.get("conversationId")] = (msg.get("sourceClientId"), params)
                                self.condition.notify_all()
                    elif msg.get("type") == "broadcast" and msg.get("method") == "thread-stream-state-changed":
                        params = msg.get("params") or {}
                        change = params.get("change") or {}
                        if params.get("hostId") == "local" and msg.get("version") != 11:
                            with self.condition:
                                tid=params.get("conversationId");self.snapshots.pop(tid,None);self.revisions.pop(tid,None);self.condition.notify_all()
                        if params.get("hostId") == "local" and msg.get("version") == 11 and change.get("type") == "snapshot":
                            state = change.get("conversationState") or {}
                            if state.get("id") == params.get("conversationId"):
                                with self.condition:
                                    self.snapshots[state["id"]] = (time.monotonic(), msg.get("sourceClientId"), state)
                                    self.revisions[state["id"]] = change.get("revision")
                                    if len(self.snapshots) > 8:
                                        oldest = min(self.snapshots, key=lambda k:self.snapshots[k][0])
                                        self.snapshots.pop(oldest, None)
                                    self.condition.notify_all()
                        elif params.get("hostId") == "local" and msg.get("version") == 11 and change.get("type") == "patches":
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
        rid = str(uuid.uuid4())
        waiter = queue.Queue()
        self.pending[rid] = waiter
        request = {"type": "request", "requestId": rid, "sourceClientId": self.client,
                   "version": VERSIONS[method], "method": method, "params": params, "timeoutMs": int(timeout*1000)}
        if owner:
            request["targetClientId"] = owner
        try:
            self._send(request)
            result = waiter.get(timeout=timeout+1)
            if result.get("resultType") != "success":
                error = str(result.get("error", "未知错误"))
                if error == "no-client-found":
                    raise ControlError("电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试")
                raise ControlError("Codex 未完成操作：" + error[:180])
            if owner and result.get("handledByClientId") != owner:
                raise ControlError("对话持有者发生变化，结果未确认")
            return result
        except queue.Empty:
            raise ControlError("Codex 响应超时，结果未确认；不会自动重试") from None
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


def native_questions(state):
    cards = []
    for req in state.get("requests", []):
        if req.get("method") != "item/tool/requestUserInput":
            continue
        params = req.get("params") or {}
        # Approval tools use different request methods and are never offered here.
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
                entry['records'].append(record)
        entry.update(size=stat.st_size, mtime=stat.st_mtime_ns)
        _async_index.pop(key, None)
        _async_index[key] = entry
        while len(_async_index) > 16:
            _async_index.pop(next(iter(_async_index)))
        return list(entry['records'])


def async_questions(path, active_turn):
    """Read only typed async question calls; never turn arbitrary prose into a form."""
    turn_id, pending, answers = None, {}, {}
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
                        answers[(ident[1], str(ident[2]))] = [a.get("answer", "")]
            except (ValueError, KeyError, IndexError, TypeError):
                continue
    out = []
    for call, q in pending.items():
        if not q["questions"]:
            continue
        if all((call, v["id"]) in answers for v in q["questions"]):
            q.update(status="answered", answers={v["id"]: answers[(call,v["id"])] for v in q["questions"]})
        elif q["turn_id"] != active_turn:
            continue
        out.append(q)
    return out[-6:]


class Bridge:
    def __init__(self):
        self.pipe = None
        self.lock = threading.RLock()
        self.cache = {}
        self.delivery_evidence_cache = {}
        self.data_root = DATA / "attachments"
        self.references = None
        self.dismiss_manager = None

    def _pipe(self):
        if self.pipe is None or self.pipe.closed:
            if self.pipe:
                self.pipe.close()
            try:
                self.pipe = DesktopPipe()
            except Exception as exc:
                raise ControlError("无法连接 Codex 桌面，请确认客户端已打开") from exc
        return self.pipe

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
            removed = self._pipe().call("thread-follower-remove-queued-message", {"conversationId": tid, "messageId": mid}, owner, 20)["result"].get("removed")
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
            qs = native_questions(state)
            qs += async_questions(Path(item["path"]), turns[-1].get("turnId") if is_running(state) and turns else None)
            active_turn = turns[-1].get("turnId") if is_running(state) and turns else None
            for q in qs:
                q["answer_revision"] = hashlib.sha256(json.dumps(q.get("answers", {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
                q["editable"] = q["kind"] == "async" and q["turn_id"] == active_turn
                if self.dismiss_manager:
                    q["desktop_dismiss"] = self.dismiss_manager.latest(tid, q["id"])
            try:
                queued = [{"id": v["id"], "text": v.get("text", ""), "status": (v.get("submission") or {}).get("status", "queued")}
                          for v in self._local_queue(tid)]
                queue_available = True
            except ControlError:
                queued, queue_available = [], False
            self.reconcile_pending(tid)
            return {"available": True, "settings": selected_settings(state), "running": is_running(state),
                    "active_turn_id": turns[-1].get("turnId") if is_running(state) and turns else None,
                    "recent_turns": [{"id":t.get("turnId"),"status":t.get("status")} for t in turns[-4:]],
                    "questions": qs, "plan": latest_plan(state), "catalog": catalog(),
                    "queued": queued, "queue_available": queue_available,
                    "images": self.message_images(tid), "observed_at": int(time.time()*1000)}
        except (ControlError, chats.ChatError, OSError) as exc:
            return {"available": False, "reason": str(exc), "questions": [], "plan": None,
                    "catalog": catalog(), "images": self.message_images(tid)}

    @contextmanager
    def _db(self):
        self.data_root.mkdir(exist_ok=True)
        con = sqlite3.connect(self.data_root / "delivery.sqlite", timeout=15)
        try:
            with con:
                con.execute("CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, thread TEXT, fingerprint TEXT, state TEXT, result TEXT, data TEXT, created REAL)")
                yield con
        finally:
            con.close()

    def _begin(self, rid, tid, body):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{12,80}", rid):
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

    def receipt(self, tid, rid):
        if not (self.data_root / "delivery.sqlite").exists():
            return {"state": "unknown"}
        with self._db() as con:
            row = con.execute("SELECT state,result,data FROM deliveries WHERE id=? AND thread=?", (rid,tid)).fetchone()
        if not row:
            return {"state": "unknown"}
        body = json.loads(row[2])
        result = json.loads(row[1])
        status = row[0]
        if status == "dispatching" and str(body.get("question_id", "")).startswith("native:"):
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

    def send(self, body, timing=None):
        phase=timing or (lambda *args:None)
        phase('send_lock','等待 Codex 发送通道')
        tid, rid = str(body.get("id", "")), str(body.get("request_id", ""))
        text = str(body.get("text", "")).strip()
        ids = body.get("attachments") or []
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
            cards = native_questions(state)
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
        if app not in ('codex','claude','deepseek'):raise ControlError('未知客户端',400)
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
