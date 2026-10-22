"""Actual account server behind a browser HTTPS route adapter; no real accounts."""
import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from playwright.sync_api import sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_accounts import Accounts
from relay_cloud import Cloud


class AccountUiTests(unittest.TestCase):
    def test_invite_login_bind_logout_password_reset_and_no_dom_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Accounts(Path(tmp)/'auth.sqlite3')
            cloud=Cloud(0,'https://relay.example',store)
            threading.Thread(target=cloud.serve_forever,daemon=True).start()
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(channel='chrome',headless=True)
                    context=browser.new_context()
                    page=context.new_page()
                    errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    def route(request_route):
                        request=request_route.request
                        headers=request.all_headers()
                        headers['Host']='relay.example'
                        conn=http.client.HTTPConnection('127.0.0.1',cloud.server_port,timeout=10)
                        conn.request(request.method,request.url.removeprefix('https://relay.example'),
                                     body=request.post_data_buffer,headers=headers)
                        response=conn.getresponse()
                        out={k:v for k,v in response.getheaders() if k.lower() not in ('connection','content-length')}
                        request_route.fulfill(status=response.status,headers=out,body=response.read())
                        conn.close()
                    page.route('https://relay.example/**',route)
                    invite=store.grant('invite')
                    page.goto('https://relay.example/account#invite='+invite)
                    self.assertEqual(page.url,'https://relay.example/account')
                    page.locator('#name').fill('alice')
                    page.locator('#password').fill('browser-password-alice')
                    page.locator('#register').click()
                    page.get_by_text('已完成，请登录',exact=True).wait_for()
                    page.locator('#password').fill('browser-password-alice')
                    page.locator('#login').click()
                    page.locator('#signed').wait_for(state='visible')
                    cookies=context.cookies()
                    auth=next(c for c in cookies if c['name']=='__Host-ar_account')
                    self.assertTrue(auth['secure'] and auth['httpOnly'])
                    self.assertEqual(auth['sameSite'],'Strict')
                    page.locator('#bind').click()
                    page.wait_for_function("document.querySelector('#message').textContent.includes('绑定码')")
                    code=page.locator('#message').inner_text().split('\n')[-1]
                    store.bind(code,'<img src=x onerror=alert(1)>','alice')
                    page.reload()
                    page.locator('#devices li').wait_for()
                    self.assertEqual(page.locator('#devices img').count(),0)
                    page.locator('#old').fill('browser-password-alice')
                    page.locator('#new').fill('browser-password-changed')
                    page.locator('#change').click()
                    page.get_by_text('密码已修改，请重新登录',exact=True).wait_for()
                    self.assertFalse(store.valid(auth['value']))
                    reset=store.grant('reset',store.user('alice')['id'])
                    page.goto('https://relay.example/account#reset='+reset)
                    page.locator('#password').fill('browser-password-reset')
                    page.locator('#reset').click()
                    page.get_by_text('已完成，请登录',exact=True).wait_for()
                    page.locator('#name').fill('alice')
                    page.locator('#password').fill('browser-password-reset')
                    page.locator('#login').click()
                    page.locator('#signed').wait_for(state='visible')
                    page.locator('#logout').click()
                    page.get_by_text('已退出',exact=True).wait_for()
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                cloud.shutdown();cloud.server_close()


if __name__=='__main__':unittest.main()
