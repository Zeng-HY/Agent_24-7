"""The relay's own lines about its tunnel (relay_transport.py), and phones that hang up giving their place back.

A real Service on 127.0.0.1, as in test_relay_v2.py: which computer connected and why its link ended, which phone
requests were turned away busy (503) and why (at most one line a minute for each computer), and that a phone which
hangs up gives its computer's place back within about a second instead of when the computer next sends something.
"""
import asyncio
import base64
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from aiohttp import web, ClientSession, ClientTimeout

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_identity import Identity
from relay_service import Service, COOKIE
from relay_agent import Agent


class Mail:
    ready=True
    def __init__(self): self.sent=[]
    def send(self,*args): self.sent.append(args)


def lines(seen):
    """The captured lines without the logger prefix, how long things took made N (a slow machine may take a second
    more)."""
    return [re.sub(r'(这次连了|最久的开了|之后) \d+ 秒',r'\1 N 秒',line.split('relay.tunnel:',1)[1]) for line in seen.output]


class TunnelLogTests(unittest.IsolatedAsyncioTestCase):
    async def start(self,app,**options):
        runner=web.AppRunner(app,access_log=None,**options);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        self.runners.append(runner)
        return site._server.sockets[0].getsockname()[1]

    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.runners=[];self.tasks=[];self.raw=[]
        self.store=Identity(Path(self.tmp.name)/'state.sqlite3')
        self.service=Service('https://relay.test',self.store,Mail())
        self.hub=self.service.hub
        self.port=await self.start(self.service.app)
        self.origin='http://127.0.0.1:'+str(self.port)
        self.service.origin=self.origin;self.service.authority='127.0.0.1:'+str(self.port)
        self.client=ClientSession(timeout=ClientTimeout(total=20))
        await asyncio.to_thread(self.store.register,'alice','password-for-alice',self.store.grant('invite'))
        self.token=await asyncio.to_thread(self.store.login,'alice','password-for-alice')
        self.key='a'*43
        self.device=self.store.approve(self.token,self.store.start_authorization(self.key,'alice'))
        self.end='…'+self.device[-6:]  # the computer as the lines name it: the last six characters of its id
        self.release=asyncio.Event()
        async def backend(req):
            if req.cookies.get('lbr')!='local-0':return web.Response(status=401)
            if req.path=='/events':  # a chat's live stream: one event, then quiet
                stream=web.StreamResponse(headers={'Content-Type':'text/event-stream'});await stream.prepare(req)
                await stream.write(b'data: first\n\n');await self.release.wait()
                return stream
            if req.path=='/slow':await self.release.wait()  # the computer takes its time to answer
            return web.Response(text='ok')
        app=web.Application();app.router.add_route('*','/{path:.*}',backend)
        self.local_port=await self.start(app)

    async def asyncTearDown(self):
        self.release.set()
        for writer in self.raw:writer.close()
        for task in self.tasks:task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.client.close()
        for runner in reversed(self.runners):await runner.cleanup()
        self.tmp.cleanup()

    def held(self,conn):
        """The places this computer's open requests take (the relay's limit is 16)."""
        return sum(item[0] is conn for item in self.hub.pending.values())

    async def until(self,check,seconds=5):
        deadline=time.monotonic()+seconds
        while not check():
            if time.monotonic()>deadline:self.fail('timed out')
            await asyncio.sleep(.02)
        return time.monotonic()

    async def connect_agent(self):
        self.tasks.append(asyncio.create_task(Agent(self.origin,self.key,self.local_port,'local-0',test_http=True).run()))
        await self.until(lambda:self.device in self.hub.connections)
        return self.hub.connections[self.device]

    async def computer(self,port):
        """A computer's control link made by hand: it says ready, then never answers a ping or closes politely."""
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        self.raw.append(writer)
        writer.write(('GET /tunnel/connect HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                      'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer %s\r\n\r\n'
                      %(port,base64.b64encode(os.urandom(16)).decode(),self.key)).encode())
        head=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),5)
        self.assertTrue(head.startswith(b'HTTP/1.1 101'),head)
        mask=os.urandom(4)
        writer.write(bytes([0x81,0x85])+mask+bytes(b^mask[i%4] for i,b in enumerate(b'ready')))
        await writer.drain()
        return reader,writer

    async def phone(self,path,accept='application/json'):
        """A phone's request on a connection of its own, which the test can hang up."""
        reader,writer=await asyncio.open_connection('127.0.0.1',self.port)
        self.raw.append(writer)
        writer.write(f'GET /d/{self.device}{path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                     f'Cookie: {COOKIE}={self.token}\r\nAccept: {accept}\r\n\r\n'.encode())
        await writer.drain()
        return reader,writer

    async def streams(self,count):
        phones=[await self.phone('/events','text/event-stream') for _ in range(count)]
        for reader,_ in phones:await asyncio.wait_for(reader.readuntil(b'data: first'),5)
        return phones

    async def status(self):
        async with self.client.get(self.origin+'/d/'+self.device+'/api/status?t=query-secret',
                                   headers={'Cookie':COOKIE+'='+self.token}) as r:
            await r.read()
            return r.status,r.headers.get('Retry-After')

    async def test_connect_replace_close_and_remove_are_written(self):
        with self.assertLogs('relay.tunnel','INFO') as seen:
            old=await self.client.ws_connect(self.origin+'/tunnel/connect',headers={'Authorization':'Bearer '+self.key})
            await old.send_str('ready')
            await self.until(lambda:self.device in self.hub.connections)
            first=self.hub.connections[self.device]
            new=await self.client.ws_connect(self.origin+'/tunnel/connect',headers={'Authorization':'Bearer '+self.key})
            await new.send_str('ready')
            await self.until(lambda:self.hub.connections.get(self.device) not in (None,first))
            await old.close()
            await new.close()  # the computer closes its link politely (1000), as when 遥应 quits
            await self.until(lambda:self.device not in self.hub.connections)
            await self.connect_agent()
            async with self.client.post(self.origin+'/account/revoke',headers={'Cookie':COOKIE+'='+self.token,'Origin':self.origin},
                                        json={'id':self.device}) as r:self.assertEqual(r.status,200)
        self.assertEqual(lines(seen),[
            f'tunnel: connect {self.end} -> 电脑连上了',
            f'tunnel: drop {self.end} -> 电脑断开了（同一台电脑又连了一条新的，换下旧的这条），这次连了 N 秒',
            f'tunnel: connect {self.end} -> 电脑连上了',
            f'tunnel: drop {self.end} -> 电脑断开了（电脑关闭了连接（1000）），这次连了 N 秒',
            f'tunnel: connect {self.end} -> 电脑连上了',
            f'tunnel: drop {self.end} -> 电脑断开了（在账号页上被移除），这次连了 N 秒'])
        self.assertTrue(all(self.device not in line and self.key not in line and self.token not in line for line in seen.output))

    async def test_a_silent_computer_is_dropped_for_its_heartbeat_and_a_cut_link_says_so(self):
        self.hub.heartbeat=.4  # 20 in service: ping after 20 s of silence, dropped 10 s later
        with self.assertLogs('relay.tunnel','INFO') as seen:
            await self.computer(self.port)
            await self.until(lambda:self.device in self.hub.connections)
            await self.until(lambda:self.device not in self.hub.connections)
        self.assertEqual(lines(seen)[-1],f'tunnel: drop {self.end} -> 电脑断开了（心跳超时：约 1 秒没收到电脑的任何消息），这次连了 N 秒')
        self.hub.heartbeat=20
        with self.assertLogs('relay.tunnel','INFO') as seen:
            _,writer=await self.computer(self.port)
            await self.until(lambda:self.device in self.hub.connections)
            writer.close()  # the TCP link just ends, no websocket close: network, proxy or Caddy
            await self.until(lambda:self.device not in self.hub.connections)
        self.assertEqual(lines(seen),[f'tunnel: connect {self.end} -> 电脑连上了',
            f'tunnel: drop {self.end} -> 电脑断开了（连接被掐断，没收到关闭信号（网络、代理或 Caddy 断了）），这次连了 N 秒'])

    async def test_a_relay_that_shuts_down_says_so(self):
        service=Service('https://relay.test',self.store,Mail())
        runner=web.AppRunner(service.app,access_log=None,shutdown_timeout=.5);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        service.authority='127.0.0.1:'+str(port)
        try:
            await self.computer(port)
            await self.until(lambda:self.device in service.hub.connections)
        except BaseException:
            await runner.cleanup();raise
        # two phones turned away busy whose line is not written yet: written as the relay stops
        service.hub.busy[self.device]=[2,asyncio.get_running_loop().call_later(60,service.hub.busy_minute,self.device)]
        with self.assertLogs('relay.tunnel','INFO') as seen:
            await runner.cleanup()
        self.assertIn(f'tunnel: busy {self.end} -> 之后 1 分钟里又拒了 2 个手机请求（503）',lines(seen)[0])
        self.assertEqual(lines(seen)[-1],f'tunnel: drop {self.end} -> 电脑断开了（中转在关闭），这次连了 N 秒')
        self.assertEqual(service.hub.busy,{})

    async def test_a_busy_computer_is_written_at_most_once_a_minute_with_how_many_were_turned_away(self):
        await self.connect_agent()
        self.hub.busy_window=.5
        await self.streams(16)
        with self.assertLogs('relay.tunnel','INFO') as seen:
            for _ in range(4):self.assertEqual(await self.status(),(503,'2'))
            self.assertEqual(len(seen.output),1)
            await self.until(lambda:len(seen.output)==2)
            await asyncio.sleep(1.2)  # a quiet minute: nothing more, and the next one is written at once
            self.assertEqual(len(seen.output),2)
            self.assertEqual(await self.status(),(503,'2'))
            self.assertEqual(len(seen.output),3)
        busy=lines(seen)
        self.assertEqual(busy[0],f'tunnel: busy {self.end} -> 拒绝手机请求（503）：这台电脑已开着 16 个请求，到上限 16 了（最久的开了 N 秒）；全站 16 个')
        self.assertEqual(busy[1],f'tunnel: busy {self.end} -> 之后 N 秒里又拒了 3 个手机请求（503）；现在这台电脑开着 16 个，全站 16 个')
        self.assertEqual(busy[2],busy[0])
        for line in seen.output:
            for secret in (self.device,self.token,self.key,'/api/status','query-secret','/events'):self.assertNotIn(secret,line)

    async def test_the_limit_for_the_whole_relay_is_named(self):
        await self.connect_agent()
        self.hub.active=256
        try:
            with self.assertLogs('relay.tunnel','INFO') as seen:
                self.assertEqual(await self.status(),(503,'2'))
        finally:self.hub.active=0
        self.assertEqual(lines(seen),[f'tunnel: busy {self.end} -> 拒绝手机请求（503）：全站已开着 256 个请求，到上限 256 了；这台电脑 0 个'])

    async def test_a_phone_that_hangs_up_before_the_answer_gives_its_place_back_within_a_second(self):
        conn=await self.connect_agent()
        with self.assertNoLogs('aiohttp','ERROR'):
            _,hangs_up=await self.phone('/slow')
            waiting,_=await self.phone('/slow')
            await self.until(lambda:self.held(conn)==2)
            hangs_up.close()
            left=time.monotonic()
            self.assertLess(await self.until(lambda:self.held(conn)==1)-left,2.5)
            await asyncio.sleep(1.5)
            self.assertEqual(self.held(conn),1)  # the phone still waiting keeps its place
            self.release.set()
            head=await asyncio.wait_for(waiting.readuntil(b'\r\n\r\n'),5)
            self.assertTrue(head.startswith(b'HTTP/1.1 200'),head)

    async def test_a_phone_that_hangs_up_mid_stream_gives_its_place_back_within_a_second(self):
        conn=await self.connect_agent()
        with self.assertNoLogs('aiohttp','ERROR'):
            [(_,writer)]=await self.streams(1)
            self.assertEqual(self.held(conn),1)
            writer.close()  # the computer sends nothing more on this stream; before, its place stayed taken
            left=time.monotonic()
            self.assertLess(await self.until(lambda:self.held(conn)==0)-left,2.5)

    async def test_sixteen_phones_that_hang_up_make_room_for_the_next_one(self):
        conn=await self.connect_agent()
        phones=await self.streams(16)
        self.assertEqual(await self.status(),(503,'2'))
        for _,writer in phones:writer.close()
        await self.until(lambda:self.held(conn)==0,3)
        self.assertEqual(await self.status(),(200,None))


if __name__=='__main__':unittest.main()
