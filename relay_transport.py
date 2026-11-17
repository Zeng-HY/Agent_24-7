"""Authenticated outbound WSS control + independent bounded request streams.

No arbitrary TCP proxying: each stream is a single relative HTTP request routed
only to the owning device. Separate streams preserve backpressure without a slow
download blocking unrelated SSE. Requests are never replayed after disconnect.
"""
import asyncio
from dataclasses import dataclass, field
import logging
import secrets
import time
from urllib.parse import urlsplit
from aiohttp import web, WSMsgType, WebSocketError
from relay_pages import scoped_page

CHUNK=65536
MAX_BODY=64*1024*1024
REQUEST_HEADERS=('Content-Type','Accept','Accept-Encoding','Range','If-Range','Last-Event-ID','User-Agent')
RESPONSE_HEADERS={'content-type','content-length','content-range','accept-ranges',
                  'content-disposition','etag','last-modified','content-encoding'}

# Which computer came and went, and which phone requests were turned away busy (relay_service.py keeps no access
# log). Only a computer's id tail, counts, durations and reasons: never a URL, path, cookie, key or body.
log=logging.getLogger('relay.tunnel')


def tail(device):
    """The last six characters of a computer's id, as relay_push.chat_tail writes a conversation's."""
    return '…'+str(device)[-6:]


def span(seconds):
    """'45 秒', '12 分钟', '2 小时 5 分钟' (relay_agent.format_duration's words)."""
    seconds=max(0,int(seconds))
    if seconds<60:return f'{seconds} 秒'
    if seconds<3600:return f'{seconds//60} 分钟'
    hours,minutes=divmod(seconds//60,60)
    return f'{hours} 小时' if minutes==0 else f'{hours} 小时 {minutes} 分钟'


def gone(request):
    """The phone's connection (Caddy's, for it) has closed. aiohttp runs this relay with handler_cancellation off,
    so the handler goes on after that and would keep the computer's place until the computer next sent something."""
    transport=request.transport
    return transport is None or transport.is_closing()


async def answer(ws, request, seconds):
    """The computer's next message on this stream, like wait_for(ws.receive(), seconds), except that a phone that
    hangs up meanwhile ends the wait within a second (ConnectionError)."""
    deadline=time.monotonic()+seconds
    while not gone(request):
        left=deadline-time.monotonic()
        if left<=0:raise asyncio.TimeoutError()
        try:return await asyncio.wait_for(ws.receive(),min(1,left))
        except asyncio.TimeoutError:pass
    raise ConnectionError('phone gone')


class Refused(Exception):
    """The computer answered the relay's own request with another status than 200."""
    def __init__(self, status):
        super().__init__(status)
        self.status=status


@dataclass(eq=False)
class DeviceConnection:
    device: str
    key: str
    socket: object
    streams: set = field(default_factory=set)
    since: float = field(default_factory=time.monotonic)


class TunnelHub:
    heartbeat=20  # the control link's ping (aiohttp closes it when no pong comes in half this)
    busy_window=60  # at most one "turned away busy" line a computer per this many seconds

    def __init__(self, store):
        self.store=store
        self.connections={}
        self.pending={}
        self.opened={}  # pending ident -> when it was opened (time.monotonic)
        self.active=0
        self.busy={}  # device -> [phone requests turned away since its last line, the timer that writes them]
        self.closing=False

    def allowed(self, connection, token=None):
        return (self.connections.get(connection.device) is connection and
                self.store.channel_device(connection.key)==connection.device and
                (token is None or self.store.device(token,connection.device) is not None))

    def count(self, conn):
        """Requests open on this computer's tunnel: the phones' and the relay's own (fetch) alike."""
        return sum(item[0] is conn for item in self.pending.values())

    def turn_away(self, conn):
        """The answer for a phone's request when the computer or the relay is full (503 with Retry-After, as before),
        and a line saying why, at most once a minute for each computer: the first at once, the rest counted into one
        line at the end of that minute."""
        entry=self.busy.get(conn.device)
        if entry:entry[0]+=1
        else:
            log.info('tunnel: busy %s -> 拒绝手机请求（503）：%s',tail(conn.device),self.why_busy(conn))
            self.busy[conn.device]=[0,asyncio.get_running_loop().call_later(self.busy_window,self.busy_minute,conn.device)]
        return web.HTTPServiceUnavailable(headers={'Retry-After':'2'})

    def why_busy(self, conn):
        """Which limit was reached, and how long this computer's open requests have been open: many old ones
        point to requests whose phone is long gone, many new ones to a burst."""
        mine=[(ident,item) for ident,item in self.pending.items() if item[0] is conn]
        if self.active>=256:return f'全站已开着 {self.active} 个请求，到上限 256 了；这台电脑 {len(mine)} 个'
        now=time.monotonic()
        ages=[now-self.opened[ident] for ident,_ in mine if ident in self.opened]
        old=sum(age>=60 for age in ages)
        own=sum(item[1] is None for _,item in mine)  # relay_push reading this computer's notifications (fetch)
        about=[]
        if old:about.append(f'{old} 个开了超过 1 分钟')
        if ages:about.append(f'最久的开了 {span(max(ages))}')
        if own:about.append(f'{own} 个是中转自己在读通知')
        details=f'（{"，".join(about)}）' if about else ''
        return f'这台电脑已开着 {len(mine)} 个请求，到上限 16 了{details}；全站 {self.active} 个'

    def busy_minute(self, device, last=False):
        """The end of a computer's minute: how many more were turned away. While they keep coming, the next
        minute counts them the same way."""
        refused,timer=self.busy.pop(device,(0,None))
        if timer:timer.cancel()
        if not refused:return
        conn=self.connections.get(device)
        log.info('tunnel: busy %s -> 之后 %s里又拒了 %s 个手机请求（503）；现在这台电脑开着 %s 个，全站 %s 个',
                 tail(device),span(self.busy_window),refused,self.count(conn) if conn else 0,self.active)
        if not last:
            self.busy[device]=[0,asyncio.get_running_loop().call_later(self.busy_window,self.busy_minute,device)]

    def stopping(self):
        """The relay is shutting down (relay_service's on_shutdown and close): a link that ends from now on says so,
        and the busy counts not yet written are."""
        self.closing=True
        for device in list(self.busy):self.busy_minute(device,last=True)

    def ended(self, ws, msg=None):
        """Why a computer's control link ended by itself, from what aiohttp 3.14.5 leaves on the websocket: never
        str() of an exception, whose text can carry an address."""
        if self.closing:return '中转在关闭'
        exc=ws.exception()
        if exc is None and msg is not None and msg.type==WSMsgType.ERROR:exc=msg.data
        if isinstance(exc,asyncio.TimeoutError):
            return f'心跳超时：约 {round(self.heartbeat*1.5)} 秒没收到电脑的任何消息'
        if isinstance(exc,WebSocketError):return f'电脑发来的消息不对（{exc.code}）'
        if msg is not None and msg.type!=WSMsgType.ERROR:return '电脑发来的消息不对'
        if isinstance(exc,ConnectionError) or exc is None and ws.close_code in (None,1006):
            return '连接被掐断，没收到关闭信号（网络、代理或 Caddy 断了）'
        if exc is not None:return f'出错（{type(exc).__name__}）'
        return f'电脑关闭了连接（{ws.close_code}）'

    async def disconnect(self, device, reason='中转断开了这条连接'):
        conn=self.connections.pop(device,None)
        if conn:
            open_now=self.count(conn)
            log.info('tunnel: drop %s -> 电脑断开了（%s），这次连了 %s%s',tail(device),reason,
                     span(time.monotonic()-conn.since),f'，断开时开着 {open_now} 个请求' if open_now else '')
            async def close(ws):
                try:await asyncio.wait_for(ws.close(code=1008),1)
                except (TimeoutError,ConnectionError):pass
            await asyncio.gather(*(close(ws) for ws in [*conn.streams,conn.socket]),return_exceptions=True)

    async def control(self, request):
        authorization=request.headers.get('Authorization','')
        key=authorization[7:] if authorization.startswith('Bearer ') else ''
        device=self.store.channel_device(key)
        if not device: raise web.HTTPUnauthorized()
        await self.disconnect(device,'同一台电脑又连了一条新的，换下旧的这条')
        ws=web.WebSocketResponse(heartbeat=self.heartbeat,max_msg_size=16384,compress=False)
        await ws.prepare(request)
        conn=DeviceConnection(device,key,ws)
        self.connections[device]=conn
        log.info('tunnel: connect %s -> 电脑连上了',tail(device))
        why=None
        try:
            async for msg in ws:
                if not self.allowed(conn):
                    why='这台电脑的钥匙已经不能用（被移除或重新绑定）';break
                if msg.type==WSMsgType.TEXT and msg.data=='ready': continue
                why=self.ended(ws,msg);break
        finally:
            if self.connections.get(device) is conn:
                await self.disconnect(device,'中转在关闭' if self.closing else why or self.ended(ws))
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

    async def fetch(self, device, target, headers=None):
        """A GET of the relay's own on this computer's tunnel (relay_push.py's event stream): the body's chunks as
        they come, until the computer ends it or goes away. Not on a phone's behalf, so no sign-in is checked and
        no usage counted; it takes one of the computer's 16 places while open. Close it with aclose()."""
        conn=self.connections.get(device)
        if not conn or not self.allowed(conn): raise ConnectionError('device offline')
        if self.count(conn)>=16: raise ConnectionError('device busy')
        ident=secrets.token_hex(16)
        future=asyncio.get_running_loop().create_future()
        self.pending[ident]=(conn,None,future)
        self.opened[ident]=time.monotonic()
        ws=finished=None
        try:
            await conn.socket.send_json({'v':1,'stream':ident})
            ws,finished=await asyncio.wait_for(future,15)
            conn.streams.add(ws)
            await ws.send_json({'v':1,'method':'GET','target':target,'headers':dict(headers or {}),'length':None})
            await ws.send_json({'end':True})
            message=await asyncio.wait_for(ws.receive(),120)
            if message.type!=WSMsgType.TEXT: raise ConnectionError()
            metadata=message.json()
            status=metadata.get('status') if isinstance(metadata,dict) else None
            if status!=200: raise Refused(status if isinstance(status,int) else 502)
            while self.allowed(conn):
                # the computer sends a keepalive every 45 s (ntfy_feed.KEEPALIVE)
                message=await asyncio.wait_for(ws.receive(),150)
                if message.type==WSMsgType.BINARY: yield message.data
                elif message.type==WSMsgType.TEXT and message.json().get('end'): return
                else: raise ConnectionError()
            raise ConnectionError('device gone')
        finally:
            self.pending.pop(ident,None)
            self.opened.pop(ident,None)
            if ws:
                conn.streams.discard(ws)
                await ws.close()
            if finished: finished.set()

    async def proxy(self, request, token, device, target):
        conn=self.connections.get(device)
        if not conn or not self.allowed(conn,token): raise web.HTTPServiceUnavailable(text='电脑未连接')
        # 16 at a time per computer (an open chat holds one for as long as it is open); 256 in all
        if self.active>=256 or self.count(conn)>=16: raise self.turn_away(conn)
        self.active+=1
        ident=secrets.token_hex(16)
        future=asyncio.get_running_loop().create_future()
        self.pending[ident]=(conn,token,future)
        self.opened[ident]=started=time.monotonic()
        ws=finished=upload=None
        uploaded=downloaded=0
        response=None
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
            message=await answer(ws,request,120)
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
                    chunk=await answer(ws,request,120)
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
                if gone(request): raise ConnectionError('phone gone')  # give its place back now, not at the next chunk
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
            self.opened.pop(ident,None)
            if upload:
                upload.cancel()
                await asyncio.gather(upload,return_exceptions=True)
            if ws:
                conn.streams.discard(ws)
                await ws.close()
            if finished: finished.set()
            self.active-=1
            self.store.usage(device,uploaded,downloaded,1)
