"""Outbound HTTPS-only device agent. No listening public port or frpc process."""
import asyncio
import contextlib
import json
import random
import time
from urllib.parse import urlsplit
from aiohttp import (ClientSession, ClientTimeout, WSMsgType, ClientResponseError, ClientSSLError,
                     ClientConnectorError, ConnectionTimeoutError, ServerTimeoutError, WSServerHandshakeError)
from relay_transport import CHUNK, MAX_BODY, REQUEST_HEADERS, RESPONSE_HEADERS
from relay_service import clean_target


REPORT_INTERVAL=600  # seconds between "still not connected" lines while the relay is unreachable


def format_duration(seconds):
    seconds=max(0,int(seconds))
    if seconds<60:return f'{seconds} 秒'
    if seconds<3600:return f'{seconds//60} 分钟'
    hours,minutes=divmod(seconds//60,60)
    return f'{hours} 小时' if minutes==0 else f'{hours} 小时 {minutes} 分钟'


def exception_reason(exc):
    """What to write for an exception. Never str(exc): aiohttp's text carries the URL, and a URL can carry a key."""
    if isinstance(exc,ConnectionTimeoutError):return f'连中转超时（{type(exc).__name__}）'
    if type(exc) is ServerTimeoutError:return '中转没回应心跳（心跳超时）'
    if isinstance(exc,asyncio.TimeoutError):return f'连中转超时（{type(exc).__name__}）'
    if isinstance(exc,ClientSSLError):return f'和中转的加密连接出错（{type(exc).__name__}）'
    if isinstance(exc,WSServerHandshakeError):return f'中转没接受连接（HTTP {exc.status}）'
    if isinstance(exc,ClientConnectorError):return f'连不上中转（{type(exc).__name__}）'
    if isinstance(exc,ClientResponseError):return f'中转没接受连接（HTTP {exc.status}）'
    return type(exc).__name__


def close_reason(ws):
    """Why the control websocket ended, from its exception and close code (aiohttp 3.14.5)."""
    exc=ws.exception()
    if exc is not None:return exception_reason(exc)
    code=ws.close_code
    if code==1000:return '中转正常关闭（1000）'
    if code==1001:return '中转那边在关闭（1001）'
    if code==1008:return '中转关掉了这条连接（1008：中转重启、同一台电脑又连了一条，或被撤销、重新绑定）'
    if code in (1006,None):return '连接被掐断，没收到关闭信号（1006）'
    return f'中转关闭了连接（代码 {code}）'


class LinkLog:
    """The relay link's history across every Agent of one program run (the controller owns it)."""
    def __init__(self, write, clock=time.monotonic):
        self._write=write;self._clock=clock
        self._ever_connected=False;self._connected_at=None
        self._since=None;self._attempts=0;self._last_reason=''
        self._next_report=None

    def write(self,text):
        try:self._write(text)
        except Exception:pass  # a log line must never break the connection

    def attempt(self):
        """One more connection attempt started after a disconnect (the successful one counts too)."""
        if self._since is not None:self._attempts+=1

    def connected(self):
        now=self._clock()
        if not self._ever_connected:
            self._ever_connected=True
            self.write('中转：连上了')
        elif self._since is not None:
            self.write(f'中转：重新连上了（断了 {format_duration(now-self._since)}，重连 {self._attempts} 次）')
        self._connected_at=now;self._since=None;self._next_report=None

    def lost(self,reason):
        now=self._clock()
        connected_at=self._connected_at if self._connected_at is not None else now
        self.write(f'中转：断开了（{reason}），这次连了 {format_duration(now-connected_at)}')
        self._connected_at=None;self._since=now;self._attempts=0
        self._last_reason=reason;self._next_report=now+REPORT_INTERVAL

    def stopped(self):
        """The controller itself ended a live connection (local-service restart or rebind): start the outage clock,
        write no line (line 9/7/8 already says why). An outage that is already running keeps its start."""
        if self._since is not None:return
        now=self._clock()
        self._connected_at=None;self._since=now;self._attempts=0
        self._next_report=now+REPORT_INTERVAL

    def failed(self,reason):
        now=self._clock()
        if self._since is None:
            # The controller stopped the last connection (a local-service restart) without a lost() line,
            # or the program has not connected yet: start the outage clock quietly and report every ten minutes.
            self._since=now;self._attempts=1;self._last_reason=reason
            self._next_report=now+REPORT_INTERVAL;self._connected_at=None
            if not self._ever_connected:self.write(f'中转：连不上（{reason}）')
            return
        if self._attempts==0:self._attempts=1
        self._last_reason=reason
        if self._next_report is not None and now>=self._next_report:
            while self._next_report<=now:self._next_report+=REPORT_INTERVAL
            self.write(f'中转：还没连上（已经断了 {format_duration(now-self._since)}，重连 {self._attempts} 次；最近一次：{reason}）')

    def refused(self,status):
        self.write(f'中转：不认这台电脑的凭据（HTTP {status}），停止重连，要在电脑上重新绑定')
        self._connected_at=None;self._since=None;self._next_report=None;self._attempts=0


class Agent:
    def __init__(self, origin, key, backend_port, backend_token, *, test_http=False, state=None, link=None):
        parsed=urlsplit(origin)
        if parsed.scheme!=('http' if test_http else 'https') or not parsed.netloc or parsed.path or parsed.username:
            raise ValueError('HTTPS origin required')
        self.origin,self.key=origin,key
        self.port,self.token=int(backend_port),backend_token
        self.state=state or (lambda value:None)
        self.link=link
        self.tasks=set()
        self.stopping=False

    async def stream(self, client, ident):
        async with client.ws_connect(self.origin+'/tunnel/stream/'+ident,
                headers={'Authorization':'Bearer '+self.key,'Origin':self.origin},heartbeat=20,
                max_msg_size=CHUNK+16384,compress=0) as ws:
            sent=False;finished=False;listener=None
            main=asyncio.current_task()
            async def watch():
                # After the request is read, this is the only reader: receive() answers the relay's pings, so a
                # slow local answer does not let the relay's heartbeat close the stream. Anything it returns is a
                # closed channel or an unexpected message, so stop sending and let the local request go too.
                try:
                    await ws.receive()
                except asyncio.CancelledError: raise
                except Exception: pass
                if not finished and not main.done(): main.cancel()
            def listening():
                nonlocal listener
                if listener is None: listener=asyncio.create_task(watch())
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
                            listening()  # the request is fully read; from here receive() only watches the channel
                            return
                        else: raise ConnectionError()
                if meta['method']!='POST':
                    async for chunk in body():
                        if chunk: raise ValueError('body on read request')
                async with client.request(meta['method'],'http://127.0.0.1:'+str(self.port)+target,
                        data=body() if meta['method']=='POST' else None,headers=headers,allow_redirects=False) as response:
                    try:
                        await ws.send_json({'status':response.status,'headers':{k:v for k,v in response.headers.items() if k.lower() in RESPONSE_HEADERS}})
                        sent=True
                        if meta['method']!='HEAD':
                            async for chunk in response.content.iter_chunked(CHUNK):
                                await asyncio.wait_for(ws.send_bytes(chunk),120)
                        await ws.send_json({'end':True})
                        finished=True
                    except asyncio.CancelledError:
                        response.close()  # the relay is gone: close the local request, do not return it to the pool half-read
                        raise
            except (Exception,asyncio.CancelledError):
                if not sent and not ws.closed:
                    with contextlib.suppress(Exception):
                        await ws.send_json({'status':502,'headers':{}})
                        await ws.send_json({'end':True})
                raise
            finally:
                finished=True
                if listener is not None:
                    listener.cancel()
                    await asyncio.gather(listener,return_exceptions=True)

    def finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled(): task.exception()  # Never log URLs, credentials or payloads.

    async def once(self, client):
        async with client.ws_connect(self.origin+'/tunnel/connect',
                headers={'Authorization':'Bearer '+self.key,'Origin':self.origin},heartbeat=20,
                max_msg_size=16384,compress=0) as ws:
            self.state('online')
            if self.link:self.link.connected()
            reason=None;bad=False
            try:
                await ws.send_str('ready')
                async for message in ws:
                    if message.type!=WSMsgType.TEXT:
                        bad=message.type is not WSMsgType.ERROR  # an ERROR carries a heartbeat exception
                        break
                    data=message.json()
                    ident=data.get('stream','')
                    if data.get('v')!=1 or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):bad=True;break
                    if len(self.tasks)>=32: continue  # busy: this request fails; the tunnel and the others carry on
                    task=asyncio.create_task(self.stream(client,ident))
                    self.tasks.add(task);task.add_done_callback(self.finished)
            except asyncio.CancelledError: raise
            except Exception as exc: reason=exception_reason(exc)
            finally:
                for task in list(self.tasks): task.cancel()
                await asyncio.gather(*list(self.tasks),return_exceptions=True)
                self.state('offline')
            if reason is None: reason='中转发来的消息不对，主动断开' if bad else close_reason(ws)
            if self.link:self.link.lost(reason)

    async def run(self):
        delay=1
        async with ClientSession(timeout=ClientTimeout(total=None,sock_connect=15,sock_read=120),
                                 auto_decompress=False,trust_env=False) as client:
            while not self.stopping:
                if self.link:self.link.attempt()
                started=asyncio.get_running_loop().time()
                try: await self.once(client)
                except asyncio.CancelledError: raise
                except ClientResponseError as exc:
                    if exc.status in (401,403):
                        self.state('unauthorized')
                        if self.link:self.link.refused(exc.status)
                        return
                    self.state('reconnecting')
                    if self.link:self.link.failed(exception_reason(exc))
                except Exception as exc:
                    self.state('reconnecting')
                    if self.link:self.link.failed(exception_reason(exc))
                if asyncio.get_running_loop().time()-started>60: delay=1
                await asyncio.sleep(random.uniform(.8,1.2)*delay)
                delay=min(delay*2,60)
