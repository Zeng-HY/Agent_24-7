"""Outbound HTTPS-only device agent. No listening public port or frpc process."""
import asyncio
import contextlib
import json
import random
from urllib.parse import urlsplit
from aiohttp import ClientSession, ClientTimeout, WSMsgType
from relay_transport import CHUNK, MAX_BODY, REQUEST_HEADERS, RESPONSE_HEADERS
from relay_service import clean_target


class Agent:
    def __init__(self, origin, key, backend_port, backend_token, *, test_http=False, state=None):
        parsed=urlsplit(origin)
        if parsed.scheme!=('http' if test_http else 'https') or not parsed.netloc or parsed.path or parsed.username:
            raise ValueError('HTTPS origin required')
        self.origin,self.key=origin,key
        self.port,self.token=int(backend_port),backend_token
        self.state=state or (lambda value:None)
        self.tasks=set()
        self.stopping=False

    async def stream(self, client, ident):
        async with client.ws_connect(self.origin+'/tunnel/stream/'+ident,
                headers={'Authorization':'Bearer '+self.key,'Origin':self.origin},heartbeat=20,
                max_msg_size=CHUNK+16384,compress=0) as ws:
            sent=False
            try:
                message=await asyncio.wait_for(ws.receive(),15)
                if message.type!=WSMsgType.TEXT: return
                meta=message.json()
                if meta.get('v')!=1 or meta.get('method') not in ('GET','HEAD','POST'): return
                target=clean_target(meta['target'])
                if urlsplit(target).path.startswith(('/account','/relay/','/tunnel/','/device-auth/')): return
                length=meta.get('length')
                if length is not None and (not isinstance(length,int) or not 0<=length<=MAX_BODY): return
                headers={k:v for k,v in meta.get('headers',{}).items() if k in REQUEST_HEADERS and isinstance(v,str)}
                headers.update({'Host':'127.0.0.1:'+str(self.port),'Cookie':'lbr='+self.token})
                if length is not None and meta['method']=='POST': headers['Content-Length']=str(length)
                async def body():
                    size=0
                    while True:
                        chunk=await asyncio.wait_for(ws.receive(),120)
                        if chunk.type==WSMsgType.BINARY:
                            size+=len(chunk.data)
                            if size>MAX_BODY: raise ValueError('size limit')
                            yield chunk.data
                        elif chunk.type==WSMsgType.TEXT and chunk.json().get('end'):
                            if length is not None and size!=length: raise ValueError('incomplete body')
                            return
                        else: raise ConnectionError()
                if meta['method']!='POST':
                    async for chunk in body():
                        if chunk: raise ValueError('body on read request')
                async with client.request(meta['method'],'http://127.0.0.1:'+str(self.port)+target,
                        data=body() if meta['method']=='POST' else None,headers=headers,allow_redirects=False) as response:
                    await ws.send_json({'status':response.status,'headers':{k:v for k,v in response.headers.items() if k.lower() in RESPONSE_HEADERS}})
                    sent=True
                    if meta['method']!='HEAD':
                        async for chunk in response.content.iter_chunked(CHUNK):
                            await asyncio.wait_for(ws.send_bytes(chunk),120)
                    await ws.send_json({'end':True})
            except (Exception,asyncio.CancelledError):
                if not sent and not ws.closed:
                    with contextlib.suppress(Exception):
                        await ws.send_json({'status':502,'headers':{}})
                        await ws.send_json({'end':True})
                raise

    def finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled(): task.exception()  # Never log URLs, credentials or payloads.

    async def once(self, client):
        async with client.ws_connect(self.origin+'/tunnel/connect',
                headers={'Authorization':'Bearer '+self.key,'Origin':self.origin},heartbeat=20,
                max_msg_size=16384,compress=0) as ws:
            self.state('online')
            await ws.send_str('ready')
            try:
                async for message in ws:
                    if message.type!=WSMsgType.TEXT: break
                    data=message.json()
                    ident=data.get('stream','')
                    if data.get('v')!=1 or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident): break
                    if len(self.tasks)>=32: continue  # busy: this request fails; the tunnel and the others carry on
                    task=asyncio.create_task(self.stream(client,ident))
                    self.tasks.add(task);task.add_done_callback(self.finished)
            finally:
                for task in list(self.tasks): task.cancel()
                await asyncio.gather(*list(self.tasks),return_exceptions=True)
                self.state('offline')

    async def run(self):
        delay=1
        async with ClientSession(timeout=ClientTimeout(total=None,sock_connect=15,sock_read=120),
                                 auto_decompress=False,trust_env=False) as client:
            while not self.stopping:
                started=asyncio.get_running_loop().time()
                try: await self.once(client)
                except asyncio.CancelledError: raise
                except Exception: self.state('reconnecting')
                if asyncio.get_running_loop().time()-started>60: delay=1
                await asyncio.sleep(random.uniform(.8,1.2)*delay)
                delay=min(delay*2,60)
