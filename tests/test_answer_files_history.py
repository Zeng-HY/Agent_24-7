"""B segment: answer files reach every public message and /api/chat/files (temporary records only)."""
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import chat_history
import live_events
from agents import registry


class StubAgent:
    id = "codex"
    home_list = True
    dedupe_twins = False

    def __init__(self, presented=None, page=None):
        self._presented = presented or {}
        self._page = page

    def presented_files(self, message, item):
        return self._presented.get(message.get("id"))

    def message_request_ids(self, tid):
        return {}

    def runtime(self, path):
        return {}

    def read(self, tid, **options):
        return self._page


def make_env(tmp_path, texts, app="codex", agent=None):
    agent = agent or StubAgent()
    item = {"app": app, "id": "chat-1", "title": "测试", "folder": tmp_path.name,
            "cwd": str(tmp_path), "updated": 0}
    messages = []
    for index, text in enumerate(texts):
        messages.append({"id": f"m{index}", "role": "assistant", "text": text,
                         "time": "2026-11-25T03:00:00Z", "activity_turn": "turn-1"})
    entry = SimpleNamespace(messages=messages, by_id={m["id"]: m for m in messages},
                            state={"running": False}, offset=0, size=0, mtime=0,
                            lock=threading.RLock(), context={}, agent=agent,
                            path=tmp_path / "record.jsonl", cwd=str(tmp_path),
                            app=app, tid="chat-1")
    history = chat_history.History(secret="test-only")
    history.transcript = lambda app, tid: (item, entry)
    return history, item, entry


def make(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture", encoding="utf-8")
    return path


def test_public_page_has_files_notes_and_rewritten_text(tmp_path, monkeypatch):
    image = make(tmp_path, "out/chart.png")
    agent = StubAgent()
    history, item, entry = make_env(tmp_path, [
        f"图 [看图]({image.as_posix()})，旧图 [旧](out/old.png)",
        "没有文件",
    ], agent=agent)
    entry.messages.insert(0, {"id": "u", "role": "user", "text": f"看 {image.as_posix()}"})
    entry.by_id["u"] = entry.messages[0]
    monkeypatch.setattr(registry, "get", lambda app: agent)

    page = history.conversation("codex", "chat-1")
    first, second, user = page["messages"][1], page["messages"][2], page["messages"][0]
    assert first["files"][0]["path"] == str(image)
    assert first["text"].startswith(f"图 [看图](<{image.as_posix()}>)")
    assert first["length"] == len(first["text"])
    assert first["file_notes"] == [{"href": "out/old.png", "reason": "not_found",
                                    "text": chat_history._ANSWER_REASONS["not_found"]}]
    assert second["files"] == []
    assert "files" not in user


def test_message_endpoint_returns_full_rewritten_text(tmp_path, monkeypatch):
    image = make(tmp_path, "out/chart.png")
    agent = StubAgent()
    text = ("前" * 6500) + f" [图]({image.as_posix()})"
    history, item, entry = make_env(tmp_path, [text], agent=agent)
    monkeypatch.setattr(registry, "get", lambda app: agent)

    page = history.conversation("codex", "chat-1")
    assert page["messages"][0]["truncated"] is True
    assert len(page["messages"][0]["text"]) == 6000
    full = history.message("codex", "chat-1", "m0")
    assert full["truncated"] is False
    assert len(full["text"]) == len(text) + 2  # < > around the address
    assert full["files"][0]["path"] == str(image)


def test_list_files_keeps_one_row_per_index_only_for_one_message(tmp_path, monkeypatch):
    image = make(tmp_path, "out/chart.png")
    agent = StubAgent()
    history, item, entry = make_env(tmp_path, [
        f"[a]({image.as_posix()}) [b]({image.as_posix()})",
    ], agent=agent)
    monkeypatch.setattr(registry, "get", lambda app: agent)

    rows = history.list_files("codex", "chat-1", "m0")["items"]
    assert [row["index"] for row in rows] == [0, 1]
    assert len({row["id"] for row in rows}) == 2
    assert rows[0]["view"] == "image" and rows[0]["thumb"] is False
    for key in ("name", "path", "kind", "view", "ext", "mime", "size", "modified",
                "state", "v", "line", "lang", "via", "id", "index"):
        assert key in rows[0]

    whole = history.list_files("codex", "chat-1")["items"]
    assert len(whole) == 1 and whole[0]["index"] == 0
    assert history.file("codex", "chat-1", rows[1]["id"])["path"] == image


def test_policy_refusals_are_notes_and_missing_stays_a_file(tmp_path, monkeypatch):
    secret = make(tmp_path, ".env")
    folder = tmp_path / "folder"
    folder.mkdir()
    missing = tmp_path / "missing.png"
    agent = StubAgent()
    history, item, entry = make_env(tmp_path, [
        f"[secret]({secret.as_posix()}) [folder]({folder.as_posix()}) [gone]({missing.as_posix()})",
    ], agent=agent)
    monkeypatch.setattr(registry, "get", lambda app: agent)

    page = history.conversation("codex", "chat-1")
    message = page["messages"][0]
    assert [row["path"] for row in message["files"]] == [str(missing)]
    assert message["files"][0]["state"] == "missing"
    notes = {(note["href"], note["reason"]) for note in message["file_notes"]}
    assert (secret.as_posix(), "denied") in notes
    assert (folder.as_posix(), "folder") in notes


def test_scan_runs_once_per_message_and_never_while_reading_the_record(tmp_path, monkeypatch):
    image = make(tmp_path, "out/chart.png")
    calls = []
    real = chat_history.answer_files.scan

    def counting(*args, **kwargs):
        calls.append(args[0][:20])
        return real(*args, **kwargs)

    monkeypatch.setattr(chat_history.answer_files, "scan", counting)
    agent = StubAgent()
    history, item, entry = make_env(tmp_path, [f"[图]({image.as_posix()})"], agent=agent)
    monkeypatch.setattr(registry, "get", lambda app: agent)

    history.conversation("codex", "chat-1")
    history.conversation("codex", "chat-1")
    assert len(calls) == 1
    assert calls[0].strip()


def test_a_transcript_refresh_does_not_scan(tmp_path, monkeypatch):
    image = make(tmp_path, "out/chart.png")
    line = {"type": "assistant", "uuid": "a1", "timestamp": "2026-11-25T03:00:00Z",
            "message": {"role": "assistant", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": f"[图]({image.as_posix()})"}]}}
    record = tmp_path / "record.jsonl"
    record.write_text(json.dumps(line) + "\n", encoding="utf-8")
    monkeypatch.setattr(chat_history.answer_files, "scan",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scan during refresh")))
    entry = chat_history.Transcript(record, "claude", str(tmp_path)).refresh()
    assert entry.messages[0]["text"] == f"[图]({image.as_posix()})"


def claude_record(tmp_path: Path, with_answer: bool) -> tuple[Path, Path]:
    image = make(tmp_path, "out/chart.png")
    lines = [
        {"type": "user", "uuid": "u1", "timestamp": "2026-11-25T03:00:00Z",
         "message": {"role": "user", "content": "做图"}},
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-11-25T03:00:01Z",
         "message": {"role": "assistant", "stop_reason": "tool_use", "content": [
             {"type": "text", "text": "我把图发给你。"},
             {"type": "tool_use", "id": "t1", "name": "SendUserFile",
              "input": {"files": [str(image)]}}]}},
    ]
    if with_answer:
        lines.append({"type": "assistant", "uuid": "a2", "timestamp": "2026-11-25T03:00:02Z",
                      "message": {"role": "assistant", "stop_reason": "end_turn",
                                  "content": [{"type": "text", "text": "图在 [这里](out/chart.png)。"}]}})
    record = tmp_path / "record.jsonl"
    record.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
                      encoding="utf-8")
    return record, image


def test_a_second_refresh_weighs_messages_that_already_have_a_scan_cache(tmp_path):
    image = make(tmp_path, "out/chart.png")
    first = {"type": "assistant", "uuid": "a1", "timestamp": "2026-11-25T03:00:00Z",
             "message": {"role": "assistant", "stop_reason": "end_turn",
                         "content": [{"type": "text", "text": f"[图]({image.as_posix()})"}]}}
    second = {"type": "assistant", "uuid": "a2", "timestamp": "2026-11-25T03:00:01Z",
              "message": {"role": "assistant", "stop_reason": "end_turn",
                          "content": [{"type": "text", "text": "后面的回答"}]}}
    record = tmp_path / "record.jsonl"
    record.write_text(json.dumps(first) + "\n", encoding="utf-8")
    entry = chat_history.Transcript(record, "claude", str(tmp_path)).refresh()
    history = chat_history.History(secret="test-only")
    history.public_message(entry.messages[0], item={"cwd": str(tmp_path)}, entry=entry,
                           app="claude", tid="chat-1")
    with record.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(second) + "\n")
    entry.refresh()
    assert len(entry.messages) == 2


def test_claude_send_user_file_moves_to_the_next_answer(tmp_path):
    record, image = claude_record(tmp_path, with_answer=True)
    entry = chat_history.Transcript(record, "claude", str(tmp_path)).refresh()
    answer = next(m for m in entry.messages if m["role"] == "assistant" and "图在" in m["text"])
    tool = next(m for m in entry.messages if m["role"] == "tool")
    assert answer["_presented_files"] == [str(image)]
    assert not tool.get("_presented_files")
    history = chat_history.History(secret="test-only")
    public = history.public_message(answer, item={"cwd": str(tmp_path)}, entry=entry,
                                    app="claude", tid="chat-1")
    assert public["files"][0]["path"] == str(image)
    assert "presented" in public["files"][0]["via"]


def test_claude_send_user_file_stays_on_the_tool_without_an_answer(tmp_path):
    record, image = claude_record(tmp_path, with_answer=False)
    entry = chat_history.Transcript(record, "claude", str(tmp_path)).refresh()
    tool = next(m for m in entry.messages if m["role"] == "tool")
    assert tool["_presented_files"] == [str(image)]
    history = chat_history.History(secret="test-only")
    public = history.public_message(tool, item={"cwd": str(tmp_path)}, entry=entry,
                                    app="claude", tid="chat-1")
    assert public["files"][0]["path"] == str(image)
    assert public["files"][0]["via"] == ["presented"]


def test_deepseek_presented_rows_reach_the_public_page(tmp_path, monkeypatch):
    image = make(tmp_path, "out/chart.png")
    message = {"id": "d1", "role": "assistant", "kind": "deliverables",
               "text": "成果文件：\nchart.png", "presented_files": [{"path": str(image)}]}
    page = {"app": "deepseek", "id": "chat-1", "title": "测试", "folder": tmp_path.name,
            "cwd": str(tmp_path), "updated": 0, "messages": [message]}
    agent = StubAgent(presented={"d1": [str(image)]}, page=page)
    agent.id = "deepseek"
    agent.home_list = False
    monkeypatch.setattr(registry, "get", lambda app: agent)
    history = chat_history.History(secret="test-only")

    result = history.conversation("deepseek", "chat-1")
    assert result["messages"][0]["files"][0]["path"] == str(image)
    assert result["messages"][0]["files"][0]["via"] == ["presented"]


def test_live_merge_publishes_files(tmp_path):
    image = make(tmp_path, "out/chart.png")
    item = {"cwd": str(tmp_path)}
    entry = SimpleNamespace(lock=threading.RLock(), by_id={}, messages=[], offset=0,
                            state={"running": True, "current_turn_id": "turn-1"},
                            agent=StubAgent(), cwd=str(tmp_path))
    state = {"id": "chat-1", "turns": [{
        "turnId": "turn-1", "status": "inProgress", "turnStartedAtMs": 1000,
        "items": [{"id": "live-1", "type": "agentMessage", "phase": "commentary",
                   "text": f"[图]({image.as_posix()})"}]}]}
    history = chat_history.History(secret="test-only")

    def public(message):
        return history.public_message(message, item=item, entry=entry, app="codex", tid="chat-1")

    messages, live_ids = live_events.merge_live_messages(
        {"id": "chat-1", "messages": []}, entry, state, public=public)
    assert live_ids == ["live-1"]
    assert messages[0]["files"][0]["path"] == str(image)
    assert messages[0]["text"] == f"[图](<{image.as_posix()}>)"
