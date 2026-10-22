#!/usr/bin/env bash
# Put this package's relay files in place of the running 0.27 service's and restart it. The files it replaces are
# kept beside them (previous-<time>/) and put back if the service does not come up. The database is not touched
# (a table the new files need is added when the service starts).
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo '用 sudo 运行'; exit 1; }
cd -- "$(dirname -- "$0")"
target=/opt/agent-relay-027
test -f "$target/relay_service.py" || { echo '还没装 0.27：先运行 stage-027.sh'; exit 1; }
files=(relay_service.py relay_identity.py relay_accounts.py relay_mail.py relay_transport.py relay_pages.py relay_routing.js relay_account.html relay_account.css relay_account.js)
for file in "${files[@]}"; do test -f "$file" || { echo "包里缺 $file"; exit 1; }; done
keep="$target/previous-$(date +%Y%m%d-%H%M%S)"
install -d -o root -g root -m 755 "$keep"
for file in "${files[@]}"; do
    cp -a "$target/$file" "$keep/" 2>/dev/null || true
    install -o root -g root -m 644 "$file" "$target/$file"
done
systemctl restart agent-relay-027.service
for attempt in {1..30}; do
    if curl --fail --silent --max-time 2 --output /dev/null -H 'Host: 8.166.15.235' http://127.0.0.1:18771/account; then
        echo "已更新。换下的文件在 $keep"
        exit 0
    fi
    sleep 1
done
for file in "${files[@]}"; do test -f "$keep/$file" && install -o root -g root -m 644 "$keep/$file" "$target/$file"; done
systemctl restart agent-relay-027.service
echo "新文件没起来，已换回原来的。看 journalctl -u agent-relay-027.service -n 50"
exit 1
