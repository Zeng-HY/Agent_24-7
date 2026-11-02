"""11-02: the list's timer for a running turn. summary() reads the last 256 KB of a record and keeps the turn's start by
file, so a long turn is not searched back tens of megabytes on every poll. One turn can end and the next begin between
two polls: then the next one's start, more than 256 KB back by now, is the one to find, not the kept one (measured: a
turn begun 13:32:41 showed the 13:24:00 turn's start, 8 minutes too long). And a compaction writes old lines into the
record again: their starts, hours old, are not a new turn."""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats  # noqa: E402

KB = 1 << 10
LINE_KB = 20
OLD, T1, E1, T2, E2, T3, LAST = ('2026-11-02T' + at + 'Z' for at in (
    '04:00:00', '13:24:00', '13:31:00', '13:32:41', '13:40:00', '13:41:00', '13:45:00'))


def unix(ts):
    return int(datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp())


class ClaudeRecord:
    app = 'claude'

    def __init__(self):
        self.count = 0

    def line(self, kind, ts, **fields):
        self.count += 1
        return json.dumps({'type': kind, 'uuid': f'u-{self.count}', 'timestamp': ts, **fields}) + '\n'

    def start(self, ts, text='下一件事'):
        return self.line('user', ts, message={'role': 'user', 'content': text})

    def quiet(self, kb):
        """Big lines that say nothing of the turn: the parser passes over them, as in a real record."""
        line = json.dumps({'type': 'api-request-blob', 'hash': 'h', 'message': 'z' * (LINE_KB * KB)}) + '\n'
        return line * (kb // LINE_KB)

    def work(self, ts, kb):
        return ''.join(self.line('assistant', ts, message={'stop_reason': 'tool_use', 'content': [
            {'type': 'text', 'text': '还在做'},
            {'type': 'tool_use', 'id': f'tool-{self.count}', 'name': 'Bash', 'input': {'command': 'ls'}}]})
            + self.quiet(LINE_KB) for _ in range(kb // LINE_KB))

    def end(self, ts):
        return self.line('assistant', ts, message={'stop_reason': 'end_turn',
                                                    'content': [{'type': 'text', 'text': '好了'}]})

    def slash_command(self, ts, text):
        """How a slash command's turn begins: taken from Claude's queue, with no user line until it is done."""
        return ''.join(json.dumps({'type': 'queue-operation', 'operation': op, 'timestamp': ts, 'content': text}) + '\n'
                       for op in ('enqueue', 'dequeue'))

    def compacted(self, ts):
        """What a compaction writes after the old lines it copies."""
        return (self.line('system', ts, subtype='compact_boundary') + self.line(
            'user', ts, isCompactSummary=True, message={'role': 'user', 'content': '之前的对话摘要'}))


class CodexRecord:
    app = 'codex'

    def event(self, ts, kind, **fields):
        return json.dumps({'type': 'event_msg', 'timestamp': ts, 'payload': {'type': kind, **fields}}) + '\n'

    def start(self, ts):
        return self.event(ts, 'task_started', turn_id='t') + self.event(ts, 'user_message', message='下一件事')

    def quiet(self, kb):
        """Tools' output, which says nothing of the turn's status."""
        return (json.dumps({'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'output': 'z' * (LINE_KB * KB)}}) + '\n') * (kb // LINE_KB)

    def work(self, ts, kb):
        return ''.join(self.quiet(LINE_KB) + self.event(ts, 'agent_message', message='还在做', phase='commentary')
                       for _ in range(kb // LINE_KB))

    def end(self, ts):
        return self.event(ts, 'task_complete', turn_id='t')


class Timer:
    """The same cases for each app's record; a subclass names the record and adds what only its app has."""
    record_type = None

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'record.jsonl'
        self.path.touch()
        self.record = self.record_type()
        self.parsed = []  # bytes given to the parser, one entry a read: how far each poll went looking
        parse = chats._parse

        def counted(app, lines, context=None):
            self.parsed.append(sum(map(len, lines)))
            return parse(app, lines, context)

        # the dates here are fixed, so none may count as out of date
        for patcher in (mock.patch.object(chats, 'conv_path', lambda item: self.path),
                        mock.patch.object(chats, '_parse', counted),
                        mock.patch.object(chats, 'STALE_SECONDS', 1 << 40)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def poll(self, *written):
        with self.path.open('ab') as f:
            f.write(''.join(written).encode())
        self.parsed.clear()
        return chats.summary({'app': self.record.app, 'id': 'c1'})

    def assertTimer(self, summary, started):
        self.assertEqual((summary['status'], summary['turn_started']), ('running', unix(started)))

    def test_a_turn_begun_between_polls_times_from_its_own_start(self):
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 40)), T1)
        self.assertTimer(self.poll(r.end(E1), r.start(T2), r.work(LAST, 300)), T2)  # over 256 KB since it began

    def test_of_several_turns_between_polls_the_last_counts(self):
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 40)), T1)
        between = r.end(E1) + r.start(T2) + r.work(E2, 300) + r.end(E2) + r.start(T3) + r.work(LAST, 300)
        self.assertTimer(self.poll(between), T3)

    def test_a_growing_turn_keeps_its_start_and_only_the_end_is_read(self):
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(LAST, 300)), T1)  # its start is past the first 256 KB already
        for _ in range(4):
            self.assertTimer(self.poll(r.work(LAST, 100)), T1)
            self.assertEqual(len(self.parsed), 1)
            self.assertLessEqual(self.parsed[0], 256 * KB)

    def test_a_turn_grown_far_past_the_last_poll_is_searched_only_once(self):
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 40)), T1)
        self.assertTimer(self.poll(r.work(LAST, 2000)), T1)  # no new turn could hide in there unread
        self.assertGreater(len(self.parsed), 1)
        self.assertGreater(self.parsed[-1], 2000 * KB)
        self.assertTimer(self.poll(r.work(LAST, 100)), T1)  # and what was read is remembered
        self.assertEqual(len(self.parsed), 1)

    def test_after_an_ended_turn_the_next_has_its_own_start(self):
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 40)), T1)
        ended = self.poll(r.work(E1, 300), r.end(E1))
        self.assertEqual((ended['status'], ended['turn_ended']), ('idle', unix(E1)))
        self.assertTimer(self.poll(r.start(T2), r.work(LAST, 300)), T2)

    def test_lines_after_the_end_do_not_bring_the_turn_back(self):
        r = self.record
        self.assertEqual(self.poll(r.start(T1), r.work(T1, 40), r.end(E1), r.quiet(100))['status'], 'idle')
        self.assertEqual(self.poll(r.quiet(200))['status'], 'idle')  # the end is past the last 256 KB now

    def test_a_rewritten_file_forgets_the_kept_start(self):
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 2000)), T1)
        self.path.write_bytes((r.start(T2) + r.work(LAST, 300)).encode())  # now shorter than what was read
        self.assertTimer(self.poll(), T2)

    def test_a_start_past_the_limit_shows_no_timer_rather_than_the_kept_one(self):
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 40)), T1)
        self.assertEqual(self.poll(' ' * (65 << 20) + '\n', r.work(LAST, 100))['turn_started'], 0)


class ClaudeTimerTests(Timer, unittest.TestCase):
    record_type = ClaudeRecord

    def test_a_start_line_caught_half_written_is_not_passed_over(self):
        # a picture makes a user line hundreds of KB long. The read that stops inside it cannot parse it, and by the next
        # poll the last 256 KB start inside it too, before where the first read stopped
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 40)), T1)
        line = r.start(T2, 'x' * (400 * KB))
        self.assertTimer(self.poll(line[:300 * KB]), T1)
        self.assertTimer(self.poll(line[300 * KB:], r.work(LAST, 100)), T2)

    def test_a_start_past_the_limit_is_not_searched_on_every_poll(self):
        r = self.record
        first = self.poll(r.start(T1), ' ' * (65 << 20) + '\n', r.work(LAST, 100))
        self.assertEqual((first['status'], first['turn_started']), ('running', 0))
        self.assertEqual(len(self.parsed), 5)  # 256 KB, then 1, 4, 16 and 64 MB
        later = self.poll(r.work(LAST, 100))
        self.assertEqual((later['status'], later['turn_started']), ('running', 0))
        self.assertEqual(len(self.parsed), 1)
        self.assertTimer(self.poll(r.end(E2), r.start(T3), r.work(LAST, 40)), T3)  # the next turn has its timer again

    def test_a_record_with_no_start_at_all_shows_no_timer(self):
        self.assertEqual(self.poll(self.record.work(LAST, 40))['turn_started'], 0)

    def test_a_compaction_rewriting_old_lines_does_not_move_the_timer(self):
        # the old lines come with their old times, their originals out of reach of the last 256 KB
        r = self.record
        old = r.start(OLD) + r.end(OLD)
        self.assertEqual(self.poll(old)['status'], 'idle')
        self.assertTimer(self.poll(r.start(T1), r.work(LAST, 300)), T1)
        self.assertTimer(self.poll(old, r.compacted(LAST), r.work(LAST, 40)), T1)
        self.assertEqual(len(self.parsed), 1)
        self.assertTimer(self.poll(r.work(LAST, 100)), T1)
        self.assertTimer(self.poll(r.end(E2), r.start(T3), r.work(LAST, 40)), T3)  # the next real turn counts

    def test_a_turn_end_among_the_rewritten_lines_does_not_lose_the_timer(self):
        # the last copied line reads as an ended turn until Claude writes its next real line
        r = self.record
        old = r.start(OLD) + r.end(OLD)
        self.poll(old)
        self.assertTimer(self.poll(r.start(T1), r.work(LAST, 300)), T1)
        self.poll(old, r.compacted(LAST))
        self.assertTimer(self.poll(r.work(LAST, 40)), T1)

    def assert_timer_of_turn_that_set_off_a_compaction(self, start):
        # the old lines follow its start at once, then the compaction runs for minutes. They end on a copy of the last
        # turn's start, no older than what is kept, and their originals are out of reach of what is read
        r = self.record
        old, last_start = r.start(OLD) + r.work(OLD, 300), r.start(T1)
        self.poll(old, r.end(OLD))
        self.assertTimer(self.poll(last_start, r.work(E1, 2000)), T1)
        self.assertEqual(self.poll(r.end(E1))['status'], 'idle')
        self.assertEqual(self.poll(start, old, last_start)['turn_started'], unix(T2))
        self.assertTimer(self.poll(r.compacted(LAST), r.work(LAST, 40)), T2)
        self.assertEqual(len(self.parsed), 1)

    def test_a_message_that_set_off_a_compaction_times_from_its_own_start(self):
        self.assert_timer_of_turn_that_set_off_a_compaction(self.record.start(T2))

    def test_a_slash_command_that_set_off_a_compaction_times_from_its_own_start(self):
        self.assert_timer_of_turn_that_set_off_a_compaction(self.record.slash_command(T2, '/compact'))

    def test_a_compaction_longer_than_the_window_is_read_past_once(self):
        r = self.record
        old = r.start(OLD) + r.work(OLD, 300) + r.end(OLD)
        self.poll(old)
        self.assertTimer(self.poll(r.start(T1), r.work(LAST, 2000)), T1)
        self.assertTimer(self.poll(old, r.compacted(LAST), r.work(LAST, 40)), T1)
        self.assertGreater(len(self.parsed), 1)
        self.assertTimer(self.poll(r.work(LAST, 100)), T1)
        self.assertEqual(len(self.parsed), 1)


class CodexTimerTests(Timer, unittest.TestCase):
    record_type = CodexRecord

    def test_status_past_the_last_read_is_looked_for_not_assumed(self):
        # with the turn's end unread behind the last 256 KB, the kept start must not make it read as running
        r = self.record
        self.assertTimer(self.poll(r.start(T1), r.work(T1, 40)), T1)
        ended = self.poll(r.work(E1, 300), r.end(E1), r.work(LAST, 300))
        self.assertEqual((ended['status'], ended['turn_ended']), ('idle', unix(E1)))

    def test_notes_after_a_read_end_do_not_bring_the_turn_back(self):
        # the end was read last time and is past the last 256 KB now: an ended turn keeps no start to seem running by
        r = self.record
        self.assertEqual(self.poll(r.start(T1), r.work(T1, 40), r.end(E1), r.work(LAST, 100))['status'], 'idle')
        self.assertEqual(self.poll(r.work(LAST, 200))['status'], 'idle')

    def test_a_status_past_the_limit_is_not_searched_on_every_poll(self):
        r = self.record
        first = self.poll(r.start(T1), ' ' * (65 << 20) + '\n', r.work(LAST, 100))
        self.assertEqual((first['status'], first['turn_started']), ('unknown', 0))
        self.assertEqual(len(self.parsed), 5)  # 256 KB, then 1, 4, 16 and 64 MB
        later = self.poll(r.work(LAST, 100))  # still being written, no end in 64 MB
        self.assertEqual((later['status'], later['turn_started']), ('running', 0))
        self.assertEqual(len(self.parsed), 1)
        self.assertTimer(self.poll(r.end(E2), r.start(T3), r.work(LAST, 40)), T3)


class ReadTailTests(unittest.TestCase):
    def test_where_the_lines_start_and_the_read_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'record.jsonl'
            path.write_bytes(b'aaa\nbbb\nccc')  # 11 bytes, the last line still being written
            self.assertEqual(chats.read_tail_span(path, 100), ([b'aaa', b'bbb', b'ccc'], 0, 11))
            self.assertEqual(chats.read_tail_span(path, 11), ([b'aaa', b'bbb', b'ccc'], 0, 11))
            self.assertEqual(chats.read_tail_span(path, 5), ([b'ccc'], 8, 11))  # begins inside bbb: that line is dropped
            self.assertEqual(chats.read_tail_span(path, 2), ([], 11, 11))  # no whole line begins in the last 2 bytes
            self.assertEqual(chats.read_tail(path, 100), ([b'aaa', b'bbb', b'ccc'], True))
            self.assertEqual(chats.read_tail(path, 5), ([b'ccc'], False))


if __name__ == '__main__':
    unittest.main()
