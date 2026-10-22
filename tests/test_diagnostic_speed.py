"""Browser checks for optional timings; fake transport, no desktop/model actions."""
import re
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = re.search(r'<script id="diagnostic-speed">(.*?)</script>',
                   (ROOT/'remote.html').read_text(encoding='utf-8'), re.S).group(1)
HTML = '''<html><meta charset="utf-8"><body><div id="settingsBody"></div><script>
window.calls=[];window.notices=[];window.replyMode='ok';
window.toast=(message)=>notices.push(message);
window.fetch=async(input,init)=>{
 calls.push({input:String(input),method:init?.method||'GET'});
 await new Promise(r=>setTimeout(r,25));
 if(replyMode==='network')throw new TypeError('private error details');
 if(replyMode==='abort')throw new DOMException('cancel','AbortError');
 const body=replyMode==='business'?{ok:false,error:'private message'}:{ok:true};
 return new Response(JSON.stringify(body),{status:replyMode==='http'?401:200,headers:{'Content-Type':'application/json'}});
};
</script><script>''' + SCRIPT + '</script></body></html>'


class DiagnosticSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':390,'height':844})
        self.page=self.context.new_page()
        self.errors=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.route('http://diagnostic.test/**',lambda route:route.fulfill(body=HTML,content_type='text/html'))
        self.page.goto('http://diagnostic.test/')

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.context.close()

    def enable(self):
        self.page.locator('#diagnosticSpeedSwitch').check()

    def upload(self):
        return self.page.evaluate("""async()=>{try{const r=await fetch('/api/codex/upload?name=private-name&id=private-id',
        {method:'POST',body:new Blob([new Uint8Array(1000)])});return await r.json();}catch(e){return {thrown:e.name};}}""")

    def test_off_has_no_records_or_extra_requests(self):
        self.assertEqual(self.upload(),{'ok':True})
        self.assertEqual(self.page.locator('#diagnosticResults').inner_text(),'')
        self.assertEqual(self.page.evaluate('calls.length'),1)
        self.assertTrue(self.page.locator('#diagnosticProbe').is_disabled())

    def test_upload_result_privacy_and_clear(self):
        self.enable();self.assertEqual(self.upload(),{'ok':True})
        self.page.wait_for_function("document.querySelector('#diagnosticResults').textContent.includes('图片上传')")
        text=self.page.locator('#diagnosticResults').inner_text()
        self.assertIn('请求完成',text);self.assertIn('0.00 MB',text)
        self.assertNotIn('private',text)
        self.page.get_by_text('清空记录',exact=True).click()
        self.assertNotIn('图片上传：',self.page.locator('#diagnosticResults').inner_text())

    def test_failure_semantics_preserved(self):
        self.enable()
        for mode,expected in [('business','服务端未成功'),('http','HTTP 401'),('network','网络失败'),('abort','已取消或超时')]:
            self.page.evaluate('(mode)=>replyMode=mode',mode)
            result=self.upload()
            self.page.wait_for_function('(s)=>document.querySelector("#diagnosticResults").textContent.includes(s)',arg=expected)
            if mode=='network':self.assertEqual(result,{'thrown':'TypeError'})
            if mode=='abort':self.assertEqual(result,{'thrown':'AbortError'})
            self.assertNotIn('private',self.page.locator('#diagnosticResults').inner_text())

    def test_probe_three_small_gets_only(self):
        self.enable();self.page.locator('#diagnosticProbe').click()
        self.page.wait_for_function("document.querySelector('#diagnosticResults').textContent.includes('连接请求 3/3')")
        self.assertEqual(self.page.evaluate('calls'),[{'input':'/api/status','method':'GET'}]*3)

    def test_toggle_persists_but_records_do_not(self):
        self.enable();self.upload()
        self.page.reload()
        self.assertTrue(self.page.locator('#diagnosticSpeedSwitch').is_checked())
        self.assertNotIn('图片上传：',self.page.locator('#diagnosticResults').inner_text())
        self.page.locator('#diagnosticSpeedSwitch').uncheck()
        self.upload()
        self.assertEqual(self.page.locator('#diagnosticResults').inner_text(),'')


if __name__=='__main__':unittest.main()
