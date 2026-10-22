# Agent Remote 移动端工程

本目录是独立 Capacitor 启动器。Node 24.14.0、npm 11.9.0；Capacitor core/cli/ios/android 8.5.3，InAppBrowser 4.1.0。依赖由 package-lock.json 固定。iOS 使用 Codemagic；Android 可在 Windows 局部工具链构建。

## Android APK

要求 Java 21、Android SDK Platform 36、Build Tools 36.0.0、Platform Tools。Android 最低 8.0（API 26），目标 API 36。工具链可放在忽略目录 `.toolchain/jdk/<JDK目录>` 和 `.toolchain/sdk`，不改变全局 Java 或其他项目环境。首次安装从 Adoptium 和 Android 官方站下载；本机使用 Temurin 21.0.12.1+1 和 commandlinetools 15859902。

```powershell
Set-Location D:\Personal\agent_remote\mobile
npm run android:build
# 也可以指定已有工具链：
pwsh -NoProfile -File scripts/build-android.ps1 -JavaHome C:\path\jdk-21 -AndroidSdk C:\path\android-sdk
```

脚本执行锁定依赖安装、测试、现有 iOS CI 配置检查、Web 构建、Android 同步及 `assembleDebug`，然后校验 APK 签名。产物为 `build/PocketAgentDesk-0.4.0-debug.apk`。Android 工程目录不提交；`prepare-android.mjs` 可重复应用原生配置，固定 Gradle 8.14.3，禁用明文 HTTP 和系统备份。没有 `server.url`、TLS 忽略或认证信息注入。可直接复制 APK 到手机安装；仅给实际用于打开该文件的应用授予安装来源权限，不需要关闭系统安全防护。

这是 Android 自动生成的 **debug 测试签名包**，不是正式发行签名。测试签名通常保存在用户私有目录 `~/.android/debug.keystore`，不上传仓库。换电脑或重建该密钥后，旧测试包可能需要卸载后才能安装（会丢失应用本地状态）。长期正式更新需另行生成稳定 release keystore，私有保存并离线备份；本任务不生成正式签名或公开 Release。

Android 0.2.0 的主连接窗口改用独立原生 Activity 中的普通 WebView，支持服务器 BasicAuth 原生输入框；远端 WebView 不挂载 Capacitor 或 JavascriptInterface。它与启动器处于同一应用进程，靠浏览器同源规则隔离存储，不再宣称独立进程。密码只交给当前 WebView 认证处理器，启动器不保存或记录密码。窗口仅允许当前 HTTPS origin 内导航，不忽略证书错误、不允许明文或混合内容。Cookie 会 flush 到应用存储，不主动清除；会话 Cookie 不保证跨进程重启保留。

0.4.0 默认打开 `/account`，使用服务器统一的邮箱/旧账号登录页面。正常页面不再显示原生 IP、账号和刷新工具栏，也不注入 APK 内的账号主题。系统栏、挖孔和键盘避让由原生层统一处理；遥控页面中的账号、刷新和连接设置位于侧边菜单。网络或证书失败时使用原生故障页，提供重试、账号和连接设置。

请先部署 0.27 账号服务再验收统一登录样式；仅更新 APK 不会改变旧服务器 HTML。服务器未启用 SMTP 时，旧账号登录仍可使用，邮箱注册暂不开放。新设备由电脑端窗口登录确认，不再要求用户复制绑定码或设备 ID。

文件和图片通过 Android 系统文件选择器上传；窗口保留返回键历史导航，音视频采集按系统权限询问。直接拍照、下载、Cookie 跨进程重启、SSE 恢复及真实上传仍需手机验收。原“兼容登录（系统浏览器）”仅保留作备用窗口；其 Cookie 独立，不能用来给主窗口预先登录。iOS 继续使用官方 InAppBrowser，现有签名与云工作流不变。

原生源码在 `native/android/`，由 prepare 脚本写入可重新生成的 Android 工程。构建包含 JS 入口测试、Java origin 策略测试和 Robolectric 原生认证／无地址栏及故障页测试（固定 4.17）；本地框架测试不等于手机连真实后端验收。APK 版本为 0.4.0/versionCode 4，沿用原 debug 签名，可覆盖安装旧测试版。

## 本地运行

```powershell
Set-Location D:\Personal\agent_remote\mobile
npm ci
npm test
npm run check:ci
npm run build
npm run dev
```

预览地址为 http://127.0.0.1:4173。预览只验证地址、保存设置，不访问真实服务，不发送任务。修改 HTML/CSS 后重新运行预览；JS 自动重建。

首次生成 iOS 工程：`npm run ios:add`。后续：`npm run build`、`npm run ios:sync`、`node scripts/prepare-ios.mjs`。本机可生成/同步工程，不能进行 Xcode 编译。生成目录 ios/ 不提交，云端从锁定依赖重新生成。不要把手工原生修改放在该目录；需要保留的修改写进 prepare-ios.mjs。

## 接入方式

启动页只保存 HTTPS origin 和 home/account 入口。默认 IP 为当前服务，域名启用后可直接在界面替换。`com.pocketagentdesk.remote` 仅为候选 bundle ID，未注册 Apple App ID，显示名也可修改。

iOS 应用通过官方 InAppBrowser 的独立 WKWebView 打开服务；Android 主窗口见上节。远端页面不放进带 Capacitor 桥接的主 WebView。服务器正常返回 remote.html 并注入 window.MACHINE，保留 static、诊断测速和全部业务接口。当前单用户使用现有配对入口；多用户云端部署完成后选择多用户账号入口。不替换或绕过另一任务的认证。

Cookie：服务器设置的 Secure/HttpOnly/SameSite=Strict Cookie 留在服务 WebView；启动页不读取、不复制 Cookie，不保存密码。与 Safari 的登录状态不保证共享；需要在 App 内重新登录。关闭窗口不等于退出，退出须走服务页面。Cookie 跨关闭/重启持久性仍需 iOS 实测。

Origin/CSRF：远端页面同源发起 fetch/SSE/上传，保留服务器 Host、Origin 和 Sec-Fetch-Site 校验。没有跨域 API 代理、CORS 放宽、ATS 例外、TLS 忽略或 server.url。主启动页 CSP connect-src 为 none。只允许输入无凭据、无路径/参数/片段的 HTTPS origin。

SSE：继续使用现有网页实时连接；iOS 后台可能暂停连接，回前台恢复、断线补拉和消息去重仍须真机验收。上传：复用 HTML 文件选择与同源请求，媒体用途说明在原生生成脚本中添加；照片/拍照/麦克风权限、文件选择、下载，以及旧外层 BasicAuth 在 WKWebView 的行为均需实测。没有把桌面预览当作上述功能通过。

## Codemagic

免费账号侧载使用 `ios-sideload` 工作流：以 iPhoneOS SDK 构建 Release arm64 App，生成 `Payload/App.app` 结构的 `AgentRemote-unsigned.ipa`。下载后在 Windows 的 Sideloadly 中用自己的 Apple 账号签名安装；该 IPA 尚未签名，不能直接点击安装。首次用 USB 连接并在手机确认信任，按 iOS 提示启用开发者模式。账号和验证码由用户亲自输入，不放入 Codemagic、GitHub 或聊天。免费签名七天有效；自动刷新需要电脑运行 Sideloadly Daemon，且手机经 USB 或已配置的 Wi-Fi 可连接。官方说明：https://sideloadly.io/faq.html 。真机安装和业务功能需实际验收。

根目录 codemagic.yaml 提供手动 ios-simulator 工作流：mac_mini_m2、Xcode 26.2、Node 24.14.0，最多 30 分钟，无自动触发、签名和发布。运行 npm ci、测试、Web 构建、cap add/sync、SPM 解析和无签名模拟器编译。产物仅 App.zip 和 Package.resolved，不上传日志、聊天或服务端运行状态。模拟器包不能直接装到 iPhone；设备包/TestFlight 需要另行配置 Apple Developer 签名。

Codemagic 官方截至 2026-10-22 列出个人账户每月 500 M2 分钟。登录后核对账户额度，勿开启付费计划。参考：
- https://docs.codemagic.io/yaml-quick-start/building-an-ionic-app/
- https://docs.codemagic.io/specs-macos/xcode-26-2/
- https://codemagic.io/pricing/
- https://capacitorjs.com/docs/getting-started/environment-setup
- https://capacitorjs.com/docs/apis/inappbrowser

账号登录/OAuth 由用户在官方页面完成。用户已选择现有公开仓库 Zeng-HY/Agent_24-7 用于 Codemagic；只提交 mobile/ 受控源码和根 codemagic.yaml，不提交同时进行的后端业务改动。上传前检查实际文件集合和 Git 历史，确保无 remote_config.json、attachments、logs、token、证书私钥或本地状态；.gitignore 不能清除已有历史。云构建结果以 Codemagic 对应提交的执行记录为准。

依赖说明：xcode 工具包使用 uuid.v4；通过局部 override 固定 uuid 11.1.1，处理旧 uuid 审计告警，不升级全局工具。Swift 侧 Capacitor 精确固定 8.5.3，InAppBrowser 上游原生库精确固定 3.0.0。首次云端解析得到的完整 Package.resolved 作为产物保留；完整原生依赖图和编译结果须以云端执行为准。
