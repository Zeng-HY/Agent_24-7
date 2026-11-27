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

（待填）

### 8.3 线 C 安卓

（待填）
