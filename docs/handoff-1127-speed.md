# 11-27 提速：手机发给 Codex 的消息更快进去

这份文件是三路 DeepSeek 同时开工的共同依据：线 A 电脑，线 B iPhone，线 C 安卓。第 1 节是查到的事实，第 2 节是这次要改的五处，第 3 到 5 节分别写给三路，第 6 节是手机和电脑之间新增的约定，第 7 节是规矩，第 8 节由各路填写结果。

版本由合并的人统一改，各路都不改版本号。下一版：Windows dev.59，iOS 0.9.3，安卓 1.0.13。

## 1 查到的事实（11-27 上午同一个 Codex 对话的 6 条消息）

| 第几条 | 电脑收到 | 怎么发的 | 进到 Codex 记录 | 用时 |
|---|---|---|---|---|
| 1 | 7:41:11 | 新开一轮 | 7:41:18 | 7 秒 |
| 2 | 7:43:43 | 排队，2 秒后点「立即补充」 | 7:43:48 | 5 秒 |
| 3 | 7:44:06 | 排队，3 秒后点「立即补充」 | 7:44:24 | 18 秒 |
| 4 | 7:52:35 | 新开一轮 | 7:52:38 | 3 秒 |
| 5 | 7:53:06 | 排队，10 秒后点「立即补充」 | 7:54:47 | 1 分 41 秒 |
| 6 | 7:53:27 | 排队，4 秒后点「立即补充」 | 7:54:47 | 1 分 20 秒 |

时间来源：
- 电脑的送达记录 `delivery.sqlite`；
- 日志 `codex request=… elapsed_ms=…`；
- 送达证据里的 `evidence.time`；
- Codex 记录文件里各条目的时间。

每一段花在哪：
- **新开一轮**：电脑里 `send_message_to_thread` 一次调用花 3.2 到 4.5 秒，大部分是 Codex 自己开这一轮（`thread_settings_applied`、`task_started`）。电脑在 `_begin` 之前还先调了一次 `read_thread`，这一段现在没有计时。
- **插话**：Codex 只在两步之间收插话，也就是一条命令跑完、或者一段修改写完之后。
  - 第 2 条：等一条快结束的命令，2 秒多；
  - 第 3 条：Codex 先想了 8 秒，又跑了一条 6 秒的命令，共 15 秒；
  - 第 5、6 条：Codex 从 7:53:37 起，花了 67 秒生成一大段代码修改，7:54:45 改完，两条插话 7:54:47 一起进去。
- **排队再「立即补充」**：Codex 在干活时，两部手机的发送键默认都是「发送并排队」（iPhone `ComposerView.swift` 第 278 行、安卓 `ComposerUi.kt` 第 391 行）。用户每次都要再点「立即补充」，多了 2 到 10 秒手动时间，外加一次请求；「立即补充」这次请求本身最慢 3.8 秒。
- **「已送达」晚了**：第 5、6 条 7:54:47 就进了 Codex，电脑 8:00:40 才标「已送达」。原因是 `codex_apptools.reconcile_deliveries` 只在有人读这个对话的状态时才跑。
- **手机到电脑这一段**：电脑只记收到的时间，手机发出的时间没有记录，算不出来。电脑时钟以前还发现过比标准时间慢约 19 秒，所以不能拿两边的钟直接相减。

**改不了的**：Codex 在「想」和「写」的时候，没有办法让它中途接插话。电脑这边的「停止」走钩子：要等它下一次调用工具才生效，只能结束正在跑的命令（`codex_hooks.request_stop` → `kill_running_command`）。Codex 电脑版自己的停止按钮没有开放给我们。

## 2 这次要改的五处

| 编号 | 做什么 | 哪几路 |
|---|---|---|
| S1 | Codex（以及支持插话的助手）正在干活时，发送键直接**插话**；按住发送键才「排队」 | B、C |
| S2 | Codex 正在跑命令、插话在等时，给「结束这条命令，马上插话」：只结束这条命令，不停这一轮；命令的结果作废，插话马上进去 | A、B、C |
| S3 | 测出手机到电脑这一段：手机记来回总时间，电脑回报自己处理用了多久，两者相减就是网络和中转的时间；电脑把每次的数字记进日志 | A、B、C |
| S4 | 电脑发送前后每一步计时；能省的 `read_thread` 省掉 | A |
| S5 | Codex 一收到插话，电脑就标「已送达」；手机在插话等待时显示「等 Codex 做完这一步再插进去 · 已等 N 秒」 | A、B、C |

## 3 线 A 电脑

分支 `pc59`，工作树 `D:\Personal\agent_remote_lanes\pc59`，起点 agent-registry 64d5d9b（dev.58）。

### 3.1 S4：每一步计时，省掉多余的 `read_thread`

1. `codex_apptools.AppToolsBridge.send`、`queue_action`、`drain_if_idle` 里，给每次管道调用计时：`read_thread`、`send_message_to_thread`、读设置。每次请求在日志写一行，只写数字：
   `codex timing request=<编号前 8 位> read_ms=… send_ms=… other_ms=… total_ms=…`
2. 发送前的 `read_thread` 只用来判断「在不在跑」。改成：这个对话最近 3 秒内已经从管道读过状态（`_status_cache` 或者别的现成缓存），并且记录文件之后没有变化，就直接用这个结果，不再调一次。拿不准的时候照旧调。
   `intent == "queue"` 时，「在不在跑」决定排不排队，必须是可靠的结果。宁可多调一次，也不能该排队的没排队。
3. 不改任何发送行为。测试用假的管道客户端，数清每种情况调了几次管道，并检查计时日志行的格式。

### 3.2 S5：「已送达」马上标上

1. 有「已接收、还没送达证据」的发送（`deliveries` 里状态是 accepted，`result.evidence` 里没有 `message_id`）时，这个对话的记录文件一变，就跑一次 `reconcile_deliveries(tid)`。用现成的监视或轮询来触发，不要为每个对话开新线程。没有待确认的发送时什么也不做。
2. 15 分钟还没找到证据，就不再自动找，以后有人读状态时照旧找。
3. 测试：插话被接收后，记录文件追加了这条消息，下一次记录文件变化时就标上「已送达」，不需要有人读状态。

### 3.3 S2：只结束正在跑的命令

1. 判断「正在跑命令」：记录文件尾部最后一个命令调用（`exec` 等会跑 `pwsh.exe` 的那种）还没有对应的输出。用 `latest_turn_state` 现有的读尾部的办法。`_active_commands[tid]` 只在 PreToolUse 时写、到 Stop 才清，不能单独用来判断，但杀进程时要用它里面的命令文字。
2. Codex 的状态里加一个字段 `command`（第 6.3 节）。
3. 新接口 `POST /api/agents/codex/kill-command`，老地址 `/api/codex/kill-command` 也接上：
   - 只调 `kill_running_command`，**不**设停止标记，这一轮继续，插话在命令结束后马上进去；
   - 钩子没被信任、没有正在跑的命令、或者不是完全访问模式（沙盒里的命令不能杀，`kill_running_command` 本来就不碰沙盒账号），都返回 409 和一句人话，`not_submitted: true`。
   - 返回 `{ok, killed, killed_pids, text, server_ms}`。
4. 能力表：Codex 的 `capabilities_now` 加 `kill_command: bool`。钩子被信任时为 true，否则写明原因放进 notes。
5. 测试用假的进程列表和假的钩子：有命令在跑时只杀那一个，不设停止标记；没在跑、沙盒、钩子不信任，三种情况各自拒绝。

### 3.4 S3：电脑这一半

1. Codex 的 `send`、`queue-action`、`kill-command` 回答里都加 `server_ms`：从这个请求进到处理函数，到回答写出之前，电脑用了多少毫秒（第 6.1 节）。Claude、DeepSeek、Antigravity 的发送回答也加上；做不到的写明原因。
2. 收到手机带来的 `client_prev`（第 6.2 节）时，日志写一行，只写数字：
   `phone timing request=<上一条编号前 8 位> roundtrip_ms=… server_ms=… network_ms=…`
   `network_ms` = `roundtrip_ms` − `server_ms`，小于 0 时记 0。不拿手机的钟做任何判断。
3. 测试：回答里有 `server_ms`；带 `client_prev` 的请求会写日志行，内容是数字，没有消息文字。

### 3.5 线 A 可以改的文件

`codex_apptools.py`、`codex_hooks.py`（只加只杀命令的方法）、`agents/codex.py`（接口、能力、状态字段）、`agents/claude.py`、`agents/deepseek.py`、`agents/antigravity.py`（只加 `server_ms`）、`remote.py`（只在必要时接路由）、`tests/` 下相关测试。不改版本号和更新说明。

## 4 线 B iPhone

分支 `ios-093`，工作树 `D:\Personal\agent_remote_lanes\ios-093`，起点 ipad-adapt 7ae9f5a（0.9.2）。

### 4.1 S1：干活时直接插话

1. `ComposerView.swift` 第 278 行：`queue = chat.control.running && chat.control.queueAvailable && model.offersQueue(app)`。改成：运行中**点**发送键就是插话（`send(queue: false)`，老 Codex 路线走 `intent: "steer"`，新助手照它的 `send_modes` 用插话那一种）。
2. 运行中**按住**发送键（`contextMenu` 或长按手势）出一个菜单：「排队到这一轮结束后再发」，选了才 `send(queue: true)`。
3. 发送键的无障碍标签：运行中叫「发送（插话）」，长按的提示是「按住可排队」。不运行时完全照旧。
4. 只在助手同时支持插话和排队时这样做；只支持一种的，照它支持的那一种。
5. Claude 也一样，前提是它的能力表里两种都有。
6. 已经排队的消息，队列条和「立即补充」照旧。

### 4.2 S5：插话等待时说清楚在等什么

1. 一条插话被电脑接收（标签「已接收」，`intent` 是 steer）、还没「已送达」时，在它下面（或输入框上面那条状态栏里）显示一行灰字：「等 Codex 做完这一步再插进去 · 已等 N 秒」。N 用手机自己的时间，从收到电脑回答那一刻起算，每秒更新。变成「已送达」或被移除时，这行字消失。
2. 字里的「Codex」换成当前助手的名字。

### 4.3 S2：结束命令，马上插话

1. 上面那行字出现，并且 Codex 状态里 `command.running && command.can_kill`、能力表 `kill_command` 为真时，同一行多一个按钮「结束这条命令，马上插话」。
2. 点了先弹确认：「Codex 正在跑的这条命令会被结束，它的结果作废；你的话会马上交给 Codex。」确认后调 `kill-command`（第 6.4 节）。
3. 结果：
   - 成功：显示一句「已结束命令，正在插话…」，之后照常等「已送达」；
   - 失败：显示电脑给的原因。
4. 老电脑（状态里没有 `command`）不显示这个按钮。

### 4.4 S3：手机这一半

1. 每次发送、「立即补充」、`kill-command` 都记来回总时间：从发出请求到收到回答，用 `ContinuousClock`。回答里有 `server_ms` 时，算出「网络和中转」= 来回 − `server_ms`。
2. 下一次发送时，把上一次的数字放进 `client_prev`。另外每次发送都带 `client_sent_ms`，这只是给日志参考。
3. 现有的速度提示（`SpeedToast`、`timed("消息提交", …)`）多显示一段，比如「手机→电脑 0.6 秒 · 电脑处理 3.2 秒」。别让它比现在更常弹出。

### 4.5 线 B 可以改的文件

`Teleply/Composer/ComposerView.swift`、`Teleply/Chat/Timeline.swift`（只加等待那一行）、`TeleplyState/ChatModel*.swift`、`TeleplyModel/Relay.swift`、`TeleplyModel/ChatCore.swift`、和速度提示有关的文件、演示和测试文件。

测试：
- 运行中点发送是插话、长按选排队是排队；
- 等待字样的出现和消失；
- `kill-command` 按钮出现的条件；
- `client_prev` 和网络时间的计算。

## 5 线 C 安卓

分支 `and-1013`，工作树 `D:\Personal\agent_remote_lanes\and-1013`，起点 and-1012 4889957（1.0.12）。和线 B 做同样的四件事（第 4.1 到 4.4 节），文字一模一样。

安卓的位置：
- `ComposerUi.kt` 第 391 行（`queue = chat.control.running && …`）和第 467 行（`SendButton`）；
- 长按用 `combinedClickable` 或现成的菜单组件；
- `ChatController.kt` 的 `send` / `dispatch` / `promote`；
- `RelayApi.kt`；
- 等待字样放在 `ChatUi.kt` 的用户气泡下面，或 `ComposerUi.kt` 的状态行。

可以改的文件：上面这些、`Models.kt`（只加字段）、`FixtureApi.kt` 和新建的演示文件、测试文件。

测试：同线 B。用 `testDebugUnitTest` 和 `assembleDebug`；模拟器可以开（这一批只有这一路用安卓模拟器），用完关掉。

## 6 手机和电脑之间新增的约定

### 6.1 `server_ms`

发送、`queue-action`、`kill-command` 的回答里多一个整数 `server_ms`：电脑处理这个请求用了多少毫秒。老电脑没有这个字段，手机就不算网络时间。

### 6.2 `client_sent_ms` 和 `client_prev`

发送请求里可以多带两个字段：
- `client_sent_ms`：手机按下发送时的时间，用手机自己的钟，毫秒；
- `client_prev`：上一次请求的数字，形如 `{"request_id": "...", "roundtrip_ms": 820, "server_ms": 310}`。

电脑只把它们写进日志，不用来做任何判断，也不拿去和自己的钟比。老电脑收到这两个字段会忽略。

**注意**：电脑按「请求体的指纹」去重（`codex_control._begin`）。重发时，必须带原来那次的请求体。手机在「重发」时，要把 `client_sent_ms` 和 `client_prev` 从请求体里去掉，或者原样保留第一次的值，不能换成新值，否则同一个编号会被当成别的内容。最简单的做法：首次发送时就把这两个字段存进副本，重发原样发出。

### 6.3 Codex 状态里的 `command`

```json
"command": {"running": true, "since_ms": 1764200000000, "can_kill": true}
```

没有正在跑的命令时为 `null`。`since_ms` 是电脑的钟，手机只拿它来和同一台电脑的其他时间比，不和手机的钟比。`can_kill` 为真的条件：钩子被信任，并且这条命令是在完全访问模式下跑的。

### 6.4 `kill-command`

`POST /api/agents/codex/kill-command`，老地址 `/api/codex/kill-command` 也接上。请求 `{"id": "<对话>", "turn_id": "<可选>"}`。只结束正在跑的命令，不停这一轮。拒绝时返回 409、一句人话，以及 `not_submitted: true`。

## 7 规矩

照 `docs/handoff-1126-fixes.md` 第 9 节的共同规矩做，再加一条：**绝不操作正在运行的 Codex、Claude 桌面程序和正在运行的遥应电脑端，也不读真实的 Codex 记录和送达记录。**测试全部用假的管道、假的记录文件、假的进程列表。真机上的计时，由审核的人装好以后看日志。

## 8 结果（各路只改自己那一小节）

### 8.1 线 A 电脑

（待填）

### 8.2 线 B iPhone

**结论**：第 4.1 到 4.4 节按设计做完，演示和测试都加了。这台电脑没有 Swift，**没编译、没跑测试、没跑截图巡览**，等 Codemagic 编译和跑测试。

**S1（4.1）：干活时点就是插话，按住才排队**

- `ChatModel.sendKey`（新，`SendKeyModes`）：运行中时算出两件事——能不能插话（`steer` 在这份对话此刻的 `send_modes` 里，新助手读 `capabilities_now`，三家读能力表）、能不能排队（状态 `queue_available` 且能力表 `queue`；新助手按 `send_modes` 里的 `queue`，和 `submit` 的同一条规矩）。
- 发送键：运行中**点**是 `send(queue: false)`（老 Codex/DeepSeek 走 `intent: "steer"` 加 `expected_turn`，新助手走它 `send_modes` 的插话）；两种都行时挂 `contextMenu`，只有「排队到这一轮结束后再发」这一项，选了才 `send(queue: true)`；只支持一种的，点和按住都是那一种。
- 无障碍：运行中标签「发送（插话）」，两种都行时提示「按住可排队」；不运行时标签和菜单与原来逐字一样。⌘↩ 仍是点，也就是插话。
- Claude 能力表里没有 `queue`（`send_modes` 只有 `send`、`steer`），所以它只有插话、没有菜单，符合 4.1.5。已经排队的消息、队列条、「立即补充」一点没动（4.1.6）。

**S5（4.2）：等的时候说清在等什么**

- 一行灰字放在**输入框上面**（设计允许的第二种位置）：`等 Codex 做完这一步再插进去 · 已等 N 秒`，名字用当前助手（`Labels.sourceName`），N 用手机自己的钟、从收到电脑回答那一刻起算，`TimelineView` 每秒重画。
- 判断是纯函数 `steerWaiting`：`action == "send"`、标签「已接收」、请求体的 `intent == "steer"`。排队（已排队）、执行计划、已送达、已移除都不算。
- 起算时刻记在 `ChatModel.steerSince`（按请求编号）：标签刚变「已接收」时记一次；已经是「已接收」的（重启后、或核对只改了备注）沿用，没有就退回这条副本的发送时刻。
- **每 3 秒问一次回执**（审后补的）：有一条插话在等时，`ChatModel.watchSteerWait` 每 3 秒按 `reconcile` 现成的规则读一次这条的回执。电脑把送达记录改成带 `conversation_record` 证据的 accepted 之后，标签变「已送达」，这行字消失，轮询也停。只问最新那条在等的；只在这个对话和手机都在前台时问；这一轮结束、或者等满 15 分钟就停；回执出错不报错，下一个 3 秒再问。这一行仍然要求 `control.running`，作为回合结束的兜底。本地示例不轮询（演示的回执永远没有证据），演示里那行字照常显示。

**S2（4.3）：结束这条命令，马上插话**

- 同一行多一个按钮「结束这条命令，马上插话」，条件是那行字在、`command.running && command.can_kill`、并且能力表 `kill_command` 为真（`Control.canKillCommand`，纯判断）。老电脑的状态里没有 `command`，按钮不出现（4.3.4）。
- 点了先弹确认：「Codex 正在跑的这条命令会被结束，它的结果作废；你的话会马上交给 Codex。」确认后 `POST /api/agents/codex/kill-command`，请求体 `{"id","turn_id"}`（第 6.4 节）。
- 成功显示「已结束命令，正在插话…」几秒，然后照常等「已送达」；失败显示电脑给的那句话（409 的 `error`）。按钮在请求期间不能连点（`ChatModel.killing`）。请求完再读一次状态：命令没了，按钮跟着消失，这一轮和那行字都还在。
- `kill_command` 的「能力表」只能读状态的 `capabilities_now`：`AgentCatalog.swift` 不在第 4.5 节的清单里，不能给 `AgentCapabilities` 加字段。Codex 本来就按第 3.3 节第 4 点把它放进 `capabilities_now`。

**S3（4.4）：手机这一半**

- 发送、「立即补充」、`kill-command` 都用 `ContinuousClock` 记来回，回答里有 `server_ms` 时算「网络和中转 = 来回 − server_ms」（小于 0 记 0，`PhoneTiming`）。
- 每次发送带 `client_sent_ms`（手机钟，毫秒），并把**上一次**请求的 `request_id`、`roundtrip_ms`、`server_ms` 放进 `client_prev`。上一次的回答没有 `server_ms`（老电脑）时**不带** `client_prev`：不带就不会让电脑把整个来回记成网络时间。
- **重发（第 6.2 节）**：两个字段写在副本的请求体里，不是 `SendNote` 里的备注，所以「重发」原样发出第一次的值，一个字节都不换（`resend` 只去掉备注），电脑按请求体指纹去重不会把它当成另一次。测试里有一条专门验这个。
- 「换掉电脑上的「…」再发」（Claude，`resendReplacing`）是新请求编号，所以换成新的 `client_sent_ms` 和当前的 `client_prev`，不继承被退回那次的。
- 速度提示：`timed("消息提交", …)` 的结果多一段，变成 `消息提交：0.9 秒 · 请求完成 · 手机→电脑 0.6 秒 · 电脑处理 3.2 秒`；老电脑没有 `server_ms` 时一个字都不加。弹出的次数和现在一样（「立即补充」「结束命令」只记数字，不弹）。
- **`SpeedLog.add` 改了一行**（`Teleply/Settings/SettingsView.swift`，第 4.5 节允许的「和速度提示有关的文件」）：提示条是不是成功原来按结果**整串相等**判断，现在结果后面多了那一段，会变成红的，所以改成按前几个字（`hasPrefix`）判断。

**改了哪些文件**

- `TeleplyCore/Sources/TeleplyModel/ChatCore.swift`：`RunningCommand`、`Control.command`（新存储属性，`Equatable` 一起比）、`Control.canKillCommand`、`SendKeyModes`、`steerWaiting`、`sendIntent`、`steerWaitingText`、`killCommandConfirmText`、`killCommandStartedText`、`PhoneTiming`、`milliseconds`、`phoneTiming`、`clientPrev`、`timingWords`；文件头补了 `import Foundation`（原来没有，新代码用 `Data` 和 `String(format:)`）。
- `TeleplyCore/Sources/TeleplyModel/Relay.swift`：`killCommand(device:app:chat:turn:)`，打到 `/api/agents/<id>/kill-command`。
- `TeleplyCore/Sources/TeleplyState/ChatModel.swift`：`sendKey`、`steerWait`、`steerWaitSeconds`、`watchSteerWait`（3 秒回执轮询，`steerPoll`/`steerPollGeneration`）、`killCommand()`、`noteKill`、`killing`、`killNote`、`lastTiming`、`steerSince`；`submit` 带 `client_sent_ms`/`client_prev`；`dispatch` 记来回并给提示条加一段；`save` 记/清起算时刻并在插话被收下时开始轮询；`run` 在进对话时开始；`bind` 在离开或退到后台时停；`resendReplacing` 换新数字。
- `TeleplyCore/Sources/TeleplyState/ChatModel+SteerDemo.swift`（新建）：`-TeleplyDemoSteer` 时给 `插话等待示例` 放一条「已接收」的插话副本。
- `TeleplyCore/Sources/TeleplyDemo/DemoSteer.swift`（新建）：那一条列表行、那份记录、那个开关。
- `TeleplyCore/Sources/TeleplyDemo/DemoWorld.swift`：`steerDemo`（公开 init 的默认值是开关）、那个对话的状态（`running`、`command`、`capabilities_now.kill_command`）、`killCommand`、列表多一行、记录走 `SteerDemo.messages`。
- `TeleplyCore/Sources/TeleplyDemo/DemoTransport.swift`：`/api/agents/codex/kill-command` 和老的 `/api/codex/kill-command` 两条都接上；记录带开关。
- `Teleply/Composer/ComposerView.swift`：`SteerWaitBar`（灰字、秒数、按钮、确认、结果一句话）、发送键改成点/按住两种、无障碍标签和提示。
- `Teleply/Settings/SettingsView.swift`：`SpeedLog.add` 的成功判断改 `hasPrefix`（见上）。
- 测试：`TeleplyCoreTests/SteerSpeedTests.swift`（新建，13 项）。
- **没动**：`Teleply/Chat/Timeline.swift`、`ConversationView.swift`（灰字放在输入框上面，这两处都不用改）、`ChatSheets.swift`、`AppModel*.swift`、`AgentCatalog.swift`、`TeleplyApp.swift`、`LaunchOptions.swift`、README 和版本号。

**测试加了哪些**

- 运行中点发送是插话、按住那一条是排队：同一条 `/api/codex/send` 上，第一条 `intent=steer` 且有 `expected_turn`，第二条 `intent=queue`，副本标签「已排队」；`sendKey` 三种情况（两种都行、只有一种、空闲）的 `tapQueues`/`holdQueues`。
- 等待字样：`steerWaiting` 对七种副本（已接收/已排队/已送达/已移除/intent auto/intent queue/queue-action）的判断；`steerWaitingText` 的名字和秒数（含负数记 0）；模型上从 0 秒数到 3 秒、移除后和回合结束后消失、`sendKey` 回到全否。
- 3 秒回执轮询（审后补的）：回执先答 accepted（`app_tools_ack`）、再答 accepted（`conversation_record`），标签变「已送达」、`steerWait` 变空、问过两次（一次只问一条），之后再怎么让出都不再问；也验了问的间隔是 3 秒。
- `kill-command` 按钮的条件：能杀、不能杀、命令没在跑、状态里没有 `command`（老电脑）、没有 `kill_command`、`kill_command` 为假，共六种；确认那句的原话。模型上：请求打到 `/api/agents/codex/kill-command`、带 `id` 和 `turn_id`、成功后说「已结束命令，正在插话…」且按钮消失、这一轮还在；409 时显示电脑那句话、命令没被杀、按钮还在。
- `client_prev` 和网络时间：820 减 310 等于 510、「0.5 秒 / 0.3 秒」的说法、电脑比来回还长时记 0、老电脑没有 `server_ms` 时不算也不带 `client_prev`；模型上第一次发送带 `client_sent_ms` 不带 `client_prev`，第二次带上第一次的请求编号和 `server_ms`；「重发」原样带第一次的 `client_sent_ms`/`client_prev`。
- 演示：`DemoWorld(steerDemo: true)` 的那个对话状态有 `command` 和 `kill_command`、列表行只在开关打开时出现、`kill-command` 打过去之后命令没了而这一轮还在、别的对话被 409 拒。

**演示**：启动参数 `-TeleplyDemoSteer`（只在 DEBUG 有效，默认关）。打开本地示例 → 列表里多一行「插话等待示例」：这一轮在跑一条命令，输入框上方是「等 Codex 做完这一步再插进去 · 已等 12 秒」（会自己往上数）和「结束这条命令，马上插话」；点按钮、确认之后显示「已结束命令，正在插话…」，按钮消失，这一轮继续。关掉开关时列表、记录和截图组都与原来一样（现有截图组没改）。

**没做 / 没验**

- 这台电脑没有 Swift：**没编译、没跑测试、没跑截图巡览**。只按类型和可选值逐处静态核对，括号配平，测试里新加的原始字符串都查过没有 `"#`。
- 真机上没验：按住发送键的菜单在玻璃输入卡上好不好按、VoiceOver 的「按住可排队」、灰字每秒重画的代价、确认框在底部栏里的样子。
- 3 秒轮询在真机上的请求量和耗电没量过：一条在等的插话最多每 3 秒一次回执、最多 15 分钟（约 300 次），一条进去就停。
- Claude 的「立即补充」走的是它桌面上的令牌（`workspace.action("claude/choose")`，`WorkspaceModel.swift` 不在第 4.5 节的可改文件里），这次没给它计时；Codex/DeepSeek 的 `promote` 计时了。
- 演示里的发送回答没有 `server_ms`，所以在演示里看不到提示条那一段（真电脑 dev.59 才有）；`client_sent_ms`/`client_prev` 在演示里照发，不显示。
- `kill_command` 只从 `capabilities_now` 读：以后要给新助手用，得在 `AgentCapabilities` 里加字段（不在这次的可改文件里）。
- 新加的界面文字（「结束这条命令，马上插话」「等 … 做完这一步再插进去 · 已等 N 秒」「已结束命令，正在插话…」「排队到这一轮结束后再发」「按住可排队」等）没进 `Localizable.xcstrings`（不在可改列表里），英文界面会显示中文。

**最担心编不过的几处**

1. `ComposerView.sendButton`：`@ViewBuilder` 方法里先 `let button = Button { … } label: …` 加一串修饰符，再 `if steers && queues { button.contextMenu { … } } else { button }` —— 不透明的 `some View` 存进 `let` 再分支，能不能编。
2. `SteerWaitBar`：`TimelineView(.periodic(from: Self.start, by: 1))` 里的 `Date`、`Text(verbatim:)`、`.alert(_:isPresented:) { } message: { }` 挂在底部栏的视图上。
3. `Control` 多一个存储属性 `command`（自定义 init 加了末尾默认参数），`parseControl` 是唯一的生产调用方；`RunningCommand` 有两个 init（带标签的和 `_ json:`），这次没有把构造器当函数引用（`compactMap(SomeType.init)` 的坑）。
4. `milliseconds(_:)` 用 `Duration.components`（`attoseconds / 1e15`）算毫秒，以及 `String(format:)`；`TeleplyModel` 原来没有 `import Foundation`。
5. `ChatModel.killCommand()` 的 `Task { [weak self] }`：跨 `await` 之后写 `killNote`/`killing`、再 `take(fresh)`，在 `TeleplyState` 默认 MainActor 隔离下能不能直接编。
6. 测试：`SteerComputer` 的 `(state: String, missing: Bool)` 元组参数和默认值、复用 `Mutexed`/`IdlePacer`/`temporaryFolder`/`queryValue`、`DemoTransport.computer` 的位置参数、`world.control` 的可访问性。
7. `DemoWorld` 是 `public`，公开 init 的默认参数引用了 `SteerDemo.on`，所以 `SteerDemo` 声明成了 `public`（`SendDemo` 是 internal，因为它没出现在公开签名里）。

### 8.3 线 C 安卓

（待填）
