"""Claude's questions and permission prompts, answered through Claude Code's own hook (10-27).

Claude Code posts a PermissionRequest here the moment it would ask on the desktop (a question card of AskUserQuestion,
or the prompt before a command or a file change) and shows the desktop's card at the same time. This service holds
that request open: the phone sees the question (claude_control.Controller builds its prompt from here) and its
answer goes back as the reply, which Claude Code takes and closes the desktop's card with. Answered on the PC first,
Claude Code goes on with the PC's answer and leaves the request open: the record then holds the call's result, and the
request is let go. Stop on the PC, the hook's timeout or Claude Code ending close it from that side.

Tried 10-27 on Claude 3.6556.2.0 (Claude Code 2.1.308) in a throwaway conversation: the card closed when the hook
answered, the PC's own answer won when it came first, and with nothing listening the cards worked as before (Claude
Code notes a hook error in the record, nothing shows in the window). Claude's window is not clicked, not brought to
the front and the pointer stays where it is, which the click of dev.23 needed.

The hook is one entry in Claude's user settings (~/.claude/settings.json), put there when the service starts and
taken out when Teleply is uninstalled (relay_desktop.py --remove-claude-hook); the user agreed to it on 10-27.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import chats

PATH = "/api/claude/hook/"  # + the hook key (remote_config.json "claude_hook_key"); remote.Handler serves it
HOOK_TIMEOUT = 3600         # seconds Claude Code waits on the hook; tried 10-27 with 700 (its default is 600)
WAIT_SECONDS = HOOK_TIMEOUT - 60  # the service lets go first, so Claude Code never cuts a request it still holds
NOT_HELD = {"ExitPlanMode"}  # a plan's approval wants its own input with "allow"; not tried, left to the desktop
SHOWN_AFTER = 3.0           # seconds the desktop's card may still be drawn after an answer went back
DENIED = ("The user said no to this from their phone (Teleply). Do not try it another way; stop and wait for the "
          "user's next message.")
NAV = {"back": ("Show previous question", "上一题"), "skip": ("Skip", "跳过"),
       "next": ("Next", "下一题"), "submit": ("Submit", "提交")}


def settings_file() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


class Ask:
    """One request Claude Code holds open, and the phone's answer to it as it is put together."""

    def __init__(self, item: dict, payload: dict) -> None:
        self.id = secrets.token_hex(8)
        self.item = item
        self.tool = str(payload.get("tool_name") or "")
        self.input = payload["tool_input"]
        self.suggestions = payload.get("permission_suggestions") or []
        self.done = threading.Event()
        self.reply: dict | None = None  # what goes back to Claude Code; None: no decision
        self.ended = ""                 # phone / pc / gone / late / closed
        self.call: str | None = None    # the call's id in the conversation's record, once found there
        self.seen = None                # the record's size when last looked at
        self.at = 0                     # the question shown (AskUserQuestion)
        self.answers: dict[str, object] = {}
        self.picked: list[str] = []     # what is ticked on a question that takes several

    @property
    def questions(self) -> list:
        return self.input.get("questions") if self.tool == "AskUserQuestion" else []

    def stamp(self) -> list:
        """What a tap's ticket is bound to: a tap made on what the phone showed before is refused."""
        return [self.id, self.at, [[k, v] for k, v in sorted(self.answers.items())], list(self.picked)]


class Bridge:
    link_wait = 10  # seconds a request waits for its conversation to be linked to its record (find)

    def __init__(self, log=print, notify=None, changed=None, sessions=None, record=None, clock=time.monotonic) -> None:
        self.log = log
        self.notify = notify          # notify.Notifier.asking: the phone hears that Claude waits
        self.changed = changed or (lambda tid: None)  # the controller drops what it read of this conversation
        self.sessions = sessions or (lambda: chats.claude_sessions(100000))
        self.record = record or chats.conv_path
        self.clock = clock
        self.lock = threading.Lock()
        self.asks: dict[str, Ask] = {}      # held now, oldest first
        self.answered: dict[str, float] = {}  # conversation -> when a phone answer last went back

    # -- Claude Code's side

    def find(self, session: str) -> dict | None:
        """The desktop's conversation that runs this Claude Code session. A new one is linked to its record 6-7 s
        after its first message (chats.claude_sessions), so it is looked for again for a moment."""
        deadline = self.clock() + self.link_wait
        while True:
            item = next((s for s in self.sessions() if s.get("cli") == session), None)
            if item is not None or self.clock() >= deadline:
                return item
            time.sleep(1)

    def handle(self, payload: dict, gone=lambda: False) -> dict | None:
        """One hook request, on its own connection's thread: blocks until the phone answers or the request is let go.
        gone(): whether Claude Code closed the connection. Returns the hook's reply, or None for no decision (the
        desktop's card goes on as usual)."""
        if payload.get("hook_event_name") != "PermissionRequest" or not isinstance(payload.get("tool_input"), dict):
            return None
        tool = str(payload.get("tool_name") or "")
        if not tool or tool in NOT_HELD or (tool == "AskUserQuestion" and not questions_ok(payload["tool_input"])):
            return None
        item = self.find(str(payload.get("session_id") or ""))
        if item is None:  # Claude Code in a terminal or an editor, or a conversation this service does not list
            return None
        ask = Ask(item, payload)
        with self.lock:
            self.asks[ask.id] = ask
        self.changed(item["id"])
        what = summary(ask)
        self.log(f"Claude「{item.get('title', '')}」：{what}，等手机或电脑回答")
        if self.notify:
            threading.Thread(target=self.notify, args=(item, what), daemon=True).start()
        try:
            deadline, tick = self.clock() + WAIT_SECONDS, 0
            while not ask.done.wait(.5):
                tick += 1
                reason = ("gone" if gone() else "pc" if tick % 2 == 0 and self.settled(ask)
                          else "late" if self.clock() >= deadline else "")
                if reason:
                    with self.lock:  # a tap at this very moment either went back first or is refused
                        if not ask.done.is_set():
                            ask.ended = reason
                            ask.done.set()
        finally:
            with self.lock:
                self.asks.pop(ask.id, None)
            self.changed(item["id"])
        told = {"phone": "手机上答了", "pc": "在电脑上答了", "gone": "Claude 那边不等了（停止、超时或关掉了）",
                "late": f"{WAIT_SECONDS // 60} 分钟没人答，不再等"}.get(ask.ended, ask.ended)
        self.log(f"Claude「{item.get('title', '')}」：{what}——{told}")
        return ask.reply if ask.ended == "phone" else None

    def settled(self, ask: Ask) -> bool:
        """Whether the conversation's record holds this call's result: answered on the PC (allowed, refused or the
        question answered), so Claude Code no longer waits on this request."""
        path = self.record(ask.item)
        if path is None:
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == ask.seen:
            return False
        ask.seen = size
        lines, _ = chats.read_tail(path, 2 << 20)
        calls = open_calls(lines, ask.tool)
        if ask.call is None:
            same = [cid for cid, given in calls.items() if given == ask.input]
            ask.call = same[-1] if same else next(iter(calls)) if len(calls) == 1 else None
            return False
        return ask.call not in calls

    # -- the phone's side

    def layout(self, tid: str) -> tuple[str, dict, list] | None:
        """(request id, its prompt, the stamp its taps are bound to) for the oldest request held on this conversation,
        read at one moment; None when none is held."""
        with self.lock:
            ask = next((a for a in self.asks.values() if a.item["id"] == tid and not a.done.is_set()), None)
            return (ask.id, self.prompt(ask), ask.stamp()) if ask else None

    def just_answered(self, tid: str) -> bool:
        """Whether a phone answer went back a moment ago: the desktop may still draw the card it closes."""
        return self.clock() - self.answered.get(tid, -SHOWN_AFTER) < SHOWN_AFTER

    def prompt(self, ask: Ask) -> dict:
        """The request laid out as claude_control._dock_read lays out the desktop's prompt for the phone: title,
        progress, choices, nav, other. Each part says in 'do' what a tap on it does (Controller makes it a ticket)."""
        if ask.tool != "AskUserQuestion":
            choices = [{"name": "Allow", "label": "允许", "description": "", "do": ["allow"]}]
            rules = always_rules(ask.suggestions)
            if rules:
                choices.append({"name": "Always allow", "label": "允许，以后这类不再问",
                                "description": "、".join(rules), "do": ["always"]})
            choices.append({"name": "Deny", "label": "拒绝", "description": "", "do": ["deny"]})
            return {"title": describe(ask.tool, ask.input), "progress": None, "choices": choices, "nav": [], "other": None}
        qs = ask.questions
        q = qs[ask.at]
        several, last = bool(q.get("multiSelect")), ask.at == len(qs) - 1
        choices = []
        for i, option in enumerate(q.get("options") or []):
            label = str(option.get("label") or "")
            pressed = label in ask.picked if several else ask.answers.get(q["question"]) == label
            # the phone apps do not mark what is ticked (iOS passes selected: false, Android ignores 'pressed'), so a
            # question that takes several shows it in the label
            choices.append({"name": label, "label": ("✓ " if several and pressed else "") + label,
                            "description": str(option.get("description") or ""), "pressed": pressed, "do": ["pick", i]})
        nav = [{"name": NAV["back"][0], "label": NAV["back"][1], "do": ["back"]}] if ask.at else []
        nav.append({"name": NAV["skip"][0], "label": NAV["skip"][1], "do": ["skip"]})
        if several:
            name, label = NAV["submit" if last else "next"]
            nav.append({"name": name, "label": label, "do": ["next"], "ready": bool(ask.picked)})
        return {"title": str(q.get("question") or ""), "progress": f"{ask.at + 1} / {len(qs)}" if len(qs) > 1 else None,
                "choices": choices, "nav": nav, "other": {"name": "Other"}}

    def press(self, tid: str, ask_id: str, do: list, stamp: list) -> str:
        """A tap on the phone. Returns what the phone is told; raises chats.ChatError when the request is gone or the
        phone showed something else than there is now."""
        with self.lock:
            ask = self.asks.get(ask_id)
            if ask is None or ask.item["id"] != tid or ask.done.is_set():
                raise chats.ChatError("Claude 已经不在等这个了：电脑上答过了，或者这一轮停了。刷新看看")
            if ask.stamp() != stamp:
                raise chats.ChatError("题目已经变了，刷新后再选")
            kind = do[0] if do else ""
            if ask.tool != "AskUserQuestion":
                if kind == "allow":
                    return self._finish(ask, allow({}), "已允许")
                if kind == "always":
                    return self._finish(ask, allow({"updatedPermissions": [s for s in ask.suggestions
                                                                          if s.get("type") == "addRules"]}),
                                        "已允许，以后这类不再问")
                if kind == "deny":
                    return self._finish(ask, {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
                        "behavior": "deny", "message": DENIED}}}, "已拒绝")
                raise chats.ChatError("没有这个选项")
            q = ask.questions[ask.at]
            options = [str(o.get("label") or "") for o in q.get("options") or []]
            several = bool(q.get("multiSelect"))
            if kind == "pick" and len(do) > 1 and isinstance(do[1], int) and 0 <= do[1] < len(options):
                label = options[do[1]]
                if not several:
                    ask.answers[q["question"]] = label
                    return self._advance(ask, f"已选：{label}")
                ask.picked = [o for o in options if (o in ask.picked) != (o == label)]  # tick or untick, in option order
                return ("已勾选：" if label in ask.picked else "已取消：") + label
            if kind == "back" and ask.at:
                ask.at -= 1
                self._restore(ask)
                return "回到上一题"
            if kind == "skip":
                ask.answers.pop(q["question"], None)
                return self._advance(ask, "跳过了这一题")
            if kind == "next" and several and ask.picked:
                ask.answers[q["question"]] = list(ask.picked)
                return self._advance(ask, "已选：" + "、".join(ask.picked))
            raise chats.ChatError("这一步现在点不了，刷新看看")

    def _restore(self, ask: Ask) -> None:
        q = ask.questions[ask.at]
        given = ask.answers.get(q["question"])
        ask.picked = list(given) if q.get("multiSelect") and isinstance(given, list) else []

    def _advance(self, ask: Ask, text: str) -> str:
        ask.at += 1
        if ask.at < len(ask.questions):
            self._restore(ask)
            self.changed(ask.item["id"])
            return text
        # one answer per question, by its text; several as Claude Code's documents write them: "A, B"
        answers = {k: ", ".join(v) if isinstance(v, list) else v for k, v in ask.answers.items()}
        return self._finish(ask, allow({"updatedInput": {**ask.input, "answers": answers}}),
                            text + ("，已提交" if answers else "，都没答，已告诉 Claude"))

    def _finish(self, ask: Ask, reply: dict, text: str) -> str:
        ask.reply, ask.ended = reply, "phone"
        self.answered[ask.item["id"]] = self.clock()
        ask.done.set()
        self.changed(ask.item["id"])
        return text


def allow(extra: dict) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow", **extra}}}


def questions_ok(data: dict) -> bool:
    qs = data.get("questions")
    return isinstance(qs, list) and bool(qs) and all(
        isinstance(q, dict) and isinstance(q.get("question"), str) and isinstance(q.get("options"), list) and q["options"]
        and all(isinstance(o, dict) and isinstance(o.get("label"), str) for o in q["options"]) for q in qs)


def always_rules(suggestions: list) -> list[str]:
    """The rules a "don't ask again" would add, as the settings write them: Bash(npm run lint). Only rule suggestions:
    another kind may switch the conversation's mode (setMode acceptEdits, seen 10-27)."""
    out = []
    for s in suggestions:
        if isinstance(s, dict) and s.get("type") == "addRules" and s.get("behavior") == "allow":
            for r in s.get("rules") or []:
                if isinstance(r, dict) and r.get("toolName"):
                    out.append(f"{r['toolName']}({r['ruleContent']})" if r.get("ruleContent") else str(r["toolName"]))
    return out


def describe(tool: str, data: dict) -> str:
    """What Claude asks permission for: a first line the phone shows on its own, then the details."""
    def text(value, limit=800):
        value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return value if len(value) <= limit else value[:limit] + "…"
    if tool in ("Bash", "PowerShell"):
        head, body = "Claude 想运行命令", text(data.get("command") or "")
    elif tool in ("Edit", "MultiEdit", "NotebookEdit"):
        head, body = "Claude 想改文件", text(data.get("file_path") or data.get("notebook_path") or "")
    elif tool == "Write":
        head, body = "Claude 想写文件", text(data.get("file_path") or "")
    elif tool == "WebFetch":
        head, body = "Claude 想打开网页", text(data.get("url") or "")
    elif tool == "WebSearch":
        head, body = "Claude 想上网搜索", text(data.get("query") or "")
    elif tool.startswith("mcp__"):
        parts = tool.split("__")
        head, body = f"Claude 想用 {parts[1] if len(parts) > 2 else tool} 的 {parts[-1]}", text(data, 600)
    else:
        head, body = f"Claude 想用 {tool}", text(data, 600)
    note = data.get("description") if isinstance(data.get("description"), str) else ""
    return "\n".join(p for p in (head, body, note) if p)


def summary(ask: Ask) -> str:
    """One line for the log and the phone's notification."""
    if ask.tool == "AskUserQuestion":
        return "问：" + chats.one_line(str(ask.questions[0].get("question") or ""), 80)
    return chats.one_line(describe(ask.tool, ask.input).replace("\n", "："), 90)


def open_calls(lines: list[bytes], tool: str) -> dict[str, dict]:
    """The calls of this tool in these lines of a Claude record that have no result yet: their id -> their input, in
    the order they were made."""
    calls: dict[str, dict] = {}
    needle = tool.encode()
    for raw in lines:
        if needle not in raw and b"tool_result" not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        content = (rec.get("message") or {}).get("content") if isinstance(rec, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == tool and block.get("id"):
                calls[block["id"]] = block.get("input")
            elif block.get("type") == "tool_result":
                calls.pop(block.get("tool_use_id"), None)
    return calls


# ---------------------------------------------------------------- Claude's settings


def _ours(handler) -> bool:
    url = handler.get("url") if isinstance(handler, dict) else None
    try:
        return isinstance(url, str) and PATH in url and urlsplit(url).hostname in ("127.0.0.1", "localhost")
    except ValueError:
        return False


def _read(path: Path, log) -> dict | None:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError) as exc:
        log(f"Claude 的设置读不懂，没改（{path}）：{exc}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict) \
            or not isinstance(data.get("hooks", {}).get("PermissionRequest", []), list):
        log(f"Claude 的设置不是常见的样子，没改（{path}）")
        return None
    return data


def _write(path: Path, data: dict, original: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".before-teleply")
    if original is not None and not backup.exists():  # the user's file as it was before Teleply first changed it
        backup.write_bytes(original)
    temp = path.with_name(path.name + ".teleply-tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _strip(data: dict) -> None:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get("PermissionRequest"), list):
        return
    groups = []
    for group in hooks["PermissionRequest"]:
        handlers = group.get("hooks") if isinstance(group, dict) else None
        if isinstance(handlers, list) and any(_ours(h) for h in handlers):
            group = {**group, "hooks": [h for h in handlers if not _ours(h)]}
            if not group["hooks"]:
                continue
        groups.append(group)
    if groups:
        hooks["PermissionRequest"] = groups
    else:
        del hooks["PermissionRequest"]
        if not hooks:
            del data["hooks"]


def install(url: str, log=print, path: Path | None = None) -> bool:
    """Put this service's hook into Claude's user settings, or bring an older one up to date (another port or key).
    The rest of the file stays as it is. Returns whether the file was written."""
    path = path or settings_file()
    data = _read(path, log)
    if data is None:
        return False
    entry = {"type": "http", "url": url, "timeout": HOOK_TIMEOUT}
    ours = [h for g in data.get("hooks", {}).get("PermissionRequest", []) if isinstance(g, dict)
            for h in g.get("hooks") or [] if _ours(h)]
    if ours == [entry]:
        return False
    original = path.read_bytes() if path.exists() and not ours else None  # kept once: the file before Teleply's hook
    _strip(data)
    data.setdefault("hooks", {}).setdefault("PermissionRequest", []).append({"hooks": [entry]})
    _write(path, data, original)
    log(f"Claude 的设置里加上了遥应的 hook（{path}）：Claude 问问题、要权限时先告诉遥应")
    return True


def remove(log=print, path: Path | None = None) -> bool:
    """Take this service's hook out of Claude's user settings (uninstall). Returns whether the file was written."""
    path = path or settings_file()
    data = _read(path, log)
    if not data:
        return False
    before = json.dumps(data, sort_keys=True)
    _strip(data)
    if json.dumps(data, sort_keys=True) == before:
        return False
    _write(path, data, None)
    log(f"Claude 的设置里去掉了遥应的 hook（{path}）")
    return True
