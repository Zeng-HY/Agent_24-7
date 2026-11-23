"""Legacy route prefixes, old default app and old page capability flags.

This is the single compatibility table for pre-registry routes (/api/codex/*,
/api/claude/*, /api/deepseek/*, /api/chat/*) so common code in remote.py does
not branch on assistant names. New assistants never need entries here.
"""

from __future__ import annotations

DEFAULT_APP = "codex"
CODEX = "codex"
CLAUDE = "claude"
DEEPSEEK = "deepseek"

LEGACY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/deepseek/", DEEPSEEK),
    ("/api/codex/", CODEX),
    ("/api/claude/", CLAUDE),
)

DEEPSEEK_LEGACY_CHAT_PATHS = frozenset({
    "/api/chat/send",
    "/api/chat/enter",
    "/api/chat/check",
})


def match_prefix(path: str) -> tuple[str, str] | None:
    """Return (agent_id, subpath) if path hits a legacy per-agent prefix, else None."""
    for prefix, agent_id in LEGACY_PREFIXES:
        if path.startswith(prefix):
            return agent_id, path[len(prefix):]
    return None


def page_capabilities(apps: list[str]) -> dict:
    """Old window.MACHINE capability flags expected by the existing web UI."""
    return {"claude_archive": True} if CLAUDE in apps else {}


def refused_legacy_chat_route(app: str, path: str) -> str | None:
    """Error message when an old /api/chat/* route is called for an assistant with its own channel."""
    if app == DEEPSEEK and path in DEEPSEEK_LEGACY_CHAT_PATHS:
        return "DeepSeek 请使用专用控制通道；草稿已保留"
    return None
