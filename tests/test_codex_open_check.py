"""11-17: 电脑上打开 for Codex waits until a Codex window really took the conversation (app.asar 26.1106:
thread-owner-discovery answers only from the window showing it; a window that could not resume answers no-client-found).
The phone is told why in the computer's own words, and gets that reason through status() for ten minutes after the try.
"""
import json,sqlite3,struct,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats,codex_control,remote
from codex_control import Bridge,ControlError

def not_taken():  # the class arrives with the change; read late so the old code fails each test, not the import
    return getattr(codex_control,'CodexNotTaken')

TID='01a1e40d-6797-7890-972e-182572fd5fc8'
TITLE='更新C-Brain论文材料'
NOT_TAKEN='Codex 没接手这个对话。请看电脑上这个对话有没有提示，或重启 Codex 再试'
CANNOT_CONNECT='连不上电脑上的 Codex，请确认 Codex 开着，再点「电脑上打开」'


class FakeClock:
    """time.monotonic only moves when the code sleeps, so the ten seconds of waiting cost no real time."""
    def __init__(self, start=1000.0):
        self.now=start
        self.slept=0.0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now+=seconds
        self.slept+=seconds


class OpenCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rollout=Path(self.temp.name)/'rollout.jsonl'
        self.rollout.write_text('',encoding='utf-8')
        self.item={'app':'codex','path':str(self.rollout)}
        self.bridge=Bridge()
        self.bridge.pipe=SimpleNamespace(closed=False,handle=object())
        self.lines=[]
        self.bridge.log=self.lines.append
        self.clock=FakeClock()
    def patch_time(self):
        return patch.multiple('codex_control.time',monotonic=self.clock.monotonic,sleep=self.clock.sleep)
    def confirm(self):
        """confirm_open with the fake clock and a pipe that never talks to a real Codex."""
        with self.patch_time(),patch('codex_control.codex_version',return_value='26.1106.6628.0'):
            return self.bridge.confirm_open(TID)

    # 1. The third question finds an owner, the state is readable: it can send, and the lock stayed free while waiting.
    def test_a_taken_conversation_says_it_can_send_and_the_lock_is_free_while_waiting(self):
        answers=[None,None,'owner-client']
        lock_free=[]
        def sleep(seconds):
            got=self.bridge.lock.acquire(blocking=False)
            lock_free.append(got)
            if got:self.bridge.lock.release()
            self.clock.sleep(seconds)
        self.bridge.owner=Mock(side_effect=lambda tid:answers.pop(0))
        self.bridge.status=Mock(return_value={'available':True})
        with patch.multiple('codex_control.time',monotonic=self.clock.monotonic,sleep=sleep),\
             patch('codex_control.codex_version',return_value='26.1106.6628.0'),\
             patch.object(chats,'find',return_value={'title':TITLE}):
            result=self.bridge.confirm_open(TID)
        self.assertEqual(result,{'ok':True,'text':f'电脑上已打开「{TITLE}」，可以发了'})
        self.assertEqual(self.bridge.owner.call_count,3)
        self.assertTrue(lock_free and all(lock_free),lock_free)
        self.bridge.status.assert_called_once_with(TID,fresh=True)
        self.assertEqual(self.lines,[])

    # 2. No owner ever: CodexNotTaken with the plain sentence; one log line, id/seconds/version/providers, no title.
    def test_no_owner_ever_says_so_and_writes_one_line(self):
        self.bridge.owner=Mock(return_value=None)
        with self.patch_time(),patch('codex_control.codex_version',return_value='26.1106.6628.0'),\
             patch('codex_control.thread_provider',return_value='openai'),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()) as caught:
                self.bridge.confirm_open(TID)
        self.assertEqual(caught.exception.code,'codex_not_taken')
        self.assertEqual(str(caught.exception),NOT_TAKEN)
        self.assertEqual(self.clock.slept,10.0)
        self.assertEqual(len(self.lines),1,self.lines)
        line=self.lines[0]
        for part in (TID[:8],'10.0 秒','26.1106.6628.0','遥应测过 '+codex_control.TESTED_APP_VERSION,'openai','原因不明'):
            self.assertIn(part,line)
        self.assertNotIn(TITLE,line)
        self.assertNotIn('没接手这个对话。请看电脑上这个对话',line)  # the log says its own words

    # 3. The conversation and the computer use different providers: the provider sentence, names cut at 24 characters.
    def test_a_provider_mismatch_says_which_provider_to_switch_back_to(self):
        self.bridge.owner=Mock(return_value=None)
        long_name='anthropic-'+'x'*40
        cut=long_name[:24]
        with self.patch_time(),patch('codex_control.codex_version',return_value='26.1106.6628.0'),\
             patch('codex_control.thread_provider',return_value=long_name),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()) as caught:
                self.bridge.confirm_open(TID)
        self.assertEqual(str(caught.exception),
                         f'Codex 没接手：这个对话用 {cut}，电脑上的 Codex 现在用 openai，请在电脑上切回 {cut}')
        self.assertIn('提供商不同',self.lines[0])

    # 4. No owner and a Codex newer than the one tested: the version sentence.
    def test_a_newer_codex_that_does_not_take_it_says_it_may_need_an_update(self):
        self.bridge.owner=Mock(return_value=None)
        with self.patch_time(),patch('codex_control.codex_version',return_value='26.1200.1.0'),\
             patch('codex_control.thread_provider',return_value='openai'),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()) as caught:
                self.bridge.confirm_open(TID)
        self.assertEqual(str(caught.exception),
                         'Codex 没接手。电脑上的 Codex 是 26.1200.1.0，比遥应测过的新，可能要更新遥应')
        self.assertIn('版本较新',self.lines[0])

    # 5. Owner found but the state still cannot be read: the two sentences (newer Codex, same Codex).
    def test_an_owner_whose_state_cannot_be_read_says_what_to_do(self):
        self.bridge.owner=Mock(return_value='owner-client')
        self.bridge.status=Mock(return_value={'available':False,'reason':'没有取得当前会话快照，请在电脑打开该对话后重试'})
        with self.patch_time(),patch('codex_control.codex_version',return_value='26.1200.1.0'),\
             patch('codex_control.thread_provider',return_value='openai'),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()) as caught:
                self.bridge.confirm_open(TID)
        self.assertEqual(str(caught.exception),
                         'Codex 已接手，但遥应读不到它的状态：电脑上的 Codex 是 26.1200.1.0，遥应要更新')
        self.assertIn('版本较新',self.lines[0])
        self.lines.clear()
        with self.patch_time(),patch('codex_control.codex_version',return_value='26.1106.6628.0'),\
             patch('codex_control.thread_provider',return_value='openai'),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()) as caught:
                self.bridge.confirm_open(TID)
        self.assertEqual(str(caught.exception),'Codex 已接手，但遥应还读不到它的状态，请稍后再点「电脑上打开」')
        self.assertIn('读不到状态',self.lines[0])

    # 6. The pipe never opens: it says Codex itself is not reachable, not that the conversation is not open.
    def test_a_pipe_that_never_connects_says_codex_is_not_reachable(self):
        self.bridge.owner=Mock(side_effect=ControlError('无法连接 Codex 桌面，请确认客户端已打开'))
        with self.patch_time(),patch('codex_control.codex_version',return_value=''),\
             patch('codex_control.thread_provider',return_value=''),\
             patch('codex_control.current_provider',return_value=''):
            with self.assertRaises(not_taken()) as caught:
                self.bridge.confirm_open(TID)
        self.assertEqual(str(caught.exception),CANNOT_CONNECT)
        self.assertIn('连不上',self.lines[0])

    # 7. For ten minutes after a failed try the phone gets that reason; after that the plain one; once taken, it is gone.
    def test_the_reason_last_ten_minutes_and_goes_once_taken(self):
        plain='电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试'
        self.bridge.owner=Mock(return_value=None)
        with self.patch_time(),patch('codex_control.codex_version',return_value='26.1106.6628.0'),\
             patch('codex_control.thread_provider',return_value='openai'),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()):
                self.bridge.confirm_open(TID)
        missing=ControlError(plain,code='no-client-found')
        ok=(self.item,'owner',{})
        self.bridge.snapshot=Mock(side_effect=[missing])
        with self.patch_time():
            self.assertEqual(self.bridge.status(TID)['reason'],NOT_TAKEN)
        self.clock.now+=601
        self.bridge.snapshot=Mock(side_effect=[missing])
        with self.patch_time():
            self.assertEqual(self.bridge.status(TID)['reason'],plain)
        # A conversation that is readable again has forgotten the reason: a later no-client-found says the plain words.
        self.bridge.snapshot=Mock(side_effect=[ok,missing])
        with self.patch_time():
            self.assertTrue(self.bridge.status(TID)['available'])
            self.assertEqual(self.bridge.status(TID)['reason'],plain)

    # 8. status() writes one line when a conversation stops being sendable, and one when it can send again.
    def test_status_writes_one_line_on_each_change_of_being_sendable(self):
        ok=(self.item,'owner',{})
        missing=ControlError('电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试',code='no-client-found')
        self.bridge.snapshot=Mock(side_effect=[ok,ok,missing,missing,ok])
        self.bridge.status(TID)  # first seen and sendable: nothing written
        self.bridge.status(TID)
        self.assertEqual(self.lines,[])
        self.bridge.status(TID)
        self.assertEqual(len(self.lines),1,self.lines)
        self.assertIn(f'Codex 对话 {TID[:8]}：手机发不了',self.lines[0])
        self.bridge.status(TID)  # still unavailable, same reason: no second line
        self.assertEqual(len(self.lines),1,self.lines)
        self.bridge.status(TID)
        self.assertEqual(len(self.lines),2,self.lines)
        self.assertIn(f'Codex 对话 {TID[:8]}：手机又能发了',self.lines[1])

    # 9. DesktopPipe.call: the same words as before, and a code beside them.
    def no_client_pipe(self):
        pipe=object.__new__(codex_control.DesktopPipe)
        pipe.pending={};pipe.client='test-client'
        def send(request):
            pipe.pending[request['requestId']].put({'resultType':'error','error':'no-client-found'})
        pipe._send=send
        return pipe

    def test_desktop_pipe_call_keeps_the_words_and_adds_the_code(self):
        with self.assertRaises(ControlError) as caught:
            self.no_client_pipe().call('thread-owner-discovery',{'hostId':'local','conversationId':TID})
        self.assertEqual(str(caught.exception),'电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试')
        self.assertEqual(caught.exception.code,'no-client-found')
        pipe=self.no_client_pipe()
        pipe._send=lambda request:pipe.pending[request['requestId']].put({'resultType':'error','error':'boom'})
        with self.assertRaises(ControlError) as caught:
            pipe.call('thread-owner-discovery',{'hostId':'local','conversationId':TID})
        self.assertEqual(str(caught.exception),'Codex 未完成操作：boom')
        self.assertEqual(caught.exception.code,'boom')
        pipe=self.no_client_pipe()
        with patch('codex_control.queue.Queue') as queue_type:
            queue_type.return_value.get.side_effect=__import__('queue').Empty()
            with self.assertRaises(ControlError) as caught:
                pipe.call('thread-owner-discovery',{'hostId':'local','conversationId':TID})
        self.assertEqual(str(caught.exception),'Codex 响应超时，结果未确认；不会自动重试')
        self.assertEqual(caught.exception.code,'timeout')

    # 10. The version comes from the Codex package's own folder, and comparing it is by four numbers.
    def test_the_codex_version_comes_from_its_package_folder_and_compares_by_numbers(self):
        path=r'C:\Program Files\WindowsApps\OpenAI.Codex_26.1106.6628.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe'
        self.assertEqual(codex_control._codex_version_in_path(path),'26.1106.6628.0')
        self.assertEqual(codex_control._codex_version_in_path(r'C:\Program Files\Other\app.exe'),'')
        self.assertEqual(codex_control._codex_version_in_path(''),'')
        pipe=SimpleNamespace(closed=False,handle=object())
        with patch('codex_control.win32pipe.GetNamedPipeServerProcessId',return_value=4242),\
             patch('codex_control._image_path',return_value=path) as image:
            self.assertEqual(codex_control.codex_version(pipe),'26.1106.6628.0')
            self.assertEqual(codex_control.codex_version(pipe),'26.1106.6628.0')
        self.assertEqual(image.call_count,1)  # the same pipe connection asks once
        self.assertTrue(codex_control.version_newer('26.1106.6628.0','26.1007.2314.0'))
        self.assertFalse(codex_control.version_newer('26.1007.2314.0','26.1106.6628.0'))
        self.assertTrue(codex_control.version_newer('27','26.1106.6628.0'))
        self.assertEqual(codex_control._codex_version_in_path(r'x\OpenAI.Codex_26.1106.6628.0_x64\a.exe'),'26.1106.6628.0')
        self.assertTrue(codex_control.version_newer('26.1106.6628.1','26.1106.6628.0'))
        self.assertFalse(codex_control.version_newer('26.1106.6628.0','26.1106.6628.0'))
        self.assertFalse(codex_control.version_newer('','26.1106.6628.0'))
        self.assertFalse(codex_control.version_newer('26.1106.6628.0',''))
        self.assertFalse(codex_control.version_newer('26.x','26.1106.6628.0'))

    # 11. config.toml: the profile's provider first, then the top-level one, else openai; unreadable is "unknown".
    def test_current_provider_reads_the_profile_then_the_top_level(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)
            with patch.object(chats,'CODEX_HOME',home):
                self.assertEqual(codex_control.current_provider(),'')
            config=home/'config.toml'
            config.write_text('profile = "work"\nmodel_provider = "azure"\n[profiles.work]\nmodel_provider = "bedrock"\n',encoding='utf-8')
            with patch.object(chats,'CODEX_HOME',home):
                self.assertEqual(codex_control.current_provider(),'bedrock')
            config.write_text('model_provider = "azure"\n',encoding='utf-8')
            with patch.object(chats,'CODEX_HOME',home):
                self.assertEqual(codex_control.current_provider(),'azure')
            config.write_text('profile = "missing"\n',encoding='utf-8')
            with patch.object(chats,'CODEX_HOME',home):
                self.assertEqual(codex_control.current_provider(),'openai')
            config.write_text('# nothing set\n',encoding='utf-8')
            with patch.object(chats,'CODEX_HOME',home):
                self.assertEqual(codex_control.current_provider(),'openai')
            config.write_text('this is not toml [[[\n',encoding='utf-8')
            with patch.object(chats,'CODEX_HOME',home):
                self.assertEqual(codex_control.current_provider(),'')

    # 11b. The conversation's provider comes from Codex's own thread table, read-only.
    def test_thread_provider_reads_the_conversations_own_provider(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)
            db=home/'state_5.sqlite'
            con=sqlite3.connect(db)
            con.execute('create table threads (id text primary key, model_provider text)')
            con.execute('insert into threads values (?,?)',(TID,'azure'))
            con.commit();con.close()
            with patch.object(chats,'CODEX_HOME',home):
                self.assertEqual(codex_control.thread_provider(TID),'azure')
                self.assertEqual(codex_control.thread_provider('no-such-thread'),'')
            with patch.object(chats,'CODEX_HOME',home/'missing'):
                self.assertEqual(codex_control.thread_provider(TID),'')

    # 12. /api/chat/open for Codex: open on the desktop worker, then wait outside it; failures are 400 with the code.
    def handler(self,desktop,codex):
        handler=object.__new__(remote.Handler)
        handler.server=SimpleNamespace(desktop=desktop,codex=codex,log=SimpleNamespace(write=lambda text:None))
        responses=[]
        handler._json=lambda body,status=200:responses.append((body,status))
        handler.responses=responses
        return handler

    def test_opening_a_codex_conversation_waits_outside_the_desktop_worker(self):
        desktop=SimpleNamespace(open=Mock(return_value={'ok':True,'text':'电脑上已打开「x」'}),run=Mock(return_value={'ok':True}))
        codex=SimpleNamespace(confirm_open=Mock(return_value={'ok':True,'text':f'电脑上已打开「{TITLE}」，可以发了'}))
        handler=self.handler(desktop,codex)
        handler._open_codex(TID)
        desktop.run.assert_called_once_with(desktop.open,'codex',TID,timeout=45)
        codex.confirm_open.assert_called_once_with(TID)
        self.assertEqual(handler.responses,[({'ok':True,'text':f'电脑上已打开「{TITLE}」，可以发了'},200)])

    def test_a_codex_conversation_that_is_not_taken_is_a_400_with_its_code(self):
        desktop=SimpleNamespace(open=Mock(),run=Mock(return_value={'ok':True}))
        for error,code in ((not_taken()(NOT_TAKEN),'codex_not_taken'),
                           (ControlError('无法连接 Codex 桌面，请确认客户端已打开'),None)):
            codex=SimpleNamespace(confirm_open=Mock(side_effect=error))
            handler=self.handler(desktop,codex)
            handler._open_codex(TID)
            body,status=handler.responses[0]
            self.assertEqual(status,400)
            self.assertNotEqual(status,503)
            self.assertEqual(body,{'ok':False,'error':str(error),'text':str(error),'code':code})
        desktop=SimpleNamespace(open=Mock(),run=Mock(side_effect=TimeoutError()))
        handler=self.handler(desktop,SimpleNamespace(confirm_open=Mock()))
        handler._open_codex(TID)
        self.assertEqual(handler.responses,[({'ok':False,'error':'超过 45 秒没做完'},504)])

    # 13. After Codex restarted, two threads asking for the pipe at once share one connection (the open request asks
    # outside self.lock; the one-second status reads ask inside it).
    def test_two_threads_asking_for_the_pipe_share_one_connection(self):
        made=[]
        class SlowPipe:
            def __init__(self):
                made.append(1)
                time.sleep(0.05)
                self.closed=False
        bridge=Bridge()
        with patch.object(codex_control,'DesktopPipe',SlowPipe):
            threads=[threading.Thread(target=bridge._pipe) for _ in range(4)]
            for thread in threads:thread.start()
            for thread in threads:thread.join()
        self.assertEqual(len(made),1)


class StreamVersionTests(unittest.TestCase):
    """26.1111.2228.0 raised thread-stream-state-changed from 11 to 13 and changed nothing else (11-17:
    stream-versions-1106-vs-1111.txt; the snapshot and patch shapes and the receiving code are the same, and a real
    v13 snapshot read correctly in v13-snapshot-shape.txt). The fake state below has only the fields that probe saw."""
    TID='11111111-2222-3333-4444-555555555555'

    def state(self):
        return {'id':self.TID,'hostId':'local','turnHistory':{'kind':'canonical','history':{'entitiesByKey':{}}},
                'turns':[],'requests':[],'resumeState':'resumed','historyMode':'paginated','modelProvider':'openai',
                'latestModel':'gpt-6-astra','latestReasoningEffort':'low',
                'latestCollaborationMode':{'mode':'default','settings':{'model':'gpt-6-astra','reasoning_effort':'low'}},
                'latestThreadSettings':{'model':'gpt-6-astra','effort':'low','serviceTier':None},
                'threadRuntimeStatus':{'type':'idle'}}

    def pipe(self):
        pipe=object.__new__(codex_control.DesktopPipe)
        pipe.closed=False;pipe.pending={};pipe.condition=threading.Condition()
        pipe.snapshots={};pipe.revisions={};pipe.queues={};pipe.handle=object()
        return pipe

    def snapshot(self,version=13,revision=5,state=None):
        return {'type':'broadcast','method':'thread-stream-state-changed','version':version,'sourceClientId':'owner-client',
                'params':{'hostId':'local','conversationId':self.TID,
                          'change':{'type':'snapshot','revision':revision,'conversationState':state or self.state()}}}

    def patches(self,version=13,base=5,revision=6,patches=None):
        return {'type':'broadcast','method':'thread-stream-state-changed','version':version,'sourceClientId':'owner-client',
                'params':{'hostId':'local','conversationId':self.TID,
                          'change':{'type':'patches','baseRevision':base,'revision':revision,
                                    'patches':patches or [],'acceptedTextChanges':[]}}}

    def feed(self,pipe,messages):
        """Run the real _read over these frames, its pipe reads replaced by the frames themselves."""
        frames=b''.join(struct.pack('<I',len(raw))+raw
                        for raw in (json.dumps(m,ensure_ascii=False).encode('utf-8') for m in messages))
        reads={'n':0}
        def read_file(handle,size,overlapped):
            reads['n']+=1
            return (0,frames) if reads['n']==1 else (0,b'')
        def result(handle,overlapped,wait):
            return len(frames) if reads['n']==1 else 0
        pipe.closed=False
        with patch.object(codex_control.win32file,'ReadFile',read_file),\
             patch.object(codex_control.win32file,'GetOverlappedResult',result):
            pipe._read()
        return pipe

    def test_a_version_13_snapshot_is_stored_and_status_reads_it(self):
        pipe=self.feed(self.pipe(),[self.snapshot(13)])
        self.assertIn(self.TID,pipe.snapshots)
        self.assertEqual(pipe.snapshots[self.TID][2]['latestModel'],'gpt-6-astra')
        # The reading side: the phone's status comes out of that snapshot, as on v11.
        pipe.closed=False;pipe.watches={self.TID:1}
        bridge=Bridge();bridge.pipe=pipe
        with tempfile.TemporaryDirectory() as td:
            rollout=Path(td)/'rollout.jsonl';rollout.write_text('',encoding='utf-8')
            with patch.object(chats,'find',return_value={'app':'codex','path':str(rollout)}):
                status=bridge.status(self.TID)
        self.assertTrue(status['available'])
        self.assertEqual(status['settings']['model'],'gpt-6-astra')
        self.assertEqual(status['settings']['effort'],'low')
        self.assertFalse(status['running'])

    def test_version_13_patches_follow_a_version_13_snapshot(self):
        pipe=self.feed(self.pipe(),[self.snapshot(13,revision=5),
                                    self.patches(13,base=5,revision=6,
                                                 patches=[{'op':'replace','path':['latestModel'],'value':'gpt-7'}])])
        self.assertEqual(pipe.revisions[self.TID],6)
        self.assertEqual(pipe.snapshots[self.TID][2]['latestModel'],'gpt-7')

    def test_version_11_still_works(self):
        pipe=self.feed(self.pipe(),[self.snapshot(11,revision=3)])
        self.assertIn(self.TID,pipe.snapshots)
        self.assertEqual(pipe.revisions[self.TID],3)

    def test_other_versions_are_still_thrown_away(self):
        pipe=self.pipe()
        # A snapshot kept from before is cleared by a version nobody tested; 12 and 14 are not in the tuple.
        for version in (12,14):
            pipe.snapshots[self.TID]=(time.monotonic(),'owner-client',self.state())
            pipe.revisions[self.TID]=1
            self.feed(pipe,[self.snapshot(version)])
            self.assertNotIn(self.TID,pipe.snapshots,version)
            self.assertNotIn(self.TID,pipe.revisions,version)
        self.feed(pipe,[self.snapshot(12)])
        self.assertEqual(pipe.snapshots,{})

    def test_the_tested_version_is_26_1111(self):
        self.assertEqual(codex_control.TESTED_APP_VERSION,'26.1111.2228.0')
        self.assertFalse(codex_control.version_newer('26.1111.2228.0',codex_control.TESTED_APP_VERSION))
        self.assertTrue(codex_control.version_newer('26.1112.0.0',codex_control.TESTED_APP_VERSION))

    def test_an_owner_whose_state_cannot_be_read_logs_the_states_reason(self):
        bridge=Bridge();bridge.pipe=SimpleNamespace(closed=False,handle=object())
        lines=[];bridge.log=lines.append;clock=FakeClock()
        bridge.owner=Mock(return_value='owner-client')
        reason='没有取得当前会话快照，请在电脑打开该对话后重试'
        bridge.status=Mock(return_value={'available':False,'reason':reason})
        with patch.multiple('codex_control.time',monotonic=clock.monotonic,sleep=clock.sleep),\
             patch('codex_control.codex_version',return_value='26.1111.2228.0'),\
             patch('codex_control.thread_provider',return_value='openai'),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()) as caught:
                bridge.confirm_open(self.TID)
        # The phone's words stay what they were; the log gets the state's own reason, cut at 80 characters.
        self.assertEqual(str(caught.exception),'Codex 已接手，但遥应还读不到它的状态，请稍后再点「电脑上打开」')
        self.assertIn('；状态：'+reason,lines[0])
        self.assertNotIn(reason,str(caught.exception))
        lines.clear()
        bridge.status=Mock(return_value={'available':False,'reason':'长'*100})
        with patch.multiple('codex_control.time',monotonic=clock.monotonic,sleep=clock.sleep),\
             patch('codex_control.codex_version',return_value='26.1111.2228.0'),\
             patch('codex_control.thread_provider',return_value='openai'),\
             patch('codex_control.current_provider',return_value='openai'):
            with self.assertRaises(not_taken()):
                bridge.confirm_open(self.TID)
        self.assertIn('；状态：'+'长'*80,lines[0])
        self.assertNotIn('长'*81,lines[0])


if __name__=='__main__':
    unittest.main()

