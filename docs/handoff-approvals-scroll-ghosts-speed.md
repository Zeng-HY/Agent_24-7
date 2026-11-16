# 交接：Codex 批准到不了手机、读对话被拉回底部、Claude 旧消息淡色重影、打开对话慢（2026-11-16）

写给接手修复的 DeepSeek Harness 会话。四件事的原因都已查清，表里写明哪些读代码坐实、哪些实测过、哪些只是推断。你要做的是照第 4 节**分阶段**改代码、补测试、本地提交，每个阶段做完在第 9 节记结果，再做下一个。代码位置按 main 的 `2796020` 写，行号可能前后差几行。

---

## 0. 结论

| 编号 | 用户看到的 | 原因（一句话） | 状态 |
|---|---|---|---|
| 批-1 | Codex 在电脑上弹「允许一次 / 拒绝」时，手机上只有「正在处理」，这一轮一直卡着 | 电脑端只把 `item/tool/requestUserInput` 提问转给手机，批准请求被跳过（`codex_control.py:326` 的注释写明「从不在这里提供」）；也没有回答批准的通道（`call()` 只认 `VERSIONS` 里有的方法） | 读代码坐实；Codex 26.1106 的 app.asar 里找到了回答批准的方法 |
| 批-2 | 列表、推送、锁屏岛都不说「在等你」 | `activity.py` 只数提问和计划；`notify.py` 只看记录文件，而记录文件里根本不写批准；20 分钟没新行还会把这一轮当成过期丢掉 | 读代码坐实 |
| 批-3 | 可能：Codex 运行中，手机排队发的消息发不出去 | 26.1106 里 `thread-follower-set-queued-follow-ups-state` 似乎是第 3 版，代码写的是第 1 版 | 只读了 app.asar，没实测，**先核实再改** |
| 滚-1 | iPhone：DeepSeek 刷得快时往上翻不动，总被拉回最新处 | 「在底部」只按位置算（离底 24 点以内），不管手指在不在屏上；DeepSeek 每秒最多推 5 次画面，每次都 `scrollTo` 底部。往上拖的头几帧都在 24 点以内，就被拽回去了 | 读代码坐实 |
| 滚-2 | 安卓：大体对，几处漏洞 | 拖动状态要经过一次重组才生效；回到底部要精确到底才重新跟随；内容变短会自己重新钉住；恢复位置时强制不跟随 | 读代码坐实，部分推断 |
| 影-1 | Claude 对话底部出现自己以前发的淡色消息，再发一条、Claude 开始干活就消失 | 是 iPhone 自己存的「已发消息」，不是电脑端的排队清单。第一页没读成时，实时流的快照填满列表却没带「上面还有更早的」，手机的对照规则就失效，存着的已发消息全叠在底部；要等列表里出现一条更晚的用户消息才一起清掉 | 机制读代码坐实，用记录重放核对过时间线；哪一次请求失败没法坐实（手机没日志） |
| 影-2 | 同上，个别消息一直淡着 | 带引用、只发图片、超过 6000 字的消息，记录里的文字和手机发的不一样，永远对不上；标签「已移除」的也不跳过 | 读代码坐实 |
| 慢-1 | 点开对话要等 | 每页里 50%–86% 是手机根本不存的工具输出（`detail`、`result`，每条最多 16000 字） | 实测 |
| 慢-2 | 同上 | 电脑→中转→手机三段都不压缩 | 读代码坐实 |
| 慢-3 | DeepSeek 对话尤其慢、时快时慢 | 电脑端每 30 秒重新找一次 DeepSeek 的端口（起 PowerShell 和 netstat，1.7 秒），一切正常时也找，而且就在请求路上 | 实测 |
| 慢-4 | 大对话服务启动后第一次打开要 1–2 秒 | 每行 JSON 解析两次；Codex 最终回答的比对随数量平方增长；只缓存 8 个对话 | 实测 |

**做的顺序**：阶段一 Codex 批准 → 阶段二 滚动 → 阶段三 打开速度 → 阶段四 淡色重影。每个阶段单独提交。批-1 的电脑端先做，靠一个兼容字段，**已经发出去的手机版不用更新就能答批准**（见 4.1）。

---

## 1. 用户看到的现象（11-16，iPhone 和安卓都有）

- **批准**：Codex 桌面版（另一台电脑，Windows 用户 13770）弹出「终端」批准卡片：标题「压缩包解压遇到 Windows 长路径问题，是否允许改用官方安装器的 Git 稀疏下载方式完成同一安装?」，下面是要跑的命令，按钮「拒绝 Esc」「允许一次」（带下拉）。手机上这个对话只显示「正在处理 · 1 步」和「停止这一轮」，看不到卡片，只能回电脑上点。
- **滚动**：DeepSeek flash 出思考链很快，界面一直往底部追，用户没法往上看过程。用户要的是：打开对话停在最新处；往上翻看旧内容时，不要再被拉回最新输出。
- **淡色重影**：用户 11-15 在 Claude 对话「Source First 工作流顶层设计优化」里看到：Claude 最新输出下面，叠着自己以前发过的几条消息，颜色是淡的；再发新消息、Claude 开始干活，这几条就消失了。当晚用户重启了 Windows（电脑端 23:08 随之重启），还删了 %TEMP%，之后没再出现。
- **打开慢**：点开一个对话要等一会儿才出内容。

---

## 2. 证据（都只读，不要改、不要删）

### 2.1 Codex 批准请求长什么样（从这台电脑 Codex 26.1106.6628.0 的 app.asar 读的，没抓到实况）

- **怎么进状态**：Codex 把每个待处理的服务器请求放进对话状态的 `requests` 列表。电脑端从跟随快照和补丁里拿到它（`codex_control.py:127-153`）。旧的 `execCommandApproval`、`applyPatchApproval` 两个方法 Codex 自己只记日志不处理。
- **命令批准**：`{"id": <rpc id>, "method": "item/commandExecution/requestApproval", "params": {threadId, turnId, itemId, reason, command, commandActions, cwd?, proposedExecpolicyAmendment?, networkApprovalContext?, proposedNetworkPolicyAmendments?, approvalId?, availableDecisions?, additionalPermissions?}}`。桌面卡片的标题就是 `params.reason`（截图里那句问话，推断是模型写的 justification），标签「Terminal / 终端」。
- **文件批准**：`item/fileChange/requestApproval`，params `{threadId, turnId, itemId, grantRoot?, …}`；改哪些文件要从这一轮里 `{"type":"fileChange","id":itemId,"changes":[…]}` 那一项读。
- **其他几种**：`item/permissions/requestApproval`、`mcpServer/elicitation/request`、`item/tool/requestOptionPicker` 是另外的请求，这一轮手机上不答，只说「请在电脑上处理」。
- **回答通道**：和现有的 `thread-follower-submit-user-input` 同一条管道、同一个 owner。方法是 `thread-follower-command-approval-decision` 或 `thread-follower-file-approval-decision`，params `{conversationId, requestId, decision}`。app.asar 里 owner 的处理分支已核对：`case "thread-follower-command-approval-decision": return await e.replyWithCommandExecutionApprovalDecision(…)`，文件那个同理。版本号调查会话读到是 1，**没实测**。
- **桌面版按钮发的 decision**：命令：`"accept"`（允许一次）、`"decline"`（拒绝和 Esc）、`{"acceptWithExecpolicyAmendment": {…}}`（允许类似命令）、网络批准的 `"acceptForSession"`；文件：`"accept"`、`"acceptForSession"`（允许全部修改）、`"decline"`。`"cancel"` 存在但界面不发；停止这一轮时 Codex 会自己拒绝待处理的批准。
- **注意**：请求已经不在了（比如用户在电脑上先点了），owner 什么也不做，但照样回 `{ok: true}`。所以回答以后要重读快照，看请求还在不在。
- **记录文件里没有批准**：这台电脑上 27 次提权请求（`require_escalated` 加 `justification`），调用和输出之间只有一条 token_usage 记录；`logs_2.sqlite` 里也没有批准。所以 `notify.py` 只看记录文件，永远看不到「在等批准」。
- **还不知道的**：rpc id 是数字还是字符串、哪些可选字段会出现；13770 那台电脑上的 Codex 版本有没有这两个方法（旧版会回 `request-version-mismatch` 或 `no-handler-for-request`）。见 5.1。
- 调查会话的脚本和摘录在 `C:\Users\39011\AppData\Local\Temp\claude\6ee46b7f4051a927\b58d7776-539b-4460-89fc-9ed4412c43d4\scratchpad\probe-codex\`（`asar_grep.py`、`asar_slice.py` 等，临时文件夹，可能被清掉）。

### 2.2 打开速度实测（这台电脑，文件已在系统缓存里，两次相差 5% 以内）

| 对话 | 服务启动后第一次打开 | 已经读过 | 一页大小 | gzip 后 | 去掉手机不用的字段再 gzip |
|---|---|---|---|---|---|
| Claude 7–10 MB | 0.17–0.23 秒 | 3 毫秒 | 63–83 KB | 17–20 KB | 8 KB |
| Claude 114 / 120 / 148 MB | 1.29 / 1.35 / 1.6 秒 | 3.6 毫秒 | 45–134 KB | 12–39 KB | 10 KB |
| Codex 11 MB | 0.15 秒 | 1.7 毫秒 | 166 KB | 46 KB | 7 KB |
| Codex 388 MB | 2.1 秒 | 2.2 毫秒 | 138 KB | 29 KB | 9 KB |
| DeepSeek | 页面本身 50–225 毫秒，105–192 KB；找端口 1.7 秒（每 30 秒一次）；对话列表缓存过期时 0.64 秒 | | | | |

- 114 MB 的 Claude 文件：读文件 30–43 毫秒，整个解析 1.19 秒，其中 JSON 解析约占 45%（每行解析两次）。Codex 388 MB：解析 1.89 秒，JSON 解析 1.33 秒，最终回答比对 0.21 秒（446 个回答）；第一次读状态还要另建提问索引 0.9 秒（`codex_control.py:365-412`）。
- 只解析文件最后 1–4 MB 就够凑出 60 条消息：Claude 17–76 毫秒，Codex 用户对话 12–120 毫秒（子代理要 16–64 MB）。这一轮不做（id 依赖全量解析，风险大），留给以后。
- 手机打开一个对话时：iOS 先等这一页回来，再开实时流（`AppModel.swift:238-255,629-643`；`ChatModel.swift:181-231`）；安卓同时发出去（`MainActivity.kt:105-118` → `ChatController.kt:51-103`），于是同一页下了两份（实时流第一帧里又带一遍，`live_events.py:121,134`）。两边都不先显示本机缓存，都清空了等网络（`AppModel+Reading.swift:61-73`，`ReaderViewModel.kt:741-742`）。
- 中转：三段都不压缩（`remote.py:331-342` 发原样 JSON；`relay_transport.py:17` 不转发 `Accept-Encoding`；中转自己不压缩）。电脑每处理一个手机请求都新开一条到中转的 WebSocket（`relay_agent.py:23-26`，`relay_transport.py:146-147`），多三个来回。
- 调查脚本和原始数据在同一个临时文件夹的 `probe-speed\`（`results.jsonl`、`probe.py`、`probe_lite.py`）。

---

## 3. 逐条原因和代码位置

### 3.1 批-1、批-2、批-3

- 批-1：`native_questions()`（`codex_control.py:320-346`）只留 `item/tool/requestUserInput`，`status()`（约 654、691 行）于是不给批准卡片。手机只从 `questions` 画 Codex 卡片（iOS `Interaction.swift:39-44`、`QuestionCards.swift:41`；安卓 `ChatUi.kt:782, 832-894`），`running` 还是 true 又没有提问，标题就写「正在处理」（`Timeline.swift:261`；`ChatUi.kt:502`）。`call()`（约 169 行）拒绝 `VERSIONS`（37-44 行）里没有的方法，所以就算手机想答也发不出去。
- 批-2：`activity.py:34-37` 只数提问和计划；`notify.py:542-546` 只看记录文件判断 Codex 在不在跑，537-541 行 20 分钟没新行就当过期丢掉；记录文件里没有批准，所以永远不会推「在等你」、岛也不会变成「需要你」。另外 `apps/android/README.md:534` 写着 Codex 批准显示「请在电脑上处理」，代码里没有这回事。
- 批-3：`VERSIONS` 里 `thread-follower-set-queued-follow-ups-state` 是 1（41 行），读 `thread-queued-followups-changed` 的地方按 2 处理（约 123 行）。调查会话从 26.1106 的版本表里读到这两个都是 3。没实测。`TESTED_APP_VERSION` 还写着 `26.1007.2314.0`。

### 3.2 滚-1（iPhone，`apps/ios/Teleply/Chat/ConversationView.swift`）

- `atBottom`（13 行）在每次几何变化时重算：离底 24 点以内就是 true（110-115 行），不管是谁让几何变了，也没有手势状态。
- 每来一帧有消息的画面（`model.conversation.revision` 变了，132 行；计数在 `ChatModel.swift:262` 加一），`follow()`（323-330 行）只要 `atBottom` 就 `position.scrollTo(edge: .bottom)`，不看手指在不在屏上。`defaultScrollAnchor(atBottom ? .bottom : .top, for: .sizeChanges)`（108 行）用的也是这个值。
- 为什么拽回去：往上拖的头 200 毫秒还在 24 点以内，这时来一帧（DeepSeek 每 0.2 秒一帧，`live_events.py:185-190`；Codex、Claude 每秒一帧，145 行）就被拉回底部，拖得慢的根本出不了这个范围。内容变短也会自己钉住：这一轮结束时运行中的折叠收起（`Timeline.swift:43-46, 97`），思考行消失（93-99 行），位置被夹到底部，`atBottom` 又变成 true。
- 发送：没有任何滚动（Composer 里没有滚动代码），发出去的气泡只有本来就在底部时才看得见。
- 已有的「有新消息 ↓」胶囊：`ConversationView.swift:281-304`。

### 3.3 滚-2（安卓，`ChatUi.kt`，LazyColumn 不反向，229-233 行）

- 任何拖动设 `follow=false`；`!canScrollForward && !dragging` 时设回 true（158-164 行）。来新画面时只有跟随中才 `scrollToEnd`（165-169、307-312 行），输入框变高时也一样（196 行）。内容长高不会移动没在跟随的读者，因为列表保持第一个可见项和偏移。
- 漏洞：拖动状态经 `collectIsDraggedAsState` 和一次重组才到（139-140 行），快速轻扫时可能漏掉，随后的 `scrollToItem` 会打断惯性滑动（推断）；回到底部要精确到底，文字一边长一边往下翻时可能永远接不上；内容变短（折叠收起 491 行、卡片和待发气泡消失）会重新钉住；恢复位置（转屏、改窗口、从设置回来）时强制 `follow=false`（175-179 行）；没有新画面的变高（待发气泡，270-273 行）不跟随。
- 发送：只有本来在跟随时才滚到底。胶囊在 `ChatUi.kt:289-291`。

### 3.4 影-1、影-2（Claude 淡色旧消息）

- **淡色气泡是 iPhone 自己存的「已发消息」**，不是电脑端的排队清单。iOS：`ConversationView.swift:45-46` 建 outbox，87-90 行画在所有消息后面（`sending: true`），`Timeline.swift:362` 透明度 0.6；手机每个对话最多存 100 条已发消息（`LocalStore.swift:92, 263-268`），进对话时读回来（`ChatModel.swift:181-198`）。安卓画不出这种气泡：它的待发行只显示「提交中」，恢复时重置（`ChatUi.kt:270-272`、`ChatController.kt:65`）。电脑端报的 Claude 排队是输入框上方带时钟图标的一排（`ComposerView.swift:46-108`），也不是气泡。
- **什么时候去掉**：`outboxSends()`（`Outbox.swift:26-53`）只在四种情况下不画一条已发消息：① 标签是「未接收」「已取消排队」或是命令（32-34 行）；② 记录里找到了同一条（按 request id，或按文字且记录位置 `order > _claude_offset`，35-42、83-98 行）；③ 列表上面还有更早的没读、且这一页从这条之后才开始（43 行；`olderUnread` 为 false 或标签是「已排队」时不看这条）；④ 已过 10 分钟、且列表里有更晚的用户消息（44-49 行）。
- **坏在哪**：打开另一个对话时，`olderAvailable` 先设成 false（`AppModel+Reading.swift:61-69`），只有第一页读成功才按回答设回去（73-77 行）。第一页读失败或被取消时，`live()` 照样连上（`AppModel.swift:238-256`），实时流的快照把列表填上（`AppModel+Reading.swift:182-194`），但快照里的 `has_more` 没有带过来（`ChatCore.swift:116-134` 里没有这个字段）。于是第③种永远不成立；最新 60 行里又没有这些消息，存着的已发消息就全部淡淡地叠在底部。直到列表里出现一条更晚的用户消息，第④种才把 10 分钟以前的一起去掉——正好是「再发一条、Claude 开始干活就消失」。`OutboxTests.swift:139-140` 断言「`olderUnread == false` 就说明列表是整份记录」，坏的正是这个假设。另一个可能的触发：查找消息跳转（`AppModel+Reading.swift:163-178`）以后，最新几行被接在下面，中间留了空档。
- **实证**（调查会话用电脑端自己的 `Transcript` 在临时副本里重放了这个对话的记录 `C:\Users\39011\.claude\projects\D--Personal-claude-sqlite-translation\5db34450-a774-4577-91a7-186d39317c1e.jsonl`，154.8 MB，11-12 14:40 误删时 Claude 重建过）：11-15 12:56 到 15:35，最新一页（60 行）里一条用户消息都没有；15:43:31 用户从手机发出一条，马上写进记录，这是 12:32 以来第一条用户消息，第④种当场把以前的全清掉。日志里手机 11-12 到 11-15 给这个对话发过 17 条，全都直接写成普通用户消息，标签应是「已送达」，按第②③种本该清掉，只有列表不完整时才会留下。具体是哪一次请求失败没法坐实：手机没有日志，dev.35 也不记失败的请求（记录失败请求是后来 `remote.py:387-437` 加的）。
- **影-2，永远对不上的几种**：带引用的消息，记录里是文字加引用，手机只拿自己的文字比（`remote.py:795-797`、`Outbox.swift:86-87`）；只发图片的，电脑端替它写成「请查看这些图片。」（`remote.py:794`）；超过 6000 字的，页面里被截断（`chat_history.py:196-197`）。电脑端其实已经在发送结果里给了实际写进记录的文字 `check_text`（`remote.py:730, 811`），iPhone 也存了（`ChatModel.swift:10` 的 `_claude_check_text`、562 行），只是对照时没用。另外标签「已移除」（`ChatModel.swift:711, 737` 设的）不在第①种的跳过名单里，删掉的消息还会画出来。
- **电脑端排队清单不是原因**：它只在内存里（`Transcript.context['queue']`，`chats.py:886-887`），重放显示 15:34:31 到 15:43:31 是空的；重启后照记录重放，得到的状态一样。小毛病一个：Claude 运行中发带图片的消息，会先写一条空的排队项、再写附件、再写带文字的移除，空项一直留着，下一个 /compact 被 Claude 接走时就不显示（调查会话在临时副本里重演过）。
- **%TEMP% 和重启都无关**：电脑端运行代码只有 `setup_machine.py` 用 tempfile；装的是 PyInstaller 文件夹版（`G:\AgentRemote\_internal`），不往 %TEMP% 解包。顺带发现：这台电脑装的是 **dev.35**（`G:\AgentRemote` 里的 `windows-version.json`），不是 dev.36。

### 3.5 慢-1 到 慢-4

- 慢-1：工具步骤的 `detail`、`result` 每条最多 16000 字（`activity_records.py:92-93, 118, 139`），占每页 50%–86%。两个手机都不存它们（iOS `Models.swift:173` 的 `messageDetails`、安卓 `Models.kt:42` 的 `MessageDetails` 里都没有），只有网页用。
- 慢-2：见 2.2 中转一条。手机的 URLSession、OkHttp 收到 gzip 会自己解开，不用改手机。
- 慢-3：`deepseek_control.py` 的 `Client.connection_info()`（约 299-305 行）每 30 秒调一次 `discover()`（约 284-297 行），不管调用是不是一直成功。
- 慢-4：`chat_history.py:49-50` 每行先 `chats._parse`、再 `activity_records.enrich`，后者又 `json.loads` 一遍（`activity_records.py:32`）；`chat_history.py:56` 起每个 Codex 最终回答都扫一遍全部消息找同一轮的另一份；`chat_history.py:102` 只留 8 个解析好的对话，第 9 个一开，最早的就要重新整份解析。

---

## 4. 修法（分阶段；每个阶段先写测试、确认在旧代码上失败，再改；做完单独提交）

### 4.1 阶段一：Codex 批准（批-1、批-2；批-3 只核实）

**电脑端（先做，做完已发的手机版就能用）**

1. `codex_control.py:37-44`：`VERSIONS` 加 `"thread-follower-command-approval-decision": 1`、`"thread-follower-file-approval-decision": 1`。
2. 在 `native_questions()` 后面加 `native_approvals(state)`：
   - 遍历 `state["requests"]`，method 是 `item/commandExecution/requestApproval` 或 `item/fileChange/requestApproval` 的，按 `native_questions` 一样的条件筛（`params.threadId == state.id` 且 `is_running(state)`）。
   - 卡片：`{"id": "approval:<turnId>:<rid>", "kind": "approval", "request_id", "turn_id", "status": "pending", "approval_type": "command"|"file", "reason", "command"（列表拼成一行字符串）, "cwd", "files"（文件批准从这一轮 `itemId` 对应的 fileChange 项里取路径）, "choices": [{"id":"accept","label":"允许一次"}, {"id":"decline","label":"拒绝"}], "answerable": true}`。这一轮手机上**只给这两个选择**，不给「允许类似命令」「允许全部修改」（锁屏岛那份交接 `docs/handoff-dynamic-island.md:610` 也定过不在岛上给）。
   - **兼容字段**：同时放 `questions: [{"id": "decision", "header": …, "question": "<reason>\n\n<command>", "options": [{"label": "允许一次"}, {"label": "拒绝"}], "isOther": false}]`，字段名照 `item/tool/requestUserInput` 的提问（先读 iOS `QuestionCards.swift`、安卓 `ChatUi.kt` 的 CodexCards、网页 `codex-ui.js:262-297` 确认它们读哪些字段）。这样 iOS 0.7.3、安卓 1.0.6 不用更新就会画出卡片、提问条和「需要你回答」，安卓手表提醒（`WatchNotifications.kt:24`）也会响。
   - 其他几种请求（permissions、MCP elicitation、option picker）：卡片 `answerable: false`，不给选项，文字「Codex 在电脑上等你处理，这种请求手机上还不能答」。
   - 遇到不认识的 method：每个请求 id 记一行日志，只写 method 和 params 的键名，不写值。以后 Codex 再改协议能一眼看出来。
3. `status()`（约 654 行）：`qs += native_approvals(state)`。
4. `answer()`（约 1020-1060 行）：找卡片时把批准卡片也算上；在 `_begin` 之前把答案（「允许一次」/`accept`、「拒绝」/`decline`）换成 decision，别的一律 400，不留账本行；调 command 或 file 那个方法，params `{conversationId, requestId, decision}`，发给和 `submit-user-input` 同一个 owner；然后重读快照，确认请求不在了。回 `request-version-mismatch` 或 `no-handler-for-request` 时记为 rejected，回答「请在电脑上处理」。
5. `receipt()`（约 785 行）：加 `approval:` 的情况：dispatching 且请求已经不在，就算 accepted（「已交给 Codex」）。因为 owner 对已经不在的请求也回 ok，文字写中性一点，比如「Codex 已收到；如果你已在电脑上处理过，以电脑为准」。
6. 「在等你」：`activity.py:34` 把批准也算进 pending；`notify.py` 的 `look()` 对还在跑的 Codex 对话，像 `activity.py:31` 那样不阻塞地拿锁读实时状态，最多约 12 秒一次；有待批准的，照 DeepSeek 的做法（`notify.py:778-791`）：键 `pending:<ids>`、`waiting[conv]`、`_tell(…asks=True)`，中转已经会发「在等你选」并把岛设成等待（`relay_push.py:47, 156, 831`）；请求还在时，537-546 行不要把它当过期清掉；请求消失后清 `reported_running`，让「运行中」重新发一次。
7. 批-3：**只核实，不盲改**。在 5.1 用户帮忙时，Codex 运行中从手机发一条消息，看日志有没有 `request-version-mismatch`。确实不匹配，再对照 app.asar 26.1106 改版本号和 params，补测试。核实过 26.1106 以后，`TESTED_APP_VERSION` 改成实测的版本。

**手机（电脑端做完以后）**

- 回答都走现有的 `codex/answer`：`{question_id, answer_revision, answers: {"decision": ["accept"]}}`。它已经过中转的检查（`RelayApi.kt:293`，`Relay.swift:300`），也有按回执「核对上次操作」（`WorkspaceModel.swift:573-576`；`WorkspaceController.kt:468-472`）；电脑已经处理过时回 4xx，会清掉待处理（`WorkspaceModel.swift:520-529`；`WorkspaceController.kt:558-567`）。
- iOS：`InlineCard` 加 `codexApproval`，在 `QuestionCards.swift:13-43` 按 `kind` 分流；卡片照 `DeepSeekApprovalCard`（366-403 行）：标题「Codex 想运行命令」/「Codex 想改文件」，标签「终端」/「文件」，命令用 `CodePanel`，下面一行工作文件夹，按钮「拒绝」「允许一次」；`answerable == false` 写「请在电脑上处理」。同时改 `pendingCards`（`Interaction.swift:39-44`）、提问条的「去处理」（`QuestionCards.swift:494-497`）、标题「需要你批准」（`Timeline.swift:260`）。
- 安卓：`pendingCards`（`ChatUi.kt:782`）加批准分支；`CodexCards` 里加 `CodexApprovalCard`，照 DeepSeek 批准卡（`ChatUi.kt:943-958`）。
- 网页：兼容提问已经能用（`isOther:false` 会藏起自由输入）；要正式卡片就复用 `deepseek-ui.js:158-171` 的 `approvalPart`，`interaction-ui.js:11/40` 加「需要你批准」。

**测试**

- Python（夹具照 `tests/test_codex_delivery.py:14-32`）：建出批准卡片，别的对话、不在运行、旧方法都不算；每个选择对应的 `pipe.call` 方法、params、decision 都对；自由文字回 400、回执仍是 unknown；同一请求重放只调一次，过期的拒绝；版本不匹配记为 rejected，回执能对上；`TaskCenter.observe` 数到批准；notify：「在等你」只发一次，请求在时一直保持，处理后回到运行中，20 分钟过期规则不清掉它。
- 安卓（`ChatUiLogicTest`、`WorkspaceControllerTest`）：`pendingCards` 和手表提醒。iOS（`InteractionTests`、`ChatCoreTests`）：`pendingCards`，`parseControl` 给批准设好 `questions`。

### 4.2 阶段二：滚动（滚-1、滚-2）

**规则（三家对话都一样）**

1. 「跟随」只随用户的动作变：开始拖 → 不跟随；滚动停下时离底 48 点（dp）以内 → 跟随，并补滚到底；打开对话、发送、点「有新消息 ↓」、点「回到最新」→ 跟随；搜索命中、加载更早消息 → 不跟随。内容变长、变短、输入框高度变化**都不改它**。
2. 跟随且没在滑动时，新输出就滚到底；手指在屏上或惯性滑动中，永远不滚。
3. 不跟随时，新输出只设 `unseen`，显示已有的「有新消息 ↓」胶囊。
4. 不跟随时来了提问卡或批准卡，不把人拽下去；已有的提问条「去选择 / 去处理 ›」（`QuestionCards.swift:482-499`，`ComposerUi.kt:164-176`）负责提示和跳转。

**iOS（`ConversationView.swift`）**

- `atBottom`（13 行）换成 `following`；另留一个 `nearBottom`（`onScrollGeometryChange`，110-115 行，阈值改 48 点，仍只算 Bool，不存每个像素的偏移）。
- 加 `.onScrollPhaseChange`：进入 `.tracking`、`.interacting`（用户手指）→ `following = false`；变回 `.idle` 时若 `nearBottom` → `following = true`、`unseen = false`、`scrollTo(edge: .bottom)`。`.animating`（程序滚动）不改跟随。
- `follow()`（323-330 行）：只有 `following` 且滚动阶段是 `.idle` 时才滚，否则 `unseen = true`。
- 108 行改成 `following ? .bottom : .top`；胶囊条件（283 行）改成 `unseen && !following`。
- `restore()`（309-320 行）打开在最新处时设 `following = true`；`keepPlace()`（333-337 行）设 `false`。卡片 id 变化时也调一次 `follow()`。
- 发送：`ChatModel.submit`（`ChatModel.swift:427`）加一个 `sent` 计数（照 `focus`、`acknowledged` 的做法）；页面 `onChange(of: sent)` → `following = true`，带动画滚到底。
- **不要**把 VStack 改成懒加载：改过一次，键盘一弹出屏幕就白了（`apps/ios/README.md:474`，`ConversationView.swift:49-51`）。

**安卓（`ChatUi.kt`）**

- 换掉 139-140、158-164 行：直接收 `list.interactionSource.interactions`，`DragInteraction.Start` → `follow = false`、记下「摸过」；`snapshotFlow { list.isScrollInProgress }` 变成 false 且摸过时，离底 ≤ 48dp（算法同 311 行 `scrollToEnd`）就重新跟随。
- 跟随且没在滑动时，`canScrollForward` 变成 true 也滚到底（盖住待发气泡、卡片这些没有新画面的变高）。
- 发送：`ComposerState`（`ChatController.kt:11`）加 `sent` 计数，变化时跟随，等待发气泡出现后滚到底。
- `ReadingPlace`（`ReaderViewModel.kt:121`）加 `follow`，恢复位置时（175-179 行）照存的值；加载更早消息（208-212 行）设不跟随。

**网页（顺手，可选）**：`static/scroll-anchor.js` 已经是「只在底部 80px 以内才跟」、内容长高不算用户滚动；补一条：手指按着时不重新钉住。

**不要退回去的（README 里记过的）**：打开就在最新处；搜索命中停在那条消息；「回到最新」到底；加载更早消息保持位置；同一次阅读里重画保持位置（`apps/android/README.md:127-132`）；iOS 重画开销（`apps/ios/README.md:469-474`）。

**测试**

- 把规则写成纯函数或小类型（iOS 放 TeleplyState，安卓放在 `ChatUiLogicTest` 旁边），用例：内容变长变短都不改跟随；拖动取消跟随；停在离底 48 以内重新跟随；打开和发送重新跟随；`newerAvailable` 时不跟随。
- 安卓 Robolectric 场景（`sharedTest/ReaderUiScenarios.kt`、`ReaderRobolectricTest.kt`，`ChatControllerTest.kt:36` 有假的 `events()` 可用）：每 200 毫秒来一帧，往上划 → 第一个可见项不变、出现胶囊；点胶囊 → 最后一项可见；发送 → 重新跟随。
- iOS：演示数据加一个会持续出字的对话，`TeleplyUITests` 加同样的场景（这台电脑编不了 iOS，见第 6 节）。

### 4.3 阶段三：打开速度（慢-1 到 慢-4，电脑端为主）

1. **慢-1 精简页**：手机请求 `/api/chat` 加 `lite=1`（iOS `Relay.swift:234-243`，安卓 `RelayApi.kt:273-278`），实时流 `/api/events` 也加；电脑端见到 `lite=1` 就不放 `detail`、`result`（`chat_history.py:192-198`，`live_events.py:42-47`）。旧手机不带这个参数，不受影响；网页不带，照旧。测试：`tests/test_history_projection.py` 加用例。
2. **慢-2 压缩**：`remote.py` 的 `_send`：请求头 `Accept-Encoding` 含 gzip、内容是 `application/json`、超过约 1 KB 时 gzip，并带 `Content-Encoding: gzip`、`Vary: Accept-Encoding`。不碰实时流（text/event-stream）、文件下载和带 Range 的请求；中转会改写 `/` 的 HTML（`relay_transport.py:172-183`），HTML 不压。`relay_transport.py:17` 的 `REQUEST_HEADERS` 加 `Accept-Encoding`（`Content-Encoding` 已经会回传）。这一处是中转服务器的代码，要等用户在服务器上更新才生效；电脑端先改好不影响现在的中转。测试：头部的单元测试。
3. **慢-3 DeepSeek 端口**：`Client.connection_info()` 只在没有连接、或上一次调用失败后才 `discover()`；调用失败时清掉连接（先核对 `call()` 现在是不是已经这样）。测试：连续成功调用不再起 PowerShell；失败一次后重新找。
4. **慢-4 第一次打开**：
   - 每行只解析一次：`chats._parse` 解析好的记录交给 `activity_records.enrich`，别再 `json.loads`（`chat_history.py:49-50`，`activity_records.py:32`），接口保持向后兼容。
   - Codex 最终回答按 turn 建索引，去掉 `chat_history.py:56` 起的全量扫描。
   - `chat_history.py:102` 的缓存按源文件总大小限（比如 24 个以内、源文件合计 600 MB 以内），别只按 8 个。
   - 测试：现有的投影测试全过；用 `probe-speed\probe.py` 的思路量一下 114 MB Claude、388 MB Codex 的第一次打开，记在第 9 节。
5. **这一轮不做，列给用户以后定**：从文件尾部先出第一页（id 依赖全量解析，风险大）；实时流第一帧不再重复整页；电脑和中转之间保持几条连接；手机先显示缓存再刷新；中转权限检查缓存；iOS Markdown 结果缓存。

### 4.4 阶段四：Claude 淡色旧消息（影-1、影-2）

**iOS（主要）**

1. 实时流快照带上分页：`LiveFrame`（`ChatCore.swift:116-134`）读出快照的 `has_more`、`next_cursor`（先核对电脑端快照里这两个字段的实际名字，`live_events.py` 的 snapshot）。`apply`（`AppModel+Reading.swift:182-194`）里：快照和现有列表一个 id 都对不上时，用快照替换列表，并按快照设 `olderAvailable`、`cursor`；跳转后的页（`anchor != nil`）不要把最新几行接在下面。
2. `outboxSends()`（`Outbox.swift`）：
   - 「已移除」加进第①种的跳过名单；
   - Claude 的消息标签是「已送达」（电脑已确认写进记录）且超过约 60 秒，就不再画，画不画以记录为准；
   - 按文字对照时，有 `_claude_check_text` 就用它，没有再用手机自己的文字。
3. 测试：`OutboxTests`：列表只有快照时「已送达」不画（同时改掉 139-140 行那条假设）；「已移除」不画；带引用的消息按 `_claude_check_text` 能对上；只发图片的能对上。`AppModelTests`：第一页读失败、随后来了快照，outbox 为空；和旧列表不重叠的快照替换旧列表。

**电脑端（小）**

- `_queue_remove`（`chats.py:843-861`）什么都没对上时，去掉最老的一个空项。测试放 `tests/test_claude_send.py` 的 `QueueShadowTests`（约 578 行）：运行中发带图片的消息，接着 /compact，Claude 接走时显示命令。

**安卓**：不用改。

---

## 5. 要用户帮忙的

### 5.1 抓一次 Codex 批准（阶段一做完电脑端以后，由 Claude 和用户一起做）

在这台电脑的 Codex 里，用「工作区可写 + 需要时询问」的权限，让它跑一条要提权的命令，电脑上会弹批准卡片。这时看电脑端日志里那行「不认识的 method」（如果有），用 `bridge.snapshot(tid)` 确认 `requests` 里的 id 类型和字段，再从手机点「允许一次」，看 Codex 有没有真的继续。顺便在 Codex 运行中从手机发一条消息，核实批-3。DeepSeek 不要自己去触发 Codex 批准，也不要用用户的 Codex 账号跑任务。

### 5.2 真机验证（新版本装上以后）

见 7.2。

---

## 6. 边界

- 只在 `main` 上本地提交，一个文件一个文件 `git add`，提交前 `git status` 只看得到你改的文件。**不要 push。**
- 不要动：`deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`（用户自己没提交的改动）；`IOS API key\` 文件夹；`C:\Users\39011\.teleply-updates`、`C:\Users\39011\.android\teleply-signing` 里的钥匙。钥匙和令牌一律不打印。
- 不要改版本号、不要打包、不要发版：安卓 1.0.7 和 Windows dev.37 已经打包但没发布，这一轮改完由 Claude 重新打包（版本号不变）；iOS 下一版 0.7.4 由 Claude 改版本号。
- 不碰中转服务器、苹果后台、Codemagic、TestFlight、Obsidian 里的规范。
- iOS 这台电脑编不了（Swift 工具链 11-12 被删）：写好代码和 `TeleplyCore` 测试，尽量照已有写法；编译和测试由 Claude 在用户同意推送后用 Codemagic 跑。不要自己装 Swift 工具链，也不要开 Codemagic。
- PowerShell 里不要用自动变量当变量名（`$home`、`$HOME`、`$pwd`、`$args`、`$input`、`$host`、`$profile`）；不要递归删除你自己文件夹以外的东西；删除前先打印绝对路径。
- 这几台电脑上的 Codex、Claude、DeepSeek 都在用：不要停止、重启或改它们的设置；不要启动或停止遥应电脑端（`G:\AgentRemote`）。

---

## 7. 验证

### 7.1 本地

- Python：`.venv\Scripts\python.exe -m unittest discover -s tests`。基线（11-12）：765 项、6 跳过、22 出错，22 项都是老问题（21 项 Playwright 浏览器没装，1 项 `test_mobile_polish` 找旧按钮名）。加了新测试以后，出错的仍只能是这 22 项。
- 安卓：`apps\android\scripts\build.ps1`（默认跑 assembleDebug、testDebugUnitTest、lintDebug、assembleDebugAndroidTest）。基线：213 项单元测试全过。`debug.keystore` 11-16 已重新生成，脚本能跑。
- iOS：只能写，编译交给 Claude（第 6 节）。

### 7.2 真机（新版本装上以后，请用户照做）

- 批准：Codex 弹批准时，手机上出现卡片，点「允许一次」后 Codex 继续；点「拒绝」后 Codex 换别的做法；电脑上先点了，手机上的卡片消失；锁屏岛和推送说「在等你」。
- 滚动：DeepSeek flash 跑长任务时，往上翻能停住，不被拉回；出现「有新消息 ↓」，点它回到最新；滑回底部后又自动跟随；发消息后回到底部。
- 速度：同一个大对话，点开到出内容的时间和改之前比。
- 重影：iPhone 上给 Claude 发的消息写进记录以后，一分钟内淡色气泡消失；带引用、只发图片的也一样；网络差、第一页没读成时，底部也不会叠出以前发过的消息。

---

## 8. 发布（每一步都先问用户，上一次同意不算这一次）

- Claude 做：推送（等用户同意）→ Codemagic `ios-native-check` 编译和测试 → iOS 0.7.4 传 TestFlight（问）→ 用新代码重新打安卓 1.0.7 和 Windows dev.37 → 发 GitHub（问）→ 用户在 Workbench 更新中转（带上 `Accept-Encoding` 和之前的 `0e086e7`）。
- 安卓 1.0.7、Windows dev.37 换了新钥匙，第一次都要手动装：安卓先卸载再装，电脑端装完重新登录、绑定原来那台电脑。

---

## 9. 结果记录（接手的会话填）

（每个阶段做完写：改了哪些文件；新测试的名字，旧代码上的结果和新代码上的结果；全部测试的结果；没做的和原因；提交编号。）

### 9.1 阶段一：Codex 批准（批-1、批-2；批-3 只核实，没改）

改动（电脑端）：
- `codex_control.py`：`VERSIONS` 加 `thread-follower-command-approval-decision`、`thread-follower-file-approval-decision`；新增 `native_approvals(state)`（命令/文件批准卡片、`questions` 兼容字段、`answerable:false` 的其他请求、每行日志只写 method 和 params 键名）；`status()` 把批准卡片并进 `questions`；`answer()` 认批准卡片，先校验两个选择再 `_begin`，调对应方法并重读快照；`receipt()` 对 `approval:` 的 dispatching 按「请求已不在」记 accepted；新增 `_log_unknown_requests`。
- `activity.py`：待处理数把批准算进去（`TaskCenter` 的列表/锁屏岛）。
- `notify.py`：`Notifier` 接 `bridge`；`look()` 对记录里读作 running 的 Codex 对话最多约 12 秒读一次桌面批准，有待批准时 `waiting`、`pending:<ids>`、`_tell(asks=True)`，20 分钟过期规则不再丢掉它；请求消失后清 `reported_running`，让「运行中」重新报一次。
- `remote.py`：创建 `Notifier` 时传 `bridge=server.codex`。

改动（手机）：
- iOS：`Interaction.swift` 的 `pendingCards` 认 `kind: approval`；`QuestionCards.swift` 加 `codexApproval` 卡片（标题、终端/文件标签、命令/文件 CodePanel、工作文件夹、拒绝/允许一次，`answerable:false` 写「请在电脑上处理」），提问条批准走「去处理 ›」；`Timeline.swift` 折叠标题按批准说「需要你批准」。
- 安卓：`ChatUi.kt` 的 `pendingCards` 认批准、`CodexCards` 分流到新的 `CodexApprovalCard`、折叠标题说「需要你批准」；`ComposerUi.kt` 提问条批准走「去处理 ›」。
- 手表提醒不用改：`WatchNotifications.kt` 读的就是 `questions` 里的 pending 卡片，批准卡片会一起响（补了测试）。

新测试：
- `tests/test_codex_approvals.py`（14 项）：卡片字段与两种批准类型、别的对话/不在运行/旧方法不算、未知请求只记一行且不写值、允许/拒绝对应的 pipe 方法与 `decision`、自由文字 400 且不留账本、过期请求拒绝、版本不匹配记 rejected、回执按请求消失算 accepted、`status()` 列出批准、`TaskCenter` 计数、notify 的「在等你」只发一次/20 分钟规则不丢/请求消失后回到运行中。
- iOS `InteractionTests.codexApprovalsAreTheirOwnPendingCard`、`ChatCoreTests.aPendingCodexApprovalIsWaiting`。
- 安卓 `ChatUiLogicTest.codexApprovalsAreTheirOwnCard`、`PlatformPolicyTest.aPendingCodexApprovalCountsAsWaitingForTheWatch`、`WorkspaceControllerTest.aCodexApprovalSendsTheOneDecision`。

旧代码上的结果（`stage1-new-tests-on-old-code.log`）：14 项里 1 项本来就成立（过期的请求会被拒绝），其余 13 项失败（3 failures、10 errors），失败的正是「旧代码没有批准通道/卡片」。
新代码上的结果：14 项全过（`stage1-new-tests-on-new-code.log`）。
安卓：`build.ps1 -Tasks compileDebugKotlin testDebugUnitTest` 通过，单元测试 **216 项全过**（基线 213 + 本次 3）。
iOS：只写代码和 TeleplyCore 测试，本机没有 Swift 工具链，**没编译**，等 Claude 在 Codemagic 跑。
全部 Python：`782 项，6 跳过，22 出错`；22 项与基线同类（21 项 Playwright 浏览器缺失、1 项 `test_mobile_polish` 找旧按钮名），没有新增失败。782 里含本次 14 项。

没做/待定：
- 批-3 按文档**只核实不改**：`thread-follower-set-queued-follow-ups-state` 的版本号、`TESTED_APP_VERSION` 都没动，等 5.1 用真实 Codex 运行中从手机发一条消息看日志，确认后再改。
- 网页的正式批准卡片没做（可选）：兼容 `questions` 字段已经让网页画出提问并藏起自由输入。
- 5.1 抓一次真实批准、从手机点「允许一次」：要用户和 Claude 一起做，本会话没有触发 Codex。
- 提交编号：见 9.7（各阶段提交完成后一并补）。

### 9.2 阶段二：滚动（滚-1、滚-2）

改动（iOS）：
- `ConversationView.swift`：`atBottom` 换成 `reading: ReadingFollow`（11-16 新类型）；`nearBottom` 阈值 24→48；加 `.onScrollPhaseChange`（`.tracking`/`.interacting` 停止跟随，`.idle` 且离底 48 点内重新跟随并补滚到底，`.animating` 不动跟随）；`follow()` 只在跟随且阶段 `.idle` 时滚，否则置 unseen；`defaultScrollAnchor`、胶囊条件改用 `reading`；`restore()` 按「打开在最新处/查找命中」设跟随，`keepPlace()` 设不跟随；发送时 `onChange(of: conversation.sent)` 回到跟随并滚到底；卡片 id 变化也调一次 `follow()`。没有改成懒加载（README 记过键盘弹出白屏）。
- `ChatModel.swift`：加 `sent` 计数，`submit` 里每发一条加一（`self.sent`，避免和函数里的局部 `sent` 重名）。
- 新 `TeleplyModel/ReadingFollow.swift`：拖动、停住、打开、发送、新画面五条规则，纯类型。

改动（安卓）：
- `ChatUi.kt`：直接收 `list.interactionSource.interactions` 的 `DragInteraction.Start` 停止跟随（不再等一次重组）；`snapshotFlow { isScrollInProgress }` 变 false 且摸过、离底 ≤48dp 时重新跟随并补滚；新增 `ReadingFollow` 纯类型，跟随/未读都由它算；内容变长变短、程序滚动不改跟随；发送（`chat.sent`）重新跟随并等发气泡出现后滚到底；待发气泡、提问卡出现时若在跟随就滚到底；恢复位置按 `ReadingPlace.follow`，加载更早消息设不跟随；新增 `distanceFromEnd`。
- `ChatController.kt`：`ComposerState` 加 `sent`，`submit` 里 `action=="send"` 时加一。
- `ReaderViewModel.kt`：`ReadingPlace` 加 `follow`（默认 false，旧测试仍编译）；新增 `fixtureApi` 钩子，本地示例默认还是 `FixtureApi()`。
- 测试脚手架：`ReaderUiScenarios.launch` 可传 `api`，并把同一个工厂给本地示例。

改动（网页，可选）：`static/scroll-anchor.js` 手指按着（`pointerdown`…`pointerup/cancel`）时 `restore()` 直接返回，不再重新钉住。没有浏览器测试（Playwright 浏览器缺失）。

新测试：
- iOS `ReadingFollowTests` 4 项（拖动/停住/打开与发送/内容变长变短不改跟随）、`ChatModelTests.aSendCountsOnceSoThePageFollows`。
- 安卓 `ChatUiLogicTest.readingFollowChangesOnlyWithTheReader`；`ReaderRobolectricTest.readingAboveHoldsItsPlaceWhileFramesArrive`（打开 200 条的示例对话，往上划，连续送来 3 帧：滚动位置不变、出现「有新消息」胶囊；点胶囊回到最新；再往上划后发送，重新跟随到底）。

结果：
- 安卓：`build.ps1` 默认全跑（assembleDebug、testDebugUnitTest、lintDebug、assembleDebugAndroidTest）**通过**，单元测试 **218 项全过**（阶段一 216 + 本次 2）。
- 全部 Python：`782 项，6 跳过，22 出错`，与阶段一逐行相同的 22 项（21 项 Playwright 浏览器缺失、1 项 `test_mobile_polish` 找旧按钮名）。
- iOS：只写代码和 TeleplyCore 测试，**没编译**（本机没有 Swift 工具链）。`ScrollPhase` 用 `==` 比较、没有用 `switch`（它是 struct）。

没做：
- iOS 演示数据里「会持续出字的对话」和 `TeleplyUITests` 的同场景**没加**：`DemoTransport` 目前没有实时流接口，硬加要改演示传输和 UI 测试，本机没法编译验证，留给 Claude 在云端补。
- 网页的手指按着不改钉住没有自动化测试（浏览器缺失）。

提交编号：见 9.7。

### 9.3 阶段三：打开速度（慢-1 到 慢-4）

改动（电脑端）：
- `chat_history.py`：`conversation(..., lite=False)` 和 `public_message(..., lite=True)`，lite 页去掉每条消息的 `detail`、`result`；每行只解析一次（`chats._parse` 把解析好的记录交给 `activity_records.enrich`，不再 `json.loads`）；Codex 最终回答按轮次建索引（`final_answers`），不再每条扫全部消息；缓存从「最多 8 个」改为「最多 24 个、源文件合计 600 MB」，并且先 `refresh()` 再按大小淘汰（新加入的那个也算进总量）。
- `chats.py`：`parse_codex`、`parse_claude`、`_parse` 加可选 `parsed` 字典，填入最后解析的记录。
- `activity_records.py`：`enrich(..., record=None)`，给了就不再解析。
- `live_events.py`：`stream(..., lite=False)`、`merge_live_messages(..., lite=False)`，快照和补进来的实时消息都按 lite 去字段。
- `remote.py`：`/api/chat` 和 `/api/events` 认 `lite=1`；`_send` 对 JSON、超过 1 KB、客户端 `Accept-Encoding` 含 gzip、无 Range、未自带 `Content-Encoding` 的响应 gzip，带 `Content-Encoding: gzip` 和 `Vary: Accept-Encoding`；实时流、文件、HTML 不动。
- `relay_transport.py`：`REQUEST_HEADERS` 加 `Accept-Encoding`（`Content-Encoding` 本来就在回传名单里；`relay_agent.py` 早就 `auto_decompress=False`，中转不会误解压）。
- `deepseek_control.py`：`connection_info()` 只在没有连接时调用 `discover()`（不再每 30 秒起 PowerShell+netstat）；`call()` 失败时把连接清掉，下一次重新找。

改动（手机）：
- iOS `Relay.swift`：`history` 和 `events` 都带 `lite=1`；安卓 `RelayApi.kt` 同样。旧手机不带这个参数，电脑端照旧返回全量；网页也不带。

新测试：
- `tests/test_open_speed.py`（6 项）：大于 1 KB 的 JSON 会 gzip 且能解回原样；小 JSON、HTML、Range、没要 gzip、只要 deflate 都发原样；已带 `Content-Encoding` 不二次压缩；连续成功取连接只 discover 一次（时钟推进 40/80/120 秒也不再找）；成功的调用不会去找端口；调用失败清连接、下一次重新找。
- `tests/test_history_projection.py` 加 5 项：lite 页去掉 `detail`/`result` 而全量页保留、`/api/chat/message` 仍完整；`enrich` 收到的是已解析的记录；两轮的最终回答只在各自轮次里配对；缓存按总大小淘汰；`/api/chat` 与 `/api/events` 的 `lite` 真的传到 `conversation`/`stream`。
- `tests/test_live_history.py`、`tests/test_data_folder_wipe.py` 的假 `conversation` 改成接受关键字参数（新加了可选参数，假对象太严会报 TypeError；不是行为变化）。

旧代码上的结果：
- `stage3-new-tests-on-old-code.log`：`test_open_speed.py` 6 项里 4 项失败（gzip 三项 + 30 秒后重新找端口）。
- `stage3-history-tests-on-old-code.log`：`test_history_projection.py` 12 项里 1 失败、3 错误（lite 参数不存在、`enrich` 不接记录、`MAX_TRANSCRIPTS` 不存在；「最终回答按轮次配对」旧代码本来就对，作为回归测试保留）。
新代码上的结果：两个文件 18 项全过；相关的 129 项（`test_live_history`、`test_deepseek_control`、`test_new_deepseek`、`test_deepseek_stream`、`test_activity_records`、`test_relay_controller` 等）全过。
安卓：`build.ps1` 默认全跑通过，单元测试 **218 项全过**。
全部 Python：`793 项，6 跳过，22 出错`（就是基线那 22 项，逐行相同，没有新增失败）。

实测（同一台电脑、文件已在系统缓存里，两次相差不大；脚本和原始输出在 `20261116-approvals-scroll\probe_*.py`、`probe-*-results.jsonl`）：

| 对话 | 第一次打开（改前） | 第一次打开（改后） | 已读过（改后） | 一页大小 | lite 一页 | lite + gzip |
|---|---|---|---|---|---|---|
| Claude 114.4 MB（3915 条消息） | 1310 ms | **974 ms** | 2.1 ms | 68.5 KB | 33.6 KB | 8.2 KB |
| Codex 388.1 MB（2033 条消息） | 2181 ms | **1400 ms** | 2.2 ms | 138.1 KB | 39.8 KB | 9.1 KB |

- 页里最大的字段确实是 `result`、`detail`（Claude 一页 19.4 + 14.9 KB，Codex 70.5 + 27.2 KB），lite 去掉后正是手机不存的那部分。
- 每行只解析一次后，`projection_full_ms`：Claude 1201→898 ms，Codex 1966→1376 ms；Codex 的最终回答比对原来随数量平方增长，388 MB 那个从 0.21 秒降到测不出来。
- 内存峰值（整个探针进程）Claude 284 MB、Codex 837 MB，与改前相同。

没做（文档 4.3.5 列的，留给你以后定）：
- 从文件尾部先出第一页（id 依赖全量解析）；实时流第一帧不再重复整页；电脑和中转之间保持几条连接；手机先显示本机缓存再刷新；中转权限检查缓存；iOS Markdown 结果缓存。
- 中转服务器要用户自己在 Workbench 更新后，`Accept-Encoding` 转发才生效；电脑端先改好不影响现在的中转。
- iOS 只写了 `Relay.swift` 的两处查询参数，**没编译**。

提交编号：见 9.7。

### 9.4 阶段四：Claude 淡色旧消息（影-1、影-2）

改动（iOS）：
- `ChatCore.swift`：`LiveFrame` 加 `hasMore`、`nextCursor`（快照的 `has_more`/`next_cursor`）和公开构造器；`StreamReducer` 在快照帧里读出这两个字段。
- `AppModel+Reading.swift` 的 `apply`：快照和现有列表一个 id 都对不上时，用快照替换列表并按快照设 `olderAvailable`、`cursor`、`newerAvailable`；`anchor != nil`（查找消息停在历史页）时不再把实时/快照的最新几行接在下面；页面字段（上下文环）的更新移到这之前，历史页也能更新。
- `Outbox.swift`：加 `claudeCheckTextNote`（`_claude_check_text`）；`已移除` 加进不画的名单；Claude 的 `已送达` 超过 60 秒不再画（画不画以记录为准）；按文字对照时优先用电脑写进记录的原话（引用、只发图片、6000 字截断都能对上），没有才用手机自己的文字。

改动（电脑端）：`chats.py` 的 `_queue_remove`：都匹配不上时去掉最老的一个空排队项（运行中发带图片的消息会先留一个空项，之前一直留到下一个 /compact）。

新测试：
- `OutboxTests`：`已送达` 一分钟内还画、超过一分钟不画（`已接收` 仍等）；`已移除` 不画；带引用、只发图片、6000 字截断三种都按 `_claude_check_text` 对上；原来 139-140 行「列表是整份记录就画出来」的假设改成「已送达超过一分钟以记录为准」。
- `AppModelTests`：第一页没读成、随后快照一个 id 都对不上时，列表换成快照、`olderAvailable`/`cursor` 跟着快照，outbox 因此为空；快照有共同 id 时只合并、不动分页；`anchor != nil` 时实时帧不把最新几行接在历史页下面。
- `test_claude_send.py` 的 `QueueShadowTests.test_an_unmatched_removal_takes_the_oldest_empty_part_away`。

结果：
- Python：`test_claude_send` 60 项全过；全部套件 `794 项，6 跳过，22 出错`（与基线相同的 22 项，没有新增失败）。
- iOS：只写代码和 TeleplyCore 测试，**没编译**（本机没有 Swift 工具链）。
- 安卓：这一阶段没改，沿用阶段三的 218 项全过。

没做：
- iOS 真机上「第一页请求失败」的复现要等新版本装好后照 7.2 做；手机没日志，没法在本机坐实是哪一次请求失败（文档 3.4 已说明）。
- 电脑端排队清单的另一个小毛病（Claude 运行中发带图片的消息会先写一条空排队项）只按文档改了 `_queue_remove`，没有改写入端。

### 9.5 和代码对不上的地方（只记，没改原文）

- 文档 4.1 批-3 的两个版本号（`thread-follower-set-queued-follow-ups-state`、`thread-queued-followups-changed`）仍按「只核实」处理：`TESTED_APP_VERSION` 还是 `26.1007.2314.0`，等 5.1 实测 26.1106 后再改。
- 文档 4.3 慢-3 说「先核对 `call()` 现在是不是已经这样」。实际情况：`call()` 失败时只是把 `checked` 置 0，连接还留着；旧 `connection_info()` 的 30 秒有效期会让下一次调用重新找，所以失败路径本来就大致能用。这次把它改成显式清空连接。
- 文档 4.4 说 `OutboxTests.swift:139-140` 的假设要改：那条断言在 11-16 的代码里是 134–141 行（行号有漂移），已按说明改掉。
- 文档 4.2 说 iOS 要在演示数据里加一个「会持续出字的对话」并加 `TeleplyUITests` 场景：`DemoTransport` 目前没有实时流接口，加它要改演示传输和 UI 测试，本机又没法编译，所以没加（见 9.6）。
- `apps/android/README.md` 说 Codex 批准显示「请在电脑上处理」，现在电脑端对还不能答的请求会回 `answerable:false` 的卡片，手机显示「请在电脑上处理」；能答的两种显示「允许一次 / 拒绝」。文档 3.1 提到的这段 README 描述已过时。

### 9.6 没做

- 没 push、没打包、没改版本号、没发版；没动中转服务器、苹果后台、Codemagic、TestFlight、Obsidian。
- 5.1 真实 Codex 批准的抓取、从手机点「允许一次」、批-3 的版本核实：要用户和 Claude 一起做，本会话没有触发 Codex。
- 5.2 真机验证：等新版本装上后由用户照 7.2 做。
- 阶段二 iOS 的演示流和 UI 测试（原因见 9.5）。
- 阶段三文档 4.3.5 列的：尾部分页、实时首帧去重、常驻连接、手机先显示缓存、中转权限缓存、iOS Markdown 缓存。
- 阶段一网页的正式批准卡片（可选项；兼容 `questions` 已能让网页画出提问）。
- Playwright 的 22 项仍缺浏览器（与基线相同），没有为了跑它们去装浏览器。

### 9.7 提交

`main` 上本地提交，一个文件一个文件 `git add`，都没有 push：

- 阶段一（Codex 批准）：`3cc2392`。
- 阶段二（滚动）：`9116cf0`。
- 阶段三（打开速度）：`3e92106`。
- 阶段四（淡色重影）：`3a50d89`。
- 收尾：紧接本次的一个只改本文件的提交，把阶段四编号补进来（就是上一次提交 `3a50d89`；这次提交本身只改本节）。

工作区 `F:\Android-Dev\work\20261101-island-duplicates\20261116-approvals-scroll\` 里留了：两次旧代码基线日志、四个阶段的全量测试日志、安卓构建日志、`probe_*.py` 和 `probe-*-results.jsonl`（测速原始数据）、`old-tree\`（旧代码副本，用于基线）。仓库里除了这些提交没有留下临时文件。

### 9.8 Claude 复核和云端编译（11-16 下午）

- 四个阶段 Claude 逐个复核过：阶段一的兼容字段核对了 iOS 0.7.3、安卓 1.0.6 的旧代码（`questions` 里 pending 的卡片都会画、答案按选项文字回传）；阶段三用改前改后两份代码解析同样六份真实记录（Claude 7–125 MB、Codex 94–407 MB），全部消息和最新一页逐字节相同，解析快 26%–33%；全部 Python 794 项、22 个老错误，没有新失败。
- 推送到 GitHub 后在 Codemagic 跑 `ios-native-check`（compile）三次：
  - `6afa8d5b`：编译失败，`OutboxTests.swift` 新测试里 `send()` 的参数顺序错（`created` 要在 `app` 前）。同时读代码发现 `CodexApprovalCard.submit` 把 `String` 直接放进 `JSONValue` 数组，应用编译到那里也会错。两处在 `95bccec` 修好。
  - `6afa8ef7`：跑满 45 分钟超时。`ChatModelTests.aSendCountsOnceSoThePageFollows` 发送后没开假电脑 `CommandComputer` 的闸门就 `settleSends()`，一直等。日志在被杀时截断，其余「没结束」的测试多半只是结果没写出来；这一轮里其它新测试（批准卡片、outbox 三条、ReadingFollow、500MB）都已通过。`b91fb76` 补上 `computer.gate.open()`。
  - `6afa9aac`：**通过**，3 分钟。`TeleplyCore` 272 项测试（36 组）全过，应用 Debug 构建成功（`ConversationView.swift`、`QuestionCards.swift` 都编到了；有 3 个 `onChange(of:perform:)` 已弃用的警告，不影响）。
- 还没做：iOS 0.7.4 版本号和 TestFlight 上传（等用户同意）；5.1 真实 Codex 批准；7.2 真机验证。
