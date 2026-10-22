"""Loopback-only authenticated FRP entry; the original desktop server stays private.

The cloud TLS terminator remains trusted. This is not end-to-end encryption.
Pair grants are issued locally, consumed once and never logged by the gateway.
"""
import argparse
from contextlib import contextmanager
import hashlib
import http.client
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit, parse_qsl, urlencode

HERE = Path(__file__).resolve().parent
COOKIE = '__Host-ar_relay'
MAX_BODY = 64 * 1024 * 1024
SESSION_SECONDS = 30 * 86400


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Sessions:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS grants (hash TEXT PRIMARY KEY, label TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS sessions
                    (id TEXT PRIMARY KEY, hash TEXT UNIQUE, label TEXT, expires REAL, created REAL);
                CREATE TABLE IF NOT EXISTS attempts (time REAL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def issue(self, label):
        code = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM grants WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO grants VALUES (?,?,?)', (digest(code), label[:80], time.time()+600))
        return code

    def consume(self, code):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE time < ?', (now-60,))
            if db.execute('SELECT count(*) FROM attempts').fetchone()[0] >= 10:
                return None
            db.execute('INSERT INTO attempts VALUES (?)', (now,))
            row = db.execute('SELECT label FROM grants WHERE hash=? AND expires>?', (digest(code), now)).fetchone()
            if row is None:
                return None
            db.execute('DELETE FROM grants WHERE hash=?', (digest(code),))
            token = secrets.token_urlsafe(32)
            ident = secrets.token_hex(8)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                       (ident, digest(token), row[0], now+SESSION_SECONDS, now))
        return token

    def valid(self, token):
        if not token or len(token) > 256:
            return False
        with self.connect() as db:
            return db.execute('SELECT 1 FROM sessions WHERE hash=? AND expires>?',
                              (digest(token), time.time())).fetchone() is not None

    def listing(self):
        with self.connect() as db:
            return db.execute('SELECT id,label,expires FROM sessions WHERE expires>?', (time.time(),)).fetchall()

    def revoke(self, ident):
        with self.connect() as db:
            return db.execute('DELETE FROM sessions WHERE id=?', (ident,)).rowcount

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (digest(token),))


LOGIN = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>连接电脑</title>
<style>body{font:17px/1.7 system-ui;max-width:480px;margin:60px auto;padding:24px;color:#182333}
input,button{box-sizing:border-box;width:100%;padding:14px;margin:8px 0;font:inherit}button{background:#1767dc;color:white;border:0;border-radius:8px}</style>
<h1>连接这台电脑</h1><p>在电脑上生成配对码，再粘贴到这里。配对码十分钟内有效，只能使用一次。</p>
<form id="form"><input id="code" type="password" autocomplete="off" required placeholder="一次性配对码">
<button id="button">连接</button></form><p id="message"></p>
<script>document.querySelector('#form').onsubmit=async e=>{e.preventDefault();const b=document.querySelector('#button');b.disabled=true;
try{const r=await fetch('/relay/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:document.querySelector('#code').value.trim()})});
document.querySelector('#code').value='';if(!r.ok)throw Error('配对码无效、已过期，或尝试过于频繁。请在电脑上重新生成，稍后再试。');location.replace('/');}
catch(e){document.querySelector('#message').textContent=e.message;}finally{b.disabled=false;}};</script></html>'''


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, port, origin, sessions, backend_port, backend_token):
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('origin must be an HTTPS origin without a trailing slash')
        if not backend_token or any(c in backend_token for c in '\r\n;'):
            raise ValueError('invalid backend token')
        self.origin = origin
        self.authority = parsed.netloc
        self.sessions = sessions
        self.backend_port = backend_port
        self.backend_token = backend_token
        super().__init__(('127.0.0.1', port), Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def parse_request(self):
        # BaseHTTPRequestHandler collapses leading // before handle_request.
        # Reject the raw ambiguous target before that normalization can hide it.
        words = self.raw_requestline.split()
        if len(words) >= 2 and words[1].startswith(b'//'):
            self.requestline = self.raw_requestline.decode('iso-8859-1').rstrip('\r\n')
            self.request_version = 'HTTP/1.1'
            self.command = None
            self.send_error(400, 'Ambiguous request target')
            return False
        return super().parse_request()

    def log_message(self, *args):
        pass  # Never log URLs, authentication headers or message content.

    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def reply(self, status, body=b'', content_type='application/json', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.close_connection = True
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def token(self):
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            return cookie[COOKIE].value if COOKIE in cookie else ''
        except CookieError:
            return ''

    def cookie(self, token, age=SESSION_SECONDS):
        return f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={age}'

    def gate(self):
        if self.headers.get_all('Host') != [self.server.authority]:
            self.reply(421, '{"error":"wrong host"}')
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != self.server.origin:
            self.reply(403, '{"error":"wrong origin"}')
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.reply(403, '{"error":"cross-site request"}')
            return False
        if self.command == 'POST' and origin != self.server.origin:
            self.reply(403, '{"error":"origin required"}')
            return False
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1:
            self.reply(400, '{"error":"unsupported framing"}')
            return False
        try:
            self.body_size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.reply(400); return False
        if self.body_size < 0 or self.body_size > MAX_BODY or (self.command != 'POST' and self.body_size):
            self.reply(413); return False
        return True

    def handle_request(self):
        if not self.gate():
            return
        parsed = urlsplit(self.path)
        if not self.path.startswith('/') or self.path.startswith('//') or parsed.netloc or parsed.scheme:
            self.reply(400); return
        path = parsed.path
        token = self.token()
        valid = self.server.sessions.valid(token)
        if path == '/relay/pair' and self.command == 'POST':
            if self.body_size > 2048:
                self.reply(413); return
            try:
                data = json.loads(self.rfile.read(self.body_size))
                code = data.get('code', '') if isinstance(data, dict) else ''
                if not isinstance(code, str) or len(code) > 128:
                    raise ValueError()
            except (ValueError, OSError):
                self.reply(400); return
            new_token = self.server.sessions.consume(code)
            if not new_token:
                self.reply(403, '{"error":"pairing failed"}'); return
            self.reply(200, '{"ok":true}', extra={'Set-Cookie': self.cookie(new_token)})
            return
        if path == '/relay/logout' and self.command == 'POST':
            self.server.sessions.logout(token)
            self.reply(200, '{"ok":true}', extra={'Set-Cookie': self.cookie('', 0)})
            return
        if not valid:
            if path == '/' and self.command in ('GET', 'HEAD'):
                self.reply(200, LOGIN, 'text/html; charset=utf-8')
            else:
                self.reply(401, '{"error":"请打开首页重新配对"}')
            return
        if path.startswith('/relay/'):
            self.reply(404); return
        self.proxy(token, parsed)

    def proxy(self, token, parsed):
        # Never let remote callers supply local trust headers, legacy cookies or tokens.
        query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != 't'])
        target = parsed.path + ('?' + query if query else '')
        port, headers = self.upstream()
        for name in ('Content-Type', 'Accept', 'Range', 'If-Range', 'Last-Event-ID', 'User-Agent'):
            if name in self.headers:
                headers[name] = self.headers[name]
        if self.command == 'POST':
            headers['Content-Length'] = str(self.body_size)
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
        sent_headers = False
        try:
            conn.putrequest(self.command, target, skip_host=True, skip_accept_encoding=True)
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            remaining = self.body_size
            deadline = time.monotonic()+120
            while remaining:
                if time.monotonic() > deadline or not self.authorized(token):
                    raise ConnectionError('upload expired')
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    raise ConnectionError('incomplete upload')
                conn.send(chunk)
                self.transferred(uploaded=len(chunk))
                remaining -= len(chunk)
            response = conn.getresponse()
            if not self.authorized(token):
                self.reply(401); return
            self.close_connection = True
            self.send_response(response.status)
            allowed = {'content-type', 'content-length', 'content-range', 'accept-ranges',
                       'content-disposition', 'etag', 'last-modified', 'content-encoding'}
            for k, v in response.getheaders():
                if k.lower() in allowed:
                    self.send_header(k, v)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Connection', 'close')
            self.end_headers()
            sent_headers = True
            if self.command != 'HEAD':
                while self.authorized(token):
                    chunk = response.read1(65536)
                    if not chunk or not self.authorized(token):
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    self.transferred(downloaded=len(chunk))
        except (OSError, http.client.HTTPException):
            if not sent_headers:
                self.reply(502, '{"error":"本机遥控服务连接失败"}')
        finally:
            conn.close()

    def authorized(self, token):
        return self.server.sessions.valid(token)

    def transferred(self, uploaded=0, downloaded=0):
        pass

    def upstream(self):
        return self.server.backend_port, {
            'Host': f'127.0.0.1:{self.server.backend_port}',
            'Cookie': 'lbr=' + self.server.backend_token, 'Connection': 'close'}

    def do_GET(self):
        self.handle_request()

    def do_HEAD(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=HERE/'attachments'/'relay-private'/'auth.sqlite3')
    sub = parser.add_subparsers(dest='action', required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--origin', required=True)
    serve.add_argument('--port', type=int, default=18767)
    pair = sub.add_parser('pair')
    pair.add_argument('--label', required=True)
    sub.add_parser('list')
    revoke = sub.add_parser('revoke')
    revoke.add_argument('id')
    args = parser.parse_args()
    sessions = Sessions(args.state)
    if args.action == 'pair':
        print('一次性配对码（十分钟有效；仅粘贴到手机配对页面，不要发到聊天）：')
        print(sessions.issue(args.label))
    elif args.action == 'list':
        for ident, label, expires in sessions.listing():
            print(ident, label, time.strftime('%Y-%m-%d %H:%M', time.localtime(expires)))
    elif args.action == 'revoke':
        print('撤销会话数：', sessions.revoke(args.id))
    else:
        cfg = json.loads((HERE/'remote_config.json').read_text(encoding='utf-8-sig'))
        server = Gateway(args.port, args.origin, sessions, int(cfg.get('port', 8765)), cfg['token'])
        print(f'Relay gateway listening on 127.0.0.1:{args.port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
