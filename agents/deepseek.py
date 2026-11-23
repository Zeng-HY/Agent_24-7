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


AGENT = DeepSeekAgent
