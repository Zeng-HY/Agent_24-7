"""The list's read every 10 s on the web, against the computer's own paging: a list of one state drops the rows that left it and keeps later pages, the whole list keeps later pages (WebKit)."""
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


def row(name,status='running',age=0,created=None):
    at=1761000000000-age
    return {'app':'codex','id':name,'title':name,'status':status,'updated':at,'created':at if created is None else created,'folder':'D:/demo','cwd':'D:/demo'}
def rows(count,status='running'):return [row(f'r{i}',status,i) for i in range(count)]
def names(*ranges):return [f'r{i}' for r in ranges for i in r]


class ListRead(unittest.TestCase):
    def setUp(self):
        self.rows=[];self.asked=[];self.errors=[]
        pw=sync_playwright().start();self.addCleanup(pw.stop)
        browser=pw.webkit.launch();self.addCleanup(browser.close)
        self.page=browser.new_page();self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.route(ORIGIN+'/**',self.route)

    def route(self,r,q):
        if urlsplit(q.url).path!='/api/chats':return handle(r,q)
        ask={k:v[0] for k,v in parse_qs(urlsplit(q.url).query).items()}
        self.asked.append(ask.get('status','all'))
        with patch.object(History,'_load',lambda _:(list(self.rows),[])),patch('chats.summary',lambda item:{'status':item['status'],'preview':''}):
            page=History().conversations(ask.get('app','all'),int(ask['limit']),ask.get('cursor',''),ask.get('query',''),ask.get('sort','updated'),ask.get('status','all'))
        r.fulfill(content_type='application/json',body=json.dumps(page))

    def settled(self):self.page.wait_for_function("!document.querySelector('.list-more').disabled")
    def start(self):self.page.goto(ORIGIN,wait_until='commit');self.page.wait_for_function('!!window.readingUI&&!!window.interactionUI');self.page.wait_for_selector('#convList .conv');self.settled()
    def pick(self,menu,label):  # ⋯ → 状态 → 运行中
        self.page.get_by_role('button',name='列表显示选项').click()
        self.page.locator('#displayMenu button',has_text=menu).click()
        self.page.locator('#displayMenu').get_by_role('button',name=label,exact=True).click()
        self.page.evaluate('dismissOverlays()');self.settled()
    def more(self):self.page.get_by_role('button',name='加载更多对话',exact=True).click();self.settled()
    def read(self):self.settled();self.page.evaluate('readingUI.loadList()');self.settled()  # what the 10 s timer calls
    def shown(self):return self.page.evaluate("[...document.querySelectorAll('#convList .conv')].map(n=>n.dataset.key.split(':')[1])")
    def tearDown(self):self.assertEqual(self.errors,[])

    def test_a_row_that_ended_leaves_a_list_of_one_state(self):
        self.rows=[row('a'),row('b',age=1),row('old','idle',2)]
        self.start();self.pick('状态','运行中')
        self.assertEqual(self.shown(),['a','b']);self.assertEqual(self.asked[-1],'running')
        self.rows[1]['status']='idle'
        self.read()
        self.assertEqual(self.shown(),['a'])
        self.assertTrue(self.page.locator('.list-more').is_hidden())
        # back on the whole list it is there, ended
        self.pick('状态','全部')
        self.assertEqual(self.shown(),['a','b','old'])
        self.assertEqual(self.page.locator('#convList .conv',has_text='b').first.locator('.st').inner_text(),'空闲')

    def test_the_pages_read_past_the_first_stay_in_a_list_of_one_state(self):
        self.rows=rows(70,'idle')
        self.start();self.pick('状态','已结束')
        self.assertEqual(self.asked[-1],'idle');self.assertEqual(self.shown(),names(range(20)))
        self.more();self.assertEqual(self.shown(),names(range(40)))
        self.read();self.assertEqual(self.shown(),names(range(40)))
        self.more();self.assertEqual(self.shown(),names(range(60)))

    def test_a_row_that_left_its_state_goes_even_with_later_pages_read(self):
        self.rows=rows(50)
        self.start();self.pick('状态','运行中')
        self.more();self.assertEqual(self.shown(),names(range(40)))
        self.rows[5]['status']='idle'
        self.read();self.assertEqual(self.shown(),names(range(5),range(6,40)))
        self.more();self.assertEqual(self.shown(),names(range(5),range(6,50)))

    def test_a_row_pushed_off_the_first_page_stays(self):
        self.rows=rows(30)
        self.start();self.pick('状态','运行中')
        self.assertEqual(self.shown(),names(range(20)))
        self.rows.insert(0,row('new',age=-1))
        self.read();self.assertEqual(self.shown(),['new']+names(range(20)))
        self.more();self.assertEqual(self.shown(),['new']+names(range(30)))

    def test_rows_past_the_first_page_go_once_the_list_fits_on_it(self):
        self.rows=rows(25)
        self.start();self.pick('状态','运行中')
        self.more();self.assertEqual(self.shown(),names(range(25)))
        for v in self.rows[19:]:v['status']='idle'
        self.read();self.assertEqual(self.shown(),names(range(19)))
        self.assertTrue(self.page.locator('.list-more').is_hidden())

    def test_sorted_by_creation_that_order_decides_what_stays(self):
        # the rows created last were active longest ago: by 最近活动 every one past the first page would come before it
        self.rows=[row(f'r{i}','idle',age=50-i,created=1761000000000-i) for i in range(50)]
        self.start();self.pick('排序','创建时间');self.pick('状态','已结束')
        self.assertEqual(self.shown(),names(range(20)))
        self.more();self.assertEqual(self.shown(),names(range(40)))
        self.read();self.assertEqual(self.shown(),names(range(40)))

    def test_the_whole_list_keeps_the_pages_read_past_the_first(self):
        self.rows=rows(70)
        self.start();self.assertEqual(self.shown(),names(range(20)))
        self.more();self.assertEqual(self.shown(),names(range(40)))
        self.rows.insert(0,row('new',age=-1))
        self.read();self.assertEqual(self.shown(),['new']+names(range(40)))
        self.more();self.assertEqual(self.shown(),['new']+names(range(60)))


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
