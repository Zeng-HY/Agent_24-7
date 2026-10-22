"""Trusted, loopback-only multi-user relay behind Caddy HTTPS.

Each device gets its own frps listener, token and fixed loopback proxy port.
No user-selected backend URL, arbitrary port or shared frp registration token.
"""
import argparse
from http.cookies import SimpleCookie, CookieError
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from relay_accounts import Accounts, TTL
from relay_gateway import Handler

COOKIE = '__Host-ar_account'
DEVICE_COOKIE = '__Host-ar_device'


class Cloud(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, port, origin, accounts):
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('HTTPS origin required, without trailing slash')
        self.origin, self.authority = origin, parsed.netloc
        self.sessions = accounts
        super().__init__(('127.0.0.1', port), CloudHandler)


class CloudHandler(Handler):
    def read_cookie(self, name):
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            return cookie[name].value if name in cookie else ''
        except CookieError:
            return ''

    def token(self):
        return self.read_cookie(COOKIE)

    def cookie(self, token, age=TTL, name=COOKIE):
        return f'{name}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={age}'

    def json_reply(self, status, data, extra=None):
        self.reply(status, json.dumps(data, ensure_ascii=False), extra=extra)

    def handle_request(self):
        if not self.gate():
            return
        parsed = urlsplit(self.path)
        if not self.path.startswith('/') or self.path.startswith('//') or parsed.netloc or parsed.scheme:
            self.reply(400); return
        token = self.token()
        path = parsed.path
        if path == '/account' and self.command in ('GET', 'HEAD'):
            self.reply(200, (Path(__file__).with_name('relay_account_legacy.html')).read_bytes(), 'text/html; charset=utf-8')
            return
        if path.startswith('/account/'):
            self.account_request(path, token)
            return
        # Old local pairing endpoints are never reachable via the cloud router.
        if path.startswith('/relay/'):
            self.reply(404); return
        if not self.server.sessions.valid(token):
            if path == '/' and self.command in ('GET', 'HEAD'):
                self.reply(303, extra={'Location':'/account'})
            else:
                self.reply(401)
            return
        self.device_id = self.read_cookie(DEVICE_COOKIE)
        self.route = self.server.sessions.device(token, self.device_id)
        if not self.route:
            self.reply(403, '{"error":"请在账号页选择已绑定的电脑"}')
            return
        self.uploaded = self.downloaded = 0
        try:
            self.proxy(token, parsed)
        finally:
            self.server.sessions.usage(self.device_id, self.uploaded, self.downloaded, 1)

    def authorized(self, token):
        # Recheck both session and ownership/revocation during uploads and SSE.
        return self.server.sessions.device(token, self.device_id) is not None

    def upstream(self):
        return self.route['port'], {'Host':self.server.authority,
            'Authorization':'Bearer '+self.route['gateway_secret'],
            'Origin':self.server.origin, 'Connection':'close'}

    def transferred(self, uploaded=0, downloaded=0):
        self.uploaded += uploaded
        self.downloaded += downloaded

    def account_request(self, path, token):
        store = self.server.sessions
        if self.command in ('GET', 'HEAD') and path == '/account/state':
            if not store.valid(token):
                self.reply(401); return
            self.json_reply(200, {'devices':store.devices(token), 'usage':store.usage_for(token)})
            return
        if self.command != 'POST':
            self.reply(405); return
        if self.body_size > 8192:
            self.reply(413); return
        try:
            data = json.loads(self.rfile.read(self.body_size))
            if not isinstance(data, dict) or any(not isinstance(v, str) for v in data.values()):
                raise ValueError('请求格式错误')
            public = ('/account/login', '/account/register', '/account/reset', '/account/enroll')
            if path in public:
                # Caddy is the only public entry. Do not trust forwarded client IPs.
                store.rate('public-auth', 30, 60)
            elif not store.valid(token):
                self.reply(401); return
            extra = None
            result = {'ok':True}
            if path == '/account/register':
                store.register(data.get('name',''), data.get('password',''), data.get('code',''))
            elif path == '/account/login':
                new = store.login(data.get('name',''), data.get('password',''))
                extra = {'Set-Cookie':self.cookie(new)}
            elif path == '/account/logout':
                store.logout(token)
                extra = {'Set-Cookie':self.cookie('',0)}
            elif path == '/account/password':
                store.change_password(token, data.get('old',''), data.get('password',''))
                extra = {'Set-Cookie':self.cookie('',0)}
            elif path == '/account/reset':
                store.reset(data.get('code',''), data.get('password',''))
            elif path == '/account/bind':
                store.rate('bind:'+store.owner(token), 5, 3600)
                result = {'code':store.grant('bind', store.owner(token)), 'expires_in':600}
            elif path == '/account/enroll':
                device = store.bind(data.get('code',''), data.get('label',''), data.get('account',''))
                result = {k:device[k] for k in ('id','label','gateway_secret','tunnel_secret','ingress','port')}
            elif path == '/account/select':
                ident = data.get('id','')
                if not store.device(token, ident):
                    self.reply(404); return
                extra = {'Set-Cookie':self.cookie(ident, name=DEVICE_COOKIE)}
            elif path == '/account/revoke':
                if not store.revoke(token, data.get('id','')):
                    self.reply(404); return
            else:
                self.reply(404); return
            self.json_reply(200, result, extra)
        except (ValueError, UnicodeError) as exc:
            self.json_reply(400, {'error':str(exc) if not isinstance(exc, json.JSONDecodeError) else '请求格式错误'})


def export_device(store, ident, directory):
    """Explicit administrator action. Writes private per-device frps files only."""
    with store.connect() as db:
        row = db.execute('SELECT * FROM devices WHERE id=? AND revoked=0', (ident,)).fetchone()
    if not row:
        raise ValueError('active device not found')
    folder = Path(directory)/ident
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        folder.chmod(0o700)
    token_path = folder/'token'
    token_path.write_text(row['tunnel_secret'], encoding='utf-8')
    config = f'''bindAddr = "0.0.0.0"
bindPort = {row['ingress']}
proxyBindAddr = "127.0.0.1"
allowPorts = [{{ single = {row['port']} }}]
maxPortsPerClient = 1
auth.method = "token"
auth.additionalScopes = ["HeartBeats", "NewWorkConns"]
auth.tokenSource.type = "file"
auth.tokenSource.file.path = {json.dumps(str(token_path))}
transport.tls.force = true
transport.tls.certFile = "/etc/frp/server.crt"
transport.tls.keyFile = "/etc/frp/server.key"
'''
    (folder/'frps.toml').write_text(config, encoding='utf-8')
    if os.name != 'nt':
        token_path.chmod(0o600)
        (folder/'frps.toml').chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--origin', required=True)
    serve.add_argument('--port', type=int, default=18770)
    invite = sub.add_parser('invite')
    invite.add_argument('--origin', required=True)
    reset = sub.add_parser('reset')
    reset.add_argument('name')
    reset.add_argument('--origin', required=True)
    sub.add_parser('devices')
    export = sub.add_parser('export-device')
    export.add_argument('id')
    export.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        os.umask(0o077)
    store = Accounts(args.state)
    if args.action == 'serve':
        Cloud(args.port, args.origin, store).serve_forever()
    elif args.action == 'invite':
        print(args.origin+'/account#invite='+store.grant('invite', ttl=86400))
    elif args.action == 'reset':
        row = store.user(args.name)
        if not row:
            parser.error('account not found')
        print(args.origin+'/account#reset='+store.grant('reset', row['id']))
    elif args.action == 'devices':
        with store.connect() as db:
            for row in db.execute('SELECT d.id,u.name,d.label,d.ingress,d.port,d.revoked FROM devices d '
                                  'JOIN users u ON d.owner=u.id'):
                print(json.dumps(dict(row), ensure_ascii=False))
    else:
        export_device(store, args.id, args.directory)
        print('Device configuration written; no service was started.')


if __name__ == '__main__':
    main()
