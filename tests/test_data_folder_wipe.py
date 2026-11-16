"""11-12: the data folder was wiped under a running service. A small database file opened again was made empty by
sqlite3.connect, and every table in it was gone; the unexpected error was never answered, so the phone saw 502 or a
live stream that ended at once. These tests delete each file under a temporary AR_DATA_DIR and check that the next use
works, and that an error nobody caught is answered with 500 and written to the day's log without the request's query.
"""
import http.client,io,json,shutil,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import codex_control
import codex_question_dismiss as dismiss
import deepseek_control
import live_events
import remote
from codex_control import Bridge
from composer_references import References
from new_conversations import NewConversations


def png_bytes():
    from PIL import Image
    buf=io.BytesIO();Image.new('RGB',(4,3),'red').save(buf,'PNG')
    return buf.getvalue()


class TemporaryData(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.mkdtemp(prefix='teleply-wipe-');self.addCleanup(shutil.rmtree,self.temp,True)
        self.root=Path(self.temp)

    def inside(self,path):
        """The file is one this test made; only then may it be deleted."""
        resolved=Path(path).resolve()
        self.assertTrue(resolved.is_relative_to(Path(self.temp).resolve()),resolved)
        return resolved


class NewConversationsAfterWipe(TemporaryData):
    def setUp(self):
        super().setUp()
        self.data=self.root/'data';self.data.mkdir()
        self.folder=self.root/'project';self.folder.mkdir()
        home=self.root/'home';home.mkdir()
        self.bridge=Bridge();self.bridge.data_root=self.root/'images';self.bridge.data_root.mkdir()
        self.addCleanup(self.bridge.close)
        history=SimpleNamespace(catalog=lambda:[])
        self.service=NewConversations(history,References(history,home),self.bridge,Mock(),root=self.data)
        self.service.context=lambda app,folder:str(self.folder)  # the folder list is another test's subject

    def test_draft_upload_and_submit_work_after_the_database_is_deleted(self):
        # 删-1: new-conversations.sqlite came back empty, so create_draft/upload/submit raised no such table: requests
        self.service.create_draft()
        self.inside(self.service.db).unlink()
        rid=self.service.create_draft()['request_id']
        meta=self.service.upload(rid,'photo.png',png_bytes())
        body={'request_id':rid,'app':'codex','folder':str(self.folder),'text':'hello','attachments':[meta['id']],'references':[]}
        with patch('new_conversations.threading.Thread'):
            result=self.service.submit(body)
        self.assertEqual(result['state'],'creating')
        self.assertEqual(self.service._read(rid)[0],'creating')
        with self.service._db() as con:
            tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{'requests','client_timings'})


class DeepSeekAfterWipe(TemporaryData):
    def test_once_and_receipt_work_after_the_database_is_deleted(self):
        # 删-3: deepseek-requests.sqlite was made only in Bridge.__init__, so the first send after a wipe would 502
        bridge=deepseek_control.Bridge(client=Mock(),root=self.root/'data')
        self.addCleanup(bridge.events.close)
        self.inside(bridge.db).unlink()
        rid='a'*32
        self.assertEqual(bridge.once(rid,'session-1',{'text':'hello'},lambda:{'ok':True}),{'ok':True})
        self.assertEqual(bridge.receipt(rid)['state'],'accepted')
        with bridge._db() as con:
            tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{'requests'})


class CodexStatusAfterWipe(TemporaryData):
    def test_delivery_locations_reads_a_wiped_file_as_no_records(self):
        # 5.1: delivery_locations opens the file read-only; a wiped file has no deliveries table and must not raise
        bridge=Bridge();bridge.data_root=self.root/'data';bridge.data_root.mkdir()
        self.addCleanup(bridge.close)
        (bridge.data_root/'delivery.sqlite').write_bytes(b'')
        self.assertEqual(bridge.delivery_locations('thread',['request-1']),{})

    def test_status_survives_a_deleted_database_and_makes_the_dismiss_table_again(self):
        # 删-2: delivery.sqlite kept only deliveries; status() read the dismissed question cards from desktop_dismiss
        bridge=Bridge();bridge.data_root=self.root/'data';bridge.data_root.mkdir()
        self.addCleanup(bridge.close)
        manager=dismiss.DismissManager(bridge,True,dismiss.VERIFIED_VERSION)
        manager.pool.shutdown();manager.pool=Mock()
        bridge.dismiss_manager=manager
        logged=[];bridge.log=logged.append
        rollout=self.root/'rollout.jsonl';rollout.write_text('',encoding='utf-8')
        item={'app':'codex','id':'thread','path':str(rollout)}
        state={'id':'thread','hostId':'local','title':'安排领取下载并启动新单',
               'turns':[{'turnId':'turn-1','status':'completed','items':[
                   {'type':'userInputResponse','completed':True,'requestId':'request-1',
                    'questions':[{'id':'0','question':'继续吗？','options':[{'label':'继续'},{'label':'停下'}]}],
                    'answers':{'0':'继续'}}]}]}
        self.inside(bridge.data_root/'delivery.sqlite').unlink()
        with patch.object(bridge,'snapshot',return_value=(item,'owner',state)),patch.object(codex_control.chats,'CODEX_HOME',self.root/'codex'):
            result=bridge.status('thread',fresh=True)
        self.assertTrue(result['available'],result)
        self.assertEqual([(q['id'],q['status'],q['desktop_dismiss']) for q in result['questions']],
                         [('native:turn-1:request-1','answered',None)])
        with bridge._db() as con:
            tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{'deliveries','desktop_dismiss'})
        self.assertEqual(logged,[])  # the table was made before the read, so nothing failed


class UnexpectedErrorAnswer(TemporaryData):
    def setUp(self):
        super().setUp()
        patcher=patch('remote.LOG_DIR',self.root);patcher.start();self.addCleanup(patcher.stop)
        self.server=remote.Server(('127.0.0.1',0),remote.Handler)
        self.server.cfg={'token':'TOKEN','bind':'127.0.0.1'}
        self.server.log=remote.Log();self.server.verbose=False
        self.server.machine={'voice':False,'name':'test','apps':[]}
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.addCleanup(lambda:self.server.log._file and self.server.log._file.close())  # no unclosed-file warning

    def log_text(self):
        files=list(self.root.glob('*.log'))
        self.assertEqual(len(files),1,files)
        return files[0].read_text(encoding='utf-8')

    def test_an_unexpected_error_is_answered_with_500_and_logged_without_the_query(self):
        # 删-1 和删-2 reached the phone as 502: nothing answered and nothing was written down
        def missing_table(*args,**kwargs):raise sqlite3.OperationalError('no such table: requests')
        self.server.deepseek=SimpleNamespace(receipt=missing_table)
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=5)
        self.addCleanup(connection.close)
        for _ in range(2):  # the second one proves the connection was answered, not dropped
            connection.request('GET','/api/deepseek/receipt?request_id=private-words&t=TOKEN')
            response=connection.getresponse();body=response.read()
            self.assertEqual(response.status,500)
            self.assertEqual(json.loads(body)['error'],'电脑端出错（OperationalError），已记入日志')
        text=self.log_text()
        self.assertIn('GET /api/deepseek/receipt',text)
        self.assertIn('Traceback',text)
        self.assertIn('OperationalError',text)
        self.assertNotIn('private-words',text)
        self.assertNotIn('request_id=',text)
        self.assertNotIn('TOKEN',text)

    def test_an_error_after_output_starts_closes_the_connection_without_a_second_answer(self):
        handler=object.__new__(remote.Handler)
        handler.path='/api/events?t=TOKEN'
        handler.request_version='HTTP/1.1';handler.requestline='GET /api/events HTTP/1.1'
        handler.wfile=io.BytesIO()
        handler.server=SimpleNamespace(log=remote.Log(),cfg={'token':'TOKEN','bind':'127.0.0.1'},verbose=False)
        def action():
            handler._send(200,b'partial','text/plain')
            raise RuntimeError('after the first bytes')
        handler._guarded('GET',action)
        self.assertEqual(handler.wfile.getvalue().count(b'HTTP/1.1 '),1)  # no 500 written into the stream
        self.assertTrue(handler.close_connection)
        text=self.log_text()
        self.assertIn('GET /api/events',text)
        self.assertIn('RuntimeError',text)
        self.assertNotIn('TOKEN',text)


class LiveStreamErrorLog(TemporaryData):
    def setUp(self):
        super().setUp()
        patcher=patch.dict(live_events._stream_error_at,{},clear=True);patcher.start();self.addCleanup(patcher.stop)

    def handler(self,logged):
        return SimpleNamespace(send_response=Mock(),send_header=Mock(),end_headers=Mock(),connection=Mock(),
                               wfile=io.BytesIO(),log=logged.append)

    def stream_once(self,logged):
        history=SimpleNamespace(transcript=lambda *a:({},SimpleNamespace()),conversation=lambda *a,**k:{'id':'thread','messages':[]})
        bridge=SimpleNamespace(watch=lambda *a:None,status=Mock(side_effect=RuntimeError('no such table: desktop_dismiss')))
        with patch('live_events.select.select',return_value=([],[],[])):
            live_events.stream(self.handler(logged),history,bridge,None,'codex','thread')

    def test_a_stream_that_fails_is_written_down_once_a_minute(self):
        # 11-12: live_events.stream() swallowed the error and ended the stream; the log said nothing
        logged=[]
        self.stream_once(logged);self.stream_once(logged)
        self.assertEqual(len(logged),1,logged)
        self.assertIn('实时流出错（codex thread）',logged[0])
        self.assertIn('RuntimeError',logged[0])


if __name__=='__main__':unittest.main()
