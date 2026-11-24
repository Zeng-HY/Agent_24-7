"""The small programs packaged next to AgentRemote.exe, listed by the assistant registry.

version.py calls this module to compile each helper and to write build/agent-helpers.iss, which
setup.iss includes in [Files]. A new assistant with a helper declares it in its own module's
`helpers` and needs no change here or in the installer.
"""
from __future__ import annotations

from pathlib import Path
import sys


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def helpers() -> tuple[tuple[str, str], ...]:
    """Every (source path from the repo root, exe name) declared by the registered assistants."""
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from agents import registry

    found: list[tuple[str, str]] = []
    for agent in registry.load():
        for source, exe in getattr(agent, "helpers", ()) or ():
            found.append((str(source), str(exe)))
    return tuple(found)


def write_iss(path) -> tuple[tuple[str, str], ...]:
    """Write one [Files] line per helper for setup.iss, and return the list it was made from."""
    items = helpers()
    lines = [
        f'Source: "..\\..\\build\\{exe}"; DestDir: "{{app}}"; Flags: ignoreversion uninsneveruninstall'
        for _source, exe in items
    ]
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    return items
