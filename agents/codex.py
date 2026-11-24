"""Codex desktop: its own mark, files and local channel."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import difflib
import json
import re

import chats

from .base import Agent, NotFound, make_manifest

CODEX_STEPS = {
    "exec": "run",
    "shell": "run",
    "exec_command": "run",
    "apply_patch": "edit",
    "web_search": "search",
    "search": "search",
    "js": "run",
}

# 11-24: one thread per automation run, its source 'automation'; kept apart from the conversations a person talks in so
# that however many tasks run they never push those out of the newest LIMIT.
AUTOMATION_WHERE = "coalesce(thread_source, '') = 'automation'"
AUTOMATION_LIMIT = 10
_AUTOMATION_ID = re.compile(r"^[ \t]*Automation ID:[ \t]*([A-Za-z0-9_-]{1,80})[ \t]*$", re.M)
_AUTOMATION_NAME = re.compile(r"^[ \t]*Automation:[ \t]*(.+?)[ \t]*$", re.M)


class CodexAgent(Agent):
    id = "codex"
    home_list = True
    requires_running_state = True
    dedupe_twins = True
    assign_turn_id = True
    final_answer_plan = True
    desktop_tasks = True
    has_skills = True
    can_reset_usage = True
    archive_order = 10
    desktop_process = chats.CODEX_PROCESS
    desktop_send_text = "已按回车，等对话记录确认"
    delivery_markers = (b"UserMessage", b"user_message", b"codex_delegation", b"hook_prompt", b"HookPrompt")

    def build_manifest(self) -> dict:
        caps = {
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
            "settings": ["model", "effort", "mode"],
            "send_modes": ["send", "steer", "queue"],
            "statuses": ["running", "waiting", "idle", "unknown"],
        }
        sources = {"catalog": "sqlite", "transcript": "jsonl", "control": "ipc", "live": "pipe+file"}
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
            capabilities=caps,
            params={"refresh_ms": 2500},
            ui={"card_layout": "codex.v1", "waiting_text": "等你处理"},
            sources=sources,
        )

    def capabilities_now(self, server, conv_id: str) -> dict | None:
        import codex_apptools
        import codex_hooks

        route = codex_apptools.current_route()
        if route == "legacy":
            base_caps = self.manifest()["capabilities"]
            caps = {
                **base_caps,
                "settings": list(base_caps["settings"]),
                "send_modes": list(base_caps["send_modes"]),
                "statuses": list(base_caps["statuses"]),
            }
            return {"capabilities": caps, "notes": {}}
        if route == "apptools":
            trust = codex_hooks.read_trust_status()
            hooks_trusted = trust == "enabled"
            caps = {
                "list": True,
                "read": True,
                "search": True,
                "open": True,
                "stop": bool(hooks_trusted),
                "queue": True,
                "steer": True,
                "approve": bool(hooks_trusted),
                "answer": bool(hooks_trusted),
                "new": True,
                "new_projectless": True,
                "new_permission": False,
                "archive": True,
                "restore": True,
                "delete": True,
                "usage": True,
                "waiting": True,
                "attachments": True,
                "slash_commands": False,
                "settings": ["model", "effort"],
                "send_modes": ["send", "steer", "queue"],
                "statuses": ["running", "waiting", "idle", "unknown"],
            }
            notes = {
                "slash_commands": "新版 Codex 不能从手机压缩对话（/compact）",
                "mode": "新版 Codex 从手机发的消息跟着电脑上当前的模式走，手机上不能切换",
            }
            if not hooks_trusted:
                hook_reason = (
                    codex_hooks.TRUST_HINT
                    if trust == "pending_trust"
                    else "遥应的 Codex 钩子还没装上，手机暂时不能批准、停止、回答"
                )
                notes["stop"] = hook_reason
                notes["approve"] = hook_reason
                notes["answer"] = hook_reason
            return {"capabilities": caps, "notes": notes}
        caps = {
            "list": True,
            "read": True,
            "search": True,
            "open": True,
            "stop": False,
            "queue": False,
            "steer": False,
            "approve": False,
            "answer": False,
            "new": True,
            "new_projectless": True,
            "new_permission": False,
            "archive": True,
            "restore": True,
            "delete": True,
            "usage": True,
            "waiting": False,
            "attachments": False,
            "slash_commands": False,
            "settings": [],
            "send_modes": [],
            "statuses": ["running", "waiting", "idle", "unknown"],
        }
        reason = codex_apptools.NOT_RUNNING_REASON
        notes = {
            "send": reason,
            "steer": reason,
            "queue": reason,
            "stop": reason,
            "approve": reason,
            "answer": reason,
            "attachments": reason,
        }
        return {"capabilities": caps, "notes": notes}

    def find(self, conv_id: str) -> dict:
        item = chats.codex_thread(conv_id)
        if item is None:
            raise NotFound("找不到这个对话（可能已归档或删掉了）")
        return item

    def transcript_path(self, item: dict):
        path = Path(item["path"]) if item.get("path") else None
        return path if path is not None and path.is_file() else None

    def parse_lines(self, lines, context=None, parsed=None):
        return chats.parse_codex(lines, context, parsed)

    def parse_for_item(self, item: dict, lines: list[bytes]) -> tuple[list[dict], dict]:
        return chats.parse_codex(lines, thread_id=str(item.get("id") or ""))

    def skip_record(self, raw: bytes) -> bool:
        return (b"event_msg" not in raw[:160] and b"response_item" not in raw[:160]
                and b'"compacted"' not in raw[:160])

    def step_of(self, name: str, argument: str = "") -> str:
        action = CODEX_STEPS.get((name or "").rsplit(".", 1)[-1])
        if name == "exec":
            text = (argument or "").lower()
            if "apply_patch" in text or "*** begin patch" in text:
                return "edit"
            if "web_search" in text or "search_query" in text or "web.run" in text:
                return "search"
        return action or ""

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
            payload = rec.get("payload") or {}
            event = payload.get("type") if rec.get("type") == "event_msg" else None
            if event == "task_started":
                action = ""
            elif rec.get("type") == "response_item" and payload.get("type") in ("function_call", "custom_tool_call"):
                step = self.step_of(str(payload.get("name") or ""), str(payload.get("input") or ""))
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
            payload = rec.get("payload") or {}
            event = payload.get("type") if kind == "event_msg" else None
            if event == "task_started":
                out["turn_time"] = ts
            if kind == "turn_context":
                settings = (payload.get("collaboration_mode") or {}).get("settings") or {}
                model = payload.get("model") or settings.get("model")
                if out["model"] and model != out["model"]:
                    out.update(used_tokens=None, context_window=None, percent=None, usage_time=None,
                               context_state="waiting")
                out.update(model=model, effort=payload.get("effort") or payload.get("reasoning_effort")
                           or settings.get("reasoning_effort"), model_time=ts, model_turn_id=payload.get("turn_id"))
            if kind == "compacted" or event == "context_compacted":
                out.update(used_tokens=None, context_window=None, percent=None, usage_time=None,
                           context_state="waiting")
            if event == "token_count":
                info = payload.get("info") or {}
                used = (info.get("last_token_usage") or {}).get("total_tokens")
                window = info.get("model_context_window")
                if isinstance(used, int) and not isinstance(used, bool) and used >= 0 and isinstance(window, int) and window > 0:
                    out.update(used_tokens=used, context_window=window, percent=round(used / window * 100, 1),
                               usage_time=ts, context_state="available")
        return out

    def runtime_complete(self, out: dict) -> bool:
        return bool(out.get("model") and out.get("context_state") != "unavailable")

    def enrich_activity(self, record: dict, messages: list[dict], context: dict, ts: str):
        import activity_records
        p = record.get("payload") or {}
        kind = p.get("type")
        current = context.get("activity_turn")
        if record.get("type") == "response_item" and current:
            timing = context.get("activity_turns", {}).get(current, {})
            if kind == "function_call" and str(p.get("name", "")).split(".")[-1] == "request_user_input":
                context.setdefault("activity_waits", {})[p.get("call_id")] = current
                timing.setdefault("paused_at", activity_records.milliseconds(ts))
            elif kind == "function_call_output":
                waiting = context.setdefault("activity_waits", {}).pop(p.get("call_id"), None)
                if waiting:
                    clock = context["activity_turns"][waiting]
                    start = clock.pop("paused_at", None)
                    end = activity_records.milliseconds(ts)
                    if start is not None and end is not None:
                        clock["paused_ms"] = clock.get("paused_ms", 0) + max(0, end - start)
                        clock.setdefault("pauses", []).append([start, end])
            return None
        if kind == "task_started":
            context["activity_turn"] = p.get("turn_id") or "start:" + ts
            context.setdefault("activity_turns", {})[context["activity_turn"]] = {
                "status": "running", "started_at": activity_records.milliseconds(ts), "pauses": []}
        turn = context.get("activity_turn")
        if kind in ("task_complete", "turn_aborted") and turn:
            context["activity_turns"][turn].update(
                status="stopped" if kind == "turn_aborted" else "completed",
                ended_at=activity_records.milliseconds(ts))
        item = p.get("item") or {}
        if kind == "item_completed" and item.get("type") in ("FileChange", "fileChange"):
            changes = []
            source_changes = item.get("changes") or []
            if isinstance(source_changes, dict):
                source_changes = [dict(value, path=path) for path, value in source_changes.items() if isinstance(value, dict)]
            for row in source_changes:
                if not isinstance(row, dict):
                    continue
                k = row.get("kind", "modify")
                k = k.get("type", "modify") if isinstance(k, dict) else row.get("type", k)
                patch = row.get("diff") or row.get("unified_diff")
                if k in ("add", "delete") and isinstance(row.get("content"), str):
                    content = row["content"].splitlines()
                    patch = "\n".join(difflib.unified_diff(
                        [] if k == "add" else content, content if k == "add" else [],
                        fromfile="/dev/null" if k == "add" else row["path"],
                        tofile=row["path"] if k == "add" else "/dev/null", lineterm=""))
                c = activity_records.change(row.get("path"), patch, k)
                if c and isinstance(row.get("move_path"), str):
                    c.update(kind="rename", destination=row["move_path"])
                if c:
                    changes.append(c)
            succeeded = str(item.get("status", "")).lower() in ("completed", "success", "succeeded")
            messages.append({
                "role": "tool", "text": "修改文件", "time": ts, "source_id": item.get("id"),
                "tool_status": "completed" if succeeded else "failed" if item.get("status") == "failed" else "unknown",
                "_changes": changes,
            })
        if kind == "item_completed" and item.get("type") == "CommandExecution":
            for m in messages:
                if m["role"] == "tool":
                    command = item.get("command")
                    m["detail"] = (command if isinstance(command, str) else json.dumps(command, ensure_ascii=False))[:16000]
                    m["result"] = str(item.get("aggregated_output") or "")[:16000]
                    m["tool_status"] = "failed" if item.get("exit_code", item.get("exitCode", 0)) not in (0, None) else "completed"
                    if (item.get("exit_code", item.get("exitCode")) == 1 and isinstance(command, str)
                            and re.match(r"^\s*(?:rg|ripgrep)\s", command)
                            and not re.search(r"[;&|<>\r\n`]", command) and not m["result"].strip()):
                        m["tool_status"] = "no_matches"
                        m["result"] = "搜索完成，没有匹配项"
        return turn

    def runtime(self, path) -> dict:
        return chats.runtime_info("codex", path)

    def catalog_entries(self, limit: int) -> list[dict]:
        return chats.codex_threads(limit)

    def summary(self, item: dict) -> dict:
        return chats.summary_for(self, item)

    def read(self, conv_id: str, *, limit: int = 60, before: str = "",
             around: str = "", lite: bool = False) -> dict:
        return chats.conversation_for(self, conv_id, limit)

    def final_answer(self, message: dict) -> bool:
        return message.get("role") == "assistant" and message.get("phase") == "final_answer"

    def twins(self, a: dict, b: dict) -> bool:
        return chats.codex_twins(a, b)

    def project_group(self, item: dict):
        import chat_projects
        layout = chat_projects.codex_layout()
        placed = chat_projects.codex_group(item, layout)
        if placed is None:
            return None
        key, place = placed
        name = chat_projects.OTHER_NAME if key == chat_projects.OTHER_KEY else layout[0][key]["name"]
        return key, name, place

    def new_folder(self, group: dict) -> str:
        import chat_projects
        if group["key"] == chat_projects.OTHER_KEY:
            return ""
        roots = chat_projects.codex_layout()[0].get(group["key"], {}).get("roots") or []
        return roots[0] if roots else ""

    def _apptools_for(self, bridge):
        import codex_apptools
        existing = getattr(bridge, "_apptools_bridge", None)
        if existing is None:
            hooks = getattr(bridge, "_codex_hooks", None)
            existing = codex_apptools.AppToolsBridge(bridge, hooks=hooks)
            try:
                bridge._apptools_bridge = existing
            except Exception:
                pass
        elif existing.hooks is None and getattr(bridge, "_codex_hooks", None) is not None:
            existing.hooks = bridge._codex_hooks
        hooks = existing.hooks
        if hooks is not None and getattr(hooks, "auto_install_enabled", False) and not getattr(hooks, "installed_once", False):
            try:
                hooks.ensure_installed()
            except Exception:
                pass
        return existing

    def on_server_init(self, server) -> None:
        import codex_apptools
        import codex_hooks

        cfg = getattr(server, "cfg", {}) or {}
        apps = (getattr(server, "machine", {}) or {}).get("apps") or []
        log = getattr(getattr(server, "log", None), "write", lambda _t: None)
        bridge = getattr(server, "codex", None)
        if bridge is None:
            return
        apptools = self._apptools_for(bridge)

        def on_waiting(tid: str, card: dict) -> None:
            notifier = getattr(server, "notifier", None)
            if notifier is None:
                return
            try:
                item = chats.find(self.id, tid)
                what = str(card.get("question") or "Codex 在等你处理")[:90]
                notifier.asking(item, what)
            except Exception:
                pass

        hooks = codex_hooks.CodexHookServer(
            pop_queued=apptools.pop_queued_for_stop_hook,
            has_queued=apptools.queues.has_any,
            on_change=lambda tid: apptools._status_cache.pop(tid, None),
            on_waiting=on_waiting,
            log=log,
        )
        bridge._codex_hooks = hooks
        apptools.hooks = hooks
        try:
            if cfg.get("codex_hooks") is False:
                hooks.enabled = False
                codex_hooks.remove_hooks(log=log)
            elif self.id in apps:
                hooks.auto_install_enabled = True
                hooks.start()
                if codex_apptools.current_route() == "apptools":
                    hooks.ensure_installed()
        except Exception as exc:
            log(f"Codex 钩子初始化未完成：{exc}")

    def on_server_close(self, server) -> None:
        bridge = getattr(server, "codex", None)
        if bridge is None:
            return
        for attr in ("_apptools_bridge", "_codex_hooks"):
            obj = getattr(bridge, attr, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass

    def wait_update(self, bridge, tid: str, timeout: float) -> bool:
        route, backend = self._backend(bridge)
        if route == "apptools" and getattr(backend, "hooks", None) is not None:
            backend.hooks.wait_change(tid, timeout)
            return True
        return False

    def _backend(self, bridge, *, force_route: bool = False):
        import codex_apptools
        route = codex_apptools.current_route(force=force_route)
        if route == "legacy":
            return "legacy", bridge
        if route == "apptools":
            return "apptools", self._apptools_for(bridge)
        return "none", bridge

    def watch(self, bridge, tid: str):
        route, _ = self._backend(bridge)
        if route != "legacy":
            return None
        try:
            return bridge.watch(tid)
        except Exception:
            return None

    def control(self, bridge, tid: str):
        route, backend = self._backend(bridge)
        if route == "none":
            return self._not_running_state(bridge, tid)
        return backend.status(tid)

    def _not_running_state(self, bridge, tid: str) -> dict:
        import codex_apptools
        import codex_control
        images = bridge.message_images(tid)
        by_req = codex_apptools.read_request_source_map(tid)
        if by_req:
            images = [
                {**row, "message_id": by_req[row["request_id"]]}
                if row.get("request_id") in by_req and not row.get("message_id")
                else row
                for row in images
            ]
        return {
            "available": False,
            "route": "none",
            "reason": codex_apptools.NOT_RUNNING_REASON,
            "questions": [],
            "plan": None,
            "catalog": codex_control.catalog(),
            "images": images,
        }

    def message_request_ids(self, tid: str) -> dict[str, str]:
        import codex_apptools
        return codex_apptools.read_source_request_map(tid)

    def merge_live(self, page: dict, entry, state, previous=None, lite: bool = False):
        import live_events
        return live_events.merge_live_messages(page, entry, state, previous, lite)

    def detect(self) -> bool:
        import machines

        def package(prefix: str) -> bool:
            packages = machines.LOCALAPPDATA / "Packages"
            return packages.is_dir() and any(packages.glob(prefix + "_*"))

        return package("OpenAI.Codex") or (machines.LOCALAPPDATA / "OpenAI" / "Codex").is_dir()

    # -- commands, references, usage, archives

    def commands(self, conv_id: str, *, references=None, deepseek=None) -> list:
        import codex_apptools
        import composer_commands
        if codex_apptools.current_route() != "legacy":
            return []
        return [composer_commands.item(**v) for v in composer_commands.CODEX]

    def skill_roots(self, home, cwd: str, read_config, warnings: list, warn_fn) -> tuple[list, set]:
        import stat
        disabled = set()
        conf = read_config(home / ".codex/config.toml")
        skills = conf.get("skills", {})
        plugins = conf.get("plugins", {})
        if not isinstance(skills, dict) or not isinstance(plugins, dict):
            raise ValueError("Invalid skill/plugin configuration")
        rows = skills.get("config", [])
        if not isinstance(rows, list):
            raise ValueError("Invalid skill configuration")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid skill rule")
            if row.get("enabled") is False and row.get("path"):
                disabled.add(str(Path(row["path"]).resolve()).casefold())
        roots = [
            (home / ".codex/skills", "个人技能", False),
            (home / ".codex/skills/.system", "内置技能", False),
            (home / ".agents/skills", "个人技能", False),
        ]
        for key, value in plugins.items():
            if not isinstance(value, dict):
                raise ValueError("Invalid plugin rule")
            if value.get("enabled") is not True or "@" not in key:
                continue
            plugin, market = key.rsplit("@", 1)
            base = home / ".codex/plugins/cache" / market / plugin
            try:
                versions = [p for p in base.iterdir() if re.fullmatch(r"\d+(?:\.\d+)*", p.name)]
                if not versions:
                    raise ValueError("No supported numeric plugin version")
                selected = max(versions, key=lambda p: tuple(map(int, p.name.split("."))))
                root = selected / "skills"
                if not stat.S_ISDIR(selected.stat().st_mode):
                    raise ValueError("Plugin version is not a directory")
                roots.append((root, plugin, False))
            except (OSError, ValueError) as exc:
                warn_fn(warnings, plugin, exc)
        current = Path(cwd) if cwd else None
        for parent in ([current, *current.parents] if current and current.is_absolute() else [])[:12]:
            if parent == home:
                break
            for name in (".agents/skills", ".codex/skills"):
                roots.insert(0, (parent / name, "项目技能 · " + parent.name, False))
        return roots, disabled

    def format_skills(self, skills: list[dict], *, native: bool = True) -> tuple[str, list[dict]]:
        if not native:
            lines = [f"请使用以下技能：{s['name']}（说明文件：{s['path']}）" for s in skills]
            return "\n".join(lines), []
        names = " ".join("$" + s["name"] for s in skills)
        native_items = [{"type": "skill", "name": s["name"], "path": s["path"]} for s in skills]
        return names, native_items

    def read_usage(self, svc, live: bool = False) -> dict:
        return svc._codex(bool(live))

    def redeem_usage(self, svc, body: dict) -> dict:
        import time
        import usage_limits
        with usage_limits._LOCK:
            cached = svc._cache[1] if svc._cache and svc._cache[1].get("source") == "live" else None
        result = usage_limits.codex_redeem(
            body.get("request_id"), body.get("credit_id"), svc.server_factory,
            data_dir=svc.data_dir, log=svc.log, cached=cached,
        )
        if result.get("usage"):
            with usage_limits._LOCK:
                svc._cache = (time.monotonic(), result["usage"])
        return result

    def archive_conv(self, svc, conv_id: str) -> None:
        import archives
        item = chats.find(self.id, conv_id)
        if chats.summary(item).get("status") == "running":
            raise archives.ArchiveError("这个对话正在运行，先停止这一轮再归档")
        with svc.lock, svc.server() as server:
            try:
                server.call("thread/archive", {"threadId": conv_id})
            except archives.CodexRefused as exc:
                if any(w in str(exc).lower() for w in archives.WRITER):
                    raise archives.ArchiveError(
                        "电脑上的 Codex 正开着这个对话（或刚开过），这段记录被它占着，现在归档不了。"
                        "过几分钟再试，或者在电脑上归档。"
                    ) from None
                raise archives.ArchiveError("Codex 没有归档：" + str(exc)) from None
        svc._tell_desktop("thread-archived", 2, conv_id)

    def unarchive_conv(self, svc, conv_id: str) -> None:
        import archives
        row = archives.codex_row(conv_id)
        if row is None:
            raise archives.ArchiveError("找不到这个 Codex 对话（可能已经删掉了）", 404)
        if row["archived"]:
            with svc.lock, svc.server() as server:
                try:
                    server.call("thread/unarchive", {"threadId": conv_id}, 60)
                except archives.CodexRefused as exc:
                    raise archives.ArchiveError("Codex 没有恢复：" + str(exc)) from None
            svc._tell_desktop("thread-unarchived", 1, conv_id)

    def archived_list(self, svc) -> list[dict]:
        import archives
        return [dict(v, can_delete=True) for v in archives.codex_rows("archived = 1")]

    def prepare_delete(self, conv_id: str) -> dict | None:
        import archives
        row = archives.codex_row(conv_id)
        if row is None:
            return {"app": self.id, "id": conv_id, "ok": True, "gone": True}
        if not row["archived"]:
            return {"app": self.id, "id": conv_id, "ok": False, "error": "只能删除已归档的对话"}
        return None

    def delete_convs(self, svc, conv_ids: list[str]) -> list[dict]:
        import archives
        results = []
        if conv_ids:
            with svc.lock, svc.server() as server:
                for tid in conv_ids:
                    try:
                        server.call("thread/delete", {"threadId": tid}, 60)
                        results.append({"app": self.id, "id": tid, "ok": True})
                    except archives.CodexRefused as exc:
                        results.append({"app": self.id, "id": tid, "ok": False, "error": str(exc)[:160]})
            for r in results:
                if r.get("ok") and not r.get("gone"):
                    svc._tell_desktop("thread-archived", 2, r["id"])
                    svc.log(f"手机上删除了 Codex 对话 {r['id']}")
        return results

    # -- notify hooks

    def notify_turn_end(self, lines: list[bytes]) -> dict | None:
        states = {"task_started": "running", "task_complete": "done", "turn_aborted": "stopped"}
        end = None
        for raw in lines:
            if b"event_msg" not in raw[:160]:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            payload = rec.get("payload") or {}
            state = states.get(payload.get("type"))
            if state:
                ts = rec.get("timestamp") or ""
                end = {
                    "state": state,
                    "key": payload.get("turn_id") or ts,
                    "time": ts,
                    "text": chats.codex_answer(payload.get("last_agent_message") or ""),
                }
        return end

    def notify_step(self, name: str, argument: str = "") -> str | None:
        name = (name or "").strip()
        action = CODEX_STEPS.get(name)
        if name == "exec":
            text = (argument or "").lower()
            if "apply_patch" in text or "*** begin patch" in text:
                return "edit"
            if "web_search" in text or "search_query" in text or "web.run" in text:
                return "search"
            return "run"
        return action

    def notify_scan_record(self, scan: dict, rec: dict) -> None:
        kind = rec.get("type")
        payload = rec.get("payload") or {}
        ts = rec.get("timestamp") or ""
        if ts:
            scan["latest"] = ts
        event = payload.get("type") if kind == "event_msg" else None
        if event == "task_started":
            scan.update(state="running", started=ts, ended="", key=payload.get("turn_id") or ts, text="", action="",
                        raw_text="", abort_reason="")
        elif event in ("task_complete", "turn_aborted"):
            raw = (payload.get("last_agent_message") or "") if event == "task_complete" else ""
            scan.update(
                state="stopped" if event == "turn_aborted" else "done",
                ended=ts,
                key=payload.get("turn_id") or scan["key"] or ts,
                text=chats.codex_answer(raw) if event == "task_complete" else scan["text"],
                raw_text=raw,
                abort_reason=(payload.get("reason") or "") if event == "turn_aborted" else "",
                action="",
            )
        elif event == "item_completed" and (payload.get("item") or {}).get("type") == "UserMessage":
            self._scan_automation(scan, chats._join_text((payload.get("item") or {}).get("content")))
        elif kind == "response_item":
            ptype = payload.get("type")
            if ptype in ("function_call", "custom_tool_call"):
                step = self.notify_step(str(payload.get("name") or ""), str(payload.get("input") or ""))
                if step:
                    scan["action"] = step
            elif ptype == "message" and payload.get("role") in ("user", "developer"):
                self._scan_automation(scan, chats._join_text(payload.get("content")))
            elif ptype == "item_completed" and (payload.get("item") or {}).get("type") == "CommandExecution":
                scan["action"] = "run"

    def _scan_automation(self, scan: dict, text: str) -> None:
        """The Automation ID and name Codex writes at the top of an automation run's user message (11-24). Not cleared
        on task_started: the record writes the user message before the turn starts."""
        ids = _AUTOMATION_ID.findall(text or "")
        names = _AUTOMATION_NAME.findall(text or "")
        if ids:
            scan["automation_id"] = ids[-1]
        if names:
            scan["automation_name"] = chats.one_line(names[-1], 80)

    def notify_conversations(self, limit: int, automations: str = "codex") -> tuple[list[dict], list[dict]]:
        """The conversations the phone hears about. 11-24: automations too, unless off; they are looked up
        separately (the newest ten) so that a pile of them never squeezes out the conversations a person had."""
        import sqlite3
        import notify
        try:
            rows = notify.chats._codex_rows(notify.CODEX_WHERE, (), limit)
        except sqlite3.Error:
            try:
                rows = notify.chats.codex_threads(limit)
            except sqlite3.Error:
                rows = []
        rows = list(rows)
        if automations != "off":
            try:
                extra = notify.chats._codex_rows(AUTOMATION_WHERE, (), AUTOMATION_LIMIT)
            except sqlite3.Error:
                extra = []
            known = {row.get("id") for row in rows}
            for row in extra:
                if row.get("id") in known:  # never twice (the two queries cannot overlap in the database)
                    continue
                item = dict(row)
                item["automation"] = True
                rows.append(item)
        return rows, []

    def notify_check_approvals(self, notifier, item: dict, conv: tuple, title: str, found) -> bool:
        import codex_apptools
        route = codex_apptools.current_route()
        if route == "legacy":
            return notifier._codex_approvals(item, conv, title, found)
        if route != "apptools":
            return False
        bridge = getattr(notifier, "bridge", None)
        hooks = getattr(bridge, "_codex_hooks", None) if bridge is not None else None
        if hooks is None:
            return False
        cards = hooks.pending_cards(item["id"])
        if cards:
            key = "pending:" + ",".join(sorted(str(v["request_id"]) for v in cards))
            previous = notifier.running.get(conv) or {}
            since = int(previous.get("since") or notifier.clock())
            notifier.running.pop(conv, None)
            notifier.waiting[conv] = {"since": since, "title": title, "item": item}
            if notifier.reported_approvals.get(conv) != key:
                notifier.reported_approvals[conv] = key
                source = "记录" if previous.get("source") == "记录" else "电脑注意到"
                notifier._tell(found, item, {
                    "state": "done", "key": key, "time": "", "asks": True,
                    "text": "Codex 在等你处理，请打开对话查看。",
                    "started": since, "ended": int(notifier.clock()),
                    "started_source": source,
                })
            return True
        if notifier.reported_approvals.pop(conv, None) is not None:
            notifier.waiting.pop(conv, None)
            notifier.running.pop(conv, None)
            notifier.reported_running.discard(conv)
        return False

    # -- new conversation hooks

    def new_options(self, svc) -> dict:
        import new_conversations
        return {
            "models": [
                {
                    "id": m["id"],
                    "label": m["name"],
                    "efforts": [{"id": e, "label": e} for e in m["efforts"]],
                    "default_effort": m.get("default_effort"),
                }
                for m in new_conversations.codex_control.catalog()["models"]
            ],
            "note": "",
        }

    def prepare_new_submission(self, svc, rid: str, data: dict, body: dict) -> None:
        if data.get("projectless"):
            data["folder"] = svc._projectless_folder()

    def run_new(self, svc, rid: str, data: dict, trace) -> None:
        import codex_apptools
        import new_conversations
        route = codex_apptools.current_route()
        if route == "none":
            raise new_conversations.chats.SendNotSubmitted(codex_apptools.NOT_RUNNING_REASON)
        if not data.get("id"):
            svc._empty_codex(rid, data)
        svc._save(rid, "prepared", data, {"message": "正在连接桌面端的新对话…"})
        trace.phase("desktop_open", "在桌面打开新对话")
        if route == "apptools":
            new_conversations.os.startfile("codex://threads/" + data["id"])
            apptools = self._apptools_for(svc.bridge)
            trace.phase("desktop_owner", "等待新版 Codex 接管对话")
            deadline = new_conversations.time.monotonic() + new_conversations.TAKEOVER_SECONDS
            reopen = new_conversations.time.monotonic() + new_conversations.REOPEN_SECONDS
            while True:
                try:
                    apptools.client.read_thread(data["id"], include_turns=False)
                    break
                except Exception:
                    now = new_conversations.time.monotonic()
                    if now >= deadline:
                        raise new_conversations.chats.InputNotSubmitted(
                            f"新对话已创建，桌面端 {new_conversations.TAKEOVER_SECONDS} 秒内没有接管；请打开该对话后发送保留的草稿"
                        )
                    if now >= reopen:
                        trace.phase("desktop_reopen", "再次在桌面打开新对话")
                        new_conversations.os.startfile("codex://threads/" + data["id"])
                        reopen = now + new_conversations.REOPEN_SECONDS
                    new_conversations.time.sleep(0.5)
            settings = {}
            if data.get("settings"):
                settings = svc._picked({"model": data.get("default_model"), "effort": data.get("default_effort"),
                                        "mode": "default", "service_tier": None}, data["settings"])
            submitted_settings = (data.get("submitted") or {}).get("settings")
            if (
                codex_apptools._is_plan_mode_requested(data.get("settings"))
                or codex_apptools._is_plan_mode_requested(submitted_settings)
            ):
                settings = {**settings, "mode": "plan"}
            trace.phase("bind", "准备首条消息与附件")
            svc._bind(rid, data)
            svc._save(rid, "dispatching", data, {"message": "正在提交首条消息…"})
            answer = apptools.send(
                {
                    "id": data["id"],
                    "request_id": rid,
                    "text": data["text"],
                    "attachments": data["attachments"],
                    "references": data["references"],
                    "settings": settings or None,
                },
                timing=trace.phase,
            )
            if not (answer.get("accepted") or answer.get("delivered")):
                raise new_conversations.chats.ChatError(answer.get("text") or answer.get("message") or "首条消息结果尚未确认")
            if codex_apptools.PLAN_MODE_IGNORED_NOTE in str(answer.get("text") or ""):
                data["accepted_message"] = str(answer["text"])
            return
        new_conversations.chats.require_send_desktop()
        new_conversations.os.startfile("codex://threads/" + data["id"])
        trace.phase("desktop_owner", "等待桌面接管对话")
        deadline = new_conversations.time.monotonic() + new_conversations.TAKEOVER_SECONDS
        reopen = new_conversations.time.monotonic() + new_conversations.REOPEN_SECONDS
        while True:
            try:
                owner, snapshot = svc.bridge._pipe().snapshot(data["id"], 5, timing=trace.phase)
                if snapshot.get("id") == data["id"]:
                    break
            except Exception:
                now = new_conversations.time.monotonic()
                if now >= deadline:
                    raise new_conversations.chats.InputNotSubmitted(
                        f"新对话已创建，桌面端 {new_conversations.TAKEOVER_SECONDS} 秒内没有接管；请打开该对话后发送保留的草稿"
                    )
                if now >= reopen:
                    trace.phase("desktop_reopen", "再次在桌面打开新对话")
                    new_conversations.chats.require_send_desktop()
                    new_conversations.os.startfile("codex://threads/" + data["id"])
                    reopen = now + new_conversations.REOPEN_SECONDS
                new_conversations.time.sleep(0.5)
        settings = svc._desktop_settings(data, snapshot, trace)
        if data.get("settings"):
            settings = svc._picked(settings, data["settings"])
        trace.phase("bind", "准备首条消息与附件")
        svc._bind(rid, data)
        svc._save(rid, "dispatching", data, {"message": "正在提交首条消息…"})
        answer = svc.bridge.send(
            {
                "id": data["id"],
                "request_id": rid,
                "text": data["text"],
                "attachments": data["attachments"],
                "references": data["references"],
                "settings": settings,
            },
            timing=trace.phase,
        )
        if not (answer.get("accepted") or answer.get("delivered")):
            raise new_conversations.chats.ChatError(answer.get("text") or answer.get("message") or "首条消息结果尚未确认")

    def reconcile_new_status(self, svc, rid: str, state: str, data: dict, result: dict) -> tuple[str, dict]:
        if data.get("id") and state in ("dispatching", "unconfirmed") and svc._codex_accepted(rid, data):
            state, result = "accepted", {"message": "首条消息已送达"}
            svc._save(rid, state, data, result)
        return state, result

    def handle_new_error(self, svc, rid: str, state: str, data: dict, trace, exc: Exception) -> tuple[bool, bool]:
        if state == "dispatching" and data.get("id") and svc._late_receipt(rid, data, trace):
            trace.finish()
            svc._save(rid, "accepted", data, {"message": "首条消息已送达"})
            svc._log(data, trace, f"送达（Codex 先回了「{str(exc)[:80]}」，记录里随后有了这条消息）")
            return True, False
        safe = isinstance(exc, chats.SendNotSubmitted) and state != "dispatching"
        if state == "dispatching" and data.get("id"):
            try:
                safe = svc.bridge.receipt(data["id"], rid).get("state") == "unknown"
            except Exception:
                pass
        return False, safe

    def check_new_retry(self, svc, data: dict) -> None:
        if data.get("projectless") and not Path(data["folder"]).is_dir():
            raise chats.ChatError("无项目对话的文件夹已不在，请重新新建")

    # -- desktop & delivery hooks

    def is_our_delivery(self, rec: dict, want: str) -> bool:
        payload = rec.get("payload") or {}
        if payload.get("type") == "item_completed":
            item = payload.get("item") or {}
            if item.get("type") == "UserMessage":
                raw_text, _ = chats._unwrap_hook_prompt(chats._join_text(item.get("content")))
                return want in chats.norm(raw_text)
            if item.get("type") == "HookPrompt":
                return want in chats.norm(chats._hook_prompt_item_text(item))
            if item.get("type") == "FunctionCallOutput":
                raw_text = chats._codex_delegation_raw_text(item)
                if raw_text and want in chats.norm(raw_text):
                    return True
        if payload.get("type") == "user_message":
            raw_text, _ = chats._unwrap_hook_prompt(payload.get("message") or "")
            return want in chats.norm(raw_text)
        return False

    def desktop_send(self, desktop, item: dict, text: str, images=None, replace=None) -> None:
        desktop._send_codex(item, text)

    def desktop_open(self, desktop, item: dict) -> None:
        import os
        os.startfile(f"codex://threads/{item['id']}")
        desktop._front(chats.CODEX_PROCESS, 6.0)

    def resolve_aliases(self, server, tid: str, ids: list[str]) -> dict:
        route, backend = self._backend(server.codex)
        if route == "apptools":
            return backend.delivery_locations(tid, ids)
        return server.codex.delivery_locations(tid, ids)

    def chat_send_with_references(self, handler, body: dict) -> dict:
        raise chats.InputNotSubmitted("页面版本已过期，请刷新后通过 Codex 控制通道发送；草稿已保留")

    def _upload_for_chat(self, handler, tid: str, name: str, raw: bytes) -> dict:
        return handler.server.codex.upload(tid, name, raw, self.id)

    # -- HTTP action handlers (shared by /api/agents/codex/* and /api/codex/*)

    def _run_codex_get(self, handler, fn) -> None:
        import codex_control
        try:
            fn()
        except (codex_control.ControlError, chats.ChatError, OSError) as exc:
            handler._json({"error": str(exc)}, getattr(exc, "status", 400))

    def _run_codex_post(self, handler, body: dict, fn, *, require_running: bool = True) -> None:
        import traceback
        import codex_apptools
        import codex_control
        route, backend = self._backend(handler.server.codex)
        try:
            if require_running and route == "none":
                raise codex_apptools.AppToolsError(
                    codex_apptools.NOT_RUNNING_REASON, 409, code="codex_not_running", not_submitted=True
                )
            handler._json(fn(backend))
        except (codex_control.ControlError, chats.ChatError, OSError, ValueError, TypeError) as exc:
            not_submitted = bool(getattr(exc, "not_submitted", False))
            if isinstance(exc, codex_control.ControlError) and body.get("request_id"):
                try:
                    not_submitted = backend.receipt(str(body.get("id", "")), str(body["request_id"]))["state"] in ("unknown", "rejected")
                except Exception:
                    pass
            handler._json(
                {"error": str(exc), "not_submitted": not_submitted, "code": getattr(exc, "code", None)},
                getattr(exc, "status", 400),
            )
        except Exception:
            handler.log.write(traceback.format_exc())
            handler._json({"error": "Codex 操作结果未确认，请检查对话；不会自动重试"}, 500)

    def http_state(self, handler) -> None:
        q = handler._query()
        def run():
            tid = q.get("id", "")
            route, backend = self._backend(handler.server.codex)
            if route == "none":
                data = self._not_running_state(handler.server.codex, tid)
            else:
                data = backend.status(tid, fresh=q.get("fresh") == "1")
            if hasattr(handler.server, "tasks"):
                handler.server.tasks.observe(tid, data)
            handler._json(self.attach_capabilities_now(handler, tid, data))
        self._run_codex_get(handler, run)

    def http_receipt(self, handler) -> None:
        q = handler._query()
        def run():
            tid, rid = q.get("id", ""), q.get("request_id", "")
            route, backend = self._backend(handler.server.codex)
            if route == "apptools":
                handler._json(backend.receipt(tid, rid))
            else:
                handler._json(handler.server.codex.receipt(tid, rid))
        self._run_codex_get(handler, run)

    def http_send(self, handler, body: dict) -> None:
        import time
        def run(bridge):
            result = bridge.send(body)
            result["accepted_at"] = int(time.time() * 1000)
            return result
        self._run_codex_post(handler, body, run)

    def http_stop(self, handler, body: dict) -> None:
        payload = body
        if "turn_id" not in body and body.get("expected_turn"):
            payload = {**body, "turn_id": body["expected_turn"]}
        self._run_codex_post(handler, payload, lambda bridge: bridge.stop_turn(payload))

    def http_queue(self, handler, body: dict) -> None:
        payload = body
        if "message_id" not in body and body.get("item_id"):
            action_map = {"steer": "promote", "remove": "delete"}
            payload = {
                **body,
                "message_id": body["item_id"],
                "action": action_map.get(body.get("action"), body.get("action")),
            }
        self._run_codex_post(handler, payload, lambda bridge: bridge.queue_action(payload))

    def http_answer(self, handler, body: dict) -> None:
        self._run_codex_post(handler, body, lambda bridge: bridge.answer(body))

    def http_open(self, handler, body: dict) -> None:
        import traceback
        import codex_control
        tid = str(body.get("id", ""))
        try:
            handler.desktop.run(handler.desktop.open, self.id, tid, timeout=45)
            route, backend = self._backend(handler.server.codex, force_route=True)
            if route == "apptools":
                result = backend.confirm_open(tid)
            else:
                result = handler.server.codex.confirm_open(tid)
        except (chats.ChatError, codex_control.ControlError) as exc:
            handler._json({"ok": False, "error": str(exc), "text": str(exc),
                           "code": getattr(exc, "code", None) or None}, 400)
            return
        except TimeoutError:
            handler._json({"ok": False, "error": "超过 45 秒没做完"}, 504)
            return
        except Exception as exc:
            handler.log.write(traceback.format_exc())
            text = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"
            handler._json({"ok": False, "error": text, "text": text}, 500)
            return
        handler._json(result if isinstance(result, dict) else {"ok": True, "result": result})

    def http_legacy_get(self, handler, sub: str) -> None:
        import codex_control
        if sub == "state":
            self.http_state(handler)
            return
        if sub == "receipt":
            self.http_receipt(handler)
            return
        q = handler._query()
        bridge = handler.server.codex
        def run():
            if sub == "image":
                meta = bridge.attachment(q.get("id", ""))
                file = bridge.data_root / meta["id"] / ("thumb.png" if q.get("thumb") == "1" else "image.png")
                handler._send(200, file.read_bytes(), "image/png", {"X-Content-Type-Options": "nosniff"})
            elif sub == "attachments":
                items = []
                for ident in q.get("ids", "").split(",")[:5]:
                    try:
                        items.append(bridge.public_attachment(bridge.attachment(ident, q.get("id", ""))))
                    except codex_control.ControlError:
                        continue
                handler._json({"items": items})
            else:
                handler._json({"error": "没有这个接口"}, 404)
        self._run_codex_get(handler, run)

    def http_legacy_post(self, handler, sub: str, body: dict) -> None:
        import codex_control
        if sub == "send":
            self.http_send(handler, body)
        elif sub == "stop":
            self.http_stop(handler, body)
        elif sub == "answer":
            self.http_answer(handler, body)
        elif sub == "queue-action":
            self._run_codex_post(handler, body, lambda bridge: bridge.queue_action(body))
        elif sub == "remove-attachment":
            self._run_codex_post(
                handler, body,
                lambda _bridge: handler.server.codex.remove_attachment(str(body.get("id", "")), str(body.get("attachment", ""))),
                require_running=False,
            )
        else:
            def _missing(_bridge):
                raise codex_control.ControlError("没有这个接口", 404)
            self._run_codex_post(handler, body, _missing, require_running=False)


AGENT = CodexAgent
