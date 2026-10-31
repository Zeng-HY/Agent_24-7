# 交接：换用域名 pocketagentdesk.com

记于 2026-10-25，2026-10-31 更新：备案已通过，用户说开工（“换域名和补上架缺口一起开工”）。

## 定下来的

- 服务用 `app.pocketagentdesk.com`；主域名 `pocketagentdesk.com` 放网站（介绍、下载、隐私政策、帮助），`www` 转到主域名。
- IP `8.166.15.235` 先留着，旧版 App、旧电脑端和旧 FRP 电脑照常走 IP；看访问情况再决定什么时候停。
- 网页打开 IP 时不自动跳到域名。

## 现在的情况（2026-10-31 查到的）

- 域名解析在阿里云（hichina），10-31 时一条记录都没有。这台电脑的 DNS 会给出 198.18.x.x 的假地址（代理），查解析要用 `https://dns.alidns.com/resolve?name=…&type=A`。
- 服务器：阿里云 `8.166.15.235`（广州），中转 0.27.0-dev.30，邮箱注册已开（`email_enabled: true`）。
- HTTPS：Caddy 2.6.2，全局 `auto_https off`、`default_sni 8.166.15.235`，只听 443，80 端口空着。IP 证书是 Certbot 签的 Let's Encrypt 短期证书（10-30 签、11-05 到期，每张约 6.7 天），续期方式 `authenticator = standalone`（续期时自己占 80），钩子 `50-frp-speed-caddy` 复制到 `/etc/caddy/certs/`。所以 `switch-domain.py` 去掉 `auto_https off`、让 Caddy 占 80，把 Certbot 挪到 `127.0.0.1:18402`，由 Caddy 转发 IP 的验证请求，切换时先试运行续期。
- 备案：粤ICP备2026170106号（2026-10-30 通过，个人备案，曾环宇）。网站内容要保持个人、非商业。
- 0.27 隧道转给电脑的请求只带 `REQUEST_HEADERS`，不带 Host/Origin，所以手机换地址不影响还没更新的电脑。
- 写死 IP 的地方：`relay_desktop.py`（已改）、iOS `ServiceOrigin.swift`、安卓 `ReaderViewModel.kt`（这两个在改）、旧 iOS 套壳 `mobile/src/settings.mjs`（不改，用户说旧套壳不动）、旧 FRP 绑定工具 `relay_bind_gui.py` 和旧部署文件（不改，旧 FRP 一直走 IP）。
- 更新下载：Windows 和安卓已经是阿里云 OSS 优先；`dl.pocketagentdesk.com` 已经写进 `relay_updates.py`、`Updates.kt`、`publish.py`，安卓等绑好域名后把 `ANDROID_FROM_ALIYUN` 改成 True。
- iPhone 推送（中转 → 苹果）不依赖地址。

## 已经做了（代码，还没提交、没部署）

- `relay_service.py`：新参数 `--alias-origin`（可重复）和 `--legacy-origin`。每个请求按它进来的地址检查 Host 和 Origin；电脑绑定链接用电脑自己用的地址；邮件链接用主地址；旧 FRP 电脑收到的始终是 `--legacy-origin`。不加新参数时和原来完全一样。
- 删除账号：`POST /account/delete {"password"}`（`relay_identity.py` 的 `delete_account`）。删账号、邮箱、登录、验证码、通知登记、电脑的连接凭证和流量统计；电脑那一行清空后标成已撤销（旧 FRP 端口号不能重复发）。网页“我的电脑”右上角菜单加了“删除账号”。
- 网页账号页加了页脚：隐私政策、ICP 备案号。
- 网站：`deploy/site/`（首页、隐私政策中英、帮助中英）。
- `deploy/relay/switch-domain.py`：加 Caddy 站点、装网站、加 systemd 附加设置让中转认两个地址、用验证过的 HTTPS 核对，出错自动退回；`--check` 只检查，`--rollback` 退回。
- `deploy/relay/pack-027.py`：包里带上网站和切换脚本；页面里还有“待填”时拒绝打包。
- 电脑端：`ORIGIN` 换成域名；绑定在 IP 上的电脑启动时自动改用域名，设备钥匙不变（`relay_desktop.current_binding`）。
- iPhone、安卓（10-31 在单独工作区做完、合进 main，没提交）：默认地址换成域名，启动时把 IP 上的登录搬过去（只搬一次，之后手动填的 IP 保留）；删除账号；隐私政策入口。删除账号成功后，手机上这个账号的本地记录清掉，iPhone 结束灵动岛，安卓关掉后台会话检查。iPhone 另加 App 内注册和找回密码（不再跳 Safari）、6.9 英寸截图机型；安卓顺手修了“默认地址时后台会话检查开不了”。
- 网站页脚、隐私政策、帮助页的空都填了：备案号、运营者曾环宇、联系邮箱 390116927@qq.com（用户 10-31 给的）。
- 服务器包 `dist/agent-relay-0.27.0-dev.zip` 已打好，里面的 `relay_push.py` 固定用 17bba06 那版（另一个会话的灵动岛改动还没经用户同意上服务器）。重打时照样替换。

## 2026-10-31 晚上的结果

- 21:50 用户运行 `update-027.sh`（中转 0.27.0-dev.31 的文件，`relay_push.py` 是 17bba06 那版），随后 `switch-domain.py`。第一次等主域名证书超时，全部自动退回；换上“网站证书慢了不退回”的新脚本后第二次切换成功：`https://app.pocketagentdesk.com` 和 IP 都是 200，http 跳 https。
- 主域名的证书 22 点多由 Caddy 重试拿到，网站三页、页脚、404 都正常；`www` 当时还在重试。
- 原因：服务器连 Let's Encrypt 很慢，正式和测试接口每次 4–12 秒，偶尔 30 秒超时（两种协议都会）。Caddy 2.6.2 每个请求只等 30 秒，所以经常半路失败，靠它自己的重试（1、2、5 分钟……最长 30 天）拿到。备用的 ZeroSSL 在这个旧版 Caddy 里用不了（`caddy_legacy_user_removed`），失败日志里会一直有它，无害。
- IP 证书仍由 Certbot 续（等得更久，一直续得上），现在经 Caddy 的 80 端口转给 `127.0.0.1:18402`，切换时试运行通过。下次真正续期大约在 11-02 到 11-03，这张 11-05 到期，到时看一眼：`sudo openssl x509 -in /etc/caddy/certs/fullchain.pem -noout -dates`。
- 另一个会话（灵动岛）的 `relay_push.py` 改动经用户同意后会单独打包上传，只运行 `update-027.sh`，附加设置 `domain.conf` 保留。

## 实施步骤（按顺序，每一步都能退回）

1. **解析（用户）**：阿里云云解析加 A 记录 `app`、`@`、`www` 指向 `8.166.15.235`，TTL 10 分钟。
2. **打包上传**：先确认另一个会话（灵动岛）没有改到一半的 `relay_push.py`，再 `python deploy/relay/pack-027.py`，把 `dist/agent-relay-0.27.0-dev.zip` 传到 `/home/admin/`：
   ```bash
   rm -rf /home/admin/agent-relay-027-new
   python3 -m zipfile -e /home/admin/agent-relay-0.27.0-dev.zip /home/admin/agent-relay-027-new
   sudo bash /home/admin/agent-relay-027-new/update-027.sh
   ```
   这一步只换代码，中转仍然只认 IP。
3. **检查**：`sudo python3 /home/admin/agent-relay-027-new/switch-domain.py --check`
4. **切换**：`sudo python3 /home/admin/agent-relay-027-new/switch-domain.py`
5. **核对**：浏览器打开 `https://pocketagentdesk.com` 和 `https://app.pocketagentdesk.com/account`；用旧 App 和旧电脑端确认 IP 照常能用。
6. **公安联网备案（用户）**：网站开通 30 天内到 beian.mps.gov.cn 办，拿到号后加到页脚。
7. **下载域名（用户）**：OSS `teleply-updates` 绑定 `dl.pocketagentdesk.com`（照 `deploy/updates/README.md`），阿里云免费证书 3 个月一换、不会自己续，要定提醒；然后 `ANDROID_FROM_ALIYUN = True`，网站下载按钮改成 `dl.` 的链接。
8. **各端发新版**（服务器切完以后才发）：电脑端 0.27.0-dev.31、安卓 1.0.5、iPhone（先 TestFlight，再提交 App Store）。

## 回退

- 服务器：`sudo python3 /home/admin/agent-relay-027-new/switch-domain.py --rollback`（去掉附加设置、恢复 `/etc/caddy/Caddyfile.before-domain`）。
- App：设置 → 开发者选项 → 服务地址 仍可手动填 IP。
- 解析：删掉 A 记录。

## 以后再说

- 停用 IP：先看日志确认没有旧客户端，再停 IP 证书续期。
- 用 `@pocketagentdesk.com` 发验证邮件：现在 `configure-mail.py` 用 QQ 等邮箱的 SMTP，换的话要开域名邮箱或邮件推送服务，再加 SPF/DKIM 解析。
- iPhone 通用链接、安卓 App Links：在域名下放验证文件，iPhone 要重新生成描述文件。
- 国区上架要的 APP 备案：在阿里云同一个备案系统里加，iPhone 和安卓一起填。
