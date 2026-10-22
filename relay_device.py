"""Explicit local enrollment and credential-protected desktop relay entry."""
import argparse
import getpass
import hmac
import json
import os
import re
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from relay_gateway import Gateway, Handler, HERE

DEFAULT_CONFIG = HERE/'attachments'/'relay-device'/'device.json'


class DeviceCredentials:
    def __init__(self, path):
        self.path = Path(path)

    def valid(self, token):
        try:
            cfg = json.loads(self.path.read_text(encoding='utf-8'))
            return not cfg.get('revoked', False) and bool(token) and hmac.compare_digest(token, cfg['gateway_secret'])
        except (OSError, ValueError, KeyError, TypeError):
            return False


class DeviceHandler(Handler):
    def token(self):
        values = self.headers.get_all('Authorization', [])
        return values[0][7:] if len(values) == 1 and values[0].startswith('Bearer ') else ''

    def handle_request(self):
        if not self.gate():
            return
        parsed = urlsplit(self.path)
        if not self.path.startswith('/') or self.path.startswith('//') or parsed.netloc or parsed.scheme:
            self.reply(400); return
        token = self.token()
        if not self.authorized(token):
            self.reply(401); return
        if parsed.path.startswith(('/relay/', '/account')):
            self.reply(404); return
        self.proxy(token, parsed)


class DeviceGateway(Gateway):
    def __init__(self, port, origin, config, backend_port, backend_token):
        super().__init__(port, origin, DeviceCredentials(config), backend_port, backend_token)
        self.RequestHandlerClass = DeviceHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never send enrollment material to a different origin.


def request_enrollment(opener, origin, code, account, label):
    code = code.strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', code):
        raise ValueError('绑定码格式不正确：请只粘贴账号页生成的那串绑定码，不含说明文字。')
    payload = json.dumps({'code':code,'account':account,'label':label}).encode()
    request = Request(origin+'/account/enroll', data=payload, headers={
        'Content-Type':'application/json','Origin':origin}, method='POST')
    try:
        with opener.open(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        status = exc.code
        try:
            data = json.loads(exc.read(8192))
            error = data.get('error') if isinstance(data, dict) else None
        except (ValueError, OSError):
            error = None
        finally:
            exc.close()
        known = {
            '链接或绑定码无效、已使用或已过期': '绑定码无效、已使用或已过期。请在账号页生成新绑定码，只复制码本身再试。',
            '账号不符，未绑定': '绑定码所属账号不符。请确认账号页登录的账号与命令中的账号一致。',
            '尝试过于频繁，请稍后重试': '尝试过于频繁，请稍后重试。',
            '设备名额已用完，请联系管理员': '设备名额已用完，请联系管理员。',
            '请求格式错误': '服务器拒绝了请求格式，请检查客户端与服务器版本。',
        }
        detail = known.get(error, '服务器未返回可识别的绑定原因；请提供这个 HTTP 状态码以继续排查。')
        raise ValueError(f'绑定失败（HTTP {status}）：{detail}') from None


def clipboard_binding_code():
    if os.name != 'nt':
        raise ValueError('剪贴板读取目前仅支持 Windows。')
    import win32clipboard
    input('现在将新绑定码复制到这台电脑的剪贴板，然后只按回车读取（不要粘贴到终端）：')
    try:
        win32clipboard.OpenClipboard()
    except Exception:
        raise ValueError('无法打开剪贴板，请稍后重试。') from None
    try:
        if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            raise ValueError('剪贴板中没有文字，请复制绑定码后重试。')
        return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def private_directory(folder):
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        import ntsecuritycon
        import win32api
        import win32con
        import win32security
        # Exact protected DACL; grant:r alone would preserve other explicit ACEs.
        # Never alter the existing single-user frp directory.
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        acl = win32security.ACL()
        flags = win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE
        for principal in (sid, win32security.ConvertStringSidToSid('S-1-5-18')):
            acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, ntsecuritycon.FILE_ALL_ACCESS, principal)
        win32security.SetNamedSecurityInfo(str(folder), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
    else:
        folder.chmod(0o700)


def enroll(args, *, code=None, confirmed=False):
    args.account = args.account.strip().lower()
    parsed = urlsplit(args.origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('HTTPS origin required without trailing slash')
    if args.config.exists():
        raise ValueError('Configuration already exists; revoke and explicitly choose a new file before re-enrolling')
    if not args.certificate.is_file():
        raise ValueError('Verified frps public certificate file is required')
    if not args.frpc.is_file():
        raise ValueError('Installed frpc executable is required')
    if not confirmed:
        print('服务器：'+args.origin+'\n绑定账号：'+args.account+'\n电脑名称：'+args.label)
        if input('确认将这台电脑交由该账号远程访问？输入账号名确认：').strip().lower() != args.account:
            raise ValueError('未确认，未绑定')
    # Prepare protected destination before consuming the one-time enrollment grant.
    private_directory(args.config.parent)
    if code is None:
        code = clipboard_binding_code() if args.code_from_clipboard else getpass.getpass('十分钟绑定码（输入不显示）：')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    cfg = request_enrollment(opener, args.origin, code, args.account, args.label)
    cfg.update(origin=args.origin, local_port=args.port, revoked=False,
               frpc_executable=str(args.frpc.resolve()))
    # Enrollment is one-shot. Persist before generating derivative frpc configuration.
    with args.config.open('x', encoding='utf-8') as output:
        json.dump(cfg, output, ensure_ascii=False, indent=2)
    folder = args.config.parent
    (folder/'token').write_text(cfg['tunnel_secret'], encoding='utf-8')
    (folder/'server.crt').write_bytes(args.certificate.read_bytes())
    toml = f'''serverAddr = {json.dumps(parsed.hostname)}
serverPort = {int(cfg['ingress'])}
loginFailExit = false
auth.method = "token"
auth.additionalScopes = ["HeartBeats", "NewWorkConns"]
auth.tokenSource.type = "file"
auth.tokenSource.file.path = {json.dumps(str(folder/'token'))}
transport.tls.enable = true
transport.tls.trustedCaFile = {json.dumps(str(folder/'server.crt'))}
transport.tls.serverName = {json.dumps(parsed.hostname)}
[[proxies]]
name = {json.dumps('device-'+cfg['id'])}
type = "tcp"
localIP = "127.0.0.1"
localPort = {args.port}
remotePort = {int(cfg['port'])}
'''
    (folder/'frpc.toml').write_text(toml, encoding='utf-8')
    if not confirmed:
        print('已保存独立设备凭据。请管理员按设备 ID 启用专属隧道：'+cfg['id'])
    return cfg


def serve(path):
    cfg = json.loads(path.read_text(encoding='utf-8'))
    local = json.loads((HERE/'remote_config.json').read_text(encoding='utf-8-sig'))
    if cfg.get('revoked'):
        raise ValueError('Device locally revoked')
    server = DeviceGateway(cfg['local_port'], cfg['origin'], path, int(local.get('port',8765)), local['token'])
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest='action', required=True)
    bind = sub.add_parser('enroll')
    bind.add_argument('--origin', required=True)
    bind.add_argument('--account', required=True)
    bind.add_argument('--label', required=True)
    bind.add_argument('--certificate', type=Path, required=True)
    bind.add_argument('--frpc', type=Path, required=True)
    bind.add_argument('--port', type=int, default=18768)
    bind.add_argument('--code-from-clipboard', action='store_true', help='Wait for confirmation, then read Windows clipboard without displaying the code')
    sub.add_parser('serve')
    sub.add_parser('revoke-local')
    args = parser.parse_args()
    if args.action == 'enroll':
        try:
            enroll(args)
        except ValueError as exc:
            parser.exit(1, str(exc)+'\n')
        except (URLError, TimeoutError):
            parser.exit(1, '连接未完成，无法确定服务器是否已绑定。请先检查账号页的电脑列表，不要反复提交。\n')
    elif args.action == 'serve':
        serve(args.config)
    else:
        cfg = json.loads(args.config.read_text(encoding='utf-8'))
        cfg['revoked'] = True
        cfg['gateway_secret'] = secrets.token_urlsafe(32)
        temp = args.config.with_suffix('.tmp')
        temp.write_text(json.dumps(cfg), encoding='utf-8')
        temp.replace(args.config)
        print('本机入口已撤销；请在账号页同时撤销云端绑定。')


if __name__ == '__main__':
    main()
