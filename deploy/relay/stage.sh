#!/usr/bin/env bash
# Run from the extracted deployment directory. Never changes Caddy or legacy frps.
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run with sudo bash stage.sh'; exit 1; }
cd -- "$(dirname -- "$0")"
test -x /usr/bin/python3
test -x /usr/local/bin/frps
getent passwd frp >/dev/null
if ! getent passwd agent-relay >/dev/null; then
    useradd --system --home-dir /var/lib/agent-relay --shell /usr/sbin/nologin agent-relay
fi
# Refuse to replace an existing install; upgrades need their own reviewed rollback.
if [[ -e /opt/agent-relay/relay_cloud.py || -e /etc/systemd/system/agent-relay.service ]]; then
    echo 'Existing relay install found; nothing overwritten.'
    exit 1
fi
install -d -o root -g root -m 755 /opt/agent-relay
install -d -o agent-relay -g agent-relay -m 700 /var/lib/agent-relay
for file in relay_cloud.py relay_accounts.py relay_gateway.py relay_account.html relay_account_legacy.html; do
    install -o root -g root -m 644 "$file" "/opt/agent-relay/$file"
done
install -o root -g root -m 644 agent-relay.service /etc/systemd/system/agent-relay.service
install -o root -g root -m 644 frps-device@.service /etc/systemd/system/frps-device@.service
systemctl daemon-reload
systemctl enable --now agent-relay.service
for attempt in {1..30}; do
    if curl --fail --silent --max-time 2 --output /dev/null -H 'Host: 8.166.15.235' http://127.0.0.1:18770/account; then
        echo 'Account service ready on loopback 18770. Caddy and legacy frps unchanged.'
        exit 0
    fi
    sleep 1
done
echo 'Readiness not confirmed. Inspect: systemctl status agent-relay.service --no-pager -l'
exit 1
