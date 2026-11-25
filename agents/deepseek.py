"""DeepSeek Harness desktop: its local interface and websocket."""

from __future__ import annotations

import chats

from .base import Agent, NotFound, Unsupported, make_manifest

DEEPSEEK_STEPS = {
    "pwsh": "run",
    "shell": "run",
    "bash": "run",
    "terminal": "run",
    "exec": "run",
    "apply_patch": "edit",
    "edit": "edit",
    "write": "edit",
    "write_file": "edit",
    "read": "read",
    "read_file": "read",
    "grep": "read",
    "glob": "read",
    "web_search": "search",
    "web_fetch": "search",
    "fetch": "search",
}


class DeepSeekAgent(Agent):
    id = "deepseek"
    home_list = False
    has_skills = False
    archive_order = 20
    notify_uses_file = False
    new_requires_desktop = False
    new_folder_list_own_only = True

    def step_of(self, name: str, argument: str = "") -> str:
        return DEEPSEEK_STEPS.get((name or "").rsplit(".", 1)[-1]) or ""

    def build_manifest(self) -> dict:
        return make_manifest(
            ident="deepseek",
            zh="DeepSeek",
            en="DeepSeek",
            order=30,
            color="#4D6BFE",
            icon={"kind": "builtin", "key": "deepseek"},
            legacy=True,
            min_protocol=1,
            capabilities={
                "list": True,
                "read": True,
                "search": True,
                "open": True,
                "stop": True,
                "queue": True,
                "steer": True,
                "approve": True,
                "answer": True,
                "new": True,
                "new_projectless": False,
                "new_permission": True,
                "archive": True,
                "restore": True,
                "delete": False,
                "usage": False,
                "waiting": True,
                "attachments": True,
                "slash_commands": True,
                "settings": ["model", "permission"],
                "send_modes": ["send", "steer", "queue"],
                "statuses": ["running", "waiting", "idle", "unknown"],
            },
            params={"refresh_ms": 2500},
            ui={"card_layout": "deepseek.v1", "waiting_text": "等待你处理"},
            sources={"catalog": "local-api", "transcript": "local-api", "control": "local-api", "live": "websocket"},
        )

    def _bridge(self):
        import deepseek_control
        return deepseek_control.bridge()

    def find(self, conv_id: str) -> dict:
        import deepseek_control
        try:
            return self._bridge().find(conv_id)
        except deepseek_control.DeepSeekError as exc:
            raise chats.ChatError(str(exc)) from None

    def transcript_path(self, item: dict):
        return None

    def catalog_entries(self, limit: int) -> list[dict]:
        import deepseek_control
        return deepseek_control.listing()["top"]

    def ungrouped(self) -> list[dict]:
        import deepseek_control
        return deepseek_control.listing()["ungrouped"]

    def summary(self, item: dict) -> dict:
        return {"status": item.get("status", "unknown"), "preview": item.get("preview", ""),
                "turn_started": 0, "turn_ended": 0, "step": ""}

    def read(self, conv_id: str, *, limit: int = 60, before: str = "",
             around: str = "", lite: bool = False) -> dict:
        import deepseek_control
        try:
            return self._bridge().conversation(conv_id, limit, before, around)
        except deepseek_control.DeepSeekError as exc:
            raise chats.ChatError(str(exc)) from None

    def transcript(self, tid: str):
        import deepseek_control
        try:
            return self._bridge().transcript(tid)
        except deepseek_control.DeepSeekError as exc:
            raise chats.ChatError(str(exc)) from None

    def project_group(self, item: dict):
        import chat_projects
        if item.get("ungrouped"):
            return chat_projects.OTHER_KEY, chat_projects.OTHER_NAME, ""
        if isinstance(item.get("workspace"), dict):
            return ("w:" + item["workspace"]["id"],
                    item["workspace"]["name"] or item.get("folder") or chat_projects.OTHER_NAME, "")
        return item.get("cwd") or chat_projects.OTHER_KEY, item.get("folder") or chat_projects.OTHER_NAME, ""

    def new_folder(self, group: dict) -> str:
        import chat_projects
        if group["key"] == chat_projects.OTHER_KEY:
            return ""
        item = group["items"][0][0]
        if isinstance(item.get("workspace"), dict) and item["workspace"].get("path"):
            return item["workspace"]["path"]
        return chat_projects._strip(item.get("origin") or item.get("cwd"))

    def children(self, tid: str, offset: int = 0, limit: int = 50) -> dict:
        if tid == "ungrouped":
            kids = self.ungrouped()
        else:
            rows = self.catalog_entries(1000000)
            kids = next((v.get("children", []) for v in rows if v.get("id") == tid), None)
        if kids is None:
            raise chats.ChatError("找不到这个对话，请刷新列表", 404)
        offset = max(0, int(offset)); limit = max(1, min(100, int(limit)))
        return {"items": [self._child(c) for c in kids[offset:offset + limit]],
                "total": len(kids), "offset": offset}

    @staticmethod
    def _child(c: dict) -> dict:
        out = {k: c.get(k) for k in ("app", "id", "title", "folder", "cwd", "updated", "status", "kind", "parent")}
        if c.get("parent_title"):
            out["parent_title"] = c["parent_title"]
        return out

    def ungrouped_bucket(self, stray: list[dict]) -> dict:
        running = sum(1 for c in stray if c.get("status") == "running")
        return {"app": self.id, "id": "ungrouped", "group": True, "title": "未分组的会话",
                "folder": "", "cwd": "", "updated": max(c["updated"] for c in stray),
                "status": "running" if running else "idle",
                "preview": "不在 DeepSeek 工作区里，多是脚本或命令行开的一次性会话",
                "children": stray}

    def presented_files(self, message: dict, item: dict) -> list[str] | None:
        if message.get("kind") != "deliverables":
            return None
        import os
        from pathlib import Path
        paths = []
        for declaration in message.get("presented_files", []):
            raw = declaration["path"]; p = Path(raw)
            if not p.is_absolute():
                cwd = Path(item.get("cwd") or "")
                if not cwd.is_absolute() or p.drive or raw.startswith(("\\", "/")):
                    continue
                p = Path(os.path.abspath(cwd / p))
            paths.append(str(p.absolute()))
        return paths

    def native_stream(self, handler, tid: str, history=None, lite: bool = False) -> bool:
        import live_events
        live_events.deepseek_stream(handler, tid, history, lite)
        return True

    def detect(self) -> bool:
        import machines

        return (machines.APPDATA / "@deepseek-ai" / "dsh-desktop").is_dir()

    # -- commands, archives

    def commands(self, conv_id: str, *, references=None, deepseek=None) -> list:
        import composer_commands
        if deepseek is None:
            return []
        rows = []
        for command in deepseek.commands(conv_id):
            name = command["name"]
            if name in composer_commands.DEEPSEEK_HIDDEN:
                continue
            words = composer_commands.DEEPSEEK.get(name, {})
            rows.append(composer_commands.item(
                name, words.get("title", ""),
                words.get("detail") or composer_commands.one_line(command.get("description")),
                command.get("hint", ""),
            ))
        return rows

    def delete_unavailable_reason(self) -> str:
        return "DeepSeek 没有删除对话的功能，只能恢复"

    def archive_conv(self, svc, conv_id: str) -> None:
        import archives
        import deepseek_control
        ds = svc.deepseek()
        ds.find(conv_id)
        try:
            ds.client.call("workspace/archiveSession", {"request": {"sessionId": conv_id}})
        except deepseek_control.DeepSeekError as exc:
            if getattr(exc, "code", "") == "workspace/session-active":
                raise archives.ArchiveError("这个对话正在运行，先停止这一轮再归档") from None
            raise archives.ArchiveError("DeepSeek 没有归档：" + archives.deepseek_reason(exc)) from None

    def unarchive_conv(self, svc, conv_id: str) -> None:
        import archives
        import deepseek_control
        try:
            svc.deepseek().client.call("workspace/unarchiveSession", {"request": {"sessionId": conv_id}})
        except deepseek_control.DeepSeekError as exc:
            raise archives.ArchiveError("DeepSeek 没有恢复：" + archives.deepseek_reason(exc)) from None

    def archived_list(self, svc) -> list[dict]:
        import archives
        return [dict(v, can_delete=False) for v in archives.deepseek_archived(svc.deepseek())]

    # -- notify hooks

    def notify_step(self, name: str, argument: str = "") -> str | None:
        return DEEPSEEK_STEPS.get((name or "").strip().rsplit(".", 1)[-1])

    def notify_conversations(self, limit: int) -> tuple[list[dict], list[dict]]:
        import deepseek_control
        catalog = deepseek_control.catalog()
        return catalog[:limit], catalog

    def notify_poll(self, notifier, found, item: dict) -> bool:
        from datetime import datetime
        import time
        import deepseek_control
        import notify
        if item.get("status") == "unknown":
            return True
        bridge = deepseek_control.bridge()
        conv = (self.id, item["id"])
        initial = conv not in notifier.ended
        if initial:
            notifier.ended[conv] = "observed"
        now = int(getattr(notifier, "clock", time.time)())
        previous = (getattr(notifier, "running", {}) or {}).get(conv, {})
        events = []
        try:
            page, _ = bridge.records(item["id"], limit=100)
            events = [v.get("event") for v in page.get("records", []) if v.get("event")]
        except deepseek_control.DeepSeekError:
            pass
        starts = [e.get("time", 0) / 1000 for e in events if e.get("type") == "turn/start" and e.get("time")]
        starts = [int(v) for v in starts if v > 0]
        ends = [e for e in events if e.get("type") == "turn/end"]
        action = ""
        last_start = next((e for e in reversed(events) if e.get("type") == "turn/start"), None)
        turn_id = (last_start.get("data") or {}).get("turn") if last_start else None
        for event in reversed(events):
            if event.get("type") == "tool/call":
                data = event.get("data") or {}
                if turn_id is not None and data.get("turn") != turn_id:
                    continue
                name = data.get("name") or ""
                action = self.notify_step(str(name)) or action
                if action:
                    break
        interactions = bridge.events.for_session(item["id"])
        questions = (item.get("_values", {}).get("userQuestions") or {}).get("active", [])
        waiting = getattr(notifier, "waiting", None)
        if interactions or questions:
            notifier.running.pop(conv, None)
            ids = [v["eventId"] for v in interactions] + [q["callId"] for q in questions]
            key = "pending:" + ",".join(sorted(ids))
            text = "DeepSeek 有待处理的提问或批准，请打开对话查看。"
            asks = True
            started = notify.turn_start(previous.get("since"), starts, now)
            if waiting is not None:
                waiting[conv] = {"since": started, "title": chats.one_line(item.get("title") or "", 60)}
            end = dict(key=key, state="done", text=text, asks=asks, started=started, ended=now,
                       started_source="记录" if starts else "不知道")
        elif item.get("_running"):
            if waiting is not None:
                waiting.pop(conv, None)
            started = notify.turn_start(previous.get("since"), starts, now) or None
            notifier._running(item, {"started": datetime.fromtimestamp(started).isoformat() if started else "",
                                     "key": str(starts[-1]) if starts else "", "action": action})
            if action and hasattr(notifier, "_step"):
                notifier._step(item, {"action": action}, notifier.relay_on())
            return True
        else:
            notifier.running.pop(conv, None)
            if waiting is not None:
                waiting.pop(conv, None)
            if not ends:
                return True
            end_event = ends[-1]
            ended = int(end_event.get("time", 0) / 1000) if end_event.get("time") else now
            if ended < notifier.since or (end_event.get("data", {}).get("reason", {}).get("kind") != "completed"):
                return True
            key = str(end_event.get("seq"))
            text = item.get("preview", "")
            asks = False
            started = notify.turn_start(previous.get("since"), starts, now)
            end = dict(key=key, state="done", text=text, asks=asks, started=started or ended, ended=ended,
                       started_source="记录" if starts else ("电脑注意到" if started else "不知道"))
        old = notifier.ended.get(conv)
        notifier.ended[conv] = end["key"]
        if old == end["key"]:
            return True
        if asks and initial:
            return True
        if asks and waiting is not None:
            waiting[conv] = {"since": end["started"], "title": chats.one_line(item.get("title") or "", 60)}
        notifier._tell(found, item, end)
        return True

    # -- new conversation hooks

    def new_own_folders(self, svc) -> list[tuple[str, str, str | None]]:
        import deepseek_control
        return [(w["path"], "DeepSeek 工作区", w.get("name")) for w in deepseek_control.workspaces()]

    def new_options(self, svc) -> dict:
        import deepseek_control
        import new_conversations
        try:
            catalog = deepseek_control.bridge().models()
        except deepseek_control.DeepSeekError as exc:
            return {"models": [], "note": "DeepSeek 的模型列表暂时读不到：" + str(exc)[:100]}
        routable = set(catalog.get("routableProviders") or [])
        groups = [g for g in catalog.get("groups") or [] if not routable or g.get("id") in routable]
        return {
            "models": [
                {
                    "id": f"{g['id']}/{m['id']}",
                    "label": (m.get("name") or m["id"]) + (" · " + (g.get("name") or g["id"]) if len(groups) > 1 else ""),
                    "efforts": [
                        {"id": e["id"], "label": new_conversations.DEEPSEEK_EFFORTS.get(e["id"], e.get("name") or e["id"])}
                        for e in (m.get("reasoning") or {}).get("efforts") or []
                    ],
                    "default_effort": (m.get("reasoning") or {}).get("defaultEffort"),
                }
                for g in groups
                for m in g.get("models") or []
            ],
            "note": "",
        }

    def validate_new_permission(self, permission: str, confirmed: bool) -> None:
        import deepseek_control
        option = next((value for value in deepseek_control.bridge().permissions()["options"] if value["value"] == permission), None)
        if option is None:
            raise chats.ChatError("DeepSeek 权限选项已变化，请重新选择")
        if option["confirm"] and confirmed is not True:
            raise chats.ChatError("完全权限或自动审查需要先确认")

    def validate_new_references(self, refs: list) -> None:
        if any(isinstance(r, dict) and r.get("kind") not in ("chat", "file", "folder") for r in refs):
            raise chats.ChatError("DeepSeek 不能用技能，只能引用对话、附文件")

    def prepare_new_submission(self, svc, rid: str, data: dict, body: dict) -> None:
        import deepseek_control
        data["workspace_id"] = deepseek_control.workspace_for(data["folder"])["id"]
        if body.get("permission"):
            data.update(permission=body.get("permission"), permission_confirmed=body.get("permission_confirmed") is True)

    def run_new(self, svc, rid: str, data: dict, trace) -> None:
        svc._run_deepseek(rid, data, trace)

    def reconcile_new_status(self, svc, rid: str, state: str, data: dict, result: dict) -> tuple[str, dict]:
        if data.get("id") and state in ("dispatching", "unconfirmed") and svc._deepseek_receipt(rid) == "accepted":
            state, result = "accepted", {"message": "首条消息已送达"}
            svc._save(rid, state, data, result)
        if state == "prepared":
            state, result = "failed", {"message": "对话已建好，第一句话还没发出；可以继续发送", "not_submitted": True}
            svc._save(rid, state, data, result)
        return state, result

    def handle_new_error(self, svc, rid: str, state: str, data: dict, trace, exc: Exception) -> tuple[bool, bool]:
        safe = isinstance(exc, chats.SendNotSubmitted) and state != "dispatching"
        if state == "prepared":
            safe = True
        elif state == "dispatching" and data.get("id"):
            safe = svc._deepseek_receipt(rid) == "unknown"
        return False, safe

    # -- lifecycle & HTTP action handlers (shared by /api/agents/deepseek/* and /api/deepseek/*)

    def on_server_init(self, server) -> None:
        import deepseek_control
        bridge = getattr(server, "deepseek", None)
        if bridge is None or not deepseek_control.HOME.is_dir():
            return
        bridge.events.start()
        self.set_service(server, bridge.events)

    def on_server_close(self, server) -> None:
        events = self.service(server)
        bridge = getattr(server, "deepseek", None)
        if events is None and bridge is not None:
            events = getattr(bridge, "events", None)
        if events is not None:
            try:
                events.close()
            except Exception:
                pass

    def on_apps_rechecked(self, server, apps: list[str]) -> None:
        import deepseek_control
        deepseek = getattr(server, "deepseek", None)
        if deepseek is not None and self.id in apps and deepseek_control.HOME.is_dir():
            deepseek.events.start()
            self.set_service(server, deepseek.events)

    def _upload_for_chat(self, handler, tid: str, name: str, raw: bytes) -> dict:
        return handler.server.codex.upload(tid, name, raw, self.id)

    def _run_deepseek(self, handler, fn) -> None:
        import codex_control
        import deepseek_control
        try:
            result = fn(handler.server.deepseek)
            if result is not None:
                handler._json(result)
        except (deepseek_control.DeepSeekError, codex_control.ControlError, chats.ChatError) as exc:
            handler._json(
                {"error": str(exc), "not_submitted": bool(getattr(exc, "not_submitted", False))},
                getattr(exc, "status", 400),
            )
        except (ValueError, TypeError, KeyError):
            handler._json({"error": "DeepSeek 请求或接口格式不兼容"}, 400)

    def http_state(self, handler) -> None:
        q = handler._query()
        self._run_deepseek(handler, lambda bridge: bridge.state(q.get("id", "")))

    def http_receipt(self, handler) -> None:
        q = handler._query()
        self._run_deepseek(handler, lambda bridge: bridge.receipt(q.get("request_id", "")))

    def http_send(self, handler, body: dict) -> None:
        import time
        payload = {**body, "intent": "steer"} if body.get("intent") == "auto" else body
        def run(bridge):
            result = bridge.send(payload)
            result["accepted_at"] = int(time.time() * 1000)
            return result
        self._run_deepseek(handler, run)

    def http_stop(self, handler, body: dict) -> None:
        turn = body.get("expected_turn") if "expected_turn" in body else body.get("turn_id")
        self._run_deepseek(handler, lambda bridge: bridge.stop(body.get("id"), turn))

    def http_queue(self, handler, body: dict) -> None:
        item_id = body.get("item_id") if "item_id" in body else body.get("message_id")
        action_map = {"promote": "steer", "delete": "remove"}
        action = action_map.get(body.get("action"), body.get("action"))
        self._run_deepseek(handler, lambda bridge: bridge.queue_action(body.get("id"), item_id, action))

    def http_answer(self, handler, body: dict) -> None:
        if "choice" in body:
            self._run_deepseek(
                handler,
                lambda bridge: bridge.events.answer(body.get("id"), body.get("event_id"), body.get("choice"), "approval/request"),
            )
        else:
            self._run_deepseek(handler, lambda bridge: bridge.answer(body))

    def http_open(self, handler, body: dict) -> None:
        import deepseek_control
        import remote
        try:
            handler.server.deepseek.find(body.get("id"))
            remote.os.startfile("dsh://open")
            handler._json({"ok": True, "text": "已打开 DeepSeek；请在电脑侧选择对应对话"})
        except (deepseek_control.DeepSeekError, OSError) as exc:
            handler._json({"error": str(exc)}, 400)

    def http_legacy_get(self, handler, sub: str) -> None:
        import deepseek_control
        if sub == "state":
            self.http_state(handler)
            return
        if sub == "receipt":
            self.http_receipt(handler)
            return
        q = handler._query()
        def run(bridge):
            if sub == "image":
                raw, mime = bridge.image(q.get("id", ""), q.get("attachment", ""), q.get("thumb") == "1")
                handler._send(200, raw, mime)
                return None
            if sub == "models":
                return bridge.models()
            if sub == "permissions":
                return bridge.permissions(q.get("id", ""))
            raise deepseek_control.DeepSeekError("没有这个接口", 404)
        self._run_deepseek(handler, run)

    def http_legacy_post(self, handler, sub: str, body: dict) -> None:
        import deepseek_control
        if sub == "send":
            import time
            def run(bridge):
                result = bridge.send(body)
                result["accepted_at"] = int(time.time() * 1000)
                return result
            self._run_deepseek(handler, run)
        elif sub == "stop":
            self._run_deepseek(handler, lambda bridge: bridge.stop(body.get("id"), body.get("expected_turn")))
        elif sub == "queue":
            self._run_deepseek(handler, lambda bridge: bridge.queue_action(body.get("id"), body.get("item_id"), body.get("action")))
        elif sub == "answer":
            self._run_deepseek(handler, lambda bridge: bridge.answer(body))
        elif sub == "approval":
            self._run_deepseek(
                handler,
                lambda bridge: bridge.events.answer(body.get("id"), body.get("event_id"), body.get("choice"), "approval/request"),
            )
        elif sub == "permission":
            self._run_deepseek(
                handler,
                lambda bridge: bridge.set_permission(body.get("id"), body.get("preset"), body.get("confirmed") is True),
            )
        elif sub == "model":
            self._run_deepseek(handler, lambda bridge: bridge.select_model(body.get("id"), body.get("settings", {})))
        elif sub == "create":
            self._run_deepseek(handler, lambda bridge: bridge.create(body))
        else:
            def _missing(_bridge):
                raise deepseek_control.DeepSeekError("没有这个接口", 404)
            self._run_deepseek(handler, _missing)


AGENT = DeepSeekAgent
