"""Fixture-only preview. No production config, accounts, filesystem routes or real sessions."""
import argparse,base64,json,mimetypes
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from artifact_preview_check import ROOT,PAGE,HTML,ATTACK,PNG

def pdf():
    objects=[b'<</Type/Catalog/Pages 2 0 R>>',b'<</Type/Pages/Kids[3 0 R]/Count 1>>',b'<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R>>',b'<</Length 28>>\nstream\n0 0 1 rg 30 30 200 200 re f\nendstream']
    result=b'%PDF-1.4\n';offsets=[0]
    for i,o in enumerate(objects,1):offsets.append(len(result));result+=str(i).encode()+b' 0 obj\n'+o+b'\nendobj\n'
    start=len(result);result+=b'xref\n0 5\n0000000000 65535 f \n'+b''.join(f'{x:010} 00000 n \n'.encode() for x in offsets[1:])+b'trailer\n<</Size 5/Root 1 0 R>>\nstartxref\n'+str(start).encode()+b'\n%%EOF'
    return result

FILES={
 'html':('中文 空格（括号）.html',HTML.encode(),'text'),
 'relative':('relative.html',b'<h1>Relative resources</h1><link rel="stylesheet" href="style.css"><img src="img.png"><img src="unprovided.png">','text'),
 'css':('style.css',b'h1{color:#2563eb}','text'),'img':('img.png',PNG,'image'),
 'md':('阅读说明.md','# 阅读视图\n\n**粗体**与段落。\n\n|项目|状态|\n|---|---|\n|附件|候选|'.encode(),'text'),
 'txt':('代码.json','{"内容":"<script>不会执行</script>","状态":"候选"}'.encode(),'text'),
 'pdf':('示例.pdf',pdf(),'pdf'),'zip':('示例.zip',bytes.fromhex('504b05060000000000000000000000000000000000000000'),'download'),
 'attack':('隔离测试.html',ATTACK.encode(),'text'),'empty':('空文件.txt',b'','text'),
 'large':('大文本.txt',b'large fixture\n'*(100000),'text'),
 'bad':('损坏图片.png',b'not an image','image'),'updated':('已更新.html',b'<h1>Current updated content</h1>','text'),
 'missing':('已删除.html',b'','text'),'expired':('登录失效.html',b'','text')}
EXTRA='''<p>选择附件测试页面、源码、下载与返回。PDF 能否内嵌显示由浏览器决定，可随时下载。</p><div id="samples" style="display:flex;flex-wrap:wrap;gap:8px"></div><p><button id="theme">切换深浅色</button></p><script>const samples=LIST;for(const [id,name] of samples){const b=document.createElement('button');b.className='tp-button';b.textContent=name;b.onclick=()=>artifactPreview.open({app:'codex',id:'fixture'},{id,name,path:'C:/fixture/'+(id==='relative'?'relative.html':name)});document.querySelector('#samples').append(b)}document.querySelector('#theme').onclick=()=>document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';</script>'''
HOME=PAGE.replace('</body>','').replace('<div style="height:1300px"></div>','').replace('</script>', '</script>',1)+EXTRA.replace('LIST',json.dumps([(k,v[0]) for k,v in FILES.items() if k not in ('css',)],ensure_ascii=False))

class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        u=urlsplit(self.path);q=parse_qs(u.query);path=u.path
        def send(body,mime='application/json',status=200,download=None):
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            if download:
                from urllib.parse import quote
                self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(download))
            self.end_headers();self.wfile.write(body)
        if path=='/':return send(HOME.encode(),'text/html; charset=utf-8')
        allowed={'theme.css','artifact-preview.css','artifact-preview.js','purify.min.js','markdown-it.min.js'}
        if path.startswith('/static/') and path[8:] in allowed:
            f=ROOT/'static'/path[8:];return send(f.read_bytes(),mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
        if path.startswith('/api/'):
            if q.get('id')!=['fixture']:return send(b'{"error":"fixture only"}',status=403)
            if path=='/api/chat/files':return send(json.dumps({'items':[{'id':k,'path':'C:/fixture/'+v[0]} for k,v in FILES.items() if k in ('css','img')]}).encode())
            fid=q.get('file',[''])[0]
            if fid not in FILES:return send(b'{"error":"unknown reference"}',status=403)
            if fid in ('missing','expired'):return send(b'{"error":"fixture failure"}',status=404 if fid=='missing' else 401)
            name,data,kind=FILES[fid]
            if path=='/api/file/meta':return send(json.dumps({'name':name,'kind':kind,'size':65<<20 if fid=='huge' else len(data),'updated':fid=='updated'}).encode())
            if path=='/api/file':return send(data,'application/octet-stream',download=name)
        send(b'Not found','text/plain',404)

if __name__=='__main__':
    args=argparse.ArgumentParser();args.add_argument('--host',default='127.0.0.1');args.add_argument('--port',type=int,default=8770);a=args.parse_args()
    print(f'Fixture preview http://{a.host}:{a.port}',flush=True);ThreadingHTTPServer((a.host,a.port),Fixture).serve_forever()
