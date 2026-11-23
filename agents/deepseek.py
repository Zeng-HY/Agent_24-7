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

    def native_stream(self, handler, tid: str) -> bool:
        import live_events
        live_events.deepseek_stream(handler, tid)
        return True

    def detect(self) -> bool:
        import machines

        return (machines.APPDATA / "@deepseek-ai" / "dsh-desktop").is_dir()


AGENT = DeepSeekAgent
