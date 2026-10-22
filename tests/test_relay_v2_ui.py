import asyncio
import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit
from aiohttp import web
from playwright.sync_api import sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_identity import Identity
from relay_service import Service


class Mail:
    ready=True
    def __init__(self):self.sent=[]
    def send(self,*args):self.sent.append(args)


class UI(unittest.TestCase):
    def test_unified_login_register_device_dialog_and_responsive_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Identity(Path(temp)/'state.db');mail=Mail()
            store.register('alice','password-for-alice',store.grant('invite'))
            token=store.login('alice','password-for-alice')
            store.approve(token,store.start_authorization('x'*43,'测试电脑'))
            service=Service('https://relay.test',store,mail)
            loop=asyncio.new_event_loop()
            runner=web.AppRunner(service.app,access_log=None)
            async def start():
                await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
                return site._server.sockets[0].getsockname()[1]
            thread=threading.Thread(target=loop.run_forever,daemon=True);thread.start()
            port=asyncio.run_coroutine_threadsafe(start(),loop).result()
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(channel='chrome',headless=True)
                    context=browser.new_context(viewport={'width':390,'height':844})
                    page=context.new_page();errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    def forward(route):
                        request=route.request;p=urlsplit(request.url)
                        headers=request.all_headers();headers['Host']='relay.test'
                        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
                        conn.request(request.method,p.path+('?' +p.query if p.query else ''),body=request.post_data_buffer,headers=headers)
                        response=conn.getresponse()
                        route.fulfill(status=response.status,headers={k:v for k,v in response.getheaders() if k.lower() not in ('connection','content-length')},body=response.read())
                        conn.close()
                    page.route('https://relay.test/**',forward)
                    page.goto('https://relay.test/account');page.locator('#mode').wait_for(state='visible')
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    shots=Path(__file__).resolve().parents[1]/'attachments/qa027';shots.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(shots/'login.png'),full_page=True)
                    page.locator('#mode').click();self.assertEqual(page.locator('#title').inner_text(),'创建账号')
                    page.locator('#name').fill('new@example.test');page.locator('#password').fill('new-user-password')
                    page.locator('#form').evaluate('(form)=>form.requestSubmit()')
                    page.locator('#resend').wait_for(state='visible')
                    page.locator('#resend').click();page.get_by_text('已重新发送',exact=True).wait_for()
                    self.assertEqual(len(mail.sent),2)
                    page.locator('#mode').click();page.locator('#name').fill('alice');page.locator('#password').fill('password-for-alice')
                    page.locator('#submit').click();page.locator('#signed').wait_for(state='visible')
                    page.screenshot(path=str(shots/'devices.png'),full_page=True)
                    page.get_by_label('管理电脑').click();page.get_by_role('button',name='重命名',exact=True).click();page.locator('#dialog').wait_for(state='visible')
                    page.locator('#dialog-label').fill('自己的电脑');page.locator('#confirm').click()
                    page.get_by_text('自己的电脑',exact=True).wait_for()
                    page.locator('#menuButton').click();page.get_by_role('button',name='退出登录',exact=True).click()
                    page.locator('#auth').wait_for(state='visible')
                    page.set_viewport_size({'width':320,'height':568})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),320)
                    page.screenshot(path=str(shots/'login-320.png'),full_page=True)
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                asyncio.run_coroutine_threadsafe(runner.cleanup(),loop).result()
                loop.call_soon_threadsafe(loop.stop);thread.join();loop.close()


    def test_codes_typed_on_the_page_sign_in_and_reset_and_closed_sign_up_says_so(self):
        """Sign-up and 忘记密码 with the six digits from the email, typed where they were asked for; without mail
        set up on the server, 暂未开放注册 instead of the way in."""
        with tempfile.TemporaryDirectory() as temp:
            store=Identity(Path(temp)/'state.db');mail=Mail()
            service=Service('https://relay.test',store,mail)
            loop=asyncio.new_event_loop();runner=web.AppRunner(service.app,access_log=None)
            async def start():
                await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
                return site._server.sockets[0].getsockname()[1]
            thread=threading.Thread(target=loop.run_forever,daemon=True);thread.start()
            port=asyncio.run_coroutine_threadsafe(start(),loop).result()
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(channel='chrome',headless=True)
                    page=browser.new_context(viewport={'width':390,'height':844}).new_page();errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    def forward(route):
                        request=route.request;p=urlsplit(request.url)
                        headers=request.all_headers();headers['Host']='relay.test'
                        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
                        conn.request(request.method,p.path+('?'+p.query if p.query else ''),body=request.post_data_buffer,headers=headers)
                        response=conn.getresponse()
                        route.fulfill(status=response.status,headers={k:v for k,v in response.getheaders() if k.lower() not in ('connection','content-length')},body=response.read())
                        conn.close()
                    page.route('https://relay.test/**',forward)
                    page.goto('https://relay.test/account');page.locator('#mode').wait_for(state='visible')
                    page.locator('#mode').click();page.locator('#name').fill('typed@example.test');page.locator('#password').fill('typed-account-password')
                    page.locator('#submit').click()
                    page.locator('#code').wait_for(state='visible')
                    self.assertEqual((page.locator('#title').inner_text(),page.locator('#sentTo').inner_text()),('输入验证码','typed@example.test'))
                    page.locator('#code').press_sequentially(mail.sent[-1][3])  # the sixth digit sends it
                    page.locator('#signed').wait_for(state='visible')
                    page.locator('#menuButton').click();page.get_by_role('button',name='退出登录',exact=True).click()
                    page.locator('#forgot').wait_for(state='visible');page.locator('#forgot').click()
                    page.locator('#name').fill('typed@example.test');page.locator('#submit').click()
                    page.locator('#code').wait_for(state='visible')
                    self.assertEqual(page.locator('#title').inner_text(),'重置密码')
                    page.locator('#code').fill(mail.sent[-1][3]);page.locator('#password').fill('typed-password-changed');page.locator('#submit').click()
                    page.locator('#signed').wait_for(state='visible')
                    self.assertTrue(store.login('typed@example.test','typed-password-changed'))
                    mail.ready=False  # no mail on the server: no way in that cannot work
                    page.locator('#menuButton').click();page.get_by_role('button',name='退出登录',exact=True).click()
                    page.reload();page.locator('#closed').wait_for(state='visible')
                    self.assertEqual((page.locator('#closed').inner_text(),page.locator('#mode').is_visible(),page.locator('#forgot').is_visible()),('暂未开放注册',False,False))
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                asyncio.run_coroutine_threadsafe(runner.cleanup(),loop).result()
                loop.call_soon_threadsafe(loop.stop);thread.join();loop.close()


if __name__=='__main__':unittest.main()
