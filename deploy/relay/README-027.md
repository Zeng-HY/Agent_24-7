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

## 开启遥应通知（iPhone 推送）

中转替 iPhone 上的遥应向苹果发通知（`relay_push.py`）。电脑只告诉中转"哪个应用、哪个对话、什么事"，中转写成"Claude · 我的电脑：有个对话好了"交给苹果，对话内容不出电脑。没配置密钥时这一块不工作，别的照常。

1. 先测服务器连不连得上苹果（只读）：

```bash
curl -sS -m 10 --http2 -o /dev/null -w '%{http_code} %{http_version}\n' https://api.push.apple.com/3/device/test
```

打出 `405 2` 这样的三位数加 2 就是通的；`000` 加报错就是不通。

2. 照下面"更新服务器"上传新包并运行 `update-027.sh`。它先装新的 Python 库（httpx、h2、cryptography），装不上就什么都不换。
3. 在苹果开发者网站建好推送密钥（环境 Production，类型 Topic Specific，勾 `com.pocketagentdesk.teleply`），把下载的 `.p8` 文件上传到 `/home/admin/`，然后：

```bash
sudo /opt/agent-relay-027/.venv/bin/python /home/admin/agent-relay-027-new/configure-push.py
```

按提示填 `.p8` 的路径和 Key ID（Team ID 默认 `CPSVJ7235A`）。脚本先问苹果一次，苹果收下了才保存：`/etc/agent-relay/push.env`（root 0600）和 systemd 附加设置 `/etc/systemd/system/agent-relay-027.service.d/push.conf`，再重启服务。之后删掉上传的 `.p8` 文件。密钥只在服务器上输入，不发到聊天、命令参数或 GitHub；日志里的手机令牌只有哈希的前 8 位。

关掉：`sudo rm /etc/systemd/system/agent-relay-027.service.d/push.conf`，再 `sudo systemctl daemon-reload` 和 `sudo systemctl restart agent-relay-027.service`。手机登记的令牌留在数据库里，不影响别的功能。

## 换用域名 pocketagentdesk.com

先在阿里云云解析里把 `app`、`@`、`www` 三条 A 记录指向 `8.166.15.235`，再照下面“更新服务器”装好新包（只换代码，中转仍然只认 IP）。然后：

```bash
sudo python3 /home/admin/agent-relay-027-new/switch-domain.py --check
sudo python3 /home/admin/agent-relay-027-new/switch-domain.py
```

第一行只检查，不改动。第二行做这些事，有一步不通过就自动换回：

- 给 Caddy 加上 `app.pocketagentdesk.com`（中转）和 `pocketagentdesk.com`、`www`（网站，装到 `/var/www/pocketagentdesk`），去掉全局的 `auto_https off`，域名的证书由 Caddy 自己申请，http 自动转到 https。IP 站点和它的 Certbot 证书照旧。
- Caddy 从此占用 80 端口。Certbot 续 IP 证书时不再自己占 80，改在 `127.0.0.1:18402` 等着，由 Caddy 把 IP 的验证请求转过去（续期设置里加了 `http01_port`、`http01_address`）。切换时先试运行一次续期，不通过就全部换回。
- 加 systemd 附加设置 `agent-relay-027.service.d/domain.conf`，让中转以域名为主地址、同时认 IP。旧版 App、旧电脑端、旧 FRP 电脑照常走 IP。

以后检查 IP 证书续期，照旧运行 `sudo certbot renew --cert-name 8.166.15.235 --dry-run`。

退回：`sudo python3 /home/admin/agent-relay-027-new/switch-domain.py --rollback`（Caddyfile、Certbot 续期设置、中转附加设置都换回原样）。

## 更新服务器

在电脑的源码目录运行 `python deploy/relay/pack-027.py`，把生成的 `dist/agent-relay-0.27.0-dev.zip` 上传到 `/home/admin/`，然后：

```bash
python3 -m zipfile -e /home/admin/agent-relay-0.27.0-dev.zip /home/admin/agent-relay-027-new
sudo bash /home/admin/agent-relay-027-new/update-027.sh
```

换下的文件留在 `/opt/agent-relay-027/previous-时间/`；新文件起不来会自动换回。数据库不用动。

默认 `AR_ACCOUNT_LIMIT=20`、`AR_DEVICE_LIMIT=3`。如需修改，向同一私有环境文件加入这两个配置后重启 `agent-relay-027.service`。只调整数值，不取消认证和限流。发信失败时注册保持不可用；原用户名登录继续可用。

2026-10-31 起账号上限是 200，没有写进邮箱设置文件（`smtp.env` 里有发信密码，不去动它），而是写在单独的附加设置 `/etc/systemd/system/agent-relay-027.service.d/limits.conf`（两行：`[Service]`、`Environment=AR_ACCOUNT_LIMIT=200`）。注意 `EnvironmentFile` 里的同名设置会盖过它，所以调之前先确认 `sudo grep -c '^AR_ACCOUNT_LIMIT' /etc/agent-relay/smtp.env` 是 0。改数字：改这个文件，再 `sudo systemctl daemon-reload && sudo systemctl restart agent-relay-027.service`。核对：`sudo cat /proc/$(systemctl show -p MainPID --value agent-relay-027.service)/environ | tr '\0' '\n' | grep '^AR_ACCOUNT_LIMIT'`。退回默认 20：删掉这个文件，再 daemon-reload 和重启。

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


## 0.27.0-dev.1 电脑端与兼容补丁

账号与电脑菜单使用页面顶层操作面板；旧版连接仅表示旧通道配置仍保留。移除设备是撤销访问，不删除电脑文件。此补丁不改 SMTP 配置或旧隧道端口。

新版 Windows 有状态窗口和托盘菜单。关闭窗口会留在托盘，右键可打开、查看账号、检查更新、切换登录自启、重新绑定或退出。重复双击唤起已有实例；旧客户端仍在运行时提示先退出旧版。绑定请求过期会自动重新申请，仍需用户确认；不会自动重复绑定。

未绑定时可选择旧版文件夹。迁移保留原目录，失败恢复覆盖的目标文件；验证手机连接、附件与 Windows 登录自启后再人工处理旧目录或旧设备记录，不按相同名称自动合并。不要据“在线”一项就删除旧数据。

Windows 更新版本由根目录 `windows-version.json` 维护。递增 build；运行 `deploy/windows/build.ps1` 会生成单文件安装包及 `dist/windows-update.json`，清单记录对应源码提交、文件名、大小与 SHA-256。dev.25 起再运行 `deploy/updates/publish.py windows`：签名清单，把安装包和清单传到阿里云（应用先看阿里云，再看 GitHub），见 `deploy/updates/README.md`。然后把安装包、`windows-update.json`、`windows-update.json.sig` 上传同一个 GitHub Release；测试版本标记 Pre-release。仅上传 Actions 临时产物不会推送更新。

旧版没有检查更新功能，需要手动覆盖安装本版一次。此后用户从托盘检查、下载并确认安装；不会静默下载执行。覆盖更新保留当前安装目录、数据与自启选择。代码哈希校验不等于 Windows 发布者数字签名。


## 0.27.0-dev.2 窗口与网页恢复

首次打开直接在主窗口登录；原生左上角齿轮收纳辅助操作，底部自启为复选框。账号 WebView2 与本地设置视图为同一个窗口内的隔离控件，切换设置保留输入，不保存密码；没有向远端页面开放本机接口。

页面模块监测区分下载失败、执行失败和加载超时。仅对已确认下载失败的模块重试一次；在途超时及已执行出错的脚本不重复执行。Claude 和引用模块按依赖初始化，诊断只记录模块名和失败类型。提示位于导航下方的正常布局中，可关闭；返回 Safari 和模块失败均不自动整页刷新。需要整页刷新时由用户主动选择。

网页资源版本跟随 Windows 构建版本递增，避免不同测试包共用资源标识。此轮未修改设备代理或云端账号服务；网页修复在更新电脑端后生效，手机手动刷新一次即可。WebKit 自动检查不能替代 iPhone Safari 实机验收。


## 0.27.0-dev.3 新标志

程序、安装包、窗口和任务栏换成新标志：黑色圆角方块里一个白色 A，横杠换成一个点，即「已连接」前面的那个点。托盘里的点只在这台电脑连上时亮，未连上时变暗，鼠标停留显示当前状态。手机网页的主屏幕图标同时更换；已添加到 iPhone 主屏幕的需删除后重新添加。全部图标由 `brand/make_icons.py` 生成，安卓和 iOS App 图标在下次构建时生效。
