"""11-24: opening a big conversation fast. The parsed-transcript cache is bounded by the memory the messages take, not by
the size of their files; a cold parse no longer holds History's lock; the conversations updated last are read ahead in
slices. Synthetic records in temporary folders only."""
import gc,json,sys,threading,tempfile,time,tracemalloc,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chat_history
from chat_history import History,Transcript


def record(n,text=None,tool=False):
    """Claude record lines for one exchange: the user's message, then a tool call and its (long) result, then the answer."""
    ts='2026-11-24T04:%02d:%02dZ'%(n//60%60,n%60)
    out=[{'type':'user','uuid':f'u{n}','timestamp':ts,'message':{'role':'user','content':text or f'问题 {n}：这一轮要做什么'}}]
    if tool:
        out+=[{'type':'assistant','uuid':f't{n}','timestamp':ts,'message':{'role':'assistant','stop_reason':'tool_use','content':[
                  {'type':'tool_use','id':f'toolu_{n}','name':'Bash','input':{'command':f'echo {n}'}}]}},
              {'type':'user','uuid':f'r{n}','timestamp':ts,'message':{'role':'user','content':[
                  {'type':'tool_result','tool_use_id':f'toolu_{n}','content':'output line\n'*400}]}}]
    out.append({'type':'assistant','uuid':f'a{n}','timestamp':ts,'message':{'role':'assistant','stop_reason':'end_turn',
               'content':[{'type':'text','text':f'第 {n} 个回答。'+'Some English words in the answer. '*20}]}})
    return ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in out)


def write(path,turns,tool=True,padding=0):
    """A record of turns exchanges; padding: a big line nothing is shown of (a screenshot's bytes), as real records hold."""
    text=''.join(record(n,tool=tool) for n in range(turns))
    if padding:text+=json.dumps({'type':'progress','uuid':'pad-'+path.stem,'data':'x'*padding})+'\n'
    path.write_text(text,encoding='utf-8')
    return path


class Weight(unittest.TestCase):
    def test_the_estimate_is_near_what_the_parsed_messages_take(self):
        with tempfile.TemporaryDirectory() as td:
            path=write(Path(td)/'one.jsonl',300)
            Transcript(path,'claude').refresh()  # the parsers' own first-use caches are not the transcript's
            gc.collect();tracemalloc.start()
            try:
                before=tracemalloc.get_traced_memory()[0]
                entry=Transcript(path,'claude').refresh()
                gc.collect();real=tracemalloc.get_traced_memory()[0]-before
            finally:tracemalloc.stop()
            self.assertGreater(len(entry.messages),600)
            self.assertTrue(.5<=entry.weight/real<=1.5,(entry.weight,real))

    def test_a_big_line_nothing_is_shown_of_weighs_nothing(self):
        # the file's size no longer stands for the memory: 3 MB of screenshot bytes keep nothing
        with tempfile.TemporaryDirectory() as td:
            plain=Transcript(write(Path(td)/'plain.jsonl',20),'claude').refresh()
            padded=Transcript(write(Path(td)/'padded.jsonl',20,padding=3<<20),'claude').refresh()
            self.assertGreater(padded.size,plain.size+(3<<20))
            self.assertLess(abs(padded.weight-plain.weight),2000)

    def test_a_parse_in_slices_ends_as_one_in_a_single_go(self):
        with tempfile.TemporaryDirectory() as td:
            path=write(Path(td)/'one.jsonl',120)
            whole=Transcript(path,'claude').refresh()
            sliced=Transcript(path,'claude');slices=0;offsets=[]
            while True:
                sliced.refresh(20000);slices+=1;offsets.append(sliced.offset)
                if not sliced.partial:break
            raw=path.read_bytes()
            self.assertGreater(slices,5)
            self.assertTrue(all(raw[o-1:o]==b'\n' for o in offsets))  # each slice ends at a line's end
            self.assertEqual(sliced.messages,whole.messages)
            self.assertEqual((sliced.state,sliced.offset,sliced.size),(whole.state,whole.offset,whole.size))
            self.assertEqual(sliced.context.get('activity_turns'),whole.context.get('activity_turns'))
            self.assertEqual(sliced.weight,whole.weight)
            # what the file gains later is read as before, and weighed with it
            with path.open('a',encoding='utf-8') as f:f.write(record(500,tool=True))
            self.assertEqual(sliced.refresh().messages,whole.refresh().messages)
            self.assertEqual(sliced.weight,whole.weight)

    def test_a_rewritten_file_is_weighed_from_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            path=write(Path(td)/'one.jsonl',60)
            entry=Transcript(path,'claude').refresh();big=entry.weight
            write(path,3)
            self.assertLess(entry.refresh().weight,big/5)
            self.assertEqual(entry.weight,Transcript(path,'claude').refresh().weight)


class Cache(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory();self.root=Path(self.td.name);self.parsed=[]
        self.addCleanup(self.td.cleanup)
        real=chat_history.activity_records.enrich
        def enrich(app,raw,msgs,context,record=None):  # which conversation each parsed line was of
            self.parsed.append(context.get('thread_id'));return real(app,raw,msgs,context,record)
        for p in (patch('chat_history.chats.find',lambda app,tid:{'id':tid,'app':app,'title':tid,'path':str(self.root/(tid+'.jsonl'))}),
                  patch('chat_history.chats.conv_path',lambda item:Path(item['path'])),
                  patch('chat_history.activity_records.enrich',enrich)):
            p.start();self.addCleanup(p.stop)

    def make(self,tid,turns=10,**kw):return write(self.root/(tid+'.jsonl'),turns,**kw)

    def test_the_cache_is_bounded_by_memory_not_by_file_size(self):
        h=History()
        for tid in ('a','b','c'):self.make(tid,20,padding=2<<20)
        one=Transcript(self.root/'a.jsonl','claude').refresh().weight
        with patch('chat_history.MAX_TRANSCRIPT_MEMORY',int(one*2.5)):
            for tid in ('a','b','c'):h.transcript('claude',tid)
            self.assertEqual([k[1] for k in h.entries],['b','c'])  # three would not fit, two do: by weight
            h.transcript('claude','b')                               # asked again: the newest
            self.make('d',20);h.transcript('claude','d')
            self.assertEqual([k[1] for k in h.entries],['b','d'])
        # 6 MB of files that hold little stay together under the 4 MB the old kind of cap would have allowed
        h=History()
        with patch('chat_history.MAX_TRANSCRIPT_MEMORY',4<<20):
            for tid in ('a','b','c'):h.transcript('claude',tid)
        self.assertEqual([k[1] for k in h.entries],['a','b','c'])
        self.assertGreater(sum(e.size for e in h.entries.values()),6<<20)

    def test_the_one_being_returned_is_never_pushed_out(self):
        h=History()
        self.make('a',30);self.make('b',30)
        with patch('chat_history.MAX_TRANSCRIPT_MEMORY',1000):  # smaller than either
            _,a=h.transcript('claude','a')
            _,b=h.transcript('claude','b')
            self.assertEqual(list(h.entries.values()),[b])
            self.assertEqual(len(b.messages),90)

    def test_a_cold_parse_does_not_hold_up_another_conversation(self):
        self.make('big',40);self.make('small',3)
        h=History();started=threading.Event();release=threading.Event();done={}
        real=chat_history.activity_records.enrich
        def slow(app,raw,msgs,context,record=None):
            if context.get('thread_id')=='big':
                started.set()
                if not release.wait(10):raise AssertionError('never released')
            return real(app,raw,msgs,context,record)
        def read(tid):done[tid]=h.conversation('claude',tid,60,lite=True)
        with patch('chat_history.activity_records.enrich',slow):
            big=threading.Thread(target=read,args=('big',));big.start()
            try:
                self.assertTrue(started.wait(5))
                small=threading.Thread(target=read,args=('small',));small.start();small.join(5)
                self.assertFalse(small.is_alive(),'the small conversation waited for the big one')
                self.assertTrue(big.is_alive())
                self.assertEqual(len(done['small']['messages']),9)  # 3 turns: question, tool, answer
            finally:
                release.set();big.join(10)
        self.assertEqual(done['big']['total'],120)

    def test_two_requests_for_one_new_conversation_share_one_entry(self):
        self.make('a',30)
        h=History();gate=threading.Barrier(4);got=[]
        def ask():
            gate.wait(5);got.append(h.transcript('claude','a')[1])
        threads=[threading.Thread(target=ask) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join(10)
        self.assertEqual(len(got),4);self.assertTrue(all(e is got[0] for e in got))
        self.assertEqual(list(h.entries.values()),[got[0]])
        self.assertEqual(self.parsed.count('a'),120)  # each line parsed once: 30 turns of 4 records

    def test_one_pushed_out_while_it_was_read_comes_back_as_the_newest(self):
        self.make('a',5);self.make('b',5)
        h=History();_,a=h.transcript('claude','a')
        real=Transcript.refresh
        def refresh(entry,budget=None):
            if entry.tid=='b':h.entries.clear()  # another thread made room meanwhile
            return real(entry,budget)
        with patch.object(Transcript,'refresh',refresh):_,b=h.transcript('claude','b')
        self.assertIs(h.entries[('claude','b',str(self.root/'b.jsonl'))],b)


class ReadAhead(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory();self.root=Path(self.td.name);self.parsed=[]
        self.addCleanup(self.td.cleanup)
        real=chat_history.activity_records.enrich
        def enrich(app,raw,msgs,context,record=None):
            self.parsed.append(context.get('thread_id'));return real(app,raw,msgs,context,record)
        def item(tid,updated=0,app='claude'):return {'id':tid,'app':app,'title':tid,'updated':updated,'path':str(self.root/(tid+'.jsonl'))}
        self.item=item
        self.catalog=[]
        for p in (patch('chat_history.chats.find',lambda app,tid:item(tid,app=app)),
                  patch('chat_history.chats.conv_path',lambda item:Path(item['path'])),
                  patch('chat_history.activity_records.enrich',enrich),
                  patch.object(History,'catalog',lambda h:list(self.catalog))):
            p.start();self.addCleanup(p.stop)

    def make(self,tid,turns=10,updated=0,**kw):
        write(self.root/(tid+'.jsonl'),turns,**kw);return self.item(tid,updated)

    def test_the_newest_conversations_are_read_ahead_and_opened_without_parsing(self):
        self.catalog=[self.make(f'c{i}',5,updated=100-i) for i in range(5)]+[{'id':'gone','app':'claude','updated':1,'path':str(self.root/'gone.jsonl')}]
        h=History()
        self.assertEqual(h.warm_once(count=3,pause=0),3)
        self.assertEqual(sorted(k[1] for k in h.entries),['c0','c1','c2'])
        self.assertTrue(all(not e.partial and e.offset==e.size for e in h.entries.values()))
        parsed=len(self.parsed)
        page=h.conversation('claude','c0',60,lite=True)
        self.assertEqual((len(page['messages']),len(self.parsed)),(15,parsed))  # nothing parsed again

    def test_a_request_during_the_read_ahead_gets_the_whole_page(self):
        self.catalog=[self.make('w',80,updated=9)]
        expected=History().conversation('claude','w',100,lite=True)
        h=History();pages=[]
        class Stop(threading.Event):
            def wait(self,timeout=None):  # the pause between two slices: the phone opens the conversation then
                if not pages:
                    entry=next(iter(h.entries.values()))
                    pages.append((entry.offset<entry.path.stat().st_size,h.conversation('claude','w',100,lite=True)))
                return super().wait(0)
        h.warm_stop=Stop();self.parsed.clear()
        with patch('chat_history.WARM_SLICE',30000):h.warm_once(count=1,pause=0)
        self.assertTrue(pages and pages[0][0],'the read-ahead was not caught half way')
        self.assertEqual(pages[0][1]['messages'],expected['messages'])
        self.assertEqual(pages[0][1]['total'],expected['total'])
        self.assertEqual(self.parsed.count('w'),320)  # every line once, between the read-ahead and the request

    def test_the_read_ahead_pushes_nothing_out(self):
        for tid in ('u1','u2'):self.make(tid,5)
        h=History();h.transcript('claude','u1');h.transcript('claude','u2')
        self.catalog=[self.make('w1',5,updated=9),self.make('w2',5,updated=8)]
        with patch('chat_history.MAX_TRANSCRIPTS',2):
            h.warm_once(pause=0)
            self.assertEqual([k[1] for k in h.entries],['u1','u2'])
        held=h._memory()
        with patch('chat_history.MAX_TRANSCRIPT_MEMORY',held+(self.root/'w1.jsonl').stat().st_size//8):
            h.warm_once(pause=0)  # a quarter of its file would not fit
            self.assertEqual([k[1] for k in h.entries],['u1','u2'])

    def test_what_is_read_ahead_goes_first_and_what_was_opened_keeps_its_place(self):
        for tid in ('u1','u2','u3'):self.make(tid,5)
        h=History();h.transcript('claude','u1');h.transcript('claude','u2')
        self.catalog=[self.make('w1',5,updated=9),self.item('u1',8)]
        with patch('chat_history.MAX_TRANSCRIPTS',3):
            h.warm_once(pause=0)
            self.assertEqual([k[1] for k in h.entries],['w1','u1','u2'])
            h.transcript('claude','u3')
            self.assertEqual([k[1] for k in h.entries],['u1','u2','u3'])

    def test_one_pushed_out_half_way_is_not_read_on(self):
        self.catalog=[self.make('w',80,updated=9)]
        h=History()
        class Stop(threading.Event):
            def wait(self,timeout=None):h.entries.clear();return super().wait(0)
        h.warm_stop=Stop();self.parsed.clear()
        with patch('chat_history.WARM_SLICE',30000):h.warm_once(count=1,pause=0)
        self.assertLess(self.parsed.count('w'),100)
        self.assertEqual(len(h.entries),0)

    def test_errors_are_counted_and_the_others_still_read(self):
        self.catalog=[self.make('bad',3,updated=9),self.make('ok',3,updated=8)]
        h=History();seen=[];h.log=seen.append
        real=Transcript.refresh
        def refresh(entry,budget=None):
            if entry.tid=='bad':raise OSError('the file went away')
            return real(entry,budget)
        with patch.object(Transcript,'refresh',refresh):h.warm_once(pause=0)
        self.assertEqual(h.warm_errors,1);self.assertIn('OSError',seen[0])
        self.assertFalse(h.entries[('claude','ok',str(self.root/'ok.jsonl'))].partial)

    def test_only_the_installed_app_starts_the_thread_and_it_stops(self):
        self.assertIsNone(History().warming)  # tests and source runs: no thread
        ran=threading.Event()
        def once(h,count=8,pause=0):ran.set();return 0
        with patch('chat_history.WARM_AFTER',0),patch.object(History,'warm_once',once):
            with patch.object(sys,'frozen',True,create=True):h=History()
            try:
                self.assertTrue(ran.wait(5))
            finally:
                h.stop_warming(5)
        self.assertFalse(h.warming.is_alive())


if __name__=='__main__':unittest.main()
