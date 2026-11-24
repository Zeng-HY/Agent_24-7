"""11-24: a Claude state poll answered from a window read 4-60 s old, at once, with what the hooks and the record say
now, while the window is read again in the background. Fake desktop and hooks; a synthetic record in a temporary folder."""
import copy,json,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import claude_control

TID='local_swr'
ITEM={'app':'claude','id':TID,'title':'swr','cwd':'','cli':'cli-swr'}
RECORDED={'model':'claude-opus-5-5','effort':'high','mode':'auto','recorded_at':1}


def line(value):return json.dumps(value,ensure_ascii=False)+'\n'
def user(uuid,text):return line({'type':'user','uuid':uuid,'timestamp':'2026-11-24T04:00:00Z','message':{'role':'user','content':text}})


class Hooks:
    """What claude_hooks.Bridge tells the controller, set by the test."""
    def __init__(self):self.active=True;self.running=False;self.held=None;self.queue=[]
    def is_active(self,tid):return self.active
    def conv_state(self,tid):
        return {'running':self.running,'turn_started':1767323500 if self.running else 0,'step':'run' if self.running else ''}
    def layout(self,tid):return copy.deepcopy(self.held)
    def just_answered(self,tid):return False
    def list_queued(self,tid):return list(self.queue)


class Desktop:
    """Claude's window showing this conversation, its model button and, when asked, Stop."""
    def __init__(self):self.reads=[];self.gate=None;self.buttons=['Model: Opus 5.5 High'];self.fail=None
    def run(self,fn,*args,**kwargs):
        background=threading.current_thread() is not threading.main_thread()
        self.reads.append('background' if background else 'now')
        if self.fail:raise self.fail
        if background and self.gate is not None and not self.gate.wait(10):raise AssertionError('gate never opened')
        return fn(*args)
    def _claude_unminimize(self):pass
    def _claude_where(self,ctrl):return (False,None)
    def _claude_ask(self,root,doc=None):return None
    def _find(self,scope,kind,name=None):
        if kind=='ButtonControl':return [SimpleNamespace(Name=n,IsOffscreen=False,IsEnabled=True) for n in self.buttons]
        return []


class StaleWhileRead(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory();self.addCleanup(self.td.cleanup)
        self.path=Path(self.td.name)/'cli-swr.jsonl';self.path.write_text(user('u1','开始'),encoding='utf-8')
        self.desktop=Desktop();self.hooks=Hooks()
        c=claude_control.Controller(self.desktop);c.catalogs={};c.catalog_path=Path(self.td.name)/'catalog.json'
        c.hooks=self.hooks;c._document=lambda item,open_first=False:(1,'root','doc');self.c=c
        for p in (patch('claude_control.chats.find',lambda app,tid:dict(ITEM)),
                  patch('claude_control.settings',lambda item:dict(RECORDED)),
                  patch('claude_control.chats.conv_path',lambda item:self.path),
                  patch('claude_control.chats.summary',lambda item:{'status':'idle','turn_started':0,'turn_ended':0,'step':''})):
            p.start();self.addCleanup(p.stop)
        self.addCleanup(self.join)

    def join(self):
        for t in list(self.c.revalidating.values()):t.join(10)
        self.assertFalse(any(t.is_alive() for t in self.c.revalidating.values()))

    def age(self,seconds):
        when,*rest=self.c.cache[TID];self.c.cache[TID]=(when-seconds,*rest)

    def test_a_read_under_4_s_old_is_answered_as_it_was(self):
        first=self.c.state(TID,True);self.age(2)
        self.assertEqual(self.c.state(TID),first)
        self.assertEqual(self.desktop.reads,['now'])

    def test_4_to_60_s_old_is_answered_at_once_with_the_hooks_as_now_and_read_again_behind(self):
        first=self.c.state(TID,True)
        self.assertFalse(first['running']);self.assertNotIn('stop_token',first)
        self.hooks.running=True;self.age(10)  # a turn the hooks saw start since the window was read
        stale=self.c.state(TID)
        self.assertEqual(self.desktop.reads[0],'now')
        self.assertTrue(stale['running']);self.assertEqual(stale['step'],'run');self.assertTrue(stale['stop_token'])
        self.assertEqual(stale['observed_at'],first['observed_at'])  # the window's part is the read it was
        self.join()
        self.assertEqual(self.desktop.reads,['now','background'])
        renewed=self.c.cache[TID]
        self.assertTrue(renewed[1]['running'])
        self.assertEqual(self.c.state(TID)['running'],True);self.assertEqual(len(self.desktop.reads),2)  # young again
        now=self.c.state(TID,True)
        self.assertEqual(set(stale),set(now))  # the same shape as a read made now
        self.assertEqual(stale['stop_revision'],now['stop_revision'])

    def test_the_question_the_hooks_hold_is_the_current_one(self):
        self.c.state(TID,True);self.age(10)
        self.hooks.held=('ask-1',{'title':'Which fruit?','progress':None,'other':None,
                                 'choices':[{'name':'Apple','label':'Apple','do':['pick',0]}],'nav':[]},'stamp-1')
        stale=self.c.state(TID)
        self.assertEqual(stale['prompt']['title'],'Which fruit?');self.assertTrue(stale['prompt']['choices'][0]['token'])
        self.assertEqual(stale['actions'],[])
        self.assertEqual(self.desktop.reads[0],'now')

    def test_the_queue_teleply_holds_is_the_current_one(self):
        self.hooks.queue=[{'id':'q-old','text':'一'}]
        first=self.c.state(TID,True)
        self.assertEqual([q['id'] for q in first['queued']],['q-old'])
        self.hooks.queue=[{'id':'q-new','text':'二'}];self.age(10)
        self.assertEqual([q['id'] for q in self.c.state(TID)['queued']],['q-new'])
        self.assertEqual(self.c.cache[TID][2]['queued'],[])  # the window's own part holds no hook messages

    def test_a_desktop_question_or_buttons_are_never_answered_stale(self):
        for shown in ({'prompt':{'title':'Proceed?','progress':None,'choices':[],'nav':[],'other':None}},
                      {'actions':[{'name':'Yes','type':'ButtonControl','token':'t'}]}):
            with self.subTest(shown=list(shown)):
                self.c.cache.clear();self.desktop.reads.clear()
                self.c.state(TID,True);self.c.cache[TID][2].update(shown);self.age(10)
                answer=self.c.state(TID)
                self.assertEqual(self.desktop.reads,['now','now'])  # read again before answering
                self.assertEqual((answer['prompt'],answer['actions']),(None,[]))  # what the window shows now
                self.assertEqual(self.c.revalidating,{})

    def test_older_than_60_s_or_fresh_is_read_now(self):
        self.c.state(TID,True);self.age(61)
        self.c.state(TID);self.assertEqual(self.desktop.reads,['now','now'])
        self.age(10);self.c.state(TID,True);self.assertEqual(self.desktop.reads,['now','now','now'])
        self.assertEqual(self.c.revalidating,{})

    def test_a_turn_begun_since_is_read_now(self):
        self.desktop.buttons.append('Stop');self.hooks.running=True;first=self.c.state(TID,True)
        with self.path.open('a',encoding='utf-8') as f:f.write(user('u2','下一轮'))
        self.age(10);now=self.c.state(TID)
        self.assertEqual(self.desktop.reads,['now','now'])
        self.assertNotEqual(now['stop_revision'],first['stop_revision'])  # bound to the new turn

    def test_a_question_in_the_record_is_read_now(self):
        self.c.state(TID,True)
        with self.path.open('a',encoding='utf-8') as f:
            f.write(line({'type':'assistant','uuid':'a1','timestamp':'2026-11-24T04:00:01Z','message':{'role':'assistant',
                          'stop_reason':'tool_use','content':[{'type':'tool_use','id':'toolu_q','name':'AskUserQuestion','input':{'questions':[]}}]}}))
        self.age(10);self.c.state(TID)
        self.assertEqual(self.desktop.reads,['now','now'])

    def test_a_failed_read_is_not_answered_from(self):
        self.desktop.fail=TimeoutError('the desktop worker was busy');first=self.c.state(TID,True)
        self.assertEqual(first['reason'],'the desktop worker was busy')
        self.assertIsNone(self.c.cache[TID][2])
        self.desktop.fail=None;self.age(10);self.c.state(TID)
        self.assertEqual(self.desktop.reads,['now','now'])

    def test_one_read_behind_per_conversation_and_one_from_before_an_action_is_not_kept(self):
        self.c.state(TID,True);self.age(10);self.desktop.gate=threading.Event()
        self.c.state(TID);self.c.state(TID)  # two polls while the window is read behind
        self.assertEqual(len(self.c.revalidating),1)
        self.c.cache.pop(TID)  # an action on the conversation drops what was read before it
        self.desktop.gate.set();self.join()
        self.assertEqual(self.desktop.reads,['now','background'])
        self.assertNotIn(TID,self.c.cache)


if __name__=='__main__':unittest.main()
