#!/usr/bin/env bash
# Put this package's relay files in place of the running 0.27 service's and restart it. The files it replaces are
# kept beside them (previous-<time>/) and put back if the service does not come up. The database is not touched
# (a table the new files need is added when the service starts). Libraries the package adds (遥应通知: httpx, h2,
# cryptography) are installed first; when that fails, nothing is replaced.
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo '用 sudo 运行'; exit 1; }
cd -- "$(dirname -- "$0")"
target=/opt/agent-relay-027
test -f "$target/relay_service.py" || { echo '还没装 0.27：先运行 stage-027.sh'; exit 1; }
files=(windows-version.json static/theme.js static/theme.css static/favicon.svg static/favicon-dark.svg static/favicon.ico static/icon-maskable-512.png static/apple-touch-icon.png relay_service.py relay_identity.py relay_accounts.py relay_mail.py relay_transport.py relay_pages.py relay_push.py relay_routing.js relay_account.html relay_account.css relay_account.js requirements-relay.txt)
for file in "${files[@]}"; do test -f "$file" || { echo "包里缺 $file"; exit 1; }; done
if ! cmp -s requirements-relay.txt "$target/requirements-relay.txt"; then
    PIP_CONFIG_FILE=/dev/null PIP_EXTRA_INDEX_URL='' PIP_TRUSTED_HOST='' "$target/.venv/bin/python" -m pip install --disable-pip-version-check --index-url https://pypi.org/simple -r requirements-relay.txt ||
        { echo '新库没装上，什么都没换。看上面 pip 的报错'; exit 1; }
fi
keep="$target/previous-$(date +%Y%m%d-%H%M%S)"
install -d -o root -g root -m 755 "$keep"
for file in "${files[@]}"; do
    install -d -m 755 "$(dirname "$keep/$file")" "$(dirname "$target/$file")"
    cp -a "$target/$file" "$keep/$file" 2>/dev/null || true
    install -o root -g root -m 644 "$file" "$target/$file"
done
systemctl restart agent-relay-027.service || true
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
