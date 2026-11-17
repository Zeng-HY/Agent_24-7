"""A tunnel stream must answer the relay's pings while the local service is still working on the answer."""
import asyncio
import contextlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, ClientTimeout, web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_agent import Agent
from relay_identity import Identity
from relay_service import Service, COOKIE


FAST_HEARTBEAT=0.5  # the relay's stream heartbeat is 20 s; shrink the same race so the tests are quick
SLOW=1.5            # three fast heartbeats: the old code loses the stream long before this


class FastWebSocketResponse(web.WebSocketResponse):
    """Test-only: relay_transport's stream websocket is built with heartbeat=20; force a small one here."""
    def __init__(self,*args,**kwargs):
        kwargs['heartbeat']=FAST_HEARTBEAT
        super().__init__(*args,**kwargs)


async def wait_until(predicate,timeout=8):
    deadline=asyncio.get_running_loop().time()+timeout
    while asyncio.get_running_loop().time()<deadline:
        if predicate():return True
        await asyncio.sleep(0.05)
    return predicate()


class StreamHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patcher=patch.object(web,'WebSocketResponse',FastWebSocketResponse)
        self.patcher.start();self.addCleanup(self.patcher.stop)
        self.tmp=tempfile.TemporaryDirectory();self.runners=[];self.runs=[]
        self.store=Identity(Path(self.tmp.name)/'state.sqlite3')
        self.service=Service('https://relay.test',self.store,types.SimpleNamespace(send=lambda *args:None))
        runner=web.AppRunner(self.service.app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start();self.runners.append(runner)
        port=site._server.sockets[0].getsockname()[1]
        self.origin='http://127.0.0.1:'+str(port)
        self.service.origin=self.origin;self.service.authority='127.0.0.1:'+str(port)
        self.client=ClientSession(timeout=ClientTimeout(total=20))
        await asyncio.to_thread(self.store.register,'alice','password-for-alice',self.store.grant('invite'))
        self.token=await asyncio.to_thread(self.store.login,'alice','password-for-alice')
        self.key='a'*43
        self.device=self.store.approve(self.token,self.store.start_authorization(self.key,'alice'))
        self.backend_closed=asyncio.Event()
        async def slow(request):
            await asyncio.sleep(SLOW)
            return web.Response(text='done')
        async def slow_post(request):
            body=await request.read()
            await asyncio.sleep(SLOW)
            return web.Response(body=b'got:'+body)
        async def slow_stream(request):
            response=web.StreamResponse();await response.prepare(request)
            await response.write(b'first')
            await asyncio.sleep(SLOW)
            await response.write(b'second');await response.write_eof()
            return response
        async def closing_stream(request):
            response=web.StreamResponse();await response.prepare(request)
            await response.write(b'first')
            deadline=asyncio.get_running_loop().time()+10
            while asyncio.get_running_loop().time()<deadline:
                if request.transport is None or request.transport.is_closing():
                    self.backend_closed.set();return response
                await asyncio.sleep(0.02)
            return response
        app=web.Application()
        app.router.add_get('/slow',slow);app.router.add_post('/slow',slow_post)
        app.router.add_get('/stream',slow_stream);app.router.add_get('/closing',closing_stream)
        backend=web.AppRunner(app,access_log=None);await backend.setup()
        bsite=web.TCPSite(backend,'127.0.0.1',0);await bsite.start();self.runners.append(backend)
        self.backend_port=bsite._server.sockets[0].getsockname()[1]
        self.agent=Agent(self.origin,self.key,self.backend_port,'local',test_http=True)
        self.runs.append(asyncio.create_task(self.agent.run()))
        self.assertTrue(await wait_until(lambda:self.device in self.service.hub.connections))

    async def asyncTearDown(self):
        for task in self.runs:task.cancel()
        await asyncio.gather(*self.runs,return_exceptions=True)
        await self.client.close()
        for runner in reversed(self.runners):await runner.cleanup()
        self.tmp.cleanup()

    def headers(self):
        return {'Cookie':COOKIE+'='+self.token,'Origin':self.origin}

    async def test_a_slow_get_answer_survives_the_relay_heartbeat(self):
        chunks=self.service.hub.fetch(self.device,'/slow');body=b''
        try:
            async for chunk in chunks:body+=chunk
        finally:
            await chunks.aclose()
        self.assertEqual(body,b'done')

    async def test_a_slow_post_answer_survives_the_relay_heartbeat(self):
        async with self.client.post(self.origin+'/d/'+self.device+'/slow',
                headers=self.headers(),data=b'payload') as response:
            self.assertEqual(response.status,200)
            self.assertEqual(await response.read(),b'got:payload')

    async def test_a_stream_with_a_long_gap_keeps_reading(self):
        chunks=self.service.hub.fetch(self.device,'/stream');body=b''
        try:
            async for chunk in chunks:body+=chunk
        finally:
            await chunks.aclose()
        self.assertEqual(body,b'firstsecond')

    async def test_closing_the_relay_stream_stops_the_local_request_at_once(self):
        chunks=self.service.hub.fetch(self.device,'/closing')
        try:
            first=await asyncio.wait_for(chunks.__anext__(),5)
            self.assertEqual(first,b'first')
            stream=next(iter(self.service.hub.connections[self.device].streams))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stream.close(code=1008),1)
            await asyncio.wait_for(self.backend_closed.wait(),2)
        finally:
            await chunks.aclose()


if __name__=='__main__':unittest.main()
