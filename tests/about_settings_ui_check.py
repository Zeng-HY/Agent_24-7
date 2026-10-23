"""User-visible Settings -> About reachability with real HTML and APK-packaged UI."""
from pathlib import Path
from urllib.parse import urlsplit
import mimetypes,sys
from types import SimpleNamespace
from playwright.sync_api import sync_playwright
import motion_check as fixture
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_pages import scoped_page
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/about-ui';OUT.mkdir(parents=True,exist_ok=True)
state={'signed':False,'online':False};did='a'*32
native=(ROOT/'mobile/src/native-about.js').read_text(encoding='utf-8-sig')
def route(r):
 req=r.request;u=urlsplit(req.url);path=u.path.removeprefix('/d/'+did)
 if path=='/':return r.fulfill(content_type='text/html',body=scoped_page((ROOT/'remote.html').read_bytes(),did))
 if path=='/account':return r.fulfill(path=str(ROOT/'relay_account.html'),content_type='text/html',headers={'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'"})
 if path in ['/account/ui.js','/account/ui.css']:
  name='relay_account.'+path.rsplit('.',1)[1];return r.fulfill(path=str(ROOT/name),content_type='application/javascript' if name.endswith('js') else 'text/css')
 name=path.removeprefix('/account/').lstrip('/')
 if name and (ROOT/'static'/name).is_file():return r.fulfill(path=str(ROOT/'static'/name),content_type=mimetypes.guess_type(name)[0] or 'application/javascript')
 if path=='/account/config':return r.fulfill(json={'email_enabled':False})
 if path=='/account/state':
  if not state['signed']:return r.fulfill(status=401,json={'error':'请先登录'})
  return r.fulfill(json={'devices':[{'id':did,'label':'测试电脑','online':state['online'],'connectable':state['online'],'legacy':False}],'email':'','usage':{}})
 return fixture.handle(r,SimpleNamespace(url=fixture.ORIGIN+path+('?' +u.query if u.query else ''),method=req.method,post_data=req.post_data))
with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True)
 for width in [360,390]:
  c=b.new_context(viewport={'width':width,'height':844},is_mobile=True,has_touch=True);c.route('**/*',route);page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  for signed in [False,True]:
   state['signed']=signed;page.goto(fixture.ORIGIN+'/account?choose=1');page.locator('main:not(.booting)').wait_for();page.wait_for_timeout(800)
   assert not page.locator('[data-native-about]').count()
   centers=page.locator('.app-settings-header > .brand,.theme-settings>summary').evaluate_all('(ns)=>ns.map(n=>{const r=n.getBoundingClientRect();return r.y+r.height/2})');assert len(centers)==2 and max(centers)-min(centers)<1,centers
   page.evaluate(native);page.evaluate("window.aboutOpened=0;TeleplyAbout.mount(()=>aboutOpened++)")
   page.get_by_text('设置',exact=True).click();page.get_by_role('button',name='关于遥应',exact=True).click();assert page.evaluate('aboutOpened')==1
   assert page.locator('[data-native-about]').count()==1
   for mode in ['light','dark']:
    page.evaluate('m=>TeleplyTheme.set(m)',mode);page.wait_for_timeout(250)
    assert page.locator('.theme-choices').evaluate('n=>getComputedStyle(n).borderTopWidth')=='0px'
    assert page.locator('.theme-choices button').evaluate_all("ns=>ns.every(n=>getComputedStyle(n).borderTopWidth==='0px')")
    page.screenshot(path=str(OUT/f'account-{width}-{signed}-{mode}.png'))
   if signed:assert page.locator('.device-connect').is_disabled()
  page.goto(fixture.ORIGIN+'/d/'+did+'/');page.wait_for_function('window.navigationUI');assert not page.locator('[data-native-about]').count()
  page.evaluate(native);page.evaluate("window.aboutOpened=0;TeleplyAbout.mount(()=>aboutOpened++)")
  page.locator('header [aria-label="打开导航"]').click();page.wait_for_timeout(450);page.locator('#settingsBtn').click();page.wait_for_timeout(450)
  page.locator('#settingsBody').get_by_role('button',name='关于遥应',exact=True).click();assert page.evaluate('aboutOpened')==1
  page.screenshot(path=str(OUT/f'chat-settings-{width}.png'));assert not errors,errors;c.close()
 b.close()
print('PASS visible Settings -> About for logged-out, offline and chat screens; browser exclusion; header alignment; segmented themes at 360/390px')
