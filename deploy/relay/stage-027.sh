#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
cd -- "$(dirname -- "$0")"
getent passwd agent-relay >/dev/null
test -f /var/lib/agent-relay/accounts.sqlite3
test ! -e /opt/agent-relay-027/relay_service.py || { echo 'Already staged; inspect before retrying'; exit 1; }
install -d -o root -g root -m 700 /var/backups/agent-relay
backup="/var/backups/agent-relay/accounts.before-027-$(date +%Y%m%d-%H%M%S).sqlite3"
python3 - "$backup" <<'PY'
import sqlite3,sys,os
os.umask(0o077)
with sqlite3.connect('/var/lib/agent-relay/accounts.sqlite3') as source, sqlite3.connect(sys.argv[1]) as target:
    source.backup(target)
PY
install -d -o root -g root -m 755 /opt/agent-relay-027
for file in relay_service.py relay_identity.py relay_accounts.py relay_mail.py relay_transport.py relay_pages.py relay_routing.js relay_account.html relay_account.css relay_account.js requirements-relay.txt; do
    install -o root -g root -m 644 "$file" "/opt/agent-relay-027/$file"
done
if ! python3 -m venv /opt/agent-relay-027/.venv; then
    apt-get update -qq
    apt-get install -y python3-venv
    python3 -m venv /opt/agent-relay-027/.venv
fi
PIP_CONFIG_FILE=/dev/null PIP_EXTRA_INDEX_URL='' PIP_TRUSTED_HOST='' /opt/agent-relay-027/.venv/bin/python -m pip install --disable-pip-version-check --index-url https://pypi.org/simple -r /opt/agent-relay-027/requirements-relay.txt
install -o root -g root -m 644 agent-relay-027.service /etc/systemd/system/agent-relay-027.service
systemctl daemon-reload
systemctl enable --now agent-relay-027.service
for attempt in {1..30}; do
    if curl --fail --silent --max-time 2 --output /dev/null -H 'Host: 8.166.15.235' http://127.0.0.1:18771/account; then
        echo '0.27 ready on loopback 18771; public routes and old tunnels unchanged.'
        exit 0
    fi
    sleep 1
done
echo 'Readiness failed; inspect agent-relay-027.service. Do not switch public routes.'
exit 1
