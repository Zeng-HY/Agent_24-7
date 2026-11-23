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
    # Reading hooks the shared transcript reader asks about.
    home_list = False            # appears in chats.list_conversations (the old home list)
    requires_running_state = True  # a transcript without a running flag cannot be called idle
    dedupe_twins = False         # two records of one answer (Codex)
    relative_links = False       # rewrite relative file links against the working folder (Claude)
    mark_next_open = False       # mark the next-step box seen after reading (Claude)
    assign_turn_id = False       # put the current turn id on every message (Codex)
    final_answer_plan = False    # Codex's plan is a final answer; Claude's is a separate message
    desktop_tasks = False        # desktop IPC task summary tracking (Codex)
    has_skills = False           # supports skill discovery in composer_references
    can_reset_usage = False      # supports usage reset credit redemption (Codex)
    archive_order: int | None = None  # display order in archived list (defaults to manifest order)

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

    def transcript_path(self, item: dict):
        """The file a conversation is read from, or None (an interface-based assistant)."""
        raise Unsupported("这个助手没有可读的记录文件")

    def parse_lines(self, lines: list[bytes], context: dict | None = None,
                    parsed: dict | None = None) -> tuple[list[dict], dict]:
        raise Unsupported("这个助手还不能解析记录")

    def parse_record(self, raw: bytes, context: dict | None = None,
                     parsed: dict | None = None) -> tuple[list[dict], dict]:
        return self.parse_lines([raw], context, parsed)

    def record_uuid(self, raw: bytes) -> str:
        """A record's own uuid when it has one, so a repeated copy can be left out."""
        return ""

    def skip_record(self, raw: bytes) -> bool:
        """Whether this line carries nothing the phone shows."""
        return False

    def step_of(self, name: str, argument: str = "") -> str:
        """edit | run | search | read for a recorded tool call, or ''."""
        return ""

    def tail_step(self, path, started: int = 0) -> str:
        return ""

    def parse_runtime(self, lines: list[bytes]) -> dict:
        return {"model": None, "effort": None, "model_time": None, "usage_time": None,
                "used_tokens": None, "context_window": None, "percent": None,
                "context_state": "unavailable", "turn_time": None, "model_turn_id": None}

    def runtime_complete(self, out: dict) -> bool:
        return bool(out.get("model"))

    def enrich_activity(self, record: dict, messages: list[dict], context: dict, ts: str):
        return None

    def runtime(self, path) -> dict:
        return {}

    def catalog_entries(self, limit: int) -> list[dict]:
        return []

    def ungrouped(self) -> list[dict]:
        return []

    def children(self, tid: str, offset: int = 0, limit: int = 50) -> dict:
        raise Unsupported("这个助手没有子对话")

    def ungrouped_bucket(self, stray: list[dict]) -> dict:
        raise Unsupported("这个助手没有未分组的会话")

    def project_group(self, item: dict) -> tuple[str, str, str] | None:
        """(key, display name, place) for the sidebar tree; None leaves the conversation out."""
        raise Unsupported("这个助手还不能分项目")

    def new_folder(self, group: dict) -> str:
        return ""

    def final_answer(self, message: dict) -> bool:
        return False

    def twins(self, a: dict, b: dict) -> bool:
        return False

    def absolute_links(self, text: str, cwd: str) -> str:
        return text

    def presented_files(self, message: dict, item: dict) -> list[str] | None:
        """Files this message explicitly presented as deliverables, or None for the usual link scan."""
        return None

    def mark_open_next(self, messages: list[dict]) -> None:
        pass

    def transcript(self, tid: str):
        """(item, transcript-like entry) for an interface-based assistant."""
        raise Unsupported("这个助手没有本地记录")

    def native_stream(self, handler, tid: str) -> bool:
        return False

    def watch(self, bridge, tid: str):
        return None

    def control(self, bridge, tid: str):
        return None

    def merge_live(self, page: dict, entry, state, previous=None, lite: bool = False):
        return page["messages"], []

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

    def read_usage(self, svc, live: bool = False) -> dict:
        return self.usage(live=live)

    def usage_not_installed(self) -> dict:
        return {"available": False, "reason": f"这台电脑没装 {self.manifest()['name']['zh']}"}

    def redeem_usage(self, svc, body: dict) -> dict:
        raise Unsupported("这个助手没有重置次数功能")

    # -- archive hooks used by archives.Archives
    def archive_available(self, svc) -> bool:
        return self.can("archive")

    def archive_unavailable_reason(self) -> str:
        return f"{self.manifest()['name']['zh']} 的对话还不能从手机归档"

    def delete_unavailable_reason(self) -> str:
        return "这种对话还不能删除"

    def archive_conv(self, svc, conv_id: str) -> None:
        self.archive(conv_id)

    def unarchive_conv(self, svc, conv_id: str) -> None:
        self.restore(conv_id)

    def archived_list(self, svc) -> list[dict]:
        return []

    def prepare_delete(self, conv_id: str) -> dict | None:
        """Return an immediate result dict if this item shouldn't enter batch delete, else None."""
        return None

    def delete_convs(self, svc, conv_ids: list[str]) -> list[dict]:
        out = []
        for tid in conv_ids:
            try:
                res = self.delete(tid)
                out.append({"app": self.id, "id": tid, "ok": bool(res.get("ok", True)),
                            **({"gone": True} if res.get("gone") else {})})
            except Exception as exc:
                out.append({"app": self.id, "id": tid, "ok": False, "error": str(exc)[:160]})
        return out

    # -- references and skills
    def skill_roots(self, home, cwd: str, read_config, warnings: list, warn_fn) -> tuple[list, set]:
        return [], set()

    def format_skills(self, skills: list[dict]) -> tuple[str, list[dict]]:
        text = "请使用以下选定技能完成本条请求：\n" + "\n".join(
            "[" + s["name"] + "](<" + s["path"] + ">)" for s in skills
        )
        return text, []

    # -- attachments and commands
    def upload(self, conv_id: str, name: str, raw: bytes) -> dict:
        raise Unsupported("这个助手还不能收附件")

    def commands(self, conv_id: str, *, references=None, deepseek=None) -> list:
        raise Unsupported("这个助手还没有斜杠命令")
