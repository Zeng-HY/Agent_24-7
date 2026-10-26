# 遥应 Teleply iOS 版（原生 SwiftUI，0.1.0 进行中）

执行计划：`C:\Users\39011\.claude\plans\codex-ios-app-apple-developer-program-q-piped-hanrahan.md`（10-26 用户批准）。设计依据：Obsidian 里的《Teleply - iOS SwiftUI 设计规范》v0.8；页面和按钮照网页，向电脑要东西的时机、缓存和轮询照安卓 1.0.1（`apps/android`）。

## 身份和安装

- **Bundle ID**：`com.pocketagentdesk.teleply`，桌面名字“遥应”，和安卓正式版一样（用户 10-26 确认）。旧的网页外壳 `mobile/ios`（`com.pocketagentdesk.remote`）和它的两个 Codemagic 工作流不动，两个应用可以同时装着。
- **最低系统**：iOS 26；先只支持 iPhone（iPad 一旦上架支持就不能去掉，宽屏分栏做好再开）。
- **安装**：TestFlight 内部测试，只给用户自己。应用里不放“检查更新”，新构建由 TestFlight 提醒。
- **版本**：`project.yml` 的 `MARKETING_VERSION`；构建号由 `ios-native-testflight` 取 TestFlight 上最新的加一，不用手改。

## 工程

- `project.yml`：XcodeGen 的工程描述，在云端生成 `Teleply.xcodeproj`（生成物不进 git）。Xcode 新建工程模板里的设置（Swift 6、默认主线程、图标名等）都写在这里。
- `Teleply/`：应用本体。`App/` 入口和启动页，`Design/` 颜色，`Platform/` 网络收发，`Resources/` 资源（颜色和图标由 `Assets.xcassets` 提供，开发语言简体中文）。
- `TeleplyCore/`：不碰界面的 Swift 包，Windows 上也能编译和测试。`TeleplyModel` 数据和逻辑（接口返回的宽松读法、服务地址、请求构造、错误文字、Markdown），`TeleplyState` 页面状态（主线程），`TeleplyDemo` 本地示例。依赖只有 swift-markdown 0.9.0 和它带的 swift-cmark 0.9.0（`Package.swift` 里写死提交号）。
- `TeleplyUITests/`：截图测试，用本地示例跑（启动参数 `-TeleplyDemo`、`-TeleplyAppearance`，只在调试版生效）。
- `scripts/`：`ci-check.sh`、`ci-testflight.sh`（云端），`codemagic.ps1`（本机启动构建、等结果、下载产物）。

## 怎么构建

- **本机**（Swift 6.4.1，Windows）：在 `apps/ios/TeleplyCore` 里 `swift build`、`swift test`。
- **云端检查**：Codemagic 工作流 `ios-native-check`（Xcode 27.1）。`CHECK_MODE=compile` 只编译并跑 `TeleplyCore` 测试；`CHECK_MODE=shots` 再在模拟器上截图（默认 iOS 27.1，`SHOT_RUNTIMES="iOS-27-1 iOS-26-5"` 加跑 26.5），截图在产物 `shots.zip`。
- **TestFlight**：工作流 `ios-native-testflight`。要先在 Codemagic 里加好名为 `teleply-asc` 的 App Store Connect 密钥，以及这个 Bundle ID 的 App Store 证书和描述文件。上传前会核对包里的 Bundle ID、构建号、加密声明、图标、隐私清单和简体中文；只进内部测试，不提交审核。
- 本机启动构建：`apps/ios/scripts/codemagic.ps1 -ListApps` 找到应用编号，再 `codemagic.ps1 -AppId <编号> -Workflow ios-native-check -Mode shots`。令牌放在 `%USERPROFILE%\.codemagic\token.txt`。构建的是 GitHub 上的 `ios-native` 分支，先推送。
- Codemagic 免费额度每月 500 分钟；每次构建的实际分钟数记在下面。头两周用掉一半以上，就把检查构建挪到 GitHub Actions。

## 0.1.0（进行中）

目标：TestFlight 装上“遥应”，打开是标志页，显示版本号和默认服务的版本，在真机上提前证明证书和网络设置没问题。

| 项目 | 本机测过 | 模拟器截图看过 | 真机验过 |
|---|---|---|---|
| `TeleplyCore` 编译和测试 | 通过（10-26，Swift 6.4.1 Windows，14 项） | — | — |
| 云端编译 | — | 待测 | — |
| 启动页（浅色、深色、最大字号） | — | 待测 | 待测 |
| TestFlight 安装、显示服务版本 | — | — | 待测 |

- 本机工具链（10-26 装）：Swift 6.4.1 在 `%LOCALAPPDATA%\Programs\Swift`；Visual Studio 2022 生成工具在 `F:\Dev\VS2022BuildTools`，Windows SDK 10.0.22621 在 `F:\Windows Kits\10`。Swift 安装时跳过了它自带的 Python 3.10 依赖，`python` 仍是原来的 3.11。新开的终端才认得 `swift`。
- Windows 上编译时会出一串 `WinSDK` / `wchar_t` 的提醒，是工具链自己的，不影响结果；`.build\debug` 建不了快捷方式的提醒也一样（Windows 默认不让普通用户建符号链接）。
- 第一天的检查（计划“工程结构”一节）：`TeleplyState` 的 Observation 和“默认主线程”、Swift Testing、swift-markdown 都能在 Windows 上编译，三块都留在 `TeleplyCore`。

构建分钟数：还没有构建。
