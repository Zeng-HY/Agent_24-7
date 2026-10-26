# 遥应 Teleply iOS 版（原生 SwiftUI，0.3.0 已发 TestFlight，待真机验）

执行计划：`C:\Users\39011\.claude\plans\codex-ios-app-apple-developer-program-q-piped-hanrahan.md`（10-26 用户批准）。设计依据：Obsidian 里的《Teleply - iOS SwiftUI 设计规范》v0.8；页面和按钮照网页，向电脑要东西的时机、缓存和轮询照安卓 1.0.1（`apps/android`）。

## 身份和安装

- **Bundle ID**：`com.pocketagentdesk.teleply`，桌面名字“遥应”，和安卓正式版一样（用户 10-26 确认）。旧的网页外壳 `mobile/ios`（`com.pocketagentdesk.remote`）和它的两个 Codemagic 工作流不动，两个应用可以同时装着。
- **最低系统**：iOS 26；先只支持 iPhone（iPad 一旦上架支持就不能去掉，宽屏分栏做好再开）。
- **安装**：TestFlight 内部测试，只给用户自己。应用里不放“检查更新”，新构建由 TestFlight 提醒。
- **版本**：`project.yml` 的 `MARKETING_VERSION`；构建号由 `ios-native-testflight` 取 TestFlight 上最新的加一，不用手改。

## 工程

- `project.yml`：XcodeGen 的工程描述，在云端生成 `Teleply.xcodeproj`（生成物不进 git）。Xcode 新建工程模板里的设置（Swift 6、默认主线程、图标名等）都写在这里。
- `Teleply/`：应用本体。`App/` 入口、页面切换和启动页，`Account/` 登录和我的电脑，`List/` 对话列表，`Drawer/` 侧栏，`Chat/` 会话页（时间线、Markdown、卡片、会话状态、查找和选择文字），`Composer/` 输入区（0.3.0），`Settings/` 设置和开发者选项，`Design/` 颜色、字号、动效和按钮，`Platform/` 网络收发、钥匙串、诊断记录和后台发送，`Resources/` 资源（颜色和图标由 `Assets.xcassets` 提供，开发语言简体中文）。
- `TeleplyCore/`：不碰界面的 Swift 包，Windows 上也能编译和测试。`TeleplyModel` 数据和逻辑（接口返回的宽松读法、服务地址、请求构造、错误文字、Markdown），`TeleplyState` 页面状态（主线程），`TeleplyDemo` 本地示例。依赖只有 swift-markdown 0.9.0 和它带的 swift-cmark 0.9.0（`Package.swift` 里写死提交号）。
- `TeleplyUITests/`：截图测试，用本地示例跑（启动参数 `-TeleplyDemo`、`-TeleplyAppearance`，只在调试版生效）。
- `scripts/`：`ci-check.sh`、`ci-testflight.sh`（云端），`codemagic.ps1`（本机启动构建、等结果、下载产物）。

## 怎么构建

- **本机**（Swift 6.4.1，Windows）：在 `apps/ios/TeleplyCore` 里 `swift build`、`swift test`。
- **云端检查**：Codemagic 工作流 `ios-native-check`（Xcode 27.1）。`CHECK_MODE=compile` 只编译并跑 `TeleplyCore` 测试；`CHECK_MODE=shots` 再在模拟器上截图（默认 iOS 27.1，`SHOT_RUNTIMES="iOS-27-1 iOS-26-5"` 加跑 26.5），截图在产物 `shots.zip`。
- **TestFlight**：工作流 `ios-native-testflight`。用 Codemagic 团队里的 App Store Connect 密钥 `Teleply Codemagic`（App Manager），证书引用名 `teleply_distribution`（Apple Distribution，到期 2027-10-26），描述文件引用名 `teleply_appstore`（Apple 后台名 `Teleply App Store`，App Store 类型）；Team ID `CPSVJ7235A`，Apple App ID `6826968427`。这些名字 Codemagic 的接口读不到，构建开始时才核对。上传前会核对包里的 Bundle ID、构建号、加密声明、图标、隐私清单和简体中文；只进内部测试（App Store Connect 里的内部测试组开了自动分发），不提交审核。证书别重新生成：数量有上限，重新生成还得重做描述文件。
- 本机启动构建：`apps/ios/scripts/codemagic.ps1 -ListApps` 找到应用编号，再 `codemagic.ps1 -AppId <编号> -Workflow ios-native-check -Mode shots`。令牌放在 `%USERPROFILE%\.codemagic\token.txt`。构建的是 GitHub 上的 `ios-native` 分支，先推送。
- Codemagic 免费额度每月 500 分钟；每次构建的实际分钟数记在下面。头两周用掉一半以上，就把检查构建挪到 GitHub Actions。

## 0.3.0：聊天核心（10-26 发 TestFlight 构建 4，待真机验）

做了什么：会话页底部的玻璃输入卡片（状态行、随字数长高的输入框、⌘↩ 发送、模型和模式标签的系统菜单、发送键）；运行中发送进队列（发送键读作“发送并排队”）；队列条的“立即补充”和 ⋯ 撤回；标题栏“停止这一轮”；回执写在用户气泡下面，发送中的消息淡色显示在最后；“上一条没发出去”（Claude 电脑输入框里有别的字时可“换掉电脑上的「…」再发”）、“核对待发送消息”和“待核对发送记录”；⋯ 菜单加“电脑上打开”“常用提示语”；草稿约 0.3 秒写一次、离开或退后台立即写；点了发送马上退后台用系统给的后台时间发完；“显示操作耗时”给发送计时。

真机反馈（0.2.0，用户 10-26）：列表页顶部“对话”被挤成竖排、电脑名只剩一个字。原因是标题放在系统导航栏左侧按钮区，真机上那一格只有一个字宽。0.3.0 改成页面自己画的标题栏（规范 4.1 允许）；会话页标题改放导航栏中间、靠左。

### 留给你在真机上验（0.3.0）

只在你自己的真实对话里试；我只用本地示例测。

1. **T03 键盘**：点输入框弹出键盘，输入卡片贴在键盘上方；中文输入法选字时按回车只确认候选字；在消息区往下拖，键盘跟着收下去。多行文字到七八行后在框里滚动。
2. **T05 发送**：Codex 对话里发一条，气泡下面从“提交中”变成“已接收”或“已送达”，手机轻震一下；连点两下发送只发一条；发完马上切到别的应用，回来后不重复发送。
3. **T06 排队和停止**：电脑上那一轮还在跑时再发一条，发送键读作“发送并排队”，输入卡片上方出现队列条；点“立即补充”交给这一轮；标题栏点“停止这一轮”。
4. **Claude**：发一条，先“已接收”，过一两秒变“已送达”（或“已排队”）。电脑上 Claude 输入框里有别的字时会提示没发出去，可以“换掉电脑上的「…」再发”。
5. **DeepSeek**：发一条看回执；模式标签里换权限，“完全权限”会先弹确认。
6. **模型和模式标签**：Codex 选了模型或计划模式，状态行写“设置已绑定下一条消息”；Claude 的模型菜单先显示上次的列表，“刷新电脑上的列表”才让电脑重读。
7. **草稿**：写一半返回列表、换个对话再回来、从后台划掉再打开，草稿都在。

## 0.2.0：只读（10-26 发 TestFlight 构建 3，待真机验）

做了什么：登录、我的电脑（重命名、移除、每 15 秒重读）、对话列表（来源胶囊只列这台电脑有的、列表显示菜单、搜索、子对话折叠、每 10 秒合并第一页）、侧栏（应用、项目、会话，折叠记在手机上，从左边缘拖出）、会话页的阅读部分（Markdown、代码块自动换行或原始行、表格横滑、处理过程折叠、Claude 和 Codex 的卡片只显示、长按复制 / 选择文字 / 分享、查找消息、会话状态、有新消息、加载更早消息）、实时连接和前后台、设置（外观、账号、开源组件、开发者选项：服务地址、本地示例和示例网络、诊断测速、诊断记录导出、版本）。

| 项目 | 本机测过 | 云端 / 模拟器 | 真机验过 |
|---|---|---|---|
| `TeleplyCore`（状态、存储、示例） | 通过，65 项 | 通过 | — |
| 各页截图（浅色、深色、最大字号） | — | 看过：登录、连不上、我的电脑、列表、侧栏、会话、会话状态（#9 修了侧栏漏行、最大字号行被截断） | 待验 |
| 会话页标题位置 | — | 折叠屏模拟器上被挤成一个字，改放标题栏中间靠左，普通 iPhone 待截图 | 待验 |

### 留给你在真机上验（0.2.0）

1. **T01 启动和电脑**：打开先是标志，然后登录页（右上角只有齿轮）。用真账号登录；有一台电脑会直接进列表，多台进“我的电脑”。点“连接”进列表，标题下面是电脑名；电脑多于一台时点它能切换。
2. **T01 来源和列表**：胶囊只列这台电脑上有的应用；点 ⋯ 看四个子菜单（分组、排序、状态、来源）；搜索框停手半秒就搜。子对话的“▸ 子对话 N 个”能展开。
3. **T02 进出会话**：点一条进会话，标题靠左紧挨返回键，下面一行是项目和来源；右滑或点返回回到列表。再进同一条，回到上次看的位置。
4. **T04 阅读**：电脑上让一轮正在跑，停在底部时跟着新输出；往上翻时位置不动，底部出现“有新消息 ↓”，点了回到底部。处理过程默认折叠，点开后不被刷新收回。
5. **T09 内容**：代码块“原始行”能横滑，表格能横滑，整页不左右晃；长按消息有复制、选择文字、分享。
6. **T11 前后台**：切到别的应用一会儿再回来，连接提示条恢复正常；从后台划掉再打开，回到原来的电脑和对话。
7. **T12 外观和字号**：设置里切深色；系统文字调到最大，列表行换行不截断。
8. **T15 会话状态**：有上下文数据时标题栏有圆环，点开看百分比、模型、推理强度和数据来源；80% 以上变橙色。
9. **诊断记录**：设置 → 开发者选项 → 诊断记录 → 导出，发给我（遇到问题时）。

## 0.1.0（10-26 完成）

目标：TestFlight 装上“遥应”，打开是标志页，显示版本号和默认服务的版本，在真机上提前证明证书和网络设置没问题。

| 项目 | 本机测过 | 云端 / 模拟器 | 真机验过 |
|---|---|---|---|
| `TeleplyCore` 编译和测试 | 通过（10-26，Swift 6.4.1 Windows，14 项） | 通过（Mac 上同样 14 项） | — |
| 应用编译、签名、打包 | — | 通过（Codemagic #3，Release，App Store 签名） | — |
| 上传 TestFlight | — | 成功（10-26，0.1.0（1），Delivery UUID `c363ca0a-9107-4c07-a2dc-cd341f083bf0`） | — |
| 启动页（浅色、深色、最大字号） | — | 看过（#6 截图，iOS 27.1） | 用户验过构建 1 的深色和断网画面：标志、版本、“连不上服务器”都对；“重试”字色发灰、浅蓝偏浅，构建 2 修正，待验 |
| TestFlight 安装、显示服务版本 | — | — | 用户 10-26 在 iPhone 上装上构建 1 |

Codemagic 构建记录（分钟数按构建开始到结束）：

| 构建 | 工作流 | 结果 | 分钟 | 说明 |
|---|---|---|---|---|
| #1 `6adec0d6…` | ios-native-testflight | 失败 | 2.4 | 签名一步成功（密钥、证书、描述文件都对）；Xcode 27.1 的编译器在 `RedirectRefusal` 的异步回调上自己崩溃（SILGen emitNativeToForeignThunk），改成传统回调写法 |
| #2 `6adec214…` | ios-native-testflight | 失败（未上传） | 2.2 | 打出了签名安装包，检查拦下 `UIDeviceFamily` 含 iPad：XcodeGen 的应用预设在目标一级写了 `1,2`；图标检查原来找错了位置（iOS 写在 `CFBundleIcons` 里） |
| #3 `6adec33a…` | ios-native-testflight | 成功 | 2.7 | 构建号 1；只支持 iPhone；上传 App Store Connect 无错误 |
| #4 `6adec424…` | ios-native-check（shots） | 失败 | 1.9 | 模拟器上的调试版和截图测试都编译通过；但 iOS 27.1 模拟器不接受“iPhone 17”（Incompatible device）。改为先用构建机现有的 iPhone 模拟器，没有再从该系统支持的机型里挑 |
| #5 `6adec600…` | ios-native-testflight | 成功 | 2.8 | 构建号 2：“重试”按钮改色；上传无错误 |
| #6 `6adec604…` | ios-native-check（shots） | 成功 | 6.8 | 6 张截图（浅色、深色、最大字号 × 连上、连不上），存 `F:\Android-Dev\work\ios-010-screens`。按钮颜色对了，最大字号换行不截断。模拟器挑到了折叠屏“iPhone Duo”，以后优先普通 iPhone |
| #7 `6aded34a…` | ios-native-check（shots） | 失败 | 2.1 | 阶段 1 页面第一次编译：诊断记录导出少引 `CoreTransferable` |
| #8 `6aded3fb…` | ios-native-check（shots） | 失败 | 3.1 | 设置页少引 `TeleplyDemo`（示例网络） |
| #9 `6aded501…` | ios-native-check（shots） | 成功 | 18 | 21 张截图。只有折叠屏“iPhone Duo”可用，它把导航栏放到右侧一栏；侧栏有几行没画出来（嵌套列表的行编号重复），最大字号下列表标题被截成一个字 |
| #10 `6adeda5d…` | ios-native-check（shots） | 成功 | 10 | 只编 arm64，时间减半；侧栏和最大字号的行修好。仍是 iPhone Duo（这台机器的 27.1 没有名字恰好是“iPhone 数字”的机型），改为任何非折叠 iPhone 都优先 |
| #11 `6adedd18…` | ios-native-testflight | 成功 | 4.2 | 0.2.0（3）上传，Delivery UUID `2ab3808a-2bc4-4964-9e00-5ef72c88a660` |
| #12 `6adede40…` | ios-native-check（shots） | 取消 | 29 | 0.3.0 第一次：输入区编译通过；截图脚本点输入框时没拿到焦点（刚关浮层），三套都在打字那步失败，之后 Xcode 收集模拟器诊断又空等 10 分钟，手动取消 |
| #13 `6adee582…` | ios-native-check（shots） | 成功 | 约 15 | 改用 iOS 26.5 的 iPhone 17（27.1 只有折叠屏）、不收集诊断。列表页自绘标题栏正常；发现键盘弹起后消息区空白（懒加载列表）、两个标签被拉开 |
| #14 `6adeeb2f…` | ios-native-check（shots） | 成功 | 11 | 38 张。消息区改用普通列表后键盘弹起正常；标签贴字排；排队条、立即补充、停止、模型菜单都拍到 |
| #15 `6adeee02…` | ios-native-testflight | 成功 | 4.2 | 0.3.0（4）上传，Delivery UUID `f3e949bd-1fbe-434d-add2-00a315dfc624`；截图存 `F:\Android-Dev\work\ios-030-screens` |

构建 1 真机反馈（用户，10-26）：“重试”按钮的字被外层文字的灰色盖掉，浅蓝底上看不清；深色模式的浅蓝 #8AB4FF 偏浅。改为专门的主按钮样式（`Design/PrimaryCapsuleStyle.swift`，字色由按钮自己定）：浅色照网页账号页墨色底白字，深色改 #2563EB 底白字（和网页不同，理由写进规范 2.2）。截图测试加拍“连不上服务器”画面（调试开关 `-TeleplyDemoUnreachable`）。

### 留给你在真机上验（0.1.0）

1. TestFlight 里装“遥应”0.1.0（1）。桌面图标是 Teleply 标志，名字“遥应”。
2. 打开：白底上标志和“Teleply”居中，往上浮现；下面一行“版本 0.1.0（1）”，再下面“服务 ”加服务器版本号（例如 0.27.0-dev.16）。出现服务版本，说明证书和网络设置在真机上没问题。
3. 系统切到深色模式再打开：黑底、标志和名字变白。
4. 开飞行模式后从后台划掉再打开：应写“连不上服务器，请检查网络后重试。”和“重试”；关掉飞行模式点“重试”，应出现服务版本。
5. 设置 → 显示与亮度 → 文字大小调到最大：字跟着变大，不被截断。

- 本机工具链（10-26 装）：Swift 6.4.1 在 `%LOCALAPPDATA%\Programs\Swift`；Visual Studio 2022 生成工具在 `F:\Dev\VS2022BuildTools`，Windows SDK 10.0.22621 在 `F:\Windows Kits\10`。Swift 安装时跳过了它自带的 Python 3.10 依赖，`python` 仍是原来的 3.11。新开的终端才认得 `swift`。
- Windows 上编译时会出一串 `WinSDK` / `wchar_t` 的提醒，是工具链自己的，不影响结果；`.build\debug` 建不了快捷方式的提醒也一样（Windows 默认不让普通用户建符号链接）。
- 第一天的检查（计划“工程结构”一节）：`TeleplyState` 的 Observation 和“默认主线程”、Swift Testing、swift-markdown 都能在 Windows 上编译，三块都留在 `TeleplyCore`。

本轮学到的（以后照做）：
- Xcode 27.1 的编译器编不了“异步写法”的 Objective-C 回调方法（崩溃，不是报错）。系统回调一律用传统的回调写法；`ci-testflight.sh` 发现“nearly matches optional requirement”提醒就让构建失败，免得回调悄悄不生效。
- XcodeGen 的应用预设会在目标一级填设置，盖掉工程一级的同名设置；只对某个目标生效的设置写在目标里。上传前的 Info.plist 检查要留着。
- Codemagic 接口：构建产物字段叫 `artefacts`；脚本步骤的日志挂在 `subactions` 上；证书、描述文件、密钥名没有接口可读，只能在构建开始时核对。
