"""Test isolation: never probe the host PC's live Codex named pipes or ~/.codex during tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_codex_pipes(monkeypatch, tmp_path):
    import codex_apptools
    import codex_hooks

    monkeypatch.setattr(codex_apptools, "_list_pipes", lambda: ["codex-ipc"])
    codex_apptools.reset_route_cache()
    codex_apptools.set_default_data_dir_override(tmp_path / "isolated-codex-data")
    codex_hooks.set_default_codex_home_override(tmp_path / "isolated-codex-home")
    yield
    codex_apptools.reset_route_cache()
    codex_apptools.set_default_data_dir_override(None)
    codex_hooks.set_default_codex_home_override(None)
