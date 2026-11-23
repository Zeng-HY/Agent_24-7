"""Claude Code desktop: files, UI Automation and its hook."""

from __future__ import annotations

from .base import Agent, make_manifest


class ClaudeAgent(Agent):
    id = "claude"

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

    def detect(self) -> bool:
        import machines

        def package(prefix: str) -> bool:
            packages = machines.LOCALAPPDATA / "Packages"
            return packages.is_dir() and any(packages.glob(prefix + "_*"))

        return (package("Claude")
                or (machines.LOCALAPPDATA / "AnthropicClaude").is_dir()
                or (machines.APPDATA / "Claude").is_dir())


AGENT = ClaudeAgent
