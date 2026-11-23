"""DeepSeek Harness desktop: its local interface and websocket."""

from __future__ import annotations

from .base import Agent, make_manifest


class DeepSeekAgent(Agent):
    id = "deepseek"

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

    def detect(self) -> bool:
        import machines

        return (machines.APPDATA / "@deepseek-ai" / "dsh-desktop").is_dir()


AGENT = DeepSeekAgent
