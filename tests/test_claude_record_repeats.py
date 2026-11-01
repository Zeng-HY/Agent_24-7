"""11-01: after a /compact Claude desktop wrote 1226 old records into the same file again, every uuid twice. Read as
new lines they came back as a second copy of the old conversation (and could start and end a turn again)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats  # noqa: E402
import notify  # noqa: E402
from chat_history import Transcript  # noqa: E402


def user(uuid, ts, text):
    return json.dumps({'type': 'user', 'uuid': uuid, 'timestamp': ts,
                       'message': {'role': 'user', 'content': text}}, ensure_ascii=False).encode() + b'\n'


def answer(uuid, mid, ts, text, stop='end_turn', blocks=None):
    return json.dumps({'type': 'assistant', 'uuid': uuid, 'timestamp': ts,
                       'message': {'id': mid, 'stop_reason': stop, 'content': blocks if blocks is not None else [
                           {'type': 'text', 'text': text}]}}, ensure_ascii=False).encode() + b'\n'


OLD = (user('00000000-0000-4000-8000-000000000001', '2026-10-28T08:00:00Z', '旧问题')
       + answer('00000000-0000-4000-8000-000000000002', 'm-old', '2026-10-28T08:00:05Z', '旧回答'))
NEW = (user('00000000-0000-4000-8000-000000000003', '2026-11-01T08:00:00Z', '新问题')
       + answer('00000000-0000-4000-8000-000000000004', 'm-new', '2026-11-01T08:00:05Z', '新回答'))


class TranscriptTests(unittest.TestCase):
    def test_a_copied_block_is_not_read_as_new_talk_or_a_new_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 's.jsonl'
            path.write_bytes(OLD + NEW)  # the records the copy repeats
            record = Transcript(path, 'claude').refresh()
            self.assertIs(record.state['running'], False)
            with path.open('ab') as f:
                f.write(OLD)  # the copy, appended after the turn ended
                f.write(user('u-next', '2026-11-01T08:01:00Z', '下一件事'))
            record.refresh()
            self.assertEqual([m['text'] for m in record.messages], ['旧问题', '旧回答', '新问题', '新回答', '下一件事'])
            self.assertIs(record.state['running'], True)  # the copied "旧回答" did not end this turn
            with path.open('ab') as f:
                f.write(OLD)
            record.refresh()
            self.assertEqual([m['text'] for m in record.messages], ['旧问题', '旧回答', '新问题', '新回答', '下一件事'])
            self.assertIs(record.state['running'], True)

    def test_the_list_preview_is_not_taken_from_the_copied_block(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 's.jsonl'
            path.write_bytes(OLD + NEW + OLD)
            with mock.patch.object(chats, 'conv_path', lambda item: path):
                summary = chats.summary({'app': 'claude', 'id': 'c1'})
            self.assertEqual((summary['status'], summary['preview']), ('idle', '新回答'))

    def test_an_open_box_is_still_the_open_one(self):
        box = json.dumps({'type': 'assistant', 'uuid': 'a-box', 'timestamp': '2026-11-01T08:00:10Z',
                          'message': {'id': 'm-box', 'stop_reason': 'tool_use', 'content': [
                              {'type': 'tool_use', 'id': 'toolu_box', 'name': 'mcp__ccd_turn__wrap_up',
                               'input': {'recap': '改好了。', 'ask': '要提交吗？'}}]}}, ensure_ascii=False).encode() + b'\n'
        result = json.dumps({'type': 'user', 'uuid': 'r-box', 'timestamp': '2026-11-01T08:00:11Z',
                             'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_box',
                                                      'content': 'Nothing is pending'}]}}).encode() + b'\n'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 's.jsonl'
            path.write_bytes(OLD + user('u-new', '2026-11-01T08:00:00Z', '新问题') + box + result + OLD)
            with mock.patch.object(chats, 'conv_path', lambda item: path):
                self.assertEqual(chats.claude_open_next({'app': 'claude'})['tool_id'], 'toolu_box')


class NotifyScanTests(unittest.TestCase):
    def test_a_copied_block_does_not_begin_or_end_a_turn_again(self):
        scan = notify.new_scan('claude')
        notify.scan_lines(scan, [user('u-old', '2026-10-28T08:00:00Z', '旧问题'),
                                 answer('a-old', 'm-old', '2026-10-28T08:00:05Z', '旧回答'),
                                 user('u-new', '2026-11-01T08:00:00Z', '新问题'),
                                 answer('a-new', 'm-new', '2026-11-01T08:00:05Z', '新回答')])
        settled = dict(scan)
        notify.scan_lines(scan, [user('u-old', '2026-10-28T08:00:00Z', '旧问题'),
                                 answer('a-old', 'm-old', '2026-10-28T08:00:05Z', '旧回答')])
        self.assertEqual((scan['state'], scan['ended'], scan['key']),
                         (settled['state'], settled['ended'], settled['key']))
        self.assertEqual((scan['state'], scan['ended']), ('done', '2026-11-01T08:00:05Z'))


if __name__ == '__main__':
    unittest.main()
