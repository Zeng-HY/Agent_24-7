# 0.27 旁路部署与验收

当前源码实现邮箱注册、设备授权、WSS 接入、每标签页设备路由和统一账号页。注册默认为关闭，只有管理员通过 SMTP 实际收信测试才启用。**本地测试不等于云端已部署，也不等于两台真实电脑验收通过。**

## 服务器迁移

上传 `agent-relay-0.27.0-dev.zip` 到 `/home/admin/`，在 Workbench 分步执行：

```bash
python3 -m zipfile -e /home/admin/agent-relay-0.27.0-dev.zip /home/admin/agent-relay-027
sudo bash /home/admin/agent-relay-027/stage-027.sh
```

旁路服务使用 127.0.0.1:18771。脚本将 SQLite 一致性备份存到 root 私有的 `/var/backups/agent-relay/`，安装独立 Python 环境，进行增量建表并启动新服务；旧服务和 frps 保留。若缺少 python3-venv，仅补装该包，不升级操作系统。已存在安装目录时停止，避免盲目覆盖。

看到旁路就绪后切换已知 Caddy 路由：

```bash
sudo python3 /home/admin/agent-relay-027/switch-027.py
```

脚本验证 Caddy，备份为 `/etc/caddy/Caddyfile.before-027`，替换已知账号服务上游并验证 HTTPS。新账号/设备上游必须保留 Authorization，供独立设备凭据认证；转发到电脑时由应用重新构造受控请求头，不将浏览器认证头直接传给本机。Caddy 覆盖 `X-AR-Client-IP`，应用仅信任直接相连的回环代理；不信任浏览器自行发送的 X-Forwarded-For。

失败自动恢复旧路由。需要主动回退时：

```bash
sudo cp -a /etc/caddy/Caddyfile.before-027 /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
```

数据库迁移保留旧表，路由回退无需覆盖数据库。不要将备份恢复到正在被服务写入的数据库；也不要恢复备份而丢弃迁移后新增的账号。

## 开启邮箱注册

```bash
sudo python3 /home/admin/agent-relay-027/configure-mail.py
```

填发信邮箱（QQ、163、126、Gmail、Outlook 等会自动填好服务器）和它的 SMTP 授权码，再把测试邮件里的 6 位代码输回去，注册和找回密码就开了。授权码只在服务器上输入，不要发到聊天、命令参数或 GitHub。注册和找回密码的邮件里有 6 位验证码，在发起的那个页面（手机或电脑绑定窗口）里直接输入即可，邮件里的链接也能用。

## 更新服务器

在电脑的源码目录运行 `python deploy/relay/pack-027.py`，把生成的 `dist/agent-relay-0.27.0-dev.zip` 上传到 `/home/admin/`，然后：

```bash
python3 -m zipfile -e /home/admin/agent-relay-0.27.0-dev.zip /home/admin/agent-relay-027-new
sudo bash /home/admin/agent-relay-027-new/update-027.sh
```

换下的文件留在 `/opt/agent-relay-027/previous-时间/`；新文件起不来会自动换回。数据库不用动。

默认 `AR_ACCOUNT_LIMIT=20`、`AR_DEVICE_LIMIT=3`。如需修改，向同一私有环境文件加入这两个配置后重启 `agent-relay-027.service`。只调整数值，不取消认证和限流。发信失败时注册保持不可用；原用户名登录继续可用。

## 电脑与手机

安装 Windows 测试安装包后登录。已有设备在绑定页选择“迁移：原电脑名称”，保持设备 ID 和所属账号；新电脑选择“新增电脑”。授权凭据先保存在当前 Windows 用户的 DPAPI 私有文件中，因此断网后查询授权结果不会重复创建电脑。

新电脑只主动连接 443，不再安装 frpc 或开放新端口。程序保留原桌面服务接口；原 8765 只监听回环。已有源码安装由启动快捷方式识别，配置和常规附件复制到当前用户数据目录，原目录保留。已有可认证的 8765 服务会复用，未知监听者不会被终止。首个 Windows 重新登录测试后核对只剩一个新自启入口。

新页面使用 `/d/设备ID/` 固定当前标签页电脑。旧已打开网页的选择 Cookie 仅作兼容；新页面不会依赖该 Cookie 切换设备。原 frp 设备可通过新入口继续使用。每台电脑真正通过 WSS 连通并验收后，才停旧设备 frps 实例及对应旧入站端口。

Android 0.4.0 移除正常页的原生地址栏和账号主题注入，使用服务器统一页面。先迁移账号服务再用 APK 验收新登录样式；仅安装 APK 不会改变旧服务器 HTML。APK 仍是 debug 测试签名，iOS 工作流未改变。

## 验收与记录边界

本地自动检查覆盖邮箱验证/重置（模拟投递）、DPAPI、真实本地 TLS、两账号 HTTP/隧道流隔离、16 MiB 上传完整性、SSE 撤销、断线后不重放 POST、旧 frp 兼容、浏览器路由及登录布局。真实邮箱投递由上述服务器步骤验证。

现场依次验证：第一台迁移 → 第二台迁移 → 两账号交叉访问拒绝 → 发送和图片上传 → 断网重连 → Windows 重新登录自启 → 撤销测试设备 → 重新绑定。不要对正式工作对话发送测试控制指令。撤销阻止后续请求，无法撤回已经发送给桌面的命令。

最后使用现有 Certbot 配置执行一次 `sudo certbot renew --cert-name 8.166.15.235 --dry-run --run-deploy-hooks`，核对部署后证书与 Caddy 加载证书序列号一致，并用不带 `-k` 的 HTTPS 请求验证。失败时排查具体错误，不循环申请正式证书。

云端终止 TLS，是信任边界；不提供端到端加密。用量是应用层字节计数，不等于云服务商账单。
