"""Theme regression on real pages with mocked APIs; never touches live chats."""
from pathlib import Path
from urllib.parse import urlsplit
import mimetypes
from playwright.sync_api import sync_playwright
from motion_check import handle, ORIGIN
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/theme-check';OUT.mkdir(parents=True,exist_ok=True)
def route(r):
    path=urlsplit(r.request.url).path
    name=path.rsplit('/',1)[-1]
    if (ROOT/'static'/name).is_file():
        return r.fulfill(path=str(ROOT/'static'/name),content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
    if path=='/account':return r.fulfill(path=str(ROOT/'relay_account.html'),content_type='text/html')
    if path in ['/account/ui.css','/account/ui.js']:
        return r.fulfill(path=str(ROOT/('relay_account.'+name.split('.')[-1])),content_type='text/css' if name.endswith('css') else 'application/javascript')
    if path=='/account/config':return r.fulfill(json={'email_enabled':False})
    if path=='/account/state':return r.fulfill(status=401,json={'error':'not signed in'})
    return handle(r,r.request)
with sync_playwright() as p:
    b=p.chromium.launch(channel='chrome',headless=True)
    for width,height in [(360,800),(844,390),(1280,900)]:
        c=b.new_context(viewport={'width':width,'height':height},color_scheme='dark')
        c.route('**/*',route);page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(ORIGIN+'/');page.wait_for_function('window.TeleplyTheme && document.querySelector("[data-theme-choice]")')
        assert page.locator('html').get_attribute('data-theme')=='dark'
        assert page.locator('link[rel=icon]').count()==1
        assert page.evaluate('getComputedStyle(document.body).backgroundColor')=='rgb(0, 0, 0)'
        page.evaluate("openSheet('settingsSheet')")
        page.locator('[data-theme-choice=system]').focus();page.keyboard.press('ArrowRight')
        assert page.locator('html').get_attribute('data-theme')=='light'
        page.emulate_media(color_scheme='dark');assert page.locator('html').get_attribute('data-theme')=='light'
        page.locator('[data-theme-choice=dark]').click()
        page.screenshot(path=str(OUT/f'settings-{width}.png'))
        second=c.new_page();second.goto(ORIGIN+'/');second.wait_for_function('window.TeleplyTheme')
        second.evaluate("TeleplyTheme.set('light')");page.wait_for_function("document.documentElement.dataset.theme==='light'")
        page.evaluate("TeleplyTheme.set('dark');closeSheet('settingsSheet')")
        page.reload();page.wait_for_function("document.documentElement.dataset.theme==='dark'")
        page.wait_for_selector('.conv');page.locator('.conv').first.click();page.wait_for_timeout(700)
        page.locator('#cvText').fill('保留这段草稿');page.evaluate("TeleplyTheme.set('light');TeleplyTheme.set('dark')")
        assert page.locator('#cvText').input_value()=='保留这段草稿'
        page.screenshot(path=str(OUT/f'chat-{width}.png'))
        page.goto(ORIGIN+'/account');page.wait_for_selector('#auth:not([hidden])');page.wait_for_function("!document.querySelector('main').classList.contains('booting')");page.wait_for_timeout(750);page.locator('.theme-settings summary').click()
        assert page.locator('html').get_attribute('data-theme')=='dark'
        page.screenshot(path=str(OUT/f'account-settings-{width}.png'))
        page.locator('.theme-settings summary').click();page.screenshot(path=str(OUT/f'account-{width}.png'));page.locator('.theme-settings summary').click()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('[data-theme-choice=system]').click();page.emulate_media(color_scheme='light');page.wait_for_function("document.documentElement.dataset.theme==='light'")
        assert not errors,errors
        c.close()
    c=b.new_context(color_scheme='dark');c.route('**/*',route)
    c.add_init_script("Storage.prototype.getItem=()=>{throw Error('blocked')};Storage.prototype.setItem=()=>{throw Error('blocked')}")
    page=c.new_page();page.goto(ORIGIN+'/account');page.wait_for_function('window.TeleplyTheme');page.evaluate("TeleplyTheme.set('light')")
    assert page.locator('html').get_attribute('data-theme')=='light'
    b.close()
print('Theme: viewport, system/manual, persistence, tabs, draft, account and blocked-storage checks passed.')
