"""pocketagentdesk.com next to the IP: app. serves the relay, the bare name and www serve the site (deploy/site).

Run on the relay as root from the unpacked package, after update-027.sh has put in relay files that know
--alias-origin. Nothing changes until every check passes; when a later step fails, what was there is put back.

    sudo python3 switch-domain.py --check      only checks; changes nothing
    sudo python3 switch-domain.py              switches
    sudo python3 switch-domain.py --rollback   back to the IP alone

The server as found on 2026-10-31: Caddy 2.6.2 with `auto_https off`, only on 443, serving the IP with a Let's Encrypt
certificate that Certbot renews every few days by briefly starting its own server on port 80 (standalone). The domain
needs certificates that Caddy fetches itself, and port 80. So:
1. checks: the three names point here, the site has no blanks, Caddy and Certbot are set up as above;
2. the site goes to /var/www/pocketagentdesk;
3. Caddy loses `auto_https off` (it now fetches the domain's certificates and redirects http to https) and takes port
   80; the IP site and its Certbot certificate stay as they are;
4. Certbot's renewal of the IP moves to 127.0.0.1:18402, and Caddy passes the IP's challenge requests on port 80 to it;
   a renewal dry run must pass;
5. a systemd drop-in makes the relay answer on the domain (the main address, used in email links) and on the IP
   (an alias, and the address old FRP computers were enrolled with);
6. both addresses, the site and the http redirects are checked over verified HTTPS.
"""
import argparse
import http.client
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import time

IP = '8.166.15.235'
APP, SITE, WWW = 'app.pocketagentdesk.com', 'pocketagentdesk.com', 'www.pocketagentdesk.com'
HERE = Path(__file__).resolve().parent
CADDYFILE = Path('/etc/caddy/Caddyfile')
BACKUP = Path('/etc/caddy/Caddyfile.before-domain')
DRAFT = Path('/etc/caddy/Caddyfile.domain-candidate')
WEBROOT = Path('/var/www/pocketagentdesk')
UNIT = 'agent-relay-027.service'
DROP_IN = Path('/etc/systemd/system/agent-relay-027.service.d/domain.conf')
RELAY = Path('/opt/agent-relay-027/relay_service.py')
RENEWAL = Path(f'/etc/letsencrypt/renewal/{IP}.conf')
# not beside it: Certbot reads every *.conf in that folder
RENEWAL_BACKUP = Path(f'/var/backups/agent-relay/{IP}.conf.before-domain')
CHALLENGE_PORT = 18402
MARK = '# pocketagentdesk.com: added by switch-domain.py; the IP site above is unchanged'
EXEC = ('/opt/agent-relay-027/.venv/bin/python /opt/agent-relay-027/relay_service.py --state /var/lib/agent-relay/accounts.sqlite3 '
        f'--origin https://{APP} --alias-origin https://{IP} --legacy-origin https://{IP} --port 18771 --trusted-proxy')
SITES = f'''
{MARK}
http://{IP} {{
	# Certbot renews the IP's certificate through here (http01_port {CHALLENGE_PORT} in its renewal settings)
	handle /.well-known/acme-challenge/* {{
		reverse_proxy 127.0.0.1:{CHALLENGE_PORT}
	}}
	handle {{
		redir https://{IP}{{uri}} permanent
	}}
}}
{APP} {{
	reverse_proxy 127.0.0.1:18771 {{
		header_up X-AR-Client-IP {{remote_host}}
		header_up -Tailscale-User-Login
		flush_interval -1
	}}
}}
{SITE} {{
	root * {WEBROOT.as_posix()}
	try_files {{path}} {{path}}.html
	file_server
	header {{
		X-Content-Type-Options nosniff
		Referrer-Policy no-referrer
		Content-Security-Policy "default-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
	}}
}}
{WWW} {{
	redir https://{SITE}{{uri}} permanent
}}
'''
FAILED = (OSError, ssl.SSLError, http.client.HTTPException)


def fail(message):
    raise SystemExit('没有改动：' + message)


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, text=True, capture_output=True, **kwargs).stdout


def listening(port):
    """The names of the programs listening on this TCP port (ss -lntp)."""
    out = run('ss', '-Hlntp', 'sport', '=', f':{port}')
    return set(re.findall(r'users:\(\("([^"]+)"', out)) or ({'?'} if out.strip() else set())


def checks():
    if os.geteuid() != 0: fail('用 sudo 运行')
    if '--alias-origin' not in RELAY.read_text(): fail('服务器上的中转还是旧版本，先运行 update-027.sh')
    if DROP_IN.exists() or BACKUP.exists(): fail('好像已经切换过（附加设置或 Caddyfile 备份已经在了）；要退回用 --rollback')
    started = run('systemctl', 'show', '-p', 'ExecStart', '--value', UNIT)
    if f'--origin https://{IP} ' not in started: fail('中转的启动参数和预想的不一样，把下面这行发给我看：\n' + started)
    for name in (APP, SITE, WWW):
        try: found = {a[4][0] for a in socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)}
        except OSError: found = set()
        if IP not in found: fail(f'{name} 还没指向 {IP}（现在是 {sorted(found) or "查不到"}）；在云解析里加好 A 记录，等十分钟再试')
    site = HERE / 'site'
    pages = sorted(site.glob('*')) if site.is_dir() else []
    if not any(p.name == 'index.html' for p in pages): fail('包里没有 site/index.html')
    for page in pages:
        if page.suffix in ('.html', '.css') and '待填' in page.read_text(encoding='utf-8'): fail(f'site/{page.name} 里还有没填的“待填”')
    text = CADDYFILE.read_text()
    if MARK in text or APP in text or f'http://{IP}' in text: fail('Caddyfile 里已经有这些站点了，先看一下再说')
    if len(re.findall(r'(?m)^[ \t]*auto_https off[ \t]*$', text)) != 1 or text.count(f'https://{IP} {{') != 1:
        fail('Caddyfile 和 10-31 看到的不一样（auto_https off、https://8.166.15.235 站点），把它发给我看')
    if listening(80): fail(f'80 端口已经有程序在用：{listening(80)}')
    if listening(CHALLENGE_PORT): fail(f'{CHALLENGE_PORT} 端口已经有程序在用')
    if not shutil.which('certbot'): fail('找不到 certbot')
    renewal = RENEWAL.read_text()
    if not re.search(r'(?m)^authenticator\s*=\s*standalone\s*$', renewal) or '[renewalparams]' not in renewal:
        fail(f'{RENEWAL} 不是 standalone 续期，和 10-31 看到的不一样')
    if re.search(r'(?m)^(http01_port|http01_address|pre_hook|post_hook)\s*=', renewal):
        fail(f'{RENEWAL} 里已经有端口或 hook 设置，先看一下再说')
    return text


def candidate(text):
    return re.sub(r'(?m)^[ \t]*auto_https off[ \t]*\n', '', text, count=1).rstrip('\n') + '\n' + SITES


def install_site():
    fresh = WEBROOT.with_name(WEBROOT.name + '.new')
    shutil.rmtree(fresh, ignore_errors=True)
    shutil.copytree(HERE / 'site', fresh)
    for path in [fresh, *fresh.rglob('*')]:
        os.chown(path, 0, 0)
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    if WEBROOT.exists():
        WEBROOT.rename(WEBROOT.with_name(WEBROOT.name + '.previous-' + time.strftime('%Y%m%d-%H%M%S')))
    fresh.rename(WEBROOT)


def get(host, path, secure=True):
    """(status, headers) of a GET; over HTTPS the certificate must be valid for host."""
    conn = (http.client.HTTPSConnection(host, timeout=10, context=ssl.create_default_context()) if secure
            else http.client.HTTPConnection(host, timeout=10))
    try:
        conn.request('GET', path)
        response = conn.getresponse()
        response.read(65536)
        return response.status, dict(response.getheaders())
    finally:
        conn.close()


def wait_for_certificate(host, seconds):
    """Caddy fetches the certificate after the reload; until then the handshake fails. True once it answers."""
    started = time.monotonic()
    said = started
    while True:
        try:
            get(host, '/')
            return True
        except FAILED:
            now = time.monotonic()
            if now - started > seconds: return False
            if now - said >= 30:
                print(f'还在等 {host} 的证书（{int(now - started)} 秒）……')
                said = now
            time.sleep(5)


def caddy_reload(path):
    run('caddy', 'validate', '--config', str(path), '--adapter', 'caddyfile')
    if path != CADDYFILE: shutil.copy2(path, CADDYFILE)
    run('systemctl', 'reload', 'caddy')


def restart_relay():
    run('systemctl', 'daemon-reload')
    run('systemctl', 'restart', UNIT)
    for _ in range(30):
        time.sleep(1)
        try:
            if get(IP, '/account')[0] == 200: return
        except FAILED: pass
    raise RuntimeError('中转重启后没起来')


def renew_through_caddy():
    """Certbot's own server moves off port 80 to the loopback; Caddy passes the IP's challenges on to it."""
    text = RENEWAL.read_text()
    RENEWAL.write_text(text.replace('[renewalparams]\n', f'[renewalparams]\nhttp01_port = {CHALLENGE_PORT}\nhttp01_address = 127.0.0.1\n', 1))
    result = subprocess.run(['certbot', 'renew', '--cert-name', IP, '--dry-run', '--no-random-sleep-on-renew'],
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError('IP 证书的续期试运行没通过：\n' + (result.stdout + result.stderr)[-1500:])


def verify(checks):
    for host, path, expected in checks:
        status, headers = get(host, path)
        if status != expected: raise RuntimeError(f'https://{host}{path} 返回 {status}')
        if host == WWW and headers.get('Location') != f'https://{SITE}/': raise RuntimeError('www 没有转到主域名')
        print(f'通过 https://{host}{path}：{status}')


def verify_redirects(hosts):
    for host in hosts:
        status, headers = get(host, '/', secure=False)
        if status not in (301, 308) or not headers.get('Location', '').startswith(f'https://{host}/'):
            raise RuntimeError(f'http://{host}/ 没有转到 https（{status}）')
        print(f'通过 http://{host}/ 转到 https')


def finish_site():
    """The site's two certificates may come later than app.'s (Let's Encrypt retries from several places). They do not
    hold up the switch: Caddy keeps trying by itself, and this only checks the pages once they are there."""
    late = [host for host in (SITE, WWW) if not wait_for_certificate(host, 300)]
    if late:
        print(f'{"、".join(late)} 的证书还在申请，Caddy 会自己接着试，不用再运行本脚本；过一会儿再打开 https://{SITE} 看看。')
        return
    verify([(SITE, '/', 200), (SITE, '/privacy', 200), (SITE, '/support', 200), (WWW, '/', 301)])
    verify_redirects([SITE])


def rollback():
    if os.geteuid() != 0: raise SystemExit('用 sudo 运行')
    stamp = time.strftime('%Y%m%d-%H%M%S')
    if BACKUP.exists():
        caddy_reload(BACKUP)
        BACKUP.rename(BACKUP.with_name(BACKUP.name + '.' + stamp))
        print('Caddy 换回了原来的设置（只用 443，80 端口还给 Certbot）')
    if RENEWAL_BACKUP.exists():
        shutil.copy2(RENEWAL_BACKUP, RENEWAL)
        RENEWAL_BACKUP.rename(RENEWAL_BACKUP.with_name(RENEWAL_BACKUP.name + '.' + stamp))
        print('Certbot 的续期设置换回了原样')
    if DROP_IN.exists():
        DROP_IN.unlink()
        restart_relay()
        print('中转只认 IP 了')
    try: print(f'https://{IP}/account：{get(IP, "/account")[0]}')
    except FAILED as exc: print(f'https://{IP}/account 打不开：{exc}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='只检查，不改动')
    parser.add_argument('--rollback', action='store_true', help='退回只用 IP')
    args = parser.parse_args()
    os.umask(0o022)
    if args.rollback: return rollback()
    original = checks()
    DRAFT.write_text(candidate(original))
    try: run('caddy', 'validate', '--config', str(DRAFT), '--adapter', 'caddyfile')
    except subprocess.CalledProcessError as exc: fail('新的 Caddy 设置没通过检查：\n' + (exc.stderr or exc.stdout)[-2000:])
    if args.check:
        print('检查都通过了，什么都没改。去掉 --check 再运行一次就切换。')
        return
    if CADDYFILE.read_text() != original: fail('Caddyfile 刚才被改过，重新运行一次')
    shutil.copy2(CADDYFILE, BACKUP)
    RENEWAL_BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RENEWAL, RENEWAL_BACKUP)
    try:
        install_site()
        caddy_reload(DRAFT)
        if get(IP, '/account')[0] != 200: raise RuntimeError('IP 打不开了')
        print('Caddy 加上了域名，IP 照常能用')
        renew_through_caddy()
        print('IP 证书的续期试运行通过了（经 80 端口转给 Certbot）')
        if not wait_for_certificate(APP, 300): raise RuntimeError(f'{APP} 等了 5 分钟还没拿到证书')
        print(f'{APP} 的证书拿到了')
        DROP_IN.parent.mkdir(parents=True, exist_ok=True)
        DROP_IN.write_text(f'# switch-domain.py: the relay answers on {APP} (main) and {IP}\n[Service]\nExecStart=\nExecStart={EXEC}\n')
        restart_relay()
        verify([(APP, '/account', 200), (APP, '/account/config', 200), (IP, '/account', 200)])
        verify_redirects([APP, IP])
    except BaseException as exc:
        print('出错了，正在换回原来的设置：', exc)
        rollback()
        raise SystemExit(1)
    print(f'中转切换完成：服务 https://{APP}，旧地址 https://{IP} 照常可用。')
    try: finish_site()
    except FAILED + (RuntimeError,) as exc: print(f'网站这边还有问题（{exc}），中转不受影响；把这段发给我看。')
    print('退回：sudo python3 switch-domain.py --rollback')


if __name__ == '__main__':
    main()
