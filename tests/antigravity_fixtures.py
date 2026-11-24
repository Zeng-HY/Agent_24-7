"""Antigravity's own files, made up for tests: a summaries database and transcript files.

The shapes follow docs/adding-an-agent.md's Antigravity section and the real format seen on 2026-11-24;
the words, folders and conversation ids are invented. Nothing here touches a real user folder.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

# The columns Antigravity writes into conversation_summaries (2026-11-24).
COLUMNS = (
    "conversation_id", "title", "preview", "step_count", "last_modified_time", "workspace_uris",
    "status", "source", "project_id", "agent_name", "parent_conversation_id", "nesting_depth",
    "battle_id", "winning_conversation_id", "not_fully_idle", "killed", "last_user_input_time",
    "last_user_input_step_index", "app_data_dir", "raw_summary", "group_id",
)

DEFAULTS = {
    "title": "测试对话",
    "preview": "测试内容",
    "step_count": 2,
    "last_modified_time": "2026-11-20 10:00:00.1234567+08:00",
    "workspace_uris": '["file:///c%3A/%E6%B5%8B%E8%AF%95/%E9%A1%B9%E7%9B%AE"]',
    "status": "CASCADE_RUN_STATUS_IDLE",
    "source": "",
    "project_id": None,
    "agent_name": None,
    "parent_conversation_id": None,
    "nesting_depth": 0,
    "battle_id": None,
    "winning_conversation_id": None,
    "not_fully_idle": 0,
    "killed": 0,
    "last_user_input_time": "2026-11-20 09:59:00.0000001+08:00",
    "last_user_input_step_index": 0,
    "app_data_dir": "测试目录",
    "raw_summary": "{}",
    "group_id": None,
}


def data_root(home: Path) -> Path:
    """The Antigravity folder under a fake machines.HOME."""
    return Path(home) / ".gemini" / "antigravity"


def row(conv_id: str, **changes) -> dict:
    values = dict(DEFAULTS)
    values["conversation_id"] = conv_id
    values.update(changes)
    return values


def record(step: int, kind: str, source: str, content=None, status: str = "DONE",
           created_at: str | None = None, **extra) -> dict:
    """One transcript line, with only the fields the reader uses and the extra ones a test names."""
    item = {
        "step_index": step,
        "source": source,
        "type": kind,
        "status": status,
        "created_at": created_at or f"2026-11-20 10:00:0{min(step, 9)}.1234567+08:00",
        "content": content,
    }
    item.update(extra)
    return item


def write(
    home: Path,
    rows: list[dict] | None = None,
    transcripts: dict[str, list[dict]] | None = None,
    full: dict[str, list[dict]] | None = None,
    columns: tuple[str, ...] = COLUMNS,
) -> Path:
    """Build the data folder [home]/.gemini/antigravity and return it."""
    root = data_root(home)
    root.mkdir(parents=True, exist_ok=True)
    database = root / "conversation_summaries.db"
    if database.exists():
        database.unlink()
    con = sqlite3.connect(database)
    try:
        con.execute("CREATE TABLE conversation_summaries (" + ", ".join(f'"{name}" TEXT' for name in columns) + ")")
        for values in rows or []:
            kept = {name: values.get(name, DEFAULTS.get(name)) for name in columns}
            con.execute(
                "INSERT INTO conversation_summaries (" + ", ".join(f'"{name}"' for name in columns) + ")"
                " VALUES (" + ", ".join("?" for _ in columns) + ")",
                [kept[name] for name in columns],
            )
        con.commit()
    finally:
        con.close()
    for conv_id, records in (transcripts or {}).items():
        folder = root / "brain" / str(conv_id) / ".system_generated" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "transcript.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    for conv_id, records in (full or {}).items():
        folder = root / "brain" / str(conv_id) / ".system_generated" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "transcript_full.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    return root


TOOL_OUTPUT = "工具输出：登录页 6 个测试都通过"
STRUCTURED_CUT = '{"batch":"示例","items":[{"verdict":"pass"'
STRUCTURED_FULL = {"batch": "示例", "items": [{"verdict": "pass", "reason": "编的"}]}
PLAIN_CUT = "这是被截短的普通总结"
PLAIN_FULL = "这是写给人看的完整总结。"


def real_transcript() -> list[dict]:
    """One conversation in the shape the real records use: calls on PLANNER_RESPONSE, outputs on GENERIC."""
    return [
        record(1, "USER_INPUT", "USER_EXPLICIT", "帮我看看这个文件"),
        record(2, "SYSTEM_MESSAGE", "SYSTEM", "内部提示"),
        record(3, "PLANNER_RESPONSE", "MODEL", "看过了，没有问题。"),
        record(4, "PLANNER_RESPONSE", "MODEL", None, tool_calls=[
            {"name": "read_file", "args": {"Path": "C:\\测试\\a.txt", "StartLine": 1}},
            {"name": "run_command", "args": {"CommandLine": "pytest -q", "toolSummary": "跑登录页的测试"}},
            {"name": "edit_file", "args": {"Path": "C:\\测试\\b.py", "Replacement": "改好了"}},
        ]),
        record(5, "GENERIC", "MODEL", "工具输出：文件内容第一行，这一行不该显示"),
        record(6, "GENERIC", "MODEL", TOOL_OUTPUT),
        record(7, "GENERIC", "MODEL", "工具输出：b.py 已修改"),
        record(8, "PLANNER_RESPONSE", "MODEL", "补充一句", tool_calls=[
            {"name": "edit_file", "args": {"Path": "C:\\测试\\c.py", "Replacement": "也改好了"}},
        ]),
        record(9, "GENERIC", "MODEL", "工具输出：c.py 已修改"),
        record(10, "ERROR_MESSAGE", "SYSTEM", None, error="被限流了"),
        record(11, "CHECKPOINT", "SYSTEM", "检查点"),
        record(12, "USER_INPUT", "USER_EXPLICIT", None, media=[{"kind": "image"}]),
        record(13, "USER_INPUT", "USER_EXPLICIT", "显示的截断内容", truncated_fields=["content"]),
        record(14, "PLANNER_RESPONSE", "MODEL", None, truncated_fields=["tool_calls"], tool_calls=[
            {"name": "finish", "args": {"result": STRUCTURED_CUT}},
        ]),
        record(15, "GENERIC", "MODEL", "工具输出：结构化结果已交回"),
        record(16, "PLANNER_RESPONSE", "MODEL", None, truncated_fields=["tool_calls"], tool_calls=[
            {"name": "finish", "args": {"result": PLAIN_CUT}},
        ]),
        record(17, "GENERIC", "MODEL", "工具输出：普通总结已交回"),
    ]


# ---------------------------------------------------------------- the app's local service, made up


TOKEN = "test-csrf-token-8f3a"


def picture(fmt: str = "PNG", width: int = 2, height: int = 2) -> bytes:
    """A real, tiny picture of the named format (made in memory, never read from a user folder)."""
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


def waiting_step(trajectory: str = "traj-1", index: int = 3, action: str = "run_command",
                 target: str = "npm test") -> dict:
    """One GetCascadeTrajectorySteps entry that is waiting for an approval."""
    return {
        "status": "CORTEX_STEP_STATUS_WAITING",
        "requestedInteraction": {"permission": {"resource": {"action": action, "target": target}}},
        "metadata": {"sourceTrajectoryStepInfo": {"trajectoryId": trajectory, "stepIndex": index}},
    }


class FakeHub:
    """A tiny HTTP service on 127.0.0.1 standing in for the language server.

    It checks the CSRF header, answers the two methods this batch may call, and records every request.
    The hub file is written under the fake machines.HOME, with this test process's pid (which is alive).
    """

    def __init__(self, home: Path, token: str = TOKEN, steps: list[dict] | None = None) -> None:
        self.home = Path(home)
        self.token = token
        self.steps = list(steps or [])
        self.requests: list[dict] = []
        self.fail = ""            # a method name that answers HTTP 500
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port = 0

    def __enter__(self) -> "FakeHub":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                method = self.path.rstrip("/").rsplit("/", 1)[-1]
                owner.requests.append({"method": method, "body": body,
                                       "token": self.headers.get("x-codeium-csrf-token"),
                                       "connect": self.headers.get("Connect-Protocol-Version")})
                if self.headers.get("x-codeium-csrf-token") != owner.token:
                    return self._send(403, {"error": "token"})
                if owner.fail and method == owner.fail:
                    return self._send(500, {"error": "boom"})
                if method == "GetCascadeTrajectorySteps":
                    return self._send(200, {"steps": owner.steps})
                if method == "HandleCascadeUserInteraction":
                    owner.steps = []  # answered: the app no longer asks
                    return self._send(200, {"ok": True})
                if method == "SendUserCascadeMessage":
                    return self._send(200, {})
                if method == "UpdateConversationAnnotations":
                    cascade = str((body or {}).get("cascadeId") or "")
                    folder = data_root(owner.home) / "annotations"
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / f"{cascade}.pbtxt").write_text(
                        "permission_preset:AGENT_PERMISSION_PRESET_TURBO", encoding="utf-8")
                    return self._send(200, {})
                if method == "CancelCascadeInvocation":
                    return self._send(200, {})
                return self._send(404, {"error": "no such method"})

            def _send(self, code: int, obj: dict) -> None:
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, name="fake-antigravity", daemon=True)
        self.thread.start()
        daemon = data_root(self.home) / "daemon"
        daemon.mkdir(parents=True, exist_ok=True)
        (daemon / f"hub_{self.port}.json").write_text(json.dumps(
            {"pid": os.getpid(), "httpPort": self.port, "csrfToken": self.token}), encoding="utf-8")
        return self

    def __exit__(self, *exc) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=3)

    def calls(self, method: str) -> list[dict]:
        return [row for row in self.requests if row["method"] == method]


class FakeAgentapi:
    """Stands in for running language_server.exe: records argv/environment, returns made-up JSON."""

    def __init__(self, stdout: str = '{"ok": true}', returncode: int = 0, exc: Exception | None = None) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.exc = exc
        self.calls: list[dict] = []

    def __call__(self, exe, args: list[str], env: dict, timeout: float):
        self.calls.append({"exe": str(exe), "args": list(args), "env": dict(env), "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


class FakeAttachments:
    """The shared attachment folder, made small: stores the meta codex.public_attachment would read."""

    def __init__(self, root: Path) -> None:
        self.data_root = Path(root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.metas: dict[str, dict] = {}

    def _write_meta(self, meta: dict) -> None:
        self.metas[meta["id"]] = dict(meta)

    @staticmethod
    def public_attachment(meta: dict) -> dict:
        return {key: meta[key] for key in ("id", "name", "original_size", "width", "height")} | {
            "url": "/api/codex/image?id=" + meta["id"],
            "thumbnail": "/api/codex/image?thumb=1&id=" + meta["id"]}

    def attachment(self, ident: str, tid: str | None = None) -> dict:
        meta = dict(self.metas[ident])
        meta["path"] = str(self.data_root / ident / "image.png")
        return meta

    def cleanup_drafts(self) -> None:
        pass


