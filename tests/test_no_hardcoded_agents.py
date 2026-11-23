"""Guardrail: shared computer-side modules must not hardcode assistant IDs.

Scans the 14 shared Python files listed in plan.md §7.3 with `ast` for string
constants matching any production assistant ID in `agents.registry` (case-insensitive).
Excluded by design (per §7.3):
  - `agents/**` (each assistant's own adapter + `agents/legacy.py` legacy prefix table)
  - Per-app low-level driver modules (`codex_control.py`, `claude_control.py`,
    `deepseek_control.py`, `codex_pipe.py`, `claude_hooks.py`, etc.)
  - `tests/**`
  - Web / Android / iOS files (enabled in Steps 4 / 5 / 6 respectively)

Every remaining hit in the 14 shared files must be explicitly listed in `ALLOW`
with its enclosing scope, exact count, and reason. Adding a new hardcoded agent
branch anywhere in shared code fails this test with `file:line`.
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
)

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
}


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


if __name__ == "__main__":
    unittest.main()
