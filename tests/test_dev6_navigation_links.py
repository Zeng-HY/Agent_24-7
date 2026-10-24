"""Disposable navigation and phone link regressions; no production conversations."""
import json,os,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chat_history import History,HistoryError
from relay_controller import DesktopController


class Navigation(unittest.TestCase):
    def test_status_update_account_back_one_step(self):
        c=DesktopController.__new__(DesktopController)
        c.stop=threading.Event();c.action_lock=threading.Lock();c.nav_history=[]
        c.binding={'device':'fixture','origin':'https://relay.test'}
        c.settings_open=False;c.update_title='';c.update_notes='';c.shell=Mock(remote_showing=False)
        c.shell.load_account.side_effect=lambda url:setattr(c.shell,'remote_showing',True)
        c.shell.local_view.side_effect=lambda **kw:setattr(c.shell,'remote_showing',False)
        c.shell.show_account.side_effect=lambda:setattr(c.shell,'remote_showing',True)
        c.check_update=lambda:(setattr(c,'settings_open',True),setattr(c,'update_title','检查更新'),setattr(c,'update_notes','fixture details'),c.shell.local_view(returnable=True))
        c.dispatch('check-update');self.assertTrue(c.settings_open)
        c.dispatch('account');self.assertTrue(c.shell.remote_showing);self.assertFalse(c.settings_open)
        c.dispatch('back');self.assertFalse(c.shell.remote_showing);self.assertTrue(c.settings_open)
        self.assertEqual(c.update_title,'检查更新')
        c.dispatch('back');self.assertFalse(c.settings_open);self.assertEqual(c.nav_history,[])

    def test_file_registry_allows_explicit_cross_project_current_file_only(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'allowed';root.mkdir();good=root/'some file.md';good.write_text('fixture')
            outside=Path(td)/'private.md';outside.write_text('private')
            h=History(secret='test');entry=SimpleNamespace(lock=threading.RLock(),messages=[{'id':'m','role':'assistant','text':f'[good](<{good}>) [bad]({outside})'}])
            h.transcript=lambda *a:({'cwd':str(root)},entry)
            rows=h.list_files('codex','one')['items'];self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['path'],str(good));fid=rows[0]['id']
            with self.assertRaises(HistoryError):h.file('codex','two',fid)
            good.write_text('changed content')
            self.assertTrue(h.file('codex','one',fid)['updated'])


class PhoneLinks(unittest.TestCase):
    def test_account_valid_expired_and_login_returns_to_devices(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.webkit.launch();page=browser.new_page();signed=[True]
            def route(r):
                path=urlsplit(r.request.url).path
                assets={'/account':('relay_account.html','text/html'),'/account/ui.css':('relay_account.css','text/css'),'/account/ui.js':('relay_account.js','application/javascript')}
                if path in assets:
                    file,mime=assets[path];return r.fulfill(body=(ROOT/file).read_bytes(),content_type=mime)
                if path=='/account/login':signed[0]=True
                if path=='/account/state' and not signed[0]:return r.fulfill(status=401,content_type='application/json',body='{"error":"expired"}')
                data={'email_enabled':True} if path=='/account/config' else {'devices':[{'id':'a'*32,'label':'Fixture PC','online':True}]} if path=='/account/state' else {}
                r.fulfill(content_type='application/json',body=json.dumps(data))
            page.route('https://relay.test/**',route);page.goto('https://relay.test/account?choose=1')
            page.locator('#signed').wait_for(state='visible');signed[0]=False;page.reload()
            page.locator('#auth').wait_for(state='visible');page.locator('#name').fill('fixture');page.locator('#password').fill('fixture-password')
            page.locator('#submit').click();page.locator('#signed').wait_for(state='visible')
            self.assertEqual(page.url,'https://relay.test/account?choose=1');self.assertEqual(page.locator('.device-name').inner_text(),'Fixture PC')
            browser.close()

    def test_webkit_and_android_touch_links_and_device_scope(self):
        from playwright.sync_api import sync_playwright
        import motion_check as fixture
        from relay_pages import scoped_page
        device='a'*32;base='/d/'+device
        text='[HTTPS](https://example.test/news?q=1&lang=en)\n\n[本地文件](<D:/demo/some file.md>)\n\n[禁止](javascript:alert)\n\n`[代码](https://example.test/code)`\n\n普通消息文字'
        with sync_playwright() as pw:
            for engine in ('webkit','chromium'):
                with self.subTest(engine=engine):
                    browser=getattr(pw,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
                    ctx=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,reduced_motion='reduce')
                    seen=[]
                    def route(r):
                        path=urlsplit(r.request.url).path;seen.append(path)
                        def out(data):r.fulfill(content_type='application/json',body=json.dumps(data))
                        if path==base+'/':return r.fulfill(content_type='text/html',body=scoped_page((ROOT/'remote.html').read_bytes(),device))
                        local=path.removeprefix(base)
                        if local=='/api/chat/files':return out({'items':[{'id':'f'*32,'name':'some file.md','path':'D:\\demo\\some file.md','kind':'text','index':0,'message_id':'m','state':'current'}]})
                        if local=='/api/file/meta':return out({'kind':'text'})
                        if local=='/api/file':return r.fulfill(content_type='text/plain',body='AUTHORIZED FIXTURE CONTENT')
                        if local.startswith('/api/'):return out({})
                        file=ROOT/'static'/local.lstrip('/')
                        if file.is_file():return r.fulfill(body=file.read_bytes(),content_type='application/javascript' if file.suffix=='.js' else 'image/png')
                        r.fulfill(body='external fixture',content_type='text/plain')
                    ctx.route('**/*',route);page=ctx.new_page();page.goto('https://relay.test'+base+'/')
                    page.wait_for_function('!!window.readingUI')
                    page.evaluate('''text=>{cur={app:'codex',id:'fixture'};loaded=[{id:'m',role:'assistant',text}];document.getElementById('convView').style.display='block';document.getElementById('cvMsgs').innerHTML='<div class="bub" data-key="m">'+md(text)+'</div>';}''',text)
                    self.assertEqual(page.locator('#cvMsgs a').count(),2)
                    with page.expect_popup() as popup:page.get_by_role('link',name='HTTPS',exact=True).tap()
                    popup.value.wait_for_load_state();self.assertEqual(popup.value.url,'https://example.test/news?q=1&lang=en');popup.value.close()
                    self.assertTrue(page.locator('.msg-menu').is_hidden())
                    page.get_by_role('link',name='本地文件',exact=True).tap()
                    page.frame_locator('.artifact-frame').get_by_text('AUTHORIZED FIXTURE CONTENT',exact=True).wait_for(state='visible')
                    self.assertTrue(page.locator('.msg-menu').is_hidden())
                    for endpoint in ('/api/chat/files','/api/file'):
                        self.assertIn(base+endpoint,seen);self.assertNotIn(endpoint,seen)
                    shots=os.environ.get('AR_LINK_SHOTS')
                    if shots:page.screenshot(path=str(Path(shots)/(engine+'-file-link.png')))
                    page.evaluate('artifactPreview.close();dismissOverlays()')
                    page.locator('#cvMsgs .bub').tap(position={'x':180,'y':170})
                    page.locator('.msg-menu').wait_for(state='visible')
                    browser.close()


if __name__=='__main__':unittest.main()
