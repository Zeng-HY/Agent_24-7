"""Claude Code desktop: files, UI Automation and its hook."""

from __future__ import annotations

from datetime import datetime
import difflib
import json

import chats

from .base import Agent, NotFound, make_manifest

CLAUDE_STEPS = {
    "Bash": "run",
    "PowerShell": "run",
    "Edit": "edit",
    "Write": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Read": "read",
    "Grep": "read",
    "Glob": "read",
    "WebSearch": "search",
    "WebFetch": "search",
}


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

    def step_of(self, name: str, argument: str = "") -> str:
        return CLAUDE_STEPS.get((name or "").rsplit(".", 1)[-1]) or ""

    def tail_step(self, path, started: int = 0) -> str:
        try:
            lines, _ = chats.read_tail(path, 256 << 10)
        except OSError:
            return ""
        action = ""
        for raw in lines:
            try:
                rec = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            ts = rec.get("timestamp") or ""
            try:
                at = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
            except (ValueError, AttributeError):
                at = 0
            if started and at and at < started:
                continue
            content = (rec.get("message") or {}).get("content")
            blocks = content if isinstance(content, list) else []
            if rec.get("type") == "user" and not rec.get("isSidechain") and not rec.get("isMeta"):
                text = chats._join_text(content).strip()
                if text and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
                    action = ""
            elif rec.get("type") == "assistant":
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        step = self.step_of(str(block.get("name") or ""))
                        if step:
                            action = step
        return action

    def parse_runtime(self, lines: list[bytes]) -> dict:
        out = super().parse_runtime(lines)
        for raw in lines:
            try:
                rec = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            ts, kind = rec.get("timestamp"), rec.get("type")
            if kind == "assistant" and not rec.get("isSidechain") and not rec.get("isMeta"):
                model = (rec.get("message") or {}).get("model")
                if model and model != "<synthetic>":
                    out.update(model=model, model_time=ts)
                    usage = (rec.get("message") or {}).get("usage") or {}
                    parts = [usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
                    if all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in parts) and any(parts):
                        out.update(used_tokens=sum(parts), usage_time=ts, context_state="partial", source="last_request")
            elif kind == "system" and rec.get("subtype") == "compact_boundary":
                after = (rec.get("compactMetadata") or {}).get("postTokens")
                if isinstance(after, int) and not isinstance(after, bool) and after >= 0:
                    out.update(used_tokens=after, usage_time=ts, context_state="partial", source="compact")
                else:
                    out.update(used_tokens=None, usage_time=ts, context_state="waiting")
        return out

    def runtime_complete(self, out: dict) -> bool:
        return bool(out.get("model"))

    def enrich_activity(self, record: dict, messages: list[dict], context: dict, ts: str):
        import activity_records
        blocks = (record.get("message") or {}).get("content")
        blocks = blocks if isinstance(blocks, list) else []
        pending = context.setdefault("activity_tools", {})
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                args = block.get("input") or {}
                name = block.get("name", "")
                if name.endswith("ccd_turn__wrap_up") and str(args.get("ask") or "").strip():
                    context.setdefault("activity_asks", set()).add(block.get("id"))
                if name in ("Edit", "Write", "Read", "Bash", "Grep", "Glob"):
                    m = next((m for m in messages if m["role"] == "tool" and not m.get("source_id") and m["text"].startswith(name + "：")), None)
                    if m is None:
                        continue
                    m["source_id"] = block.get("id")
                    m["tool_status"] = "running"
                    m["detail"] = str(args.get("command") or args.get("file_path") or args.get("pattern") or "")[:16000]
                    if name in ("Edit", "Write") and isinstance(args.get("file_path"), str):
                        m["current_file"] = args["file_path"]
                    m["activity_title"] = {
                        "Edit": "修改文件", "Write": "写入文件", "Read": "读取文件",
                        "Bash": "运行命令", "Grep": "搜索内容", "Glob": "查找文件",
                    }[name]
                    if name in ("Edit", "Write", "Read"):
                        m["activity_title"] += " · " + str(args.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1]
                    m["_changes"] = []
                    if name == "Edit" and all(isinstance(args.get(k), str) for k in ("file_path", "old_string", "new_string")):
                        patch = "\n".join(difflib.unified_diff(
                            args["old_string"].splitlines(), args["new_string"].splitlines(),
                            fromfile=args["file_path"], tofile=args["file_path"], lineterm=""))
                        c = activity_records.change(args["file_path"], patch, scope="fragment")
                        if c:
                            m["_changes"].append(c)
                    if name == "Write":
                        m["change_notice"] = "该记录没有保存修改前内容"
                    pending[block.get("id")] = m
            elif block.get("type") == "tool_result":
                m = pending.get(block.get("tool_use_id"))
                if m:
                    m["tool_status"] = "failed" if block.get("is_error") else "completed"
                    if block.get("is_error"):
                        m["_changes"] = []
                    m["result"] = str(block.get("content") or "")[:16000]
        kind = record.get("type")
        text = ""
        if isinstance(blocks, list):
            text = "\n".join(str(b.get("text") or "") for b in blocks
                             if isinstance(b, dict) and b.get("type") == "text").strip()
        if isinstance((record.get("message") or {}).get("content"), str):
            text = str(record["message"]["content"]).strip()
        current = context.get("activity_turn")
        clocks = context.setdefault("activity_turns", {})
        if kind == "user" and not record.get("isSidechain") and not record.get("isMeta"):
            tool_results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
            asks = context.setdefault("activity_asks", set())
            if any(b.get("tool_use_id") in asks for b in tool_results):
                if current in clocks:
                    clocks[current].update(status="completed", ended_at=activity_records.milliseconds(ts))
            elif text.startswith("[Request interrupted"):
                if current in clocks:
                    clocks[current].update(status="stopped", ended_at=activity_records.milliseconds(ts))
            elif text and not record.get("isCompactSummary"):
                context["activity_turn"] = "user:" + str(record.get("uuid") or ts)
                clocks[context["activity_turn"]] = {"status": "running", "started_at": activity_records.milliseconds(ts), "pauses": []}
        elif kind == "assistant" and current in clocks:
            message = record.get("message") or {}
            if record.get("isApiErrorMessage"):
                clocks[current].update(status="failed", ended_at=activity_records.milliseconds(ts))
            elif message.get("stop_reason") not in (None, "tool_use"):
                clocks[current].update(status="completed", ended_at=activity_records.milliseconds(ts))
        return context.get("activity_turn")

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
