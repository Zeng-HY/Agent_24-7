import concurrent.futures
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay_gateway import Gateway, Sessions, COOKIE


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Sessions(Path(self.tmp.name)/'auth.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_use_concurrent_and_separate_revocation(self):
        code = self.store.issue('phone')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            answers = list(pool.map(self.store.consume, [code, code]))
        tokens = [x for x in answers if x]
        self.assertEqual(len(tokens), 1)
        other = self.store.consume(self.store.issue('other'))
        first_id = next(row[0] for row in self.store.listing() if row[1] == 'phone')
        self.store.revoke(first_id)
        self.assertFalse(self.store.valid(tokens[0]))
        self.assertTrue(self.store.valid(other))

    def test_expiry_and_no_plaintext_in_database(self):
        code = self.store.issue('phone')
        token = self.store.consume(code)
        with self.store.connect() as db:
            dump = '\n'.join(db.iterdump())
            self.assertNotIn(code, dump)
            self.assertNotIn(token, dump)
            db.execute('UPDATE sessions SET expires=0')
        self.assertFalse(self.store.valid(token))
        code = self.store.issue('expired')
        with self.store.connect() as db:
            db.execute('UPDATE grants SET expires=0')
        self.assertIsNone(self.store.consume(code))

    def test_pairing_attempt_limit(self):
        code = self.store.issue('phone')
        for _ in range(10):
            self.assertIsNone(self.store.consume('wrong'))
        self.assertIsNone(self.store.consume(code))


class Upstream(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.seen.append((self.path, dict(self.headers)))
        if self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: first\n\n'); self.wfile.flush()
            self.server.release_stream.wait(5)
            try:
                self.wfile.write(b'data: second\n\n'); self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True
            return
        body = b'upstream-ok'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Set-Cookie', 'lbr=BACKEND_SECRET')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.server.seen.append((self.path, dict(self.headers)))
        data = self.rfile.read(int(self.headers['Content-Length']))
        body = json.dumps({'size': len(data), 'hash': hashlib.sha256(data).hexdigest()}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Sessions(Path(self.tmp.name)/'auth.sqlite3')
        self.up = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.up.daemon_threads = True
        self.up.seen = []
        self.up.release_stream = threading.Event()
        self.gw = Gateway(0, 'https://relay.example', self.store, self.up.server_port, 'BACKEND_SECRET')
        self.threads = []
        for server in (self.up, self.gw):
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start(); self.threads.append(t)
        self.token = self.store.consume(self.store.issue('test-phone'))

    def tearDown(self):
        self.up.release_stream.set()
        for server in (self.gw, self.up):
            server.shutdown(); server.server_close()
        for thread in self.threads:
            thread.join()
        self.tmp.cleanup()

    def request(self, path='/', method='GET', body=None, auth=True, headers=None):
        h = {'Host': 'relay.example'}
        if auth:
            h['Cookie'] = COOKIE+'='+self.token
        if method == 'POST':
            h['Origin'] = 'https://relay.example'
        h.update(headers or {})
        c = http.client.HTTPConnection('127.0.0.1', self.gw.server_port, timeout=3)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), r.read()
        c.close()
        return result

    def test_unauthorized_every_resource_and_spoofed_legacy_auth(self):
        for path in ('/api/status', '/static/icon.png', '/api/codex/image?id=x', '/events'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, auth=False)[0], 401)
        status, _, body = self.request('/?t=BACKEND_SECRET', auth=False,
                                      headers={'Tailscale-User-Login': 'owner', 'Cookie': 'lbr=BACKEND_SECRET'})
        self.assertEqual(status, 200)
        self.assertIn('一次性配对码'.encode(), body)
        self.assertEqual(self.up.seen, [])

    def test_strip_untrusted_headers_legacy_token_and_upstream_cookie(self):
        status, headers, body = self.request('/?t=attacker&x=1', headers={
            'Tailscale-User-Login':'owner', 'Authorization':'Basic bad',
            'X-Forwarded-Host':'evil', 'X-Forwarded-For':'evil'})
        self.assertEqual((status, body), (200, b'upstream-ok'))
        self.assertNotIn('Set-Cookie', headers)
        path, sent = self.up.seen[-1]
        self.assertEqual(path, '/?x=1')
        self.assertEqual(sent['Cookie'], 'lbr=BACKEND_SECRET')
        for name in ('Tailscale-User-Login', 'Authorization', 'X-Forwarded-Host', 'X-Forwarded-For'):
            self.assertNotIn(name, sent)

    def test_host_origin_and_csrf_rejections(self):
        self.assertEqual(self.request(headers={'Host':'evil'})[0], 421)
        self.assertEqual(self.request(headers={'Origin':'https://evil'})[0], 403)
        self.assertEqual(self.request(headers={'Sec-Fetch-Site':'cross-site'})[0], 403)
        self.assertEqual(self.request('/api/send', 'POST', b'{}', headers={'Origin':''})[0], 403)
        self.assertEqual(self.up.seen, [])

    def test_pair_cookie_replay_logout(self):
        code = self.store.issue('new-phone')
        data = json.dumps({'code': code})
        status, headers, _ = self.request('/relay/pair', 'POST', data, auth=False)
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie']
        for item in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/'):
            self.assertIn(item, cookie)
        self.assertEqual(self.request('/relay/pair', 'POST', data, auth=False)[0], 403)
        self.assertEqual(self.request('/relay/logout', 'POST', b'{}')[0], 200)
        self.assertEqual(self.request('/api/status')[0], 401)

    def test_binary_upload_integrity(self):
        data = bytes(range(256))*8192
        status, _, body = self.request('/api/codex/upload', 'POST', data,
                                       headers={'Content-Type':'application/octet-stream'})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result, {'size':len(data), 'hash':hashlib.sha256(data).hexdigest()})

    def test_rejected_framing_size_and_pair_payload(self):
        self.assertEqual(self.request('/api/send', 'POST', b'', headers={'Content-Length':str(65*1024*1024)})[0], 413)
        self.assertEqual(self.request('/api/send', 'POST', b'', headers={'Transfer-Encoding':'chunked'})[0], 400)
        self.assertEqual(self.request('/relay/pair', 'POST', '[]', auth=False)[0], 403)
        self.assertEqual(self.request('/relay/pair', 'POST', '{bad', auth=False)[0], 400)

    def test_sse_arrives_before_upstream_finishes_and_revoke_stops_next_event(self):
        c = http.client.HTTPConnection('127.0.0.1', self.gw.server_port, timeout=2)
        c.request('GET','/events', headers={'Host':'relay.example','Cookie':COOKIE+'='+self.token})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.readline(), b'data: first\n')
        self.assertFalse(self.up.release_stream.is_set())
        self.store.revoke(self.store.listing()[0][0])
        self.up.release_stream.set()
        self.assertNotIn(b'second', r.read())
        c.close()

    def test_invalid_origin_configuration(self):
        for origin in ('http://relay.example','https://relay.example/path','https://u@relay.example'):
            with self.assertRaises(ValueError):
                Gateway(0, origin, self.store, self.up.server_port, 'x')


if __name__ == '__main__':
    unittest.main()
