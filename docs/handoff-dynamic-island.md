# 交接：iPhone 灵动岛（实时活动）

记于 2026-10-28。这份文档写给接手做灵动岛的 agent（用户会交给 DeepSeek 来做）。假定你没连过 Codemagic、苹果后台和中转服务器，也不知道之前的对话：要知道的都写在这里和 `apps/ios/README.md` 里。**到目前为止灵动岛的应用代码一行都没写**，只有第 3.5 节的密钥检查脚本；手机、中转服务、电脑端都没改。

先读第 1 节「规矩」和第 3 节「打通一遍」，再按第 7 节的阶段做。每个阶段开始前，先问第 4 节里属于这个阶段的问题。

**开始条件**：用户在聊天里说开始做哪个阶段。

**开始前**：按第 2 节「现在的情况」逐条核对，代码可能已经变了；不符合的地方先改这份文档，再动手。

几个叫法：

- **灵动岛**：iPhone 屏幕顶上那块黑色区域。
- **实时活动**（Live Activity）：苹果的「一件正在进行的事」。同一个实时活动会出现在灵动岛、锁屏、待机显示（StandBy）和 Apple Watch 的「智能叠放」里。下文说「岛」，就是指遥应的一个实时活动。
- **中转**：阿里云上的 `relay_service.py`，手机和电脑都连它。推送相关的代码在 `relay_push.py`。
- **电脑端**：Windows 上的遥应（AgentRemote），源码就在仓库根目录（`remote.py`、`notify.py`、`claude_control.py`、`claude_hooks.py` 等），装在用户电脑的 `G:\AgentRemote`。
- **苹果推送**：苹果的推送服务 APNs（Apple Push Notification service）。中转用 .p8 密钥给它发请求。

## 1. 规矩（用户定的，照做）

- **只有 `main` 分支**。改动提交到 `main`，推到 GitHub（`Zeng-HY/Agent_24-7`，远程名 `origin`）。Codemagic 构建的就是 GitHub 上的 `main`。临时分支做完合进 `main`，然后删掉分支和它的工作树。
- **同一个文件夹里还有别的 agent**：用户另开的会话还在改 iOS 和安卓（0.5.6 之后的问题）。动手前先 `git pull`、看 `git status`。提交时只 `git add` 自己改的文件，不要 `git add -A`，不要还原、覆盖或提交别人的改动。10-28 工作区里的 `tests/test_activity_records.py`（已修改）和 `docs/handoff-domain.md`（未跟踪）都不是灵动岛的，别动。
- **仓库和草稿区分开**：仓库 `D:\Personal\agent_remote` 里只放要提交的代码和文档改动。笔记、计划、日志、试验脚本、下载的文件、Python 虚拟环境、Swift 的编译目录、Codemagic 的产物、截图、备份，一律放在草稿区 `F:\Android-Dev\work\20261028-dynamic-island\`（没有就新建；那里已有的 `20261028-office-phone` 等文件夹就是这么用的）。项目自己的脚本固定写进仓库的东西（`deploy/relay/pack-027.py` 写 `dist/`，Windows 构建写 `build/`、`dist/`）可以留，这些目录 git 本来就忽略。每次提交前，`git status` 里只能看到这次要提交的文件；用 `git add <文件名>` 一个个加，不要 `git add -A` 或 `git add .`。
- **版本号**：灵动岛做成以前不动；做成了升到 0.6.0，用户说这算重大更新。细则见第 2 节「版本号怎么走」。
- **每次都要先问用户**（上一次同意不算这一次）：更新中转服务器；构建、安装或发布 Windows 版本；上传 TestFlight；改 Obsidian 里的设计规范（改前先备份）。苹果后台、Codemagic 网页上的操作由用户来点，你一步步带。iOS 代码提交并推到 `main` 不用问（用户 10-27 同意过）。
- **真账号只由用户在 iPhone 上用**。你只用本地示例测（调试版启动参数 `-TeleplyDemo`）。不要对用户正式的工作对话发测试指令。
- **钥匙不打印、不复制、不发到聊天**：Codemagic 令牌（`%USERPROFILE%\.codemagic\token.txt`）、苹果推送密钥 .p8、更新签名钥匙（`C:\Users\39011\.teleply-updates\`）、阿里云 AccessKey、手机的推送令牌。日志里的令牌只写哈希前 8 位（照 `relay_push.short`）。
- **不要重新生成**：发布证书 `teleply_distribution`（2027-10-26 到期，数量有上限，重做还得重做描述文件）；更新签名钥匙。
- **隐私**：消息、命令、回答的内容从不经过苹果；苹果只看得到状态字、来源、电脑名和几个编号。**10-28 用户另选了两次，是同一个例外**：① 长按岛要列出每个对话的模型、标题和时间，所以岛的推送 `content-state.peers` 里带标题；② 0.6.2 起普通通知的第一行也是对话标题（「Codex · 我的电脑」放第二行），叠成一摞时通知中心里也看得到标题。两处都经过中转和苹果；`relay_push.py` 开头的说明同步改了。
- **省 Codemagic 分钟**：免费每月 500 分钟。只编译约 3 分钟，上传 TestFlight 约 5 分钟，截图 10–18 分钟。能只编译就不截图；截图时用 `-Only "testLight"` 只拍浅色。每次构建记进 `apps/ios/README.md` 的构建表。
- **设计**：
  - 少点几下。用户原话：「在尽量少的交互的情况下，能够快速地实现目标…直观、简洁，交互尽可能地省力。」
  - 字短，用户一看就懂，和现有通知的说法一致：「在干活」「在等你」「好了」「出错停了」「断开了」（现有的三句见 `relay_push.WORDS`）。
  - 颜色和来源标志用应用自己的：`apps/ios/Teleply/Design/Palette.swift`、`Design/Marks.swift`。网页的设计语言：`docs/design-language.md`。
  - 打开对话一律停在最新一条（用户 10-27 定的）。点岛进对话也一样，走 `AppModel.openNotification`，它本来就这样。
  - 给用户的开关放在 设置 → 手机通知；只给开发用的（试岛、看样子）放在 设置 → 开发者选项。
- **看 Claude 的卡片用 UI Automation 读窗口，不看截图**：试的时候截图被别的应用的窗口盖住过。
- **记录**：每个 iOS 版本在 `apps/ios/README.md` 顶上写一节：做了什么、检查情况、「留给你在真机上验」。照已有各节的写法。
- **跟用户说话**：先给结论，再说原因。用大白话，技术词第一次出现时用半句话解释。不用「触发、落地、对齐、闭环、链路、赋能」这类词。要用户做的事，一步一句写清楚。

## 2. 现在的情况（2026-10-28 查到的）

### 版本和发布

- **iOS 0.5.5**（构建 11）在 TestFlight 上，等用户在真机上验（Office 文件由手机自己显示）。0.5.4、0.5.5 的真机检查清单在 `apps/ios/README.md`。
- **iOS 0.5.6** 已改完，在 `main` 上（f18038c、e9bbf3d，记录在 efd672f）：
  - 改了什么：文件页照微信铺满屏幕，操作收进右上角的 ⋯；设置里去掉 Bark，「遥应通知」只剩一个绿色开关，没有说明文字；「外观」改成一行三段的选择；语音输入的开关也改成绿色。
  - 检查到哪：云端 #34 编译和浅色截图通过，Mac 上 `TeleplyCore` 158 项测试通过；没拍深色和最大字号，没上真机。截图测试里「右滑拉出侧栏时那一行不应被打开」偶尔失败（#33），和改动无关。
  - 为什么先没上传：用户说「改完了先不要发布，我还有些其他的问题要你一并修改发布」。后来 10-28 同意传阶段零的试验构建，所以 0.5.6 随构建 12 进了 TestFlight（内部测试），不算正式发布。
- **灵动岛阶段零**的代码已在 `main`（11b4fd8、f4d25a5、89b56df，文档 25147e2，中转测试 c16e1f9），云端 #37 只编译通过，Mac 上 `TeleplyCore` 175 项通过；**0.5.6（12）已传 TestFlight**（#38，Delivery UUID `d7c07f17-4128-45af-b70b-f71904714a1c`，6 分钟），**10-28 真机通过**：锁屏卡片和计时、点「让中转改一下」变 ✓、解锁回桌面看到灵动岛。中转已更新，扩展的描述文件已传到 Codemagic（`teleply_island_appstore`）。用户说紧凑的样子不美观，阶段一按 5.4 重新设计。版本号仍是 0.5.6；按第 2 节，0.6.0 要等阶段一也验收通过。
- **灵动岛阶段一**的代码在 `main`（0ddebaa 电脑/中转、1cfc5e9 手机端、18ed29a 手机开着对话也更新岛、3f768ca 样子预览页、9ea65ae 只给刚发的消息开岛、32a0324/25cd78a 测试、ae00f5e 真机记录、5797efd 试岛用当前来源、eb726c3 遥应标志和长按列表、052df56 开关挪到手机通知、214ae79 卡片加大/手表加标题）：手机发送开岛、电脑报 `running`、中转远程开启/状态更新/断开变灰。Windows **0.27.0-dev.28** 已构建并装到这台电脑（含 DeepSeek 答题修复 `70fe829`）；中转已更新到带标题/长按列表的包。真机 0.5.6（13）验过功能后，用户定了遥应标志/长按列表，并指出锁屏卡片偏矮、手表没标题；现在 **0.6.1（16）** 已上传（#48，Delivery UUID `8644d17c-4f06-422a-84bf-eaedfd8f0c9f`），待真机验。本机 183 项 Swift、99 项 Python 通过。
- **iOS 0.6.2**（通知去重和样子，10-28）的代码在 `main`（9e9763f 中转、20906da 手机和扩展、d5f3f06 并发警告、f0d862b 紧凑岛定宽、915b5e2 样子页、5fcf9e5 文档）：一阵子只响一次、普通通知带标题并叠成一摞、岛收起补静默记录、锁屏卡片白底、新建对话也开岛、紧凑岛定宽。本机 187 项 Swift、103 项 Python 通过；云端 #50、#52 只编译通过，Mac 上 187 项通过；#53 截图 6 张。**中转已更新**（10-28 15:21，旧文件在 `/opt/agent-relay-027/previous-20261028-152116`）；**Windows 不改**（标题和 running 已经在 dev.28 里）；**0.6.2（17）已传 TestFlight**（#55，Delivery UUID `8f7b7fc5-238a-4ea6-9a29-b7335f572a08`），待真机验。检查清单见 `apps/ios/README.md` 的 0.6.2 一节。
- **iOS 0.6.3**（一台电脑一个岛，10-28）的代码在 `main`（48cbe41 中转和电脑、ad06702 手机和扩展、9bf1574 展开边距、45bea5e 手表黑底和文档）：按对话汇总计数、长按列表、锁屏、手表；岛登记补推；电脑轮询加快。本机 189 项 Swift、109 项 Python 通过；#56 编译通过，Mac 上 189 项；#57 截图 6 张。**中转已更新**（10-28 17:41 前后）、**Windows dev.29 已装**；**0.6.3（18）已传 TestFlight**（#58，Delivery UUID `638c72d7-e28b-4e28-a0f6-dd46131f77a5`），待真机验。检查清单见 `apps/ios/README.md` 的 0.6.3 一节。
- **iOS 0.6.4**（用时准、岛及时、看得到在思考，10-29）的代码在 `main`（e500236 电脑/中转/手机/测试，54fcbdf 文档和示例，d42e6b8 截图修正）：电脑按位置增量读记录、用记录里的开始和结束时间；中转保存起止时间、全部结束时保留刚结束的对话、快照补漏、远程开岛查数据库；岛和会话页显示动作与「正在思考」计时。本机 191 项 Swift、174 项 Python 全过；Codemagic 编译 `6ae338ce3e9be9cf26505d04`、截图 `6ae33cfd8e64ccacf5b3b1ef` 通过。中转已更新（10-29 20:50，旧文件 `/opt/agent-relay-027/previous-20261029-205052`）；Windows `0.27.0-dev.30`（30）已构建、装到这台电脑（20:55），并发布到阿里云和 GitHub 预发布 `windows-v0.27.0-dev.30`。**0.6.4（19）已传 TestFlight**（Codemagic `6ae3436e79b17edbd333b902`，12 分钟，Delivery UUID `f47e104a-5e30-4d12-8f0b-0298748688db`），待真机验。截图和验收清单见 `apps/ios/README.md` 的 0.6.4 一节。
- **0.6.5**（岛推送合并不丢、发出去的话不消失、英文版，10-30）的代码在 `main`（6ab9c62，a2832f7 修启动换行，8bf13b6 英文截图）：中转每座岛最多 10 秒一次、合并到最新、20 秒内一定推到；快照只在内容变了时推；列表按最近动作排并带 `more`；手机前台读 `POST /account/push/island-state` 自己补岛；发出去的消息按请求编号/文字加时间留在时间线，记录出现才换；新一轮先空 step；应用和扩展加 `Localizable.xcstrings`、`en.lproj`；中转按手机语言写通知和岛提醒。本机 197 项 Swift、170 项 Python 全过；Codemagic 编译 `6ae3e61be2705e912f5af296` 通过（Mac 197 项），英文截图 `6ae3e69ff6e1538efa7774a5` 通过（15 张，存 `F:\Android-Dev\work\20261029-island-064\shots-065`）。截图和 0.6.5 验收见 `apps/ios/README.md` 的 0.6.5 一节；0.6.5（21）已传 TestFlight（Codemagic `6ae3ee02c6cd057eaef31451`，4 分钟，Delivery UUID `7b4d31f6-487a-44ac-9d43-3a251db68abe`）。Windows `0.27.0-dev.31`（31）已构建、装到这台电脑，并发布到阿里云和 GitHub 预发布 `windows-v0.27.0-dev.31`（三个文件都在；安装包 SHA256 `255F4D12…`）。中转已更新（10-30 09:26，旧文件 `/opt/agent-relay-027/previous-20261030-092624`）。
- **`project.yml`**：`MARKETING_VERSION: "0.6.4"`，`CURRENT_PROJECT_VERSION: "1"`。构建号不用手改：`ci-testflight.sh` 取 TestFlight 上这个版本最新的号加一，每个版本从 1 开始。
- **安卓**：同样的文件页和通知开关也改了（03ac35a、583f84f），没发。灵动岛不碰 `apps/android`。
- **Windows**：**0.27.0-dev.30 已构建、装到这台电脑并发布**（10-29 20:55 装，21:07 前后发）：按位置增量读记录、用记录里的开始/结束时间、启动/重连补报 running、60 秒快照和动作；安装包、清单和签名已传阿里云，GitHub 预发布 `windows-v0.27.0-dev.30` 也附了三个文件。`dist/AgentRemote-0.27.0-dev.30-Setup.exe`，SHA256 `DD1A17E4…`。dev.29 是 0.6.3 用的那版（有任务时 2 秒、空闲 5 秒看记录）。
- **中转**：0.27 服务，10-26 开通了 iPhone 推送。现在的版本号看手机启动页「服务」后面那一串。**0.6.3 的中转已部署**（10-28 17:41 前后，包 `dist/agent-relay-0.27.0-dev.zip`，SHA256 `B80272DF…`）：新表 `push_conversations`、一台电脑一个岛、岛登记补推、日志级别 INFO。0.6.2 手机仍按旧的一对话一岛工作。

### 版本号怎么走（用户 10-28 定的）

- 灵动岛做成以前版本号不动（那时是 0.5.6）；阶段零、阶段一真机验收通过后，10-28 已升 0.6.0，用户又让外观收尾成 0.6.1（构建 16）。要在 TestFlight 上试的构建就用当时的版本号，构建号自动加一。每次上传前都要问用户，因为它会把 `main` 上当时所有的改动一起带上。
- 「灵动岛」开关已从 开发者选项 挪到 设置 → 手机通知，默认跟着遥应通知开（用户 10-28 选的），用户手动关过就记手动选择。
- **做成的标准**：第 7 节的阶段零和阶段一，在用户的 iPhone 上验收通过。
- 阶段二、三、四，每做成一个加一个小版本。用户另有说法时照用户的：10-28 下午用户把 0.6.2 定成通知去重和样子，0.6.3 定成「一台电脑一个岛，显示几个对话在工作中 / 等你定」；此后的阶段从 0.6.4 起。

### 手机（`apps/ios`）

- 工程由 XcodeGen 生成，描述文件是 `apps/ios/project.yml`。现在三个目标：`Teleply`（应用）、`TeleplyIslandWidget`（灵动岛的扩展，Bundle ID `com.pocketagentdesk.teleply.island`）和 `TeleplyUITests`（截图测试）。最低 iOS 26，只支持 iPhone，Swift 6，默认主线程（`SWIFT_DEFAULT_ACTOR_ISOLATION: MainActor`）。
- 版本见上面「版本和发布」。
- **阶段零加的**：扩展入口在 `TeleplyIslandWidget/IslandWidgets.swift`，画面在 `IslandViews.swift`；应用和扩展共用 `Shared/IslandAttributes.swift`；纯逻辑在 `TeleplyCore/Sources/TeleplyIsland`。`Info.plist` 加了 `NSSupportsLiveActivities` 和网址协议 `teleply`（`teleply://open?d=…&a=…&c=…`，`PushTarget(url:)` 校验）。开发者选项的三行在 `SettingsView.swift`，动作在 `AppModel+Island.swift`。点通知进对话仍靠通知里的 `teleply` 字段：`TeleplyModel/Push.swift` 的 `PushTarget`，再由 `AppModel.openNotification` 核对账号和电脑后打开。
- 登录信息在钥匙串里，访问级别是 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`（`Teleply/Platform/KeychainVault.swift:42`）。开机后解锁过一次，锁屏时也读得到。所以岛上的按钮在锁屏时也能发请求。
- 作答都走 `WorkspaceModel.action(route, body)`（`TeleplyCore/Sources/TeleplyState/WorkspaceModel.swift:481`）：`codex/answer`、`claude/choose`（要电脑给的 `token`）、`deepseek/approval` 等。请求经中转的 `/d/{电脑编号}/…` 到电脑（`TeleplyModel/Relay.swift`）。它从不自己重发：回复丢了就留给用户核对。
- 推送相关：`Teleply/Platform/Push.swift`（权限、令牌、点通知），`TeleplyState/PushModel.swift`，`TeleplyModel/Push.swift`（`/account/push/*` 请求）。

### 中转（`relay_push.py`）

- 中转对每台在线、账号下有登记手机的电脑，经隧道读它的事件流 `GET /api/notify/push`（一行一个 JSON）。事件只有三种：`done`、`failed`、`waiting`，带 `app` 和 `chat`（`deliver`，`relay_push.py:294`）。不认识的事件直接丢掉。
- 中转自己写字（`WORDS`），用普通通知发给苹果：请求头 `apns-push-type: alert`、`apns-priority: 10`，主题 `com.pocketagentdesk.teleply`（`Apns.send`，`relay_push.py:88`）。同一个对话的同一种事 60 秒内只发一次；一个账号一小时最多 30 条。
- 表：手机登记 `push_phones`，去重 `push_events`（建表在 `relay_accounts.py:60`）。手机的请求是 `POST /account/push/state|register|unregister|test`（`relay_service.py:272` 转给 `Push.account`）。
- **阶段零加的岛**：`push_activities`（每个岛的推送令牌、电脑、来源、对话、最后状态；`relay_push.py` 的 `activity`）、`push_start`（远程开启令牌）；请求 `POST /account/push/activity|start-token|island-test`。`Apns.send` 多了 `push_type`、`priority`、`topic` 三个参数，普通通知的默认值不变。`island-test` 用 `liveactivity` 主题给登记过的岛推一条「好了」，苹果拒收时把原因交给手机。
- 电脑掉线时，中转什么都不发（`relay_push.py` 里没有这段）。它知道哪些电脑在线：`self.hub.connections`（`relay_push.py:246`）。
- 苹果推送密钥：名字 `TeleplyAPNs`，Production 环境，Topic Specific 类型。后台的主题列表按 Bundle ID 登记，只有 `com.pocketagentdesk.teleply` 一项（10-28 用户截图，400 个名额用了 1 个），灵动岛没有单独一项。**10-28 已证实它认岛用的主题**：构建 12 上点「让中转改一下」，锁屏卡片从「在干活」变成「✓ 好了 · 用了 1 秒」，说明 `com.pocketagentdesk.teleply.push-type.liveactivity` 被接受，不用换密钥。

### 电脑端

- `notify.py` 的 `Notifier` 有任务在跑时每 2 秒（`POLL_FAST`）、空闲每 5 秒（`POLL_SECONDS`）看每个应用最新的 30 个对话。0.6.4 起每个文件记住上次读到的位置，变长只读新增部分；第一次往回读最多 64MB。开始、结束时间从记录里读（Codex 的 `task_started`/`task_complete`，Claude 的用户消息/最后回答，DeepSeek 的 `turn/start`/`turn/end`）。报给中转是 `self.relay.publish("", "", extra={"kind": …, "app": …, "chat": …, "since"/"started"/"ended": …})`；running 在电脑启动和中转重连后会再报一次，已经结束的轮次不补报。有对话在跑时每 60 秒发一个 `snapshot`，另有动作变化时的 `step`；这两种不留着给断线补读。
- 给中转的事件流和给 ntfy 应用的是两个（`self.relay` 和 `self.feed`），新事件只进 `self.relay`。事件流最多留 100 条、12 小时（`ntfy_feed.py` 的 `KEEP_COUNT`、`KEEP_SECONDS`），给断线后补读。
- Claude 的问题和权限确认经 Claude Code 的 hook 进来（`claude_hooks.py`），由 `Notifier.asking` 报成 `waiting`（`notify.py:354`）。hook 最多等一小时（`HOOK_TIMEOUT = 3600`）。每个问题有一个随机编号 `Ask.id`（不含内容），手机的每次点按都要带上电脑给的 `stamp`，旧画面上的点按会被拒。
- Claude 桌面版的 Usage 按钮写着每周额度，例如 `Usage: Weekly · all models: 48%, Resets Sat 3:00 PM`（`claude_control.py:97` 的说明）。电脑现在只读上下文，这一段没读。额度用完时 Claude 窗口有一条提示条，现在被当成「不是问题」跳过（`claude_control.py:361`）。
- 版本 `windows-version.json`：`0.27.0-dev.31`，build 31（10-30 已构建、装到这台电脑，并发布到阿里云和 GitHub 预发布）。

## 3. 打通一遍

### 3.0 一次完整的流程

改一处灵动岛的功能，从写代码到用户手机上看到，按这个顺序走：

1. 改代码。能放进 `TeleplyCore` 的逻辑都放进去，在这台电脑上跑 `swift test`（3.1）。中转和电脑端跑 Python 测试（3.1）。
2. 提交，`git push origin main`。
3. Codemagic 只编译（3.2）。界面代码在这一步第一次被编译，错了就改，再推、再编。
4. 要用户看样子时，跑一次截图（3.2），把截图给用户看。
5. 中转有改动：打包，请用户在 Workbench 更新（3.4，先问）。
6. 电脑端有改动：构建，问过以后装到这台电脑（3.6）；要发布再问一次。
7. 上传 TestFlight（3.7，先问）。用户手机上的 TestFlight 会提醒。
8. 在 `apps/ios/README.md` 写这一版的一节，列出「留给你在真机上验」；用户验完告诉你结果。

发版的先后：**中转先，电脑端第二，手机最后**。这样任何一步停住，老的手机和电脑照常工作（见 3.6 最后一条）。

### 3.1 这台电脑上

- 仓库：`D:\Personal\agent_remote`，分支 `main`。
- **Swift**：只能编不碰界面的 Swift 包 `apps/ios/TeleplyCore`。工具链装在 `%LOCALAPPDATA%\Programs\Swift`，不在 PATH 上。PowerShell 里先运行：

```powershell
$s = "$env:LOCALAPPDATA\Programs\Swift"
$env:Path = "$s\Toolchains\6.4.1+Asserts\usr\bin;$s\Runtimes\6.4.1\usr\bin;$env:Path"
$env:SDKROOT = "$s\Platforms\6.4.1\Windows.platform\Developer\SDKs\Windows.sdk"
```

  然后在一个带超时的 PowerShell job 里跑测试（有个等实时连接的测试出错时会一直挂着）。`--scratch-path` 指到草稿区，不要放进仓库：

```powershell
swift test --package-path apps/ios/TeleplyCore --scratch-path F:\Android-Dev\work\20261028-dynamic-island\swift-build
```

  编译时会冒出一串 `WinSDK` / `wchar_t` 提醒和 `.build\debug` 建不了快捷方式的提醒，是工具链自己的，不用管。
- **SwiftUI、ActivityKit、WidgetKit、AppIntents 这台电脑编不了**，只能在 Codemagic 上编。所以状态怎么变、发什么请求、JSON 长什么样，都写进 `TeleplyCore` 在这里测；界面层越薄越好。
- **Python 测试**（unittest）：

```powershell
python -m unittest tests.test_relay_push tests.test_notify tests.test_ntfy_feed tests.test_claude_hooks tests.test_claude_control
```

  `test_relay_push` 要 `requirements-relay.txt` 里的 httpx、h2、cryptography，缺了就跳过。在草稿区建一个虚拟环境（例如 `F:\Android-Dev\work\20261028-dynamic-island\relay-venv`），装上 `requirements-relay.txt` 再跑，不要装进仓库的 `.venv`。
- 小坑：在整个仓库上递归搜索很慢（有很大的目录），搜索时指定子目录或文件。

### 3.2 Codemagic（云端的 Mac：编译、截图、签名、上传）

- **是什么**：在云端 Mac 上按仓库根目录的 `codemagic.yaml` 编译、跑测试、截图、签名、上传 TestFlight。应用名 `Agent_24-7`，编号 `6ad9f7f9a1287ea2ab55b0a7`。
- **两个工作流**：
  - `ios-native-check`：`CHECK_MODE=compile` 只编译，并在 Mac 上跑 `TeleplyCore` 测试；`CHECK_MODE=shots` 再在模拟器上截图（`apps/ios/scripts/ci-check.sh`），截图在产物 `shots.zip`。默认用 iOS 26.5 的 iPhone 17（有灵动岛）；iOS 27.1 的模拟器只有折叠屏「iPhone Duo」。
  - `ios-native-testflight`：取 TestFlight 上最新的构建号加一，用 App Store 描述文件签名，检查安装包，上传到 TestFlight 内部测试（`apps/ios/scripts/ci-testflight.sh`）。不提交审核。
- **令牌**：已经放在 `%USERPROFILE%\.codemagic\token.txt`。只让脚本读，不要打印。
- **启动构建**：在仓库根目录用 PowerShell。先 `git push`，它构建的是 GitHub 上的 `main`。

```powershell
apps/ios/scripts/codemagic.ps1 -AppId 6ad9f7f9a1287ea2ab55b0a7 -Workflow ios-native-check -Mode compile -OutDir F:\Android-Dev\work\20261028-dynamic-island\codemagic
```

```powershell
apps/ios/scripts/codemagic.ps1 -AppId 6ad9f7f9a1287ea2ab55b0a7 -Workflow ios-native-check -Mode shots -Only "testLight" -OutDir F:\Android-Dev\work\20261028-dynamic-island\codemagic
```

```powershell
apps/ios/scripts/codemagic.ps1 -AppId 6ad9f7f9a1287ea2ab55b0a7 -Workflow ios-native-testflight -OutDir F:\Android-Dev\work\20261028-dynamic-island\codemagic
```

  也可以把编号放进环境变量 `TELEPLY_CODEMAGIC_APP`，就不用每次写 `-AppId`。脚本每 30 秒报一次状态，结束后把产物下到 `-OutDir` 指的文件夹。不写时默认是仓库里的 `apps/ios/build/codemagic/`，所以每次都加上 `-OutDir F:\Android-Dev\work\20261028-dynamic-island\codemagic`。
- **常见情况**：
  - 下载产物常超时：`codemagic.ps1 -BuildId <构建编号> -OutDir F:\Android-Dev\work\20261028-dynamic-island\codemagic` 再取一次。
  - 构建卡住：`POST https://api.codemagic.io/builds/<构建编号>/cancel`，请求头 `x-auth-token` 填令牌（用脚本读文件，别把令牌写进命令）。
  - 晚上免费 Mac 常排队 30–50 分钟。
  - 构建详情里，产物字段叫 `artefacts`；每一步的日志在 `buildActions[].subactions[].logUrl`。证书、描述文件、密钥的名字没有接口可读，构建开始时才核对。
- **Xcode 27.1 的坑**：
  - Objective-C 回调方法写成 `async` 形式，编译器会崩溃。系统回调一律用传统的回调写法（completion handler）。`ci-testflight.sh` 看到 "nearly matches optional requirement" 就让构建失败。
  - XcodeGen 的预设会在目标一级写 `TARGETED_DEVICE_FAMILY: "1,2"`，盖掉工程一级的值。新扩展也要在目标里写 `TARGETED_DEVICE_FAMILY: "1"`。
  - 默认主线程的设置下，交给系统框架的数据类型要写成 `nonisolated struct`（照 `ProcessGroup`、`TimelineRole` 的写法），否则 `Codable`、`ActivityAttributes` 会报隔离错误。
  - `JSONValue` 能写成 `nil`：`cond ? value : nil` 里的 `nil` 是 `JSONValue.null`，`if let` 照样拿得到。要表示「没有」时写 `JSONValue?.none`。

### 3.3 苹果后台（用户来点，你一步步带）

岛的画面放在一个**小组件扩展**里。它是装在应用里的第二个程序，要有自己的 App ID 和描述文件。苹果后台：https://developer.apple.com/account ，Team ID `CPSVJ7235A`。

1. **登记扩展的 App ID**：Certificates, IDs & Profiles → Identifiers → ＋ → App IDs → App。Description 填 `Teleply Island`，Bundle ID 选 Explicit，填 `com.pocketagentdesk.teleply.island`。能力（Capabilities）一项都不勾。
2. **做它的描述文件**：Profiles → ＋ → Distribution 下的 App Store Connect → App ID 选 `com.pocketagentdesk.teleply.island` → 证书选现有的那张 Apple Distribution（2027-10-26 到期，**不要新建**）→ 名字 `Teleply Island App Store` → Generate → Download。
3. **传到 Codemagic**：在放 `teleply_appstore` 的同一处（团队设置 → Code signing identities → iOS provisioning profiles）Upload，引用名填 `teleply_island_appstore`。
4. **改 `codemagic.yaml`**（你来改）：`ios-native-testflight` 的 `ios_signing.provisioning_profiles` 下加一行 `- teleply_island_appstore`。`ci-testflight.sh` 里的 `xcode-project use-profiles` 会按 Bundle ID 给应用和扩展各配一个。
5. **主应用的 App ID 和描述文件 `teleply_appstore` 不用动**。实时活动不要额外的能力，岛的推送用主应用已有的推送权限。只有将来选了「共享钥匙串」或「共享文件夹」（第 4 节问题 5 的 D、方案三的 B）才要给两个 App ID 都开能力、重做两个描述文件、在 Codemagic 里替换，到时再做。

**10-28 已做**：扩展 App ID `com.pocketagentdesk.teleply.island` 和描述文件 `Teleply Island App Store` 都登记好了，描述文件传到 Codemagic 的引用名是 `teleply_island_appstore`；构建 12 的签名日志里两个描述文件都读到了，包装出来也对。

### 3.4 中转服务器（用户在阿里云 Workbench 里运行，你写代码和说明）

- **服务器**：阿里云 `8.166.15.235`（广州）。0.27 服务叫 `agent-relay-027.service`，装在 `/opt/agent-relay-027/`，Python 环境 `/opt/agent-relay-027/.venv/`，监听 `127.0.0.1:18771`，前面是 Caddy。推送设置在 `/etc/agent-relay/push.env`（root 0600）。中转只认 `8.166.15.235` 这个地址，不要改（换域名见 `docs/handoff-domain.md`）。
- 服务器上的操作一直是用户在阿里云网页终端（Workbench）里运行仓库里的脚本。你不直接登录服务器。
- **更新**：
  1. 这台电脑上运行 `python deploy/relay/pack-027.py`，得到 `dist/agent-relay-0.27.0-dev.zip`。
  2. 请用户把它传到服务器的 `/home/admin/`，然后在 Workbench 运行：

```bash
python3 -m zipfile -e /home/admin/agent-relay-0.27.0-dev.zip /home/admin/agent-relay-027-new
```

```bash
sudo bash /home/admin/agent-relay-027-new/update-027.sh
```

  换下的文件留在 `/opt/agent-relay-027/previous-<时间>/`，新的起不来会自动换回。数据库不用动，新表在服务启动时建。
- **10-28 已更新**：构建 12 上传前，服务器用这个包更新过，换下的文件在 `/opt/agent-relay-027/previous-20261028-103158`；脚本的健康检查通过（`/account` 能打开）。
- **加了新文件时**：`deploy/relay/pack-027.py` 的 `RELAY`（或 `DEPLOY`）列表和 `deploy/relay/update-027.sh` 的 `files=(…)` **两处都要加**，否则不会打进包，也不会装上。要新的 Python 库就写进 `requirements-relay.txt`，`update-027.sh` 会先装，装不上就什么都不换。
- **看日志**：请用户运行 `sudo journalctl -u agent-relay-027.service -n 50`，把输出贴回来。日志里没有密钥和完整令牌。
- 关掉推送的办法在 `deploy/relay/README-027.md`「开启遥应通知」一节末尾。

### 3.5 先测：推送密钥认不认岛的主题（不用手机）

岛的推送和普通通知不同：请求头 `apns-push-type: liveactivity`，主题 `com.pocketagentdesk.teleply.push-type.liveactivity`，只能用 .p8 密钥签的令牌（中转本来就是）。现在的密钥是 Topic Specific 的，要先证明苹果让它发这个主题。

脚本已经写好：`deploy/relay/check-island-topic.py`（10-28，已加进 `pack-027.py` 的 `DEPLOY` 列表）。它读服务用的密钥（`/etc/agent-relay/push.env`），向苹果问三次，对象都是一部编出来的手机：

1. 普通通知，发到密钥本来管的主题：应当被收下（苹果回 `400 BadDeviceToken`，只是手机是假的）。
2. 对照：发到一个没人用的主题：应当被拒绝。这证明苹果先看主题、再看手机，第 3 个回答才有意义。
3. 岛的更新（`liveactivity`，主题 `…push-type.liveactivity`）：被收下就是认，被拒绝就是不认。

它什么都不保存、不重启服务，不打印密钥，也不会推到任何手机上。签名代码借用装好的服务（`/opt/agent-relay-027/relay_push.py`），所以可以单独上传。用户把它传到 `/home/admin/`，运行：

```bash
sudo /opt/agent-relay-027/.venv/bin/python /home/admin/check-island-topic.py
```

最后一行是结论：

- 「能发」（退出码 0）：往下做。阶段零有了真的岛以后，用真令牌再推一次，算最后确认。
- 「不能发」（退出码 1）：请用户在苹果后台 Keys 里看这把密钥能不能加上这个主题；不能的话新建一把 Production 密钥（Team Scoped，或 Topic Specific 但两个主题都包含），再运行一次 `configure-push.py` 换上（步骤见 `README-027.md`）。换完先在手机上点「试推一条」，确认普通通知还能收到。
- 「看不出来」「连不上」或「密钥本身的问题」（退出码 2）：照它说的查。看不出来，就等阶段零用真令牌试。

**10-28 的结果**：三问都回 `400 BadDeviceToken`（HTTP/2），对照也被放行，结论「看不出来」。苹果先查手机，手机是假的就退回，走不到查主题那一步。能确定的只有两件：密钥本身好着，服务器连得上苹果。用户随后在后台看了这把密钥（`TeleplyAPNs`）：主题按 Bundle ID 登记，只有 `com.pocketagentdesk.teleply` 一项，没有灵动岛单独的一项可勾。所以大概率认，但没证实。阶段零里「让中转改一下」成功，就证实了；那时被拒，再按上面「不能发」一条换密钥。

**10-28 真机证实**：构建 12 上点「让中转改一下」，锁屏卡片变成「✓ 好了 · 用了 1 秒」；这一步只能由中转的 APNs 推送做到，说明密钥认这个主题。3.5 的疑问解决，不用换密钥。

### 3.6 电脑端（Windows）

- 读代码、跑测试不用问；**构建、安装、发布前都先问用户**。
- **构建**：`windows-version.json` 的版本和 build 都加一（例如 `0.27.0-dev.27` / 27），写好 `windows-release-notes.json`，然后：

```powershell
deploy/windows/build.ps1 -InnoCompiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

  它默认用仓库的 `.venv\Scripts\python.exe`，得到 `dist/AgentRemote-<版本>-Setup.exe` 和 `dist/windows-update.json`。
  构建前确认 `.venv` 装了 `requirements.txt` **和** `requirements-build.txt`。10-28 这台 `.venv` 少了 pystray/pywebview，打出的 dev.27 一启动就弹「启动未完成，请检查运行环境。」；补装依赖、重新打包、重装才好。启动失败时先用安装版的 `--self-test` 排除环境，再查 `.venv` 缺的包。
- **装到这台电脑**：运行安装包（装在 `G:\AgentRemote`）。装好后一分钟内会重新连上中转。
- **发布**（用户同意后）：

```powershell
.toolchain\release-venv\Scripts\python.exe deploy\updates\publish.py windows
```

  再在 GitHub 建预发布 `windows-v<版本>`，附三个文件：安装包、`windows-update.json`、`windows-update.json.sig`。这台电脑没装 gh 命令行：用 GitHub 的 REST 接口和 git 存着的登录（`git credential fill`，不要打印），先建草稿、传文件、核对 GitHub 给的 sha256，再发布。详见 `deploy/updates/README.md`，阿里云返回 `UserDisable` 时怎么办也在那里。
- **新旧搭配**：老中转不认新事件，直接丢掉（`deliver` 开头就是这样），所以电脑端可以先发。新中转遇到老电脑，只收得到 done/failed/waiting，岛照样能更新这三种。手机不能假定新事件一定会来。

### 3.7 TestFlight 和真机

- **上传**（先问用户）：`codemagic.ps1 … -Workflow ios-native-testflight`。成功后 TestFlight 的内部测试组会自动分发。把 Codemagic 编号、分钟数、Delivery UUID 记进 README 的构建表。
- **扩展的检查**：在 `ci-testflight.sh` 的 `check_ipa` 里加几条，构建时就拦下常见错误：
  - `Payload/Teleply.app/PlugIns/TeleplyIslandWidget.appex` 存在；
  - 扩展的 `CFBundleIdentifier` 是 `com.pocketagentdesk.teleply.island`，`CFBundleVersion` 等于这次的构建号，`CFBundleShortVersionString` 和应用的一样（不一样 App Store Connect 会拒）；
  - 扩展的 `NSExtension:NSExtensionPointIdentifier` 是 `com.apple.widgetkit-extension`；
  - 应用的 `NSSupportsLiveActivities` 是 `true`。
- **真机**：岛在模拟器上能显示，但锁屏、待机显示、手表、提醒弹开这些要真机看。每一版写「留给你在真机上验」，一条一句，用户照着做。

## 4. 开始前要问用户的

按阶段问，问到了再做。每题都给了推荐。

**阶段一前**

1. **同一件事响几次**：推荐有岛时「在等你」「好了」「出错停了」只更新岛（岛弹开一下、响一声），不再另发通知；岛没登记上时照旧发通知。另一种是两样都发，会响两次。只更新岛的代价：通知中心里没有这条记录。
2. **电脑上开始的对话要不要也亮岛**：推荐「跑过 1 分钟还没完才亮」。远程开启的岛要带一条提醒（以苹果文档为准），会亮一次屏。另一种是只给手机上发出去的对话亮岛。
3. **电脑断开时岛要不要响**：推荐只变灰、不响；断开超过 30 分钟就收起。
4. **灵动岛的开关默认开还是关**（放在 设置 → 手机通知，和遥应通知放一起）：推荐遥应通知开着时默认开。

**阶段二前**

5. **岛上能写多少字**（决定「在岛上直接回答」能做到哪一步）：
   - A：只写状态和按钮，不写问题内容。岛上只能「拒绝」，或「去看看 ›」进对话里那张卡片。苹果看到的和现在一样。**推荐先做 A**。
   - B：A 加「手机自己补字」：有问题时中转多发一条后台推送叫醒手机，手机经中转向电脑要问题内容，在手机上把字写进岛里（不经过苹果）。叫得醒时岛上显示命令和选项，能直接「允许」；叫不醒（应用被划掉、系统限流）时退回 A。
   - C：让苹果看到问题和命令。最省事，但违背现在的隐私规矩。
   - D：电脑加密、手机在岛的画面里解密。苹果看不到，岛上总有字；要先做小试验，还要给两个 App ID 开共享钥匙串。
6. **锁屏时点「允许」要不要先刷脸**：推荐要。

**阶段三前**

7. **进度图标**会让苹果看到「在跑命令」「在改文件」这类类型（不含命令本身），可以吗？
8. **几个对话同时跑**：推荐让系统自己排（方案三的 A）。以后要不要做成一台电脑一个岛（B，要改隐私规矩或用共享文件夹）？

**阶段四前**

9. **额度倒计时**只做 Claude（电脑窗口上本来就写着），还是 Codex 也做（要先查 Codex 的记录里有没有额度）？

## 5. 总体设计

### 5.1 一个岛对应一个对话的一轮

> 0.6.3 起改成**一台电脑一个岛**：这台电脑上所有在干活、等你定的对话由这一个岛汇总显示（5.3 的 0.6.3 一节）。下面 5.1–5.3 的早期说明保留，是 0.6.2 及以前的做法。

一个岛从这一轮开始（或手机发出一条）亮起，经过「在等你」、回答，直到「好了」或「出错停了」，几分钟后收起。

这样分的原因：

- 对话标题可以由手机自己写进岛的固定部分，不经过苹果；苹果只传状态。
- 几个对话同时跑时，系统按「相关性」自己排：最要紧的占灵动岛，第二个缩成小圆，锁屏上每个一张卡片（方案三）。
- 一个应用同时能开的实时活动有上限（第三方文档说大约 5 个，苹果没写死）。遥应最多同时开 3 个。

### 5.2 数据：手机和扩展共用

分两层：

- **`TeleplyIsland` 模块**：加进 `apps/ios/TeleplyCore/Package.swift`，不依赖任何别的模块（扩展有内存限制，别把 swift-markdown 带进去）。里面放纯数据和逻辑：岛的状态、每种状态显示什么字和什么颜色角色、相关性分数、状态怎么变、给中转的请求体。Windows 上能测。
- **`apps/ios/Shared/IslandAttributes.swift`**：应用和扩展都编译这个文件。

```swift
import ActivityKit
import TeleplyIsland

/// 一个岛的固定部分：开岛时定下，之后不变。
nonisolated struct IslandAttributes: ActivityAttributes {
    var device: String    // 电脑编号（32 位十六进制）
    var app: String       // codex | claude | deepseek
    var chat: String      // 对话编号
    var computer: String  // 电脑名；手机开岛时取手机自己的列表，远程开启时中转填 devices.label
    var title: String     // 对话标题；手机开岛时手机填，远程开启时是空的
    typealias ContentState = IslandState
}
```

```swift
/// 岛会变的部分：每次推送或手机自己改的就是它。
public nonisolated struct IslandState: Codable, Hashable, Sendable {
    public var state: String    // working | waiting | done | failed | offline | limited
    public var since: Int       // Unix 秒：这个状态从什么时候开始，计时从这里走
    public var turn: Int        // Unix 秒：这一轮从什么时候开始，算「用了 N 分」
    public var ask: String?     // 方案二：问题的编号（电脑给的随机编号，不含内容）
    public var askType: String? // 方案二：permission | question
    public var choices: Int?    // 方案二：选项个数
    public var askText: String?     // 方案二 B：只由手机自己写，中转从不填
    public var askOptions: [String]? // 方案二 B：同上
    public var step: String?    // 方案六：edit | run | search | read
    public var ended: Int?      // 0.6.4：这一轮结束的 Unix 秒；好了一轮的用时按 ended - turn 算
    public var resets: Int?     // 方案七：额度恢复的 Unix 秒
    public var peers: [IslandPeer]? // 长按列表：每个在跑的对话的 app / chat / 标题 / 状态 / 时间 / 动作
    public var working: Int?        // 0.6.3：一台电脑的岛，几个对话在干活
    public var waiting: Int?        // 0.6.3：几个在等你定
}

/// 长按列表的一行（10-28 用户定）。
public nonisolated struct IslandPeer: Codable, Hashable, Sendable {
    public var app: String
    public var chat: String
    public var title: String
    public var state: String
    public var since: Int
    public var turn: Int
    public var step: String?    // 0.6.4：这个对话正在做什么
    public var ended: Int?      // 0.6.4：已结束那一轮的结束时间
}
```

10-28 起，`peers` 里的标题会经过中转和苹果（用户明确选择）；这是隐私规矩的唯一例外，见第 1 节。中转从 `push_activities.title` 生成 `peers`，手机在第一次推送前也自己填一份。

几条死规矩：

- **时间一律用 Unix 秒的整数，不用 `Date`**。岛的推送内容由系统用默认的 JSON 解码器读，`Date` 会被当成「从 2001 年起的秒数」，和中转写的对不上。画面里再换成 `Date(timeIntervalSince1970:)`。推送里的 `aps.timestamp` 是 Unix 秒。
- **用时以记录为准（0.6.4）**：一轮的开始、结束从 Codex / Claude / DeepSeek 的记录里读（`notify.py` 的 `scan_lines`；状态接口的 `turn_started` / `turn_ended`），不用电脑注意到的时刻，也不用手机的钟。记录里没有时才写「电脑注意到」或「不知道」，中转和日志都要能看出是哪一种。手机的计时只从电脑给的这个开始时间走。
- **以后加的字段一律是可选类型**，老中转发来的推送才解得开。
- 键名就是 Swift 里的属性名，不做下划线转换。
- 中转和手机共用一份样例 `tests/fixtures/island-states.json`：中转的测试核对自己发的内容和它一致，Swift 测试解码同一个文件。两边对不上，测试就失败。
- 固定部分加变化部分合起来不能超过 4KB（苹果的限制），这里远远用不到。

### 5.3 谁开岛、谁改、谁收

| 事情 | 谁先知道 | 怎么到岛上 |
|---|---|---|
| 手机上发出一条，这个对话开始干活 | 手机 | 手机自己开岛，标题写进固定部分；拿到这个岛的推送令牌，登记到中转 |
| 电脑上开始的一轮，跑过 1 分钟 | 电脑报 `running` → 中转 | 中转「远程开启」（push-to-start），标题为空 |
| 在等你 / 好了 / 出错停了 | 电脑 → 中转 | 中转更新岛，带提醒 |
| 电脑断开、连回 | 中转 | 中转更新岛 |
| 好了以后 2 分钟 | 中转 | 中转结束这个岛 |
| 用户在岛上回答 | 手机 | 手机经中转直接问电脑（不经过苹果），答上了手机自己改岛 |

**中转发岛的规矩**：

- 请求头 `apns-push-type: liveactivity`，主题 `com.pocketagentdesk.teleply.push-type.liveactivity`。
- 优先级（0.6.4 起）：开始、在等你、好了、出错、断开这些**状态和计数的变化用 10**，不带提醒也马上送；只有进度用 5，同一个对话至少隔 15 秒。10 秒里已经响过一次时，那一次状态变化只是不带提醒，优先级仍是 10。苹果限制优先级 10 的次数，超了会被压下；优先级 5 的不算。
- 每个岛最多 5 秒一次更新；进度最多 15 秒一次；一个账号的岛推送一小时最多 120 条（和普通通知的 30 条分开算）。干活久没有变化时每 10 分钟刷新一次（`ISLAND_REFRESH`）。
- `aps.timestamp` 填当时的 Unix 秒。苹果丢掉比上一条旧的更新，所以顺序乱不了。
- 在干活的更新带 `stale-date`（现在加 15 分钟）。过了这个时间还没新消息，岛上写「可能不是最新」。
- 苹果说令牌失效（410，或 400 `BadDeviceToken`），就删掉这个岛的记录；这时如果是在等你、好了、出错停了，改发普通通知。
- **好了或出错 2 分钟后**（0.6.4，原 5 分钟）：发 `end` 结束岛，再补一条静默记录通知（见下），然后删掉登记。
- 远程开岛（push-to-start）必须带 `alert`，但不带 `sound`，所以不响（0.6.2，用户 10-28）。
- 推送示例（以苹果文档为准，见第 10 节）：

```json
{"aps": {"timestamp": 1761630000, "event": "update",
         "content-state": {"state": "waiting", "since": 1761630000, "turn": 1761629700},
         "stale-date": 1761630900,
         "relevance-score": 100,
         "alert": {"title": "Claude · 我的电脑", "body": "有个对话在等你处理", "sound": "default"}}}
```

```json
{"aps": {"timestamp": 1761630000, "event": "start",
         "attributes-type": "IslandAttributes",
         "attributes": {"device": "…", "app": "claude", "chat": "…", "computer": "我的电脑", "title": ""},
         "content-state": {"state": "working", "since": 1761629940, "turn": 1761629940},
         "alert": {"title": "Claude · 我的电脑", "body": "开始干活了"},
         "input-push-token": 1}}
```

```json
{"aps": {"timestamp": 1761630300, "event": "end",
         "content-state": {"state": "done", "since": 1761630000, "turn": 1761629700},
         "dismissal-date": 1761630300}}
```

  远程开启的 `attributes-type` 必须和 Swift 的类型名 `IslandAttributes` 一字不差。`input-push-token: 1`（iOS 18 起）让系统给远程开的岛发一个更新用的令牌，手机拿到后要报给中转；手机没被叫醒、报不上来时，中转改不了这个岛，只能等用户下次打开应用时补登记。这一点要真机验。

**普通通知的规矩（0.6.2，用户 10-28 定）**：

- 只在「在等你 / 好了 / 出错停了」且这个对话没有能用的岛（没开、已经 3 个、灵动岛关着、岛的令牌失效）时发；手机正开着那个对话时不发（有岛时只静默改岛）。
- 第一行是对话标题，没有标题时写「模型 · 电脑」；第二行是「模型 · 电脑」；正文「好了 · 用了 6 分钟」「在等你选」「出错停了」。用时从这一轮开始（电脑报的 `running`，或岛记下的 `turn`），不到一分钟或不知道时只写「好了」。
- 同一台电脑的所有通知共用一个 `thread-id`（通知中心里叠成一摞）；同一个对话共用一个 `apns-collapse-id`（用电脑、来源、对话编号一起哈希），所以一个对话永远只占一行，新通知替换旧的。
- 推送带 `category: teleply.conversation`；应用启动时用 `UNNotificationCategory` 注册这个类别，`categorySummaryFormat` 写「还有 %u 个对话」，叠起来那一摞的标题就是它。
- **一阵子只响一次**：同一个账号 10 秒内接连来的事，不管是不是同一个对话、走岛还是走通知，只有第一件响和弹。后面的：岛改成不带 `alert` 的静默更新（优先级 5）；普通通知改成 `interruption-level: passive`、不带 `sound`，只进通知中心。中转按账号记最后一次真响的时间。
- 同一对话同一种事 60 秒内仍只发一条；一个账号一小时最多 30 条通知。
- 岛在「好了 / 出错」2 分钟后收起时，中转补一条被动通知当记录（`interruption-level: passive`，无 `sound`，优先级 5）；用户自己划掉的岛不补，断开超过半小时收起的岛也不补。
- 应用在前台时（`UNUserNotificationCenterDelegate.willPresent`）：正看着那个对话什么都不显示；别的页面横幅照常出、不响；被动通知在前台也只进通知中心。
- 中转每做一次决定写一行日志：事件、来源、对话编号后 6 位、走了哪条路（岛提醒 / 岛静默 / 通知响 / 通知静默 / 不发）和原因；日志里不写标题。

**0.6.3：一台电脑一个岛（10-28 用户定的）**

- 手机在发送被电脑收下时开或更新的是**这台电脑**的岛：`attributes.app`、`chat`、`title` 都是空，只带 `device` 和 `computer`；状态里多了 `working`、`waiting`（两个数）和 `peers` 列表。
- 中转新表 `push_conversations(device, app, chat, owner, title, state, since, turn, refreshed)` 记下每个对话最后一次事件（running→working、waiting、done、failed），24 小时后清。计数只算 working/waiting；等你定的排最前，标题截到 40 字，列表最多 3 行。
- 收到事件：先更新对话行；有电脑岛就按汇总更新（`state` 按 waiting > working > done；提醒文字用这个对话的标题和状态，例如「好了 · 用了 6 分钟」）；done/failed **先补一条静默记录**，不等岛收起。没有电脑岛、只有 0.6.2 的一对话一岛时照旧；两种都没有就发普通通知。
- 所有对话都结束后带上刚结束的那个对话（标题、状态、开始、结束），`state=done`，2 分钟后收起岛；记录已经在每个对话结束时发过，收起时不再发。
- 岛登记时中转会补推一次当前状态（`fresh_islands`），修掉「done 先到、令牌后到」导致岛停在 working 的问题。
- 升级：0.6.3 的手机启动和回前台时结束 `chat` 非空的旧岛；中转收到电脑岛登记时删掉这个 device 下旧的 `app`/`chat` 行。
- 巡检从 30 秒改成 10 秒；电脑 `notify.py` 有任务在跑时 2 秒看一次、空闲 5 秒（Windows dev.29 起）。远程开岛仍等 1 分钟。
- 画面：紧凑 1 个对话时照旧，2 个以上「3个工作中」，有等你定的「2个等你定」（橙色优先）；小圆加橙点和小数字；展开第一行汇总、等你定的排最前，左上「遥应」和右上数字加了内边距；锁屏 2 个以上第一行汇总、下面最多 3 行；手表/待机（`.small`）黑底白字。

**0.6.4：时间以记录为准，岛及时变，看得到进度（10-29）**

- **时间**：电脑报的 `running.since`、`done/failed.started/ended` 都来自记录；中转 `remember()` 优先用它们，没有才退回现在的做法。岛的 `ended` 让「用了 N 分」在结束后不再变长；没有对话在动时，`aggregate()` 带上刚结束的那一个（`peers` 里一行，`working/waiting=0`），锁屏卡片显示它的标题和真实用时。
- **电脑读法**：每个对话文件记住上次读到的位置，变长只读新增部分；第一次往回读最多 64MB 找最近一次开始和结束。电脑启动或中转重新连上时，正在跑的轮次用真实开始时间再报一次；只对已经结束的轮次不补报。记录停在「running」但 20 分钟没有新内容，不当成在干活。
- **快照**：`{"kind":"snapshot","items":[…]}`，有对话在跑时每 60 秒（以及刚启动、刚连上中转）发一次；中转用它补上漏掉的对话，连续两次快照都没有、状态又不是等你的，记成 `gone`（不响、不补记录）。快照和进度用 `Feed.publish(keep=False)`，不留给断线补读。
- **远程开岛**：中转不再靠内存里的 `self.starts`，`sweep_islands()` 查 `push_conversations` 里「在干活/等你超过 60 秒、这台电脑还没有岛」的，中转重启也能开。
- **进度**：`{"kind":"step","step":"edit|run|search|read"}`，电脑在动作变了才报、同一对话至少 15 秒；中转也守 15 秒，优先级 5、不带提醒。`content-state.step` 和每个 `peers[].step` 是可选字段，老手机解得开。
- **状态接口**：`/api/<来源>/state`、`/api/chats`（`turn_started`、`turn_ended`、`step`）、`/api/chat`（顶层和每条消息的 `turn_started`/`turn_ended`、`step`）都带本轮时间；单位是 Unix 秒。网页和安卓界面这一步不改。
- **iPhone**：锁屏卡片半透明（`CardBackground` 68%），浅色、深色都透壁纸；长按和锁屏每个在干活的对话后面有动作图标 + 两个字 + 计时；会话页最下面「正在思考 · 3 分 12 秒」，跑完的折叠条「思考了 3 分 12 秒」，列表行「运行中 · 3 分 12 秒」。计时全用电脑给的本轮开始时间。

**0.6.5：岛的推送合并、不丢，英文版（10-30）**

- **合并队列**：中转每座岛只记一份「要显示的最新内容」，最多每 10 秒推一次；连续变化覆盖前一份，最后一次变化 20 秒内一定推到。`update_island` 返回 `sent` / `queued` / `same` / `gone`，`queued` 不再被当成「已推」。一小时上限 600 是安全阀，超了排队一分钟再试并写 `push:` 日志，不丢。
- **内容比较**：状态、两个计数、三行 peer（编号、状态、动作、时间）、刚结束对话、`more` 一起算；快照只对账，内容没变不推。最后一个对话结束发一次空快照，之后只在重新连上中转时发。
- **挑三个**：等你定的最前，然后按 `action_at`（这一轮开始或最近一次 step）排；`content-state.more = 总数 - 列出的行数`。
- **手机补岛**：`POST /account/push/island-state`（账号 + 电脑编号）返回和推送一样的内容；应用启动和回前台读一次，用 `activity.update` 自己改岛。
- **英文版**：`Localizable.xcstrings`（应用、扩展各一份），`CFBundleLocalizations` 加 `en`，`en.lproj/InfoPlist.strings`，`ci-testflight.sh` 检查 `en.lproj`。`push_phones.language`、`push_activities.language`、`push_start.language` 决定中转写的通知正文和岛提醒；`Hints.swift` 先按原文映射 20 条电脑提示，其余照旧中文。

**手机的规矩**：

- 最多同时开 3 个岛（0.6.3 起是 3 台电脑各一个）。要开第 4 个时，先结束最早「好了」的那个；都还在干活就不开（通知照来）。
- 应用启动和回到前台时，核对 `Activity<IslandAttributes>.activities`：手机知道已经结束超过 10 分钟的岛，自己结束掉；令牌会变，一直听 `pushTokenUpdates`，变了就重新登记。
- 用户在锁屏上把岛划掉，岛就结束了（`activityStateUpdates` 报 `.dismissed`），手机去中转注销它的令牌。
- 设置里关掉灵动岛：结束所有岛，注销所有令牌。
- 点岛：`teleply://open?d=<电脑编号>&a=<来源>&c=<对话编号>` → 用 `PushTarget(device:app:chat:)` 校验 → `AppModel.openNotification`。别的网址一律不理（注册了网址协议，任何网页都能拉起它）。

### 5.4 画面怎么设计

苹果给岛定了几种样子：

- **紧凑**：岛左右两小块。最常见。
- **最小**：同时有两个岛时，第二个缩成一个小圆。
- **展开**：长按岛，或带提醒的更新到来时自动弹开一下。
- **锁屏**：锁屏上的一张卡片。待机显示里放大显示；Apple Watch 的智能叠放和 CarPlay 用 `.small` 那一版。

每种状态画成这样：

| 状态 | 紧凑·左 | 紧凑·右 | 最小 | 长按展开 |
|---|---|---|---|---|
| 在干活 | 遥应标志（白） | 计时 `4:31`，白字 | 遥应标志 | 遥应标志 +「N 个」；每个在跑的对话一行：模型标志、标题、计时 |
| 在等你 | 遥应标志 + 橙点 | 「等你」橙字 | 遥应标志带橙点 | 那一行「等你」橙字；点行进对话卡片 |
| 好了 | 遥应标志 | ✓ 绿 | ✓ | 自己那行已收起，只列还在跑的 |
| 出错停了 | 遥应标志 | ! 红 | ! | 同上 |
| 断开了 | 遥应标志变灰 | 「断开」灰字 | 灰标志 | 那一行灰字、计时在走 |
| 额度用完（方案七） | 遥应标志 | 倒计时，橙字 | 遥应标志 | 那一行倒计时 |
| 过了 `stale-date` | 照原样 | 换成灰字 | 照原样 | 下面加一行灰字「可能不是最新」 |

10-28 用户定的两条：**紧凑和小图标只显示遥应的标志**（型号太多，小地方放不下，也认不出是遥应）；**长按展开列出所有正在干活或等你回答的对话**，每行模型标志、标题、时间，点一行打开那个对话。标题放在 `content-state.peers` 里，由中转带（用户明确同意标题经过苹果；消息和命令仍不经过）。

- **颜色**：灵动岛永远是黑底；遥应标志用白，列表里的模型标志用来源色（深色值）：`ClaudeTint`、`CodexTint`、`DeepSeekTint`；在等你用 `AskGo`；好了 `Success`；出错 `Danger`；断开 `Muted`。锁屏卡片跟着系统的深浅色走，用 `Ink`、`Muted` 写字。
- **字**：紧凑的右边最多 4 个汉字；计时用等宽数字（`.monospacedDigit()`），给右边一个固定的最大宽度，计时变长时不挤左边。列表一行约 20 点高，标题一行截断。
- **计时**：`Text(timerInterval: 开始…Date.distantFuture, countsDown: false)` 自己走，不用推送。倒计时用 `countsDown: true`。
- **点按**：整个岛 `.widgetURL(…)`；展开里每个对话一行是 `Link`（`teleply://open?d=…&a=…&c=…`），以后回答按钮用 `Button(intent:)`。
- **标志和颜色要复制进扩展**：扩展读不到应用的 `Assets.xcassets`。在 `apps/ios/TeleplyIslandWidget/Assets.xcassets` 里放 `TeleplyMark`、`ClaudeMark`、`CodexMark`、`DeepSeekMark` 和上面用到的颜色的副本。`ci-check.sh` 会比较这些副本和应用里的是否一样。
- **扩展里不联网**（系统也不让），**不用 UserDefaults**（用了就要给扩展也放一份隐私清单 `PrivacyInfo.xcprivacy`）。
- **读屏**：每种状态给一句 VoiceOver 的话，例如「Claude 在干活，已经 4 分 31 秒」。
- **待机显示**：夜里整屏会变红，不能只靠颜色区分状态，状态字一直要在。
- **iOS 27**：横屏时也显示紧凑的岛，而且不能变宽。宽度受限时（苹果给的判断值，WWDC26 时叫 `isDynamicIslandLimitedInWidth`，名字以正式 SDK 为准）只显示标志和最短的字。用 `if #available(iOS 27, *)` 包起来。
- **给用户看样子**：调试版的 设置 → 开发者选项 里加一页「灵动岛样子」，把锁屏卡片和岛的几种样子（照着苹果的尺寸画的近似图）按状态、深浅色排在普通页面上。截图测试拍这一页，用户在真机之前就能先看设计。真正的灵动岛截图测试拍不到。

### 5.5 工程里加什么

`project.yml` 加一个目标，应用目标依赖它（XcodeGen 默认把扩展嵌进应用）：

```yaml
  TeleplyIslandWidget:
    type: app-extension
    platform: iOS
    sources:
      - path: TeleplyIslandWidget
      - path: Shared
    dependencies:
      - package: TeleplyCore
        product: TeleplyIsland
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.pocketagentdesk.teleply.island
        PRODUCT_NAME: TeleplyIslandWidget
        TARGETED_DEVICE_FAMILY: "1"
        INFOPLIST_FILE: TeleplyIslandWidget/Info.plist
        GENERATE_INFOPLIST_FILE: NO
        SWIFT_DEFAULT_ACTOR_ISOLATION: MainActor
        SWIFT_APPROACHABLE_CONCURRENCY: YES
        SKIP_INSTALL: YES
        CODE_SIGN_STYLE: Automatic
```

- `Teleply` 目标的 `sources` 加 `- path: Shared`，`dependencies` 加 `- target: TeleplyIslandWidget` 和 `TeleplyIsland` 这个包产品。
- 扩展的 `Info.plist`：`CFBundleShortVersionString` 写 `$(MARKETING_VERSION)`、`CFBundleVersion` 写 `$(CURRENT_PROJECT_VERSION)`（和应用一样，`ci-testflight.sh` 改构建号时两边一起变；**不要在目标里另写版本**）；`CFBundleDisplayName` 写「遥应」；`NSExtension` → `NSExtensionPointIdentifier` 写 `com.apple.widgetkit-extension`。
- 应用的 `Teleply/Resources/Info.plist` 加 `NSSupportsLiveActivities`（true）；方案二 B 再加 `UIBackgroundModes` 里的 `remote-notification`；方案六再加 `NSSupportsLiveActivitiesFrequentUpdates`（true）。注册网址协议 `teleply`（`CFBundleURLTypes`）。
- 扩展的入口：`@main struct IslandWidgets: WidgetBundle`，里面一个 `ActivityConfiguration(for: IslandAttributes.self)`，带锁屏视图、`dynamicIsland`（`compactLeading`、`compactTrailing`、`minimal`、`expanded`）、`.widgetURL`、`.supplementalActivityFamilies([.small])`。

## 6. 七个方案

### 方案一：岛上显示「轮到谁」（阶段一）

**目标**：一轮从开始到结束，岛上一直看得出它在干活、在等你、还是好了。

**用户看到的**：

- 在手机上给 Claude 发「把登录页修好」，锁屏。岛左边是 Claude 的标志，右边 `0:12` 开始走。
- Claude 停下来问问题：岛弹开一下、响一声，右边变成橙色「等你」，展开写「在等你选」。点岛进这个对话的最新处。
- 做完：岛弹开一下，✓，「好了 · 用了 6 分 12 秒」，5 分钟后收起。
- 在电脑上开始的一轮：跑过 1 分钟后岛出现（亮一次屏），写「Claude · 我的电脑」。

**手机**：

1. 按 5.5 加扩展目标、`Shared` 文件、`TeleplyIsland` 模块；`Info.plist` 加 `NSSupportsLiveActivities` 和网址协议。
2. `Teleply/Platform/Island.swift`：
   - 开岛：`Activity.request(attributes:content:pushType: .token)`。在哪开：手机发送成功（回执「已接收」）时，这个对话还没有岛就开。
   - 听这个岛的令牌（`pushTokenUpdates`），拿到或变了就登记到中转。
   - 听远程开启用的令牌（`Activity<IslandAttributes>.pushToStartTokenUpdates`），登记到中转。
   - 听远程开的新岛（`Activity<IslandAttributes>.activityUpdates`），登记它的令牌。
   - 收尾：见 5.3 手机的规矩。
3. `onOpenURL`：只认 `teleply://open?d=…&a=…&c=…`（5.3）。
4. 「灵动岛」开关：0.6.0 以前放在 设置 → 开发者选项，默认关；升 0.6.0 时挪到 设置 → 手机通知，和「遥应通知」的绿色开关放在一起（第 2 节「版本号怎么走」）。系统设置里关了实时活动时（`ActivityAuthorizationInfo().areActivitiesEnabled` 为假），点开关跳到系统设置里遥应这一页，照「遥应通知」开关的做法。
5. 开发者选项加「试一下灵动岛」（阶段零就有）和「灵动岛样子」（5.4）。
6. `TeleplyModel/Push.swift` 加两个请求：`/account/push/activity`、`/account/push/start-token`。
7. `TeleplyCore` 测试：每种状态的字和颜色角色、相关性、样例 JSON 解码、请求体、最多 3 个岛的取舍。

**中转**（`relay_push.py`、`relay_accounts.py`）：

1. `Apns.send` 加参数 `push_type='alert'`、`priority=10`、`topic=None`；岛用 `TOPIC + '.push-type.liveactivity'`。普通通知不变。
2. 新表：
   - `push_activities(id, owner, device, app, chat, token, environment, state, since, turn, created, refreshed, result)`：每个岛一行；`state`、`since` 记下最后的状态，方案四要用。
   - `push_start(token PRIMARY KEY, owner, environment, refreshed)`：远程开启令牌，每部手机一个。
   - 账号的手机被删（退出登录、改密码）时，这两张表里它的行一并删。
3. `Push.account` 加两个动作：
   - `activity`：`{"op": "register" 或 "unregister", "token", "device", "app", "chat", "environment"}`。核对这台电脑属于这个账号。
   - `start-token`：`{"token", "environment"}`。
4. `deliver`：
   - 收到 `running`：有这个对话的岛，就更新成 working（优先级 5）。没有岛、手机登记了远程开启令牌，就记下开始时间。
   - 收到 `waiting` / `done` / `failed`：有岛就更新（优先级 10，带提醒），按第 4 节问题 1 的决定发不发通知；没有岛照旧发通知。
5. `sweep`（每 30 秒）：记下开始时间、跑过 60 秒还没完的，远程开启；好了或出错超过 5 分钟的岛，发 `end`。
6. 测试（`tests/test_relay_push.py`，用假的发送端）：请求头、主题、优先级；内容和 `tests/fixtures/island-states.json` 一致；只有允许的键（隐私：没有标题和内容）；60 秒才远程开启；限流；令牌失效时删掉并改发通知；好了 5 分钟后结束。

**电脑**（`notify.py`）：

1. 一轮开始时报 `running`：`look()` 里 `turn_end` 返回 running、而上次看到的不是 running 时，`self.relay.publish("", "", extra={"kind": "running", "app": …, "chat": …, "since": 这一轮开始的 Unix 秒})`。DeepSeek 看 `item["_running"]`。
2. 每个对话只在状态变化时报一次。电脑刚启动时，已经在跑的不补报（照 `since` 的做法）。
3. 测试：在 `tests/test_notify.py` 里补。

**边界**：

- 手机正开着这个对话：应用在前台时，系统本来就不在灵动岛上显示它自己的岛，不用管。
- 一个账号两部手机：每部手机各有自己的岛和令牌，中转都更新。
- 一轮跑过 8 小时：苹果自己结束这个岛，不用管。
- 手机离线：苹果只留最后一条更新；岛的更新 `apns-expiration` 设短一点（10 分钟），过时的不要再送到。

**真机验收**：

1. 在手机上给一个对话发一句会跑一阵的话，锁屏：岛出现，计时在走。
2. 电脑上让它问一个问题：岛弹开、响、右边变橙；点岛进对话的最新处。
3. 做完：岛弹开、✓、用时对；5 分钟后消失。
4. 在电脑上开始一个长任务：1 分钟后手机上的岛出现，亮一次屏。
5. 设置里关掉灵动岛：岛马上没了，之后只收通知。

### 方案二：在岛上直接回答（阶段二）

**目标**：问题来了，不开应用也能答；可能出事的批准，一定先让人看到内容。

**用户看到的**（按第 4 节问题 5）：

- 选 A（推荐先做）：
  - 权限确认（Claude 要运行命令、改文件；DeepSeek 的批准）：展开写「Claude 想运行一条命令」，两个按钮「拒绝」「去看看 ›」。拒绝不看内容也安全，所以直接做；允许必须先看到内容，所以进对话里那张卡片。
  - 问题（Claude 的选择题、Codex 的问题）：「Claude 有 3 个选项等你选」，按钮「去选 ›」。
- 选 B：手机叫得醒时，展开里显示命令（一行，太长截断）和最多 3 个选项，按钮「允许」「拒绝」或各个选项；叫不醒时同 A。
- 选 C 或 D：总像 B 那样。
- 「允许并且以后这类不再问」永远不放在岛上，只在对话里的卡片上。

**电脑**：`waiting` 事件加三个字段：`ask`（问题的编号：Claude 用 `Ask.id`；Codex 用待答问题的 `id`，形如 `async:<call_id>`，见 `codex_control.py:420`；DeepSeek 用 `eventId` / `callId`，见 `notify.py:391`。都只是编号，不含内容）、`askType`（permission / question）、`choices`（选项个数）。`Notifier.asking` 要多收这几样。

**中转**：把这三个字段放进岛的 `content-state`。选 B 时再发一条后台推送：`apns-push-type: background`、`apns-priority: 5`、`aps.content-available: 1`，主题是 `com.pocketagentdesk.teleply`，带 `teleply: {d, a, c}`。苹果对后台推送限流（一小时两三条为宜），应用被划掉后收不到。

**手机**：

1. 按钮的动作是一个 `LiveActivityIntent`（`Teleply/Platform/IslandAnswer.swift`），带 `device`、`app`、`chat`、`ask`、`choice`（deny / allow / option:<序号>）。它在应用的进程里跑，系统会在后台启动应用来跑它。
2. 它做的事：
   1. 从钥匙串读登录（锁屏时也读得到，见第 2 节）。
   2. 向电脑读一次这个对话当前的状态（和会话页读的是同一个请求），找到正在等的问题。
   3. 编号对不上（已经在电脑上答了、换了问题）：把岛改成「电脑上已经处理了」，结束。
   4. 对得上：照对话里那张卡片的路由和请求体作答（`codex/answer`、`claude/choose` 带刚读到的 `token` 和 `stamp`、`deepseek/approval`）。把 `WorkspaceModel.action` 里拼请求的部分抽到 `TeleplyState`，卡片和岛共用一份，不要写两遍。
   5. 答上了：手机自己把岛改回在干活。没答上：岛上写一句原因和「去看看 ›」。
   6. 不自己重发（和卡片一样）。
3. 「允许」的动作设 `authenticationPolicy = .requiresLocalDeviceAuthentication`（锁屏时要先刷脸）。真机先试岛上的按钮认不认这一项；不认的话，把「允许」改成打开那张卡片的链接（打开应用本来就要解锁）。「拒绝」用 `.alwaysAllowed`。
4. 选 B：在 `AppDelegate` 里接后台推送（用传统回调写法，见 3.2），经中转读问题内容，用 `activity.update(…)` 把 `askText`、`askOptions` 写进岛。这是手机自己改的，不经过苹果；下一条中转的推送会盖掉这两个字段，那时状态已经变了，正好。

**真机验收**：

1. 锁屏时电脑上 Claude 要运行命令：岛弹开，有「拒绝」「去看看 ›」。点「拒绝」：电脑上的卡片关掉，Claude 停下等下一句话，岛回到在干活。
2. 再来一次，点「去看看 ›」：解锁后直接是那张卡片，在卡片上点「允许」。
3. 在电脑上先答，再点岛上的按钮：岛写「电脑上已经处理了」，电脑上什么都没多出来。
4. 选了 B：同样的命令，岛上显示命令原文，「允许」要刷脸。

### 方案三：几个对话同时跑（阶段三）

**目标**：三个对话一起跑时，最要紧的那个在岛上，其余的也找得到。

**A（推荐）**：每个对话一个岛，交给系统排。给每种状态一个相关性分数（开岛时、手机自己改时写进 `ActivityContent(… relevanceScore:)`，中转的推送写 `relevance-score`）：在等你 100，出错 80，断开 60，在干活 50（这一轮开始得越晚分越高），好了 10。系统把分最高的放在紧凑的岛上，第二个缩成小圆，锁屏上每个一张卡片。最多 3 个（5.3）。

- 最小的样子要一眼分得清：来源标志加一个状态点（橙＝等你，绿＝好了，红＝出错，灰＝断开）。

**B（以后再说）**：一台电脑一个岛，展开里每个对话一行。好处是都在一处；问题是对话标题要么经过苹果，要么扩展去共享文件夹里读手机存的标题（要两个 App ID 都开 App Groups、重做描述文件，而且要先试岛的画面能不能读共享文件夹）。用户没要求就不做。

**真机验收**：同时让两个对话跑、一个停下来问问题：灵动岛上是问问题的那个，另一个是小圆；锁屏上两张卡片。

### 方案四：电脑断了，岛会说（阶段一）

**目标**：电脑睡着或断网时，用户不再干等一个不会来的「好了」。

**中转**：

- `look()` 每 30 秒一次。一台电脑有岛、却不在 `hub.connections` 里超过 60 秒：把它的岛都改成 `offline`，`since` 是第一次发现它不在的时间。优先级 10，按第 4 节问题 3 决定带不带声音。原来的状态和时间记在 `push_activities` 里。
- 连回来：改回原来的状态，`since` 用原来的。
- 断开超过 30 分钟：结束这个岛，锁屏上留 1 小时。
- 中转刚重启时所有电脑都还没连上，不能当成断开：只看中转启动以后连上过的电脑，再等 60 秒。
- 测试：假的 hub 去掉一台电脑，60 秒后发 offline；放回来，发回原状态；30 分钟后结束。

**电脑**：不用改。

**真机验收**：电脑正跑着一轮时拔网线（或让电脑睡眠），一两分钟内岛变灰「断开了」，计时在走；插回网线，岛变回在干活。记下从拔线到岛变灰用了多久，写进 README（这取决于中转多快发现隧道断了）。

### 方案五：手机放下也能看（阶段一顺带）

**目标**：手机横放充电、或者戴着手表时，不拿起手机也看得到。

- **待机显示**：锁屏卡片会被放大显示。卡片里字要大、少、粗：标志、状态字、计时三样。夜里整屏变红，靠字区分状态（5.4）。
- **Apple Watch**（watchOS 11 起自动出现在智能叠放里，用户可以在手表上关）：`.supplementalActivityFamilies([.small])`，画面里看 `@Environment(\.activityFamily)`，`.small` 时只放标志、状态字、计时。
- **CarPlay**（iOS 26 起也显示）：同样用 `.small`。`.small` 里**不放回答按钮**，开车时不该批准命令。
- Mac 的菜单栏也会显示 iPhone 的实时活动，但用户的电脑是 Windows，不用管。

**真机验收**：iPhone 锁屏后横放在充电器上：岛的卡片放大，字清楚。有 Apple Watch 的话：抬腕转表冠，智能叠放里有它。

### 方案六：看得懂的进度（阶段三；0.6.4 已做）

**状态（10-29）**：已做。电脑从新增记录里认动作，动作变了才报（同一对话至少 15 秒）；中转优先级 5、不带提醒、也守 15 秒；岛的展开列表和锁屏卡片显示图标 + 两个字，紧凑只留计时；会话页和列表另有「正在思考 / 思考了 / 运行中」计时（见 0.6.4 一节）。还没上真机。

**目标**：在干活时，岛上换一个小图标说它在做什么，不滚日志。

**电脑**（`notify.py`）：这一轮在跑时，从新增记录（不再是只读末尾）找最后一次工具调用，换成四种之一：

- Claude（记录里 `tool_use` 的名字）：`Bash` → run；`Edit`、`Write`、`MultiEdit`、`NotebookEdit` → edit；`Read`、`Grep`、`Glob` → read；`WebSearch`、`WebFetch` → search；别的不报。
- Codex（`response_item` 里的函数调用名）：执行命令的（如 `shell`、`exec_command`）→ run；`apply_patch` → edit；网页搜索 → search。**先只读地看几份真实的 Codex 记录，核对名字再写**。
- DeepSeek：看 `deepseek_control` 的事件有没有工具类型；没有就不报。

只在类型变了时报 `step`，同一个对话至少隔 15 秒。**进度事件不留着给断线后补读**（或者单独计数），否则一阵进度会把事件流里的「好了」挤出 100 条的上限。

**中转**：优先级 5，不带提醒，每个岛最多 15 秒一次；岛不在 working 时丢掉。

**手机**：展开和锁屏卡片里，计时旁边放图标（SF Symbols：`pencil` 改文件、`terminal` 跑命令、`magnifyingglass` 查资料、`doc.text` 读文件）；紧凑的右边太窄，仍只放计时。`Info.plist` 加 `NSSupportsLiveActivitiesFrequentUpdates`，系统觉得更新多时会问用户要不要多给一些次数。

**隐私**：苹果会看到「在跑命令」这类类型，先问用户（问题 7）。

**真机验收**：让 Claude 做一个要改文件、跑测试的任务，长按岛：图标在「改文件」「跑命令」之间换，间隔不短于十几秒。

### 方案七：额度倒计时（阶段四）

**目标**：Claude（或 Codex）额度用完时，岛倒数到恢复，到点提醒接着干。

**电脑**：

- `claude_control.py`：解析 Usage 按钮的字，例如 `Usage: Weekly · all models: 48%, Resets Sat 3:00 PM` → 用了 48%，恢复时间是下一个周六 15:00（电脑所在时区）换成 Unix 秒。额度用完的提示条（现在在 `claude_control.py:361` 被跳过）读出它写的恢复时间。**先用 UI Automation 读出提示条的原文再写解析**，不要猜它的写法。
- Codex：只读地看真实记录里有没有额度信息（例如 `token_count` 事件里的 `rate_limits`）；有就照做，没有就不做（问题 9）。
- 变了才报 `usage`：`{"kind": "usage", "app": "claude", "percent": 48, "resets": …, "limited": true}`。

**中转**：`limited` 为真时，给这台电脑的这个来源开（或更新）一个额度岛：`chat` 填 `usage`，状态 `limited`，带 `resets`。`sweep` 看到时间到了，更新一次带提醒：「Claude 额度恢复了，可以接着干」，10 分钟后结束。

**手机**：额度岛画倒计时（5.4 的表）。点它打开这台电脑的对话列表：网址用 `teleply://list?d=<电脑编号>`，`onOpenURL` 里同样校验。

**真机验收**：额度用完时（不必故意去用完，等遇到时验）岛上倒计时；到点弹开说恢复了。

## 7. 阶段和先后

| 阶段 | 做什么 | 先要 | 发什么 |
|---|---|---|---|
| 零：打通 | 3.3 苹果后台两步和 Codemagic 引用名；扩展骨架、「试一下灵动岛」（只在手机上开，不经过中转）；中转能发岛的推送，加 `POST /account/push/island-test`，开发者选项里「让中转改一下」，它成功就证实密钥认灵动岛（3.5） | 用户点苹果后台 | 中转更新；TestFlight 试验构建（版本号不动） |
| 一 | 方案一、四、五 | 问题 1–4 | 中转、电脑 dev.27、TestFlight；真机验收通过后升 0.6.0 |
| 二 | 方案二 | 问题 5–6 | 中转、电脑、TestFlight 0.6.1 |
| 三 | 方案三、六 | 问题 7–8 | 中转、电脑、TestFlight 0.6.2 |
| 四 | 方案七 | 问题 9 | 中转、电脑、TestFlight 0.6.3 |

**阶段零 10-28 真机通过**：锁屏卡片和计时正常，「让中转改一下」把卡片改成 ✓「好了 · 用了 1 秒」（主题被证实）；解锁回桌面看到了灵动岛。用户说紧凑的样子不美观（黑条偏宽、中间空），阶段一按 5.4 重新设计。阶段零到此做成；但按第 2 节，0.6.0 要等阶段一也验收通过。

**阶段一（10-28，收尾到 0.6.1）**：代码在 `main`（0ddebaa、1cfc5e9、18ed29a、3f768ca、9ea65ae、32a0324、25cd78a、5797efd、eb726c3、052df56、214ae79），Windows dev.28 已装，中转已更新。0.5.6（13）真机验过功能（开岛、计时），用户随后定了遥应标志/长按列表，又指出锁屏卡片偏矮、手表没标题；这些都改完，**0.6.1（16）已上传**（#48，Delivery UUID `8644d17c-4f06-422a-84bf-eaedfd8f0c9f`），等真机验：卡片高度和字号、手表标题、长按列表单表头/计数完整、开关在手机通知。验过阶段一收尾；阶段二从 0.6.2 起。

**阶段零的真机验收**：

1. 设置 → 开发者选项 → 试一下灵动岛：岛出现，计时在走。锁屏上也有，点它打开遥应。
2. 同一页点「让中转改一下」：几秒内岛变成 ✓ 好了。这一下证明了主题、令牌、推送内容整条路是通的。

## 8. 每个阶段都要过的检查

- 这台电脑上：`TeleplyCore` 的 `swift test` 全过；Python 测试全过。
- Codemagic：只编译通过；`ci-testflight.sh` 的扩展检查通过。
- 隐私：中转测试里断言岛的推送只有允许的键，没有标题、问题和命令（选了 C 或 D 的除外）。
- 截图：「灵动岛样子」那一页给用户看过。
- 真机：用户按 README 的「留给你在真机上验」验过。

## 9. 回退

- **手机**：设置里关掉灵动岛（结束所有岛、注销令牌）；或在 TestFlight 里装回上一版。
- **中转**：代码里加一个开关，环境变量 `AR_ISLAND=0` 时不发任何岛的推送，普通通知照旧。要整个退回：把 `/opt/agent-relay-027/previous-<时间>/` 里的文件放回去，重启服务。
- **电脑**：装回上一个安装包（GitHub 的 `windows-v…` 预发布里都有）。电脑退回老版本后只是不报新事件，岛还能收到 done/failed/waiting。

## 10. 参考

苹果文档（字段名以这些为准，本文的推送示例按它们核对后再用）：

- ActivityKit 总览：https://developer.apple.com/documentation/activitykit
- 显示实时数据：https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities
- 用推送开启和更新：https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications
- 设计规范（HIG）：https://developer.apple.com/design/human-interface-guidelines/live-activities
- WWDC23「Update Live Activities with push notifications」：https://developer.apple.com/videos/play/wwdc2023/10185/
- WWDC26「Live Activities essentials」（iOS 27 横屏）：https://developer.apple.com/videos/play/wwdc2026/223/
- `LiveActivityIntent`：https://developer.apple.com/documentation/appintents/liveactivityintent
- 锁屏时要求解锁：https://developer.apple.com/documentation/appintents/intentauthenticationpolicy/requireslocaldeviceauthentication
- 用密钥连苹果推送（Topic Specific 密钥）：https://developer.apple.com/documentation/usernotifications/establishing-a-token-based-connection-to-apns
- 优先级 10 的次数限制（苹果论坛）：https://developer.apple.com/forums/thread/731715

仓库和资料：

- `apps/ios/README.md`：iOS 版每一版的记录、构建表、真机检查的写法。
- `docs/design-language.md`：网页设计语言（原生跟它）。
- `deploy/relay/README-027.md`：中转的部署和推送密钥。
- `deploy/updates/README.md`：Windows 和安卓的发布。
- `docs/handoff-domain.md`：换域名的交接（中转只认一个地址的原因）。
- iOS 计划：`C:\Users\39011\.claude\plans\codex-ios-app-apple-developer-program-q-piped-hanrahan.md`。
- Obsidian：`D:\Personal\Zeng Huanyu\Codex 知识库\遥应·Teleply\产品设计\` 里的《Teleply - iOS 原生推送方案》和《Teleply - iOS SwiftUI 设计规范》v0.8。改规范要先问用户、先备份；安卓和 iOS 两份规范的第 8 节、9.1 节要保持一致。

## 11. 以后再说

- 方案三的 B（一台电脑一个岛）、问题 5 的 D（加密）。
- 苹果的广播推送（iOS 18 起，用频道一对多发）。远程开的岛报不上令牌时，可以用它代替，但要在 App ID 上另开能力。
- 安卓：安卓 16 有类似的「实时更新」通知，国内几家手机也有自己的胶囊或岛，接口各不相同，多数要上架。安卓的推送路线还没定，等 iPhone 版定型再看。
