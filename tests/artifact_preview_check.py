"""Isolated browser fixtures; never contacts the running Teleply service."""
from pathlib import Path
import base64, hashlib, json, mimetypes, struct
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/artifact-preview';OUT.mkdir(parents=True,exist_ok=True)
ORIGIN='http://artifact.test'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB1sAAAAASUVORK5CYII=')
HTML='<!doctype html>\r\n<html><head><style>body{color:#123456;padding:20px}h1{font-size:28px}</style></head><body><h1>附件页面</h1><p>中文 空格（括号）</p><img src="data:image/png;base64,'+base64.b64encode(PNG).decode()+'"></body></html>'
ATTACK='''<script>parent.PWNED=1;fetch('https://evil.test/script')</script><img src="https://evil.test/image" onerror="parent.PWNED=2"><meta http-equiv="refresh" content="0;url=https://evil.test/refresh"><base href="https://evil.test/"><iframe src="https://evil.test/frame"></iframe><object data="https://evil.test/object"></object><form action="https://evil.test/form"><input name=x><button>send</button></form><a href="javascript:parent.PWNED=3">js</a><a href="https://evil.test/link" download>download</a><style>@import 'https://evil.test/css';body{background:url(https://evil.test/bg)}</style><svg onload="parent.PWNED=4"><use href="https://evil.test/svg"/></svg><p style="background:url(https://evil.test/style)">safe</p>'''
PAGE='''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><link rel=stylesheet href=/static/theme.css><link rel=stylesheet href=/static/artifact-preview.css><style>body{margin:0;font:16px system-ui}main{padding:24px;max-width:800px;margin:auto}textarea{width:90%;height:70px}button{min-height:44px}</style><main><h1>Teleply 附件候选</h1><p>脱敏样例；不连接真实会话。</p><button id=open>打开 HTML</button><textarea id=draft>保留草稿</textarea><div style="height:1300px"></div></main><script src=/static/purify.min.js></script><script src=/static/markdown-it.min.js></script><script src=/static/artifact-preview.js></script><script>window.PWNED=0;document.querySelector('#open').onclick=()=>artifactPreview.open({app:'codex',id:'fixture'},{id:'html',name:'中文 空格（括号）.html',path:'C:/fixture/page.html'});</script>'''

def run():
    with sync_playwright() as p:
        for engine in ('chromium','webkit'):
            browser=getattr(p,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
            context=browser.new_context(accept_downloads=True,viewport={'width':390,'height':844})
            page=context.new_page();errors=[];unexpected=[]
            page.on('pageerror',lambda e:errors.append((state.get('current'),str(e))))
            state={'updated':False,'error':0,'reads':0,'resources':[]}
            fixtures={'html':('中文 空格（括号）.html',HTML.encode(),'text'), 'attack':('attack.html',ATTACK.encode(),'text'),
                'relative':('page.html',b'<h1>relative</h1><link rel="stylesheet" href="style.css"><img src="img.png"><img src="secret.png">','text'),
                'img':('img.png',PNG,'image'),'css':('style.css',b'h1{color:rgb(255,0,0)}','text'),
                'md':('read.md','# 阅读标题\n\n**强调**\n\n<script>parent.PWNED=1</script>'.encode(),'text'),
                'txt':('code.json',b'{"x":"<script>parent.PWNED=1</script>"}','text'),
                'utf16':('utf16.txt','中文\r\n a  b'.encode('utf-16'),'text'),
                'invalid':('bad.txt',b'\xff\x11\x90','text'),'empty':('empty.txt',b'','text'),
                'docx':('document.docx',b'PK\x03\x04fixture','download'),'zip':('archive.zip',b'PK\x03\x04fixture','download'),
                'svg':('image.svg',b'<svg onload="parent.PWNED=1"/>','download'),
                'unknown':('noextension',b'fixture','download'),'badimg':('bad.png',b'not an image','image'),
                'badpdf':('bad.pdf',b'<script>parent.PWNED=1</script>','pdf'),
                'pdf':('sample.pdf',b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF','pdf'),
                'huge':('huge.zip',b'PK\x03\x04fixture','download'),
                'large':('large.txt',b'x'*(2<<20),'text')}
            def route(r):
                if r.request.url.startswith('blob:'+ORIGIN+'/'):return r.continue_()
                u=urlsplit(r.request.url);q=parse_qs(u.query);path=u.path
                if u.hostname!='artifact.test':unexpected.append(r.request.url);return r.abort()
                if path=='/':return r.fulfill(body=PAGE,content_type='text/html')
                if path.startswith('/static/'):
                    f=ROOT/path.lstrip('/');return r.fulfill(path=str(f),content_type=mimetypes.guess_type(f.name)[0] or 'text/plain')
                if state['error']:return r.fulfill(status=state['error'],json={'error':'fixture error'})
                if path=='/api/chat/files':return r.fulfill(json={'items':[{'id':'img','path':'C:/fixture/img.png'},{'id':'css','path':'C:/fixture/style.css'}]})
                fid=q.get('file',[''])[0]
                if q.get('id')!=['fixture'] or fid not in fixtures:return r.fulfill(status=403,json={'error':'denied'})
                name,data,kind=fixtures[fid]
                if path=='/api/file/meta':return r.fulfill(json={'name':name,'size':65<<20 if fid=='huge' else len(data),'kind':kind,'updated':state['updated']})
                if path=='/api/file':
                    state['reads']+=1;state['resources'].append(fid)
                    return r.fulfill(body=data,headers={'Content-Type':'application/octet-stream','Content-Disposition':'attachment'})
                unexpected.append(r.request.url);return r.abort()
            page.route('**/*',route);page.goto(ORIGIN)
            def open_file(fid):
                state['current']=fid
                page.evaluate("id=>artifactPreview.open({app:'codex',id:'fixture'},{id,name:id,path:'C:/fixture/page.html'})",fid)
                page.wait_for_timeout(100)
            open_file('html')
            assert page.locator('.artifact-frame').get_attribute('sandbox')==''
            assert page.frame_locator('.artifact-frame').locator('h1').inner_text()=='附件页面'
            assert page.frame_locator('.artifact-frame').locator('h1').evaluate('(n)=>getComputedStyle(n).color')=='rgb(18, 52, 86)'
            before=len(errors)
            assert page.locator('.artifact-frame').evaluate('(n)=>n.contentDocument===null')
            page.wait_for_timeout(50)
            # WebKit also reports our deliberate parent->opaque-frame probe as pageerror.
            assert all('lacks the "allow-same-origin" flag' in e[1] for e in errors[before:])
            del errors[before:]
            page.get_by_role('button',name='查看源码').click()
            assert page.locator('.artifact-source').text_content()==HTML
            page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async s=>window.copied=s}})")
            page.get_by_role('button',name='复制源码').click();assert page.evaluate('copied')==HTML
            with page.expect_download() as event:page.get_by_role('button',name='下载',exact=True).click()
            download=event.value
            assert hashlib.sha256(Path(download.path()).read_bytes()).digest()==hashlib.sha256(HTML.encode()).digest()
            assert download.suggested_filename=='中文 空格（括号）.html'
            open_file('attack');page.wait_for_timeout(150)
            frame=page.frame_locator('.artifact-frame')
            assert frame.locator('script,meta[http-equiv=refresh],base,iframe,object,form,svg').count()==0
            assert frame.locator('[href],[onerror]').count()==0
            assert page.evaluate('PWNED')==0
            assert not unexpected,unexpected
            open_file('relative')
            assert '部分资源未提供' in page.locator('.artifact-status').inner_text()
            assert page.frame_locator('.artifact-frame').locator('h1').evaluate('(n)=>getComputedStyle(n).color')=='rgb(255, 0, 0)'
            assert page.frame_locator('.artifact-frame').locator('img[src^="data:"]').count()==1
            assert 'secret' not in state['resources']
            for fid in ('txt','utf16','md','img','pdf','empty','docx','zip','svg','unknown','badimg','badpdf','invalid','large'):
                open_file(fid)
                if fid=='utf16':assert page.locator('pre').text_content()=='中文\r\n a  b'
                if fid=='md':assert page.frame_locator('.artifact-frame').locator('h1').inner_text()=='阅读标题'
                if fid in ('docx','zip','svg','unknown','large'):assert page.locator('.artifact-frame,.artifact-image,pre').count()==0
                if fid=='badimg':assert '图片损坏' in page.locator('.artifact-status').inner_text()
                if fid=='badpdf':assert '有效的 PDF' in page.locator('.artifact-status').inner_text()
                if fid=='invalid':assert 'UTF-8' in page.locator('.artifact-status').inner_text()
            for status in (401,403,404,409):
                state['error']=status;open_file('html');assert page.get_by_role('button',name='重试',exact=True).count()==1
                assert page.url==ORIGIN+'/'
            state['error']=0;state['updated']=True;open_file('html');assert '已更新' in page.locator('.artifact-status').inner_text()
            state['error']=401;page.get_by_role('button',name='下载',exact=True).click();page.wait_for_timeout(50)
            assert '登录已失效' in page.locator('.artifact-status').inner_text()
            assert not page.get_by_role('button',name='下载',exact=True).is_disabled()
            state['error']=0
            with page.expect_download():page.get_by_role('button',name='下载',exact=True).click()
            reads=state['reads'];open_file('large');assert state['reads']==reads
            page.evaluate("""()=>{window.realFetch=window.fetch;window.fetch=(url,init)=>String(url).startsWith('/api/file?')?Promise.resolve(new Response(new ReadableStream({start(c){for(let i=0;i<3;i++)c.enqueue(new Uint8Array(524288));c.close()},cancel(){window.streamCancelled=true}}))):realFetch(url,init)}""")
            open_file('txt');assert '读取上限' in page.locator('.artifact-status').inner_text();page.evaluate('window.fetch=realFetch')
            # Offline fetch, oversized header/stream, malformed dimensions and unchanged draft.
            page.route('**/api/file/meta?**',lambda r:r.abort())
            open_file('txt');assert '离线' in page.locator('.artifact-status').inner_text();page.unroute('**/api/file/meta?**')
            assert page.evaluate("""()=>{const b=new Uint8Array(24);b.set([137,80,78,71,13,10,26,10]);new DataView(b.buffer).setUint32(16,99999);new DataView(b.buffer).setUint32(20,99999);try{artifactPreview.dimensions(b);return false}catch{return true}}""")
            page.evaluate("window.scrollTo(0,500)");scroll=page.evaluate('scrollY');open_file('txt');page.get_by_role('button',name='返回聊天').click();assert page.evaluate('scrollY')==scroll
            # Late completion ignores AbortSignal deliberately, testing generation identity as well as cancellation.
            page.evaluate("""()=>{artifactPreview.close();window.revoked=[];window.created=[];const c=URL.createObjectURL.bind(URL),r=URL.revokeObjectURL.bind(URL);URL.createObjectURL=b=>{const u=c(b);created.push(u);return u};URL.revokeObjectURL=u=>{revoked.push(u);r(u)};window.delayed={meta:()=>new Promise(resolve=>window.finish=()=>resolve({name:'late.html',size:3,kind:'text'})),bytes:async()=>new TextEncoder().encode('old')};artifactPreview.open({}, {name:'late',id:'late'}, {adapter:delayed});} """)
            open_file('img');page.evaluate('finish()');page.wait_for_timeout(50)
            assert page.locator('.artifact-image').count()==1
            page.evaluate('artifactPreview.close()');assert page.evaluate('created.every(u=>revoked.includes(u))')
            page.evaluate("artifactPreview.open({}, {name:'late',id:'late'}, {adapter:delayed});artifactPreview.close();finish()")
            page.wait_for_timeout(50);assert page.locator('dialog').count()==0
            assert page.locator('#draft').input_value()=='保留草稿'
            for width,height in ((390,844),(844,390),(1280,800)):
                page.set_viewport_size({'width':width,'height':height})
                for theme in ('light','dark'):
                    page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme);open_file('html')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('.artifact-panel').evaluate('(n)=>n.scrollWidth<=n.clientWidth')
                    for b in page.locator('.artifact-panel button').all():assert b.bounding_box()['height']>=44
                    page.screenshot(path=str(OUT/f'{engine}-{width}-{theme}.png'))
                    page.get_by_role('button',name='返回聊天').click()
            assert not errors,errors
            assert not unexpected,unexpected
            # WebKit does not emit native download events for route.fulfill attachments.
            # Exercise the streaming handoff against a real, fixture-only HTTP endpoint.
            from serve_artifact_preview import Fixture,FILES
            from http.server import ThreadingHTTPServer
            from threading import Thread
            FILES['huge']=('native.zip',b'fixture native bytes','download')
            server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            native=context.new_page()
            try:
                native.goto('http://127.0.0.1:'+str(server.server_port))
                native.evaluate("artifactPreview.open({app:'codex',id:'fixture'},{id:'huge',name:'native.zip'})")
                with native.expect_download(timeout=5000) as result:native.get_by_role('button',name='下载',exact=True).click()
                assert Path(result.value.path()).read_bytes()==b'fixture native bytes'
                assert '浏览器下载' in native.locator('.artifact-status').inner_text()
                assert native.url.endswith(str(server.server_port)+'/')
            finally:native.close();server.shutdown();server.server_close()
            context.close();browser.close();print(engine+': attachment security, original-byte/native downloads, formats, races, 6 layouts passed')

if __name__=='__main__':run()
