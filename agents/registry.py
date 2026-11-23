"""The one list of desktop assistants.

Adding an assistant is: one module under agents/, one line in AGENT_MODULES,
and (optionally) an icon under agents/icons/. Nothing else in the service
needs to know its name.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Iterable

from .base import Agent, UnknownAgent

# One line per assistant. Order here does not matter; each manifest has `order`.
AGENT_MODULES: tuple[str, ...] = (
    "agents.codex",
    "agents.claude",
    "agents.deepseek",
)

# Test-only module: never in the production list above, and never in the frozen build.
TESTING_MODULE = "agents.testing"


def _testing_requested(include_testing: bool) -> bool:
    """The test-only assistant is for source tests; a packaged service ignores the switch."""
    if include_testing:
        return True
    if getattr(sys, "frozen", False):
        return False
    return os.environ.get("TELEPLY_TEST_AGENTS") == "1"


def load(include_testing: bool = False) -> list[Agent]:
    """Every registered module, in manifest order."""
    names = list(AGENT_MODULES)
    if _testing_requested(include_testing):
        names.append(TESTING_MODULE)
    found: list[Agent] = []
    seen: set[str] = set()
    for name in names:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError:
            if name == TESTING_MODULE:
                continue  # a frozen build has no test assistant: not an error
            raise
        factory = getattr(module, "AGENT")
        agent: Agent = factory()
        if agent.id in seen:
            raise RuntimeError(f"助手名单里重复的 id：{agent.id}")
        seen.add(agent.id)
        found.append(agent)
    return sorted(found, key=lambda a: (a.manifest()["order"], a.id))


def for_ids(ids: Iterable[str], include_testing: bool = False) -> list[Agent]:
    """The agents named by a computer's apps list, in manifest order."""
    wanted = {str(v) for v in ids}
    return [a for a in load(include_testing) if a.id in wanted]


def manifests_for(ids: Iterable[str], include_testing: bool = False) -> list[dict]:
    return [a.manifest() for a in for_ids(ids, include_testing)]


def installed(include_testing: bool = False) -> list[Agent]:
    """The agents whose desktop app is on this computer."""
    return [a for a in load(include_testing) if a.detect()]


def get(app: str, include_testing: bool = False) -> Agent:
    for agent in load(include_testing):
        if agent.id == app:
            return agent
    raise UnknownAgent(f"不认识的应用 {app}")


def ids(include_testing: bool = False) -> list[str]:
    return [a.id for a in load(include_testing)]
