"""0.6.6 (user 10-31): what the box offers after /, and which messages are one slash command."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import composer_commands  # noqa: E402
import notify  # noqa: E402


class CommandListTests(unittest.TestCase):
    def test_one_slash_command_and_its_words(self):
        self.assertEqual(composer_commands.parse('/compact'), ('/compact', ''))
        self.assertEqual(composer_commands.parse('  /compact  只留结论 \n'), ('/compact', '只留结论'))
        self.assertEqual(composer_commands.parse('/security-review'), ('/security-review', ''))
        for text in ('请 /compact', '/', '/ compact', '//compact', 'compact', '/123'):
            self.assertIsNone(composer_commands.parse(text), text)

    def test_codex_offers_what_runs_from_the_phone(self):
        items = composer_commands.catalog('codex', 'thread')['items']
        self.assertEqual([(v['text'], v['title'], v['input']) for v in items], [('/compact', '压缩上下文', '')])

    def test_claude_adds_its_own_commands_and_skills_once(self):
        references = Mock()
        references.skills.return_value = [
            {'name': 'deploy', 'description': '  上线\n到测试环境 ', 'scope': '个人命令'},
            {'name': 'compact', 'description': '重名的不再列', 'scope': '个人技能'},
            {'name': '带空格 的名字', 'description': 'x', 'scope': '个人技能'},
        ]
        items = composer_commands.catalog('claude', 'session', references=references)['items']
        self.assertEqual([v['text'] for v in items], ['/compact', '/init', '/review', '/security-review', '/deploy'])
        self.assertEqual((items[0]['input'], items[-1]['detail'], items[-1]['scope']), ('要保留的重点', '上线 到测试环境', '个人命令'))
        references.skills.assert_called_once_with('claude', 'session')

    def test_a_source_without_commands_offers_none(self):
        self.assertEqual(composer_commands.catalog('deepseek', 's'), {'items': []})
        self.assertEqual(composer_commands.catalog('mail', 's'), {'items': []})


class ClaudeCompactNoticeTests(unittest.TestCase):
    """The notice loop read Claude's compaction summary and its "Compacted" as new turns: after a /compact the island
    said 在干活 for twenty minutes."""

    def test_compacted_ends_what_the_command_began(self):
        scan = notify.new_scan('claude')
        notify.scan_lines(scan, [
            b'{"type":"assistant","timestamp":"2026-10-05T08:10:19Z","message":{"id":"m1","stop_reason":"end_turn","content":[{"type":"text","text":"ok"}]}}',
            b'{"type":"user","isCompactSummary":true,"timestamp":"2026-10-05T08:25:09Z","message":{"role":"user","content":"This session is being continued"}}',
            b'{"type":"user","timestamp":"2026-10-05T08:20:57Z","message":{"role":"user","content":"<command-name>/compact</command-name><command-args></command-args>"}}',
        ])
        self.assertEqual(scan['state'], 'running')
        notify.scan_lines(scan, [
            b'{"type":"user","timestamp":"2026-10-05T08:25:10Z","message":{"role":"user","content":"<local-command-stdout>Compacted </local-command-stdout>"}}',
        ])
        self.assertEqual((scan['state'], scan['ended']), ('stopped', '2026-10-05T08:25:10Z'))


class CodexCompactionTests(unittest.TestCase):
    """A Codex compaction (/compact, or Codex out of room) is the same 对话已压缩 divider Claude's is."""

    LINE = b'{"timestamp":"2026-10-31T02:32:54.401Z","type":"compacted","payload":{"message":"summary","replacement_history":[]}}\n'

    def test_the_record_reader_shows_a_divider(self):
        import chats
        msgs, _ = chats.parse_codex([self.LINE])
        self.assertEqual(msgs, [{'role': 'event', 'text': '对话已压缩', 'time': '2026-10-31T02:32:54.401Z'}])

    def test_the_page_reader_shows_it_too(self):
        import tempfile
        import chat_history
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rollout.jsonl'
            path.write_bytes(self.LINE)
            entry = chat_history.Transcript(path, 'codex').refresh()
            self.assertEqual([(m['role'], m['text']) for m in entry.messages], [('event', '对话已压缩')])


if __name__ == '__main__':
    unittest.main()
