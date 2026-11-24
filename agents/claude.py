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
    has_skills = True
    archive_order = 30
    desktop_process = chats.CLAUDE_PROCESS
    desktop_send_text = "已提交，等待对话记录确认"
    delivery_markers = (b"enqueue", b'"user"', b'"queued_command"')

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
            sources={"catalog": "json-index", "transcript": "jsonl", "control": "hook+ui-automation", "live": "file-poll"},
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

    # -- commands, references, usage, archives

    def commands(self, conv_id: str, *, references=None, deepseek=None) -> list:
        import re
        import composer_commands
        rows = [composer_commands.item(**v) for v in composer_commands.CLAUDE]
        taken = {v["name"] for v in rows}
        if references is not None:
            for skill in references.skills(self.id, conv_id):
                name = skill["name"]
                if name in taken or not re.fullmatch(r"[A-Za-z][\w:.-]{0,63}", name):
                    continue
                taken.add(name)
                rows.append(composer_commands.item(
                    name, detail=composer_commands.one_line(skill.get("description")),
                    scope=skill.get("scope") or "",
                ))
        return rows

    def skill_roots(self, home, cwd: str, read_config, warnings: list, warn_fn) -> tuple[list, set]:
        from pathlib import Path
        roots = [
            (home / ".claude/skills", "个人技能", False),
            (home / ".claude/commands", "个人命令", True),
        ]
        installed = read_config(home / ".claude/plugins/installed_plugins.json").get("plugins", {})
        enabled = read_config(home / ".claude/settings.json").get("enabledPlugins", {})
        if not isinstance(installed, dict) or not isinstance(enabled, dict):
            raise ValueError("Invalid Claude plugin configuration")
        for key, entries in installed.items():
            if enabled.get(key) is not True:
                continue
            if not isinstance(entries, list):
                raise ValueError("Invalid installed plugin entries")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Invalid installed plugin entry")
                if entry.get("scope") == "project" and str(entry.get("projectPath", "")).casefold() != str(cwd).casefold():
                    continue
                if entry.get("installPath"):
                    roots.append((Path(entry["installPath"]) / "skills", key.split("@")[0], False))
        current = Path(cwd) if cwd else None
        for parent in ([current, *current.parents] if current and current.is_absolute() else [])[:12]:
            if parent == home:
                break
            roots.insert(0, (parent / ".claude/skills", "项目技能 · " + parent.name, False))
            roots.insert(0, (parent / ".claude/commands", "项目技能 · " + parent.name, True))
        return roots, set()

    def read_usage(self, svc, live: bool = False) -> dict:
        import usage_limits
        if svc.desktop is None:
            return {"available": False, "reason": "这会儿读不到 Claude 窗口，请稍后再试"}
        try:
            return svc.desktop.run(usage_limits.claude_window, svc.desktop, timeout=10)
        except Exception:
            return {"available": False, "reason": "这会儿读不到 Claude 窗口，请稍后再试"}

    def archive_available(self, svc) -> bool:
        return svc.claude is not None

    def archive_conv(self, svc, conv_id: str) -> None:
        svc.claude.session_actions.change(conv_id, True)

    def unarchive_conv(self, svc, conv_id: str) -> None:
        svc.claude.session_actions.change(conv_id, False)

    def archived_list(self, svc) -> list[dict]:
        import claude_archive
        return claude_archive.archived()

    # -- notify hooks

    @staticmethod
    def _claude_text(content) -> str:
        if isinstance(content, str):
            return content
        return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")

    def notify_turn_end(self, lines: list[bytes]) -> dict | None:
        end = None
        asks = {}
        seen = set()
        for raw in lines:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            uuid = rec.get("uuid")
            if isinstance(uuid, str) and uuid:
                if uuid in seen:
                    continue
                seen.add(uuid)
            kind = rec.get("type")
            if kind not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
                continue
            ts = rec.get("timestamp") or ""
            message = rec.get("message") or {}
            content = message.get("content") if isinstance(message.get("content"), list) else []
            if kind == "user":
                box = next(
                    (asks[b["tool_use_id"]] for b in content
                     if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in asks),
                    None,
                )
                if box:
                    end = {"state": "done", "key": box["tool_id"], "time": ts, "text": box["ask"], "asks": True}
                    continue
                stopped = self._claude_text(message.get("content")).lstrip().startswith("[Request interrupted")
                end = {"state": "stopped" if stopped else "running", "key": rec.get("uuid") or ts, "time": ts, "text": ""}
                continue
            for block in content:
                box = chats._claude_next(block) if isinstance(block, dict) and block.get("type") == "tool_use" else None
                if box and box["ask"]:
                    asks[block.get("id")] = box
            key = message.get("id") or rec.get("uuid") or ts
            if message.get("stop_reason") in (None, "tool_use"):
                end = {"state": "running", "key": key, "time": ts, "text": ""}
                continue
            text = self._claude_text(message.get("content")).strip()
            if end and end["key"] == key and end["state"] in ("done", "failed"):
                end["text"] = (end["text"] + "\n" + text).strip()
            else:
                end = {"state": "failed" if rec.get("isApiErrorMessage") else "done", "key": key, "time": ts, "text": text}
        return end

    def notify_step(self, name: str, argument: str = "") -> str | None:
        return CLAUDE_STEPS.get((name or "").strip())

    def notify_scan_record(self, scan: dict, rec: dict) -> None:
        uuid = rec.get("uuid")
        if isinstance(uuid, str) and uuid:
            seen = scan.setdefault("uuids", set())
            if uuid in seen:
                return
            seen.add(uuid)
        kind = rec.get("type")
        if kind not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
            return
        ts = rec.get("timestamp") or ""
        if ts:
            scan["latest"] = ts
        message = rec.get("message") or {}
        content = message.get("content")
        blocks = content if isinstance(content, list) else []
        if kind == "user":
            tool_results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
            if tool_results:
                asked = any(b.get("tool_use_id") in scan["asks"] for b in tool_results)
                if asked and scan["state"] == "running":
                    scan.update(state="done", ended=ts, action="")
                return
            text = self._claude_text(content).strip()
            if not text or rec.get("isCompactSummary"):
                return
            if chats._COMMAND_OUTPUT.search(text) and not chats.clean_claude_user(text):
                if scan["state"] == "running":
                    scan.update(state="stopped", ended=ts, action="")
                return
            if text.startswith("[Request interrupted"):
                scan.update(state="stopped", ended=ts, action="")
                return
            scan.update(state="running", started=ts, ended="", key=rec.get("uuid") or ts, text="", action="")
            return
        key = message.get("id") or rec.get("uuid") or ts
        if key != scan.get("answer_id"):
            scan["answer_id"], scan["text"] = key, ""
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                box = chats._claude_next(block)
                if box and box.get("ask"):
                    scan["asks"].add(block.get("id"))
                step = self.notify_step(str(block.get("name") or ""))
                if step and scan["state"] == "running":
                    scan["action"] = step
            elif block.get("type") == "text" and (block.get("text") or "").strip():
                scan["text"] = (scan.get("text", "") + "\n" + block["text"].strip()).strip()
        if rec.get("isApiErrorMessage"):
            scan.update(state="failed", ended=ts, key=key, action="")
            return
        stop = message.get("stop_reason")
        if stop in (None, "tool_use"):
            if scan["state"] is None:
                scan["state"] = "running"
            return
        scan.update(state="done", ended=ts, key=key, action="")
        scan["last_kind"] = "assistant"

    def notify_conversations(self, limit: int) -> tuple[list[dict], list[dict]]:
        import notify
        return notify.chats.claude_sessions(limit), []

    # -- new conversation hooks

    def new_options(self, svc) -> dict:
        return svc.claude.new_options() if svc.claude else {"models": [], "note": "Claude 的模型列表暂时读不到"}

    def prepare_new_submission(self, svc, rid: str, data: dict, body: dict) -> None:
        import new_conversations
        data["known_ids"] = [v["id"] for v in new_conversations.chats.claude_sessions(1000000, pending=True)]

    def run_new(self, svc, rid: str, data: dict, trace) -> None:
        from pathlib import Path
        import new_conversations
        images = [svc.bridge.attachment(v, "new:" + rid) for v in data["attachments"]]

        def dispatched():
            svc._save(rid, "dispatching", data, {"message": "已提交，正在核对新对话…"})

        name = Path(data["folder"]).name.casefold()
        unique = bool(data["folder"]) and sum(Path(v["path"]).name.casefold() == name for v in svc.folders()) == 1
        chosen = data.get("settings")
        prepare = (lambda hwnd: svc.claude.apply_new(hwnd, chosen["model"], chosen.get("effort"))) if chosen and svc.claude else None
        trace.phase("desktop_queue", "等待桌面操作")
        extra = (prepare,) if prepare else ()
        svc.desktop.run(
            svc.desktop.new_claude, data["folder"], data["compiled"], images,
            dispatched, unique, trace.phase, *extra, timeout=70 if prepare else 50,
        )
        trace.phase("claude_record", "等待首条消息记录")
        deadline = new_conversations.time.monotonic() + 35
        item = None
        while new_conversations.time.monotonic() < deadline:
            item = svc._find_claude(data)
            if item:
                break
            new_conversations.time.sleep(0.5)
        if not item:
            raise new_conversations.chats.ChatError("尚未在 Claude 记录中确认新对话，请核对电脑；不会重复发送")
        trace.phase("receipt", "保存送达回执")
        data.update(id=item["id"], title=item["title"])
        svc._bind(rid, data)
        svc._record_claude(rid, data)

    def reconcile_new_status(self, svc, rid: str, state: str, data: dict, result: dict) -> tuple[str, dict]:
        if state in ("dispatching", "unconfirmed"):
            item = svc._find_claude(data)
            if item:
                data.update(id=item["id"], title=item["title"])
                state, result = "accepted", {"message": "首条消息已送达"}
                svc._bind(rid, data)
                svc._record_claude(rid, data)
                svc._save(rid, state, data, result)
        return state, result

    # -- desktop, lifecycle & delivery hooks

    def is_our_delivery(self, rec: dict, want: str) -> bool:
        steered = chats._claude_steer_message(rec)
        if steered:
            return want in chats.norm(steered["text"])
        if rec.get("type") == "queue-operation" and rec.get("operation") == "enqueue":
            return want in chats.norm(chats._join_text(rec.get("content")))
        if rec.get("type") == "user":
            return want in chats.norm(chats._join_text((rec.get("message") or {}).get("content")))
        return False

    def desktop_send(self, desktop, item: dict, text: str, images=None, replace=None) -> None:
        desktop._send_claude(item, text, images, replace)

    def desktop_check(self, item: dict, offset: int, text: str) -> dict:
        stage = chats.claude_delivery_stage(chats.conv_path(item), int(offset), text)
        return {"delivered": stage == "received", "queued": stage == "queued", "stage": stage}

    def desktop_open(self, desktop, item: dict) -> None:
        desktop._claude_open(item, [item["title"], self.conversation_title(item)])

    def conversation_title(self, item: dict) -> str:
        import json
        import chats
        path = chats.conv_path(item)
        if path is None:
            return ""
        lines, _ = chats.read_tail(path, 256 << 10)
        for raw in reversed(lines):
            if b"custom-title" in raw[:80]:
                try:
                    return json.loads(raw).get("customTitle") or ""
                except ValueError:
                    continue
        return ""

    def on_server_start(self, cfg: dict, apps: list[str], log) -> None:
        import remote
        remote.hook_settings(cfg, self.id in apps, log)

    def on_server_init(self, server) -> None:
        import threading
        hooks = getattr(server, "claude_hooks", None)
        if hooks is not None and hasattr(hooks, "refresh_sessions"):
            addr = getattr(server, "server_address", None)
            if isinstance(addr, tuple) and len(addr) >= 2 and addr[1]:
                hooks.server_port = int(addr[1])
            threading.Thread(target=hooks.refresh_sessions, name="claude-hook-warm", daemon=True).start()

    def chat_send_with_references(self, handler, body: dict) -> dict:
        import time
        tid = str(body.get("id", ""))
        text = str(body.get("text", ""))
        images = []
        if body.get("attachments"):
            ids = body["attachments"]
            if (not isinstance(ids, list) or len(ids) > 5
                    or any(not isinstance(v, str) for v in ids) or len(set(ids)) != len(ids)):
                raise chats.InputNotSubmitted("图片请求无效，尚未发送")
            images = [handler.server.codex.attachment(v, tid) for v in ids]
            if any(v.get("app", "codex") != "claude" for v in images) or sum(v["original_size"] for v in images) > 50 << 20:
                raise chats.InputNotSubmitted("图片不属于此 Claude 会话或超过大小限制，尚未发送")
            if not text.strip():
                text = "请查看这些图片。"
        if body.get("references"):
            text, _ = handler.server.references.compose(self.id, tid, text, body["references"])
        if images:
            previous = handler.server.codex._begin(str(body.get("request_id", "")), tid, body)
            if previous:
                return previous
            for image in images:
                image["used"] = True
                handler.server.codex._write_meta(image)
        replace = {"replace": body["replace_draft"][:2000]} if isinstance(body.get("replace_draft"), str) else {}
        result = (
            handler.desktop.send(self.id, tid, text, images, **replace)
            if images else handler.desktop.send(self.id, tid, text, **replace)
        )
        result["accepted_at"] = int(time.time() * 1000)
        for image in images:
            image["used"] = True
            handler.server.codex._write_meta(image)
        if body.get("references") or images:
            result["check_text"] = text
        if images:
            handler.server.codex._finish(body["request_id"], result)
        return result

    def _upload_for_chat(self, handler, tid: str, name: str, raw: bytes) -> dict:
        return handler.server.codex.upload(tid, name, raw, self.id)

    # -- HTTP action handlers (shared by /api/agents/claude/* and /api/claude/*)

    def _run_claude_post(self, handler, path_label: str, fn) -> None:
        import traceback
        import claude_control
        try:
            handler._json(fn())
        except Exception as exc:
            if not isinstance(exc, chats.ChatError):
                handler.log.write(f"Claude 操作 {path_label} 出错：\n" + traceback.format_exc())
            handler._json(
                {
                    "error": claude_control.plain_error(exc),
                    "not_submitted": bool(getattr(exc, "not_submitted", False)),
                    "code": getattr(exc, "code", None),
                },
                409,
            )

    def http_state(self, handler) -> None:
        import time
        try:
            q = handler._query()
            tid = q.get("id", "")
            ua = handler.headers.get("User-Agent") or ""
            handler.server.claude_reads.append({
                "time": time.strftime("%H:%M:%S"),
                "id": tid[-6:],
                "fresh": q.get("fresh") == "1",
                "from": "iPhone" if "iPhone" in ua else "Android" if "Android" in ua else "other",
            })
            handler._json({
                **handler.server.claude.state(tid, q.get("fresh") == "1"),
                "images": handler.server.codex.message_images(tid),
            })
        except Exception as exc:
            handler._json({"error": str(exc)}, 400)

    def http_receipt(self, handler) -> None:
        q = handler._query()
        tid, rid = q.get("id", ""), q.get("request_id", "")
        bridge = getattr(handler.server, "codex", None)
        if bridge is not None and rid:
            try:
                rec = bridge.receipt(tid, rid)
                if isinstance(rec, dict) and rec.get("state") and rec.get("state") != "unknown":
                    handler._json(rec)
                    return
            except Exception:
                pass
        handler._json({"state": "unknown", "id": tid, "request_id": rid})

    def http_send(self, handler, body: dict) -> None:
        if body.get("intent") == "steer" and (body.get("expected_turn") or body.get("turn_id")):
            def run():
                tid = str(body.get("id", ""))
                text = str(body.get("text", ""))
                if body.get("references"):
                    text, _ = handler.server.references.compose(self.id, tid, text, body["references"])
                expected = str(body.get("expected_turn") or body.get("turn_id") or "")
                result = handler.server.claude.send_steer(tid, text, expected, str(body.get("request_id", "")))
                result["check_text"] = text
                return result
            self._run_claude_post(handler, "/api/claude/steer", run)
            return
        handler._chat_call(handler._send_with_references, {**body, "app": self.id}, timeout=60)

    def http_stop(self, handler, body: dict) -> None:
        if body.get("token"):
            self._run_claude_post(
                handler, "/api/claude/choose",
                lambda: handler.server.claude.choose(str(body.get("id", "")), str(body.get("token", "")), None),
            )
            return
        if isinstance(body.get("option"), dict):
            handler._chat_call(
                handler.desktop.claude_press, str(body.get("id", "")), body["option"],
                str(body.get("text", "")), bool(body.get("enter")), timeout=40,
            )
            return
        handler._json({"error": "停止 Claude 需要当前桌面令牌（token）"}, 400)

    def http_queue(self, handler, body: dict) -> None:
        handler._json({"error": "这个助手还没有队列", "code": "unsupported"}, 400)

    def http_answer(self, handler, body: dict) -> None:
        tid = str(body.get("id", ""))
        if body.get("token"):
            self._run_claude_post(
                handler, "/api/claude/choose",
                lambda: handler.server.claude.choose(tid, str(body.get("token", "")), body.get("value")),
            )
        elif "tool_id" in body:
            self._run_claude_post(
                handler, "/api/claude/next",
                lambda: handler.server.claude.next_step(tid, str(body.get("tool_id", "")), int(body.get("index", -1)), str(body.get("label", ""))),
            )
        elif "title" in body and "button" in body:
            self._run_claude_post(
                handler, "/api/claude/task",
                lambda: handler.server.claude.task_step(tid, str(body.get("title", "")), str(body.get("button", ""))),
            )
        elif isinstance(body.get("option"), dict):
            handler._chat_call(
                handler.desktop.claude_press, tid, body["option"],
                str(body.get("text", "")), bool(body.get("enter")), timeout=40,
            )
        else:
            handler._json({"error": "缺少回答所需的令牌或选项"}, 400)

    def http_open(self, handler, body: dict) -> None:
        handler._chat_call(handler.desktop.open, self.id, str(body.get("id", "")), timeout=45)

    def http_legacy_get(self, handler, sub: str) -> None:
        if sub == "state":
            self.http_state(handler)
            return
        handler._json({"error": "没有这个地址"}, 404)

    def http_legacy_post(self, handler, sub: str, body: dict) -> None:
        path = "/api/claude/" + sub
        def run():
            tid = str(body.get("id", ""))
            if sub == "menu":
                return handler.server.claude.menu(tid, str(body.get("kind", "")))
            if sub == "catalog":
                return handler.server.claude.catalog(tid, bool(body.get("fresh")))
            if sub == "setting":
                return handler.server.claude.select_setting(
                    tid, str(body.get("kind", "")), str(body.get("name", "")),
                    body.get("value"), body.get("expected_model"),
                )
            if sub == "choose":
                return handler.server.claude.choose(tid, str(body.get("token", "")), body.get("value"))
            if sub == "close-menu":
                return handler.server.claude.close_menu(tid)
            if sub == "next":
                return handler.server.claude.next_step(tid, str(body.get("tool_id", "")), int(body.get("index", -1)), str(body.get("label", "")))
            if sub == "task":
                return handler.server.claude.task_step(tid, str(body.get("title", "")), str(body.get("button", "")))
            if sub == "steer":
                text = str(body.get("text", ""))
                if body.get("references"):
                    text, _ = handler.server.references.compose(self.id, tid, text, body["references"])
                result = handler.server.claude.send_steer(tid, text, str(body.get("expected_turn", "")), str(body.get("request_id", "")))
                result["check_text"] = text
                return result
            raise chats.ChatError("没有这个操作")
        self._run_claude_post(handler, path, run)


AGENT = ClaudeAgent
