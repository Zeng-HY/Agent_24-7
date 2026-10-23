"""WebKit layout checks for the account home and relay connection panel."""
import json,sys,unittest
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relay_pages import scoped_page


class MobileLayout(unittest.TestCase):
    def test_account_home_and_connection_panel(self):
        shots=ROOT/'attachments/qa-mobile-layout';shots.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as pw:
            browser=pw.webkit.launch();page=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            def route(r):
                path=urlsplit(r.request.url).path
                assets={'/account':('relay_account.html','text/html'),'/account/ui.css':('relay_account.css','text/css'),'/account/ui.js':('relay_account.js','application/javascript')}
                if path in assets:
                    name,mime=assets[path];return r.fulfill(body=(ROOT/name).read_bytes(),content_type=mime)
                if path=='/account/config':data={'email_enabled':True}
                elif path=='/account/state':data={'email':'test@example.test','devices':[{'id':'a'*32,'label':'家里电脑','online':True}]}
                else:data={}
                r.fulfill(content_type='application/json',body=json.dumps(data))
            page.route('https://relay.test/**',route);page.goto('https://relay.test/account?choose=1')
            page.locator('#signed').wait_for(state='visible')
            for width,height in [(390,844),(320,568),(844,390)]:
                page.set_viewport_size({'width':width,'height':height})
                brand=page.locator('.brand');self.assertLess(brand.bounding_box()['y'],65)
                self.assertGreaterEqual(brand.evaluate('n=>parseFloat(getComputedStyle(n).fontSize)'),24)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(shots/'home.png'))
            # Use a scoped device page: the routing injection must style its own dialog.
            source=b'<html><head><meta charset="utf-8"></head><body><aside id="navSheet"><div class="box"></div></aside></body></html>'
            page.unroute_all();page.route('https://relay.test/**',lambda r:r.fulfill(body=scoped_page(source,'a'*32),content_type='text/html'))
            page.goto('https://relay.test/d/'+'a'*32+'/')
            trigger=page.get_by_role('button',name='连接设置',exact=True)
            for width,height in [(390,844),(320,568),(844,390)]:
                page.set_viewport_size({'width':width,'height':height});trigger.click()
                panel=page.locator('dialog');panel.wait_for(state='visible');r=panel.bounding_box()
                self.assertGreaterEqual(r['x'],0);self.assertLessEqual(r['x']+r['width'],width)
                self.assertGreaterEqual(r['y'],0);self.assertLessEqual(r['y']+r['height'],height)
                self.assertEqual(panel.evaluate('n=>getComputedStyle(n).borderRadius'),'26px')
                page.keyboard.press('Escape');page.locator('dialog').wait_for(state='detached')
                self.assertTrue(trigger.evaluate('n=>n===document.activeElement'))
            page.set_viewport_size({'width':390,'height':844});trigger.click();page.screenshot(path=str(shots/'connection.png'))
            page.get_by_role('button',name='完成',exact=True).click();page.locator('dialog').wait_for(state='detached')
            trigger.click();page.mouse.click(1,1);page.locator('dialog').wait_for(state='detached')
            self.assertEqual(errors,[]);browser.close()


if __name__=='__main__':unittest.main()
