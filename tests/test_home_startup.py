"""Homepage startup uses one small request and preserves pagination/recovery in WebKit."""
import json,sys,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parent))
from motion_check import handle,ORIGIN,fake_chats
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chat_history import History
from playwright.sync_api import sync_playwright


class HomeStartup(unittest.TestCase):
    def test_webkit_first_page_shared_before_and_after_module_load(self):
        for slow in ('api','module','failure'):
            with self.subTest(slow=slow),sync_playwright() as pw:
                browser=pw.webkit.launch();page=browser.new_page();calls=[];held=[];errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                rows=fake_chats(40)
                def answer(r):
                    q=parse_qs(urlsplit(r.request.url).query);offset=20 if q.get('cursor') else 0
                    r.fulfill(content_type='application/json',body=json.dumps({'items':rows[offset:offset+20],
                        'next_cursor':'next' if not offset else None,'has_more':not offset,'total':40}))
                def route(r,q):
                    path=urlsplit(q.url).path
                    if path=='/reading-ui.js' and slow=='module':held.append(r);return
                    if path=='/api/chats':
                        calls.append(q.url)
                        if len(calls)==1 and slow in ('api','failure'):held.append(r);return
                        return answer(r)
                    return handle(r,q)
                page.route(ORIGIN+'/**',route);page.goto(ORIGIN,wait_until='commit')
                if slow=='module':
                    page.wait_for_selector('#convList .conv')
                    page.wait_for_function('!convLoading')
                    handle(held[0],held[0].request)
                else:
                    page.wait_for_function('!!window.readingUI')
                    if slow=='failure':held[0].fulfill(status=503,content_type='application/json',body='{"error":"fixture offline"}')
                    else:answer(held[0])
                if slow=='failure':
                    page.wait_for_function("document.getElementById('convHint').textContent.includes('fixture offline')")
                    page.evaluate('readingUI.loadList()')
                page.wait_for_function("document.querySelectorAll('#convList .conv').length===20")
                self.assertEqual(len(calls),2 if slow=='failure' else 1)
                self.assertTrue(all(parse_qs(urlsplit(u).query)['limit']==['20'] for u in calls))
                page.get_by_role('button',name='加载更多对话',exact=True).click()
                page.wait_for_function("document.querySelectorAll('#convList .conv').length===40")
                self.assertEqual(parse_qs(urlsplit(calls[-1]).query)['cursor'],['next'])
                self.assertEqual(errors,[])
                browser.close()

    def test_cold_catalog_scanned_once_for_simultaneous_readers(self):
        h=History();started=threading.Event();release=threading.Event()
        def scan(*args):
            started.set();self.assertTrue(release.wait(3));return []
        with patch('chats.codex_threads',side_effect=scan) as codex,patch('chats.claude_sessions',return_value=[]),patch('deepseek_control.listing',return_value={'top':[],'ungrouped':[]}):
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs=[pool.submit(h.catalog) for _ in range(4)]
                self.assertTrue(started.wait(3));release.set()
                for job in jobs:self.assertEqual(job.result(timeout=3),[])
            self.assertEqual(codex.call_count,1)
            h.invalidate();h.catalog();self.assertEqual(codex.call_count,2)

    def test_invalidation_during_scan_is_not_lost(self):
        h=History()
        def scan(*args):h.invalidate();return []
        with patch('chats.codex_threads',side_effect=scan),patch('chats.claude_sessions',return_value=[]),patch('deepseek_control.listing',return_value={'top':[],'ungrouped':[]}):
            h.catalog();self.assertEqual(h.catalog_cache[0],0)


if __name__=='__main__':unittest.main()
