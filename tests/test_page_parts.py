"""Real page/module fault injection in Chromium and WebKit, without user data."""
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parent))
from motion_check import handle,ORIGIN
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_pages import scoped_page


class Parts(unittest.TestCase):
    def run_case(self,engine,case):
        with sync_playwright() as pw:
            browser=getattr(pw,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
            page=browser.new_page(viewport={'width':390,'height':844});requests=[];errors=[];count=0
            page.on('pageerror',lambda e:errors.append(str(e)))
            def route(r,q):
                nonlocal count
                path=urlsplit(q.url).path;requests.append(path)
                if path=='/claude-ui.js':
                    count+=1
                    if case=='recover' and count==1:return r.abort()
                    if case=='download':return r.abort()
                    if case=='execution':return r.fulfill(content_type='application/javascript',body="window.testExecuted=(window.testExecuted||0)+1;throw new Error('fixture execution failure')")
                return handle(r,q)
            page.route(ORIGIN+'/**',route);page.goto(ORIGIN)
            if case=='clean':
                page.wait_for_function('window.claudeUI && window.referencesUI')
                self.assertFalse(page.locator('#partsNotice').is_visible());self.assertEqual(errors,[])
            elif case=='recover':
                page.wait_for_function('window.claudeUI && window.referencesUI')
                self.assertEqual(count,2);self.assertEqual(page.locator('#claudeComposerTools').count(),1)
                self.assertEqual(page.locator('#referencePicker').count(),1);self.assertFalse(page.locator('#partsNotice').is_visible())
            else:
                page.locator('#partsNotice').wait_for(state='visible')
                if case=='download':page.wait_for_function("pageParts.snapshot().find(r=>r.key==='claudeUI').attempts===1 && pageParts.snapshot().find(r=>r.key==='claudeUI').status==='download'")
                else:self.assertEqual(page.evaluate('window.testExecuted'),1)
                header=page.locator('body>header').bounding_box();notice=page.locator('#partsNotice').bounding_box()
                self.assertGreaterEqual(notice['y'],header['y']+header['height'])
                self.assertTrue(page.get_by_role('button',name='打开导航',exact=True).is_visible())
                page.get_by_role('button',name='关闭加载提示',exact=True).click()
                self.assertFalse(page.locator('#partsNotice').is_visible())
                page.evaluate('pageParts.retry()');page.wait_for_timeout(1200)
                self.assertFalse(page.locator('#partsNotice').is_visible())
                self.assertEqual(count,2 if case=='download' else 1)
            self.assertEqual(requests.count('/'),1,'No automatic document reload')
            browser.close()

    def test_chromium(self):
        for case in ['clean','recover','download','execution']:
            with self.subTest(case=case):self.run_case('chromium',case)

    def test_webkit(self):
        for case in ['clean','recover','download','execution']:
            with self.subTest(case=case):self.run_case('webkit',case)

    def test_retry_remains_within_selected_device_path(self):
        with sync_playwright() as pw:
            b=pw.webkit.launch();page=b.new_page();paths=[];device='a'*32
            source=(Path(__file__).resolve().parents[1]/'remote.html').read_bytes()
            def route(r,q):
                path=urlsplit(q.url).path;paths.append(path)
                if path=='/d/'+device+'/':return r.fulfill(content_type='text/html',body=scoped_page(source,device))
                if path.endswith('/claude-ui.js'):return r.abort()
                # Only fake APIs/assets through the already-bound device prefix.
                if path.startswith('/d/'+device+'/'):
                    class Request:
                        url=ORIGIN+q.url.split('/d/'+device,1)[1]
                        post_data=q.post_data
                    return handle(r,Request())
                return r.fulfill(status=404,body='unscoped')
            page.route(ORIGIN+'/**',route);page.goto(ORIGIN+'/d/'+device+'/')
            page.wait_for_function("pageParts.snapshot().find(r=>r.key==='claudeUI').attempts===1")
            self.assertTrue(all(p.startswith('/d/'+device+'/') for p in paths if p.endswith('.js')))
            b.close()

    def test_timeout_does_not_execute_second_copy_or_lose_draft(self):
        with sync_playwright() as pw:
            b=pw.webkit.launch();page=b.new_page();requests=[];held=[]
            page.clock.install()
            def route(r,q):
                if urlsplit(q.url).path=='/claude-ui.js':requests.append(q.url);held.append(r);return
                return handle(r,q)
            page.route(ORIGIN+'/**',route);page.goto(ORIGIN,wait_until='commit')
            page.wait_for_selector('#cvText',state='attached')
            page.evaluate("document.getElementById('cvText').value='unsent fixture'")
            page.clock.run_for(1000);page.clock.fast_forward(17000)
            page.wait_for_function("pageParts.snapshot().some(r=>r.key==='claudeUI'&&r.status==='timeout')")
            page.evaluate('pageParts.retry()')
            self.assertEqual(len(requests),1)
            self.assertEqual(page.locator('#cvText').input_value(),'unsent fixture')
            held[0].fulfill(content_type='application/javascript',body='window.claudeUI={};')
            page.wait_for_load_state('load')
            page.unroute_all(behavior='ignoreErrors')
            b.close()
