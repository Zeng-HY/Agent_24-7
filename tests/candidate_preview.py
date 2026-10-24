"""Phone candidate server: synthetic data only, no desktop bridge or credentials.

Run explicitly on a private interface: python tests/candidate_preview.py --host IP
All assets are snapshotted in memory at startup; no production services are replaced.
"""
import argparse,json,mimetypes,time,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from remote import STATIC_FILES

SCENARIOS={'order':'顺序：A 先发，B 后补充','activity':'过程：补充分段与结束收起','keyboard':'键盘：关闭、旋转与返回','markdown':'排版：列表、折叠、代码、表格、附件'}
NOW=int(time.time()*1000)
TEXT='''# 候选阅读检查

普通正文与 **强调**。这段正文应该自然换行。

- 列表第一项
- 列表第二项
  - 嵌套项目

> 引用中的文字。

<details><summary>展开说明</summary>

展开后直接阅读。刷新内容不应重置手动展开状态。

</details>

```powershell
Get-Content "D:/示例项目/很长的路径/文件名 (1).txt"
'''+('long-command-'*30)+'''
```

| 列一 | 列二 | 列三 |
| --- | --- | --- |
| '''+('wide-table-'*25)+''' | 内容 | 内容 |

![测试图片](D:/candidate/image.png)

[测试文件](<D:/candidate/中文 文件 (1).md>)

`[代码示例不应成为附件](D:/private.md)`
'''
def message(mid,role,text,order,**kw):return dict(id=mid,role=role,text=text,order=order,**kw)
def chat(cid):
    scene=cid.removeprefix('candidate-')
    rows=[message('u','user','这是隔离候选，仅使用测试数据。',1)]
    if scene=='activity':
        rows += [message('p1','assistant','正在检查第一部分。',2,phase='commentary',activity_turn='fixture'),message('tool','tool','读取 示例文件.md',3,activity_turn='fixture',tool_status='completed',detail='Get-Content "示例文件.md"',result='示例内容'),message('u2','user','请同时检查手机排版。',4,time=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(NOW/1000))),message('p2','assistant','收到补充，继续检查手机排版。',5,phase='commentary',activity_turn='fixture')]
    elif scene=='order':rows += [message('intro','assistant','点击上方“重放迟到记录”，观察 A 始终在 B 前面；两条文字相同也应保持独立。',2)]
    else:rows += [message('markdown','assistant',TEXT,2)]
    return dict(app='codex',id=cid,title=SCENARIOS.get(scene,'候选检查'),status='running' if scene=='activity' else 'idle',messages=rows,has_more=False,next_cursor=None,activity_turns={'fixture':dict(started_at=NOW-95000,status='running',pauses=[])},activity_current='fixture' if scene=='activity' else None)

BOOT=r'''<script>
addEventListener('load',()=>{
 const row=el('div','candidate-controls');row.style.cssText='padding:4px 12px;display:flex;gap:8px;flex-wrap:wrap;font-size:12px;background:var(--bg);flex:none';
 row.append(el('span','','隔离候选 · 不连接真实对话'));
 const replay=el('button','','重放迟到记录'),end=el('button','','模拟本轮完成');for(const b of [replay,end]){b.className='tp-button';b.style.cssText='font-size:12px;min-height:44px';row.append(b);}
 document.querySelector('.cv-top').after(row);
 let replaying=false;
 replay.onclick=()=>{if(!cur||replaying)return;replaying=true;clearTimeout(convTimer);readingUI.pauseStream();const base=[{id:'base',role:'user',text:'开始测试',order:0}];renderMsgs(base);const suffix=Date.now(),a='A-'+suffix,b='B-'+suffix;
   workspaceUI.capture(cur,{request_id:a,started:Date.now(),text:'相同文字'},{transport:'codex',originalText:'A：相同文字'});renderMsgs(base);
   workspaceUI.capture(cur,{request_id:b,started:Date.now()+1,text:'相同文字'},{transport:'codex',originalText:'B：相同文字'});renderMsgs(base);
   const B={id:'source-'+b,client_request_id:b,role:'user',text:'B：相同文字',order:20};
   setTimeout(()=>renderMsgs([...base,B]),1000);setTimeout(()=>{renderMsgs([...base,B,{id:'source-'+a,client_request_id:a,role:'user',text:'A：相同文字',order:10}]);replaying=false;},2200);
 };
 end.onclick=()=>{if(!cur)return;clearTimeout(convTimer);readingUI.pauseStream();cur.status='idle';interactionUI.meta({activity_turns:{fixture:{started_at:Date.now()-95000,ended_at:Date.now(),status:'completed',pauses:[]}}});renderMsgs([...currentMessages,{id:'done',role:'assistant',text:'本轮已完成。过程默认收起，手动状态优先。',order:100}]);};
 const original=window.readingUI.loadConversation;window.readingUI.loadConversation=async(...args)=>{if(replaying)return;return original(...args);};
});</script>'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8769);args=parser.parse_args()
    assets={url:((ROOT/'static'/name).read_bytes(),mime) for url,(name,mime) in STATIC_FILES.items() if (ROOT/'static'/name).is_file()}
    assets['/']=((ROOT/'remote.html').read_text(encoding='utf-8').replace('</body>',BOOT+'</body>').encode(),'text/html; charset=utf-8')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,body,status=200,mime='application/json; charset=utf-8'):
            raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_POST(self):self.respond({'error':'隔离预览不发送消息，请使用上方的场景按钮。'},409)
        def do_GET(self):
            u=urlsplit(self.path);q=parse_qs(u.query);cid=q.get('id',['candidate-markdown'])[0]
            if u.path in assets:return self.respond(assets[u.path][0],mime=assets[u.path][1])
            if u.path=='/api/chats':return self.respond({'items':[dict(app='codex',id='candidate-'+k,title=v,updated=NOW,status='idle',folder='隔离候选') for k,v in SCENARIOS.items()],'has_more':False,'total':4})
            if u.path=='/api/chat':return self.respond(chat(cid))
            if u.path=='/api/codex/state':return self.respond({'available':False,'reason':'隔离候选，不连接电脑控制','questions':[],'images':[],'queued':[]})
            if u.path=='/api/codex/receipt':return self.respond({'state':'unknown'})
            if u.path=='/api/chat/files':return self.respond({'items':[dict(id='fixture-image',index=0,message_id='markdown',name='image.png',kind='image',state='current'),dict(id='fixture-text',index=1,message_id='markdown',name='中文 文件 (1).md',kind='text',state='current')]})
            if u.path=='/api/file/meta':return self.respond({'state':'current'})
            if u.path=='/api/file':
                if q.get('file')==['fixture-image']:return self.respond(assets['/icon-192.png'][0],mime='image/png')
                if q.get('file')==['fixture-text']:return self.respond('这是隔离预览文件，不读取电脑真实文件。'.encode(),mime='text/plain; charset=utf-8')
                return self.respond({'error':'引用无效'},403)
            if u.path=='/api/events':return self.respond({},404)
            if u.path.startswith('/api/'):return self.respond({})
            return self.respond({},404)
    print(f'Candidate only: http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=='__main__':main()
