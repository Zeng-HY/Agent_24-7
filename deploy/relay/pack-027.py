"""The server package: dist/agent-relay-0.27.0-dev.zip, everything at its top level, as README-027.md unpacks it.

    python deploy/relay/pack-027.py
"""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
RELAY = ['relay_service.py', 'relay_identity.py', 'relay_accounts.py', 'relay_mail.py', 'relay_transport.py', 'relay_pages.py',
         'windows-version.json', 'relay_routing.js', 'relay_account.html', 'relay_account.css', 'relay_account.js', 'requirements-relay.txt']
DEPLOY = ['stage-027.sh', 'update-027.sh', 'switch-027.py', 'configure-mail.py', 'agent-relay-027.service', 'README-027.md']


def main():
    out = ROOT / 'dist' / 'agent-relay-0.27.0-dev.zip'
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in RELAY:
            z.write(ROOT / name, name)
        for name in ['theme.js','theme.css','favicon.svg','favicon-dark.svg','favicon.ico','icon-maskable-512.png','apple-touch-icon.png']:
            z.write(ROOT/'static'/name, 'static/'+name)
        for name in DEPLOY:
            info = zipfile.ZipInfo.from_file(ROOT / 'deploy' / 'relay' / name, name)
            if name.endswith('.sh'):
                info.external_attr = 0o755 << 16
            data=(ROOT / 'deploy' / 'relay' / name).read_bytes()
            if name.endswith('.sh'):data=data.replace(b'\r\n',b'\n')
            z.writestr(info, data, zipfile.ZIP_DEFLATED)
    print(out)


if __name__ == '__main__':
    main()
