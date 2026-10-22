"""Expose only /account routes before legacy authentication; run with sudo."""
from pathlib import Path
import os
import re
import shutil
import subprocess


def candidate(text):
    pattern = r'(?m)^([ \t]*)route[ \t]*\{[ \t]*$'
    if len(re.findall(pattern, text)) != 1 or '@ar_accounts' in text or '127.0.0.1:18770' in text:
        raise ValueError('Unexpected configuration or account route already present; nothing changed')
    if len(re.findall(r'(?m)^[ \t]*basicauth[ \t]*\{[ \t]*$', text)) != 1:
        raise ValueError('Expected one unchanged legacy basicauth block')
    def insert(match):
        pad = match.group(1)
        lines = ['@ar_accounts path /account /account/*', 'route {',
                 '    reverse_proxy @ar_accounts 127.0.0.1:18770 {',
                 '        header_up -Authorization', '        header_up -Tailscale-User-Login',
                 '        flush_interval -1', '    }']
        return '\n'.join(pad + line for line in lines)
    return re.sub(pattern, insert, text)


def main():
    os.umask(0o077)
    path = Path('/etc/caddy/Caddyfile')
    backup = Path('/etc/caddy/Caddyfile.before-accounts')
    draft = Path('/etc/caddy/Caddyfile.accounts-candidate')
    if backup.exists():
        raise SystemExit('Backup already exists; stop and inspect before retrying')
    original = path.read_text()
    updated = candidate(original)
    draft.write_text(updated)
    subprocess.run(['caddy', 'validate', '--config', str(draft), '--adapter', 'caddyfile'], check=True)
    if path.read_text() != original:
        raise SystemExit('Live configuration changed during validation; nothing replaced')
    shutil.copy2(path, backup)
    try:
        path.write_text(updated)
        subprocess.run(['systemctl', 'reload', 'caddy'], check=True)
    except BaseException:
        shutil.copy2(backup, path)
        subprocess.run(['systemctl', 'reload', 'caddy'], check=True)
        raise
    print('Account route enabled. Legacy routes and authentication preserved.')
    print('Rollback file: ' + str(backup))


if __name__ == '__main__':
    main()
