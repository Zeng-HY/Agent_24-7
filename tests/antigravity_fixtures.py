"""Antigravity's own files, made up for tests: a summaries database and transcript files.

The shapes follow docs/adding-an-agent.md's Antigravity section and the real format seen on 2026-11-24;
the words, folders and conversation ids are invented. Nothing here touches a real user folder.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# The columns Antigravity writes into conversation_summaries (2026-11-24).
COLUMNS = (
    "conversation_id", "title", "preview", "step_count", "last_modified_time", "workspace_uris",
    "status", "source", "project_id", "agent_name", "parent_conversation_id", "nesting_depth",
    "battle_id", "winning_conversation_id", "not_fully_idle", "killed", "last_user_input_time",
    "last_user_input_step_index", "app_data_dir", "raw_summary", "group_id",
)

DEFAULTS = {
    "title": "测试对话",
    "preview": "测试内容",
    "step_count": 2,
    "last_modified_time": "2026-11-20 10:00:00.1234567+08:00",
    "workspace_uris": '["file:///c%3A/%E6%B5%8B%E8%AF%95/%E9%A1%B9%E7%9B%AE"]',
    "status": "CASCADE_RUN_STATUS_IDLE",
    "source": "",
    "project_id": None,
    "agent_name": None,
    "parent_conversation_id": None,
    "nesting_depth": 0,
    "battle_id": None,
    "winning_conversation_id": None,
    "not_fully_idle": 0,
    "killed": 0,
    "last_user_input_time": "2026-11-20 09:59:00.0000001+08:00",
    "last_user_input_step_index": 0,
    "app_data_dir": "测试目录",
    "raw_summary": "{}",
    "group_id": None,
}


def data_root(home: Path) -> Path:
    """The Antigravity folder under a fake machines.HOME."""
    return Path(home) / ".gemini" / "antigravity"


def row(conv_id: str, **changes) -> dict:
    values = dict(DEFAULTS)
    values["conversation_id"] = conv_id
    values.update(changes)
    return values


def record(step: int, kind: str, source: str, content=None, status: str = "DONE",
           created_at: str | None = None, **extra) -> dict:
    """One transcript line, with only the fields the reader uses and the extra ones a test names."""
    item = {
        "step_index": step,
        "source": source,
        "type": kind,
        "status": status,
        "created_at": created_at or f"2026-11-20 10:00:0{min(step, 9)}.1234567+08:00",
        "content": content,
    }
    item.update(extra)
    return item


def write(
    home: Path,
    rows: list[dict] | None = None,
    transcripts: dict[str, list[dict]] | None = None,
    full: dict[str, list[dict]] | None = None,
    columns: tuple[str, ...] = COLUMNS,
) -> Path:
    """Build the data folder [home]/.gemini/antigravity and return it."""
    root = data_root(home)
    root.mkdir(parents=True, exist_ok=True)
    database = root / "conversation_summaries.db"
    if database.exists():
        database.unlink()
    con = sqlite3.connect(database)
    try:
        con.execute("CREATE TABLE conversation_summaries (" + ", ".join(f'"{name}" TEXT' for name in columns) + ")")
        for values in rows or []:
            kept = {name: values.get(name, DEFAULTS.get(name)) for name in columns}
            con.execute(
                "INSERT INTO conversation_summaries (" + ", ".join(f'"{name}"' for name in columns) + ")"
                " VALUES (" + ", ".join("?" for _ in columns) + ")",
                [kept[name] for name in columns],
            )
        con.commit()
    finally:
        con.close()
    for conv_id, records in (transcripts or {}).items():
        folder = root / "brain" / str(conv_id) / ".system_generated" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "transcript.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    for conv_id, records in (full or {}).items():
        folder = root / "brain" / str(conv_id) / ".system_generated" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "transcript_full.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    return root
