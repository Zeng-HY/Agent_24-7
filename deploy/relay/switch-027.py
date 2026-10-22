"""Switch known account routes to 0.27, preserving speed tools and rollback."""
import http.client
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import re


def candidate(text):
    if text.count('reverse_proxy @ar_application 127.0.0.1:18770 {')!=1 or text.count('reverse_proxy @ar_accounts 127.0.0.1:18770 {')!=1:
        raise ValueError('Unexpected live routes; nothing changed')
    if 'X-AR-Client-IP' in text or '127.0.0.1:18771' in text:
        raise ValueError('Already migrated or custom configuration; inspect first')
    def convert(match):
        body=re.sub(r'(?m)^[ \t]*header_up -Authorization[ \t]*\n','',match['body'])
        return 'reverse_proxy '+match['matcher']+' 127.0.0.1:18771 {\n            header_up X-AR-Client-IP {remote_host}'+body+'}'
    updated,count=re.subn(r'reverse_proxy (?P<matcher>@ar_application|@ar_accounts) 127\.0\.0\.1:18770 \{(?P<body>[^{}]*)\}',convert,text)
    if count!=2:raise ValueError('Unexpected proxy configuration; nothing changed')
    return updated


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true',help='Validate candidate without changing the live route')
    args=parser.parse_args()
    os.umask(0o077)
    path=Path('/etc/caddy/Caddyfile');backup=Path('/etc/caddy/Caddyfile.before-027')
    draft=Path('/etc/caddy/Caddyfile.027-candidate')
    if backup.exists():raise SystemExit('Backup exists; inspect before retrying')
    original=path.read_text();updated=candidate(original)
    draft.write_text(updated)
    subprocess.run(['caddy','validate','--config',str(draft),'--adapter','caddyfile'],check=True)
    if args.check:
        print('0.27 route candidate validated. Live Caddy configuration unchanged.')
        return
    if path.read_text()!=original:raise SystemExit('Live configuration changed; nothing replaced')
    shutil.copy2(path,backup)
    try:
        path.write_text(updated);subprocess.run(['systemctl','reload','caddy'],check=True)
        for route,status in [('/account',200),('/account/ui.css',200),('/account/config',200),('/account/state',401),('/speed',401)]:
            conn=http.client.HTTPSConnection('8.166.15.235',timeout=10)
            try:
                conn.request('GET',route);response=conn.getresponse();response.read()
                if response.status!=status:raise ValueError('Public check failed: '+route)
            finally:conn.close()
        print('0.27 account entry enabled. Old device tunnels retained. SMTP registration remains gated by its private configuration.')
    except BaseException:
        shutil.copy2(backup,path);subprocess.run(['systemctl','reload','caddy'],check=True)
        print('Old account routes restored.');raise


if __name__=='__main__':main()
