"""Codex desktop: its own mark, files and local channel."""

from __future__ import annotations

from .base import Agent, make_manifest


class CodexAgent(Agent):
    id = "codex"

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

    def detect(self) -> bool:
        import machines

        def package(prefix: str) -> bool:
            packages = machines.LOCALAPPDATA / "Packages"
            return packages.is_dir() and any(packages.glob(prefix + "_*"))

        return package("OpenAI.Codex") or (machines.LOCALAPPDATA / "OpenAI" / "Codex").is_dir()


AGENT = CodexAgent
