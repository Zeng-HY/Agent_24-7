"""Claude Code desktop: files, UI Automation and its hook."""

from __future__ import annotations

import chats

from .base import Agent, NotFound, make_manifest


class ClaudeAgent(Agent):
    id = "claude"
    home_list = True
    requires_running_state = False
    relative_links = True
    mark_next_open = True

    def build_manifest(self) -> dict:
        return make_manifest(
            ident="claude",
            zh="Claude",
            en="Claude",
            order=20,
            color="#D97757",
            icon={"kind": "builtin", "key": "claude"},
            legacy=True,
            min_protocol=1,
            capabilities={
                "list": True,
                "read": True,
                "search": True,
                "open": True,
                "stop": True,
                "queue": False,
                "steer": True,
                "approve": True,
                "answer": True,
                "new": True,
                "new_projectless": True,
                "new_permission": False,
                "archive": True,
                "restore": True,
                "delete": False,
                "usage": True,
                "waiting": True,
                "attachments": True,
                "slash_commands": True,
                "settings": ["model", "effort", "permission", "mode"],
                "send_modes": ["send", "steer"],
                "statuses": ["running", "waiting", "idle", "unknown"],
            },
            params={"state_timeout_s": 20, "new_timeout_s": 70, "refresh_ms": 5000},
            ui={"card_layout": "claude.v1", "waiting_text": "等待你处理"},
            sources={"catalog": "json-index", "transcript": "jsonl", "control": "ui-automation+hook", "live": "file-poll"},
        )

    def find(self, conv_id: str) -> dict:
        item = next((s for s in chats.claude_sessions(100000) if s["id"] == conv_id), None)
        if item is None:
            raise NotFound("找不到这个对话（可能已归档或删掉了）")
        return item

    def transcript_path(self, item: dict):
        return chats.claude_transcript(item)

    def parse_lines(self, lines, context=None, parsed=None):
        return chats.parse_claude(lines, context, parsed)

    def record_uuid(self, raw: bytes) -> str:
        return chats.record_uuid(raw)

    def catalog_entries(self, limit: int) -> list[dict]:
        return chats.claude_sessions(limit)

    def summary(self, item: dict) -> dict:
        return chats.summary_for(self, item)

    def read(self, conv_id: str, *, limit: int = 60, before: str = "",
             around: str = "", lite: bool = False) -> dict:
        return chats.conversation_for(self, conv_id, limit)

    def project_group(self, item: dict):
        import chat_projects
        key, name = chat_projects.claude_group(item)
        return key, name, ""

    def new_folder(self, group: dict) -> str:
        import chat_projects
        if group["key"] == chat_projects.OTHER_KEY:
            return ""
        item = group["items"][0][0]
        return chat_projects._strip(item.get("origin") or item.get("cwd"))

    def absolute_links(self, text: str, cwd: str) -> str:
        from message_files import absolute_links
        return absolute_links(text, cwd)

    def mark_open_next(self, messages: list[dict]) -> None:
        chats.mark_open_next(messages)

    def detect(self) -> bool:
        import machines

        def package(prefix: str) -> bool:
            packages = machines.LOCALAPPDATA / "Packages"
            return packages.is_dir() and any(packages.glob(prefix + "_*"))

        return (package("Claude")
                or (machines.LOCALAPPDATA / "AnthropicClaude").is_dir()
                or (machines.APPDATA / "Claude").is_dir())


AGENT = ClaudeAgent
