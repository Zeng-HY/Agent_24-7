"""Appearance bounds and account availability, using real pages and isolated fixtures."""
from pathlib import Path
from urllib.parse import urlsplit
import json,mimetypes,sys
from playwright.sync_api import sync_playwright
import motion_check as fixture
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_pages import scoped_page
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/dev10-ui';OUT.mkdir(parents=True,exist_ok=True)
did='a'*32;online=[False];racing=[False];calls=[];short=[True]
def route(r):
 req=r.request;u=urlsplit(req.url);path=u.path.removeprefix('/d/'+did)
 if path=='/':return r.fulfill(content_type='text/html',body=scoped_page((ROOT/'remote.html').read_bytes(),did))
 if path=='/account':return r.fulfill(path=str(ROOT/'relay_account.html'),content_type='text/html')
 if path in ['/account/ui.js','/account/ui.css']:
  name='relay_account.'+path.rsplit('.',1)[1];return r.fulfill(path=str(ROOT/name),content_type='application/javascript' if name.endswith('js') else 'text/css')
 name=path.removeprefix('/account/').lstrip('/')
 if (ROOT/'static'/name).is_file():return r.fulfill(path=str(ROOT/'static'/name),content_type=mimetypes.guess_type(name)[0] or 'application/javascript')
 if path=='/account/config':return r.fulfill(json={'email_enabled':False})
 if path=='/account/state':return r.fulfill(json={'devices':[{'id':did,'label':'测试电脑','online':online[0],'connectable':online[0],'legacy':True}],'email':'','usage':{}})
 if path=='/account/select':
  calls.append(req.post_data)
  if racing[0]:online[0]=False;return r.fulfill(status=409,json={'error':'电脑已离线，请等待上线后再连接','code':'device_offline'})
  return r.fulfill(json={'url':'/d/'+did+'/'})
 if path=='/api/chats' and short[0]:return r.fulfill(json={'items':fixture.fake_chats(1),'total':1,'has_more':False,'next_cursor':None})
 from types import SimpleNamespace
 return fixture.handle(r,SimpleNamespace(url=fixture.ORIGIN+path+('?' +u.query if u.query else ''),method=req.method,post_data=req.post_data))
with sync_playwright() as p:
 browser=p.chromium.launch(channel='chrome',headless=True);ctx=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
 ctx.route('**/*',route);page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(fixture.ORIGIN+'/account?choose=1');page.wait_for_selector('.device-connect');page.evaluate("TeleplyTheme.set('dark')")
 assert page.locator('.device-connect').is_disabled();assert page.locator('.device-connect').inner_text()=='离线'
 assert page.locator('.device-actions .icon-button').is_enabled()
 colors=page.evaluate("[...document.querySelectorAll('.device-actions button')].map(n=>getComputedStyle(n).backgroundColor)")
 assert colors[0]=='rgb(30, 30, 30)' and colors[1]=='rgba(0, 0, 0, 0)',colors
 page.locator('.device-connect').evaluate('(b)=>b.click()');assert not calls
 page.wait_for_function("!document.querySelector('main').classList.contains('booting')");page.wait_for_timeout(800)
 page.screenshot(path=str(OUT/'offline.png'))
 online[0]=True;page.evaluate('state()');assert page.locator('.device-connect').is_enabled()
 racing[0]=True;before=page.url;page.locator('.device-connect').click();page.wait_for_function("document.querySelector('.device-connect').disabled")
 assert page.url==before and '电脑已离线' in page.locator('#message').inner_text()
 online[0]=True;racing[0]=False;page.evaluate('state()');page.locator('.device-connect').click();page.wait_for_url('**/d/'+did+'/');page.wait_for_function('window.navigationUI')
 page.add_init_script("window.__teleplyAppearanceDocument='test';window.nativeThemes=[];window.TeleplyAppearance={postMessage:value=>nativeThemes.push(JSON.parse(value))};")
 page.reload();page.wait_for_function('window.navigationUI && window.TeleplyTheme');page.wait_for_timeout(250)
 for dark in [False,True]:
  page.evaluate('v=>TeleplyTheme.set(v)','dark' if dark else 'light')
  assert page.locator('meta[name=theme-color]').count()==1
  assert page.evaluate('nativeThemes.at(-1).resolved')==('dark' if dark else 'light')
  assert page.evaluate('getComputedStyle(document.documentElement).backgroundColor')==('rgb(0, 0, 0)' if dark else 'rgb(255, 255, 255)')
  assert page.evaluate('getComputedStyle(document.body).paddingBottom')=='0px'
  assert page.evaluate('document.documentElement.scrollHeight<=innerHeight+1')
  page.locator('header [aria-label="打开导航"]').click();page.wait_for_timeout(450)
  assert not page.locator('.relay-menu button').filter(has_text='连接设置').count()
  for width,height in [(390,650),(844,390),(390,844)]:
   page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(150)
   m=page.evaluate("(()=>{const r=document.querySelector('#navSheet .box').getBoundingClientRect();return {bottom:r.bottom,height:innerHeight,width:document.documentElement.scrollWidth,viewportWidth:innerWidth,inline:document.querySelector('#navSheet').style.height}})()")
   assert abs(m['bottom']-m['height'])<1 and m['width']<=m['viewportWidth']+1 and not m['inline'],m
  page.screenshot(path=str(OUT/('drawer-dark.png' if dark else 'drawer-light.png')))
  page.locator('#navSheet [aria-label="关闭导航"]').click();page.wait_for_timeout(450)
  assert page.evaluate('getComputedStyle(document.getElementById("chatBackdrop")).backgroundColor')==('rgb(0, 0, 0)' if dark else 'rgb(255, 255, 255)')
 assert not errors,errors
 browser.close()
print('PASS offline disabled/management/race/reconnect; theme messages; short-page height; drawer dynamic bounds; root and chat backgrounds')
