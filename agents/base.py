"""What one desktop assistant must answer for the rest of 遥应.

A new assistant is one module under this package plus one line in registry.py.
The module says what it is (manifest) and whether it is installed (detect); the
operations are filled in as the rest of the service learns to use them.
"""

from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """A request the agent could not carry out; the web layer turns it into JSON."""


class Unsupported(AgentError):
    """The agent does not offer this operation (see capabilities in its manifest)."""


class NotFound(AgentError):
    """The conversation is not in this agent's records."""


class UnknownAgent(AgentError):
    """No such assistant on this computer."""


# All capabilities start false: a manifest only claims what its module really does.
CAPABILITIES: dict[str, Any] = {
    "list": False,
    "read": False,
    "search": False,
    "open": False,
    "stop": False,
    "queue": False,
    "steer": False,
    "approve": False,
    "answer": False,
    "new": False,
    "new_projectless": False,
    "new_permission": False,
    "archive": False,
    "restore": False,
    "delete": False,
    "usage": False,
    "waiting": False,
    "attachments": False,
    "slash_commands": False,
    "settings": [],
    "send_modes": [],
    "statuses": ["running", "waiting", "idle", "unknown"],
}

PARAMS: dict[str, Any] = {
    "state_timeout_s": 40,
    "send_timeout_s": 60,
    "open_timeout_s": 45,
    "new_timeout_s": 60,
    "refresh_ms": 2500,
    "max_images": 5,
    "max_image_bytes": 50 * 1024 * 1024,
    "max_text": 20000,
}


def make_manifest(
    *,
    ident: str,
    zh: str,
    en: str,
    order: int,
    color: str,
    color_dark: str | None = None,
    icon: dict | None = None,
    legacy: bool = True,
    min_protocol: int = 1,
    capabilities: dict | None = None,
    params: dict | None = None,
    ui: dict | None = None,
    sources: dict | None = None,
) -> dict:
    """One manifest with the defaults every client can rely on."""
    caps = dict(CAPABILITIES)
    caps.update(capabilities or {})
    limits = dict(PARAMS)
    limits.update(params or {})
    return {
        "schema": 1,
        "id": ident,
        "name": {"zh": zh, "en": en},
        "order": int(order),
        "color": color,
        "color_dark": color_dark or color,
        "icon": icon or {"kind": "builtin", "key": ident},
        "legacy": bool(legacy),
        "min_protocol": int(min_protocol),
        "capabilities": caps,
        "params": limits,
        "ui": ui or {"card_layout": "generic.v1", "waiting_text": "等待你处理"},
        "sources": sources or {},
    }


class Agent:
    """The questions one assistant answers. Unimplemented ones raise Unsupported."""

    id = ""

    def __init__(self) -> None:
        self._manifest = self.build_manifest()

    def build_manifest(self) -> dict:
        raise NotImplementedError

    def manifest(self) -> dict:
        return self._manifest

    def can(self, capability: str) -> bool:
        return bool(self._manifest["capabilities"].get(capability))

    # -- this computer
    def detect(self) -> bool:
        """Whether the desktop app is installed; a few folder checks, no UI."""
        return False

    # -- reading
    def catalog(self, *, limit: int = 40, cursor: str = "", query: str = "",
                sort: str = "updated", status: str = "all") -> dict:
        raise Unsupported("这个助手还不能列对话")

    def find(self, conv_id: str) -> dict:
        raise Unsupported("这个助手还不能定位对话")

    def summary(self, item: dict) -> dict:
        raise Unsupported("这个助手还不能算状态")

    def read(self, conv_id: str, *, limit: int = 60, before: str = "",
             around: str = "", lite: bool = False) -> dict:
        raise Unsupported("这个助手还不能读对话")

    def state(self, conv_id: str, *, fresh: bool = False) -> dict:
        raise Unsupported("这个助手还没有控制态")

    # -- acting
    def send(self, payload: dict) -> dict:
        raise Unsupported("这个助手还不能发消息")

    def check(self, conv_id: str, offset: int, text: str) -> dict:
        raise Unsupported("这个助手还不能核对送达")

    def stop(self, payload: dict) -> dict:
        raise Unsupported("这个助手还不能停止")

    def queue(self, payload: dict) -> dict:
        raise Unsupported("这个助手还没有队列")

    def answer(self, payload: dict) -> dict:
        raise Unsupported("这个助手还不能回答")

    def open(self, conv_id: str) -> dict:
        raise Unsupported("这个助手还不能在电脑上打开")

    # -- new conversations
    def create(self, payload: dict) -> dict:
        raise Unsupported("这个助手还不能新建对话")

    def create_status(self, request_id: str) -> dict:
        raise Unsupported("这个助手还不能查新建进度")

    # -- archive and usage
    def archive(self, conv_id: str) -> dict:
        raise Unsupported("这个助手还不能归档")

    def restore(self, conv_id: str) -> dict:
        raise Unsupported("这个助手还不能恢复")

    def delete(self, conv_id: str) -> dict:
        raise Unsupported("这个助手还不能删除")

    def usage(self, *, live: bool = False) -> dict:
        raise Unsupported("这个助手没有用量")

    # -- attachments and commands
    def upload(self, conv_id: str, name: str, raw: bytes) -> dict:
        raise Unsupported("这个助手还不能收附件")

    def commands(self, conv_id: str) -> list:
        raise Unsupported("这个助手还没有斜杠命令")
