"""Two independent users/devices, real HTTP hops, disposable data only."""
import concurrent.futures
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay_accounts import Accounts, password_matches
from relay_cloud import Cloud, COOKIE, DEVICE_COOKIE, export_device
from relay_device import DeviceGateway


class Desktop(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.seen.append((self.command,self.path,dict(self.headers)))
        if self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: first\n\n'); self.wfile.flush()
            self.server.release.wait(8)
            try:
                self.wfile.write(b'data: secret-after-revoke\n\n'); self.wfile.flush()
            except OSError:
                pass
            self.close_connection=True
            return
        body = self.server.identity.encode()
        self.send_response(200)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        self.server.seen.append((self.command,self.path,dict(self.headers)))
        data = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)


class MultiuserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Accounts(Path(cls.tmp.name)/'cloud.sqlite3')
        cls.tokens, cls.devices, cls.locals, cls.servers = [],[],[],[]
        for index, name in enumerate(('alice','bob')):
            cls.store.register(name,'test-password-'+name,cls.store.grant('invite'))
            token = cls.store.login(name,'test-password-'+name)
            cls.tokens.append(token)
            code = cls.store.grant('bind',cls.store.owner(token))
            device = cls.store.bind(code, name+' computer',name)
            desktop = ThreadingHTTPServer(('127.0.0.1',0),Desktop)
            desktop.daemon_threads=True
            desktop.identity=name+' private chat/file'
            desktop.seen=[]
            desktop.release=threading.Event()
            cls.locals.append(desktop)
            config = Path(cls.tmp.name)/(name+'.json')
            config.write_text(json.dumps(device),encoding='utf-8')
            gateway = DeviceGateway(0,'https://relay.example',config,desktop.server_port,'local-'+name)
            device['port']=gateway.server_port
            with cls.store.connect() as db:
                db.execute('UPDATE devices SET port=? WHERE id=?',(gateway.server_port,device['id']))
            cls.devices.append(device)
            cls.servers.extend([desktop,gateway])
        cls.cloud=Cloud(0,'https://relay.example',cls.store)
        cls.servers.append(cls.cloud)
        for server in cls.servers:
            threading.Thread(target=server.serve_forever,daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for desktop in cls.locals:
            desktop.release.set()
        for server in reversed(cls.servers):
            server.shutdown(); server.server_close()
        cls.tmp.cleanup()

    def request(self,path, user=0, device=None, method='GET', data=None, headers=None, port=None):
        h={'Host':'relay.example','Origin':'https://relay.example'}
        if user is not None:
            ident = device if device is not None else self.devices[user]['id']
            h['Cookie']=COOKIE+'='+self.tokens[user]+'; '+DEVICE_COOKIE+'='+ident
        h.update(headers or {})
        body=json.dumps(data) if isinstance(data,dict) else data
        conn=http.client.HTTPConnection('127.0.0.1',port or self.cloud.server_port,timeout=4)
        conn.request(method,path,body=body,headers=h)
        response=conn.getresponse()
        result=response.status,dict(response.getheaders()),response.read()
        conn.close()
        return result

    def test_01_separate_devices_and_all_resource_types(self):
        for user,name in enumerate(('alice','bob')):
            for path in ('/api/chats','/api/codex/image?id=guessed','/attachments/guessed','/api/status'):
                self.assertEqual(self.request(path,user)[2],(name+' private chat/file').encode())
            self.assertEqual(self.request('/api/codex/upload',user,method='POST',data=b'private-upload')[2],b'private-upload')
        for user in (0,1):
            before=len(self.locals[1-user].seen)
            for path,method in (('/api/chats','GET'),('/api/codex/image?id=known','GET'),
                                ('/api/send','POST'),('/api/codex/upload','POST'),('/events','GET')):
                body = b'{}' if method=='POST' else None
                self.assertEqual(self.request(path,user,self.devices[1-user]['id'],method,body)[0],403)
            self.assertEqual(len(self.locals[1-user].seen),before)

    def test_02_direct_route_and_spoofed_headers(self):
        for device in self.devices:
            self.assertEqual(self.request('/api/chats',port=device['port'],headers={'Authorization':'Bearer wrong'})[0],401)
        self.assertEqual(self.request('/api/chats',user=None,headers={
            'Cookie':'lbr=local-bob','Authorization':'Bearer '+self.devices[1]['gateway_secret'],
            'Tailscale-User-Login':'bob','X-Forwarded-User':'bob'})[0],401)
        self.assertEqual(self.request('/api/chats',headers={'Authorization':'Bearer '+self.devices[1]['gateway_secret']})[2],b'alice private chat/file')
        sent=self.locals[0].seen[-1][2]
        self.assertEqual(sent['Cookie'],'lbr=local-alice')
        self.assertNotIn('Authorization',sent)
        self.assertNotIn('Tailscale-User-Login',sent)
        self.assertEqual(self.request('/relay/pair',method='POST',data={'code':'x'})[0],404)

    def test_03_device_list_select_revoke_ownership(self):
        state=json.loads(self.request('/account/state')[2])
        self.assertEqual([x['id'] for x in state['devices']],[self.devices[0]['id']])
        for action in ('select','revoke'):
            self.assertEqual(self.request('/account/'+action,method='POST',data={'id':self.devices[1]['id']})[0],404)
        self.assertEqual(self.request('/account/select',method='POST',data={'id':self.devices[0]['id']})[0],200)
        self.assertTrue(state['usage'])

    def test_04_csrf_framing_and_no_alternate_proxy_path(self):
        self.assertEqual(self.request('/account/bind',method='POST',data={},headers={'Origin':'https://evil'})[0],403)
        self.assertEqual(self.request('/api/status',headers={'Host':'evil'})[0],421)
        self.assertEqual(self.request('//evil/api/chats')[0],400)
        self.assertEqual(self.request('/api/send',method='POST',data=b'',headers={'Transfer-Encoding':'chunked'})[0],400)
        self.assertEqual(self.request('/api/chats?device='+self.devices[1]['id'])[2],b'alice private chat/file')

    def test_05_http_enrollment_confirmation_once_and_account_reset_gate(self):
        code=json.loads(self.request('/account/bind',method='POST',data={})[2])['code']
        self.assertEqual(self.request('/account/enroll',user=None,method='POST',data={
            'code':code,'account':'bob','label':'temporary test PC'})[0],400)
        result=self.request('/account/enroll',user=None,method='POST',data={
            'code':code,'account':'alice','label':'temporary test PC'})
        self.assertEqual(result[0],200)
        ident=json.loads(result[2])['id']
        self.assertIsNotNone(self.store.device(self.tokens[0],ident))
        self.assertIsNone(self.store.device(self.tokens[1],ident))
        self.assertEqual(self.request('/account/enroll',user=None,method='POST',data={
            'code':code,'account':'alice','label':'replay'})[0],400)
        self.assertEqual(self.request('/account/reset',user=None,method='POST',data={
            'code':'invalid','password':'replacement-password'})[0],400)
        self.store.revoke(self.tokens[0],ident)

    def test_90_revoke_stops_inflight_sse_and_future_requests(self):
        conn=http.client.HTTPConnection('127.0.0.1',self.cloud.server_port,timeout=4)
        conn.request('GET','/events',headers={'Host':'relay.example','Cookie':COOKIE+'='+self.tokens[0]+'; '+DEVICE_COOKIE+'='+self.devices[0]['id']})
        response=conn.getresponse()
        self.assertEqual(response.readline(),b'data: first\n')
        self.assertEqual(self.request('/account/revoke',method='POST',data={'id':self.devices[0]['id']})[0],200)
        self.locals[0].release.set()
        self.assertNotIn(b'secret-after-revoke',response.read())
        conn.close()
        self.assertEqual(self.request('/api/chats')[0],403)
        self.assertEqual(self.request('/api/chats',1)[0],200)


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Accounts(Path(self.tmp.name)/'state.sqlite3')
        self.store.register('alice','test-password-alice',self.store.grant('invite'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_change_reset_and_session_invalidation(self):
        token=self.store.login('alice','test-password-alice')
        owner=self.store.owner(token)
        self.store.change_password(token,'test-password-alice','changed-password-alice')
        self.assertFalse(self.store.valid(token))
        token=self.store.login('alice','changed-password-alice')
        reset=self.store.grant('reset',owner)
        self.store.reset(reset,'reset-password-alice')
        self.assertFalse(self.store.valid(token))
        with self.assertRaises(ValueError):
            self.store.reset(reset,'another-password')
        token=self.store.login('alice','reset-password-alice')
        self.store.logout(token)
        self.assertFalse(self.store.valid(token))

    def test_grants_concurrent_expired_and_wrong_account(self):
        token=self.store.login('alice','test-password-alice')
        code=self.store.grant('bind',self.store.owner(token))
        with self.assertRaises(ValueError):
            self.store.bind(code,'PC','bob')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            def bind(_):
                try:return self.store.bind(code,'PC','alice')
                except ValueError:return None
            result=list(pool.map(bind,range(2)))
        self.assertEqual(sum(x is not None for x in result),1)
        code=self.store.grant('invite',ttl=-1)
        with self.assertRaises(ValueError):
            self.store.register('bob','test-password-bob',code)

    def test_hashes_rate_limit_and_unique_frp_credentials(self):
        token=self.store.login('alice','test-password-alice')
        owner=self.store.owner(token)
        devices=[self.store.bind(self.store.grant('bind',owner),'PC','alice') for _ in range(2)]
        self.assertNotEqual(devices[0]['tunnel_secret'],devices[1]['tunnel_secret'])
        self.assertNotEqual(devices[0]['port'],devices[1]['port'])
        self.assertNotEqual(devices[0]['ingress'],devices[1]['ingress'])
        for d in devices:
            export_device(self.store,d['id'],Path(self.tmp.name)/'exports')
            config=(Path(self.tmp.name)/'exports'/d['id']/'frps.toml').read_text()
            self.assertIn('proxyBindAddr = "127.0.0.1"',config)
            self.assertIn('single = '+str(d['port']),config)
            self.assertNotIn(d['tunnel_secret'],config)
        with self.store.connect() as db:
            dump='\n'.join(db.iterdump())
        self.assertNotIn('test-password-alice',dump)
        self.assertNotIn(token,dump)
        for _ in range(10):self.store.rate('test')
        with self.assertRaises(ValueError):self.store.rate('test')


if __name__=='__main__':
    unittest.main()
