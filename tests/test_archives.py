"""Archive from the phone (archives.py, 10-20): Codex through an app-server of our own plus a broadcast to the desktop,
DeepSeek through its local interface; deleting only archived Codex conversations."""
import io, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archives
import chats
import deepseek_control


class FakeServer:
    """CodexServer as Archives uses it: records each call; a method in `refuse` answers with that error text."""
    calls, refuse = [], {}

    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        FakeServer.calls.append(('close',))

    def call(self, method, params, timeout=40):
        FakeServer.calls.append((method, params['threadId']))
        if method in FakeServer.refuse:
            raise archives.CodexRefused(FakeServer.refuse[method])
        return {}


def threads_db(path, rows):
    con = sqlite3.connect(path)
    con.execute('create table threads(id text, name text, title text, cwd text, updated_at_ms integer, updated_at integer, archived integer, '
                'archived_at integer, source text, thread_source text)')
    con.executemany('insert into threads values(?,?,?,?,?,?,?,?,?,?)', rows)
    con.commit(); con.close()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        FakeServer.calls, FakeServer.refuse = [], {}
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'state_5.sqlite'
        threads_db(self.db, [
            ('t-live', '部署方案', '', '\\\\?\\D:\\demo', 3000, 3, 0, None, 'vscode', 'user'),
            ('t-old', '', '旧的报价单\n第二行', 'D:\\demo', 2000, 2, 1, 1700000000, 'vscode', 'user'),
            ('t-exec', 'exec run', '', 'D:\\demo', 1000, 1, 1, 1700000500, 'exec', ''),
            ('t-sub', 'sub', '', 'D:\\demo', 1000, 1, 1, 1700000600, 'vscode', 'subagent')])
        self.pipe = Mock(); self.bridge = SimpleNamespace(_pipe=lambda: self.pipe)
        self.history = Mock(); self.ds = Mock(); self.ds.client.call.return_value = {'archivedSessionIds': []}
        self.archives = archives.Archives(self.bridge, self.history, server=FakeServer, deepseek=self.ds)
        for p in (patch('chats.codex_db', return_value=self.db),):
            p.start(); self.addCleanup(p.stop)

    def test_codex_archive_tells_the_desktop_and_rereads_the_lists(self):
        with patch('chats.find', return_value={'app': 'codex', 'id': 't-live'}), patch('chats.summary', return_value={'status': 'idle'}):
            self.assertTrue(self.archives.archive('codex', 't-live')['archived'])
        self.assertEqual(FakeServer.calls, [('thread/archive', 't-live'), ('close',)])
        self.pipe.broadcast.assert_called_once_with('thread-archived', 2, {'hostId': 'local', 'conversationId': 't-live'})
        self.history.invalidate.assert_called_once()

    def test_a_running_one_and_one_the_desktop_holds_are_refused(self):
        with patch('chats.find', return_value={'app': 'codex', 'id': 't-live'}), patch('chats.summary', return_value={'status': 'running'}):
            with self.assertRaises(archives.ArchiveError) as running:
                self.archives.archive('codex', 't-live')
        self.assertIn('正在运行', str(running.exception)); self.assertEqual(FakeServer.calls, [])
        FakeServer.refuse = {'thread/archive': 'thread t-live already has an active writer'}
        with patch('chats.find', return_value={'app': 'codex', 'id': 't-live'}), patch('chats.summary', return_value={'status': 'idle'}):
            with self.assertRaises(archives.ArchiveError) as held:
                self.archives.archive('codex', 't-live')
        self.assertIn('电脑上的 Codex 正开着这个对话', str(held.exception)); self.pipe.broadcast.assert_not_called()

    def test_codex_restore_only_when_archived(self):
        self.archives.unarchive('codex', 't-old')
        self.assertEqual(FakeServer.calls[0], ('thread/unarchive', 't-old'))
        self.pipe.broadcast.assert_called_once_with('thread-unarchived', 1, {'hostId': 'local', 'conversationId': 't-old'})
        FakeServer.calls = []; self.archives.unarchive('codex', 't-live'); self.assertEqual(FakeServer.calls, [])  # already back
        with self.assertRaises(archives.ArchiveError):
            self.archives.unarchive('codex', 'missing')

    def test_the_archived_list_and_who_can_be_deleted(self):
        self.ds.client.call.return_value = {'items': [
            {'sessionId': 'session-b', 'cwd': 'D:\\demo_workspace', 'updatedAt': 9, 'projections': {'values': {'title': '整理表格'}}},
            {'sessionId': 'session-sub', 'origin': 'subagent', 'projections': {'values': {'title': 'child'}}},
            {'sessionId': 'session-live', 'projections': {'values': {'title': '没归档'}}}]}
        with patch('deepseek_control.workspace_meta', return_value={'archivedSessionIds': ['session-b', 'session-sub']}):
            data = self.archives.archived()
        self.assertEqual([(v['app'], v['id'], v['can_delete']) for v in data['items']], [('codex', 't-old', True), ('deepseek', 'session-b', False)])
        self.assertEqual(data['items'][0]['title'], '旧的报价单'); self.assertEqual(data['items'][0]['archived_at'], 1700000000000)
        self.assertEqual(data['deletable'], ['codex'])

    def test_delete_takes_only_archived_codex_ones(self):
        result = self.archives.delete([{'app': 'codex', 'id': 't-old'}, {'app': 'codex', 'id': 't-live'},
                                       {'app': 'deepseek', 'id': 'session-b'}, {'app': 'codex', 'id': 'gone'}])
        self.assertEqual(FakeServer.calls, [('thread/delete', 't-old'), ('close',)])
        by = {r['id']: r for r in result['results']}
        self.assertTrue(by['t-old']['ok']); self.assertFalse(by['t-live']['ok']); self.assertIn('DeepSeek 没有删除', by['session-b']['error'])
        self.assertTrue(by['gone'].get('gone')); self.assertEqual(result['deleted'], 1)
        self.pipe.broadcast.assert_called_once_with('thread-archived', 2, {'hostId': 'local', 'conversationId': 't-old'})

    def test_deepseek_archive_restore_and_a_running_one(self):
        self.ds.find.return_value = {'id': 'session-a'}
        self.archives.archive('deepseek', 'session-a')
        self.ds.client.call.assert_called_with('workspace/archiveSession', {'request': {'sessionId': 'session-a'}})
        self.archives.unarchive('deepseek', 'session-a')
        self.ds.client.call.assert_called_with('workspace/unarchiveSession', {'request': {'sessionId': 'session-a'}})
        busy = deepseek_control.DeepSeekError('refused', 409); busy.code = 'workspace/session-active'
        self.ds.client.call.side_effect = busy
        with self.assertRaises(archives.ArchiveError) as running:
            self.archives.archive('deepseek', 'session-a')
        self.assertIn('正在运行', str(running.exception))

    def test_claude_waits(self):
        with self.assertRaises(archives.ArchiveError) as later:
            self.archives.archive('claude', 'local_x')
        self.assertIn('Claude', str(later.exception))


class WiringTests(unittest.TestCase):
    def test_deepseek_keeps_its_own_error_code(self):
        class Conn:
            def __init__(self, *a, **k): pass
            def request(self, method, url, body, headers): self.rid = json.loads(body)['rpcId']
            def getresponse(self):
                rid = self.rid
                return SimpleNamespace(status=200, read=lambda: json.dumps({'rpcId': rid, 'result': {'ok': False, 'error': {'code': 'workspace/session-active', 'message': 'busy'}}}).encode())
            def close(self): pass
        client = deepseek_control.Client(); client.connection_info = lambda: (1, 'cookie')
        with patch('deepseek_control.http.client.HTTPConnection', Conn), self.assertRaises(deepseek_control.DeepSeekError) as refused:
            client.call('workspace/archiveSession', {'request': {'sessionId': 's'}})
        self.assertEqual(refused.exception.code, 'workspace/session-active')

    def test_the_broadcast_the_desktop_reads(self):
        import codex_control
        pipe = object.__new__(codex_control.DesktopPipe); pipe.client = 'me'; pipe._send = Mock()
        pipe.broadcast('thread-archived', 2, {'hostId': 'local', 'conversationId': 't'})
        pipe._send.assert_called_once_with({'type': 'broadcast', 'sourceClientId': 'me', 'method': 'thread-archived', 'version': 2,
                                            'params': {'hostId': 'local', 'conversationId': 't'}})

    def test_delete_needs_the_phones_confirmation(self):
        import remote
        handler = object.__new__(remote.Handler); handler.path = '/api/chat/delete'; handler._authorized = lambda: True
        handler._body = lambda: {'items': [{'app': 'codex', 'id': 't'}]}
        handler.server = SimpleNamespace(machine={'voice': False}, archives=Mock()); handler._json = Mock()
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[1], 400); handler.server.archives.delete.assert_not_called()
        handler._body = lambda: {'items': [{'app': 'codex', 'id': 't'}], 'confirmed': True}; handler.server.archives.delete.return_value = {'ok': True}
        handler.do_POST(); handler.server.archives.delete.assert_called_once()


if __name__ == '__main__':
    unittest.main()
