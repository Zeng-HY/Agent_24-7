#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run with sudo bash enable-device.sh DEVICE_ID'; exit 1; }
relay_device=${1:-}
[[ "$relay_device" =~ ^[0-9a-f]{32}$ ]] || { echo 'Invalid device ID'; exit 1; }
test -f /etc/systemd/system/frps-device@.service
install -d -o root -g frp -m 750 /etc/frp/devices
/usr/bin/python3 /opt/agent-relay/relay_cloud.py --state /var/lib/agent-relay/accounts.sqlite3 \
    export-device "$relay_device" --directory /etc/frp/devices
chown -R frp:frp "/etc/frp/devices/$relay_device"
runuser -u frp -- /usr/local/bin/frps verify -c "/etc/frp/devices/$relay_device/frps.toml"
systemctl enable --now "frps-device@$relay_device.service"
systemctl is-active "frps-device@$relay_device.service"
echo 'Dedicated tunnel enabled. Open only its assigned ingress port in the cloud firewall.'
