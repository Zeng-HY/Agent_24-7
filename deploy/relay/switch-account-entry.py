"""Switch application paths to account authentication; preserve legacy speed tools.

Run on the relay as root. Validates the bound tunnel before switching, then checks
public anonymous access over verified HTTPS. Never prints stored credentials.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess

HOST = '8.166.15.235'


def candidate(text):
    pattern = r'(?m)^([ \t]*)route[ \t]*\{[ \t]*$'
    if len(re.findall(pattern, text)) != 1 or '@ar_application' in text:
        raise ValueError('Unexpected configuration or already switched; nothing changed')
    for expected in ('@ar_accounts path /account /account/*',
                     'reverse_proxy @ar_accounts 127.0.0.1:18770',
                     'reverse_proxy 127.0.0.1:18081'):
        if text.count(expected) != 1:
            raise ValueError('Expected staged account and legacy routes; nothing changed')
    if len(re.findall(r'(?m)^[ \t]*basicauth[ \t]*\{[ \t]*$',text)) != 1:
        raise ValueError('Expected unchanged legacy authentication')
    def insert(match):
        pad = match.group(1)
        lines = ['@ar_application not path /speed /upload-test', 'route {',
                 '    reverse_proxy @ar_application 127.0.0.1:18770 {',
                 '        header_up -Authorization', '        header_up -Tailscale-User-Login',
                 '        flush_interval -1', '    }']
        return '\n'.join(pad+line for line in lines)
    return re.sub(pattern,insert,text)


def request(connection, method, path, headers=None):
    try:
        connection.request(method,path,headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read(65536)
    finally:
        connection.close()


def check_tunnel(device_id):
    with sqlite3.connect('file:/var/lib/agent-relay/accounts.sqlite3?mode=ro',uri=True) as db:
        row = db.execute('SELECT port,gateway_secret FROM devices WHERE id=? AND revoked=0',
                         (device_id,)).fetchone()
    if not row:
        raise ValueError('Active device not found; nothing changed')
    status, _, body = request(http.client.HTTPConnection('127.0.0.1',row[0],timeout=10),
        'GET','/api/status',{'Host':HOST,'Authorization':'Bearer '+row[1],'Origin':'https://'+HOST})
    if status != 200 or json.loads(body).get('ok') is not True:
        raise ValueError('Authenticated device tunnel check failed; nothing changed')
    status, _, _ = request(http.client.HTTPConnection('127.0.0.1',18770,timeout=10),
                           'GET','/account',{'Host':HOST})
    if status != 200:
        raise ValueError('Account service not ready; nothing changed')
    print('Authenticated tunnel and account service checks passed.')


def check_public():
    checks = [('GET','/account',200),('GET','/',303),('GET','/api/status',401),
              ('GET','/account/state',401),('GET','/speed',401),('POST','/upload-test',401)]
    for method,path,expected in checks:
        status,headers,_ = request(http.client.HTTPSConnection(HOST,timeout=10),method,path)
        if status != expected or (path == '/' and headers.get('Location') != '/account'):
            raise ValueError(f'Public check failed: {method} {path} returned {status}')
        print(f'PASS {method} {path}: {status}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',required=True)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{32}',args.device):
        parser.error('Invalid device ID')
    os.umask(0o077)
    path = Path('/etc/caddy/Caddyfile')
    backup = Path('/etc/caddy/Caddyfile.before-account-entry')
    draft = Path('/etc/caddy/Caddyfile.account-entry-candidate')
    if backup.exists():
        raise SystemExit('Backup already exists; inspect before retrying')
    original = path.read_text()
    updated = candidate(original)
    check_tunnel(args.device)
    draft.write_text(updated)
    subprocess.run(['caddy','validate','--config',str(draft),'--adapter','caddyfile'],check=True)
    if path.read_text() != original:
        raise SystemExit('Configuration changed during validation; nothing replaced')
    shutil.copy2(path,backup)
    try:
        path.write_text(updated)
        subprocess.run(['systemctl','reload','caddy'],check=True)
        check_public()
    except BaseException:
        shutil.copy2(backup,path)
        subprocess.run(['systemctl','reload','caddy'],check=True)
        print('Previous configuration restored. Account entry switch did not pass.')
        raise
    print('Account entry enabled and public checks passed.')
    print('Rollback file: '+str(backup))


if __name__ == '__main__':
    main()
