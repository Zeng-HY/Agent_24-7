"""Test isolation: never probe the host PC's live Codex named pipes during tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_codex_pipes(monkeypatch):
    import codex_apptools

    monkeypatch.setattr(codex_apptools, "_list_pipes", lambda: ["codex-ipc"])
    codex_apptools.reset_route_cache()
    yield
    codex_apptools.reset_route_cache()
