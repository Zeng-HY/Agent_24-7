"""The list's read every 10 s on the web: a list of one state follows its first page, the whole list keeps later pages (WebKit)."""
import json,re,sys,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parent))
from motion_check import handle,ORIGIN
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chat_history import History,HistoryError
from playwright.sync_api import sync_playwright


def row(name,status='running',age=0):
    return {'app':'codex','id':name,'title':name,'status':status,'updated':1761000000000-age,'created':1761000000000-age,'folder':'D:/demo','preview':''}


class ListRead(unittest.TestCase):
    def setUp(self):
        self.rows=[];self.asked=[];self.errors=[]
        pw=sync_playwright().start();self.addCleanup(pw.stop)
        browser=pw.webkit.launch();self.addCleanup(browser.close)
        self.page=browser.new_page();self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.route(ORIGIN+'/**',self.route)

    def route(self,r,q):
        if urlsplit(q.url).path!='/api/chats':return handle(r,q)
        # as chat_history.conversations answers: the rows of the asked state, a page at a time
        ask=parse_qs(urlsplit(q.url).query);status=ask.get('status',['all'])[0];size=int(ask['limit'][0]);start=int(ask.get('cursor',['0'])[0])
        self.asked.append((status,ask.get('cursor',[None])[0]))
        rows=[v for v in self.rows if status=='all' or v['status']==status];more=start+size<len(rows)
        r.fulfill(content_type='application/json',body=json.dumps({'items':rows[start:start+size],'next_cursor':str(start+size) if more else None,'has_more':more,'total':len(rows)}))

    def settled(self):self.page.wait_for_function("!document.querySelector('.list-more').disabled")
    def start(self):self.page.goto(ORIGIN,wait_until='commit');self.page.wait_for_function('!!window.readingUI&&!!window.interactionUI');self.page.wait_for_selector('#convList .conv');self.settled()
    def pick(self,label):  # ⋯ → 状态 → label
        self.page.get_by_role('button',name='列表显示选项').click()
        self.page.locator('#displayMenu button',has_text='状态').click()
        self.page.locator('#displayMenu').get_by_role('button',name=label,exact=True).click()
        self.page.evaluate('dismissOverlays()');self.settled()
    def more(self):self.page.get_by_role('button',name='加载更多对话',exact=True).click();self.settled()
    def read(self):self.settled();self.page.evaluate('readingUI.loadList()');self.settled()  # what the 10 s timer calls
    def shown(self):return self.page.evaluate("[...document.querySelectorAll('#convList .conv')].map(n=>n.dataset.key.split(':')[1])")

    def test_a_row_that_ended_leaves_a_list_of_one_state(self):
        self.rows=[row('a'),row('b',age=1),row('old','idle',2)]
        self.start();self.pick('运行中')
        self.assertEqual(self.shown(),['a','b']);self.assertEqual(self.asked[-1],('running',None))
        self.rows[1]['status']='idle'
        self.read()
        self.assertEqual(self.shown(),['a'])
        self.assertTrue(self.page.locator('.list-more').is_hidden())
        # back on the whole list it is there, ended
        self.pick('全部')
        self.assertEqual(self.shown(),['a','b','old'])
        self.assertEqual(self.page.locator('#convList .conv',has_text='b').first.locator('.st').inner_text(),'空闲')
        self.assertEqual(self.errors,[])

    def test_a_list_of_one_state_follows_its_first_page(self):
        self.rows=[row(f'r{i}','idle',i) for i in range(50)]
        self.start();self.pick('已结束')
        self.assertEqual(self.asked[-1],('idle',None));self.assertEqual(len(self.shown()),20)
        self.more();self.assertEqual(self.asked[-1],('idle','20'));self.assertEqual(len(self.shown()),40)
        # the rows and where the next page starts both follow the first page
        self.read();self.assertEqual(self.shown(),[f'r{i}' for i in range(20)])
        self.more();self.assertEqual(self.asked[-1],('idle','20'));self.assertEqual(len(self.shown()),40)
        self.assertEqual(self.errors,[])

    def test_the_whole_list_keeps_the_pages_read_past_the_first(self):
        self.rows=[row(f'r{i}',age=i) for i in range(50)]
        self.start();self.assertEqual(len(self.shown()),20)
        self.more();self.assertEqual(len(self.shown()),40)
        self.rows.insert(0,row('new',age=-1))
        self.read()
        self.assertEqual(self.shown(),['new']+[f'r{i}' for i in range(40)])
        self.more();self.assertEqual(self.asked[-1],('all','40'))
        self.assertEqual(self.errors,[])


class OfferedStates(unittest.TestCase):
    def test_every_state_a_client_offers_is_one_the_computer_takes(self):
        def source(path):return (ROOT/path).read_text(encoding='utf-8')
        offered={
            'android':re.findall(r'"(\w+)" to "',re.search(r'ListStates = listOf\((.*)\)',source('apps/android/app/src/main/java/com/pocketagentdesk/teleply/ListUi.kt')).group(1)),
            'web':re.findall(r"\['(\w+)','",re.search(r"status:\['状态',\[(.*?)\]\],source",source('static/interaction-ui.js')).group(1)),
            'ios':re.findall(r'\.tag\("(\w+)"\)',re.search(r'Picker\("状态".*?\n\s*\}\n',source('apps/ios/Teleply/List/ChatListView.swift'),re.S).group(0)),
        }
        h=History()
        with patch('chats.codex_threads',return_value=[]),patch('chats.claude_sessions',return_value=[]),patch('deepseek_control.listing',return_value={'top':[],'ungrouped':[]}):
            for client,values in offered.items():
                with self.subTest(client=client):
                    self.assertEqual(values[0],'all');self.assertGreater(len(values),1)
                    for value in values:h.conversations(status=value)
            with self.assertRaises(HistoryError):h.conversations(status='done')


if __name__=='__main__':unittest.main()
