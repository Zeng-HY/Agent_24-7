import json,sys,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
from claude_control import Controller,MODE_CHOICES,load_modes,signature,usage_from_label

class Desktop:
    def run(self,fn,*args,**kwargs):return fn(*args)

class Control:
    def __init__(self):self.calls=0
    def GetInvokePattern(self):return self
    def Invoke(self):self.calls+=1

class Tests(unittest.TestCase):
    def test_expand_only_buttons_and_no_duplicate_action_on_error(self):
        class Expand:
            ExpandCollapseState=0
            def Expand(self):self.ExpandCollapseState=1;return True
        pattern=Expand();button=SimpleNamespace(GetExpandCollapsePattern=lambda:pattern)
        Controller._expand(button,True);self.assertEqual(pattern.ExpandCollapseState,1)
        legacy=Control();legacy.DoDefaultAction=legacy.Invoke
        Controller._invoke(SimpleNamespace(GetInvokePattern=lambda:None,GetLegacyIAccessiblePattern=lambda:legacy))
        self.assertEqual(legacy.calls,1)
        class Broken:
            def Invoke(self):raise RuntimeError('response lost')
        with self.assertRaises(chats.ChatError):Controller._invoke(SimpleNamespace(GetInvokePattern=lambda:Broken(),GetLegacyIAccessiblePattern=lambda:legacy))
        self.assertEqual(legacy.calls,1)
    def test_a_control_drawn_anew_is_read_again_and_told_in_words(self):
        # 10-14: after a switch to Sonnet the phone showed "(-2147220991, '事件无法调用任何订户', …)" on 刷新桌面目录
        import tempfile
        from claude_control import COMError,GONE,plain_error
        gone=lambda:COMError(GONE,'事件无法调用任何订户',(None,None,None,0,None))
        c=Controller(Desktop());c.catalog_path=Path(tempfile.mkdtemp())/'catalogs.json';calls=[]
        def flaky():
            calls.append(1)
            if len(calls)==1:raise gone()
            return 'read'
        self.assertEqual(c._again(flaky),'read');self.assertEqual(len(calls),2)
        self.assertEqual(plain_error(gone()),'电脑上的 Claude 界面正好在重画，这次没读到，请再试一次')
        self.assertEqual(plain_error(chats.ChatError('原样')),'原样')
        tries={'model':0,'effort':0}
        def menu(item,kind):
            tries[kind]=tries.get(kind,0)+1
            if kind=='model' and tries['model']==1:raise gone()  # once: read again
            if kind=='effort':raise gone()                        # every time: said in words
            return [(None,{'name':'Sonnet 5.5','type':'MenuItemControl','selected':True})] if kind=='model' else []
        c._menu=menu;c._dismiss_popup=lambda *a:None
        with patch('claude_control.chats.find',return_value={'id':'s','title':'t'}),patch('claude_control.settings',return_value={'model':'claude-sonnet-5-5'}):
            result=c.catalog('s',fresh=True)
        self.assertEqual([v['name'] for v in result['model']],['Sonnet 5.5'])
        self.assertEqual((result['effort'],result['effort_reason']),([],'电脑上的 Claude 界面正好在重画，这次没读到，请再试一次'))
        self.assertEqual((tries['model'],tries['effort']),(2,2))  # each read once more after the first failure
    def test_a_popup_that_closes_while_looked_at_gets_no_escape(self):
        from claude_control import COMError,GONE
        class Vanishing:
            def Exists(self,*a):raise COMError(GONE,'事件无法调用任何订户',(None,None,None,0,None))
        root=SimpleNamespace(MenuControl=lambda **kw:Vanishing(),WindowControl=lambda **kw:Vanishing())
        c=Controller(Desktop());c._document=lambda item,*a:(1,root,None)
        with patch('claude_control.winctl.press',side_effect=AssertionError('no Escape into the composer')):
            self.assertIsNone(c._dismiss_popup({'id':'s'}))
    def test_new_conversation_options_from_the_menus_kept(self):
        # 10-14: steps whose name was never read on a model take the name another model gave the same step
        import tempfile
        c=Controller(Desktop());c.catalog_path=Path(tempfile.mkdtemp())/'c.json'
        c.catalogs={'labels:claude-opus-5-5:(0.0, 5.0, 1.0)':{'0':'Low','1':'Medium (Recommended)','2':'High','3':'Extra','4':'Max','5':'Ultracode'},
                    'labels:claude-sonnet-5-5:(0.0, 5.0, 1.0)':{'4':'Max'},
                    's1':{'model_id':'claude-opus-5-5','model':[{'name':'Opus 5.5','selected':True},{'name':'Sonnet 5.5','selected':False},{'name':'Haiku 5.5','selected':False}]}}
        models=c.new_options()['models']
        self.assertEqual([m['id'] for m in models],['Opus 5.5','Sonnet 5.5','Haiku 5.5'])
        self.assertEqual((models[1]['model_id'],[e['label'] for e in models[1]['efforts']]),('claude-sonnet-5-5',['Low','Medium (Recommended)','High','Extra','Max','Ultracode']))
        c.catalogs={};self.assertEqual(c.new_options()['models'],[])
    def test_new_conversation_model_and_effort_are_set_or_nothing_is_sent(self):
        import tempfile
        c=Controller(Desktop());c.catalog_path=Path(tempfile.mkdtemp())/'c.json';c._new_page=lambda hwnd:(hwnd,'root','doc')
        # a session switched to Sonnet whose recorded id still says Opus must not make Sonnet's steps Opus's (10-14)
        c.catalogs={'s1':{'model_id':'claude-opus-5-5','model':[{'name':'Opus 5.5','selected':False},{'name':'Sonnet 5.5','selected':True}]}}
        clicked=[];c._invoke=clicked.append;c._dismiss_popup=lambda *a:None;c.desktop._value=lambda ctrl:'High'
        class Slider:
            Value=1.0
            def GetRangeValuePattern(self):return self
            def SetValue(self,v):self.Value=v;return True
        slider=Slider()
        def menu(item,kind,page):
            if kind=='model':return [('opus',{'name':'Opus 5.5','selected':True}),('sonnet',{'name':'Sonnet 5.5','selected':False})]
            return [(slider,{'name':'Effort','type':'SliderControl','selected':True,'range':{'min':0.0,'max':5.0,'step':1.0,'value':1.0}})]
        c._menu=menu;c._shows=lambda hwnd,name,seconds=4:name=='Model: Sonnet 5.5';c._buttons=lambda doc:[SimpleNamespace(Name='Effort: Medium')]
        c.apply_new(7,'Sonnet 5.5',2)
        self.assertEqual((clicked,slider.Value),(['sonnet'],2))
        self.assertEqual(c.catalogs['labels:claude-sonnet-5-5:(0.0, 5.0, 1.0)']['2'],'High')  # the step's name, learnt
        with self.assertRaises(chats.InputNotSubmitted):c.apply_new(7,'Fable 5.1',None)  # not in the menu
        c._shows=lambda *a,**k:False
        with self.assertRaises(chats.InputNotSubmitted):c.apply_new(7,'Sonnet 5.5',None)  # the page did not switch

    def test_combined_model_effort_and_preset_labels(self):
        from claude_control import model_label,effort_label
        self.assertEqual(model_label('Model: Opus 5.5 High'),'Opus 5.5')
        self.assertEqual(model_label('Opus 5.5 Preset'),'Opus 5.5')
        self.assertEqual(effort_label('Max 3.5× or more usage'),'Max')
        c=Controller(Desktop());c._new_page=lambda hwnd:(hwnd,'root','doc')
        c._buttons=lambda doc:[SimpleNamespace(Name='Model: Opus 5.5 High')]
        self.assertTrue(c._shows(1,'Model: Opus 5.5',seconds=0))
        self.assertFalse(c._shows(1,'Model: Sonnet 5.5',seconds=0))

    def test_new_numeric_effort_maps_to_current_named_menu_and_is_verified(self):
        c=Controller(Desktop());c._new_page=lambda hwnd:(hwnd,'root','doc')
        c._save_catalogs=lambda:None;c._dismiss_popup=lambda *a:None
        label=['High'];clicked=[]
        c._buttons=lambda doc:[SimpleNamespace(Name='Model: Opus 5.5 '+label[0])]
        c._menu=lambda *a:[('max',{'name':'Max 3.5× or more usage','selected':False}),('high',{'name':'High','selected':True})]
        def invoke(ctrl):clicked.append(ctrl);label[0]='Max'
        c._invoke=invoke
        c.apply_new(1,None,4)
        self.assertEqual(clicked,['max'])
        c._buttons=lambda doc:[SimpleNamespace(Name='Model: Haiku 5.5')]
        with self.assertRaises(chats.InputNotSubmitted):c.apply_new(1,None,4)
    def test_current_session_is_not_reopened(self):
        doc=SimpleNamespace(Exists=lambda *a:True)
        desk=Desktop();desk._claude_root=lambda:(1,SimpleNamespace(DocumentControl=lambda **kw:doc));desk._value=lambda _:'https://claude.ai/epitaxy/s'
        desk._claude_open=lambda *a:self.fail('same-session deep link must not be reopened')
        self.assertEqual(Controller(desk)._document({'id':'s','title':'same'},True)[0],1)
    def test_context_provenance(self):
        value=usage_from_label('Usage: Context 610k / 1M (61%), Weekly: 14%')
        self.assertEqual((value['used_tokens'],value['context_window'],value['percent']),(610000,1000000,61))
        self.assertIsNone(usage_from_label('Usage: Weekly 14%'))
        line={'type':'assistant','timestamp':'now','message':{'model':'actual-model','usage':{'input_tokens':2,'cache_read_input_tokens':200,'cache_creation_input_tokens':30,'output_tokens':9999}}}
        value=chats.parse_runtime('claude',[json.dumps(line).encode()]);self.assertEqual(value['used_tokens'],232);self.assertIsNone(value['percent'])
    def test_exact_session_url_even_with_same_title(self):
        doc=SimpleNamespace(Exists=lambda *a:True,GetLegacyIAccessiblePattern=lambda:SimpleNamespace(Value='https://claude.ai/epitaxy/wrong'))
        desk=Desktop();desk._claude_root=lambda:(1,SimpleNamespace(DocumentControl=lambda **kw:doc));desk._value=lambda _:''
        with self.assertRaises(chats.ChatError):Controller(desk)._document({'id':'wanted','title':'same'})
    def test_menu_choice_and_duplicate_request(self):
        ctrl=Control();c=Controller(Desktop());c._dismiss_popup=lambda *a:None;item={'id':'s','title':'test'};s={'model':'a','effort':'low','mode':'plan','recorded_at':100}
        option={'name':'Model B','type':'MenuItemControl','selected':False};c._menu=lambda *a:[(ctrl,option)];c._read=lambda _: {'settings':{'model':'b'}}
        revision=signature([{k:v for k,v in s.items() if k!='recorded_at'},['Model B']]);token=c._ticket('s','model',option,revision)
        with patch('claude_control.chats.find',return_value=item),patch('claude_control.settings',return_value=s):
            self.assertTrue(c.choose('s',token)['ok']);self.assertEqual(ctrl.calls,1)
            with self.assertRaises(chats.ChatError):c.choose('s',token)
            token=c._ticket('s','model',option,'stale')
            with self.assertRaises(chats.ChatError):c.choose('s',token)
            self.assertEqual(ctrl.calls,1)
    def test_mode_list_kept_and_pick_applied_by_name(self):
        # 10-11: the phone lists the modes at once from the last desktop read and sends only the name it picked
        import tempfile
        ask,plan=Control(),Control();c=Controller(Desktop());c._dismiss_popup=lambda *a:None
        item={'id':'s','title':'test'};s={'model':'a','effort':'low','mode':'auto','recorded_at':100}
        options=[(ask,{'name':'Ask permissions','type':'MenuItemControl','selected':False}),(plan,{'name':'Plan mode','type':'MenuItemControl','selected':False})]
        labels=['Auto','Plan']  # the mode button by the message box: still Auto right after the click, then Plan
        c._menu=lambda *a:options;c._read=lambda _:{'settings':s,'mode_label':labels.pop(0) if len(labels)>1 else labels[0]}
        with tempfile.TemporaryDirectory() as tmp,patch('claude_control.chats.find',return_value=item),patch('claude_control.settings',return_value=s):
            c.modes_path=Path(tmp)/'claude-modes.json';c.modes=[]
            result=c.select_setting('s','mode','Plan mode')
            self.assertEqual((plan.calls,ask.calls),(1,0))
            self.assertEqual(result['state']['mode_label'],'Plan')
            self.assertEqual([m['name'] for m in load_modes(c.modes_path)],['Ask permissions','Plan mode'])
            with self.assertRaises(chats.ChatError):c.select_setting('s','mode','Manual')  # no longer offered: nothing clicked
            self.assertEqual((plan.calls,ask.calls),(1,0))
            labels[:]=['Auto']  # the desktop never follows: say so instead of claiming the switch
            with self.assertRaises(chats.ChatError):c.select_setting('s','mode','Ask permissions')
    def test_auto_can_be_picked_but_never_a_blanket_bypass(self):
        # 10-12: the user's sessions run in Auto, and a pick of Plan on the phone could not be undone there
        for name in ('Auto Runs without asking.','Manual Always ask before making changes','Plan Create a plan before making changes','Ask permissions','Plan mode'):
            self.assertTrue(MODE_CHOICES.match(name),name)
        for name in ('Skip all approvals Claude never pauses, even for unsafe actions.','Bypass permissions Accepts all permissions',
                     'Accept edits Automatically accept all file edits','Automatically approve Claude handles permission decisions'):
            self.assertFalse(MODE_CHOICES.match(name),name)
    def test_auto_is_found_by_its_first_word(self):
        # 10-12 on the PC: Auto read 'Auto Claude handles permission decisions' while on, 'Auto Recommended Claude handles…'
        # once Plan was; picked by its whole name as last read, it was not found and Plan could not be left
        import tempfile
        auto,plan=Control(),Control();c=Controller(Desktop());c._dismiss_popup=lambda *a:None
        item={'id':'s','title':'test'};s={'model':'a','effort':'low','mode':'plan','recorded_at':100}
        options=[(auto,{'name':'Auto Recommended Claude handles permission decisions','type':'RadioButtonControl','selected':False}),
                 (plan,{'name':'Plan Create a plan before making changes','type':'RadioButtonControl','selected':True})]
        labels=['Plan','Auto']  # the mode button by the message box: still Plan right after the click, then Auto
        c._menu=lambda *a:options;c._read=lambda _:{'settings':s,'mode_label':labels.pop(0) if len(labels)>1 else labels[0]}
        with tempfile.TemporaryDirectory() as tmp,patch('claude_control.chats.find',return_value=item),patch('claude_control.settings',return_value=s):
            c.modes_path=Path(tmp)/'claude-modes.json';c.modes=[]
            result=c.select_setting('s','mode','Auto Claude handles permission decisions')
        self.assertEqual((auto.calls,plan.calls),(1,0));self.assertEqual(result['state']['mode_label'],'Auto')
    def test_a_mode_list_kept_before_auto_was_allowed_is_read_again(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'claude-modes.json'
            path.write_text(json.dumps([{'name':'Manual Always ask before making changes'},{'name':'Plan Create a plan before making changes'}]),encoding='utf-8')
            self.assertEqual(load_modes(path),[])  # kept without Auto: the phone reads the desktop menu once more
            path.write_text(json.dumps({'version':2,'modes':[{'name':'Auto Runs without asking.'}]}),encoding='utf-8')
            self.assertEqual(load_modes(path),[{'name':'Auto Runs without asking.'}])
            self.assertEqual(load_modes(Path(tmp)/'missing.json'),[])
    def test_stale_plan_and_old_stop_rejected(self):
        c=Controller(Desktop());c._read=lambda _:{'action_revision':'new','running':True,'stop_revision':'new-turn'}
        c._action_state=lambda _:('new',None)  # 10-11: actions check the dock alone, without a full _read
        with patch('claude_control.chats.find',return_value={'id':'s'}):
            for kind,revision in [('action','old'),('stop','old-turn')]:
                token=c._ticket('s',kind,{'name':'Execute'},revision)
                with self.assertRaises(chats.ChatError):c.choose('s',token)

if __name__=='__main__':unittest.main()
