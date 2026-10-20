import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_control as cc


class AsyncIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'rollout.jsonl'
        cc._async_index.clear()
        self.append({'type': 'turn_context', 'payload': {'turn_id': 'turn-1'}})
        self.question = {'type': 'response_item', 'payload': {'type': 'function_call',
            'name': 'request_user_input_async', 'call_id': 'q1',
            'arguments': json.dumps({'questions': [{'title': 'Proceed?', 'options': ['Yes', 'No']}]})}}
        self.append(self.question)

    def append(self, record):
        with self.path.open('ab') as f:
            f.write(json.dumps(record).encode() + b'\n')

    def test_question_before_large_screenshot_survives_and_poll_is_incremental(self):
        self.append({'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': 'x' * (9 << 20)}})
        self.assertEqual(cc.async_questions(self.path, 'turn-1')[0]['request_id'], 'q1')
        entry = cc._async_index[str(self.path.resolve())]
        self.assertEqual(len(entry['records']), 2)
        self.assertEqual(entry['offset'], self.path.stat().st_size)
        with patch.object(cc.json, 'loads', side_effect=AssertionError('unchanged poll must not reparse')):
            self.assertEqual(len(cc._async_question_records(self.path)), 2)

    def test_incremental_answer_and_partial_line(self):
        cc.async_questions(self.path, 'turn-1')
        reply = '<send_user_message_question_reply>' + json.dumps([{
            'questionItemId': json.dumps(['request_user_input_async', 'q1', 0]), 'answer': 'Yes'}]) + '</send_user_message_question_reply>'
        raw = json.dumps({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': reply}}).encode()
        with self.path.open('ab') as f: f.write(raw[:30])
        self.assertEqual(cc.async_questions(self.path, 'turn-1')[0]['status'], 'pending')
        with self.path.open('ab') as f: f.write(raw[30:] + b'\n')
        self.assertEqual(cc.async_questions(self.path, 'turn-1')[0]['status'], 'answered')

    def test_old_turn_not_actionable_and_truncation_clears_cache(self):
        self.assertEqual(cc.async_questions(self.path, 'turn-2'), [])
        self.path.write_bytes(b'{}\n')
        self.assertEqual(cc.async_questions(self.path, 'turn-1'), [])

    def test_tool_output_cannot_spoof_question(self):
        self.path.write_bytes(b'')
        self.append({'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': json.dumps(self.question)}})
        self.assertEqual(cc.async_questions(self.path, 'turn-1'), [])


if __name__ == '__main__':
    unittest.main()
