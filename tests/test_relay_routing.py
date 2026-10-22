from pathlib import Path
import sys
import unittest
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_pages import scoped_page


class Routing(unittest.TestCase):
    def test_relative_fetch_request_images_and_account_navigation(self):
        device='a'*32
        html=scoped_page(b'<html><head></head><body><img src="/initial"><div id="dynamic"></div></body></html>',device)
        seen=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page()
            def route(r):
                seen.append(r.request.url)
                if r.request.url.endswith('/d/'+device+'/'):
                    r.fulfill(body=html,content_type='text/html')
                else:r.fulfill(body='{}',content_type='application/json')
            page.route('https://relay.test/**',route)
            page.goto('https://relay.test/d/'+device+'/')
            page.evaluate("async()=>{await fetch('/api/status');await fetch(new Request('/api/upload',{method:'POST',body:'abc'}));const img=new Image();img.src='/photo';document.body.append(img);document.querySelector('#dynamic').innerHTML='<img src=\"/dynamic-photo\">';await fetch('/account/state');}")
            page.wait_for_timeout(150)
            for suffix in ('initial','api/status','api/upload','photo','dynamic-photo'):
                self.assertIn('https://relay.test/d/'+device+'/'+suffix,seen)
                self.assertNotIn('https://relay.test/'+suffix,seen)
            self.assertIn('https://relay.test/account/state',seen)
            browser.close()


if __name__=='__main__':unittest.main()
