import sys,threading,unittest,tempfile,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,call,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
from claude_control import Controller,signature

class Edit:
    def __init__(self,value='\n',bad=False):
        self.Value=value;self.IsReadOnly=False;self.bad=bad;self.writes=[]
        # 11-17: the page around a box is its composer, the dock its Send is looked for in, and the document; the page's
        # own name is never read (a session may be titled "Side chat")
        self.composer=SimpleNamespace(Name='',ClassName='bg-surface-3 rounded-composer',ControlTypeName='GroupControl')
        self.dock=SimpleNamespace(Name='',ClassName='group/approval-dock pointer-events-auto',ControlTypeName='GroupControl')
        self.document=SimpleNamespace(Name='test - Claude Code',ClassName='',ControlTypeName='DocumentControl',GetParentControl=lambda:None)
        self.GetParentControl=lambda:self.composer
        self.composer.GetParentControl=lambda:self.dock
        self.dock.GetParentControl=lambda:self.document
    def GetValuePattern(self):return self
    def SetValue(self,text):self.writes.append(text);self.Value='a' if self.bad else text+'\n';return True

class SendTests(unittest.TestCase):
    def desktop(self,edit):
        d=object.__new__(chats.Desktop);d.input_lock=threading.Lock();d.log=Mock();d.sent_last={};d._claude_open=Mock(return_value=(1,'root'));d._claude_verified_prompt=Mock(return_value=('doc',edit))
        d._claude_show=Mock();d._keyboard_owner=Mock(return_value=None)  # never touch this PC's real windows
        submit=Mock(return_value=True);button=SimpleNamespace(ControlTypeName='ButtonControl',Name='Send',IsOffscreen=False,IsEnabled=True,GetParentControl=lambda:None,GetInvokePattern=lambda:SimpleNamespace(Invoke=submit))
        d._find=Mock(return_value=[button]);d._paste=Mock(side_effect=AssertionError('keyboard paste must not be used'))
        return d,submit
    def test_claude_send_has_no_ctrl_a_clipboard_or_enter(self):
        edit=Edit();d,submit=self.desktop(edit)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'),patch('chats.winctl.press') as press:
            d._send_claude({'id':'s','title':'test'},'中文第一行\n第二行')
        self.assertEqual(edit.writes,['中文第一行\n第二行']);submit.assert_called_once();press.assert_not_called();d._paste.assert_not_called()
        # 侧-3：Send 只在主对话框所在的 dock 里找，不再整页找
        d._find.assert_called_once_with(edit.dock,'ButtonControl','Send')
    def test_message_box_comes_from_one_query_and_must_be_the_only_one(self):
        # 10-12: walking Claude's page element by element took 0.7 s a time, and a send walked it six times or more
        def box(off=False,enabled=True):  # 11-17: a box in a dock (its own page, not a side chat's)
            edit=SimpleNamespace(Name='Prompt',ClassName='tiptap ProseMirror',ControlTypeName='EditControl',IsOffscreen=off,IsEnabled=enabled)
            composer=SimpleNamespace(Name='',ClassName='bg-surface-3 rounded-composer',ControlTypeName='GroupControl')
            dock=SimpleNamespace(Name='',ClassName='group/approval-dock pointer-events-auto',ControlTypeName='GroupControl')
            document=SimpleNamespace(Name='s - Claude Code',ClassName='',ControlTypeName='DocumentControl',GetParentControl=lambda:None)
            edit.GetParentControl=lambda:composer;composer.GetParentControl=lambda:dock;dock.GetParentControl=lambda:document
            return edit
        only=box();d=object.__new__(chats.Desktop);d._claude_document=Mock(return_value='doc')
        d._find=Mock(return_value=[only,box(True),box(False,False)])
        self.assertEqual(d._claude_verified_prompt('root','s'),('doc',only));d._find.assert_called_once_with('doc','EditControl','Prompt')
        d._find=Mock(return_value=[box(),box()])
        with self.assertRaises(chats.InputNotSubmitted):d._claude_verified_prompt('root','s')
    def test_picture_count_reads_the_part_that_holds_the_add_button(self):
        inner,outer=SimpleNamespace(),SimpleNamespace();inner.GetParentControl=lambda:outer;edit=SimpleNamespace(GetParentControl=lambda:inner)
        button=lambda name,off=False:SimpleNamespace(Name=name,IsOffscreen=off)
        def find(scope,kind,name=None):
            if scope is inner:return []
            return [button('Add')] if name=='Add' else [button('Add'),button('Remove image 1'),button('Remove attachment b.png'),button('Remove image 3',True),button('Send')]
        d=object.__new__(chats.Desktop);d._find=find;self.assertEqual(d._claude_image_count(edit),2)
    def test_find_asks_windows_once(self):
        asked=[]
        class Found:
            Length=2
            def GetElement(self,i):return f'e{i}'
        class Element:
            def FindAll(self,scope,condition):asked.append((scope,condition));return Found()
        d=object.__new__(chats.Desktop);d.uia=SimpleNamespace(CreatePropertyCondition=lambda prop,value:(prop,value),CreateAndCondition=lambda a,b:('and',a,b))
        d.auto=SimpleNamespace(PropertyId=SimpleNamespace(ControlTypeProperty='type',NameProperty='name'),ControlType=SimpleNamespace(ButtonControl=50000),
                               Control=SimpleNamespace(CreateControlFromElement=lambda e:'control '+e))
        self.assertEqual(d._find(SimpleNamespace(Element=Element()),'ButtonControl','Send'),['control e0','control e1'])
        self.assertEqual(asked,[(4,('and',('type',50000),('name','Send')))])
    def test_find_leaves_out_an_element_gone_before_it_is_read(self):
        # 10-26: one in 444 reads of the sidebar's buttons failed whole: Claude drew one anew between Windows' answer and
        # its reading. In a send, that would end it before any row is pressed or the link tried.
        failing={}
        class Found:
            Length=3
            def GetElement(self,i):return f'e{i}'
        def create(e):
            if e in failing:raise failing[e]
            return 'control '+e
        d=object.__new__(chats.Desktop);d.uia=SimpleNamespace(CreatePropertyCondition=lambda prop,value:(prop,value),CreateAndCondition=lambda a,b:('and',a,b))
        d.auto=SimpleNamespace(PropertyId=SimpleNamespace(ControlTypeProperty='type',NameProperty='name'),ControlType=SimpleNamespace(ButtonControl=50000),
                               Control=SimpleNamespace(CreateControlFromElement=create))
        scope=SimpleNamespace(Element=SimpleNamespace(FindAll=Mock(return_value=Found())))
        failing['e1']=chats.COMError(chats.ELEMENT_GONE,'事件无法调用任何订户',(None,None,None,0,None))
        self.assertEqual(d._find(scope,'ButtonControl'),['control e0','control e2'])
        scope.Element.FindAll.assert_called_once()  # still one question to Windows
        failing['e1']=chats.COMError(-2146233083,'',(None,None,None,0,None))  # UIA_E_TIMEOUT: Claude not answering, not a gone element
        with self.assertRaises(chats.COMError):d._find(scope,'ButtonControl')

    def test_clipboard_cards_count_even_when_remove_is_hover_only(self):
        node=SimpleNamespace()
        edit=SimpleNamespace(GetParentControl=lambda:node)
        button=lambda name,off=False:SimpleNamespace(Name=name,IsOffscreen=off)
        controls=[button('Add'),button('image.png',True),button('Remove image.png',True),
                  button('image.png',True),button('Remove image.png',True),button('Remove unrelated',True)]
        d=object.__new__(chats.Desktop)
        d._find=lambda scope,kind,name=None:[c for c in controls if name is None or c.Name==name]
        self.assertEqual(d._claude_image_count(edit),2)

    def test_new_environment_is_ready_only_for_exact_folder(self):
        self.assertTrue(chats.Desktop._claude_folder_ready(['Environment: project'],'project'))
        self.assertTrue(chats.Desktop._claude_folder_ready(['Local','project'],'project'))
        self.assertFalse(chats.Desktop._claude_folder_ready(['Environment: project-other'],'project'))
        self.assertFalse(chats.Desktop._claude_folder_ready(['Environment: project']*2,'project'))
        self.assertTrue(chats.Desktop._claude_folder_ready(['Environment: This computer','Folder: Choose folder…'],chats.CLAUDE_NO_FOLDER))
        self.assertFalse(chats.Desktop._claude_folder_ready(['Environment: This computer','Folder: another'],chats.CLAUDE_NO_FOLDER))

    def test_current_attachment_tray_is_outside_first_add_ancestor(self):
        composer=SimpleNamespace(ControlTypeName='GroupControl')
        inner=SimpleNamespace(GetParentControl=lambda:composer)
        edit=SimpleNamespace(GetParentControl=lambda:inner)
        button=lambda name:SimpleNamespace(Name=name,IsOffscreen=False)
        def find(scope,kind,name=None):
            if kind=='EditControl':return [edit]
            controls=[button('Add')]
            if scope is composer:controls += [button('image.png'),button('Remove image.png'),button('image.png'),button('Remove image.png')]
            return [c for c in controls if name is None or c.Name==name]
        d=object.__new__(chats.Desktop);d._find=find
        self.assertEqual(d._claude_image_count(edit),2)

    def test_first_image_failure_stops_before_second_image_and_send(self):
        edit=Edit();d,submit=self.desktop(edit)
        d._claude_image_count=Mock(return_value=0)
        d._paste_claude_image=Mock(side_effect=chats.InputNotSubmitted('attachment not confirmed'))
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):
            with self.assertRaises(chats.InputNotSubmitted):
                d._send_claude({'id':'s','title':'test'},'test',[{'path':'one.png'},{'path':'two.png'}])
        self.assertEqual(d._paste_claude_image.call_count,1)
        submit.assert_not_called()

    def test_two_images_are_sequential_and_final_count_is_required(self):
        for final_count in (1,2):
            edit=Edit();d,submit=self.desktop(edit)
            d._claude_image_count=Mock(side_effect=[0,final_count])
            d._paste_claude_image=Mock()
            with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):
                if final_count==2:d._send_claude({'id':'s','title':'test'},'test',[{'path':'one.png'},{'path':'two.png'}])
                else:
                    with self.assertRaises(chats.InputNotSubmitted):d._send_claude({'id':'s','title':'test'},'test',[{'path':'one.png'},{'path':'two.png'}])
            self.assertEqual([(v.args[-2],v.args[-1]) for v in d._paste_claude_image.call_args_list],[('one.png',1),('two.png',2)])
            self.assertEqual(submit.call_count,1 if final_count==2 else 0)
    def test_residual_letter_or_partial_write_never_sent(self):
        for edit in (Edit('a'),Edit(bad=True)):
            d,submit=self.desktop(edit)
            with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):
                with self.assertRaises(chats.InputNotSubmitted):d._send_claude({'id':'s','title':'test'},'expected complete message')
            submit.assert_not_called()
    def test_same_existing_draft_can_send_without_overwriting(self):
        edit=Edit('expected\n');d,submit=self.desktop(edit)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):d._send_claude({'id':'s','title':'test'},'expected')
        self.assertEqual(edit.writes,[]);submit.assert_called_once()
    def test_copy_of_the_last_sent_message_is_replaced_other_text_is_not(self):
        edit=Edit('按你的建议来进行\n');d,submit=self.desktop(edit);d._claude_stale_copy=Mock(return_value=True)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):d._send_claude({'id':'s','title':'test'},'下一条消息')
        self.assertEqual(edit.writes,['下一条消息']);submit.assert_called_once()
        edit=Edit('电脑上没写完的草稿\n');d,submit=self.desktop(edit);d._claude_stale_copy=Mock(return_value=False)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):
            with self.assertRaises(chats.InputNotSubmitted):d._send_claude({'id':'s','title':'test'},'下一条消息')
        self.assertEqual(edit.writes,[]);submit.assert_not_called();self.assertIn('没有覆盖',d.log.call_args[0][0])
    def test_refusal_log_says_when_the_box_is_marked_empty(self):
        class Hidden(Edit):  # the text read from the box is not on screen: its first line is marked empty
            def GetChildren(self):return [SimpleNamespace(ControlTypeName='GroupControl',ClassName='is-empty is-editor-empty')]
        edit=Hidden('别的文字\n');d,submit=self.desktop(edit);d._claude_stale_copy=Mock(return_value=False)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):
            with self.assertRaises(chats.InputNotSubmitted):d._send_claude({'id':'s','title':'test'},'下一条消息')
        self.assertIn('标着空',d.log.call_args[0][0]);submit.assert_not_called()
    def test_send_remembers_what_it_sent_there(self):
        edit=Edit();d,submit=self.desktop(edit)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):d._send_claude({'id':'s','title':'test'},'第一条')
        self.assertEqual(d.sent_last,{'s':'第一条'})
        with patch('chats.conv_path',return_value=None):
            self.assertTrue(d._claude_stale_copy({'id':'s'},'第一条\n'))
            self.assertFalse(d._claude_stale_copy({'id':'s'},'别的草稿'));self.assertFalse(d._claude_stale_copy({'id':'other'},'第一条'))
    def test_last_message_far_back_behind_a_long_turn_is_still_found(self):
        # 10-12 12:44: the last message lay 1.2 MB back, behind a turn full of screenshots; only 512 KB was read
        user={'type':'user','message':{'role':'user','content':'文件夹图标不用有颜色'},'timestamp':'2026-10-12T04:21:54Z'}
        shot={'type':'user','message':{'role':'user','content':[{'type':'tool_result','content':'x'*(200<<10)}]},'timestamp':'2026-10-12T04:30:00Z'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'s.jsonl';path.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in [user]+[shot]*6)+'\n',encoding='utf-8')
            d=object.__new__(chats.Desktop);d.sent_last={}
            with patch('chats.conv_path',return_value=path):
                self.assertTrue(d._claude_stale_copy({'id':'s'},'文件夹图标不用有颜色\n'))
                self.assertFalse(d._claude_stale_copy({'id':'s'},'电脑上没写完的草稿'))
    def test_last_prompt_line_counts_unless_cut(self):
        line=lambda p:json.dumps({'type':'last-prompt','lastPrompt':p},ensure_ascii=False).encode()
        self.assertEqual(chats.claude_last_sent([line('旧的'),line('短消息')]),['短消息'])
        self.assertEqual(chats.claude_last_sent([line('长'*200+'…')]),[])  # Claude cuts text over 200 characters
        user=json.dumps({'type':'user','message':{'role':'user','content':[{'type':'image'},{'type':'text','text':'看图'}]}},ensure_ascii=False).encode()
        self.assertEqual(chats.claude_last_sent([user,line('看图')]),['看图','看图'])
    def test_a_write_that_does_not_show_is_written_once_more(self):
        class Late(Edit):  # the first write never shows (a busy window), the second does
            def SetValue(self,text):
                self.writes.append(text)
                if len(self.writes)>1:self.Value=text+'\n'
                return True
        edit=Late();d,submit=self.desktop(edit);clock=iter(range(0,100000))
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'),patch('chats.time.sleep'),patch('chats.time.monotonic',side_effect=lambda:next(clock)*.5):
            d._send_claude({'id':'s','title':'test'},'按你的建议来进行')
        self.assertEqual(edit.writes,['按你的建议来进行']*2);submit.assert_called_once()
    def test_window_is_brought_up_before_the_box_is_read(self):
        # 10-12 20:59: minimised, the box went on reading as the message just sent; restored, it read empty in 0.1 s
        edit=Edit();d,submit=self.desktop(edit);order=Mock();order.attach_mock(d._claude_show,'show');order.attach_mock(d._claude_verified_prompt,'read')
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):d._send_claude({'id':'s','title':'test'},'第一条')
        self.assertEqual(order.mock_calls[0],call.show(1));self.assertTrue(any(c[0]=='read' for c in order.mock_calls[1:]));submit.assert_called_once()
    def test_a_box_still_catching_up_is_not_taken_for_a_draft(self):
        class CatchingUp(Edit):  # a window just brought up: the old text reads twice more, then the empty box
            def __init__(self):super().__init__();self.reads=['上一条消息\n','上一条消息\n']
            @property
            def Value(self):return self.reads.pop(0) if self.reads else self._value
            @Value.setter
            def Value(self,value):self._value=value
        edit=CatchingUp();d,submit=self.desktop(edit);d._claude_stale_copy=Mock(return_value=False)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'),patch('chats.time.sleep'):
            d._send_claude({'id':'s','title':'test'},'下一条消息')
        self.assertEqual(edit.writes,['下一条消息']);submit.assert_called_once();d._claude_stale_copy.assert_not_called()
    def test_show_brings_the_window_up_without_taking_the_keyboard(self):
        # 10-12 21:31: with Claude made the active window, an "e" typed on the PC landed in its box
        d=object.__new__(chats.Desktop)
        for iconic,covered,restored,raised in ((False,False,0,0),(True,False,1,0),(False,True,0,1),(True,True,1,1)):
            d._claude_covered=Mock(return_value=covered)
            with patch('chats.win32gui.IsIconic',return_value=iconic),patch('chats.win32gui.ShowWindow') as show,patch('chats.win32gui.SetWindowPos') as top,\
                 patch('chats.winctl.focus') as focus,patch('chats.time.sleep'):
                d._claude_show(7)
            self.assertEqual((show.call_count,top.call_count),(restored,raised),(iconic,covered));focus.assert_not_called()
            if restored:self.assertEqual(show.call_args.args,(7,chats.win32con.SW_SHOWNOACTIVATE))
            if raised:self.assertTrue(top.call_args.args[-1]&chats.win32con.SWP_NOACTIVATE)
        with patch('chats.win32gui.IsIconic',side_effect=RuntimeError('window gone')),patch('chats.winctl.focus') as focus:
            d._claude_show(7)  # never stops a send
        focus.assert_not_called()
    def test_someone_at_the_pc_gets_the_keyboard_back_after_a_send(self):
        # 10-12: writing into Claude's box made Claude the active window (Notepad in front until then)
        names={5:'notepad.exe',7:'claude.exe'}
        with patch('chats._process_of',side_effect=lambda h:names.get(h,'')),patch('chats.win32gui.GetClassName',return_value='Notepad'):
            with patch('chats.winctl.idle_seconds',return_value=10),patch('chats.win32gui.GetForegroundWindow',return_value=5):
                self.assertEqual(chats.Desktop._keyboard_owner(),5)
            with patch('chats.winctl.idle_seconds',return_value=600),patch('chats.win32gui.GetForegroundWindow',return_value=5):
                self.assertIsNone(chats.Desktop._keyboard_owner())  # nobody at the PC: Claude may stay in front
            with patch('chats.winctl.idle_seconds',return_value=10),patch('chats.win32gui.GetForegroundWindow',return_value=7):
                self.assertIsNone(chats.Desktop._keyboard_owner())  # Claude was the one in use
            for front,given in ((7,1),(5,0)):
                with patch('chats.win32gui.GetForegroundWindow',return_value=front),patch('chats.win32gui.IsWindow',return_value=True),\
                     patch('chats.win32gui.IsIconic',return_value=False),patch('chats.winctl.focus') as focus:
                    chats.Desktop._give_back_keyboard(5)
                self.assertEqual(focus.call_count,given,front)
        edit=Edit('别人的草稿\n');d,submit=self.desktop(edit);d._claude_stale_copy=Mock(return_value=False);d._keyboard_owner=Mock(return_value=5);d._give_back_keyboard=Mock()
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'),patch('chats.time.sleep'):
            with self.assertRaises(chats.DesktopDraft):d._send_claude({'id':'s','title':'test'},'下一条消息')
        d._give_back_keyboard.assert_called_once_with(5)  # given back whether the send went or not
    def test_reading_restores_a_minimised_window_and_nothing_more(self):
        d=object.__new__(chats.Desktop)
        for iconic,restored in ((True,1),(False,0)):
            with patch('chats.app_window',return_value=7),patch('chats.win32gui.IsIconic',return_value=iconic),patch('chats.win32gui.ShowWindow') as show,\
                 patch('chats.win32gui.SetWindowPos') as top,patch('chats.time.sleep'):
                self.assertEqual(d._claude_unminimize(),bool(restored))
            self.assertEqual(show.call_count,restored);top.assert_not_called()
    def test_covered_only_when_no_part_of_the_window_shows(self):
        with patch('chats.win32gui.GetWindowRect',return_value=(0,0,1000,800)),patch('chats.win32gui.GetAncestor',side_effect=lambda h,flag:h):
            with patch('chats.win32gui.WindowFromPoint',return_value=99):self.assertTrue(chats.Desktop._claude_covered(7))
            with patch('chats.win32gui.WindowFromPoint',side_effect=[99,7,99]):self.assertFalse(chats.Desktop._claude_covered(7))
    def test_text_in_the_box_goes_only_when_the_phone_named_it(self):
        edit=Edit('e\n');d,submit=self.desktop(edit);d._claude_stale_copy=Mock(return_value=False)
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'),patch('chats.time.sleep'):
            with self.assertRaises(chats.DesktopDraft) as refused:d._send_claude({'id':'s','title':'test'},'下一条消息')
            self.assertEqual((refused.exception.draft,refused.exception.code),('e','desktop_draft'));submit.assert_not_called()
            with self.assertRaises(chats.DesktopDraft):d._send_claude({'id':'s','title':'test'},'下一条消息',replace='别的字')  # not what is there
            submit.assert_not_called();self.assertEqual(edit.writes,[])
            d._send_claude({'id':'s','title':'test'},'下一条消息',replace='e')
        self.assertEqual(edit.writes,['下一条消息']);submit.assert_called_once();self.assertIn('按手机上的确认',d.log.call_args_list[-1].args[0])
    def test_the_phone_is_told_what_sits_in_the_box_and_can_name_it(self):
        import remote
        handler=object.__new__(remote.Handler);responses=[]
        handler._json=lambda body,status=200:responses.append((body,status))
        handler.server=SimpleNamespace(desktop=SimpleNamespace(run=lambda fn,*a,timeout=60:fn(*a)))
        def refuse():raise chats.DesktopDraft('电脑上 Claude 的输入框里有别的字','e')
        handler._chat_call(refuse)
        self.assertEqual((responses[0][1],responses[0][0]['code'],responses[0][0]['draft'],responses[0][0]['not_submitted']),(400,'desktop_draft','e',True))
        sent=Mock(return_value={'ok':True});handler.server=SimpleNamespace(desktop=SimpleNamespace(send=sent))
        handler._send_with_references({'app':'claude','id':'s','text':'下一条','replace_draft':'e'})
        self.assertEqual(sent.call_args,call('claude','s','下一条',replace='e'))
        with self.assertRaises(chats.InputNotSubmitted):
            handler._send_with_references({'app':'codex','id':'s','text':'下一条','replace_draft':'e'})
        self.assertEqual(sent.call_count,1)  # no Codex legacy keystroke fallback
    def test_the_box_is_focused_only_when_claude_is_the_active_window(self):
        for front in (False,True):
            edit=Edit();edit.SetFocus=Mock();d,submit=self.desktop(edit)
            with patch('chats.winctl._is_front',return_value=front):d._fill_claude_prompt({'id':'s','title':'test'},SimpleNamespace(NativeWindowHandle=7),'第一条')
            self.assertEqual(edit.SetFocus.call_count,int(front))
    def test_claude_log_shows_the_switch(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'main.log'
            log.write_bytes(b'2026-10-12 17:56:15 [info] [CCD] LocalSessions.setFocusedSession: sessionId=local_a\r\n'
                            b'2026-10-12 17:56:29 [info] second-instance: suppressing duplicate argv\r\n')
            at=datetime(2026,10,12,17,56,15).timestamp()
            with patch('chats.claude_main_logs',return_value=[log]):
                self.assertTrue(chats.claude_focus_logged('local_a',at));self.assertFalse(chats.claude_focus_logged('local_b',at))
                self.assertFalse(chats.claude_focus_logged('local_a',at+5))  # a switch from before the click does not count
    def test_a_taken_sidebar_click_is_waited_for_without_the_link(self):
        # 10-12: a 42 MB session took 37 s to draw after its click; the link opened 12 s in only started a second Claude.exe
        d=object.__new__(chats.Desktop);shown=iter([None]*60+['doc']);clock=iter(range(0,100000))
        d._claude_root=Mock(return_value=(1,'root'));d._claude_document=Mock(side_effect=lambda *a:next(shown))
        d._claude_sidebar_buttons=Mock(return_value=['row']);d._claude_press=Mock(return_value=True)
        with patch('chats.claude_focus_logged',return_value=True),patch('chats.os.startfile') as link,patch('chats.time.sleep'),patch('chats.time.monotonic',side_effect=lambda:next(clock)*.5):
            self.assertEqual(d._claude_open({'id':'s','title':'t'},['t']),(1,'root'))
            d._claude_document=Mock(return_value=None)  # still not drawn after the longer wait: not sent, and still no link
            with self.assertRaises(chats.InputNotSubmitted):d._claude_open({'id':'s','title':'t'},['t'])
        link.assert_not_called()
    def test_a_click_that_was_not_taken_falls_back_to_the_link(self):
        d=object.__new__(chats.Desktop);opened=[];clock=iter(range(0,100000))
        d._claude_root=Mock(return_value=(1,'root'));d._claude_document=Mock(side_effect=lambda *a:'doc' if opened else None)
        d._claude_sidebar_buttons=Mock(return_value=['row']);d._claude_press=Mock(return_value=True)
        d._front=Mock(return_value=1);d._need_auto=Mock(return_value=SimpleNamespace(ControlFromHandle=lambda h:'root'))
        with patch('chats.claude_focus_logged',return_value=False),patch('chats.os.startfile',side_effect=opened.append),patch('chats.time.sleep'),patch('chats.time.monotonic',side_effect=lambda:next(clock)*.5):
            self.assertEqual(d._claude_open({'id':'s','title':'t'},['t']),(1,'root'))
        self.assertEqual(len(opened),1);self.assertTrue(opened[0].startswith('claude://claude.ai/epitaxy/s?r='))
    def test_sidebar_rows_are_found_by_the_names_claude_gives_them_since_2_1_299(self):
        # 10-20: rows lost their 'Idle '/'Running ' prefix on 10-15; looking for it alone sent every switch to the link
        def button(name,parent=None):return SimpleNamespace(Name=name,GetParentControl=lambda:parent)
        card=SimpleNamespace(Name='1 suggested task',GetParentControl=lambda:None)
        rows=[button('t'),button('More options for t'),button('t, rename session'),button('t Started by Claude from p'),
              button('Idle t'),button('other'),button('t',SimpleNamespace(Name='',GetParentControl=lambda:card))]
        d=object.__new__(chats.Desktop);d._find=Mock(return_value=rows)
        self.assertEqual([b.Name for b in d._claude_sidebar_buttons('root',{'title':'t'},['t'])],['t','t Started by Claude from p','Idle t'])
        self.assertEqual(d._claude_sidebar_buttons('root',{'title':''},[]),[])
    def test_sidebar_rows_are_found_by_the_names_of_claudes_new_window(self):
        # 10-26: '<title> Running' and '<title> Started from a suggestion in <project>' rows were never pressed, so those
        # sends went to the link; the states come from claude.ai's page code, the other names from the window
        names=['t','t Running','t Awaiting input','t Awaiting answer','t Using the browser','t Unread response','t Idle','t Done',
               't Started by Claude from p','t Started from a suggestion in proj','t Running Started by Claude from p','Running t']
        others=['More options for t','Hide nested sessions t','Show nested sessions t','Pin t','t, rename session','tt','t2 Running','Running tt']
        rows=[SimpleNamespace(Name=n,GetParentControl=lambda:None) for n in others[:4]+names+others[4:]]
        d=object.__new__(chats.Desktop);d._find=Mock(return_value=rows);d._claude_id_rows=Mock(return_value=[])
        d._claude_row_parts=Mock(return_value=('',''))  # the line under the title is read only for other endings
        self.assertEqual([b.Name for b in d._claude_sidebar_buttons('root',{'id':'s','title':'t'},['t'])],names)
        d._claude_id_rows.assert_called_once_with('root','s')
    def test_a_row_with_another_ending_counts_when_its_first_line_is_the_title(self):
        # an error state, say: its words are not on the list, but the row's first line is the session's title
        rows=[SimpleNamespace(Name=n,GetParentControl=lambda:None) for n in ('t Model not found','t and more','t unread')]
        first={'t Model not found':'t','t and more':'t and more','t unread':''}  # '': the row's lines could not be read
        d=object.__new__(chats.Desktop);d._find=Mock(return_value=rows);d._claude_id_rows=Mock(return_value=[])
        d._claude_row_parts=Mock(side_effect=lambda b:('',first[b.Name]))
        self.assertEqual([b.Name for b in d._claude_sidebar_buttons('root',{'id':'s','title':'t'},['t'])],['t Model not found'])
    def test_the_row_that_carries_the_session_id_comes_first(self):
        # 10-26: a row that has nested sessions carries its session id; a row of the same title that carries another
        # session's id is not this one, and this session's own row is not listed twice
        own,other='local_11111111-1111-4111-8111-111111111111','local_22222222-2222-4222-8222-222222222222'
        rows=[SimpleNamespace(Name='t',GetParentControl=lambda:None,carried=c) for c in (other,own,'')]
        d=object.__new__(chats.Desktop);d._find=Mock(return_value=rows);d._claude_id_rows=Mock(return_value=['own row'])
        d._claude_row_parts=Mock(side_effect=lambda b:(b.carried,'t'))
        self.assertEqual(d._claude_sidebar_buttons('root',{'id':own,'title':'t'},['t']),['own row',rows[2]])
        d._claude_id_rows=Mock(return_value=[])  # the id search found nothing: the row that carries this id stays in page order
        self.assertEqual(d._claude_sidebar_buttons('root',{'id':own,'title':'t'},['t']),[rows[1],rows[2]])
        d._claude_id_rows=Mock(return_value=['own row'])  # renamed since the index was written: the id still finds it
        self.assertEqual(d._claude_sidebar_buttons('root',{'id':own,'title':'old title'},['old title']),['own row'])
    def test_rows_with_the_session_id_come_from_one_raw_view_question(self):
        # the group that holds the id is not a control element: the usual search (control view) found none on 10-26
        own,other='local_11111111-1111-4111-8111-111111111111','local_22222222-2222-4222-8222-222222222222'
        row=SimpleNamespace(ControlTypeName='ButtonControl');box=SimpleNamespace(ControlTypeName='GroupControl')
        groups=[SimpleNamespace(CachedAutomationId=a,parent=p) for a,p in (('_r_82_'+own,row),('command-palette-item-'+own,row),
                                                                            ('_r_9_'+own,box),('_r_83_'+other,row),('_r_84_'+own,None))]
        asked=[]
        class Found:
            Length=len(groups)
            def GetElement(self,i):return groups[i]
        def find(scope,condition,request):asked.append((scope,condition,request.TreeFilter,request.props));return Found()
        d=object.__new__(chats.Desktop)
        d.uia=SimpleNamespace(RawViewCondition='raw',RawViewWalker=SimpleNamespace(GetParentElement=lambda e:e.parent),
                              CreatePropertyConditionEx=lambda prop,value,flags:('has',prop,value,flags))
        d.uia.CreateCacheRequest=lambda:(lambda r:setattr(r,'AddProperty',r.props.append) or r)(SimpleNamespace(TreeFilter=None,props=[]))
        d.auto=SimpleNamespace(PropertyId=SimpleNamespace(AutomationIdProperty='aid'),Control=SimpleNamespace(CreateControlFromElement=lambda e:e))
        self.assertEqual(d._claude_id_rows(SimpleNamespace(Element=SimpleNamespace(FindAllBuildCache=find)),own),[row])
        self.assertEqual(asked,[(4,('has','aid',own,2),'raw',['aid'])])  # 4: all below the window; 2: the id within the name
        self.assertEqual(d._claude_id_rows('root','__new__'),[]);self.assertEqual(len(asked),1)
        d.uia=None;self.assertEqual(d._claude_id_rows('root',own),[])  # no UI Automation: the names alone decide
    def test_row_parts_are_its_session_id_and_first_line(self):
        own='local_11111111-1111-4111-8111-111111111111';TEXT,GROUP,STATUS=50020,50026,50017
        def row(*parts):
            class Found:
                Length=len(parts)
                def GetElement(self,i):return SimpleNamespace(CachedAutomationId=parts[i][0],CachedControlType=parts[i][1],CachedName=parts[i][2])
            return SimpleNamespace(Element=SimpleNamespace(FindAllBuildCache=lambda scope,condition,request:Found()))
        d=object.__new__(chats.Desktop)
        d.uia=SimpleNamespace(RawViewCondition='raw',CreateCacheRequest=lambda:SimpleNamespace(TreeFilter=None,AddProperty=lambda p:None))
        d.auto=SimpleNamespace(PropertyId=SimpleNamespace(AutomationIdProperty=1,ControlTypeProperty=2,NameProperty=3),ControlType=SimpleNamespace(TextControl=TEXT))
        # the parts of a row with nested sessions, and of this running session's own row, as read on 10-26
        self.assertEqual(d._claude_row_parts(row(('_r_82_'+own,GROUP,''),('_r_94_',GROUP,''),('',TEXT,'t '),('',STATUS,''))),(own,'t'))
        self.assertEqual(d._claude_row_parts(row(('_r_jij_',GROUP,''),('',TEXT,''),('',TEXT,'t'),('',TEXT,'Started by Claude from p'),('',TEXT,'Running'))),('','t'))
        self.assertEqual(d._claude_row_parts(SimpleNamespace(Name='no Element')),('',''))
    def test_another_session_of_the_same_title_is_pressed_next(self):
        d=object.__new__(chats.Desktop);pressed=[];clock=iter(range(0,100000))
        d._claude_root=Mock(return_value=(1,'root'));d._claude_document=Mock(side_effect=lambda *a:'doc' if pressed[-1:]==['second'] else None)
        d._claude_sidebar_buttons=Mock(return_value=['first','second']);d._claude_press=Mock(side_effect=lambda h,b:pressed.append(b) or True)
        with patch('chats.claude_focus_logged',return_value=False),patch('chats.os.startfile') as link,patch('chats.time.sleep'),patch('chats.time.monotonic',side_effect=lambda:next(clock)*.5):
            self.assertEqual(d._claude_open({'id':'s','title':'t'},['t']),(1,'root'))
        self.assertEqual(pressed,['first','second']);link.assert_not_called()
    def test_question_area_is_found_by_going_up_from_the_message_box(self):
        # 10-12: searching the window for it took 0.45 s every 5 s; it is six levels above the box
        document=SimpleNamespace(Name='s - Claude Code',ClassName='',ControlTypeName='DocumentControl',GetParentControl=lambda:None)
        dock=SimpleNamespace(Name='',ClassName='group/approval-dock pointer-events-auto',ControlTypeName='GroupControl',GetParentControl=lambda:document);node=dock
        for cls in ('bg-surface-3','relative w-full','relative min-w-0'):node=SimpleNamespace(Name='',ClassName=cls,ControlTypeName='GroupControl',GetParentControl=(lambda up:lambda:up)(node))
        edit=SimpleNamespace(Name='Prompt',ClassName='tiptap ProseMirror',ControlTypeName='EditControl',GetParentControl=(lambda up:lambda:up)(node))
        root=SimpleNamespace(GroupControl=Mock(side_effect=AssertionError('the window must not be searched')))
        d=object.__new__(chats.Desktop);d._find=Mock(return_value=[edit])
        self.assertIs(d._claude_dock(root),dock);d._find.assert_called_once_with(root,'EditControl','Prompt')
        found=SimpleNamespace(Exists=lambda *a:True,GetParentControl=lambda:document);root=SimpleNamespace(GroupControl=Mock(return_value=found))
        d._find=Mock(return_value=[])  # no message box: a question took its place
        self.assertIs(d._claude_dock(root),found)
    def test_a_question_card_among_the_messages_is_where_claude_asks(self):
        # 10-26: Claude's new window asks in a card among the messages; read in the dock alone, the phone showed nothing
        button=lambda enabled=True:SimpleNamespace(IsEnabled=enabled)
        def card(name):  # 11-17: a card among the session's own messages, not in a side chat
            document=SimpleNamespace(Name='s - Claude Code',ClassName='',ControlTypeName='DocumentControl',GetParentControl=lambda:None)
            node=SimpleNamespace(name=name,ClassName='epitaxy-approval-card relative isolate flex flex-col',GetParentControl=lambda:document)
            return node
        old,new,answered=card('old'),card('new'),card('answered')
        # 10-27: the dock's classes hold '[&_.epitaxy-approval-card]:shrink'; a search within the class names finds it too
        dock_like=SimpleNamespace(name='dock_like',ClassName='group/approval-dock pointer-events-auto [&_.epitaxy-approval-card]:shrink')
        presses={'old':[button()],'new':[button(False),button()],'answered':[button(False)],'dock_like':[button()]}
        d=object.__new__(chats.Desktop);d._claude_dock=Mock(return_value='dock')
        d._find=Mock(side_effect=lambda scope,kind,name=None:presses[scope.name])
        d._find_class=Mock(return_value=[old,new,dock_like])
        self.assertIs(d._claude_ask('root','doc'),new);d._find_class.assert_called_once_with('doc',chats.CLAUDE_QUESTION_CARD)
        d._find_class=Mock(return_value=[old,answered])  # nothing left to press in the newest: an older card that still asks
        self.assertIs(d._claude_ask('root'),old);d._find_class.assert_called_once_with('root',chats.CLAUDE_QUESTION_CARD)
        for cards in ([],[answered]):
            d._find_class=Mock(return_value=cards);self.assertEqual(d._claude_ask('root','doc'),'dock')
        d._find_class=Mock(side_effect=RuntimeError('COM'));self.assertEqual(d._claude_ask('root','doc'),'dock')
        self.assertTrue(chats.question_card(SimpleNamespace(ClassName='epitaxy-approval-card relative isolate')))
        self.assertFalse(chats.question_card(SimpleNamespace(ClassName='group/approval-dock pointer-events-auto')))
        self.assertFalse(chats.question_card(dock_like));self.assertFalse(chats.question_card(object()))
        self.assertTrue(chats.answer_option(SimpleNamespace(ClassName='epitaxy-answer-option flex w-full items-start')))
        self.assertFalse(chats.answer_option(SimpleNamespace(ClassName='absolute inset-0 focus-visible:outline-hidden')))  # Other
        self.assertFalse(chats.answer_option(object()))
    def test_an_option_is_clicked_for_real_where_nothing_covers_it(self):
        # 10-27 08:19: UI Automation's press only moved the focus to a card's option; a click picks it
        class Rect:
            def __init__(self,l,t,r,b):self.left,self.top,self.right,self.bottom=l,t,r,b
            def width(self):return self.right-self.left
            def height(self):return self.bottom-self.top
        scrolled=[];option=SimpleNamespace(IsOffscreen=True,BoundingRectangle=Rect(100,200,300,240),
                                           GetScrollItemPattern=lambda:SimpleNamespace(ScrollIntoView=lambda:scrolled.append(1)))
        d=object.__new__(chats.Desktop);d.input_lock=threading.Lock()
        down,up=chats.winctl.MOUSEEVENTF_LEFTDOWN,chats.winctl.MOUSEEVENTF_LEFTUP
        with patch('chats.winctl.input_desktop_ready',return_value=True),patch('chats.winctl.focus') as focus,\
             patch('chats.winctl._send') as send,patch('chats.winctl._mouse_input',side_effect=lambda flags:flags),\
             patch('chats.win32gui.GetCursorPos',return_value=(5,6)),patch('chats.win32gui.WindowFromPoint',return_value=11),\
             patch('chats.win32gui.GetAncestor',return_value=7) as root,patch('chats.win32api.SetCursorPos') as pointer,patch('chats.time.sleep'),\
             patch('chats.time.monotonic',side_effect=(i/5 for i in range(10**6)).__next__),\
             patch('chats.win32gui.GetClassName',return_value='tooltips_class32'),patch('chats._process_of',return_value='claude.exe'):
            d._click_control(7,option)
            self.assertEqual(scrolled,[1]);focus.assert_called_once_with(7)
            self.assertEqual(send.call_args_list,[call([down]),call([up])])  # pressed and released apart, as a hand does
            self.assertEqual(pointer.call_args_list,[call((200,220)),call((5,6))])  # there, then back where it was
            root.side_effect=[8,8,7];send.reset_mock()  # 10-27 09:55: something over that spot for a moment
            d._click_control(7,option);self.assertEqual(send.call_count,2)
            root.side_effect=None;root.return_value=8;send.reset_mock();pointer.reset_mock()  # and one that stays
            with self.assertRaises(chats.ChatError) as refused:d._click_control(7,option)
            self.assertIn('tooltips_class32，claude.exe',str(refused.exception))  # named for the log
            send.assert_not_called();pointer.assert_called_once_with((5,6))
            root.return_value=7;focus.side_effect=chats.winctl.WinError('没能把窗口拉到前台')
            with self.assertRaises(chats.ChatError):d._click_control(7,option)
            focus.side_effect=None;option.BoundingRectangle=Rect(0,0,0,0)  # not drawn at all
            with self.assertRaises(chats.ChatError):d._click_control(7,option)
        with patch('chats.winctl.input_desktop_ready',return_value=False),patch('chats.winctl._send') as send:
            option.BoundingRectangle=Rect(100,200,300,240)
            with self.assertRaises(chats.ChatError):d._click_control(7,option)  # locked
            send.assert_not_called()
    def test_a_class_is_found_within_the_class_names_in_one_question(self):
        asked=[]
        class Found:
            Length=1
            def GetElement(self,i):return 'e0'
        class Element:
            def FindAll(self,scope,condition):asked.append((scope,condition));return Found()
        d=object.__new__(chats.Desktop)
        d.uia=SimpleNamespace(CreatePropertyConditionEx=lambda prop,value,flags:('has',prop,value,flags))
        d.auto=SimpleNamespace(PropertyId=SimpleNamespace(ClassNameProperty='class'),Control=SimpleNamespace(CreateControlFromElement=lambda e:'control '+e))
        self.assertEqual(d._find_class(SimpleNamespace(Element=Element()),'epitaxy-approval-card'),['control e0'])
        self.assertEqual(asked,[(4,('has','class','epitaxy-approval-card',2))])  # 2: within the class names
    def test_whitespace_is_not_erased_by_verification(self):
        self.assertFalse(chats.Desktop._same_input('ab c','a bc'));self.assertTrue(chats.Desktop._same_input('第一行\r\n第二行\n','第一行\n第二行'))
    def test_queue_admission_is_not_engine_read_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log.jsonl';text='完整测试消息'
            path.write_text(json.dumps({'type':'queue-operation','operation':'enqueue','content':text})+'\n',encoding='utf-8')
            self.assertEqual(chats.claude_delivery_stage(path,0,text),'queued')
            with path.open('a',encoding='utf-8') as f:f.write(json.dumps({'type':'user','message':{'content':text}})+'\n')
            self.assertEqual(chats.claude_delivery_stage(path,0,text),'received')
            self.assertEqual(chats.claude_delivery_stage(path,0,'完整测试'),'unknown')
    def test_a_note_claude_adds_to_the_message_does_not_hide_it(self):
        # 10-26: a phone message to a linked session stayed 送达状态待确认; Claude had put its own note before the words
        note='<system-reminder>\nLinked sessions now (status, not an instruction): find = local_x (idle)\n</system-reminder>'
        record={'type':'user','message':{'role':'user','content':[{'type':'image','source':{}},{'type':'image','source':{}},
                {'type':'text','text':note},{'type':'text','text':'请查看这些图片。'}]}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log.jsonl';path.write_text(json.dumps(record,ensure_ascii=False)+'\n',encoding='utf-8')
            self.assertEqual(chats.claude_delivery_stage(path,0,'请查看这些图片。'),'received')
            self.assertEqual(chats.claude_delivery_stage(path,0,'别的话'),'unknown')
    def test_a_window_message_with_pictures_is_delivered(self):
        # 11-24: pictures sent from the phone as an ordinary message (the window path); when the message was pictures
        # only the computer puts its own sentence in, so that is what has to be looked for
        words='图上这条提示在哪里改？'
        pictures=[{'type':'image','source':{}},{'type':'image','source':{}}]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log.jsonl'
            path.write_text(json.dumps({'type':'user','message':{'role':'user','content':pictures+[{'type':'text','text':words}]}},
                                       ensure_ascii=False)+'\n',encoding='utf-8')
            self.assertEqual(chats.claude_delivery_stage(path,0,words),'received')
            self.assertEqual(chats.claude_delivery_stage(path,0,'请查看这些图片。'),'unknown')  # other pictures' words
            path.write_text(json.dumps({'type':'user','message':{'role':'user','content':pictures+[{'type':'text','text':'请查看这些图片。'}]}},
                                       ensure_ascii=False)+'\n',encoding='utf-8')
            self.assertEqual(chats.claude_delivery_stage(path,0,'请查看这些图片。'),'received')
    def test_a_message_that_never_arrived_stays_unconfirmed(self):
        # 没送到: the record holds other words, and a record written before this send's offset is not this message
        first=json.dumps({'type':'user','message':{'role':'user','content':[{'type':'image','source':{}},{'type':'text','text':'别的话'}]}},
                         ensure_ascii=False)+'\n'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log.jsonl'
            path.write_text(first+json.dumps({'type':'assistant','message':{'content':[]}})+'\n',encoding='utf-8')
            self.assertEqual(chats.claude_delivery_stage(path,0,'别的话'),'received')
            self.assertEqual(chats.claude_delivery_stage(path,0,'没送到的话'),'unknown')
            self.assertEqual(chats.claude_delivery_stage(path,len(first.encode('utf-8')),'别的话'),'unknown')
    # 10-20: a /compact from the phone stayed 排队中 after the compaction had long finished. The record had the enqueue line
    # with the words sent, then the command only in tags; the summary showed as the user's own 10,973-character message,
    # and the conversation counted as running (停止这一轮)
    COMPACT=[{'type':'assistant','timestamp':'2026-10-20T07:07:53Z','message':{'role':'assistant','stop_reason':'end_turn','content':[{'type':'text','text':'推送好了。'}]}},
             {'type':'queue-operation','operation':'enqueue','content':'/compact'},{'type':'queue-operation','operation':'dequeue'},
             {'type':'system','subtype':'compact_boundary','timestamp':'2026-10-20T10:20:09Z','content':'Conversation compacted'},
             {'type':'user','isCompactSummary':True,'isVisibleInTranscriptOnly':True,'timestamp':'2026-10-20T10:20:09Z','message':{'role':'user','content':'This session is being continued from a previous conversation. '*40}},
             {'type':'user','isMeta':True,'timestamp':'2026-10-20T10:18:38Z','message':{'role':'user','content':'<local-command-caveat>Caveat: the messages below were generated by the user while running local commands.</local-command-caveat>'}},
             {'type':'user','timestamp':'2026-10-20T10:18:38Z','message':{'role':'user','content':'<command-name>/compact</command-name>\n            <command-message>compact</command-message>\n            <command-args></command-args>'}},
             {'type':'user','timestamp':'2026-10-20T10:20:10Z','message':{'role':'user','content':'<local-command-stdout>Compacted </local-command-stdout>'}}]
    def test_a_slash_command_is_found_by_its_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log.jsonl'
            path.write_text(''.join(json.dumps(v)+'\n' for v in self.COMPACT[:3]),encoding='utf-8')
            self.assertEqual(chats.claude_delivery_stage(path,0,'/compact'),'queued')
            with path.open('a',encoding='utf-8') as f:f.write(''.join(json.dumps(v)+'\n' for v in self.COMPACT[3:]))
            self.assertEqual(chats.claude_delivery_stage(path,0,'/compact'),'received')
            self.assertEqual(chats.claude_delivery_stage(path,0,'/compact 只留结论'),'unknown')  # other arguments: another message
        self.assertEqual(chats.claude_command('<command-name>/model</command-name><command-args>opus</command-args>'),'/model opus')
        self.assertEqual(chats.claude_command('<command-name>compact</command-name>'),'/compact')
        self.assertEqual(chats.claude_command('/compact 是一句普通的话'),'')
    def test_compaction_shows_as_a_divider_and_nothing_runs_after_it(self):
        msgs,state=chats.parse_claude([json.dumps(v).encode() for v in self.COMPACT])
        # 0.6.6: the /compact shows where Claude took it from its queue, once (not again at its tagged line)
        self.assertEqual([(m['role'],m['text']) for m in msgs],[('assistant','推送好了。'),('user','/compact'),('event','对话已压缩')])
        self.assertIs(state['running'],False)
        # a command that hands work to Claude (a skill) is a turn under way until the answer comes
        skill={'type':'user','timestamp':'2026-10-20T10:30:00Z','message':{'role':'user','content':'<command-message>code-review</command-message>\n<command-name>/code-review</command-name>\n<command-args></command-args>'}}
        self.assertIs(chats.parse_claude([json.dumps(v).encode() for v in [*self.COMPACT,skill]])[1]['running'],True)
    def test_a_compaction_under_way_runs_with_its_own_step(self):
        """0.6.6: between the queue's dequeue and the compact boundary Claude writes nothing for minutes; the phone says
        正在压缩上下文 with the timer from when Claude took the command."""
        lines=[json.dumps({**v,'timestamp':'2026-10-20T10:18:38Z'} if v['type']=='queue-operation' else v).encode() for v in self.COMPACT]
        msgs,state=chats.parse_claude(lines[:3])
        self.assertEqual((state['running'],state['step'],state['turn_started']),(True,'compact','2026-10-20T10:18:38Z'))
        self.assertEqual(msgs[-1],{'role':'user','text':'/compact','time':'2026-10-20T10:18:38Z'})
        msgs,state=chats.parse_claude(lines)
        self.assertEqual((state['running'],state['step']),(False,''))
        # read a line at a time (chat_history.Transcript), the command shows once too
        context,seen={},[]
        for line in lines:seen+=chats.parse_claude([line],context)[0]
        self.assertEqual([m['text'] for m in seen if m['role']=='user'],['/compact'])
    def test_a_compaction_says_what_the_context_came_down_to(self):
        boundary={'type':'system','subtype':'compact_boundary','timestamp':'2026-10-05T08:25:09Z',
                  'compactMetadata':{'trigger':'manual','preTokens':765755,'postTokens':12751}}
        answer={'type':'assistant','timestamp':'2026-10-05T08:10:19Z','message':{'model':'claude-opus','stop_reason':'end_turn',
                'usage':{'input_tokens':10,'cache_read_input_tokens':765000,'cache_creation_input_tokens':700},'content':[]}}
        out=chats.parse_runtime('claude',[json.dumps(v).encode() for v in (answer,boundary)])
        self.assertEqual((out['used_tokens'],out['context_state'],out['source']),(12751,'partial','compact'))
    def test_midturn_attachment_proves_read_and_is_public_input(self):
        record={'type':'attachment','uuid':'attachment-id','timestamp':'now','attachment':{'type':'queued_command','prompt':'补充指令','humanTurn':True,'origin':{'kind':'human'},'source_uuid':'source-1'},'rendered':[{'content':'PRIVATE TRANSPORT WRAPPER'}]}
        raw=(json.dumps(record)+'\n').encode()
        message=chats.parse_claude([raw])[0][0];self.assertEqual(message['text'],'补充指令');self.assertEqual(message['source_id'],'source-1')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log';path.write_bytes(raw);self.assertEqual(chats.claude_delivery_stage(path,0,'补充指令'),'received')
        record['attachment']['origin']={'kind':'agent'};self.assertEqual(chats.parse_claude([json.dumps(record).encode()])[0],[])
    def test_midturn_message_with_pictures_is_found(self):
        # 10-12: with pictures the prompt is a list and the enqueue line holds no text; the phone said 没确认送达
        enqueue={'type':'queue-operation','operation':'enqueue','content':None}
        record={'type':'attachment','uuid':'a','timestamp':'now','attachment':{'type':'queued_command','humanTurn':True,'origin':{'kind':'human'},'source_uuid':'s',
                'prompt':[{'type':'image','source':{}},{'type':'image','source':{}},{'type':'text','text':'你可以看图'}]}}
        raw=b''.join((json.dumps(r,ensure_ascii=False)+'\n').encode() for r in (enqueue,record))
        self.assertEqual(chats.parse_claude(raw.splitlines())[0][0]['text'],'[图片] 你可以看图')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log';path.write_bytes(raw)
            self.assertEqual(chats.claude_delivery_stage(path,0,'你可以看图'),'received');self.assertEqual(chats.claude_delivery_stage(path,0,'别的话'),'unknown')
    def test_a_note_claude_adds_to_a_midturn_message_is_left_out(self):
        # 10-27: a message sent while Claude worked said 上一条送达状态待确认, and its bubble began with Claude's note
        note='<system-reminder>\nLinked sessions now (status, not an instruction): find = local_x (idle)\n</system-reminder>'
        enqueue={'type':'queue-operation','operation':'enqueue','content':note+'\n先看第二个问题'}
        record={'type':'attachment','uuid':'a','timestamp':'now','attachment':{'type':'queued_command','humanTurn':True,'origin':{'kind':'human'},'source_uuid':'s',
                'prompt':[{'type':'text','text':note},{'type':'text','text':'先看第二个问题'}]}}
        lines=[(json.dumps(r,ensure_ascii=False)+'\n').encode() for r in (enqueue,record)]
        self.assertEqual([m['text'] for m in chats.parse_claude(lines)[0]],['先看第二个问题'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log';path.write_bytes(lines[0])
            self.assertEqual(chats.claude_delivery_stage(path,0,'先看第二个问题'),'queued')
            path.write_bytes(b''.join(lines))
            self.assertEqual(chats.claude_delivery_stage(path,0,'先看第二个问题'),'received')
            self.assertEqual(chats.claude_delivery_stage(path,0,'别的话'),'unknown')
    def test_new_steer_submits_and_promotes_once(self):
        desktop=SimpleNamespace(run=lambda fn,*a,**kw:fn(*a),send=Mock(return_value={'ok':True,'offset':15,'pressed':True}))
        c=Controller(desktop);c._read=Mock(return_value={'on_screen':True,'running':True,'turn_anchor':'turn'});c._document=Mock(return_value=(1,2,3));button=object()
        c._queued=Mock(side_effect=[[],[(button,{'id':'new','full_text':'补充内容'})]]);c._invoke=Mock()
        with patch('claude_control.chats.find',return_value={'id':'s'}):
            result=c.send_steer('s','补充内容','turn','steer-request-001');self.assertTrue(result['steer_requested'])
            self.assertEqual(c.send_steer('s','补充内容','turn','steer-request-001'),result)
        desktop.send.assert_called_once();c._invoke.assert_called_once_with(button)
    def test_steer_rejects_changed_turn_before_send(self):
        desktop=SimpleNamespace(run=lambda fn,*a,**kw:fn(*a),send=Mock());c=Controller(desktop);c._read=lambda _:{'on_screen':True,'running':True,'turn_anchor':'new-turn'}
        with patch('claude_control.chats.find',return_value={'id':'s'}):
            with self.assertRaises(chats.InputNotSubmitted):c.send_steer('s','text','old-turn','steer-request-002')
        desktop.send.assert_not_called()
    def test_old_queued_card_cannot_promote_different_message(self):
        desktop=SimpleNamespace(run=lambda fn,*a,**kw:fn(*a));c=Controller(desktop);c._document=lambda _:(1,2,3);c._queued=lambda _:[(object(),{'id':'new'})];c._invoke=Mock()
        token=c._ticket('s','steer_queued',{'id':'old'},signature(['s','turn','old']))
        with patch('claude_control.chats.find',return_value={'id':'s'}),patch('claude_control.chats.conv_path',return_value=None),patch('claude_control.turn_anchor',return_value='turn'):
            with self.assertRaises(chats.ChatError):c.choose('s',token)
        c._invoke.assert_not_called()

class QueueShadowTests(unittest.TestCase):
    """11-01: the queue this service keeps of Claude's own had drifted by one, so a /compact queued at 08:02 came out
    at 08:06 as if the user had just sent it. It is our copy, not Claude's: it must mend itself."""

    CROSS=('<cross-session-message from="uds:\\\\pipe\\\\x" from-session="local_1" hop-chain="4f0e" '
           'from-name="别处">同事的消息</cross-session-message>')

    def line(self,op=None,content=None,ts=None):
        record={'type':'queue-operation'}
        if op:record['operation']=op
        if content is not None:record['content']=content
        if ts:record['timestamp']=ts
        return json.dumps(record,ensure_ascii=False).encode()

    def said(self,text,ts):
        return json.dumps({'type':'user','uuid':'u-'+ts,'timestamp':ts,'message':{'content':text}},
                          ensure_ascii=False).encode()

    def test_removing_a_cross_session_message_ignores_its_hop_chain(self):
        # enqueue carries hop-chain="…", remove leaves it off: the exact words differed, so the entry stayed for good
        lines=[self.line('enqueue',self.CROSS,'2026-10-31T14:05:45Z'),
               self.line('remove',self.CROSS.replace(' hop-chain="4f0e"',''),'2026-10-31T14:08:45Z'),
               self.line('enqueue','/compact','2026-10-31T14:10:00Z'),
               self.line('dequeue',None,'2026-10-31T14:10:00.002Z')]
        msgs,state=chats.parse_claude(lines)
        self.assertEqual([(m['role'],m['text']) for m in msgs],[('user','/compact')])
        self.assertEqual(state['step'],'compact')

    def test_a_message_waiting_over_thirty_minutes_no_longer_shifts_the_queue(self):
        lines=[self.line('enqueue',self.CROSS,'2026-10-31T14:05:45Z'),  # never removed: hop-chain differs
               self.line('enqueue','/compact','2026-11-01T00:02:46.227Z'),
               self.line('dequeue',None,'2026-11-01T00:02:46.229Z')]
        msgs,state=chats.parse_claude(lines)
        self.assertEqual([m['text'] for m in msgs if m['role']=='user'],['/compact'])
        self.assertEqual((state['step'],state['running']),('compact',True))

    def test_the_message_that_is_written_takes_its_queued_copy_and_everything_before(self):
        lines=[self.line('enqueue','先查一下','2026-11-01T07:59:00Z'),
               self.line('enqueue','再整理','2026-11-01T07:59:02Z'),
               self.line('dequeue',None,'2026-11-01T07:59:03Z'),          # took 先查一下, 再整理 stays behind
               self.said('再整理','2026-11-01T07:59:04Z'),                # written: the stale copy goes now
               self.line('enqueue','/compact','2026-11-01T08:02:00Z'),
               self.line('dequeue',None,'2026-11-01T08:02:00.002Z')]
        msgs,_=chats.parse_claude(lines)
        self.assertEqual([m['text'] for m in msgs if m['role']=='user'],['再整理','/compact'])

    def test_an_unmatched_removal_takes_the_oldest_empty_part_away(self):
        # 11-16: a Claude message sent with a picture queued an empty part first; the words Claude took back never
        # matched it, and the empty part stayed until the next /compact, which it then broke.
        lines=[self.line('enqueue','','2026-11-01T07:59:00Z'),
               self.line('remove','看一下这个','2026-11-01T07:59:02Z'),
               self.line('enqueue','/compact','2026-11-01T08:02:00Z'),
               self.line('dequeue',None,'2026-11-01T08:02:00.002Z')]
        msgs,_=chats.parse_claude(lines)
        self.assertEqual([m['text'] for m in msgs if m['role']=='user'],['/compact'])


class LineStateTests(unittest.TestCase):
    """11-01: read a line at a time, an empty value was skipped, so '正在压缩上下文' (step=compact) stayed until the
    next tool call, four minutes of a /compact and a whole image message later."""

    def records(self):
        return [json.dumps({'type':'queue-operation','operation':'enqueue','content':'/compact',
                            'timestamp':'2026-11-01T08:02:46Z'}).encode(),
                json.dumps({'type':'queue-operation','operation':'dequeue',
                            'timestamp':'2026-11-01T08:02:46.002Z'}).encode(),
                json.dumps({'type':'system','subtype':'compact_boundary','uuid':'c1',
                            'timestamp':'2026-11-01T08:02:47Z'}).encode(),
                json.dumps({'type':'assistant','uuid':'a1','timestamp':'2026-11-01T08:03:00Z',
                            'message':{'content':[{'type':'tool_use','id':'t1','name':'Bash',
                                                   'input':{'command':'dir'}}],'stop_reason':'tool_use'}}).encode(),
                json.dumps({'type':'user','uuid':'u1','timestamp':'2026-11-01T08:06:59Z',
                            'message':{'content':'这俩对话早结束了'}},ensure_ascii=False).encode(),
                json.dumps({'type':'assistant','uuid':'a2','timestamp':'2026-11-01T08:07:30Z',
                            'message':{'content':[{'type':'text','text':'改好了。'}],'stop_reason':'end_turn'}},
                           ensure_ascii=False).encode()]

    def read(self,lines):
        """What chat_history.Transcript.refresh keeps, line by line into one state dict."""
        context,state={},{}
        for line in lines:
            msgs,changed=chats.parse_claude([line],context)
            state.update(changed)
        return state

    def test_the_dequeued_command_shows_and_its_step_clears_at_the_next_message(self):
        lines=self.records()
        self.assertEqual(self.read(lines[:2])['step'],'compact')
        after_boundary=self.read(lines[:3])
        self.assertEqual((after_boundary['step'],after_boundary['running']),('',True))  # compact_boundary clears it
        # without a boundary (the command's own "Compacted" is later): the next user message clears it too
        state=self.read([lines[0],lines[1],lines[4]])
        self.assertEqual((state['step'],state['turn_ended']),('',''))
        self.assertIs(state['running'],True)

    def test_a_tool_step_and_a_turn_end_clear_it_the_same_way(self):
        state=self.read(self.records())
        self.assertEqual((state['step'],state['turn_ended']),('','2026-11-01T08:07:30Z'))
        self.assertIs(state['running'],False)
        tool=json.dumps({'type':'assistant','uuid':'b1','timestamp':'2026-11-01T08:08:00Z',
                         'message':{'content':[{'type':'tool_use','id':'t2','name':'Bash','input':{'command':'dir'}}],
                                    'stop_reason':'tool_use'}}).encode()
        running=self.read([tool])
        self.assertEqual((running['step'],running['running']),('run',True))


class FakeControl:
    """One piece of Claude's page for the attachment tests: names, parents and rectangles, never a real window."""
    def __init__(self,name='',kind='GroupControl',parent=None,rect=None,runtime=None,offscreen=False):
        self.Name=name;self.ControlTypeName=kind;self.IsOffscreen=offscreen;self.IsEnabled=True
        self.children=[];self.invoked=0;self.written=[];self.HasKeyboardFocus=False
        self._parent=parent;self._rect=rect;self._runtime=runtime
        if parent is not None:parent.children.append(self)
    def GetParentControl(self):return self._parent
    def GetRuntimeId(self):
        if self._runtime is None:raise RuntimeError('no runtime id')
        return self._runtime
    @property
    def BoundingRectangle(self):
        if self._rect is None:raise RuntimeError('no rectangle')
        left,top,right,bottom=self._rect
        return SimpleNamespace(left=left,top=top,right=right,bottom=bottom)
    def SetFocus(self):self.HasKeyboardFocus=True
    def GetInvokePattern(self):return SimpleNamespace(Invoke=self._invoke)
    def _invoke(self):self.invoked+=1;return True
    def GetValuePattern(self):return SimpleNamespace(IsReadOnly=False,SetValue=self._write)
    def _write(self,text):self.written.append(text);return True


def find_in(scope,kind,name=None):
    """The subtree search `_find` does through Windows, over FakeControl children."""
    out=[];stack=list(scope.children)
    while stack:
        node=stack.pop()
        if node.ControlTypeName==kind and (name is None or node.Name==name):out.append(node)
        stack.extend(node.children)
    return out


class FakeImage:
    """Stands in for PIL's Image in the paste tests: a bitmap needs no real file."""
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def convert(self,mode):return self
    def save(self,buffer,format):buffer.write(b'\0'*30)


class AttachmentCardTests(unittest.TestCase):
    """11-26 P6: pictures are counted by card, not by "Remove" button."""
    def tree(self):
        document=FakeControl('s - Claude Code','DocumentControl')
        composer=FakeControl('',parent=document)
        inner=FakeControl('',parent=composer)  # holds Add; the tray of current Claude sits one level above it
        edit=FakeControl('Prompt','EditControl',parent=inner)
        FakeControl('Add','ButtonControl',parent=inner)
        return composer,edit

    def card(self,composer,runtime,removes=1):
        card=FakeControl('',parent=composer,runtime=runtime)
        FakeControl('image.png','ButtonControl',parent=card)  # every clipboard image gets the same preview name
        for _ in range(removes):FakeControl('Remove image.png','ButtonControl',parent=card)
        return card

    def test_one_card_with_two_remove_buttons_counts_once(self):
        composer,edit=self.tree();self.card(composer,(1,2),removes=2)
        d=object.__new__(chats.Desktop);d._find=find_in
        self.assertEqual(d._claude_image_count(edit),1)
        self.card(composer,(3,4))
        self.assertEqual(d._claude_image_count(edit),2)  # two cards, told apart by their RuntimeId

    def test_a_hover_only_remove_still_counts_the_card_its_preview_pairs_with(self):
        composer,edit=self.tree()
        card=FakeControl('',parent=composer,runtime=(5,6))
        FakeControl('image.png','ButtonControl',parent=card,offscreen=True)
        FakeControl('Remove image.png','ButtonControl',parent=card,offscreen=True)
        d=object.__new__(chats.Desktop);d._find=find_in
        self.assertEqual(d._claude_image_count(edit),1)

    def test_buttons_without_a_readable_card_are_grouped_by_where_they_sit(self):
        composer,edit=self.tree()
        flat=[FakeControl('Add','ButtonControl'),FakeControl('Remove image.png','ButtonControl',rect=(100,100,164,164)),
              FakeControl('Remove image.png','ButtonControl',rect=(104,100,168,164))]
        d=object.__new__(chats.Desktop);d._claude_attachment_scope=Mock(return_value='scope');d._find=Mock(return_value=flat)
        self.assertEqual(d._claude_image_count(edit),1)  # the two sit on one card, their middles 4 px apart
        flat.append(FakeControl('Remove image.png','ButtonControl',rect=(300,100,364,164)))
        self.assertEqual(d._claude_image_count(edit),2)  # another card 200 px away


class AttachmentPasteTests(unittest.TestCase):
    """11-26 P6: the wait is longer, the count has to hold still, and more cards than wanted stops at once."""
    def desktop(self,count):
        d=object.__new__(chats.Desktop);edit=FakeControl('Prompt','EditControl')
        d._claude_verified_prompt=Mock(return_value=('doc',edit));d._claude_image_count=count;d.log=Mock()
        return d,edit

    def paste(self):
        clipboard=SimpleNamespace(EnumClipboardFormats=lambda fmt:0,EmptyClipboard=lambda:None,SetClipboardData=lambda fmt,data:None,
                                  GetClipboardSequenceNumber=lambda:1,CloseClipboard=lambda:None,GetClipboardData=lambda fmt:b'')
        return patch.dict(sys.modules,{'win32clipboard':clipboard,
                                       'PIL':SimpleNamespace(Image=SimpleNamespace(open=lambda path:FakeImage()))})

    def test_a_card_that_shows_up_after_eight_seconds_is_accepted_and_the_paste_is_pressed_once(self):
        clock={'now':0.0}
        d,edit=self.desktop(lambda box:0 if clock['now']<8 else 1)
        with self.paste(),patch('chats._clip_open'),patch('chats.winctl.focus'),patch('chats.winctl.press') as press,\
             patch('chats.time.monotonic',side_effect=lambda:clock['now']),\
             patch('chats.time.sleep',side_effect=lambda seconds:clock.__setitem__('now',clock['now']+seconds)):
            d._paste_claude_image(7,'root',{'id':'s'},edit,'one.png',1)
        self.assertEqual(press.call_args_list,[call(7,'Control+v')])  # waiting never pastes again
        self.assertTrue(8.5<=clock['now']<=9.0,clock['now'])  # the card's 0.6 s of holding still, no more

    def test_more_cards_than_wanted_stop_at_once_and_say_so(self):
        d,edit=self.desktop(Mock(return_value=2))
        with self.paste(),patch('chats._clip_open'),patch('chats.winctl.focus'),patch('chats.winctl.press') as press:
            with self.assertRaises(chats.InputNotSubmitted) as refused:
                d._paste_claude_image(7,'root',{'id':'s'},edit,'one.png',1)
        self.assertEqual(str(refused.exception),'电脑上 Claude 输入框里出现了 2 张图，比要发的多，尚未发送')
        self.assertEqual(press.call_count,1)

    def test_a_card_that_never_shows_up_reports_numbers_only(self):
        clock={'now':0.0}
        d,edit=self.desktop(Mock(return_value=0))
        with self.paste(),patch('chats._clip_open'),patch('chats.winctl.focus'),patch('chats.winctl.press'),\
             patch('chats.time.monotonic',side_effect=lambda:clock['now']),\
             patch('chats.time.sleep',side_effect=lambda seconds:clock.__setitem__('now',clock['now']+seconds)):
            with self.assertRaises(chats.InputNotSubmitted) as refused:
                d._paste_claude_image(7,'root',{'id':'s'},edit,'secret-name.png',1)
        self.assertIn('第 1 张图片核验未通过（输入区识别到 0 张）',str(refused.exception))
        self.assertGreaterEqual(clock['now'],chats.CLAUDE_ATTACH_WAIT)
        line=d.log.call_args[0][0]
        self.assertIn('Claude attachment probe expected=1 observed=0',line)
        self.assertIn('removes(kind,parent,at)',line)
        self.assertNotIn('secret-name.png',line)  # a file name never reaches the log

    def test_five_slow_pictures_stop_at_the_picture_time_limit_and_are_taken_back(self):
        # 11-26: one send's pictures together may take CLAUDE_IMAGES_WAIT, not 20 s each: the phone gives the send 60 s
        clock={'now':0.0}
        d=object.__new__(chats.Desktop);d.input_lock=threading.Lock();d.log=Mock();d.sent_last={}
        edit=FakeControl('Prompt','EditControl')
        d._claude_open=Mock(return_value=(1,'root'));d._claude_show=Mock();d._keyboard_owner=Mock(return_value=None)
        d._claude_wait_prompt=Mock();d._fill_claude_prompt=Mock(return_value=('doc',edit))
        d._claude_verified_prompt=Mock(return_value=('doc',edit))
        d._claude_image_count=lambda box:min(5,int(clock['now']//7))  # every card takes seven seconds to show
        d._claude_take_back=Mock()
        submit=Mock();d._claude_send_button=Mock(return_value=SimpleNamespace(GetInvokePattern=lambda:SimpleNamespace(Invoke=submit)))
        with self.paste(),patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'),\
             patch('chats.winctl.focus'),patch('chats.winctl.press'),patch('chats._clip_open'),\
             patch('chats.time.monotonic',side_effect=lambda:clock['now']),\
             patch('chats.time.sleep',side_effect=lambda seconds:clock.__setitem__('now',clock['now']+seconds)):
            with self.assertRaises(chats.InputNotSubmitted) as refused:
                d._send_claude({'id':'s','title':'test'},'test',[{'path':f'{i}.png'} for i in range(1,6)])
        self.assertEqual(str(refused.exception),'电脑上 Claude 显示图片太慢，尚未发送')
        self.assertLessEqual(clock['now'],chats.CLAUDE_IMAGES_WAIT+0.5,clock['now'])
        d._claude_take_back.assert_called_once()
        submit.assert_not_called()

    def test_taking_back_presses_one_remove_per_card_and_clears_the_words(self):
        d,edit=self.desktop(Mock(return_value=0))
        first,second,late=(FakeControl('Remove image.png','ButtonControl') for _ in range(3))
        d._claude_attachment_cards=Mock(side_effect=[[{'removes':[{'button':first}]},{'removes':[{'button':second}]}],[{'removes':[{'button':late}]}]])
        with patch('chats.time.sleep') as sleep:d._claude_take_back('root',{'id':'s'})
        self.assertEqual((first.invoked,second.invoked,late.invoked),(1,1,1))
        self.assertEqual(edit.written,[''])  # the words this send wrote go too
        self.assertEqual(sleep.call_args_list,[call(chats.CLAUDE_ATTACH_RECALL_WAIT)])
        self.assertIn('removed=3 late=1 cleared=1',d.log.call_args[0][0])

    def test_an_over_counted_send_takes_the_pictures_back_and_presses_nothing(self):
        edit=Edit();d=object.__new__(chats.Desktop);d.input_lock=threading.Lock();d.log=Mock();d.sent_last={}
        d._claude_open=Mock(return_value=(1,'root'));d._claude_verified_prompt=Mock(return_value=('doc',edit))
        d._claude_show=Mock();d._keyboard_owner=Mock(return_value=None);d._claude_wait_prompt=Mock()
        d._find=Mock(return_value=[SimpleNamespace(ControlTypeName='ButtonControl',Name='Send',IsOffscreen=False,IsEnabled=True,
                                                  GetParentControl=lambda:None,
                                                  GetInvokePattern=lambda:SimpleNamespace(Invoke=Mock(return_value=True)))])
        submit=Mock();d._claude_send_button=Mock(return_value=SimpleNamespace(GetInvokePattern=lambda:SimpleNamespace(Invoke=submit)))
        d._claude_image_count=Mock(return_value=0)
        d._paste_claude_image=Mock(side_effect=chats.InputNotSubmitted('电脑上 Claude 输入框里出现了 2 张图，比要发的多，尚未发送'))
        d._claude_take_back=Mock()
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):
            with self.assertRaises(chats.InputNotSubmitted) as refused:
                d._send_claude({'id':'s','title':'test'},'test',[{'path':'one.png'}])
        self.assertIn('比要发的多',str(refused.exception))
        submit.assert_not_called()
        d._claude_take_back.assert_called_once_with('root',{'id':'s','title':'test'})

    def test_a_refused_image_send_is_not_submitted_and_still_clears_nothing_else(self):
        # the pre-paste check that the box is empty refuses before anything of this send is pasted: nothing is taken back
        edit=Edit();d=object.__new__(chats.Desktop);d.input_lock=threading.Lock();d.log=Mock();d.sent_last={}
        d._claude_open=Mock(return_value=(1,'root'));d._claude_verified_prompt=Mock(return_value=('doc',edit))
        d._claude_show=Mock();d._keyboard_owner=Mock(return_value=None);d._claude_wait_prompt=Mock()
        d._claude_image_count=Mock(return_value=1);d._paste_claude_image=Mock();d._claude_take_back=Mock()
        with patch('chats.require_send_desktop'),patch('chats.conversation_title',return_value='test'):
            with self.assertRaises(chats.InputNotSubmitted):
                d._send_claude({'id':'s','title':'test'},'test',[{'path':'one.png'}])
        d._paste_claude_image.assert_not_called();d._claude_take_back.assert_not_called()


class DeliveryRecordFixture(unittest.TestCase):
    """A real delivery record in a temporary folder, and a handler whose computer it is; no desktop is ever touched."""
    def setUp(self):
        import codex_control
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bridge=codex_control.Bridge();self.bridge.data_root=Path(self.tmp.name)
        self.bridge.attachment=Mock(return_value={'id':'c'*32,'path':str(Path(self.tmp.name)/'one.png'),'app':'claude',
                                                  'original_size':10,'width':1,'height':1})
        self.bridge._write_meta=Mock()
        self.item={'id':'local_s','app':'claude','title':'t'}
    def handler(self,send):
        return SimpleNamespace(server=SimpleNamespace(codex=self.bridge,claude=SimpleNamespace(hooks=None)),
                               desktop=SimpleNamespace(send=send))
    def hook_handler(self):
        return SimpleNamespace(server=SimpleNamespace(codex=self.bridge,claude=SimpleNamespace(hooks=None)),desktop=SimpleNamespace())


class AttachmentDeliveryTests(DeliveryRecordFixture):
    """11-26 P6: an image send the desktop turned away before submitting is 未接收 in the record, not 待确认 for good."""
    def test_a_refused_image_send_reads_back_as_rejected_and_never_as_still_pending(self):
        from agents.claude import ClaudeAgent
        send=Mock(side_effect=chats.InputNotSubmitted('Claude 桌面已有附件，尚未发送；请先处理桌面草稿'))
        body={'id':'local_s','text':'看图','attachments':['c'*32],'request_id':'img-refusal-0001'}
        with self.assertRaises(chats.InputNotSubmitted):
            ClaudeAgent().chat_send_with_references(self.handler(send),body)
        rec=self.bridge.receipt('local_s','img-refusal-0001')
        self.assertEqual(rec['state'],'rejected')
        self.assertIn('尚未发送',rec['result']['text'])
        again=ClaudeAgent().chat_send_with_references(self.handler(send),body)  # the same request number again
        self.assertEqual(again['delivery_state'],'rejected')  # the record's answer, not “这次请求已提交过”
        self.assertEqual(send.call_count,1)


class TextSendDeliveryTests(DeliveryRecordFixture):
    """11-26: every Claude send keeps a record, words as well as pictures, so 核对 answers for a plain message too and a
    resend of the same number never reaches Claude twice."""
    def text_body(self,request_id):
        return {'id':'local_s','text':'你好','request_id':request_id}
    def test_a_text_send_keeps_a_record_and_the_same_number_returns_it(self):
        from agents.claude import ClaudeAgent
        send=Mock(return_value={'ok':True,'pressed':True,'offset':0,'running':False,'text':'已提交'})
        first=ClaudeAgent().chat_send_with_references(self.handler(send),self.text_body('text-request-0001'))
        rec=self.bridge.receipt('local_s','text-request-0001')
        self.assertEqual(rec['state'],'accepted')  # the phone never reports 电脑没收到 for a message that arrived
        self.assertNotIn('missing',rec)
        self.assertEqual(rec['result']['text'],'已提交')
        again=ClaudeAgent().chat_send_with_references(self.handler(send),self.text_body('text-request-0001'))
        self.assertEqual(again,first)  # the record's answer, not a second message
        self.assertEqual(send.call_count,1)
    def test_a_refused_text_send_is_rejected_and_replays_as_rejected(self):
        from agents.claude import ClaudeAgent
        send=Mock(side_effect=chats.DesktopDraft('电脑上 Claude 的输入框里有别的字','e'))
        with self.assertRaises(chats.InputNotSubmitted):
            ClaudeAgent().chat_send_with_references(self.handler(send),self.text_body('text-refusal-0001'))
        rec=self.bridge.receipt('local_s','text-refusal-0001')
        self.assertEqual(rec['state'],'rejected')
        again=ClaudeAgent().chat_send_with_references(self.handler(send),self.text_body('text-refusal-0001'))
        self.assertEqual(again['delivery_state'],'rejected')
        self.assertEqual(send.call_count,1)


class HookQueueDeliveryTests(DeliveryRecordFixture):
    """11-26: a message handed to 遥应 while Claude runs keeps a record too, words as well as pictures."""
    def agent(self,hook):
        from agents.claude import ClaudeAgent
        agent=ClaudeAgent();agent._hook_bridge=Mock(return_value=hook);agent._hook_running=Mock(return_value=True)
        return agent
    def test_a_queued_text_send_keeps_a_record_and_the_same_number_replays_it(self):
        hook=Mock();hook.enqueue_message.return_value=('queued-1',False)
        agent=self.agent(hook);body={'id':'local_s','text':'排队的话','request_id':'queue-request-0001'}
        with patch('chats.find',return_value=self.item),patch('chats.conv_path',return_value=None),patch('chats.file_size',return_value=0):
            first=agent._hook_queue_send(self.hook_handler(),self.item,'local_s','排队的话',[],body)
        self.assertTrue(first['queued'])
        rec=self.bridge.receipt('local_s','queue-request-0001')
        self.assertEqual(rec['state'],'accepted')
        self.assertNotIn('missing',rec)
        with patch('chats.find',return_value=self.item),patch('chats.conv_path',return_value=None),patch('chats.file_size',return_value=0):
            again=agent._hook_queue_send(self.hook_handler(),self.item,'local_s','排队的话',[],body)
        self.assertEqual(again,first)  # the record's answer, not a second queue entry
        self.assertEqual(hook.enqueue_message.call_count,1)


class SteerDeliveryTests(DeliveryRecordFixture):
    """11-26: 插话 keeps its in-memory guard and writes a delivery record as well."""
    def controller(self):
        import claude_control
        desktop=Mock();desktop.run=lambda fn,*a,**kw:fn(*a)
        desktop.send=Mock(return_value={'ok':True,'pressed':True,'offset':7,'running':True,'text':'已提交'})
        ctrl=claude_control.Controller(desktop);ctrl.hooks=None;ctrl.deliveries=self.bridge
        ctrl._read=Mock(return_value={'on_screen':True,'running':True,'turn_anchor':'anchor-1'})
        ctrl._document=Mock(return_value=(0,None,'doc'));ctrl._queued=Mock(return_value=[])
        return ctrl,desktop
    def test_a_steer_keeps_a_record_and_the_same_number_replays_it(self):
        ctrl,desktop=self.controller()
        with patch('chats.find',return_value=self.item),patch('chats.Desktop.check',return_value={'delivered':True}):
            first=ctrl.send_steer('local_s','补充一句','anchor-1','steer-request-0001')
        rec=self.bridge.receipt('local_s','steer-request-0001')
        self.assertEqual(rec['state'],'accepted')
        self.assertNotIn('missing',rec)
        ctrl.steer_submissions.clear()  # as after a restart: only the record is left
        with patch('chats.find',return_value=self.item),patch('chats.Desktop.check',return_value={'delivered':True}):
            again=ctrl.send_steer('local_s','补充一句','anchor-1','steer-request-0001')
        self.assertEqual(again,first)
        self.assertEqual(desktop.send.call_count,1)
    def test_a_steer_that_never_got_submitted_is_rejected(self):
        ctrl,desktop=self.controller()
        desktop.run=Mock(side_effect=chats.InputNotSubmitted('Claude 当前轮次已变化，尚未发送补充指令'))
        with patch('chats.find',return_value=self.item):
            with self.assertRaises(chats.InputNotSubmitted):
                ctrl.send_steer('local_s','补充一句','anchor-1','steer-refusal-0001')
        self.assertEqual(self.bridge.receipt('local_s','steer-refusal-0001')['state'],'rejected')


if __name__=='__main__':unittest.main()

