# 两人邀请测试部署

2026-10-22 本次测试服务器已完成账号入口切换，第一台电脑已成功绑定并通过手机连接。第二台真实电脑的隔离、自启、撤销及证书续期仍待验收。下面保留分阶段安装和回退操作，不能把单台连通等同于全部验收通过。原有 `frps.service`、18080/18081、18767 单用户入口和 Tailscale 保留。原始 8765 始终只监听本机。

## 边界和实现

云端 Caddy 终止 HTTPS，账号网关检查每个请求的登录会话及设备归属，再转发到数据库指定的回环端口。本机新入口 18768 校验设备专属 Bearer 凭据，剥离外部身份头后使用本机口令访问 8765。上传分块及 SSE 输出期间复核撤销状态；已发送给桌面的命令无法撤回。

每台电脑独占一个 frps 实例，具有不同 token、入站端口和唯一允许的回环代理端口。前两台使用 7101→18101、7102→18102。没有向用户分发可注册其他电脑路由的共享 token。旧 7000 token 仅继续用于旧路径，不能发给第二人。

账号登录态、邀请、重置和绑定码只保存 SHA-256 摘要。密码使用独立随机盐的 scrypt（N=131072,r=8,p=1），并限制并发哈希和登录尝试。邀请有效一天；重置和绑定码十分钟、一次有效；登录七天。改密/重置会撤销全部登录会话及未使用绑定码。设备绑定保留，按需要单独撤销。

云端需要保存可用的设备转发和隧道凭据；数据库为服务账号私有，不能公开下载或共享备份。云服务器管理员仍能接触内容，这不是端到端加密。基础流量按 UTC 日统计应用层上传/下载字节，不包含 TLS、frp 开销，不是运营商账单。

每个账号可以绑定多台电脑，浏览器通过受保护 Cookie 选择电脑。切换会影响此浏览器全部标签页，应关闭旧遥控页后切换。绑定确认意味着授权该账号访问此 Windows 登录用户的遥控服务和本地文件；没有为一台 Windows 电脑创建多个用户级沙箱。

## 1. 先核对云端当前状态

在阿里云 Workbench Shell 中逐段执行。不要输出 `/etc/frp/token`、私钥、数据库或完整 Caddy basicauth 哈希。

```bash
sudo systemctl is-active caddy frps
sudo ss -lntp | grep -E ':(80|443|7000|18080|18081|18770)\b'
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo openssl x509 -in /etc/caddy/certs/fullchain.pem -noout -dates
sudo systemctl list-timers --all --no-pager | grep -Ei 'certbot|snap.certbot'
```

下面只显示已有路由相关行，不显示认证哈希，用于确定候选 Caddy 修改位置；没有这些当前内容时，不覆盖现有配置：

```bash
sudo grep -nE 'auto_https|default_sni|^[[:space:]]*(https://|8\.166\.|handle|route|reverse_proxy|rewrite|root|file_server|header_up|flush_interval|tls[[:space:]])' /etc/caddy/Caddyfile
```

## 2. 安装旁路账号服务（不切换公网）

将本地生成的 `agent-relay-staging.zip` 通过 Workbench 文件上传放入 `/home/admin/`。包内仅含云端程序、两个 systemd unit、安装脚本和此说明，不包含凭据、数据库、remote_config.json 或本机聊天。

```bash
mkdir -p /home/admin/agent-relay-staging
python3 -m zipfile -e /home/admin/agent-relay-staging.zip /home/admin/agent-relay-staging
cd /home/admin/agent-relay-staging
sudo bash stage.sh
```

回退旁路服务，不影响旧公网路径：

```bash
sudo systemctl disable --now agent-relay.service
```

## 3. 根据当前 Caddy 配置添加账号入口

先保留当前配置：

```bash
sudo cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.before-multiuser-$(date +%Y%m%d-%H%M%S)"
```

第一步只让 `/account` 和 `/account/*` 到 18770，且这些路由不能继续受旧共享 basicauth 约束。已有其他路由仍走旧入口。旁路阶段只验账号和绑定，暂不使用“连接”按钮；它要等首页及应用路由切换后才连接新入口。旧共享密码不发给第二人。候选配置必须依当前文件生成，执行 `caddy validate` 后才 reload；不要将下列片段直接覆盖整个 Caddyfile。

```caddyfile
@accounts path /account /account/*
handle @accounts {
    reverse_proxy 127.0.0.1:18770 {
        header_up -Authorization
        header_up -Tailscale-User-Login
        flush_interval -1
    }
}
```

若 basicauth 当前在站点级，须移入旧入口自己的 handle，不能让它拦住新账号 API。设备绑定完成并通过云端只读验证后，再把首页及其余应用路径切到 18770；保留 `/speed`、`/upload-test` 及其原有保护。不要让绕过账号校验的路由到达 18101/18102。

切换失败时，把本次备份复制回 `/etc/caddy/Caddyfile`，验证后 `sudo systemctl reload caddy`。旧 frps 和单用户网关一直保留，回退不需要重新配对或重启 8765。

## 4. 邀请和绑定

在服务器签发邀请链接；链接由管理员直接交给受邀者，不贴入公开聊天或日志：

```bash
sudo -u agent-relay python3 /opt/agent-relay/relay_cloud.py --state /var/lib/agent-relay/accounts.sqlite3 invite --origin https://8.166.15.235
```

受邀者打开链接注册、登录，在账号页生成绑定码。在其自己的电脑上准备经过核对的 frpc 0.71.1 和服务器公开证书，然后运行（以下 Windows PowerShell 示例路径适用于本机；其他电脑按实际路径填写）：

```powershell
Set-Location D:\Personal\agent_remote
$relayFrp = Join-Path $env:LOCALAPPDATA 'AgentRemote\frp'
.venv\Scripts\python.exe relay_device.py enroll --origin https://8.166.15.235 --account alice --label '我的电脑' --certificate "$relayFrp\config\server.crt" --frpc "$relayFrp\frp_0.71.1_windows_amd64\frpc.exe"
```

本机已确认存在此证书路径，其他电脑须按实际文件位置填写，并将 `alice` 换成已注册账号。程序先显示服务器、账号和电脑名称，必须在本机输入账号名确认，再隐藏输入绑定码。新凭据仅写入 `attachments/relay-device/`，Windows 在写入前为此新目录设置当前用户及 SYSTEM ACL，不改旧 frp 目录 ACL。若权限设置失败则停止，不继续保存。不要关闭 Defender 或添加排除项；先前拦截仍是第二台电脑分发时的待解决问题。

管理员列出已绑定设备（不含凭据），并启用目标 ID 的专属隧道：

```bash
sudo -u agent-relay python3 /opt/agent-relay/relay_cloud.py --state /var/lib/agent-relay/accounts.sqlite3 devices
sudo bash /home/admin/agent-relay-staging/enable-device.sh 替换为32位设备ID
```

云防火墙仅为已启用设备开放其 7101 或 7102 TCP 入站端口；18101、18102、18770、8765 不开放。原 18080/18081 继续仅回环监听。

在 Windows 手动验证新入口，使用独立终端启动：

```powershell
Set-Location D:\Personal\agent_remote
.venv\Scripts\python.exe relay_device.py serve
```

```powershell
Set-Location D:\Personal\agent_remote
& "$env:LOCALAPPDATA\AgentRemote\frp\frp_0.71.1_windows_amd64\frpc.exe" -c 'D:\Personal\agent_remote\attachments\relay-device\frpc.toml'
```

用户在账号页选自己的电脑。迁移验收使用两个测试账号：交叉选择设备 ID 应 404，伪造设备 Cookie 访问聊天/附件/上传/控制/SSE 应 403；本机新入口无有效设备凭据应 401；撤销后新请求应 403，已有 SSE 不再转发新事件。不要用真实工作对话测试控制动作。

## 5. 登录会话内后台运行

先结束上面两个新入口测试终端，再启动 supervisor，避免端口重复；旧单用户终端不动：

```powershell
Set-Location D:\Personal\agent_remote
Start-Process -FilePath '.venv\Scripts\pythonw.exe' -ArgumentList 'relay_supervisor.py' -WorkingDirectory 'D:\Personal\agent_remote' -WindowStyle Hidden
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_relay_autostart.ps1
```

supervisor 复用经过认证的 8765 服务，管理自己创建的新网关/frpc 子进程；frpc 自动重连，子进程退出按 2–60 秒退避重启。命名互斥量阻止重复 supervisor，不终止已有不明进程。自启限当前 Windows 用户登录会话，不能在注销后继续控制桌面。

回退：`powershell -NoProfile -ExecutionPolicy Bypass -File .\install_relay_autostart.ps1 -Disable` 只移除本项目自启快捷方式。紧急停止访问：`.venv\Scripts\python.exe relay_device.py revoke-local`，随后账号页撤销云端设备；supervisor 会退出其子进程。重新接入须生成新绑定，不复用撤销的路由。

## 6. 重置、撤销与证书续期验收

忘记密码由管理员签发一次性链接：

```bash
sudo -u agent-relay python3 /opt/agent-relay/relay_cloud.py --state /var/lib/agent-relay/accounts.sqlite3 reset alice --origin https://8.166.15.235
```

账号页撤销立即阻断云端转发。管理员再停该设备专属隧道、关闭其入站端口，释放资源；仅停止隧道不等于数据库撤销：

```bash
sudo systemctl disable --now frps-device@替换为32位设备ID.service
```

保留现有续期配置和钩子，先检查钩子内容，再做一次 staging dry-run，不重复申请正式证书：

```bash
sudo cat /etc/letsencrypt/renewal-hooks/deploy/50-frp-speed-caddy
sudo certbot renew --cert-name 8.166.15.235 --dry-run --run-deploy-hooks
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo openssl x509 -in /etc/letsencrypt/live/8.166.15.235/fullchain.pem -noout -serial -dates
sudo openssl x509 -in /etc/caddy/certs/fullchain.pem -noout -serial -dates
curl -I --connect-timeout 10 https://8.166.15.235/account
```

两份证书序列号应相同，curl 不使用 `-k` 且应返回成功的账号页。失败时保留原证书和服务，检查具体错误，不循环申请。Certbot 的 `--run-deploy-hooks` 在 dry-run 成功后使用当前正式证书运行钩子，不把 staging 证书部署给用户：[Certbot 官方说明](https://eff-certbot.readthedocs.io/en/stable/using.html)。

最后确认客户端凭据已保存和旧路径可回退后，由管理员删除 `/home/admin/frp-client-transfer/` 中旧临时 token 下载副本；不要删除 `/etc/frp/token`，旧隧道仍依赖它。此清理尚未执行。
