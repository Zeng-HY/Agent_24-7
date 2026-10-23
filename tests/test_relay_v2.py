import asyncio
import hashlib
import json
import io
from pathlib import Path
import sys
import tempfile
import ssl
import subprocess
import shutil
import threading
import unittest
from aiohttp import web, ClientSession, ClientTimeout, WSServerHandshakeError, TCPConnector, ClientConnectorCertificateError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_identity import Identity
from relay_service import Service, COOKIE
from relay_agent import Agent
from relay_device import DeviceGateway


class Mail:
    ready=True
    def __init__(self): self.sent=[]
    def send(self,*args): self.sent.append(args)


class V2Tests(unittest.IsolatedAsyncioTestCase):
    async def start(self,app):
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        self.runners.append(runner)
        return site._server.sockets[0].getsockname()[1]

    async def test_public_theme_assets_and_version_are_available_without_login(self):
        async with self.client.get(self.origin+'/account') as response:
            self.assertEqual(response.status,200)
            html=await response.text();self.assertIn('/account/theme.js?v=',html);self.assertNotIn('__TELEPLY_VERSION__',html)
        for name in ['theme.js','theme.css','favicon.svg','favicon-dark.svg','apple-touch-icon.png']:
            async with self.client.get(self.origin+'/account/'+name) as response:
                self.assertEqual(response.status,200,name);self.assertGreater(len(await response.read()),100)
        async with self.client.get(self.origin+'/account/config') as response:
            version=(await response.json())['version'];self.assertEqual(version,json.loads((Path(__file__).resolve().parents[1]/'windows-version.json').read_text())['version'])

    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.runners=[];self.tasks=[]
        self.store=Identity(Path(self.tmp.name)/'state.sqlite3')
        self.mail=Mail();self.service=Service('https://relay.test',self.store,self.mail)
        port=await self.start(self.service.app)
        self.origin='http://127.0.0.1:'+str(port)
        self.service.origin=self.origin;self.service.authority='127.0.0.1:'+str(port)
        self.client=ClientSession(timeout=ClientTimeout(total=20))
        self.tokens=[];self.devices=[];self.keys=[];self.backend_seen=[[],[]]
        self.local_ports=[]
        self.release=asyncio.Event()
        for index,name in enumerate(('alice','bob')):
            await asyncio.to_thread(self.store.register,name,'password-for-'+name,self.store.grant('invite'))
            token=await asyncio.to_thread(self.store.login,name,'password-for-'+name)
            self.tokens.append(token)
            key=('a' if index==0 else 'b')*43;self.keys.append(key)
            auth=self.store.start_authorization(key,name)
            device=self.store.approve(token,auth);self.devices.append(device)
            async def backend(req,i=index):
                self.backend_seen[i].append(req.path)
                if req.cookies.get('lbr')!='local-'+str(i):return web.Response(status=401)
                if req.path=='/events':
                    stream=web.StreamResponse(headers={'Content-Type':'text/event-stream'});await stream.prepare(req)
                    await stream.write(b'data: first\n\n');await self.release.wait()
                    try:await stream.write(b'data: after-revoke\n\n');await stream.write_eof()
                    except (ConnectionError,RuntimeError):pass
                    return stream
                if req.method=='POST':
                    data=await req.read();return web.json_response({'size':len(data),'hash':hashlib.sha256(data).hexdigest()})
                if req.path=='/': return web.Response(text='<html><head></head><body><img src="/image"></body></html>',content_type='text/html')
                return web.Response(text='private-'+str(i))
            app=web.Application(client_max_size=64*1024*1024);app.router.add_route('*','/{path:.*}',backend)
            local_port=await self.start(app)
            self.local_ports.append(local_port)
            agent=Agent(self.origin,key,local_port,'local-'+str(index),test_http=True)
            self.tasks.append(asyncio.create_task(agent.run()))
        for _ in range(50):
            if len(self.service.hub.connections)==2:break
            await asyncio.sleep(.05)
        self.assertEqual(len(self.service.hub.connections),2)

    async def asyncTearDown(self):
        self.release.set()
        for task in self.tasks:task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.client.close()
        for runner in reversed(self.runners):await runner.cleanup()
        self.tmp.cleanup()

    def headers(self,user=0):
        return {'Cookie':COOKIE+'='+self.tokens[user],'Origin':self.origin}

    async def test_route_isolation_binary_transfer_and_page_scope(self):
        for user in (0,1):
            for resource in ('api/chats','attachments/guessed','api/status'):
                async with self.client.get(self.origin+'/d/'+self.devices[user]+'/'+resource,headers=self.headers(user)) as r:
                    self.assertEqual(r.status,200);self.assertEqual(await r.text(),'private-'+str(user))
            for resource in ('api/chats','attachments/guessed','events'):
                async with self.client.get(self.origin+'/d/'+self.devices[1-user]+'/'+resource,headers=self.headers(user)) as r:
                    self.assertEqual(r.status,404)
            async with self.client.post(self.origin+'/d/'+self.devices[1-user]+'/api/send',headers=self.headers(user),data=b'no') as r:
                self.assertEqual(r.status,404)
        payload=bytes(range(256))*65536
        async with self.client.post(self.origin+'/d/'+self.devices[0]+'/api/upload',headers=self.headers(),data=io.BytesIO(payload)) as r:
            self.assertEqual(r.status,200)
            self.assertEqual(await r.json(),{'size':len(payload),'hash':hashlib.sha256(payload).hexdigest()})
        async with self.client.get(self.origin+'/d/'+self.devices[0]+'/',headers=self.headers()) as r:
            text=await r.text();self.assertEqual(r.status,200)
            self.assertIn('/d/'+self.devices[0]+'/image',text);self.assertIn('window.RELAY_BASE',text)

    async def test_sse_revocation_and_anonymous_rejection(self):
        async with self.client.get(self.origin+'/d/'+self.devices[0]+'/api/status') as r:self.assertEqual(r.status,401)
        response=await self.client.get(self.origin+'/d/'+self.devices[0]+'/events',headers=self.headers())
        self.assertEqual(response.status,200)
        self.assertEqual(await response.content.readline(),b'data: first\n')
        async with self.client.post(self.origin+'/account/revoke',headers=self.headers(),json={'id':self.devices[0]}) as r:self.assertEqual(r.status,200)
        self.release.set()
        try:remaining=await response.read()
        except Exception:remaining=b''
        self.assertNotIn(b'after-revoke',remaining)
        response.close()
        async with self.client.get(self.origin+'/d/'+self.devices[0]+'/api/status',headers=self.headers()) as r:self.assertEqual(r.status,404)

    async def test_email_signup_reset_and_pending_authorization_replay(self):
        headers={'Origin':self.origin}
        async with self.client.post(self.origin+'/account/register',headers=headers,json={'email':'new@example.test','password':'new-account-password'}) as r:self.assertEqual(r.status,200)
        code=self.mail.sent[-1][2]
        self.assertIsNone(self.store.user('new@example.test'))
        async with self.client.post(self.origin+'/account/verify',headers=headers,json={'code':code}) as r:self.assertEqual(r.status,200)
        async with self.client.post(self.origin+'/account/verify',headers=headers,json={'code':code}) as r:self.assertEqual(r.status,400)
        token=await asyncio.to_thread(self.store.login,'new@example.test','new-account-password')
        key='c'*43
        ident=self.store.start_authorization(key,'new PC')
        self.assertEqual(self.store.start_authorization(key,'new PC'),ident)
        device=self.store.approve(token,ident)
        self.assertEqual(self.store.approve(token,ident),device)
        with self.assertRaises(ValueError):self.store.approve(self.tokens[0],ident)
        async with self.client.post(self.origin+'/account/forgot',headers=headers,json={'email':'new@example.test'}) as r:self.assertEqual(r.status,200)
        reset=self.mail.sent[-1][2]
        async with self.client.post(self.origin+'/account/reset',headers=headers,json={'code':reset,'password':'changed-password'}) as r:self.assertEqual(r.status,200)
        self.assertFalse(self.store.valid(token))

    async def test_six_digit_codes_sign_in_on_the_page_and_logins_wait_their_turn(self):
        headers={'Origin':self.origin}
        async with self.client.post(self.origin+'/account/register',headers=headers,json={'email':'code@example.test','password':'code-account-password'}) as r:self.assertEqual(r.status,200)
        address,kind,code,pin=self.mail.sent[-1]
        self.assertEqual((address,kind),('code@example.test','signup'));self.assertRegex(pin,r'^[0-9]{6}$')
        async with self.client.post(self.origin+'/account/verify',headers=headers,json={'email':'code@example.test','pin':'12345x'}) as r:self.assertEqual(r.status,400)
        async with self.client.post(self.origin+'/account/verify',headers=headers,json={'email':'code@example.test','pin':pin}) as r:
            self.assertEqual(r.status,200);session=r.cookies[COOKIE].value
        async with self.client.get(self.origin+'/account/state',headers={'Cookie':COOKIE+'='+session}) as r:self.assertEqual(r.status,200)  # signed in by the code
        async with self.client.post(self.origin+'/account/forgot',headers=headers,json={'email':'code@example.test'}) as r:self.assertEqual(r.status,200)
        pin=self.mail.sent[-1][3]
        async with self.client.post(self.origin+'/account/reset',headers=headers,json={'email':'code@example.test','pin':pin,'password':'code-password-changed'}) as r:
            self.assertEqual(r.status,200);self.assertIn(COOKIE,r.cookies)
        self.assertTrue(await asyncio.to_thread(self.store.login,'code@example.test','code-password-changed'))
        # three at once: all signed in (two password checks run at a time; the third waits rather than 429)
        async def login(name):
            async with self.client.post(self.origin+'/account/login',headers=headers,json={'name':name,'password':'password-for-'+name}) as r:return r.status
        self.assertEqual(await asyncio.gather(login('alice'),login('bob'),login('alice')),[200,200,200])

    async def test_cross_device_stream_forgery_and_no_post_replay_on_reconnect(self):
        with self.assertRaises(WSServerHandshakeError) as denied:
            await self.client.ws_connect(self.origin+'/tunnel/connect',headers={'Authorization':'Bearer wrong'})
        self.assertEqual(denied.exception.status,401)
        ident='f'*32
        future=asyncio.get_running_loop().create_future()
        self.service.hub.pending[ident]=(self.service.hub.connections[self.devices[0]],self.tokens[0],future)
        try:
            with self.assertRaises(WSServerHandshakeError) as denied:
                await self.client.ws_connect(self.origin+'/tunnel/stream/'+ident,
                    headers={'Authorization':'Bearer '+self.keys[1]})
            self.assertEqual(denied.exception.status,403)
        finally:
            self.service.hub.pending.pop(ident,None);future.cancel()
        async with self.client.post(self.origin+'/d/'+self.devices[0]+'/api/send',headers=self.headers(),data=b'one') as r:
            self.assertEqual(r.status,200);await r.read()
        await self.service.hub.disconnect(self.devices[0])
        for _ in range(60):
            if self.devices[0] in self.service.hub.connections:break
            await asyncio.sleep(.05)
        self.assertIn(self.devices[0],self.service.hub.connections)
        self.assertEqual(self.backend_seen[0].count('/api/send'),1)
        async with self.client.get(self.origin+'/d/'+self.devices[0]+'/api/status',headers=self.headers()) as r:self.assertEqual(r.status,200)

    async def test_existing_frp_device_remains_usable_through_scoped_route(self):
        row=self.store.bind(self.store.grant('bind',self.store.owner(self.tokens[0])),'Legacy','alice')
        path=Path(self.tmp.name)/'legacy.json';path.write_text(json.dumps(row))
        gateway=DeviceGateway(0,'https://relay.test',path,self.local_ports[0],'local-0')
        gateway.origin=self.origin;gateway.authority=self.service.authority
        thread=threading.Thread(target=gateway.serve_forever,daemon=True);thread.start()
        with self.store.connect() as db:db.execute('UPDATE devices SET port=? WHERE id=?',(gateway.server_port,row['id']))
        try:
            async with self.client.get(self.origin+'/d/'+row['id']+'/api/status',headers=self.headers()) as r:
                self.assertEqual(r.status,200);self.assertEqual(await r.text(),'private-0')
            async with self.client.get(self.origin+'/d/'+row['id']+'/',headers=self.headers()) as r:
                self.assertIn('/d/'+row['id']+'/image',await r.text())
        finally:
            await asyncio.to_thread(gateway.shutdown);gateway.server_close();thread.join()

    async def test_verified_tls_stream_and_untrusted_certificate_rejection(self):
        openssl=shutil.which('openssl') or 'C:/Program Files/Git/usr/bin/openssl.exe'
        if not Path(openssl).is_file():self.skipTest('OpenSSL unavailable')
        folder=Path(self.tmp.name)
        await asyncio.to_thread(subprocess.run,[openssl,'req','-x509','-newkey','rsa:2048','-nodes',
            '-keyout',str(folder/'tls.key'),'-out',str(folder/'tls.crt'),'-days','1','-subj','/CN=127.0.0.1',
            '-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        server_ssl=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_ssl.load_cert_chain(folder/'tls.crt',folder/'tls.key')
        service=Service('https://relay.test',self.store,self.mail)
        runner=web.AppRunner(service.app,access_log=None);await runner.setup()
        self.runners.append(runner)
        site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=server_ssl);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        origin='https://127.0.0.1:'+str(port);service.origin=origin;service.authority='127.0.0.1:'+str(port)
        with self.assertRaises(ClientConnectorCertificateError):
            await self.client.ws_connect(origin+'/tunnel/connect',headers={'Authorization':'Bearer '+self.keys[0]})
        trusted=ssl.create_default_context(cafile=str(folder/'tls.crt'))
        async with ClientSession(connector=TCPConnector(ssl=trusted),auto_decompress=False) as client:
            agent=Agent(origin,self.keys[0],self.local_ports[0],'local-0')
            task=asyncio.create_task(agent.once(client))
            try:
                for _ in range(50):
                    if self.devices[0] in service.hub.connections:break
                    await asyncio.sleep(.05)
                async with client.get(origin+'/d/'+self.devices[0]+'/api/status',headers={'Cookie':COOKIE+'='+self.tokens[0]}) as r:
                    self.assertEqual(r.status,200);self.assertEqual(await r.text(),'private-0')
            finally:task.cancel();await asyncio.gather(task,return_exceptions=True)


if __name__=='__main__':unittest.main()
