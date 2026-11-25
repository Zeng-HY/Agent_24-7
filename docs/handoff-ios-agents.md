# iOS：照电脑给的「说明书」显示助手（让 iPhone / iPad 看到并使用 Antigravity）

交接设计，2026-11-25，主会话（Claude）写，DeepSeek 实现。分支 `ios-agents`，从 `ipad-adapt`（2aafa0e，TestFlight 0.8.0 (33) 的代码）切出。

## 0. 结论

- 现在的 iOS 应用（0.7.6 / 0.8.0）只认识 Codex、Claude、DeepSeek 三家，名字写死在代码里；请求不带协议号，电脑就当它是「协议 1」的老手机，不把 Antigravity 发给它。
- 这次让 iOS 像安卓 1.0.10 和网页那样：每个请求都带「协议 2」，从电脑取「助手说明书」（`/api/agents`），照说明书显示新助手、照能力位显示按钮，新助手的动作走统一地址 `/api/agents/<id>/…`。
- **三家一点不变**：三家现有的路由、控制态、卡片、按钮的代码路径不动。只在「按名字分支」的地方，给「说明书里 `legacy=false` 的助手」加一条通用的路。
- 做完以后，电脑端以后再加新助手，iOS 不用再发版。

## 1. 背景和证据（主会话 11-25 核对过）

1. **电脑端 dev.53（已发布）按协议过滤。** 用本机服务核对，只看助手名和条数：
   - 协议 2：`/api/chat/projects` 的 `apps` = codex、claude、deepseek、antigravity；`/api/agents` 返回 4 份说明书；`/api/chats?app=antigravity` 有对话。
   - 协议 1（今天的 iOS）：`/api/agents` 返回 404；树里没有 antigravity；`/api/chats?app=antigravity` 0 条。
2. **Antigravity 的说明书**（`/api/agents` 里的一项，原样）：
   - `id` antigravity，`legacy` false，`min_protocol` 2，`order` 40，`schema` 1
   - `name` `{"zh": "Antigravity", "en": "Antigravity"}`，`color` `#4285F4`，`color_dark` `#8AB4F8`，`icon` `{"kind": "builtin", "key": "generic"}`
   - `capabilities`：`{"list": true, "read": true, "search": true, "open": false, "stop": true, "queue": false, "steer": false, "approve": true, "answer": false, "new": true, "new_projectless": false, "new_permission": false, "archive": false, "restore": false, "delete": false, "usage": false, "waiting": true, "attachments": true, "slash_commands": false, "settings": [], "send_modes": ["send"], "statuses": ["running", "waiting", "idle", "unknown"], "skills": false}`
   - `params`：`{"state_timeout_s": 40, "send_timeout_s": 60, "open_timeout_s": 45, "new_timeout_s": 140, "refresh_ms": 2500, "max_images": 5, "max_image_bytes": 20971520, "max_text": 20000}`
   - `ui`：`{"card_layout": "generic.v1", "waiting_text": "等待你处理"}`
   - 三家的说明书字段相同，`legacy` true，`ui.card_layout` 是各自的（如 `codex.v1`），`icon.key` 是各自的名字。
3. **安卓 1.0.10 已经这样做了，照它的行为做。** 发布用的分支是 `android-push-caps`（cfef820），其中 `agent-android` 的 6 个提交是参考实现：
   - bd53102 协议 2 请求头/参数、`AgentInfo`、按电脑缓存的 `AgentCatalog`（404 时三家兜底）
   - f263b8c 列表、显示、能力显隐、归档、用量、通知白名单按说明书
   - 4302e3d 演示数据加假助手 `testing`，未知助手、老电脑回退的测试
   - 7367ebe 控制态和动作走统一地址，404 时回退老路由
   - 118af92 老电脑直接走老路由，电脑版本变了清除记忆重试
   - 看代码：`git show cfef820:apps/android/app/src/main/java/com/pocketagentdesk/teleply/<文件>`。重点：`RelayApi.kt:38/112-114`（`TeleplyProtocol = 2`，请求头和查询参数），`AgentInfo.kt`（通用灰 `#6B7280`、通用图标 `generic`、`generic.v1`），`AgentCatalog.kt`（`fromServer`：三家的名字、颜色、图标永远用 App 自己的），`ReaderViewModel.kt:123`（`treeApps`），`FixtureApi.kt`（假助手 `testing`、通用卡片）。
4. **中转（线上是 0b3f8d7）已经放行。** 它转发 `X-Teleply-Protocol`、`X-Teleply-Client` 两个头。推送登记按 `protocol` 存（`_parse_protocol` 认字符串和数字）。新助手的推送只发给登记了协议 ≥2 的手机。新助手的推送在 `teleply` 里多带可选的 `n`（名字）、`k`（颜色）、`m`（图标 key），见 `git show 0b3f8d7:relay_push.py` 第 253 行附近；灵动岛的推送内容也在这个文件里，自己查清新助手带了哪些字段。
5. **文档：** `git show agent-registry:docs/adding-an-agent.md`，看 §三（说明书字段）、§五（通用卡片：批准和回答）、§七（协议 1 和 2）、§八（网页和手机怎么显示）、§九（中转）。§八 里有一条要守：**运行中会变的能力看控制态里的 `capabilities_now`**，说明书里的 `capabilities` 只当默认值。
   - 原方案：`F:\Android-Dev\work\20261101-island-duplicates\20261123-agents\plan.md` 的 §1.7、§3、§6.2–6.5、§8.7、§8.10（iOS 那几行）。方案里「三家也改走统一地址」这一条，这次**不照做**，见 0 节第三条。
   - 网页的通用面板 `git show agent-registry:static/agents.js`（`window.genericAgentUI`）是通用卡片、发送、停止、回执的另一份参考。
6. **iOS 现状（ipad-adapt 2aafa0e）：**
   - 名单：`apps/ios/TeleplyCore/Sources/TeleplyModel/Models.swift:140` `public let sourceOrder = ["codex", "claude", "deepseek"]`。用到它的地方：
     - App：`apps/ios/Teleply/List/ChatListView.swift:166`
     - `apps/ios/TeleplyCore/Sources/` 下：`TeleplyDemo/DemoWorld.swift:109`、`TeleplyModel/Push.swift:14`、`TeleplyModel/Relay.swift:224/229/454`、`TeleplyState/AppModel+Archive.swift:18`、`TeleplyState/AppModel+List.swift:147/198`、`TeleplyState/AppModel+New.swift:35`、`TeleplyState/AppModel+Reading.swift:48`
   - `Relay.swift:224/229`：列表里有一行不认识的助手，整页报错。这就是电脑必须对老 iOS 藏起新助手的原因。
   - `Push.swift:24` 只读推送 `teleply` 里的 `d`、`a`、`c`。
   - 外观的写死表：`Labels.sourceName`、`Palette.tint/badge`、`Marks.SourceMark`、`IslandWords.appName`、`IslandPalette.source`、`IslandMark`；好几处的 `else` 默认画成 Codex。
   - 方案 §1.7 的表列了其余按名字分支的地方（`WorkspaceModel`、`QuestionCards`、`ChatModel`、`UsageView`、`DemoTransport` 等），行号可能已变，以代码为准。

## 2. 分支和文件夹

- 分支 `ios-agents`，工作树 `D:/Personal/agent_remote_lanes/iosag`（主会话已建好，HEAD = 2aafa0e 加这份文档）。
- 只改 `apps/ios/` 下的文件。`codemagic.yaml` 和 `apps/ios/scripts/` 非改不可才改，并在结果里写原因。不动电脑端、网页、中转、安卓。
- 不合并别的分支（`voice-keep-text` 等，以后由主会话在用户点头后合）。
- 不改版本号（`apps/ios/project.yml` 的 `MARKETING_VERSION`、`CURRENT_PROJECT_VERSION`），发 TestFlight 时由主会话定。

## 3. 怎么改

### 3.1 协议 2 握手（第一段）

- 发往电脑的每个请求（经中转的 `/api/…`、实时事件流、上传、下载、图片地址）都带 `X-Teleply-Protocol: 2` 和 `X-Teleply-Client: ios/<App 版本号>`。加不了头的地方加查询参数 `protocol=2&client=ios/<版本号>`。照安卓 `RelayApi.kt:112-114`，两样都带也行。
- 推送登记 `POST /account/push/register` 的 body 加 `"protocol": "2"`。灵动岛（Live Activity / push-to-start）的令牌如果走别的登记地址，同样加上。
- 只发往电脑和中转自己的请求；别的网址（苹果、第三方）不加。

### 3.2 说明书 `AgentCatalog`（第一段）

- 新文件 `TeleplyCore/Sources/TeleplyModel/AgentCatalog.swift`：
  - 解析 `{schema, protocol, agents: [...]}`；每项取 `id`、`name{zh,en}`、`color`、`color_dark`、`icon{kind,key}`、`order`、`legacy`、`min_protocol`、`capabilities`、`params`、`ui{card_layout, waiting_text}`。不认识的字段忽略，`sources` 不用。一项解析失败只丢那一项，不丢整份。
  - **内置三家兜底**（`builtin`）：三家的名字只在这个文件里出现一次。电脑返回 404（老电脑）或取不到时用它。
  - **按电脑缓存**：键是设备 id。App 重开、切换电脑、用户点「重试」、电脑版本号变了，才重新取（照安卓）。
  - **三家外观永远用 App 自己的**：说明书里的三家，名字、颜色、图标一律换成内置的（照安卓 `AgentCatalog.fromServer`）；只用它的顺序和能力位。
  - 显示名：按系统语言取 `zh` 或 `en`，都没有就用 id。颜色：说明书的 `color` / `color_dark`，缺了或格式不对用中性灰（安卓 `#6B7280`，深色值照安卓）。图标：新助手一律用通用图标，暂不下载远程图标（和安卓一致）；选一个现有的 SF Symbol 或遥应标志，在结果里写明选了什么。
- `sourceOrder` 的 11 处全换成 catalog：
  - 「是不是认识的助手」= catalog 里有（三家永远有）。
  - 顺序 = catalog 的 `order`，三家顺序不变。
- `Relay.swift:224/229`：接受「all」和 catalog 里的任何 id；碰到 catalog 里没有的行，**不整页报错**，照通用样式显示（名字 = id、中性灰、通用图标），只能读。
- `treeApps`（`Relay.swift:454`）：保留树里所有合法 id（照安卓 `isValidAgentId`），按 catalog 顺序排，不认识的排最后。
- 运行中会变的能力看控制态的 `capabilities_now`，说明书的 `capabilities` 只当默认。

### 3.3 显示（第一段）

- `Labels.sourceName`、`Palette.tint/badge`、`Marks.SourceMark`：三家原样；其他助手用 catalog 的外观。所有 `else` 默认画成 Codex 的地方，改成通用外观。
- 列表筛选、侧栏、归档页、新建面板里的助手列表都来自 catalog。
- 第一段做完，iPhone 就能在列表里看到 Antigravity、打开它的对话读内容（动作还不能用）。

### 3.4 新助手的动作（第二段）

原则：三家的动作、控制态、卡片代码一行不改；在按名字分支的地方，加「catalog 里 `legacy=false` → 通用路」。新助手只会出现在有统一地址的新电脑上，所以通用路不需要回退老路由。

- **控制态**：`GET /api/agents/<id>/state?id=<对话>`，间隔 `params.refresh_ms`，超时 `params.state_timeout_s`。显示 running / waiting / idle 和卡片；按钮按 `capabilities_now`。
- **发送**：`POST /api/agents/<id>/send`，body 照网页 `genericAgentUI` 和安卓的统一发送；`intent` 按 `send_modes`（Antigravity 只有 `send`）。运行中也能发，电脑会排到这一轮结束后，界面上照「已排队 / 已送达」的现有样子显示。回执 `GET /api/agents/<id>/receipt?id=&request_id=`。
- **停止**：`capabilities_now.stop` 且在跑时显示，`POST /api/agents/<id>/stop`。
- **批准 / 回答**：`ui.card_layout` 是 `generic.v1` 时用通用卡片，标题、说明、按钮都来自控制态；`POST /api/agents/<id>/answer`。卡片不设时限：`expires_at` 为 0 表示一直等，不要自己倒计时收起。卡片格式照 docs §五、网页、安卓。
- **新建**：`capabilities.new` 为真时出现在新建面板里。`GET /api/agents/<id>/options` 取项目等选项，`POST /api/agents/<id>/create`，`GET /api/agents/<id>/create/state?request_id=` 等进度，超时 `params.new_timeout_s`。字段按 `new_projectless` / `new_permission` / `settings` 显隐；Antigravity 必须选项目，没有权限和模型选项。
- **图片**：`capabilities.attachments` 为真时能发图，`POST /api/agents/<id>/upload`。张数、大小按 `params.max_images` / `params.max_image_bytes`。HEIC 照常上传，电脑会解码再重新编码。
- **在电脑上打开、归档、恢复、删除、用量、斜杠命令、技能**：按能力位显隐。Antigravity 这些都是 false，就不显示。
- **出错提示**：电脑返回的文案原样显示；前缀用通用的（如「没发出去：」），不出现 Claude / Codex 的名字。

### 3.5 通知和锁屏卡片（第三段）

- `Push.swift:14/24`：只要 `isValidAgentId(app)` 就接受，不要求在 catalog 里。冷启动点通知时说明书还没取到；而中转只会推电脑发过的助手。推送 `teleply` 里的可选 `n`、`k`、`m` 读出来，存进 `IslandAttributes` 等处新加的**可选**字段（如 `sourceName`、`tint`、`markKey`），老字段不动。
- `IslandWords.appName`、`IslandPalette`、`IslandMark` 先用这些可选字段，没有就用 catalog，再没有就通用。三家的岛一点不变。
- 点新助手的通知，能打开它的对话。

### 3.6 用量（第三段）

- `UsageView` 只给 `capabilities.usage` 为真的助手出分组；三家原样。

### 3.7 演示数据和测试（每段都要）

- `DemoWorld` / `DemoTransport` 加假助手 `testing`（显示名「测试助手」，通用外观），照安卓 `FixtureApi.kt` 和电脑端 `agents/testing.py`：几条对话（在跑、等你、空闲）、一张通用卡片、能新建、能发图。只在演示和测试里出现，不进正式名单。
- `TeleplyCore/Tests` 加测试：
  - 说明书解析；404 和取不到时用三家兜底；一项坏了只丢那一项。
  - 三家的名字、颜色、图标不被说明书改。
  - 不认识的 id 不整页报错，用通用样式。
  - 请求带协议头；推送登记带 `protocol`。
  - `treeApps` 的排序。
  - 新助手的地址和 body：state、send、receipt、stop、answer、options、create、create/state、upload。
  - 按能力位显隐；`capabilities_now` 覆盖说明书。
  - 推送的 `n/k/m` 可选字段；没有时照旧。
- 现有测试全部保留，期望值不改。只有「不认识的助手要报错」这一类本来就要变的断言可以改，改了要在结果里逐条写原因。

## 4. 边界

- **三家**：名字、颜色、图标、顺序、按钮、卡片、轮询间隔、路由，一点不变。
- **公开仓库**：代码、测试、文档里不写用户的对话标题、消息、电脑名、账号。演示数据全用编的。
- **这台电脑没有 Swift**（11-12 误删，没装回来），本机编译不了，**不要装**。所有编译和测试都在 Codemagic 上跑，由主会话推送后启动。
- 不推送、不跑 Codemagic、不传 TestFlight、不碰苹果后台和 Codemagic 网站、不碰任何密钥。

## 5. 分三段做，每段做完停下

因为本机编译不了，每段做完由主会话推到 GitHub、在 Codemagic 上编译和跑测试；报错由主会话发回来，你再改。

- **第一段**：3.1、3.2、3.3，加上对应的测试。
- **第二段**：3.4，加上对应的测试。
- **第三段**：3.5、3.6，演示数据补全；在 `apps/ios/README.md` 最前面照已有各节加一节「0.9.0 草稿：iOS 按说明书显示助手」，写改了什么和「留给你在真机上验」清单（版本号先写草稿，主会话定）。

每段结束都要：
1. 自己把这一段的改动逐个文件读一遍：Swift 6 严格并发（`@MainActor`、`Sendable`）、可选值、`switch` 是否穷尽、新类型是否被所有 `case` 处理、`public` 是否够用（TeleplyCore 是单独的包，App 要用的东西得是 `public`）。
2. 提交，说明用中文。
3. 在本文最后「结果」里写这一段：改了哪些文件；自己怎么核对的；**最可能编不过的地方**（列出文件和行，Codemagic 报错时好快速对上）；没做的和要用户看的。
4. 停下，等主会话的消息。

## 6. 验证

- 每段：上面第 5 节的自查和新测试。
- 主会话：推送后跑 Codemagic `ios-native-check` 的 compile 模式（先跑 TeleplyCore 的 `swift test`，再编模拟器版 App）。第三段后再用 shots 模式拍演示截图：三家的页面和 `ipad-adapt` 拍的应当一样，假助手的页面是新的。
- 最后在用户点头后传 TestFlight。用户在 iPhone 和 iPad 上验：三家照常；Antigravity 能看、能发、能批准、能停、能新建、能发图；通知和锁屏卡片正常；连老电脑（没有 `/api/agents`）时只显示三家、不报错。

## 7. 结果（DeepSeek 填）

### 第一段

**结论**：3.1、3.2、3.3 做完了。请求带协议 2；iOS 从 `/api/agents` 取说明书并按电脑缓存；名单、颜色、图标、筛选、侧栏、归档页、新建面板都由 catalog 来；不认识的助手不再整页报错，用通用样式显示、只能读。三家（Codex / Claude / DeepSeek）的请求、路由、控制态、卡片、按钮、颜色、图标、顺序一行没动。演示里加了假助手 `testing`，默认关着，要用 `-TeleplyDemoAgents` 打开（审后改的，见下）。本机没有 Swift，**没编译、没跑测试**，全部等 Codemagic。

**改了的文件**（都在 `apps/ios/` 下；第一段合计 31 改 3 新——审后这轮又改了 9 个文件，其中 `AppModelTests`、`DemoServiceTests` 已被改回原样，净变化里看不到）

- 新 `TeleplyCore/Sources/TeleplyModel/AgentCatalog.swift`：说明书解析（`AgentInfo` / `AgentName` / `AgentIcon` / `AgentCapabilities` / `AgentParams` / `AgentUi`，一项坏了只丢那一项）、`isValidAgentId`、`#RRGGBB`/`#AARRGGBB` 校验、`AgentCatalogSnapshot`（内置三家 + `fromServer` 把三家的名字/颜色/图标/`legacy`/`min_protocol` 换回 App 自己的，只用电脑给的 `order` 和能力位；电脑漏了三家也补上）、`AgentCatalog`（按设备 id 缓存，`Mutex` 保证 Sendable，404 存三家，版本号变了才算要重取）。
- `TeleplyModel/Relay.swift`：`TeleplyClient`（`protocolVersion = 2`、`ios/<版本>` tag，另有纯函数 `tag(_:)` 给测试拼法）；`signed()` 给每个请求加 `X-Teleply-Protocol` / `X-Teleply-Client`（上传、下载、图片、实时流都走它，因此全都带上）；`agents(device:)`（404 返回 nil）；`chatList` 的来源校验改成 `isValidAgentId`（不认识的合法 id 不再报错）；`treeApps(_:catalog:)` 保留树里所有合法 id、按 catalog 排序、不认识的排最后；实时流另带 `protocol=2&client=…` 查询参数（和安卓一样两样都带）。
- `TeleplyModel/Models.swift`：删掉 `sourceOrder`（11 处引用全部换掉，编译器会盯住漏掉的）。
- `TeleplyModel/Labels.swift`：`sourceName(_:catalog:)` 从 catalog 取名字（默认 `.current`），不认识的用 id。
- `TeleplyModel/Push.swift`：推送登记 body 加 `"protocol": "2"`；`PushTarget` 只要 `isValidAgentId(app)` 就接受（审后改：不要求在 catalog 里，冷启动点通知时说明书还没取到）。
- `TeleplyModel/NewJob.swift`：`newJobDock(_:catalog:)`。
- `TeleplyState/AppModel.swift`：新增 `catalog`（观察得到）和 `agentCatalog` 缓存、`agentsTask`；`live()` 里同步当前电脑的 catalog；`settle()` 等它；`clearAll` 清掉；`logout` 忘掉缓存；`checkStatus` 的版本号变了就重取。
- `TeleplyState/AppModel+List.swift`：新增 `syncCatalog` / `refreshAgents` / `serverVersion` / `applyCatalog`（先读 `/api/status` 的 `ui_version`，同版本不重取，取到之后才记版本，失败下次再问）；`retrySources` 一起强取；`loadTree` 用 `treeApps(tree, catalog:)`；`cachedSources` 只要求合法 id；`listDisplay` 接受任何合法来源。
- `TeleplyState/AppModel+Reading.swift`、`AppModel+New.swift`：来源切换只要求合法 id（和安卓 `pointSource` 一致）。
- `TeleplyState/AppModel+Archive.swift`：归档看 catalog 的 `archive` 能力位（三家不变，新助手没有就不出左滑）。
- `TeleplyState/ChatModel.swift`：**第一段的临时处理**——`legacy=false` 的新助手不读老地址的控制态、不轮询，只读记录和实时流（否则 404 会在能读的页面上挂一条「连接中断」）。第二段接统一地址时删掉。
- `Teleply/Design/Palette.swift`、`Marks.swift`、`List/ChatRows.swift`、`List/ChatListView.swift`、`Drawer/DrawerView.swift`、`Settings/ArchivedView.swift`、`Chat/ChatSheets.swift`、`Chat/ConversationView.swift`、`NewChat/NewChatSheet.swift`、`NewChat/NewJobViews.swift`：三家颜色/图标/名字原样；其他助手用说明书的颜色（深色值也取，格式不对用中性灰 `#6B7280`/`#9CA3AF`）和通用图标；名字、筛选、徽标、侧栏、归档分组、新建面板都从自己的 `model.catalog` 取（这样 catalog 到了会立刻重画，不会先显示 id 很久）。
- `Teleply/App/TeleplyApp.swift`：启动时把 `AppVersion.short` 交给 `TeleplyClient`。
- `Teleply/App/LaunchOptions.swift`：加 `-TeleplyDemoAgents`（只在调试版生效，照 `-TeleplyDemoSite` 的写法），打开时才给演示的测试电脑 A 加假助手。
- `TeleplyIsland/IslandWords.swift`、`TeleplyIslandWidget/IslandViews.swift`：`else` 不再默认当 Codex（名字用 id、颜色用 `muted`、图标用通用符号），三家的岛不变。Island 是单独 target，读不到 catalog，名字和颜色等第三段随推送带（`n/k/m`）。
- 演示（`TeleplyDemo/DemoWorld.swift`、`DemoTransport.swift`）：`/api/agents` 路由；`demoData` 里四份说明书（`testing` 照 `agents/testing.py`，颜色 `#7C3AED`/`#A78BFA`）；`DemoWorld(testingAgent: true)`（或 `-TeleplyDemoAgents`）才把 `testing` 的两行（`test-running`、`test-waiting`）、会话内容、侧栏分组给它——**关着时列表行、树、`/api/agents` 和 0.8.0 完全一样**；B 仍然没有 Claude，网站演示仍然只有 DeepSeek。
- 测试：新 `AgentCatalogTests.swift`（解析、坏项、三家不变、三家永远在、未知 id 通用样式、颜色格式、名字回退、id 规则、按电脑缓存与版本、treeApps 排序）、新 `AgentHandshakeTests.swift`（tag 拼法、每个请求带协议头与 tag、实时流的查询参数、推送登记带 `protocol`、未知助手行不整页报错、演示默认三家/打开后四家、catalog 到达模型、老电脑 404、取不到、新助手会话能打开能读）。

**自己怎么核对的**（本机没有 Swift，没有编译）

1. 逐个文件读过改动（可选值、`switch` 穷尽、`public` 够不够、`@MainActor`/`Sendable`）：`AgentCatalogSnapshot.current` 用 `nonisolated(unsafe)`（和 `Labels.language` 同一手法），`AgentCatalog` 是 `final class … Sendable` + `Mutex`，AppModel 侧全在 MainActor 上；TeleplyDemo/TeleplyIsland 没有反向依赖 TeleplyModel 的新类型。
2. 写了一个括号/引号配对检查脚本（`F:\Android-Dev\work\20261101-island-duplicates\20261125-ios-agents\balance_check.py`），对改动的 Swift 文件逐个跑过（第一轮 32 个、审后 10 个），0 处不平衡；它不认 Swift 语法，只能抓漏括号。
3. 用 `ConvertFrom-Json` 把这次新写的所有 JSON 字面量（4 份演示说明书、测试里的假说明书、坏项）都验过是合法 JSON。
4. 对着安卓 1.0.10 的 `AgentInfo.kt` / `AgentCatalog.kt` / `RelayApi.kt` 逐条比：能力位默认值（list/read 缺省 true）、`params` 下限、三家兜底、`fromServer` 归一化、`treeApps` 排序规则、404 语义。
5. 对着中转 0b3f8d7 核了协议登记：只有 `POST /account/push/register` 存 `protocol`（按通知令牌），灵动岛的 `/account/push/activity`、`/start-token` 不存，也不按手机协议过滤；所以 3.1 只改推送登记，岛的两个登记地址**故意没加** `protocol`。
6. 审后按用户要求把测试里可能被握手改影响的「整体相等」比较全查了一遍：正则查 `headers ==`、`absoluteString ==`、`.url ==`、`queryItems ==`、`queryValue(`，逐个看。结果：只有 `RelayClientTests:15` 的整份请求头会变（已改）；`RelayClientTests:13` 和 `ServiceOriginTests:37/39` 是 `/account/config` 和 `ServiceOrigin.url()` 的网址，没有新增查询参数；`IslandTests:180/182` 是 `IslandURL` 的网址；`queryValue(` 的三处（`AppModelTests:333`、`AttachmentTests:229`、`RelayReadTests:174`）都是按名字取值；其余是 `url.path` 列表或 `contains`。**没有别的会因为握手而变。**
7. Codemagic 报回原始字符串的问题后，写了一个扫描脚本（`F:\Android-Dev\work\20261101-island-duplicates\20261125-ios-agents\raw_string_check.py`），按 Swift 的规则走每个文件：以 N 个 `#` 开头的原始字符串在第一个 `"` + N 个 `#` 处结束，脚本检查结束符后面那个字符能不能接下去（`1`、`E` 这种就不能）。对这两轮改过的 34 个 Swift 文件跑过，改前正好报出那 7 处，改后 0 处；另外用 `json.loads` 把改过的 7 个字符串再解析了一遍，内容和改前一致。

**现有测试的改动**（逐条原因；第 1、2 处审后已撤销）

1. ~~`AppModelTests.signingInListsTheComputersAndEnteringOneShowsItsList`：`knownApps` 从三家变成四家~~——审后已改回三家（演示的假助手改成要打开才有，见「审后修改」2）。
2. ~~`DemoServiceTests.computerBHasNoClaudeAnywhere`：A 的 `treeApps` 多了 `testing`~~——同上，已改回三家。
3. `RelayReadTests.mixedListKeepsEachRowsSourceAndAcceptsAnyLegalOne`（原 `…RefusesUnknownOnes`）：`app:"other"` 的行不再报错（3.2 明说「碰到 catalog 里没有的行不整页报错」），改成断言它被接受、而 `app:"Mail!"` 这种非法 id 仍然拒绝。
4. `RelayReadTests.accountListsComputersAndTreeNamesItsApps`：`treeApps` 现在保留树里的合法 id（3.2 明说「保留树里所有合法 id」），期望值从 `["codex","deepseek"]` 变成 `["codex","deepseek","other"]`。
5. （审后第 5 处）`RelayClientTests.getAsksForJSONWithoutOriginOrBody`：整份请求头从 `["Accept": "application/json"]` 改成再加上 `X-Teleply-Protocol: "2"` 和 `X-Teleply-Client: TeleplyClient.tag`。原因：`signed()` 给每个请求都带握手（安卓 `RelayApi.request()` 也一样），这条断言写的正是整份请求头，所以确实要跟着变。
6. （审后）`PushTests.aNotificationNamesAComputerAnAppAndAConversationOnly`：`a: "mail"` 从「拒绝」改成「接受」，另加 `a: "9mail"` 仍然拒绝。原因：3.5 改成只要合法 id 就收。
7. （审后）`IslandFlowTests.tappingTheIslandOpensOnlyItsOwnAddress`：同上，`a=mail` 现在接受，另加 `a=9mail` 拒绝。

**最可能编不过的地方**（Codemagic 报错时按这里对）

- `TeleplyCore/Sources/TeleplyModel/AgentCatalog.swift:306`（`nonisolated(unsafe) public static var current`）、`434`（`Mutex<[String: Entry]>`；`import Synchronization` 的 `withLock` 返回值/`inout` 闭包）、`68`（`AgentCapabilities` 的属性名 `open`/`new`/`delete` 当变量名）。
- `TeleplyCore/Sources/TeleplyModel/Relay.swift:18`（`public static var tag` 和 `public static func tag(_ version:)` 同名重载；审后加的）。
- `TeleplyState/AppModel+List.swift:240-262`（`Task { [weak self] … }` 在 TeleplyState 默认 MainActor 隔离下捕获 `client`、`await self.serverVersion`；`known` 在闭包外读）。
- `TeleplyState/AppModel.swift:362`（`settle()` 里 `while let running = agentsTask` 和 `agentsTask == running` 的 `Task` 相等比较）、`732`（`live()` 开头调 `syncCatalog`）。
- `TeleplyState/ChatModel.swift:221`（`AgentCatalogSnapshot.current.isLegacy(key.app)` 在非 UI 的 ChatModel 里读全局）。
- `Teleply/Design/Palette.swift:79`（`UIColor(dynamicProvider:)` + `Color(uiColor:)`，这个文件新加了 `import UIKit`）。
- `Teleply/Design/Marks.swift:19`、`TeleplyIslandWidget/IslandViews.swift:61`（`Image(systemName: "sparkles").resizable()` 放在 `Group` + `.frame` 里）。
- `TeleplyCore/Sources/TeleplyModel/Push.swift:118`（body 里混用 `.string(...)` 和字符串字面量的 `[String: JSONValue]`）；`16`（`PushTarget` 的 guard 换成 `isValidAgentId`，审后改）。
- 演示：`TeleplyDemo/DemoWorld.swift:95`（`init(site:testingAgent:)` 两个默认参数）、`112`（`apps(of:)` 里 `var apps = …` 再 append）；`Teleply/App/LaunchOptions.swift:29/68`（`agentsDemo` 是 `nonisolated`，`DemoHolder` 也是 nonisolated）。
- 演示/测试里的原始字符串：`TeleplyDemo/DemoWorld.swift:834-837`、`TeleplyCoreTests/AgentCatalogTests.swift:12/56/90` 现在是 `##"…"##`（里面的 `"#1E222A"` 这类颜色值不再是结束符）。这里若再报 `not a valid digit in floating point exponent` / `expected ',' separator`，就是字符串里又出现了 `"##`，要再升一层 `###"…"###`（用同一个扫描脚本先查）。
- 测试：`AgentHandshakeTests.swift:8`（`struct LegacyAgentsTransport: RelayTransport` 只转发 `send`，AppModel 里的会话仍会去要实时流）、`43`（`AppServices` 参数顺序）、`67`（`client.agents(device:)` 在 `WatchedTransport` 上）、`74-76`（`upload`/`download` 走 `WatchedTransport`）。`AgentCatalogTests.swift:15`（`DemoData.parse` 在别 target，靠 `@testable import TeleplyDemo`）。`RelayClientTests.swift:17`（整份请求头的期望值比的是 `TeleplyClient.tag`）。

**没做的 / 要用户看的**

- 第二、三段：统一地址的控制态/发送/停止/批准/回答/新建/上传、`capabilities_now`、推送 `n/k/m`、`UsageView` 按能力分组、`README` 的 0.9.0 草稿一节——都还没做。
- 第一段的临时现状（第二段接上就好）：新助手页面上输入区是灰的、没有说明为什么不能发；新建面板能选到新助手，但创建会走老地址报 404；灵动岛/锁屏卡片里新助手的名字先显示 id、颜色用中性灰。
- 点新助手的通知：只要 id 合法就接受（审后改），冷启动点通知也能打开；卡片上的名字和颜色仍要等第三段的推送字段。
- 演示里 `testing` 默认不出现；要看它，用调试版启动参数 `-TeleplyDemoAgents`（或 `DemoWorld(testingAgent: true)`）。打开后 `testing` 用的是全能力（照 `agents/testing.py`），所以演示中它可以被归档；真电脑的能力位以说明书为准。
- 没推送、没跑 Codemagic、没碰 TestFlight/苹果后台/中转/密钥；版本号没动（`project.yml` 仍是 0.8.0）。
- 要用户在 Codemagic 上先看 compile：`swift test` 里新增的两套测试 + 老测试；再看 App 编译（`Palette`/`Marks`/新增 catalog 依赖只在 App 里编到）。

### 审后修改（第一段，2026-11-25，按用户审阅意见）

1. **一个现有测试会挂（第 5 处改动）**：`RelayClientTests.getAsksForJSONWithoutOriginOrBody` 原来要求 `/account/config` 的请求头正好是 `["Accept": "application/json"]`，而 `signed()` 现在给每个请求都加两个头。改法：保留「所有请求都带握手」（安卓 `RelayApi.request()` 也一样），把这条断言改成完整请求头 `["Accept": "application/json", "X-Teleply-Protocol": "2", "X-Teleply-Client": TeleplyClient.tag]`。
2. **测试不再改全局版本号**：`TeleplyClient` 新增纯函数 `tag(_ version:)`，测试里单独断言 `tag("0.9.0") == "ios/0.9.0"`、`tag("") == "ios/?"`；`everyRequestCarriesProtocolTwoAndTheAppTag` 不再设置 `TeleplyClient.version`，只断言请求头等于当时的 `TeleplyClient.tag`（Swift Testing 默认并行跑，改全局会让别的测试读到）。
3. **演示数据恢复原样**：`DemoWorld.apps(of:)` 回到原来的写法（测试电脑 B 两家、A 和离线那台三家），假助手 `testing` 改成要打开才有——`DemoWorld(testingAgent: true)`，外加只在调试版生效的启动参数 `-TeleplyDemoAgents`（照 `-TeleplyDemoSite` 的写法，`DemoHolder.fresh()` 里传）。关着时列表行、树、`/api/agents`（只回三家说明书）和 0.8.0 逐张一样；打开后 A 才有 `testing` 的两行、会话、侧栏分组和第四份说明书。`AppModelTests`、`DemoServiceTests` 里第一版改过的两处期望已改回原样；新测试改用 `DemoWorld(testingAgent: true)`，并加了「演示默认只回三家、打开后回四家」的测试。
4. **`PushTarget.init?` 改成只要 `isValidAgentId(app)` 就接受**：不要求在 `AgentCatalogSnapshot.current` 里，冷启动点通知时说明书还没取到；中转只会推电脑发过的助手。这样也少了一处在主线程外读全局。设计 3.5 第一条已按这个意思改。`PushTests`、`IslandFlowTests` 里原来断言 `a: "mail"` 被拒绝的两处，改成接受 `mail`、拒绝 `9mail`（第 6、7 处改动）。
5. **Codemagic `6b062a17631e119ed9f664eb` 的编译错误：原始字符串提前结束**。`#"…"#` 在第一个 `"#` 处就结束，而说明书 JSON 里的颜色值 `"#1E222A"`、`"#4285F4"` 正好带着 `"#`；`TeleplyModel`、`TeleplyIsland` 编过了，`TeleplyDemo` 在 `DemoWorld.swift` 834–837 报 `'A' is not a valid digit in floating point exponent` / `expected ',' separator`。改法：这 7 处（`DemoWorld.swift:834-837` 四份说明书；`AgentCatalogTests.swift:12`、`56`、`90`）改成 `##"…"##`，里面的 `"#` 就不再是结束符。又把这两轮写的所有原始字符串用脚本重查了一遍（见「自己怎么核对的」7）：34 个改过的 Swift 文件，改前正好只有这 7 处、改后 0 处；7 个字符串再解析成 JSON，内容和改前一样。改写时 PowerShell 把这两个文件的行尾临时写成了 CRLF，已改回 LF（`git ls-files --eol` 现在是 `i/lf w/lf`，提交里只有那 7 行变化）。

### 第二段

**结论**：3.4 做完了（统一地址的控制态、此刻能力、发送/回执、通用卡片、新建三步、上传，以及按能力位显隐和演示/测试）。三家（Codex / Claude / DeepSeek）的老路由、请求体、回执读法和界面保持不变。本机没有 Swift，**没编译、没跑测试**，等 Codemagic。

**改了的文件**（都在 `apps/ios/` 下；18 改 3 新）

- `TeleplyModel/AgentCatalog.swift`：`AgentCapabilities.narrowed(by:)`（按控制态的 `capabilities_now` 逐键收窄：false 不能变 true、列表取交集、没写的键等于说明书；和安卓 `AgentCaps.capsNow` 一致）、`flag(_:)`（按名字取能力位）、`skillsAvailable(caps:layout:)`。
- `TeleplyModel/ChatCore.swift`：`Control` 增加 `capabilitiesNow`、`capabilityNotes`、`narrowed(_:)`、`note(_:)`（去空白）；新增 `agentReceiptLabel`（新助手回执的 `delivered`/`queued` 读成「已送达 / 已排队」，三家的 `receiptLabel` 一个字节没动）。
- `TeleplyModel/Relay.swift`：统一地址 `agentState`（`params.state_timeout_s`）、`agentSend`（`send_timeout_s`）、`agentStop`、`agentQueue`、`agentAnswer`、`agentOpen`（`open_timeout_s`）、`agentReceipt`、`agentOptions`、`agentCreate`（`new_timeout_s`）、`agentCreateState`、`agentUpload`（`params.max_image_bytes`），以及 `agentPath`（先校验 id）。`control` / `command` / `receipt` / `upload` 对 `legacy=false` 走这些地址，三家走原来的分支（同一个函数，原代码未改）。
- `TeleplyModel/Interaction.swift`：`genericCards`（只认 `status=pending`、有 id、至少一题）、`genericCardTitle`（title → 第一题 header → 「<助手名> 等你批准 / 有问题要问你」）；`pendingCards`、`inlineCards` 为新助手加通用分支。
- `TeleplyState/AppModel+List.swift`：`capabilities(_:)`（说明书再按当前对话的 `capabilities_now` 收窄）、`can(_:app:)`、`capabilityNote(_:app:)`、`isGeneric(_:)`、`cardLayout(_:)`、`hasAny(_:)`（这台电脑上有没有哪家助手能做某件事）、`sendBlockedNote(_:)`（不能发时输入区的说明）。
- `TeleplyState/ChatModel.swift`：删掉第一段「新助手不读控制态」的临时处理；统一地址读控制态，新助手的轮询间隔读 `params.refresh_ms`（三家仍是 Claude 5 s、DeepSeek 2.5 s，审后确认）；发送的 `intent` 按 `send_modes`（Antigravity 只有 `send`，在跑也照发、由电脑排队），`expected_turn` 只在 `steer` 时带；`dispatch` 的动作回执对 `ok` 的新助手算「已接收」；`reconcile` 对新助手用 `agentReceiptLabel`，三家原样。
- `TeleplyState/WorkspaceModel.swift`：`generic/answer` 走 `agentAnswer`；`openOnComputer` 对新助手走 `agentOpen`；`checkAction` 认 `generic/answer`（卡片还在不在）；`loadChoices` 对新助手不读模型列表。
- `TeleplyState/WorkspaceModel+New.swift`：新助手的 `options`（项目→文件夹行、模型行只留电脑给的一句话）、`create` 的字段按能力位（`new_projectless` 是否给「无项目」、`new_permission`、`settings` 里有没有 model、不带 references）、必须选项目时的中文提示。
- `TeleplyState/WorkspaceModel+Uploads.swift`：新助手只收图片、张数 `params.max_images`、单张 `params.max_image_bytes`；新会话的草稿上传不提供。
- `TeleplyState/NewChatJobs.swift`：新助手的提交走 `create`、核对走 `create/state`；「继续发送」按同一请求号重发 `create`（电脑按请求号只建一次），三家仍走原地址。
- 新 `Teleply/Chat/GenericCards.swift`：通用卡片（`generic.v1`）：标题、等宽 `detail`（超过 12 行折叠）、1–3 题、选项单选/多选、`isOther` 自由填写、`isSecret` 密码框、批准卡点选项即提交、提问卡「提交」；按 `approve`/`answer` 此刻能力灰掉并显示 `capability_notes` 的原因或「请在电脑上处理」；`expires_at` 过了写「已过时，请在电脑上处理」，为 0 就一直等；失败只把原因显示在卡片下面，不清已选已填。
- `Teleply/Chat/QuestionCards.swift`：`InlineCard.generic`，按状态画通用卡片。
- `Teleply/Composer/ComposerView.swift`：新助手的能不能发看此刻 `send_modes`（关着的 Antigravity 发送键灰、状态行写电脑的原因）；排队只在 `queue` 模式下；新助手不显示模型/模式 chip；`/` 只在有 `slash_commands` 时、`$` 只在有技能时；附件入口按 `attachments`。三家走原来的式子（见「审后修改」一）。
- `Teleply/Composer/Attachments.swift`：新助手的 ＋ 只有拍照/手机照片（`params.max_images`），没有文件、电脑文件、引用对话/技能；新会话不提供图片。
- `Teleply/Chat/ConversationView.swift`：新助手的停止键看 `stop` 此刻能力；⋯ 菜单里「电脑上打开」「用量」按 `open`/`usage` 显隐。三家走原来的式子（见「审后修改」一）。
- `Teleply/NewChat/NewChatSheet.swift`：项目/模型/权限行按能力位显隐；没有模型时显示电脑给的一句话；「创建并发送」在没有 `new_projectless` 时必须先选项目。
- `Teleply/Settings/ArchivedView.swift`、`SettingsView.swift`：第二段曾按 `restore`/`delete`/`usage` 显隐，审后已整文件退回原样，所以不在这一版的改动里（三家和只有 DeepSeek 的电脑都照旧）。
- 演示（`TeleplyDemo/DemoWorld.swift`、`DemoTransport.swift`）：只在 `testingAgent` 打开时，`testing` 的统一地址照 `agents/testing.py` 回答——控制态（A 在跑、B 等你并带一张批准卡，`capabilities_now` 全开）、发送与回执（在跑排成 queued）、停止、回答（只一次、只收自己的选项）、`options`（一个项目）、`create`/`create/state`（按请求号只建一次）、上传（图片）；关着时这些地址 404，演示的其余回答与 0.8.0 一样。
- 测试：新 `AgentUnifiedTests.swift`（每个统一地址的网址/查询/超时/请求体、回执文字、能力位收窄、状态里的 `capabilities_now`/原因、通用卡片与问题条、id 校验、三家地址和请求体不变）、新 `AgentUnifiedFlowTests.swift`（演示上整条路：控制态与卡片→回答、发送→回执「已送达」、停止、新建三步、上传、关着时 404）。另把第一段 `AgentHandshakeTests.aNewAssistantsConversationOpensAndReads` 的「只读」断言改成「有控制态、能发、能批」（第一段的临时行为已按要求删掉）。

**自己怎么核对的**（本机没有 Swift，没有编译）

1. 对着电脑端真代码逐项比：`agents/base.py`（`http_get`/`http_post`/`http_upload` 的子路径与参数、`attach_capabilities_now`、`_now_capabilities`、`can_now`、收据形状）、`agents/antigravity.py`（`state` 字段、`send` 的 body/attachments/`delivery_state`、`check`→`delivered/queued/stage`、`_waiting_cards` 的卡片、`new_options`/`create`/`create_status`、上传上限）、`static/generic-ui.js`（标题回退、detail 12 行、单选直提、写字清选项、不能答/过时的说法）、`docs/adding-an-agent.md` §五（回答 body 与 400/409）。
2. 对着安卓 1.0.10（`RelayApi.kt` 的 `withLegacyFallback` 一支、`AgentCaps.kt`、`ComposerUi`/`ChatUi`）核了「统一地址、`intent` 按 `send_modes`、此刻能力逐键收窄、列表/新建的能力位显隐」。
3. 逐个文件读过改动（可选值、`switch` 穷尽、`public`、`@MainActor`/`Sendable`）；括号/引号配对脚本两版都跑过（第一版 23 个、审后这轮 9 个）0 问题，原始字符串扫描 0 问题，22 个原始字符串 JSON 字面量都能解析。
4. 三家不变是「同一个函数里加分支」做到的：`control`/`command`/`receipt`/`upload` 的旧代码原样保留；`ChatModel` 的三家 `intent`/`expected_turn`、回执读法、轮询间隔（5 s / 2.5 s）与原值一致；`receiptLabel` 未改，新助手另用 `agentReceiptLabel`。现有测试里只改了第一段那条「只读」断言（上面已写原因），其余期望值没动。

**最可能编不过的地方**（Codemagic 报错时按这里对）

- `TeleplyCore/Sources/TeleplyModel/Relay.swift:273`（`agentState` 起的十个统一方法；`RelayRequest` 的 `upload:` 与 `origin.url(try …)`）、`:383`（`control` 的三元/guard 分支）、`:419` 起的 `command`（统一分支的 `switch route` 返回值）。
- `TeleplyCore/Sources/TeleplyModel/AgentCatalog.swift:124`（`narrowed(by:)` 里的局部 `func flag`/`words` 与 `guard let now`简写）、`:190` 起的 `flag(_:)`。
- `TeleplyCore/Sources/TeleplyModel/ChatCore.swift:56`（`extension Control` 的计算属性与新方法）、`:202`（`agentReceiptLabel`）。
- `TeleplyCore/Sources/TeleplyModel/Interaction.swift:67`（`genericCards` 的闭包过滤、`genericCardTitle` 的默认参数）。
- `TeleplyCore/Sources/TeleplyState/ChatModel.swift:219`（统一控制态 + `Duration.milliseconds(Int64(...))`）、`:454`（`submit` 里 `generic`/`caps` 与嵌套三元 intent）、`:629`（`let took` 的 `ok` 回退）、`:736` 起（`reconcile` 里 `let state` 与外层 `state` 同名遮蔽、三元 label）。
- `TeleplyCore/Sources/TeleplyState/WorkspaceModel+New.swift:75`（`loadAgentOptions` 的 Task 捕获与 `lists`/`newData` 写入）、`:179` 起的 `create`（能力位三元、`ReadFailure` 里的字符串拼接）。
- `TeleplyCore/Sources/TeleplyState/NewChatJobs.swift:112`（`send` 的弱 `self?` 与 `?? [:]`）、`:236` 起（重发 create 的三元）。
- `TeleplyCore/Sources/TeleplyState/WorkspaceModel.swift:514`（`action` 的 generic 分支与 `checkAction` 的嵌套三元）。
- 新 `Teleply/Chat/GenericCards.swift:10`（`QuestionCard` 里混 `ForEach`/`Button`；`GenericQuestion` 的两个尾随闭包 `{…} submit: {…}`；`Group`+`SecureField`/`TextField` 的 `.fieldBox`）。
- `Teleply/NewChat/NewChatSheet.swift:147`（`modelNote` 返回 `String?`、`Text(LK(note))`）、项目行的 `projectlessAllowed` 参数与 `detail` 嵌套三元。
- `Teleply/Composer/Attachments.swift:47`（`Group { if … EmptyView() else Menu … }`，`.photosPicker` 挂在 Group 上）。
- `Teleply/Composer/ComposerView.swift:262` 起（`controls` 里的 `showsAttach`、`chips` 的 `else if !generic`、`StatusLine` 的 `blocked` 优先）。
- `TeleplyCore/Sources/TeleplyDemo/DemoWorld.swift:259` 起的 `testing*` 六个方法（`withLock` 里返回字典字面量、`(status:reply:)` 元组）、`:985` 起的 `testingApprovalCard`/`testingCapsNow`（`JSONValue` 字面量）。
- `TeleplyCore/Sources/TeleplyDemo/DemoTransport.swift:76`（`agentRoute` 里先 GET 后 POST 的 `switch`、`let reply` 只在分支里赋值）、`uploaded` 对 testing 的识别。
- 测试：`AgentUnifiedTests.swift`（`#expect(try await …)`、`#expect(await …count == 1)`、`ReadFailure` 相等比较）、`AgentUnifiedFlowTests.swift`（`until` 的 MainActor 闭包、`#require` 里的闭包、`model.openJob`/`jobs.check`）。

**没做的 / 要用户看的**

- 第三段（3.5、3.6）：推送 `n/k/m`、岛上的名字/颜色、`UsageView` 按能力分组、`README` 的 0.9.0 草稿——都还没做。
- 通用助手的 `/` 命令**列表**仍走老地址 `composer/commands`（Antigravity 的 `slash_commands` 是 false，所以看不到）；以后哪家开了 true，要接 `/api/agents/<id>/commands`。
- 新助手的新建对话不收图片（电脑的 `create` 不收），所以新会话面板不给图片；建好之后能发图。
- 新助手的停止成功后，气泡先写「停止请求已接收，等待轮次确认」，要等回执/状态说停下来了才变「已停止」——真机上要看一眼。
- 设置里「用量」现在要求这台电脑有助手支持用量：只有 DeepSeek 的电脑不再显示这一节（那页本来只列 Codex 和 Claude）；三家的其它页面不变。
- 新助手的实时流（`/api/events?app=<新助手>`）没有在真电脑上验过；控制态轮询和实时流在同一个重连循环里（原来的结构），真机上要看它是否也推事件。
- 演示里 `testing` 只有开着 `-TeleplyDemoAgents`/`DemoWorld(testingAgent: true)` 才有；截图巡览不传这个参数，列表行、树、说明书和 0.8.0 一样。
- 没推送、没跑 Codemagic、没碰 TestFlight/苹果后台/中转/密钥；版本号没动。

### 审后修改（第二段，2026-11-25，按用户审阅意见）

**一、三家的按钮改回原来的结果。** 上面「改了的文件」里 ComposerView / Attachments / ConversationView / SettingsView / ArchivedView / ChatModel 那几行描述的是新助手；三家现在不读说明书的能力位，也不读 `capabilities_now`。判断集中在 `TeleplyState` 的 `AppModel`（`AppModel+List.swift`）：

- `offersStop`、`offersQueue`、`offersSend`、`offersAttachments`、`offersOpenOnComputer` 对三家一律 `true`，对新助手才看此刻能力。
- `showsUsage` 对三家是原来的 `app != "deepseek"`，对新助手才看 `usage`。
- `allowsCommands` 对三家一律 `true`；`allowsSkills` 对三家是原来的 `app != "deepseek"`，对新助手才看 `skills`/`slash_commands`。
- `sendBlockedNote` 只对新助手给说明（三家保持没有这一行）。

界面改成只调用这些小函数：

1. `ComposerView`：`queue` 仍是 `running && queueAvailable`（三家）；`reachable` 仍是 `control.available || sendsWhileAway(app)`（三家）；`/` 三家照旧都弹；`$` 三家照旧只有 DeepSeek 不弹；＋ 三家照旧都有。
2. `Attachments.AttachButton`：三家的菜单还是拍照、手机照片、手机文件、从电脑选择文件、引用对话，引用技能只有 DeepSeek 没有；照片上限仍是 5。只有新助手才只剩拍照/照片、上限读 `params.max_images`。
3. `ConversationView`：`canStop` 三家仍是 `running && (app != "claude" || stop_token 非空)`；⋯ 菜单里「电脑上打开」三家照旧都有；「用量」三家照旧是 `app != "deepseek"`。
4. `ArchivedView`：整个文件退回第二段之前：三家的行能不能勾选删除、能不能恢复，还是 `can_delete && deletable.contains(app)` 和 `!busy`，不读能力位。
5. `SettingsView`：整个文件退回第二段之前：「已归档对话」和「用量」两节选了电脑就显示，不看能力位（只有 DeepSeek 的电脑也照旧显示「用量」）。
6. `ChatModel` 的轮询间隔：三家用原来的常数（Claude 5 秒、DeepSeek 2.5 秒，Codex 不轮询）；只有新助手才读 `params.refresh_ms`。

`model.capabilities(_:)` 仍然对所有人做收窄（卡片/显示用），但三家的按钮不再读它。新建面板（`NewChatSheet`、`WorkspaceModel+New`）按说明书能力位决定字段这一点保留（用户核过：对三家来说电脑给的值与内置表都和原来的规则一致）。

**二、Codemagic `6b0630d38fb095828b5ec55a`：TeleplyCore 的源码模块都编过了，测试模块没编过，错都在 `AgentUnifiedFlowTests.swift`**：第 49 行 `inlineCards` 在 App 的 `QuestionCards.swift` 里、测试编不到（改成 TeleplyModel 的 `genericCards`；`AgentUnifiedTests.swift` 里我也用了 `inlineCards`，同样改掉）；第 65、81 行 `body["request_id"].string()?.isEmpty` 在非可选 `String` 上用了 `?.`（改成 `!body["request_id"].string().isEmpty`）。测试编过了才会编 App 本体，所以 `GenericCards.swift`、`ComposerView` 这些界面代码下一次才第一次进编译。

**三、测试补上「三家不看此刻能力」这一条**：`AgentUnifiedFlowTests` 新增
- `theThreeKeepEveryButtonWhateverTheStateSays`：用一个把 `/api/codex/state` 的 `capabilities_now` 改成全部关掉的传输层，打开一个 Codex 对话，断言 `capabilities("codex").stop` 已经是 false、`sendModes` 是空，但 `offersStop/offersQueue/offersSend/offersAttachments/offersOpenOnComputer/showsUsage/allowsCommands/allowsSkills` 对 Codex 全是 true，`showsUsage("deepseek")`/`allowsSkills("deepseek")` 仍是 false，`sendBlockedNote("codex")` 仍是 nil。
- `aNewAssistantsButtonsFollowItsState`：同一个「全关」的 state 换成 `/api/agents/testing/state`，断言 `testing` 的这些按钮全部变 false、`sendBlockedNote("testing")` 有说明，而同一台电脑上的三家不受影响。

**审后最可能编不过的地方**：`AppModel+List.swift` 里的八个小函数（`offers*`/`showsUsage`/`allows*`，都带默认 `app: String? = nil`）；`Attachments.swift` 的 `Group { if … EmptyView() else Menu … }`；`AgentUnifiedFlowTests.swift` 末尾的 `AllOffTransport`（`guard var fields = …?.object`、空的 `send_modes: []`）和 `makeAgentModel` 全局函数。

### 审后修改二（第四次编译 6b063285983623fb72d1854d）

这次编译测试模块编过了，333 项里 2 项没过（3 处断言）；测试没全过所以 App 本体（`GenericCards.swift`、`ComposerView` 等）还没进过编译。

**1. `AgentUnifiedTests.theThreeKeepTheirOwnActionAddressesAndBodies`（第 90 行）：测试的期望写错了，改测试。** DeepSeek 那一支（`command()`，0.8.0 以来只多了函数签名和那行 `guard`）不会加 `app` 字段，`intent` 会把 `auto` 映射成 `steer`（`auto` 是 Codex 的说法，DeepSeek 用 `steer`）。断言改成实际发出的 body：`id == "c1"`、`intent == "steer"`、没有 `app`。`command()` 一个字没动。

**2. `AgentUnifiedFlowTests.aSendGoesToItsOwnAddressAndItsReceiptIsRead`（第 76、77 行，`sends.count == 0`）：是代码把正当的发送拦住了，不是测试没准备好。**
- 测试这边是准备好的：`open` 等到 `control.available`、`ready`、`workspace.ready` 才返回，`edit("跑一下测试")` 有草稿，`offersSend("testing")` 为真；同一个 `submit` 的停止路径在同一个构建里是通的（`stopGoesToItsOwnAddress` 通过），说明 `foreground`/`reachable`/`inFlight` 都没问题。
- 拦在 `ChatModel.submit` 里「新助手此刻没有发送模式就不发」那一段：它读的是进程全局的 `AgentCatalogSnapshot.current` 的说明书再收窄。Swift Testing 并行跑测试，别的用例的 AppModel（演示里没开假助手，说明书只有三家）会把 `.current` 换成没有 `testing` 的快照；`caps("testing")` 于是落到「未知助手的默认能力」（`send_modes` 为空），`submit` 设一句「这个对话现在不能从手机发消息」就返回了，请求一条都没发。App 里通常只有一个 AppModel，所以用户不容易碰上，但按 3.4「`capabilities_now` 说了算」，发送就不该看那个全局。
- 改法（代码）：`ChatModel.submit` 的发送模式改为读**这个对话自己的状态**——`capabilities_now.send_modes`（电脑给的是完整的一套，docs §八）；电脑没发 `capabilities_now`（老电脑）才回退到说明书。新增 `ChatModel.sendModes(of:app:)`，`submit` 的「不能发」「queue 是否可用」「intent 选哪个」三处都用它，不再读 `caps`。说明书只在回退时读。
- 测试这边补了两条：发送用例在 `send()` 前先断言 `control.capabilitiesNow["send_modes"]` 里有 `send`（把「状态说能发」写进断言）；新增 `aSendModeComesFromTheConversationState`（`capabilities_now` 说 `["send","steer"]` 就是这两个，说空就是空，与说明书无关）。

**这轮最可能编不过的地方**：`ChatModel.swift` 的 `static func sendModes(of:app:)` 与 `submit` 里 `modes` 的三处使用；`AgentUnifiedFlowTests.swift` 新增的 `aSendModeComesFromTheConversationState`；`AgentUnifiedTests.swift` 改过的 DeepSeek 断言（`deepseek["app"].isNull`）。

### 第三段

**结论**：3.5 做完了（推送 `n/k/m`、岛上可选的名字/颜色/图标、App 自己开岛时填进去、点新助手的通知能打开）；3.6 按用户意见**不做**（现在没有新助手 `usage` 为真，`UsageView` 三家原样）。另外做了三件用户点名的事：`TeleplyState` 不再读进程共用的 `AgentCatalogSnapshot.current`（`ChatModel` / `WorkspaceModel` / `NewChatJobs` 各持一份，`AppModel` 同步）；假助手的截图组（只跑它时用 `-Only "testAgentsLight testAgentsDark"`）；`apps/ios/README.md` 最前面加「0.9.0 草稿」。三家的岛和按钮没变。本机没有 Swift，**没编译、没跑测试**，等 Codemagic。

**改了的文件**（都在 `apps/ios/` 下；31 改 0 新）

- **catalog 归属（第一件事）**
  - `TeleplyModel/Interaction.swift`：`pendingCards(app:raw:catalog:)`、`genericCardTitle(_:app:assistant:catalog:)` 改成必须传 catalog（不再有默认值）。
  - `TeleplyState/ChatModel.swift`：新增 `catalog`（`@ObservationIgnored`，由 AppModel 同步）；控制态/回执/轮询间隔/`command`/`receipt`/`sendModes` 全用自己的；`refreshControl` 里的 Task 先把 catalog 取成本地值。
  - `TeleplyState/WorkspaceModel.swift`、`+New`、`+Uploads`：新增 `catalog`；`claudeChoiceCheck`、选项/回答/打开/上传/新建字段/`loadAgentOptions`/`isGenericNew` 都用它；`client.command`/`receipt`/`control`/`upload`/`agentOpen` 都显式传 catalog。
  - `TeleplyState/NewChatJobs.swift`：新增 `catalog`；`send`/`check`/`retry` 用它（check/retry 在 Task 前取成本地值），`agentCreate` 传 catalog。
  - `TeleplyState/AppModel.swift`、`AppModel+List.swift`：`syncCatalog` / `applyCatalog` / `clearAll` 里调新的 `shareCatalog()`，把 catalog 推给 conversation / workspace / jobs。`.current` 仍在这里赋值（App 的 Labels / Palette / Marks 默认参数要用），`TeleplyState` 里不再有读取。
  - `Teleply/Chat/QuestionCards.swift`、`Timeline.swift`、`GenericCards.swift`、`Chat/ConversationView.swift`、`Composer/Attachments.swift`：调 `pendingCards`/`inlineCards`/`genericCardTitle` 和 `params.max_images` 时传 `model.catalog`；`Timeline` 的卡片缓存也把 catalog 算进去（catalog 到了会重画）。
- **3.5 通知和岛**
  - `TeleplyModel/Push.swift`：`PushTarget` 加可选 `sourceName` / `tint` / `markKey`，从通知 `teleply` 的 `n` / `k` / `m` 读；trim、限制 60 / 32 / 120、空字符串当没有（和 relay_push.py 的 `_clean_meta` 一致）；url 形式不带；老字段与相等判断不变。
  - `TeleplyState/PushModel.swift`：`push.meta`（按助手 id 记住最近一条通知的 n/k/m）；`AppModel+Push.openNotification` 写入。
  - `TeleplyIsland/IslandState.swift`：`IslandPeer`、`IslandIdentity` 加可选 `sourceName` / `tint` / `markKey`（Codable，缺省 nil，老数据/老推送照常解码）。
  - `Shared/IslandAttributes.swift`：加可选 `sourceName` / `tint` / `markKey`，`init` 和 `identity` 双向带着；老字段一个没动。
  - `TeleplyIsland/IslandWords.swift`：`appName(_:name:)`、`title(peer:)` 用 `peer.sourceName`、`accessibility(name:)`。
  - `TeleplyIslandWidget/IslandViews.swift`：`IslandPalette.source(_:tint:)`（`#RRGGBB` / `#AARRGGBB` 解析）、`IslandMark(app:tint:markKey:)`；PeerRow / LockScreenCard / SmallCard / Minimal 都带上。`IslandWidgets.swift`：VoiceOver 和 keyline 带名字/颜色。
  - `TeleplyState/AppModel+Island.swift`：`islandSendStarted` / `islandNewChatStarted` 给新助手那一行填 catalog 的名字、深色和图标 key；新 `islandSource` 先看 catalog，没有再退回 `push.meta`；三家返回 nil，岛一点不变。
  - `Teleply/Settings/IslandPreviewPage.swift`：预览行的空标题也用 `peer.sourceName`。
- **截图**：`TeleplyUITests/ScreenshotTour.swift` 加 `testAgentsLight` / `testAgentsDark`（只在带 `-TeleplyDemoAgents` 启动时跑）：列表里的测试助手、它的对话（带通用卡片）、新建面板选中测试助手。原有各组一行没改。
- **测试**：`AgentUnifiedFlowTests`（两个 AppModel 同时进示例电脑，各自的发送/新建/上传不受对方 catalog 影响）；`PushTests`（`n/k/m` 读法与空值、点新助手的通知打开它的对话、meta 被记住）；`IslandFlowTests`（新助手的岛行有名字/颜色/图标，Codex 的没有；标题用名字；没名字时照旧）；`InteractionTests` / `PendingChoiceTests` / `AgentUnifiedTests`（调用处补 catalog 参数，期望值没改）。
- **README**：`apps/ios/README.md` 最前面加「0.9.0 草稿：iOS 按说明书显示助手」（改了什么、Codemagic 构建号和结果、「留给你在真机上验」清单）。`project.yml` 没动。

**自己怎么核对的**

1. 对着 `git show 0b3f8d7:relay_push.py`：`teleply_payload` 的 `n/k/m` 只在非空时带、limit 60/32/120、`_clean_meta` 的 trim；岛的 start attributes 只有 `device/app/chat/computer/title`（所以新字段在远端启动时是 nil，老推送照样解码）；`aggregate()` 的 peer 只有 app/chat/title/state/since/turn/ended/step（没有名字/颜色）。
2. 设计 3.5、3.7 和本文第 5 节：可选字段、三家不变、新助手从说明书填、点通知能打开。
3. `.current` 审计：`grep AgentCatalogSnapshot.current TeleplyCore/Sources/TeleplyState` 只剩 3 处赋值；`TeleplyState` 里所有 `client.control/command/receipt/upload/agentCreate/agentOpen` 都显式传 catalog；`pendingCards`/`genericCardTitle` 已无默认参数，调用处全补齐。
4. 三家不变：`islandSource` 对 `legacy` 返回 nil，`IslandWords`/`IslandPalette`/`IslandMark` 在 nil 时与改动前同一条分支；新增测试里也断言了 Codex 的岛行三个字段都是 nil。
5. 结构检查：30 个 Swift 文件括号/引号配对 0 问题，原始字符串扫描 0 问题，22 个原始字符串 JSON 字面量都能解析；四个被脚本改过的测试文件已统一回 LF。

**最可能编不过的地方**

- `TeleplyCore/Sources/TeleplyState/ChatModel.swift:112`（catalog 属性）、`:325`（`refreshControl` 里先取本地 catalog）、`:222/304/327/613/659/755/767`（调用参数）、`:574`（`sendModes(of:app:catalog:)`）。
- `TeleplyState/WorkspaceModel.swift:104`（catalog 属性）、`:13`（`claudeChoiceCheck` 签名）、`:489/510/585/590/664` 附近（action / checkAction / openOnComputer 的本地捕获与参数）。
- `TeleplyState/NewChatJobs.swift:34`（catalog 属性）、`:116`（`agentCreate` 参数）、`:157/235`（Task 前取本地 catalog）。
- `TeleplyState/AppModel+List.swift:225-295`（`shareCatalog` 与三处调用）、`AppModel.swift:409`。
- `TeleplyModel/Interaction.swift:23/76`（新签名）与 App 的 `QuestionCards.swift:38/575`、`Timeline.swift:130/145/152`、`GenericCards.swift:28`。
- `TeleplyModel/Push.swift:11-70`（可选字段、`init?` 里调 `Self.cleanMeta`）。
- `TeleplyIsland/IslandState.swift`（IslandPeer / IslandIdentity 的新字段和 init）、`Shared/IslandAttributes.swift`（init / identity）。
- `TeleplyIsland/IslandWords.swift:25`（appName）、`:213`（accessibility 的 `shown`）、`:291`（title）。
- `TeleplyIslandWidget/IslandViews.swift:24`（source）、`:39`（hex 解析）、`:60`（IslandMark 的新参数）、`:99`（`asset(for:)` 的 `guard let`）、`:189/205/319/375/386/410/435/452/580/597`；`IslandWidgets.swift:27/58/63`。
- `TeleplyState/AppModel+Island.swift:84/100/108`（peer 的可选字段、`islandSource` 的元组）。
- `TeleplyUITests/ScreenshotTour.swift` 的新方法/`agentsShots`（`segmentedControls` 的写法）。
- 测试：`AgentUnifiedFlowTests.twoModelsKeepTheirOwnCatalogsAndFlows`（两个 model 的时序）、`PushTests`（`PushTarget` 的新参数）、`IslandFlowTests`（`IslandPeer` 的新参数、`#A78BFA`）。

**没做的 / 要用户看的**

- **3.6 用量没做**（用户说这次不做）：没有新助手 `usage` 为真，`UsageView` 三家原样。
- 中转推来的岛行不带名字/颜色：`relay_push.py` 的 `content-state.peers` 没有这些字段，所以新助手的名字/颜色只在这个电话号码自己开的岛、自己加的行上出现；中转下一次推送把列表换成它自己的行后，那一行又会回到 id 和通用灰。要让它一直带着，得电脑端把 `app_name`/`app_color`/`app_icon` 放进岛的内容里（这次没动中转和电脑端）。点通知打开对话不受影响。
- `-TeleplyDemoAgents` 打开演示时，`ScreenshotTour` 的原有各组不会多出假助手（它们不带这个参数）；新组用 `codemagic.ps1 -Mode shots -Only "testAgentsLight testAgentsDark"` 单独跑。
- README 的 0.9.0 草稿排在最前面；合并时语音修复那一节也在最前面，冲突由用户合。
- 没推送、没跑 Codemagic、没碰 TestFlight/后台/中转/密钥；版本号没动（`project.yml` 仍是 0.8.0）。

