"""A fake assistant used only by tests.

It proves that one module is enough: manifest, detection, a list, reading,
sending, stopping, archiving and usage all live here, with no real computer
data. It is not in the production list in registry.py.
"""

from __future__ import annotations

import time

from .base import Agent, NotFound, Unsupported, make_manifest


class TestingAgent(Agent):
    id = "testing"
    notify_uses_file = False
    new_requires_desktop = False

    def new_options(self, svc) -> dict:
        return {"models": [{"id": "test-model", "label": "测试模型", "efforts": [{"id": "high", "label": "高"}], "default_effort": "high"}], "note": ""}

    def __init__(self) -> None:
        super().__init__()
        now = int(time.time() * 1000)
        self._rows = [
            {"app": self.id, "id": "test-running", "title": "测试对话 A", "folder": "C:\\测试\\项目",
             "cwd": "C:\\测试\\项目", "updated": now, "created": now - 60_000, "pinned": False,
             "status": "running", "preview": "正在跑测试", "turn_started": now // 1000,
             "turn_ended": 0, "step": "run", "archived": False},
            {"app": self.id, "id": "test-waiting", "title": "测试对话 B", "folder": "",
             "cwd": "", "updated": now - 120_000, "created": now - 3600_000, "pinned": False,
             "status": "waiting", "preview": "等你选择", "turn_started": now // 1000 - 60,
             "turn_ended": 0, "step": "", "archived": False},
        ]
        self._messages = {
            "test-running": [
                {"id": "m1", "role": "user", "time": now - 50_000, "text": "跑一下测试", "kind": ""},
                {"id": "m2", "role": "assistant", "time": now - 40_000, "text": "正在跑", "kind": "text"},
            ],
            "test-waiting": [
                {"id": "m3", "role": "user", "time": now - 120_000, "text": "选一个方案", "kind": ""},
                {"id": "m4", "role": "assistant", "time": now - 110_000, "text": "请选择 A 或 B", "kind": "question"},
            ],
        }
        self._created = 0

    def build_manifest(self) -> dict:
        return make_manifest(
            ident="testing",
            zh="测试助手",
            en="Test Helper",
            order=99,
            color="#7C3AED",
            color_dark="#A78BFA",
            icon={"kind": "builtin", "key": "generic"},
            legacy=False,
            min_protocol=2,
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
                "new_projectless": True,
                "new_permission": True,
                "archive": True,
                "restore": True,
                "delete": True,
                "usage": True,
                "waiting": True,
                "attachments": True,
                "slash_commands": True,
                "settings": ["model", "effort"],
                "send_modes": ["send", "steer", "queue"],
                "statuses": ["running", "waiting", "idle", "unknown"],
            },
            params={"state_timeout_s": 2, "send_timeout_s": 5, "refresh_ms": 1000},
            ui={"card_layout": "generic.v1", "waiting_text": "等待你处理"},
            sources={"catalog": "memory", "transcript": "memory", "control": "memory", "live": "memory"},
        )

    def detect(self) -> bool:
        return True

    def catalog_entries(self, limit: int) -> list[dict]:
        return self.catalog(limit=limit)["items"]

    def project_group(self, item: dict):
        import chat_projects
        if item.get("folder"):
            return "p:" + item["folder"], item["folder"], ""
        return chat_projects.OTHER_KEY, chat_projects.OTHER_NAME, ""

    def new_folder(self, group: dict) -> str:
        import chat_projects
        if group["key"] == chat_projects.OTHER_KEY:
            return ""
        return group["items"][0][0].get("folder") or ""

    def catalog(self, *, limit: int = 40, cursor: str = "", query: str = "",
                sort: str = "updated", status: str = "all") -> dict:
        rows = [r for r in self._rows if not r["archived"]]
        if query:
            needle = query.casefold()
            rows = [r for r in rows if needle in r["title"].casefold()]
        if status != "all":
            rows = [r for r in rows if r["status"] == status]
        key = "created" if sort == "created" else "updated"
        rows.sort(key=lambda r: (-r[key], r["id"]))
        start = int(cursor or 0)
        page = rows[start:start + limit]
        more = start + len(page) < len(rows)
        return {"items": [dict(r) for r in page], "has_more": more,
                "next_cursor": str(start + len(page)) if more else "", "total": len(rows)}

    def find(self, conv_id: str) -> dict:
        for row in self._rows:
            if row["id"] == conv_id:
                return row
        raise NotFound("找不到这个测试对话")

    def summary(self, item: dict) -> dict:
        return {"status": item.get("status", "unknown"), "preview": item.get("preview", ""),
                "modified": item.get("updated", 0), "turn_started": item.get("turn_started", 0),
                "turn_ended": item.get("turn_ended", 0), "step": item.get("step", "")}

    def read(self, conv_id: str, *, limit: int = 60, before: str = "",
             around: str = "", lite: bool = False) -> dict:
        item = self.find(conv_id)
        messages = self._messages.get(conv_id, [])
        if before:
            messages = [m for m in messages if m["id"] < before]
        return {"app": self.id, "id": conv_id, "title": item["title"], "folder": item["folder"],
                "cwd": item["cwd"], "status": item["status"], "runtime": {},
                "messages": messages[-limit:], "has_more": False, "next_cursor": "",
                "has_newer": False, "reset": False, "total": len(messages)}

    def transcript(self, tid: str):
        import threading
        from types import SimpleNamespace
        item = self.find(tid)
        messages = [dict(m) for m in self._messages.get(tid, [])]
        by_id = {m["id"]: m for m in messages}
        return item, SimpleNamespace(messages=messages, by_id=by_id, state={"running": item["status"] == "running"},
                                     context={}, offset=0, size=0, mtime=0, lock=threading.RLock())

    def state(self, conv_id: str, *, fresh: bool = False) -> dict:
        item = self.find(conv_id)
        return {"available": True, "running": item["status"] == "running", "status": item["status"],
                "turn_id": "turn-1" if item["status"] == "running" else "",
                "turn_started": item["turn_started"], "turn_ended": item["turn_ended"],
                "step": item["step"], "settings": {}, "runtime": {}, "questions": [],
                "tasks": [], "queued": [], "queue_available": True, "stop_token": "stop-1"}

    def send(self, payload: dict) -> dict:
        conv_id = str(payload.get("id", ""))
        item = self.find(conv_id)
        text = str(payload.get("text", ""))
        now = int(time.time() * 1000)
        mid = f"m{len(self._messages.get(conv_id, [])) + 1}"
        self._messages.setdefault(conv_id, []).append(
            {"id": mid, "role": "user", "time": now, "text": text, "kind": ""})
        item.update(status="running", preview=text, updated=now, turn_started=now // 1000)
        return {"ok": True, "accepted": True, "pressed": True, "offset": 0,
                "request_id": str(payload.get("request_id", "")), "text": "测试助手已接收",
                "delivery_state": "accepted", "accepted_at": now}

    def check(self, conv_id: str, offset: int, text: str) -> dict:
        return {"delivered": True, "queued": False, "stage": "received"}

    def stop(self, payload: dict) -> dict:
        item = self.find(str(payload.get("id", "")))
        item.update(status="idle", step="", turn_ended=int(time.time() * 1000))
        return {"ok": True, "text": "测试助手已停止"}

    def queue(self, payload: dict) -> dict:
        return {"ok": True, "action": payload.get("action", "")}

    def answer(self, payload: dict) -> dict:
        item = self.find(str(payload.get("id", "")))
        item.update(status="idle", preview="已选择", step="")
        return {"ok": True, "text": "测试助手已收到回答"}

    def open(self, conv_id: str) -> dict:
        item = self.find(conv_id)
        return {"ok": True, "text": f"测试助手已打开「{item['title']}」"}

    def create(self, payload: dict) -> dict:
        self._created += 1
        ident = f"test-new-{self._created}"
        now = int(time.time() * 1000)
        title = str(payload.get("text") or "测试新对话")[:40]
        self._rows.append({"app": self.id, "id": ident, "title": title,
                           "folder": str(payload.get("folder", "")), "cwd": str(payload.get("folder", "")),
                           "updated": now, "created": now, "pinned": False, "status": "running",
                           "preview": str(payload.get("text", "")), "turn_started": now // 1000,
                           "turn_ended": 0, "step": "", "archived": False})
        self._messages[ident] = [{"id": "m1", "role": "user", "time": now,
                                  "text": str(payload.get("text", "")), "kind": ""}]
        return {"request_id": str(payload.get("request_id", "")), "state": "accepted",
                "id": ident, "title": title, "message": "测试助手已建好"}

    def create_status(self, request_id: str) -> dict:
        return {"request_id": request_id, "state": "accepted", "id": "test-new-1", "title": "测试新对话"}

    def archive(self, conv_id: str) -> dict:
        item = self.find(conv_id)
        item["archived"] = True
        return {"ok": True, "app": self.id, "id": conv_id, "archived": True}

    def restore(self, conv_id: str) -> dict:
        item = self.find(conv_id)
        item["archived"] = False
        return {"ok": True, "app": self.id, "id": conv_id, "archived": False}

    def delete(self, conv_id: str) -> dict:
        item = self.find(conv_id)
        if not item["archived"]:
            raise Unsupported("只能删已归档的测试对话")
        self._rows = [r for r in self._rows if r["id"] != conv_id]
        return {"ok": True, "app": self.id, "id": conv_id, "gone": True}

    def usage(self, *, live: bool = False) -> dict:
        return {"available": True, "source": "testing", "as_of": int(time.time() * 1000),
                "windows": [{"label": "测试额度", "used_percent": 10, "resets_at": int(time.time() * 1000) + 3600_000}]}

    def upload(self, conv_id: str, name: str, raw: bytes) -> dict:
        return {"id": "att-1", "name": name, "size": len(raw), "app": self.id}

    def archived_list(self, svc) -> list[dict]:
        return [dict(r, can_delete=True) for r in self._rows if r["archived"]]

    def commands(self, conv_id: str, *, references=None, deepseek=None) -> list:
        import composer_commands
        return [composer_commands.item("test", "测试命令", "只用于测试")]


AGENT = TestingAgent
