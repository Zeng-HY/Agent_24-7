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

- `Push.swift:14/24`：catalog 里有就接受。推送 `teleply` 里的可选 `n`、`k`、`m` 读出来，存进 `IslandAttributes` 等处新加的**可选**字段（如 `sourceName`、`tint`、`markKey`），老字段不动。
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

### 第二段

### 第三段
