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

SCENARIOS={'stream':'实时：进度缺项与重连','history':'历史：旧缓存与超过60条记录','order':'顺序：A 先发，B 后补充','activity':'过程：补充分段与结束收起','keyboard':'键盘：关闭、旋转与返回','markdown':'排版：列表、折叠、代码、表格、附件'}
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

[HTML 静态页面](<D:/candidate/静态 页面 (1).html>)

[ZIP 下载](D:/candidate/sample.zip)

`[代码示例不应成为附件](D:/private.md)`
'''
def message(mid,role,text,order,**kw):return dict(id=mid,role=role,text=text,order=order,**kw)
SEED=[{'rid':'old-request','app':'codex','id':'candidate-history','started':1000,'receivedAt':2000,'state':'delivered','transport':'codex','text':'我人在外面，怎么查看？','originalText':'我人在外面，怎么查看？','body':{'text':'我人在外面，怎么查看？'}},{'rid':'unknown-request','app':'codex','id':'candidate-history','started':1500,'state':'unconfirmed','text':'这条发送没有可靠位置','originalText':'这条发送没有可靠位置','body':{'text':'这条发送没有可靠位置'}}]
def control(cid):
    return {'available':False,'questions':[{'id':'async:old-question','source_id':'old-question','source_order':20,'turn_id':'old','kind':'async','status':'answered','questions':[{'id':'0','question':'是否确认手机交互检查通过？'}],'answers':{'0':['已确认，这是测试答案']}}] if cid=='candidate-history' else [],'images':[],'queued':[]}
def resolve(body):
    return {'items':[{'request_id':rid,**({'status':'recorded','message_id':'old-source','order':10,'turn_id':'old','evidence':'source_client_id'} if rid=='old-request' and body.get('id')=='candidate-history' else {'status':'unresolved'})} for rid in body.get('request_ids',[])]}
def chat(cid,before=''):

    scene=cid.removeprefix('candidate-')
    rows=[message('u','user','这是隔离候选，仅使用测试数据。',1)]
    if scene=='history':
        rows=[message('old-source','user','我人在外面，怎么查看？',10,client_request_id='old-request'),message('old-question','assistant','是否确认手机交互检查通过？',20)]+[message('progress-'+str(i),'assistant','公开进度 '+str(i+1),30+i,phase='commentary',turn_id='old') for i in range(70)]+[message('latest-final','assistant','最新答复：下面不应出现旧问题卡或旧用户气泡。点击“加载更早消息”可在原位置查看旧记录；三点菜单中保留待核对发送记录。',900)]
        end=next((i for i,m in enumerate(rows) if m['id']==before),len(rows)) if before else len(rows);window=rows[max(0,end-60):end]
        return dict(app='codex',id=cid,title=SCENARIOS[scene],status='idle',messages=window,has_more=end>60,next_cursor=window[0]['id'] if end>60 else None)
    if scene=='activity':
        rows += [message('p1','assistant','正在检查 `dev.12`，提交号为 `93aedd4`。行内代码应与段落协调，不再显示成大按钮。',2,phase='commentary',activity_turn='fixture'),message('tool','tool','读取 示例文件.md',3,activity_turn='fixture',tool_status='completed',detail='Get-Content "示例文件.md"',result='示例内容'),message('u2','user','请同时检查手机排版。',4,time=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(NOW/1000))),message('p2','assistant','收到补充，继续检查手机排版。',5,phase='commentary',activity_turn='fixture')]
    elif scene=='stream':rows += [message('intro','assistant','点击“重放进度更新”：公开文字出现后，会模拟工具到达、快照缺项、重连及落盘；文字不应消失，也不应被旧计划替换。',2)]
    elif scene=='order':rows += [message('intro','assistant','点击上方“重放迟到记录”，观察 A 始终在 B 前面；两条文字相同也应保持独立。',2)]
    else:rows += [message('markdown','assistant',TEXT,2)]
    return dict(app='codex',id=cid,title=SCENARIOS.get(scene,'候选检查'),status='running' if scene=='activity' else 'idle',messages=rows,has_more=False,next_cursor=None,activity_turns={'fixture':dict(started_at=NOW-95000,status='running',pauses=[])},activity_current='fixture' if scene=='activity' else None)

BOOT=r'''<script>
addEventListener('load',()=>{
 const row=el('div','candidate-controls');row.style.cssText='padding:4px 12px;display:flex;gap:8px;flex-wrap:wrap;font-size:12px;background:var(--bg);flex:none';
 row.append(el('span','','隔离候选 · 不连接真实对话'));
 const live=el('button','','重放进度更新'),replay=el('button','','重放迟到记录'),end=el('button','','模拟本轮完成'),latest=el('button','','回到最新测试');latest.onclick=()=>readingUI.loadConversation(true);for(const b of [live,replay,end,latest]){b.className='tp-button';b.style.cssText='font-size:12px;min-height:44px';row.append(b);}
 document.querySelector('.cv-top').after(row);
 let replaying=false;
 live.onclick=()=>{if(!cur||replaying)return;replaying=true;clearTimeout(convTimer);readingUI.pauseStream();const target=chatKey(cur),turn='fixture';cur.status='running';interactionUI.meta({activity_current:turn,activity_turns:{fixture:{status:'running',started_at:Date.now(),pauses:[]}}});let messages=[{id:'demo-user',role:'user',text:'检查进度文字是否保留',order:0},{id:'demo-progress',role:'assistant',phase:'commentary',turn_id:turn,streaming:true,text:'这段公开进度已经显示。稍后到达的工具和短暂缺项，不应把它删掉。版本 `dev.13` 应显示为普通行内代码。',order:100}];renderMsgs(messages);
 const step=(delay,action)=>setTimeout(()=>{if(cur&&chatKey(cur)===target)action();},delay);
 step(900,()=>{messages=messageProjection.merge(messages,[{id:'demo-tool',role:'tool',turn_id:turn,text:'检查数据',detail:'git status --short',tool_status:'completed',order:200}]);renderMsgs(messages);});
 step(1800,()=>{messages=messageProjection.reconcileLive(messages,[]);codexUI.applyState(cur,{available:false,plan:{id:'unrelated-old-plan',ready:false,text:'旧计划，不应插入当前末尾'}});renderMsgs(messages);});
 step(2700,()=>{messages=messageProjection.merge(messages,[]);renderMsgs(messages);});
 step(3600,()=>{messages=messageProjection.merge(messages,[{id:'demo-progress',role:'assistant',phase:'commentary',turn_id:turn,text:'这段公开进度已经落盘。工具到达、快照缺项和重连后，它仍在原位置。版本 `dev.13` 保持普通行内代码样式。',order:100}]);renderMsgs(messages);});setTimeout(()=>{replaying=false;},3700);
 };
 replay.onclick=()=>{if(!cur||replaying)return;replaying=true;clearTimeout(convTimer);readingUI.pauseStream();const targetKey=chatKey(cur),base=[{id:'base',role:'user',text:'开始测试',order:0}];renderMsgs(base);const suffix=Date.now(),a='A-'+suffix,b='B-'+suffix;
   workspaceUI.capture(cur,{request_id:a,started:Date.now(),text:'相同文字'},{transport:'codex',originalText:'A：相同文字'});renderMsgs(base);
   workspaceUI.capture(cur,{request_id:b,started:Date.now()+1,text:'相同文字'},{transport:'codex',originalText:'B：相同文字'});renderMsgs(base);
   const B={id:'source-'+b,client_request_id:b,role:'user',text:'B：相同文字',order:20};
   setTimeout(()=>{if(cur&&chatKey(cur)===targetKey)renderMsgs([...base,B]);},1000);setTimeout(()=>{if(cur&&chatKey(cur)===targetKey)renderMsgs([...base,B,{id:'source-'+a,client_request_id:a,role:'user',text:'A：相同文字',order:10}]);replaying=false;},2200);
 };
 end.onclick=()=>{if(!cur)return;clearTimeout(convTimer);readingUI.pauseStream();cur.status='idle';interactionUI.meta({activity_turns:{fixture:{started_at:Date.now()-95000,ended_at:Date.now(),status:'completed',pauses:[]}}});renderMsgs([...currentMessages,{id:'done',role:'assistant',text:'本轮已完成。过程默认收起，手动状态优先。',order:100}]);};
 const original=window.readingUI.loadConversation;window.readingUI.loadConversation=async(...args)=>{if(replaying)return;return original(...args);};
});</script>'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8769);args=parser.parse_args()
    assets={url:((ROOT/'static'/name).read_bytes(),mime) for url,(name,mime) in STATIC_FILES.items() if (ROOT/'static'/name).is_file()}
    assets['/']=((ROOT/'remote.html').read_text(encoding='utf-8').replace('<head>','<head><script>if(!localStorage.getItem("lbr_outbox_v1"))localStorage.setItem("lbr_outbox_v1",'+json.dumps(json.dumps(SEED))+');</script>',1).replace('</body>',BOOT+'</body>').encode(),'text/html; charset=utf-8')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,body,status=200,mime='application/json; charset=utf-8'):
            raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            if urlsplit(self.path).path=='/api/chat/resolve':
                size=int(self.headers.get('Content-Length',0))
                if size>65536:return self.respond({},400)
                return self.respond(resolve(json.loads(self.rfile.read(size))))
            self.respond({'error':'隔离预览不发送消息，请使用上方的场景按钮。'},409)
        def do_GET(self):
            u=urlsplit(self.path);q=parse_qs(u.query);cid=q.get('id',['candidate-markdown'])[0]
            if u.path in assets:return self.respond(assets[u.path][0],mime=assets[u.path][1])
            if u.path=='/api/chats':return self.respond({'items':[dict(app='codex',id='candidate-'+k,title=v,updated=NOW,status='idle',folder='隔离候选') for k,v in SCENARIOS.items()],'has_more':False,'total':len(SCENARIOS)})
            if u.path=='/api/chat':return self.respond(chat(cid,q.get('before',[''])[0]))
            if u.path=='/api/codex/state':return self.respond(control(cid))
            if u.path=='/api/codex/receipt':return self.respond({'state':'unknown'})
            if u.path=='/api/chat/files':return self.respond({'items':[dict(id='fixture-image',index=0,message_id='markdown',name='image.png',kind='image',state='current'),dict(id='fixture-text',index=1,message_id='markdown',name='中文 文件 (1).md',kind='text',state='current'),dict(id='fixture-html',index=2,message_id='markdown',name='静态 页面 (1).html',kind='text',state='current'),dict(id='fixture-zip',index=3,message_id='markdown',name='sample.zip',kind='download',state='current')]})
            if u.path=='/api/file/meta':
                item={'fixture-image':('image.png','image'),'fixture-text':('中文 文件 (1).md','text'),'fixture-html':('静态 页面 (1).html','text'),'fixture-zip':('sample.zip','download')}.get(q.get('file',[''])[0])
                if not item:return self.respond({'error':'引用无效'},403)
                return self.respond({'state':'current','name':item[0],'kind':item[1]})
            if u.path=='/api/file':
                if q.get('file')==['fixture-image']:return self.respond(assets['/icon-192.png'][0],mime='image/png')
                if q.get('file')==['fixture-html']:return self.respond('<!doctype html><meta charset=utf-8><style>body{font:16px system-ui;padding:24px;color:#17395d}section{padding:20px;background:#edf4ff;border-radius:16px}</style><h1>统一候选 · HTML 附件</h1><section>可以查看页面、查看源码及下载原文件。退出后应回到原聊天位置。</section><script>document.body.textContent="不应执行"</script>'.encode(),mime='application/octet-stream')
                if q.get('file')==['fixture-zip']:return self.respond(bytes.fromhex('504b05060000000000000000000000000000000000000000'),mime='application/octet-stream')
                if q.get('file')==['fixture-text']:return self.respond('这是隔离预览文件，不读取电脑真实文件。'.encode(),mime='text/plain; charset=utf-8')
                return self.respond({'error':'引用无效'},403)
            if u.path=='/api/events':return self.respond({},404)
            if u.path.startswith('/api/'):return self.respond({})
            return self.respond({},404)
    print(f'Candidate only: http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=='__main__':main()
