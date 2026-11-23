"""Codex desktop: its own mark, files and local channel."""

from __future__ import annotations

from pathlib import Path

import chats

from .base import Agent, NotFound, make_manifest


class CodexAgent(Agent):
    id = "codex"
    home_list = True
    requires_running_state = True
    dedupe_twins = True
    assign_turn_id = True
    final_answer_plan = True

    def build_manifest(self) -> dict:
        return make_manifest(
            ident="codex",
            zh="Codex",
            en="Codex",
            order=10,
            color="#1E222A",
            color_dark="#FFFFFF",
            icon={"kind": "builtin", "key": "codex"},
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
                "new_projectless": True,
                "new_permission": False,
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
            params={"refresh_ms": 2500},
            ui={"card_layout": "codex.v1", "waiting_text": "等你处理"},
            sources={"catalog": "sqlite", "transcript": "jsonl", "control": "ipc", "live": "pipe+file"},
        )

    def find(self, conv_id: str) -> dict:
        item = chats.codex_thread(conv_id)
        if item is None:
            raise NotFound("找不到这个对话（可能已归档或删掉了）")
        return item

    def transcript_path(self, item: dict):
        path = Path(item["path"]) if item.get("path") else None
        return path if path is not None and path.is_file() else None

    def parse_lines(self, lines, context=None, parsed=None):
        return chats.parse_codex(lines, context, parsed)

    def skip_record(self, raw: bytes) -> bool:
        return (b"event_msg" not in raw[:160] and b"response_item" not in raw[:160]
                and b'"compacted"' not in raw[:160])

    def tail_step(self, path, started: int = 0) -> str:
        return chats.tail_step("codex", path, started)

    def runtime(self, path) -> dict:
        return chats.runtime_info("codex", path)

    def catalog_entries(self, limit: int) -> list[dict]:
        return chats.codex_threads(limit)

    def summary(self, item: dict) -> dict:
        return chats.summary_for(self, item)

    def read(self, conv_id: str, *, limit: int = 60, before: str = "",
             around: str = "", lite: bool = False) -> dict:
        return chats.conversation_for(self, conv_id, limit)

    def final_answer(self, message: dict) -> bool:
        return message.get("role") == "assistant" and message.get("phase") == "final_answer"

    def twins(self, a: dict, b: dict) -> bool:
        return chats.codex_twins(a, b)

    def project_group(self, item: dict):
        import chat_projects
        layout = chat_projects.codex_layout()
        placed = chat_projects.codex_group(item, layout)
        if placed is None:
            return None
        key, place = placed
        name = chat_projects.OTHER_NAME if key == chat_projects.OTHER_KEY else layout[0][key]["name"]
        return key, name, place

    def new_folder(self, group: dict) -> str:
        import chat_projects
        if group["key"] == chat_projects.OTHER_KEY:
            return ""
        roots = chat_projects.codex_layout()[0].get(group["key"], {}).get("roots") or []
        return roots[0] if roots else ""

    def watch(self, bridge, tid: str):
        try:
            return bridge.watch(tid)
        except Exception:
            return None

    def control(self, bridge, tid: str):
        return bridge.status(tid)

    def merge_live(self, page: dict, entry, state, previous=None, lite: bool = False):
        import live_events
        return live_events.merge_live_messages(page, entry, state, previous, lite)

    def detect(self) -> bool:
        import machines

        def package(prefix: str) -> bool:
            packages = machines.LOCALAPPDATA / "Packages"
            return packages.is_dir() and any(packages.glob(prefix + "_*"))

        return package("OpenAI.Codex") or (machines.LOCALAPPDATA / "OpenAI" / "Codex").is_dir()


AGENT = CodexAgent
