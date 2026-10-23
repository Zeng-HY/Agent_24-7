"""Authenticated outbound WSS control + independent bounded request streams.

No arbitrary TCP proxying: each stream is a single relative HTTP request routed
only to the owning device. Separate streams preserve backpressure without a slow
download blocking unrelated SSE. Requests are never replayed after disconnect.
"""
import asyncio
from dataclasses import dataclass, field
import secrets
import time
from urllib.parse import urlsplit
from aiohttp import web, WSMsgType
from relay_pages import scoped_page

CHUNK=65536
MAX_BODY=64*1024*1024
REQUEST_HEADERS=('Content-Type','Accept','Range','If-Range','Last-Event-ID','User-Agent')
RESPONSE_HEADERS={'content-type','content-length','content-range','accept-ranges',
                  'content-disposition','etag','last-modified','content-encoding'}


@dataclass(eq=False)
class DeviceConnection:
    device: str
    key: str
    socket: object
    streams: set = field(default_factory=set)


class TunnelHub:
    def __init__(self, store):
        self.store=store
        self.connections={}
        self.pending={}
        self.active=0

    def allowed(self, connection, token=None):
        return (self.connections.get(connection.device) is connection and
                self.store.channel_device(connection.key)==connection.device and
                (token is None or self.store.device(token,connection.device) is not None))

    async def disconnect(self, device):
        conn=self.connections.pop(device,None)
        if conn:
            async def close(ws):
                try:await asyncio.wait_for(ws.close(code=1008),1)
                except (TimeoutError,ConnectionError):pass
            await asyncio.gather(*(close(ws) for ws in [*conn.streams,conn.socket]),return_exceptions=True)

    async def control(self, request):
        authorization=request.headers.get('Authorization','')
        key=authorization[7:] if authorization.startswith('Bearer ') else ''
        device=self.store.channel_device(key)
        if not device: raise web.HTTPUnauthorized()
        await self.disconnect(device)
        ws=web.WebSocketResponse(heartbeat=20,max_msg_size=16384,compress=False)
        await ws.prepare(request)
        conn=DeviceConnection(device,key,ws)
        self.connections[device]=conn
        try:
            async for msg in ws:
                if not self.allowed(conn): break
                if msg.type==WSMsgType.TEXT and msg.data=='ready': continue
                break
        finally:
            if self.connections.get(device) is conn: await self.disconnect(device)
        return ws

    async def stream(self, request):
        ident=request.match_info['stream']
        item=self.pending.get(ident)
        if not item: raise web.HTTPNotFound()
        conn,token,future=item
        authorization=request.headers.get('Authorization','')
        key=authorization[7:] if authorization.startswith('Bearer ') else ''
        if self.store.channel_device(key)!=conn.device or not self.allowed(conn,token) or future.done():
            raise web.HTTPForbidden()
        ws=web.WebSocketResponse(heartbeat=20,max_msg_size=CHUNK+16384,compress=False)
        await ws.prepare(request)
        if future.done() or not self.allowed(conn,token):
            await ws.close(code=1008)
            return ws
        finished=asyncio.Event()
        future.set_result((ws,finished))
        # The HTTP request task exclusively reads this websocket.
        await finished.wait()
        return ws

    async def proxy(self, request, token, device, target):
        conn=self.connections.get(device)
        if not conn or not self.allowed(conn,token): raise web.HTTPServiceUnavailable(text='电脑未连接')
        # 16 at a time per computer (an open chat holds one for as long as it is open); 256 in all
        if self.active>=256 or sum(item[0] is conn for item in self.pending.values())>=16: raise web.HTTPServiceUnavailable(headers={'Retry-After':'2'})
        self.active+=1
        ident=secrets.token_hex(16)
        future=asyncio.get_running_loop().create_future()
        self.pending[ident]=(conn,token,future)
        ws=finished=upload=None
        uploaded=downloaded=0
        response=None
        started=time.monotonic()
        try:
            await conn.socket.send_json({'v':1,'stream':ident})
            ws,finished=await asyncio.wait_for(future,15)
            conn.streams.add(ws)
            await ws.send_json({'v':1,'method':request.method,'target':target,
                'headers':{k:request.headers[k] for k in REQUEST_HEADERS if k in request.headers},
                'length':request.content_length})
            async def send_body():
                nonlocal uploaded
                async for chunk in request.content.iter_chunked(CHUNK):
                    if not self.allowed(conn,token): raise PermissionError()
                    uploaded+=len(chunk)
                    if uploaded>MAX_BODY: raise ValueError('upload limit')
                    await asyncio.wait_for(ws.send_bytes(chunk),120)
                await ws.send_json({'end':True})
            upload=asyncio.create_task(send_body())
            message=await asyncio.wait_for(ws.receive(),120)
            if message.type!=WSMsgType.TEXT: raise ConnectionError()
            metadata=message.json()
            if not isinstance(metadata,dict) or not isinstance(metadata.get('headers',{}),dict):raise ValueError('invalid response')
            status=metadata.get('status')
            if not isinstance(status,int) or not 200<=status<=599: raise ValueError('invalid status')
            if not self.allowed(conn,token): raise PermissionError()
            if status in (502,503,504) and request.method=='GET' and (request.headers.get('Sec-Fetch-Mode')=='navigate' or 'text/html' in request.headers.get('Accept','')):
                raise web.HTTPServiceUnavailable(text='电脑连接中断，请重试')
            headers={k:v for k,v in metadata.get('headers',{}).items() if k.lower() in RESPONSE_HEADERS and isinstance(v,str)}
            headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','X-Agent-Remote-Transport':'wss'})
            if request.method=='GET' and urlsplit(target).path in ('/','/input-diagnostics') and any(k.lower()=='content-type' and 'text/html' in v for k,v in headers.items()):
                page=bytearray()
                while self.allowed(conn,token):
                    chunk=await asyncio.wait_for(ws.receive(),120)
                    if chunk.type==WSMsgType.BINARY:
                        page.extend(chunk.data)
                        if len(page)>2*1024*1024: raise ValueError('page limit')
                    elif chunk.type==WSMsgType.TEXT and chunk.json().get('end'):
                        await upload
                        page_body=scoped_page(bytes(page),device)
                        downloaded=len(page_body)
                        return web.Response(body=page_body,content_type='text/html',headers={'Cache-Control':'no-store','X-Agent-Remote-Transport':'wss'})
                    else: raise ConnectionError()
                raise PermissionError()
            response=web.StreamResponse(status=status,headers=headers)
            if status>=400 and not upload.done():
                upload.cancel()
                response.force_close()
            await response.prepare(request)
            while self.allowed(conn,token):
                if upload.done() and not upload.cancelled() and upload.exception(): raise upload.exception()
                try: message=await asyncio.wait_for(ws.receive(),1)
                except asyncio.TimeoutError:
                    if time.monotonic()-started>86400: break
                    continue
                if not self.allowed(conn,token): raise PermissionError()
                if message.type==WSMsgType.BINARY:
                    if request.method!='HEAD':
                        await asyncio.wait_for(response.write(message.data),120)
                        downloaded+=len(message.data)
                elif message.type==WSMsgType.TEXT and message.json().get('end'):
                    if not upload.cancelled():await upload
                    await response.write_eof()
                    return response
                else: raise ConnectionError()
            raise PermissionError()
        except (TimeoutError,ValueError,ConnectionError,PermissionError,RuntimeError):
            if response is not None and response.prepared:
                if request.transport: request.transport.close()
                return response
            raise web.HTTPBadGateway(text='连接中断，请检查电脑状态') from None
        finally:
            self.pending.pop(ident,None)
            if upload:
                upload.cancel()
                await asyncio.gather(upload,return_exceptions=True)
            if ws:
                conn.streams.discard(ws)
                await ws.close()
            if finished: finished.set()
            self.active-=1
            self.store.usage(device,uploaded,downloaded,1)
