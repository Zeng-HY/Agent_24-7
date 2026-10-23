"""Scoped mobile regression: drawer hit areas, composer alignment, queue editing and safe downloads."""
import json,mimetypes,sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright
import motion_check as fixture
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_pages import scoped_page
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/mobile-fixes';OUT.mkdir(parents=True,exist_ok=True)
DEVICE='a'*32;PREFIX='/d/'+DEVICE
state={'available':True,'running':True,'active_turn_id':'turn1','questions':[],'queue_available':True,'queued':[],'images':[],'plan':None,'settings':{'model':'gpt-6-astra','effort':'medium','mode':'default','service_tier':None},'catalog':{'models':[]}}
receipts={};sends=[];actions=[];files={'fail':False}
pdf=b'%PDF-1.4\n% Synthetic download test, no personal documents.\n%%EOF\n'
def route(r):
    req=r.request;u=urlsplit(req.url);path=u.path.removeprefix(PREFIX);body=json.loads(req.post_data or '{}')
    def out(v,status=200):r.fulfill(status=status,content_type='application/json',body=json.dumps(v))
    if path=='/':return r.fulfill(content_type='text/html',body=scoped_page((ROOT/'remote.html').read_bytes(),DEVICE))
    name=path.lstrip('/')
    if name and (ROOT/'static'/name).is_file():return r.fulfill(path=str(ROOT/'static'/name),content_type=mimetypes.guess_type(name)[0] or 'application/javascript')
    if path=='/api/codex/state':return out(state)
    if path=='/api/codex/receipt':return out(receipts.get(parse_qs(u.query)['request_id'][0],{'state':'unknown'}))
    if path=='/api/codex/send':
        sends.append(body);queued=body['intent']=='queue';rid=body['request_id'];receipts[rid]={'state':'queued' if queued else 'accepted'}
        if queued:state['queued'].append({'id':rid,'text':body['text'],'status':'queued'})
        return out({'accepted':True,'delivery_state':'queued' if queued else 'accepted'})
    if path=='/api/codex/queue-action':
        actions.append(body);state['queued']=[q for q in state['queued'] if q['id']!=body['message_id']];receipts[body['message_id']]={'state':'accepted' if body['action']=='promote' else 'cancelled'}
        return out({'ok':True})
    if path=='/api/chat/files':return out({'items':[{'id':'file1','name':'test.pdf','size':len(pdf),'kind':'download','modified':1}],'scope':'test'})
    if path=='/api/file':
        if files['fail']:return out({'error':'请先登录'},401)
        return r.fulfill(content_type='application/pdf',body=pdf,headers={'Content-Disposition':'attachment; filename="test.pdf"'})
    return fixture.handle(r,SimpleNamespace(url=fixture.ORIGIN+path+('?' +u.query if u.query else ''),post_data=req.post_data,method=req.method))
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True)
    ctx=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    ctx.route('**/*',route);ctx.add_init_script(fixture.INIT);page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(fixture.ORIGIN+PREFIX+'/');page.wait_for_function('window.navigationUI && window.codexUI && window.readingUI')
    page.locator('header [aria-label="打开导航"]').click();page.wait_for_timeout(500)
    row=page.locator('.relay-menu button').filter(has_text='连接设置');r=row.bounding_box();footer=page.locator('.nav-foot').bounding_box();menu=page.locator('.relay-menu').bounding_box()
    assert menu['y']+menu['height']<=footer['y']+1
    assert footer['y']+footer['height']>=830
    xs=page.locator('.relay-menu .nav-action-label').evaluate_all('(ns)=>ns.map(n=>n.getBoundingClientRect().left)');assert max(xs)-min(xs)<1
    tree=page.locator('.tree-app .tree-name').first.bounding_box();assert abs(tree['x']-xs[0])<1,(tree,xs)
    ticks=page.evaluate('window.__haptics');page.touchscreen.tap(r['x']+r['width']-10,r['y']+r['height']/2)
    page.wait_for_selector('dialog.ar-connection[open]');assert page.evaluate('window.__haptics')>ticks
    page.locator('.ar-done').click();page.screenshot(path=str(OUT/'drawer.png'));page.locator('#navSheet [aria-label="关闭导航"]').click()
    page.evaluate('c=>openConv(c)',fixture.fake_chat('codex','c4'));page.wait_for_function('!document.getElementById("cvBtn").disabled || !!document.querySelector("#modelChoice .composer-label")');page.wait_for_timeout(500)
    centers=page.locator('#addImageBtn,#modelChoice,#modeChoice').evaluate_all('(ns)=>ns.map(n=>{const r=n.getBoundingClientRect();return r.y+r.height/2})');assert max(centers)-min(centers)<1,centers
    assert not page.get_by_text('发送会立即补充给这一轮',exact=True).count()
    page.locator('#cvText').fill('排队后可编辑');page.locator('#cvBtn').click();page.wait_for_function('!sending');assert sends[-1]['intent']=='queue'
    assert page.locator('#cvText').input_value()==''
    assert not page.locator('.bub.outbox').count()
    page.screenshot(path=str(OUT/'queued.png'))
    page.locator('#codexQueue [aria-label="待发送消息操作"]').click();page.locator('#queueActionsSheet').get_by_role('button',name='编辑草稿',exact=True).click()
    page.wait_for_function("document.getElementById('cvText').value==='排队后可编辑'");assert actions[-1]['action']=='cancel'
    page.locator('#cvBtn').click();page.wait_for_function('!sending');page.locator('#cvText').fill('不能覆盖的新草稿')
    page.locator('#codexQueue [aria-label="待发送消息操作"]').click();count=len(actions);page.locator('#queueActionsSheet').get_by_role('button',name='编辑草稿',exact=True).click();page.wait_for_timeout(200)
    assert len(actions)==count and page.locator('#cvText').input_value()=='不能覆盖的新草稿'
    page.locator('#cvText').fill('');page.locator('#codexQueue button').filter(has_text='立即补充').click();page.wait_for_function("!document.querySelector('#codexQueue .queue-row')");assert actions[-1]['action']=='promote'
    state['running']=False;page.evaluate('codexUI.refresh(cur,true)');page.locator('#cvText').fill('空闲时直接发送');page.locator('#cvBtn').click();page.wait_for_function('!sending');assert sends[-1]['intent']=='auto'
    page.screenshot(path=str(OUT/'composer.png'))
    page.evaluate("openSheet('convMenu')");page.locator('#convMenu').get_by_role('button',name='对话文件',exact=True).click();page.locator('#conversationFiles').get_by_role('button',name='下载',exact=True).click();page.wait_for_selector('.file-save')
    url=page.url
    with page.expect_download() as info:page.locator('.file-save').click()
    download=info.value;assert download.suggested_filename=='test.pdf';assert Path(download.path()).read_bytes()==pdf;assert page.url==url
    page.evaluate("closeSheet('resultPreview');closeSheet('conversationFiles')");files['fail']=True
    page.evaluate("openSheet('convMenu')");page.locator('#convMenu').get_by_role('button',name='对话文件',exact=True).click();page.locator('#conversationFiles').get_by_role('button',name='下载',exact=True).click();page.wait_for_selector('#sessionExpiredSheet.is-open');assert page.url==url
    page.screenshot(path=str(OUT/'expired-download.png'))
    assert not errors,errors
    browser.close()
print('PASS drawer ordering/alignment/full-row haptic path; composer alignment; default queue/edit/promote/idle send; PDF byte integrity and 401 recovery without navigation')
