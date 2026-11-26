"""Guardrail: shared computer-side modules must not add new hardcoded assistant references.

What this test checks (using `ast`, IDs loaded from production `agents.registry`):
  1. Exact string constants matching any production assistant ID (case-insensitive)
     in `PYTHON_COMMON_FILES` (14 original shared files + `relay_controller.py` + `relay_desktop.py`).
     Every existing hit must match `ALLOW` exactly (no growth, no stale entries).
     `relay_desktop.py` has one allowed line: the packaged `--self-test` asserts that the
     three legacy assistants are in the production list.
  2. Imports of per-assistant private modules (`import <id>_...` / `from <id>_... import ...`)
     across all 16 shared files (`AST_COMMON_FILES`, including `relay_controller.py`
     and `relay_desktop.py`), locked to exact per-file counts in `FROZEN_PRIVATE_IMPORTS`.
  3. Attribute accesses matching `<id>`, `<id>_*`, or `_<id>*` (case-insensitive)
     across all 16 shared files (`AST_COMMON_FILES`), locked to exact per-file
     counts in `FROZEN_AGENT_ATTRS`.

What this test does NOT check:
  - `agents/**` (each assistant's own adapter + `agents/legacy.py` legacy prefix table)
  - Per-app low-level driver modules (`codex_*.py`, `claude_*.py`, `deepseek_*.py`)
  - `tests/**`, packaging scripts (`deploy/**`, `setup.iss`)
  - Web (`static/**`, `remote.html`), Android, and iOS files
  - Substrings inside prose/UI text, comments, or bare local/function names that are
    not exact ID string literals, private-module imports, or attribute accesses
"""

from __future__ import annotations

import ast
import unittest
from collections import Counter
from pathlib import Path

from agents import registry

ROOT = Path(__file__).resolve().parents[1]

PYTHON_COMMON_FILES = (
    "remote.py",
    "chats.py",
    "chat_history.py",
    "live_events.py",
    "notify.py",
    "new_conversations.py",
    "archives.py",
    "chat_projects.py",
    "composer_commands.py",
    "composer_references.py",
    "activity_records.py",
    "machines.py",
    "usage_limits.py",
    "activity.py",
    "relay_controller.py",
    "relay_desktop.py",
)

# All 16 shared computer-side files scanned for private-module imports and agent-named attributes.
AST_COMMON_FILES = PYTHON_COMMON_FILES

# (filename, enclosing_scope, literal) -> (exact_count, reason)
# Zero entries are allowed in remote.py, chat_history.py, notify.py,
# composer_commands.py, composer_references.py, activity_records.py,
# machines.py, and activity.py, or in any public dispatch method.
ALLOW: dict[tuple[str, str, str], tuple[int, str]] = {
    # chats.py: per-app low-level catalog/parser/desktop helpers retained for legacy imports & test patching
    ("chats.py", "_codex_rows", "codex"): (1, "Codex 底层线程读取函数构造记录行 app 字段（仅由 CodexAgent 调用）"),
    ("chats.py", "claude_main_logs", "Claude"): (2, "Windows 上 Claude 桌面版 AppData 日志目录名"),
    ("chats.py", "claude_index_dirs", "Claude"): (2, "Windows 上 Claude 桌面版 AppData 会话索引目录名"),
    ("chats.py", "claude_sessions", "claude"): (1, "Claude 底层会话读取函数构造记录行 app 字段（仅由 ClaudeAgent 调用）"),
    ("chats.py", "parse_codex", "codex"): (1, "Codex 专属记录解析函数调用步骤摘要（仅由 CodexAgent 调用）"),
    ("chats.py", "parse_claude", "claude"): (1, "Claude 专属记录解析函数调用步骤摘要（仅由 ClaudeAgent 调用）"),
    ("chats.py", "Desktop.claude_options", "claude"): (1, "Claude 专属桌面 UI 读取方法（仅由 ClaudeAgent.http_legacy_get 调用）"),
    ("chats.py", "Desktop.claude_press", "claude"): (1, "Claude 专属桌面 UI 点击方法（仅由 ClaudeAgent.http_legacy_post 调用）"),
    # live_events.py: DeepSeek-only SSE stream helper called by DeepSeekAgent.native_stream
    ("live_events.py", "deepseek_stream", "deepseek"): (4, "DeepSeek 专属实时流推送函数（仅由 DeepSeekAgent.native_stream 调用）"),
    # new_conversations.py: Windows Documents/Codex folder constant patched by tests/test_new_projectless.py
    ("new_conversations.py", "<module>", "Codex"): (1, "Windows Documents\\Codex 无项目默认目录常量（CodexAgent 使用，测试按模块变量打桩）"),
    # archives.py: per-app low-level archived-row builders called only by CodexAgent/DeepSeekAgent
    ("archives.py", "codex_rows", "codex"): (1, "Codex 底层归档列表构造记录行 app 字段（仅由 CodexAgent 调用）"),
    ("archives.py", "deepseek_archived", "deepseek"): (2, "DeepSeek 底层归档列表构造记录行与提示字段（仅由 DeepSeekAgent 调用）"),
    # chat_projects.py: Codex-only project layout/folder helper called only by CodexAgent
    ("chat_projects.py", "codex_layout", "codex"): (2, "Codex 专属项目布局缓存键（仅由 CodexAgent 调用）"),
    ("chat_projects.py", "codex_group", "Codex"): (1, "Windows Documents\\Codex 目录识别（仅由 CodexAgent 调用）"),
    # usage_limits.py: Codex wire-format rateLimitsByLimitId bucket key in Codex-only readers
    ("usage_limits.py", "_last_token_count", "codex"): (1, "Codex 用量原始协议字段 limit_id == 'codex'（仅由 CodexAgent 调用）"),
    ("usage_limits.py", "_live_snapshot", "codex"): (1, "Codex 用量原始协议字段 rateLimitsByLimitId['codex']（仅由 CodexAgent 调用）"),
    # relay_desktop.py: the packaged --self-test checks the three legacy assistants are still in the production list
    ("relay_desktop.py", "main", "codex"): (1, "打包自检：三家老助手必须在正式名单里（dev.42 漏打包的教训）"),
    ("relay_desktop.py", "main", "claude"): (1, "打包自检：三家老助手必须在正式名单里（dev.42 漏打包的教训）"),
    ("relay_desktop.py", "main", "deepseek"): (1, "打包自检：三家老助手必须在正式名单里（dev.42 漏打包的教训）"),
}

# Frozen per-file counts for importing assistant-private modules (`import <id>_...` / `from <id>_... import ...`).
# Adding a new import fails with every file:line; removing an old one also fails to remind shrinking this table.
FROZEN_PRIVATE_IMPORTS: dict[str, tuple[int, str]] = {
    "remote.py": (3, "启动时装配三家底层控制模块（服务生命周期与钩子已交给 agents/*）"),
    "live_events.py": (3, "老路线 Codex 轮次排序与 DeepSeek 专属流辅助模块"),
    "notify.py": (1, "Codex 老路线审批通知辅助引入 codex_control"),
    "new_conversations.py": (3, "新建对话读取 Codex 模型目录与 DeepSeek 底层桥接"),
    "archives.py": (2, "归档服务引入 DeepSeek 底层桥接"),
    "activity.py": (1, "Codex 桌面任务状态跟踪引入 codex_control"),
    "relay_desktop.py": (1, "Codex 弹窗收起进程入口"),
}

# Frozen per-file counts for attribute accesses matching `<id>`, `<id>_*`, or `_<id>*` (case-insensitive).
FROZEN_AGENT_ATTRS: dict[str, tuple[int, str]] = {
    "remote.py": (29, "启动与老兼容层装配及访问三家底层对象与常量（钩子服务与提示已交给 agents/*）"),
    "chats.py": (73, "Desktop 类中遗留的 Claude 桌面自动化内部方法（11-26 P6 的贴图核对与收回也是 _claude_* 方法）"),
    "live_events.py": (2, "Codex 实时消息文本清洗调用 chats.codex_answer"),
    "notify.py": (1, "通知器读取 DeepSeek 底层状态属性"),
    "new_conversations.py": (11, "新建对话访问三家底层辅助属性与常量"),
    "archives.py": (9, "归档服务访问三家底层桥接与数据库辅助方法"),
    "chat_projects.py": (2, "Codex 项目目录布局读取 CODEX_HOME 与 codex_db"),
    "usage_limits.py": (2, "用量读取访问 codex_db 与 CLAUDE_PROCESS"),
}


def _is_private_module(module_name: str | None, agent_ids: set[str]) -> bool:
    if not module_name:
        return False
    head = module_name.split(".", 1)[0].casefold()
    return any(head.startswith(aid + "_") for aid in agent_ids)


def _is_agent_attr(attr_name: str | None, agent_ids: set[str]) -> bool:
    low = (attr_name or "").casefold()
    return any(low == aid or low.startswith(aid + "_") or low.startswith("_" + aid) for aid in agent_ids)


def _scan_private_imports(path: Path, agent_ids: set[str]) -> list[tuple[int, str]]:
    """Return sorted [(lineno, module_name), ...] for assistant-private imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_private_module(alias.name, agent_ids):
                    hits.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _is_private_module(node.module, agent_ids):
                hits.append((node.lineno, str(node.module)))
    hits.sort()
    return hits


def _scan_agent_attrs(path: Path, agent_ids: set[str]) -> list[tuple[int, str]]:
    """Return sorted [(lineno, attr_name), ...] for agent-named attribute accesses."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_agent_attr(node.attr, agent_ids):
            hits.append((node.lineno, node.attr))
    hits.sort()
    return hits


def _scan_file(path: Path, agent_ids: set[str]) -> list[tuple[str, int, str, str]]:
    """Return [(filename, lineno, scope, literal), ...] for matching string constants."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[str, int, str, str]] = []
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def _visit_scoped(self, node: ast.AST, name: str) -> None:
            stack.append(name)
            try:
                self.generic_visit(node)
            finally:
                stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._visit_scoped(node, node.name)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_scoped(node, node.name)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_scoped(node, node.name)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and node.value.casefold() in agent_ids:
                scope = ".".join(stack) if stack else "<module>"
                hits.append((path.name, node.lineno, scope, node.value))

    Visitor().visit(tree)
    return hits


class NoHardcodedAgentsTests(unittest.TestCase):
    def test_shared_python_files_have_no_unapproved_hardcoded_agent_ids(self):
        agent_ids = {a.id.casefold() for a in registry.load()}
        self.assertTrue(agent_ids, "production registry must not be empty")

        actual_counts: Counter[tuple[str, str, str]] = Counter()
        locations: dict[tuple[str, str, str], list[int]] = {}
        unexpected: list[str] = []

        for filename in PYTHON_COMMON_FILES:
            path = ROOT / filename
            self.assertTrue(path.is_file(), f"expected shared module missing: {filename}")
            for fname, lineno, scope, literal in _scan_file(path, agent_ids):
                key = (fname, scope, literal)
                actual_counts[key] += 1
                locations.setdefault(key, []).append(lineno)
                if key not in ALLOW:
                    unexpected.append(f"{fname}:{lineno} ({scope}) literal={literal!r}")

        if unexpected:
            self.fail(
                "Shared Python modules contain unapproved hardcoded agent IDs:\n  "
                + "\n  ".join(unexpected)
            )

        # Also catch new hardcoded literals added inside an already-allowlisted scope
        # and stale entries left behind after further cleanup.
        over_limit: list[str] = []
        stale: list[str] = []
        for key, (expected_count, _reason) in ALLOW.items():
            seen = actual_counts.get(key, 0)
            if seen > expected_count:
                lines = ", ".join(str(n) for n in locations.get(key, []))
                over_limit.append(
                    f"{key[0]} ({key[1]}) literal={key[2]!r}: found {seen} (lines {lines}), allowed {expected_count}"
                )
            elif seen < expected_count:
                stale.append(
                    f"{key[0]} ({key[1]}) literal={key[2]!r}: found {seen}, allowlist expects {expected_count}"
                )

        if over_limit:
            self.fail("Hardcoded agent ID count exceeded allowlist:\n  " + "\n  ".join(over_limit))
        if stale:
            self.fail("Stale entries in ALLOW (update count or remove):\n  " + "\n  ".join(stale))

    def test_public_dispatch_modules_are_completely_clean(self):
        clean_modules = (
            "remote.py",
            "chat_history.py",
            "notify.py",
            "composer_commands.py",
            "composer_references.py",
            "activity_records.py",
            "machines.py",
            "activity.py",
        )
        agent_ids = {a.id.casefold() for a in registry.load()}
        for filename in clean_modules:
            hits = _scan_file(ROOT / filename, agent_ids)
            self.assertEqual(
                hits,
                [],
                f"{filename} must not contain any hardcoded agent IDs, found: {hits}",
            )

    def _assert_frozen_table(
        self,
        label: str,
        scanner,
        frozen: dict[str, tuple[int, str]],
    ) -> None:
        agent_ids = {a.id.casefold() for a in registry.load()}
        self.assertTrue(agent_ids, "production registry must not be empty")
        problems: list[str] = []
        seen_files: set[str] = set()

        for filename in AST_COMMON_FILES:
            path = ROOT / filename
            self.assertTrue(path.is_file(), f"expected shared module missing: {filename}")
            seen_files.add(filename)
            hits = scanner(path, agent_ids)
            expected = frozen.get(filename, (0, ""))[0]
            if len(hits) != expected:
                locs = ", ".join(f"{filename}:{ln} ({name})" for ln, name in hits) or "(none)"
                direction = "exceeded frozen count" if len(hits) > expected else "below frozen count (shrink table)"
                problems.append(
                    f"{filename}: {direction} — found {len(hits)}, frozen {expected}; locations: {locs}"
                )

        for filename in frozen:
            if filename not in seen_files:
                problems.append(f"{filename}: listed in frozen table but not in AST_COMMON_FILES")

        if problems:
            self.fail(f"{label} check failed:\n  " + "\n  ".join(problems))

    def test_shared_python_files_freeze_private_agent_imports(self):
        self._assert_frozen_table("Private agent module imports", _scan_private_imports, FROZEN_PRIVATE_IMPORTS)

    def test_shared_python_files_freeze_agent_named_attributes(self):
        self._assert_frozen_table("Agent-named attribute accesses", _scan_agent_attrs, FROZEN_AGENT_ATTRS)


if __name__ == "__main__":
    unittest.main()
