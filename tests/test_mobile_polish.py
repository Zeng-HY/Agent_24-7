"""Phone interaction fixtures: no production accounts, chats or clipboard writes."""
import json,os,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from relay_pages import scoped_page
import motion_check as fixture
A='a'*32;B='b'*32

class MobilePolish(unittest.TestCase):
    def test_resume_membership_login_manual_selection_and_pointer_focus(self):
        with sync_playwright() as pw:
            browser=pw.webkit.launch()
            cases=[('single','',None,[A],True,A),('last','',B,[A,B],True,B),
                   ('multi','',None,[A,B],True,None),('removed','',B,[A],True,None),('manual','?choose=1',A,[A],True,None),
                   ('offline','',A,[A],False,None),('binding','?authorize='+'c'*32,A,[A],True,None)]
            for name,query,last,ids,online,expected in cases:
                with self.subTest(name=name):
                    ctx=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
                    if last:ctx.add_init_script('localStorage.setItem("ar-last-device",'+json.dumps(last)+')')
                    selections=[];signed=[True]
                    def route(r):
                        path=urlsplit(r.request.url).path
                        assets={'/account':('relay_account.html','text/html'),'/account/ui.css':('relay_account.css','text/css'),'/account/ui.js':('relay_account.js','application/javascript')}
                        if path in assets:
                            file,mime=assets[path];return r.fulfill(body=(ROOT/file).read_bytes(),content_type=mime)
                        if path.startswith('/d/'):return r.fulfill(body='Connected fixture',content_type='text/html')
                        data={}
                        if path=='/account/config':data={'email_enabled':True}
                        if path=='/account/state':data={'devices':[{'id':v,'label':'Fixture '+v[0],'online':online} for v in ids]}
                        if path=='/device-auth/details':data={'label':'Binding fixture'}
                        if path=='/account/select':
                            ident=json.loads(r.request.post_data)['id'];self.assertIn(ident,ids);selections.append(ident);data={'url':'/d/'+ident+'/'}
                        r.fulfill(body=json.dumps(data),content_type='application/json')
                    ctx.route('https://relay.test/**',route);page=ctx.new_page();page.goto('https://relay.test/account'+query)
                    if expected:
                        page.wait_for_url('**/d/'+expected+'/');self.assertEqual(selections,[expected])
                    else:
                        page.locator('#signed').wait_for(state='visible');self.assertEqual(page.title(),'Teleply');self.assertEqual(selections,[])
                    if name=='manual':
                        page.get_by_role('button',name='管理电脑',exact=True).tap()
                        menu=page.locator('#deviceMenu');menu.wait_for(state='visible')
                        self.assertEqual(menu.locator('button').first.evaluate('e=>getComputedStyle(e).outlineStyle'),'none')
                        page.keyboard.press('Tab')
                        self.assertNotEqual(page.evaluate('getComputedStyle(document.activeElement).outlineStyle'),'none')
                        page.keyboard.press('Escape');page.get_by_role('button',name='连接',exact=True).tap()
                        page.wait_for_url('**/d/'+A+'/')
                    if name=='removed':self.assertEqual(page.evaluate('localStorage.getItem("ar-last-device")'),None)
                    ctx.close()
            # Expired sessions stay on the login form; after login the same selection intent resumes.
            page=browser.new_page();signed=[False];selected=[]
            def login_route(r):
                path=urlsplit(r.request.url).path
                assets={'/account':('relay_account.html','text/html'),'/account/ui.css':('relay_account.css','text/css'),'/account/ui.js':('relay_account.js','application/javascript')}
                if path in assets:
                    file,mime=assets[path];return r.fulfill(body=(ROOT/file).read_bytes(),content_type=mime)
                if path=='/account/login':signed[0]=True
                if path=='/account/state' and not signed[0]:return r.fulfill(status=401,body='{}',content_type='application/json')
                data={'email_enabled':True} if path=='/account/config' else {'devices':[{'id':A,'label':'PC','online':True}]} if path=='/account/state' else {'url':'/d/'+A+'/'}
                if path=='/account/select':selected.append(json.loads(r.request.post_data)['id'])
                r.fulfill(body=json.dumps(data),content_type='application/json')
            page.route('https://relay.test/**',login_route);page.goto('https://relay.test/account')
            page.locator('#auth').wait_for(state='visible');self.assertEqual(selected,[])
            page.locator('#name').fill('fixture');page.locator('#password').fill('fixture-password');page.locator('#submit').click()
            page.wait_for_url('**/d/'+A+'/');self.assertEqual(selected,[A]);browser.close()

    def test_snippet_copy_flat_icons_and_connection_focus_in_both_engines(self):
        command='printf "%s" "a & <b>"\n  echo 中文 😀'
        prompt='请保留缩进：\n\n  第一段\n  第二段'
        text='命令\n```bash\n'+command+'\n```\n\n提示词\n~~~prompt\n'+prompt+'\n~~~\n\n行内 `git status --short`\n\n````text\n内嵌围栏\n```python\nprint(1)\n```\n````'
        with sync_playwright() as pw:
            for engine in ('webkit','chromium'):
                with self.subTest(engine=engine):
                    browser=getattr(pw,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
                    ctx=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,reduced_motion='reduce')
                    ctx.add_init_script("window.copied=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied.push(text)}}});")
                    def route(r):
                        u=urlsplit(r.request.url);path=u.path.removeprefix('/d/'+A)
                        if path=='/':return r.fulfill(body=scoped_page((ROOT/'remote.html').read_bytes(),A),content_type='text/html')
                        if path=='/api/chat/projects':
                            tree=fixture.fake_tree();tree['apps'].append({'app':'deepseek','name':'DeepSeek','count':0,'projects':[]});return r.fulfill(body=json.dumps(tree),content_type='application/json')
                        return fixture.handle(r,SimpleNamespace(url='https://relay.test'+path+('?' +u.query if u.query else '')))
                    ctx.route('https://relay.test/**',route);page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('https://relay.test/d/'+A+'/');page.wait_for_function('!!window.readingUI && !!window.sidebarUI')
                    self.assertEqual(page.evaluate('localStorage.getItem("ar-last-device")'),A);self.assertEqual(page.title(),'Teleply');self.assertEqual(page.locator('meta[name="apple-mobile-web-app-title"]').get_attribute('content'),'Teleply')
                    page.get_by_role('button',name='打开导航',exact=True).tap();page.locator('.mark.deepseek').wait_for(state='visible')
                    self.assertEqual(page.locator('.nav-tree linearGradient,.nav-tree rect').count(),0)
                    self.assertEqual(page.locator('.fd').first.evaluate('e=>getComputedStyle(e).filter'),'none')
                    shots=os.environ.get('AR_POLISH_SHOTS')
                    if shots:page.screenshot(path=str(Path(shots)/(engine+'-sidebar-flat.png')))
                    trigger=page.get_by_role('button',name='连接设置',exact=True);trigger.tap()
                    page.get_by_role('button',name='完成',exact=True).tap()
                    self.assertEqual(trigger.evaluate('e=>getComputedStyle(e).outlineStyle'),'none')
                    page.evaluate('dismissOverlays()')
                    page.evaluate("""text=>{cur={app:'codex',id:'fixture'};document.getElementById('convView').style.display='flex';document.getElementById('cvTitle').textContent='分块复制示例';const bubble=document.createElement('div');bubble.className='bub assistant';bubble.innerHTML=md(text,true);document.getElementById('cvMsgs').replaceChildren(bubble);}""",text)
                    self.assertEqual(page.locator('.code-copy').count(),3)
                    page.get_by_role('button',name='复制命令',exact=True).tap();self.assertEqual(page.evaluate('copied.at(-1)'),command)
                    page.get_by_role('button',name='复制文本',exact=True).first.tap();self.assertEqual(page.evaluate('copied.at(-1)'),prompt)
                    page.get_by_role('button',name='复制行内内容',exact=True).tap();self.assertEqual(page.evaluate('copied.at(-1)'),'git status --short')
                    self.assertTrue(page.locator('.msg-menu').is_hidden())
                    self.assertEqual(page.locator('.code-wrap').last.locator('pre').inner_text(),'内嵌围栏\n```python\nprint(1)\n```')
                    if shots:
                        page.locator('#cvMsgs').evaluate('e=>e.scrollTop=0');page.screenshot(path=str(Path(shots)/(engine+'-snippet-copy.png')))
                    # Incomplete streamed blocks remain copyable, without HTML interpretation.
                    page.evaluate('text=>document.querySelector(".bub").innerHTML=md(text,true)','```prompt\n<img src=x>\npartial 😀')
                    page.get_by_role('button',name='复制当前内容',exact=True).tap();self.assertEqual(page.evaluate('copied.at(-1)'),'<img src=x>\npartial 😀')
                    self.assertEqual(page.locator('.bub img').count(),0);self.assertEqual(errors,[]);browser.close()

if __name__=='__main__':unittest.main()
