"""Build the fixed action golden bundle on mocked backends (test data only, no real assistants)."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import activity_records
import archives
import chats
import codex_control
import composer_commands
import composer_references
import deepseek_control
import new_conversations
import notify
import remote
import usage_limits

FIXED_NOW = 1767323050.0
FIXED_NOW_MS = 1767323050000
TS1 = "2026-01-02T03:04:05Z"
TS2 = "2026-01-02T03:04:10Z"


def _scrub(obj, root_str: str):
    """Replace temporary directory paths so golden JSON is deterministic across runs."""
    if isinstance(obj, str):
        return (
            obj.replace(root_str.replace("\\", "\\\\"), "<TMP>")
               .replace(root_str, "<TMP>")
               .replace(root_str.replace("\\", "/"), "<TMP>")
        )
    if isinstance(obj, (list, tuple)):
        return [_scrub(v, root_str) for v in obj]
    if isinstance(obj, dict):
        is_skill = obj.get("kind") == "skill"
        out = {}
        for k, v in obj.items():
            if k == "scan_id" and isinstance(v, str) and len(v) == 32:
                out[k] = "<SCAN_ID>"
            elif k == "id" and is_skill and isinstance(v, str) and len(v) == 24:
                out[k] = "<SKILL_ID>"
            elif k == "version" and isinstance(v, str) and ":" in v:
                out[k] = "<VER>"
            else:
                out[k] = _scrub(v, root_str)
        return out
    return obj


def _call_http(server, method: str, path: str, body=None, raw_body: bytes | None = None, headers: dict | None = None):
    handler = object.__new__(remote.Handler)
    sent = []
    sep = "&" if "?" in path else "?"
    handler.path = f"{path}{sep}t=secret"
    hdrs = dict(headers or {})
    if raw_body is not None:
        payload = raw_body
        hdrs.setdefault("Content-Length", str(len(payload)))
    elif body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Length", str(len(payload)))
    else:
        payload = b""
    handler.headers = hdrs
    handler.rfile = io.BytesIO(payload)
    handler.close_connection = False
    handler.server = server
    handler._send = lambda code, data, ctype, extra=None: sent.append((code, data, ctype))
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    code, data, ctype = sent[0]
    parsed = json.loads(data.decode("utf-8")) if ctype.startswith("application/json") else data.decode("utf-8", "replace")
    return {"status": code, "body": parsed}


def _make_codex_db(path: Path, rollout_path: Path):
    con = sqlite3.connect(path)
    con.execute(
        "create table threads(id text, name text, title text, cwd text, rollout_path text, "
        "updated_at_ms integer, updated_at integer, archived integer, archived_at integer, "
        "source text, thread_source text)"
    )
    con.executemany(
        "insert into threads values(?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("c-live", "测试对话一", "", "C:\\demo\\proj", str(rollout_path), 1767323045000, 1767323045, 0, None, "vscode", "user"),
            ("c-arch", "已归档测试", "", "C:\\demo\\proj", str(rollout_path), 1767323000000, 1767323000, 1, 1767323010, "vscode", "user"),
        ],
    )
    con.commit()
    con.close()


def _make_fake_server_cls(calls: list, answers: dict | None = None, refuse: dict | None = None):
    answers = answers or {}
    refuse = refuse or {}

    class FakeServer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            calls.append(["server_close"])

        def call(self, method, params, timeout=40):
            calls.append(["server_call", method, params])
            if method in refuse:
                raise archives.CodexRefused(refuse[method])
            val = answers.get(method, {})
            return val() if callable(val) else val

    return FakeServer


def build() -> dict:
    with tempfile.TemporaryDirectory(prefix="teleply-act-golden-") as td:
        root = Path(td)
        root_str = str(root.resolve())
        home = root / "home"
        proj = root / "proj"
        home.mkdir()
        proj.mkdir()

        # Fake skills for codex & claude
        codex_skill = home / ".codex" / "skills" / "demo-skill" / "SKILL.md"
        codex_skill.parent.mkdir(parents=True)
        codex_skill.write_text("---\nname: demo-skill\ndescription: 示例技能\n---\nBody\n", encoding="utf-8")

        claude_cmd = home / ".claude" / "commands" / "deploy.md"
        claude_cmd.parent.mkdir(parents=True)
        claude_cmd.write_text("---\nname: deploy\ndescription: 发布示例\n---\nRun\n", encoding="utf-8")

        # Fake rollout + codex db + claude transcript
        rollout = root / "rollout.jsonl"
        rollout.write_text(
            json.dumps({
                "timestamp": TS1,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "rate_limits": {
                        "limit_id": "codex",
                        "plan_type": "pro",
                        "primary": {"used_percent": 42.0, "window_minutes": 300, "resets_at": 1767340000},
                        "secondary": {"used_percent": 15.0, "window_minutes": 10080, "resets_at": 1767900000},
                    },
                },
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        codex_db = root / "state_5.sqlite"
        _make_codex_db(codex_db, rollout)

        claude_log = root / "claude.jsonl"
        claude_log.write_text(
            json.dumps({
                "type": "assistant",
                "uuid": "a-1",
                "timestamp": TS1,
                "message": {
                    "role": "assistant",
                    "model": "claude-test",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "content": [{"type": "text", "text": "收到"}],
                },
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # External call recorder
        calls: list = []

        # Fake Codex Bridge
        attachments_store = {
            "att-claude-1": {"id": "att-claude-1", "app": "claude", "thread": "cl-1", "original_size": 128, "path": str(root / "img.png"), "name": "pic.png"},
        }

        class FakePipe:
            def broadcast(self, method, version, params):
                calls.append(["codex_pipe_broadcast", method, version, params])

        class FakeCodex:
            def __init__(self):
                self.data_root = root / "codex_att"
                self.data_root.mkdir()
                self._p = FakePipe()

            def _pipe(self):
                return self._p

            def status(self, tid, fresh=False):
                calls.append(["codex.status", tid, fresh])
                return {"available": True, "running": True, "status": "running", "turn_id": "turn-1", "questions": []}

            def receipt(self, tid, rid):
                calls.append(["codex.receipt", tid, rid])
                if rid == "req-err":
                    return {"state": "rejected", "request_id": rid}
                return {"state": "accepted", "request_id": rid, "id": tid}

            def send(self, body):
                calls.append(["codex.send", body])
                if body.get("id") == "bad":
                    err = codex_control.ControlError("桌面未接管", 409, code="not_taken")
                    err.not_submitted = True
                    raise err
                return {"ok": True, "accepted": True, "request_id": body.get("request_id", ""), "text": "已交给 Codex"}

            def stop_turn(self, body):
                calls.append(["codex.stop_turn", body])
                if body.get("id") == "bad":
                    raise codex_control.ControlError("未在运行", 409)
                return {"ok": True, "text": "已请求停止"}

            def answer(self, body):
                calls.append(["codex.answer", body])
                return {"ok": True, "text": "已提交回答"}

            def queue_action(self, body):
                calls.append(["codex.queue_action", body])
                return {"ok": True, "action": body.get("action"), "message_id": body.get("message_id")}

            def remove_attachment(self, tid, ident):
                calls.append(["codex.remove_attachment", tid, ident])
                return {"ok": True, "removed": ident}

            def upload(self, tid, name, raw, app="codex", *, new_draft=False):
                calls.append(["codex.upload", tid, name, len(raw), app, new_draft])
                return {"id": "att-up-1", "name": name, "size": len(raw), "app": app, "thread": tid}

            def attachment(self, ident, tid=None):
                calls.append(["codex.attachment", ident, tid])
                if ident not in attachments_store:
                    raise codex_control.ControlError("图片不存在", 404)
                return dict(attachments_store[ident])

            def _begin(self, rid, tid, body):
                calls.append(["codex._begin", rid, tid])
                return None

            def _write_meta(self, meta):
                calls.append(["codex._write_meta", meta["id"], meta.get("used")])

            def _finish(self, rid, result):
                calls.append(["codex._finish", rid, result.get("ok")])

            def message_images(self, tid):
                calls.append(["codex.message_images", tid])
                return []

            def confirm_open(self, tid):
                calls.append(["codex.confirm_open", tid])
                if tid == "fail-open":
                    raise codex_control.ControlError("Codex 窗口未接管", 400, code="open_timeout")
                return {"ok": True, "text": "已打开 Codex 对话"}

            def delivery_locations(self, tid, ids):
                calls.append(["codex.delivery_locations", tid, ids])
                return {ids[0]: {"client_id": "cid-1", "state": "accepted"}} if ids else {}

        # Fake Claude Controller
        class FakeClaudeSessionActions:
            def change(self, tid, archived):
                calls.append(["claude.session_actions.change", tid, archived])

        class FakeClaude:
            def __init__(self):
                self.session_actions = FakeClaudeSessionActions()

            def state(self, tid, fresh=False):
                calls.append(["claude.state", tid, fresh])
                return {"available": True, "running": True, "stop_token": "tok-stop", "actions": []}

            def menu(self, tid, kind):
                calls.append(["claude.menu", tid, kind])
                return {"kind": kind, "items": [{"name": "Sonnet", "selected": True}]}

            def catalog(self, tid, fresh):
                calls.append(["claude.catalog", tid, fresh])
                return {"model": [{"name": "Sonnet", "selected": True}]}

            def select_setting(self, tid, kind, name, value, expected_model):
                calls.append(["claude.select_setting", tid, kind, name, value, expected_model])
                return {"ok": True, "kind": kind, "name": name}

            def choose(self, tid, token, value):
                calls.append(["claude.choose", tid, token, value])
                if token == "expired":
                    raise chats.ChatError("选项已过期，请重新打开面板")
                return {"ok": True, "text": "已操作"}

            def close_menu(self, tid):
                calls.append(["claude.close_menu", tid])
                return {"ok": True}

            def next_step(self, tid, tool_id, index, label):
                calls.append(["claude.next_step", tid, tool_id, index, label])
                return {"ok": True, "text": f"已在电脑上点了「{label}」"}

            def task_step(self, tid, title, button):
                calls.append(["claude.task_step", tid, title, button])
                return {"ok": True, "text": "已在电脑上开始了"}

            def send_steer(self, tid, text, expected_turn, request_id):
                calls.append(["claude.send_steer", tid, text, expected_turn, request_id])
                return {"ok": True, "steer_requested": True, "text": "已提交补充指令并请求立即读取"}

            def new_options(self):
                calls.append(["claude.new_options"])
                return {"models": [{"id": "Sonnet", "label": "Sonnet", "efforts": [{"id": 1, "label": "高"}], "default_effort": 1}], "note": ""}

        # Fake DeepSeek Bridge
        class FakeDeepSeekClient:
            def call(self, method, args):
                calls.append(["deepseek.client.call", method, args])
                if method == "session/list":
                    return {"items": [{"sessionId": "ds-arch", "cwd": str(proj), "updatedAt": 1767323020000,
                                       "projections": {"values": {"title": "归档的深求"}}}]}
                if method == "workspace/archiveSession" and args["request"]["sessionId"] == "ds-busy":
                    err = deepseek_control.DeepSeekError("busy", 409)
                    err.code = "workspace/session-active"
                    raise err
                return {"ok": True}

        class FakeDeepSeekEvents:
            def start(self):
                calls.append(["deepseek.events.start"])

            def answer(self, tid, event_id, choice, kind):
                calls.append(["deepseek.events.answer", tid, event_id, choice, kind])
                return {"ok": True, "choice": choice}

            def for_session(self, sid):
                return []

        class FakeDeepSeek:
            def __init__(self):
                self.client = FakeDeepSeekClient()
                self.events = FakeDeepSeekEvents()
                self.cache = (0, None)

            def find(self, sid):
                calls.append(["deepseek.find", sid])
                if sid == "missing":
                    raise deepseek_control.DeepSeekError("找不到这个 DeepSeek 对话", 404)
                return {"app": "deepseek", "id": sid, "title": "深求测试", "cwd": str(proj)}

            def state(self, sid):
                calls.append(["deepseek.state", sid])
                return {"available": True, "running": True, "turn_id": "ds-turn-1", "queued": []}

            def models(self):
                calls.append(["deepseek.models"])
                return {
                    "routableProviders": ["deepseek"],
                    "groups": [{
                        "id": "deepseek",
                        "name": "DeepSeek",
                        "models": [{"id": "chat", "name": "DeepSeek Chat", "reasoning": {"efforts": [{"id": "high", "name": "High"}], "defaultEffort": "high"}}],
                    }],
                }

            def receipt(self, rid):
                calls.append(["deepseek.receipt", rid])
                return {"state": "accepted", "id": "ds-1", "request_id": rid}

            def permissions(self, sid=""):
                calls.append(["deepseek.permissions", sid])
                return {"current": "default", "options": [
                    {"value": "default", "label": "默认", "confirm": False},
                    {"value": "full", "label": "完全权限", "confirm": True},
                ]}

            def send(self, body):
                calls.append(["deepseek.send", body])
                return {"accepted": True, "text": "已交给 DeepSeek", "request_id": body.get("request_id", "")}

            def set_permission(self, sid, preset, confirmed):
                calls.append(["deepseek.set_permission", sid, preset, confirmed])
                return {"ok": True, "preset": preset}

            def queue_action(self, sid, item_id, action):
                calls.append(["deepseek.queue_action", sid, item_id, action])
                return {"ok": True, "item_id": item_id, "action": action}

            def stop(self, sid, expected_turn):
                calls.append(["deepseek.stop", sid, expected_turn])
                if sid == "bad":
                    raise deepseek_control.DeepSeekError("当前轮次已变化，请刷新后再停止", 409)
                return {"ok": True}

            def select_model(self, sid, settings):
                calls.append(["deepseek.select_model", sid, settings])
                return {"ok": True, "settings": settings}

            def create(self, body):
                calls.append(["deepseek.create", body])
                return {"accepted": True, "id": "ds-new-1", "app": "deepseek", "title": "新对话"}

            def answer(self, body):
                calls.append(["deepseek.answer", body])
                return {"ok": True, "answered": True}

            def commands(self, sid):
                calls.append(["deepseek.commands", sid])
                return [
                    {"name": "compact", "description": "Compact context", "hint": ""},
                    {"name": "goal", "description": "Set goal", "hint": "target"},
                    {"name": "export", "description": "Export zip", "hint": ""},
                ]

        # Fake Desktop
        class FakeDesktop:
            auto_error = ""

            def run(self, fn, *args, timeout=None):
                calls.append(["desktop.run", getattr(fn, "__name__", str(fn)), timeout])
                return fn(*args)

            def send(self, app, tid, text, images=None, replace=None):
                calls.append(["desktop.send", app, tid, text, [i["id"] for i in (images or [])], replace])
                return {"ok": True, "pressed": True, "offset": 42, "running": False, "text": "已提交，等待对话记录确认"}

            def open(self, app, tid):
                calls.append(["desktop.open", app, tid])
                return {"ok": True, "text": f"电脑上已打开「{tid}」"}

            def press_enter(self, app, tid):
                calls.append(["desktop.press_enter", app, tid])
                return {"ok": True, "text": "按了回车"}

            def claude_press(self, tid, option, text, enter):
                calls.append(["desktop.claude_press", tid, option, text, enter])
                return {"ok": True, "text": "已点按钮"}

            def claude_options(self, tid, open_first):
                calls.append(["desktop.claude_options", tid, open_first])
                return {"options": [{"name": "Allow", "type": "ButtonControl"}]}

            def _need_auto(self):
                return SimpleNamespace(ControlFromHandle=lambda hwnd: "root")

            def _find(self, scope, kind, name=None):
                return [SimpleNamespace(Name="Usage: 35% of 5-hour limit, Resets at 12:20 PM")]

        # Fake History
        conv_items = {
            ("codex", "c-live"): {"app": "codex", "id": "c-live", "title": "测试对话一", "folder": "proj", "cwd": str(proj), "path": str(rollout), "updated": 1767323045000},
            ("claude", "cl-1"): {"app": "claude", "id": "cl-1", "title": "Claude 测试", "folder": "proj", "cwd": str(proj), "updated": 1767323046000},
            ("deepseek", "ds-1"): {"app": "deepseek", "id": "ds-1", "title": "深求测试", "folder": "proj", "cwd": str(proj), "updated": 1767323047000},
        }

        class FakeHistory:
            def catalog(self):
                return list(conv_items.values())

            def invalidate(self):
                calls.append(["history.invalidate"])

            def conversation(self, app, tid, n=30):
                return {"messages": [
                    {"id": "m1", "role": "user", "time": TS1, "text": "问个问题"},
                    {"id": "m2", "role": "assistant", "time": TS2, "text": "这是公开回答"},
                ]}

            def resolve_requests(self, app, tid, ids, aliases):
                calls.append(["history.resolve_requests", app, tid, ids, aliases])
                return {"items": [{"request_id": rid, "status": "recorded"} for rid in ids]}

        # Fake Files
        class FakeFiles:
            def picture(self, ref):
                calls.append(["files.picture", ref])
                return "from_pc.png", b"\x89PNG\r\n\x1a\nfake"

            def remove_upload(self, upload):
                calls.append(["files.remove_upload", upload])
                return {"ok": True}

        fake_codex = FakeCodex()
        fake_claude = FakeClaude()
        fake_deepseek = FakeDeepSeek()
        fake_desktop = FakeDesktop()
        fake_history = FakeHistory()
        fake_files = FakeFiles()
        fake_refs = composer_references.References(fake_history, home=home, files=fake_files)
        # Keep skill/command discovery strictly inside the temporary sandbox so parent directories
        # (e.g. a worktree's .claude or the user's real home directory) never leak into golden output.
        _orig_roots = fake_refs._roots
        _sandbox_root = root.resolve()

        def _sandboxed_roots(app, cwd, warnings):
            roots, disabled = _orig_roots(app, cwd, warnings)
            kept = []
            for entry in roots:
                try:
                    Path(entry[0]).resolve().relative_to(_sandbox_root)
                except ValueError:
                    continue
                kept.append(entry)
            return kept, disabled

        fake_refs._roots = _sandboxed_roots

        archive_server_cls = _make_fake_server_cls(calls)
        archive_svc = archives.Archives(
            fake_codex, fake_history, log=lambda t: calls.append(["archive.log", t]),
            server=archive_server_cls, deepseek=fake_deepseek,
            apps=lambda: ["codex", "claude", "deepseek"], claude=fake_claude,
        )

        usage_server_cls = _make_fake_server_cls(
            calls,
            answers={
                "account/rateLimits/read": {
                    "rateLimitsByLimitId": {
                        "codex": {
                            "limitId": "codex",
                            "planType": "pro",
                            "primary": {"usedPercent": 50.0, "windowDurationMins": 300, "resetsAt": 1767340000},
                            "secondary": None,
                            "rateLimitReachedType": None,
                        }
                    },
                    "rateLimitResetCredits": {"availableCount": 1, "credits": [
                        {"id": "cred-1", "title": "Full reset", "description": "reset", "grantedAt": 1767300000, "expiresAt": 1767900000, "status": "available"}
                    ]},
                    "ordinaryUsageAllowed": True,
                },
                "account/rateLimitResetCredit/consume": {"outcome": "reset"},
            },
        )
        usage_svc = usage_limits.Usage(
            fake_desktop, log=lambda t: calls.append(["usage.log", t]),
            apps=lambda: ["codex", "claude"], server_factory=usage_server_cls,
            data_dir=root,
        )

        new_svc = new_conversations.NewConversations(fake_history, fake_refs, fake_codex, fake_desktop, root=root / "new_db")
        new_svc.claude = fake_claude

        server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": ["codex", "claude", "deepseek"], "voice": False},
            cfg={"token": "secret"},
            log=SimpleNamespace(write=lambda t: calls.append(["server.log", t])),
            desktop=fake_desktop,
            codex=fake_codex,
            claude=fake_claude,
            claude_reads=[],
            deepseek=fake_deepseek,
            history=fake_history,
            files=fake_files,
            references=fake_refs,
            archives=archive_svc,
            usage=usage_svc,
            new_chats=new_svc,
            tasks=SimpleNamespace(observe=lambda tid, data: calls.append(["tasks.observe", tid, data.get("status")])),
        )

        out: dict = {}

        def record(name, fn):
            calls.clear()
            res = fn()
            out[name] = {"result": res, "calls": list(calls)}

        with ExitStack() as stack:
            stack.enter_context(patch("time.time", return_value=FIXED_NOW))
            stack.enter_context(patch("chats.codex_db", return_value=codex_db))
            stack.enter_context(patch("chats.HOME", home))
            stack.enter_context(patch("chats.CODEX_HOME", home / ".codex"))
            stack.enter_context(patch("new_conversations.CODEX_PROJECTLESS", home / "Documents" / "Codex"))
            stack.enter_context(patch("chats.find", side_effect=lambda app, tid: conv_items[(app, tid)] if (app, tid) in conv_items else (_ for _ in ()).throw(chats.ChatError(f"找不到 {app}:{tid}"))))
            stack.enter_context(patch("chats.claude_transcript", return_value=claude_log))
            stack.enter_context(patch("chats.claude_sessions", return_value=[conv_items[("claude", "cl-1")]]))
            stack.enter_context(patch("chats.summary", return_value={"status": "idle", "preview": "ok"}))
            stack.enter_context(patch("chats.app_window", return_value=999))
            stack.enter_context(patch("usage_limits.win32gui.IsIconic", return_value=False))
            stack.enter_context(patch("deepseek_control.bridge", return_value=fake_deepseek))
            stack.enter_context(patch("deepseek_control.workspaces", return_value=[{"id": "ws-1", "name": "工作区一", "path": str(proj)}]))
            stack.enter_context(patch("deepseek_control.workspace_for", return_value={"id": "ws-1", "name": "工作区一", "path": str(proj)}))
            stack.enter_context(patch("deepseek_control.workspace_meta", return_value={"archivedSessionIds": ["ds-arch"]}))
            stack.enter_context(patch("codex_control.catalog", return_value={"models": [{"id": "gpt-test", "name": "GPT Test", "efforts": ["low", "high"], "default_effort": "high"}]}))
            stack.enter_context(patch("remote.os.startfile", side_effect=lambda target: calls.append(["os.startfile", target])))
            stack.enter_context(patch("chats.Desktop.check", side_effect=lambda app, tid, offset, text: (calls.append(["Desktop.check", app, tid, offset, text]), {"delivered": True, "queued": False, "stage": "received"})[1]))
            stack.enter_context(patch("new_conversations.threading.Thread", side_effect=lambda *a, **kw: SimpleNamespace(start=lambda: calls.append(["new_chat_thread.start", kw.get("args")]))))
            stack.enter_context(patch("claude_archive.archived", return_value=[{"app": "claude", "id": "cl-arch", "title": "已归档 Claude", "archived": True, "can_delete": False}]))

            # 1. State & receipt
            record("codex_state", lambda: _call_http(server, "GET", "/api/codex/state?id=c-live&fresh=1"))
            record("codex_receipt", lambda: _call_http(server, "GET", "/api/codex/receipt?id=c-live&request_id=req-1"))
            record("claude_state", lambda: _call_http(server, "GET", "/api/claude/state?id=cl-1&fresh=1"))
            record("deepseek_state", lambda: _call_http(server, "GET", "/api/deepseek/state?id=ds-1"))
            record("deepseek_receipt", lambda: _call_http(server, "GET", "/api/deepseek/receipt?request_id=req-ds-1"))

            # 2. Send, steer, queue, check, enter
            record("codex_send_ok", lambda: _call_http(server, "POST", "/api/codex/send", {"id": "c-live", "text": "你好", "request_id": "req-1"}))
            record("codex_send_err", lambda: _call_http(server, "POST", "/api/codex/send", {"id": "bad", "text": "你好", "request_id": "req-err"}))
            record("codex_queue_action", lambda: _call_http(server, "POST", "/api/codex/queue-action", {"id": "c-live", "message_id": "q1", "action": "promote"}))
            record("claude_send_ok", lambda: _call_http(server, "POST", "/api/chat/send", {"app": "claude", "id": "cl-1", "text": "看看这个", "replace_draft": "旧草稿"}))
            record("claude_send_with_image", lambda: _call_http(server, "POST", "/api/chat/send", {"app": "claude", "id": "cl-1", "text": "", "attachments": ["att-claude-1"], "request_id": "req-img-1"}))
            record("claude_steer", lambda: _call_http(server, "POST", "/api/claude/steer", {"id": "cl-1", "text": "补充一下", "expected_turn": "anc-1", "request_id": "req-steer-123456"}))
            record("chat_send_codex_refused", lambda: _call_http(server, "POST", "/api/chat/send", {"app": "codex", "id": "c-live", "text": "hi"}))
            record("chat_send_deepseek_refused", lambda: _call_http(server, "POST", "/api/chat/send", {"app": "deepseek", "id": "ds-1", "text": "hi"}))
            record("chat_check_claude", lambda: _call_http(server, "POST", "/api/chat/check", {"app": "claude", "id": "cl-1", "offset": 10, "text": "hi"}))
            record("chat_enter_claude", lambda: _call_http(server, "POST", "/api/chat/enter", {"app": "claude", "id": "cl-1"}))
            record("deepseek_send_ok", lambda: _call_http(server, "POST", "/api/deepseek/send", {"id": "ds-1", "text": "发深求", "intent": "queue", "request_id": "req-ds-2"}))
            record("deepseek_queue", lambda: _call_http(server, "POST", "/api/deepseek/queue", {"id": "ds-1", "item_id": "item-1", "action": "steer"}))

            # 3. Stop
            record("codex_stop_ok", lambda: _call_http(server, "POST", "/api/codex/stop", {"id": "c-live", "turn_id": "turn-1"}))
            record("codex_stop_err", lambda: _call_http(server, "POST", "/api/codex/stop", {"id": "bad", "turn_id": "turn-1"}))
            record("claude_stop_choose", lambda: _call_http(server, "POST", "/api/claude/choose", {"id": "cl-1", "token": "tok-stop"}))
            record("claude_press", lambda: _call_http(server, "POST", "/api/chat/press", {"id": "cl-1", "option": {"name": "Stop"}, "text": "", "enter": False}))
            record("deepseek_stop_ok", lambda: _call_http(server, "POST", "/api/deepseek/stop", {"id": "ds-1", "expected_turn": "ds-turn-1"}))
            record("deepseek_stop_err", lambda: _call_http(server, "POST", "/api/deepseek/stop", {"id": "bad", "expected_turn": "ds-turn-1"}))

            # 4. Approve & Answer & Settings
            record("codex_answer", lambda: _call_http(server, "POST", "/api/codex/answer", {"id": "c-live", "request_id": "q-1", "answers": {"a": "yes"}}))
            record("claude_choose_expired", lambda: _call_http(server, "POST", "/api/claude/choose", {"id": "cl-1", "token": "expired"}))
            record("claude_next", lambda: _call_http(server, "POST", "/api/claude/next", {"id": "cl-1", "tool_id": "t1", "index": 0, "label": "继续"}))
            record("claude_task", lambda: _call_http(server, "POST", "/api/claude/task", {"id": "cl-1", "title": "修测试", "button": "start"}))
            record("claude_setting", lambda: _call_http(server, "POST", "/api/claude/setting", {"id": "cl-1", "kind": "model", "name": "Sonnet"}))
            record("claude_menu", lambda: _call_http(server, "POST", "/api/claude/menu", {"id": "cl-1", "kind": "model"}))
            record("claude_options", lambda: _call_http(server, "GET", "/api/chat/options?id=cl-1&open=1"))
            record("deepseek_answer", lambda: _call_http(server, "POST", "/api/deepseek/answer", {"id": "ds-1", "call_id": "call-1", "answers": {"q": "ok"}}))
            record("deepseek_approval", lambda: _call_http(server, "POST", "/api/deepseek/approval", {"id": "ds-1", "event_id": "ev-1", "choice": "allow"}))
            record("deepseek_permission", lambda: _call_http(server, "POST", "/api/deepseek/permission", {"id": "ds-1", "preset": "default", "confirmed": False}))
            record("deepseek_model", lambda: _call_http(server, "POST", "/api/deepseek/model", {"id": "ds-1", "settings": {"provider": "deepseek", "model": "chat"}}))
            record("deepseek_models", lambda: _call_http(server, "GET", "/api/deepseek/models"))
            record("deepseek_permissions", lambda: _call_http(server, "GET", "/api/deepseek/permissions?id=ds-1"))

            # 5. Open on computer
            record("open_codex_ok", lambda: _call_http(server, "POST", "/api/chat/open", {"app": "codex", "id": "c-live"}))
            record("open_codex_err", lambda: _call_http(server, "POST", "/api/chat/open", {"app": "codex", "id": "fail-open"}))
            record("open_claude_ok", lambda: _call_http(server, "POST", "/api/chat/open", {"app": "claude", "id": "cl-1"}))
            record("open_deepseek_ok", lambda: _call_http(server, "POST", "/api/chat/open", {"app": "deepseek", "id": "ds-1"}))
            record("open_deepseek_err", lambda: _call_http(server, "POST", "/api/chat/open", {"app": "deepseek", "id": "missing"}))

            # 6. New conversations & create/state
            record("new_folders_all", lambda: _call_http(server, "GET", "/api/chat/folders"))
            record("new_folders_deepseek", lambda: _call_http(server, "GET", "/api/chat/folders?app=deepseek"))
            record("new_options_codex", lambda: _call_http(server, "GET", "/api/chat/new/options?app=codex"))
            record("new_options_claude", lambda: _call_http(server, "GET", "/api/chat/new/options?app=claude"))
            record("new_options_deepseek", lambda: _call_http(server, "GET", "/api/chat/new/options?app=deepseek"))
            record("new_options_unknown", lambda: _call_http(server, "GET", "/api/chat/new/options?app=other"))

            with patch("new_conversations.uuid.uuid4", side_effect=[
                SimpleNamespace(hex="a" * 32),
                SimpleNamespace(hex="b" * 32),
                SimpleNamespace(hex="c" * 32),
                SimpleNamespace(hex="d" * 32),
            ]):
                draft_codex = _call_http(server, "POST", "/api/chat/new/draft")["body"]["request_id"]
                draft_claude = _call_http(server, "POST", "/api/chat/new/draft")["body"]["request_id"]
                draft_ds = _call_http(server, "POST", "/api/chat/new/draft")["body"]["request_id"]
                draft_err = _call_http(server, "POST", "/api/chat/new/draft")["body"]["request_id"]

            record("new_submit_codex", lambda: _call_http(server, "POST", "/api/chat/new", {
                "request_id": draft_codex, "app": "codex", "folder": str(proj), "text": "新建 Codex",
                "settings": {"model": "gpt-test", "effort": "high"}, "attachments": [], "references": [],
            }))
            record("new_state_codex", lambda: _call_http(server, "GET", f"/api/chat/new/state?request_id={draft_codex}"))
            out["new_state_codex"]["result"]["body"]["timing"] = "<TIMING>"

            record("new_submit_claude", lambda: _call_http(server, "POST", "/api/chat/new", {
                "request_id": draft_claude, "app": "claude", "folder": str(proj), "text": "新建 Claude",
                "settings": {"model": "Sonnet", "effort": 1}, "attachments": [], "references": [],
            }))
            record("new_submit_deepseek", lambda: _call_http(server, "POST", "/api/chat/new", {
                "request_id": draft_ds, "app": "deepseek", "folder": str(proj), "text": "新建深求",
                "permission": "default", "attachments": [], "references": [],
            }))
            record("new_submit_deepseek_projectless_err", lambda: _call_http(server, "POST", "/api/chat/new", {
                "request_id": draft_err, "app": "deepseek", "projectless": True, "text": "无项目",
                "attachments": [], "references": [],
            }))
            record("new_submit_codex_perm_err", lambda: _call_http(server, "POST", "/api/chat/new", {
                "request_id": draft_err, "app": "codex", "folder": str(proj), "permission": "default", "text": "权限",
                "attachments": [], "references": [],
            }))
            record("new_retry_unconfirmed_err", lambda: _call_http(server, "POST", "/api/chat/new/retry", {"request_id": draft_codex}))

            # 7. Upload
            record("upload_codex", lambda: _call_http(server, "POST", "/api/codex/upload?id=c-live&name=shot.png&app=codex", raw_body=b"PNGDATA"))
            record("upload_claude", lambda: _call_http(server, "POST", "/api/codex/upload?id=cl-1&name=shot.png&app=claude", raw_body=b"PNGDATA"))
            record("upload_draft", lambda: _call_http(server, "POST", f"/api/codex/upload?draft={draft_err}&name=shot.png", raw_body=b"PNGDATA"))
            record("upload_too_big", lambda: _call_http(server, "POST", "/api/codex/upload?id=c-live&name=big.png", raw_body=b"", headers={"Content-Length": str((20 << 20) + 1)}))
            record("remove_attachment", lambda: _call_http(server, "POST", "/api/codex/remove-attachment", {"id": "c-live", "attachment": "att-up-1"}))
            record("files_image_chat", lambda: _call_http(server, "POST", "/api/files/image", {"app": "codex", "id": "c-live", "ref": {"path": "x"}}))

            # 8. Archive, Restore, Delete
            record("archived_list", lambda: _call_http(server, "GET", "/api/chat/archived"))
            record("archive_codex", lambda: _call_http(server, "POST", "/api/chat/archive", {"app": "codex", "id": "c-live"}))
            record("archive_claude", lambda: _call_http(server, "POST", "/api/chat/archive", {"app": "claude", "id": "cl-1"}))
            record("archive_deepseek", lambda: _call_http(server, "POST", "/api/chat/archive", {"app": "deepseek", "id": "ds-1"}))
            record("archive_deepseek_busy_err", lambda: _call_http(server, "POST", "/api/chat/archive", {"app": "deepseek", "id": "ds-busy"}))
            record("archive_unknown_err", lambda: _call_http(server, "POST", "/api/chat/archive", {"app": "other", "id": "x"}))
            record("unarchive_codex", lambda: _call_http(server, "POST", "/api/chat/unarchive", {"app": "codex", "id": "c-arch"}))
            record("unarchive_codex_missing", lambda: _call_http(server, "POST", "/api/chat/unarchive", {"app": "codex", "id": "c-missing"}))
            record("unarchive_claude", lambda: _call_http(server, "POST", "/api/chat/unarchive", {"app": "claude", "id": "cl-1"}))
            record("unarchive_deepseek", lambda: _call_http(server, "POST", "/api/chat/unarchive", {"app": "deepseek", "id": "ds-arch"}))
            record("delete_unconfirmed_err", lambda: _call_http(server, "POST", "/api/chat/delete", {"items": [{"app": "codex", "id": "c-arch"}]}))
            record("delete_confirmed", lambda: _call_http(server, "POST", "/api/chat/delete", {
                "confirmed": True,
                "items": [
                    {"app": "codex", "id": "c-arch"},
                    {"app": "codex", "id": "c-live"},
                    {"app": "deepseek", "id": "ds-arch"},
                    {"app": "codex", "id": "c-gone"},
                ],
            }))

            # 9. Slash commands
            record("commands_codex", lambda: _call_http(server, "GET", "/api/composer/commands?app=codex&id=c-live"))
            record("commands_claude", lambda: _call_http(server, "GET", "/api/composer/commands?app=claude&id=cl-1"))
            record("commands_deepseek", lambda: _call_http(server, "GET", "/api/composer/commands?app=deepseek&id=ds-1"))
            record("commands_unknown_err", lambda: _call_http(server, "GET", "/api/composer/commands?app=other&id=x"))

            # 10. References & Resolve
            record("refs_codex_skill", lambda: _call_http(server, "GET", "/api/composer/references?app=codex&id=c-live&kind=skill"))
            record("refs_claude_skill", lambda: _call_http(server, "GET", "/api/composer/references?app=claude&id=cl-1&kind=skill"))
            record("refs_deepseek_skill", lambda: _call_http(server, "GET", "/api/composer/references?app=deepseek&id=ds-1&kind=skill"))
            codex_skill_row = fake_refs.skills("codex", "c-live")[0]
            claude_skill_row = fake_refs.skills("claude", "cl-1")[0]
            record("refs_compose_codex", lambda: fake_refs.compose("codex", "c-live", "请处理", [codex_skill_row]))
            record("refs_compose_claude", lambda: fake_refs.compose("claude", "cl-1", "请处理", [claude_skill_row]))
            record("refs_compose_chat", lambda: fake_refs.compose("deepseek", "ds-1", "参考一下", [{"kind": "chat", "app": "codex", "id": "c-live"}]))
            record("resolve_codex", lambda: _call_http(server, "POST", "/api/chat/resolve", {"app": "codex", "id": "c-live", "request_ids": ["req-1"]}))
            record("resolve_claude", lambda: _call_http(server, "POST", "/api/chat/resolve", {"app": "claude", "id": "cl-1", "request_ids": ["req-2"]}))
            record("resolve_unknown_err", lambda: _call_http(server, "POST", "/api/chat/resolve", {"app": "other", "id": "x", "request_ids": ["r1"]}))

            # 11. Usage & Reset
            record("usage_records", lambda: _call_http(server, "GET", "/api/usage"))
            record("usage_live", lambda: _call_http(server, "GET", "/api/usage?live=1"))
            record("usage_reset_unconfirmed", lambda: _call_http(server, "POST", "/api/usage/codex-reset", {"request_id": "reset-req-0001"}))
            record("usage_reset_confirmed", lambda: _call_http(server, "POST", "/api/usage/codex-reset", {
                "confirmed": True, "request_id": "reset-req-0001", "credit_id": "cred-1",
            }))
            reset_file = root / "attachments" / "codex-resets.jsonl"
            out["usage_reset_file"] = [json.loads(line) for line in reset_file.read_text(encoding="utf-8").splitlines()]

            # 12. Notify (turn_end, record_step, scan_lines, Notifier.look -> Bark/ntfy/relay payloads)
            codex_notify_lines = [
                json.dumps({"timestamp": TS1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t-n1"}}).encode(),
                json.dumps({"timestamp": TS1, "type": "response_item", "payload": {"type": "function_call", "name": "exec", "input": "*** Begin Patch"}}).encode(),
                json.dumps({"timestamp": TS2, "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t-n1", "last_agent_message": "已经完成。"}}).encode(),
            ]
            claude_notify_lines = [
                json.dumps({"type": "user", "uuid": "u-n1", "timestamp": TS1, "message": {"content": "改一下"}}).encode(),
                json.dumps({"type": "assistant", "uuid": "a-n1", "timestamp": TS1, "message": {"id": "m-n1", "stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "Edit"}]}}).encode(),
                json.dumps({"type": "assistant", "uuid": "a-n2", "timestamp": TS2, "message": {"id": "m-n2", "stop_reason": "end_turn", "content": [{"type": "text", "text": "改好了。"}]}}).encode(),
            ]
            out["notify_helpers"] = {
                "turn_end_codex": notify.turn_end("codex", codex_notify_lines),
                "turn_end_claude": notify.turn_end("claude", claude_notify_lines),
                "steps": {
                    "codex_exec_run": notify.record_step("codex", "exec", "pytest"),
                    "codex_exec_edit": notify.record_step("codex", "exec", "*** Begin Patch"),
                    "codex_exec_search": notify.record_step("codex", "exec", "web_search query"),
                    "claude_edit": notify.record_step("claude", "Edit"),
                    "deepseek_read": notify.record_step("deepseek", "tools.read_file"),
                },
            }

            codex_watch_file = root / "watch_codex.jsonl"
            codex_watch_file.write_bytes(b"\n".join(codex_notify_lines[:2]) + b"\n")
            bark_sent = []
            notify_cfg = {"bark": {"server": "https://api.day.app", "key": "FakeKey123456"}, "ntfy": True}
            notifier = notify.Notifier(
                notify_cfg, "测试电脑", lambda t: None, lambda: None,
                clock=lambda: 1767323040.0,  # before TS2 (2026-01-02T03:04:10Z = 1767323050)
                sender=lambda addr, title, body, **kw: bark_sent.append({"title": title, "body": body, **kw}),
                page_url=lambda: "https://pc.example.ts.net/",
            )
            notifier.relay.listening = 1
            with patch.object(notify.chats, "_codex_rows", return_value=[{"app": "codex", "id": "c-n1", "title": "通知测试", "path": str(codex_watch_file)}]), \
                 patch.object(notify.chats, "claude_sessions", return_value=[]), \
                 patch.object(notify.chats, "conv_path", side_effect=lambda it: Path(it["path"])), \
                 patch("deepseek_control.catalog", return_value=[]):
                notifier.look()
                with codex_watch_file.open("ab") as f:
                    f.write(codex_notify_lines[2] + b"\n")
                notifier.clock = lambda: 1767323055.0
                notifier.look()
            out["notify_delivery"] = {
                "bark": bark_sent,
                "ntfy": [{"title": e.get("title"), "message": e.get("message"), "click": e.get("click")} for _, e in notifier.feed.messages],
                "relay_kept": [{k: v for k, v in e.items() if k not in ("id", "time")} for _, e in notifier.relay.messages],
                "relay_fresh": [{k: v for k, v in e.items() if k not in ("id", "time")} for _, e in notifier.relay.fresh],
            }

            # 13. Activity records & residual chats read helpers
            codex_ctx = {}
            codex_act_1 = activity_records.enrich("codex", json.dumps({"timestamp": TS1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}}).encode(), [], codex_ctx)
            codex_act_2 = activity_records.enrich("codex", json.dumps({"timestamp": TS2, "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "FileChange", "id": "fc1", "status": "completed", "changes": [{"path": "a.py", "kind": "modify", "diff": "@@ -1 +1 @@\n-x\n+y"}]}}}).encode(), [], codex_ctx)
            claude_ctx = {}
            claude_msg = {"role": "tool", "text": "Edit：a.py", "time": TS1}
            activity_records.enrich("claude", json.dumps({"timestamp": TS1, "type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tu1", "name": "Edit", "input": {"file_path": "a.py", "old_string": "a", "new_string": "b"}}]}}).encode(), [claude_msg], claude_ctx)
            activity_records.enrich("claude", json.dumps({"timestamp": TS2, "type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}]}}).encode(), [], claude_ctx)

            codex_step_file = root / "step_codex.jsonl"
            codex_step_file.write_bytes(b"\n".join(codex_notify_lines[:2]) + b"\n")
            out["residual_read"] = {
                "activity_codex": [activity_records.public_message(m) for m in codex_act_1 + codex_act_2],
                "activity_claude": activity_records.public_message(claude_msg),
                "step_of_codex": chats._step_of("codex", "exec", "apply_patch x"),
                "step_of_claude": chats._step_of("claude", "Grep"),
                "tail_step_codex": chats.tail_step("codex", codex_step_file, 0),
                "runtime_claude": chats.runtime_info("claude", claude_log),
            }

        return _scrub(out, root_str)


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/fixtures/action-golden.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(dest)
