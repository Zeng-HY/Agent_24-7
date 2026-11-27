# 11-27 运行计时多出 40 多秒：电脑钟慢，以中转的钟为准校正

这份文件给一路 DeepSeek（电脑），分支 `pc60`，工作树 `D:\Personal\agent_remote_lanes\pc60`，起点 agent-registry ae3bc1d（dev.59）。版本由合并的人改，这一路不改版本号。下一版 Windows dev.60。手机端不用改。

## 1 查到的事实

- 用户反映：手机和网页上，各家助手的「运行中 · N 分 N 秒」好像总不是从 0 开始，而是多出 30 秒到 1 分钟。
- 2026-11-27 13:10，用 `w32tm /stripchart` 对了两台标准时间服务器（ntp.aliyun.com、time.windows.com），**这台电脑的钟比标准时间慢 46 秒**。11-17 对的时候慢 19 秒，钟一直在越走越慢。
- 原因：Windows 的时间服务 W32Time 是停着的（Stopped，启动方式 Manual），没有自动校准。
- 计时的算法：电脑发给手机的 `turn_started`（秒）等时间，取自 Codex、Claude 等的记录，用的是这台电脑的钟；手机拿自己准的「现在」去减它。
  - iPhone：`IslandWords.runningLine(started:now:)`，`now` 取自 `TimelineView` 的 `context.date`，见 `ChatRows.swift` 的 `RunningStatus`、`ThinkingRow.swift`；
  - 安卓、网页做法一样；
  - 锁屏上灵动岛的计时，起点也是电脑给的时间。

  所以每一轮都平白多出 46 秒。别的用户的电脑如果钟不准，也会这样。
- 顺带：11-27 10:39:04，`notify.py` 的通知线程在 `agents/antigravity.py` 的 `notify_poll` 里，执行 `datetime.fromtimestamp(started)` 时报 `OSError: [Errno 22] Invalid argument`，被接住了，日志记成「通知：读对话出错」。
  - `started` 来自 `turn_started`，`turn_started` 由 `_seconds(last_user_input_time)` 算出；
  - 很可能某条记录的时间是「0001-01-01」这类占位值，换算出一个很大的负数，Windows 的 `fromtimestamp` 就会报这个错。

## 2 要做的

### 2.1 以中转的钟为准，算出这台电脑的钟差

1. 电脑和中转之间一直有连接：`relay_agent.py`，`aiohttp` 的 `ClientSession`，打开 `/tunnel/connect` 和每个请求的 `/tunnel/stream/<id>`。中转每次回答都带 HTTP `Date` 头。
2. 在这个 `ClientSession` 上挂一个 `aiohttp.TraceConfig`，用 `on_request_end` 读每次回答的 `Date` 头（秒级精度），算一个样本：样本 = 中转时间 − 本机收到回答时的时间。
3. 新模块 `pc_clock.py`：
   - 保留最近 15 个样本，取中位数作为「钟差」（秒，可正可负）；
   - 钟差的绝对值小于 3 秒时当作 0，不校正；
   - 钟差变化超过 2 秒才更新，并在日志写一行，只写数字：`时钟：这台电脑比中转慢 46 秒，发给手机的时间已校正`（快就写「快」）；
   - 没有样本时钟差为 0，行为和现在完全一样。
4. 不新开任何网络连接，不访问时间服务器，不读 `remote_config.json`，也不改系统时间。

### 2.2 发给手机、网页和灵动岛的「开始、结束」时间加上钟差

只校正**拿来和手机的「现在」相减**的那一族时间。它们彼此之间也会相减，所以要成套一起校正，时长才不会变：
- `turn_started`、`turn_ended`：列表行、对话状态、控制状态、实时推送帧，以及消息上带的；
- `compact_started`；
- 11-27 新加的 `command.since_ms`（毫秒）；
- 通知和灵动岛事件里的开始、结束时间（`notify.py` 发给中转的 `started`、`ended` 之类，自己找全）。

做法：
- 在这些字段**发出去的地方**统一加钟差。写一个 `pc_clock.to_true_seconds(value)`，毫秒用 `to_true_ms`；
- 值为 0 或空时原样不动；
- 电脑内部的判断（和 `time.time()` 比、判断卡住、过期等）一律用原始值，不要改。

**不改**的东西：
- 消息的 `time`（ISO 字符串）、`created`、`accepted_at`、送达记录的时间。这些主要彼此比较，比如发送记录的 `created` 配消息的 `time`。差 46 秒对「N 分钟前」这种显示影响很小，而只改一半会让配对出错。
- 用 `grep -rn "turn_started\|turn_ended\|compact_started"` 找全发出点，在结果里列出你改了哪些地方。

### 2.3 Antigravity 的时间换算

1. `agents/antigravity.py` 的 `_seconds`、`_millis`：换算结果早于 1971 年，或者小于等于 0 时，返回 0。
2. `notify_poll` 等所有对 `turn_started` 调 `datetime.fromtimestamp` 的地方：值不在合理范围内（小于等于 0，或者大于 4102444800）时按 0 处理，不报错。顺手查一遍其他助手的同类调用。
3. 测试：「0001-01-01」这类占位时间得到 0；通知线程遇到它不报错。

### 2.4 测试

- `pc_clock`：
  - 用假的样本：中位数、3 秒门槛、变化超过 2 秒才更新、没有样本时为 0；
  - 用假的 `Date` 头喂 `on_request_end` 的处理函数。
- 校正：钟差设成 46 秒时，列表行、控制状态、实时帧、通知事件里的 `turn_started` 和 `turn_ended` 都加了 46 秒，并且两者之差不变；钟差为 0 时输出和现在逐字节一样。
- `tests/test_action_golden.py` 必须通过；钟差为 0 时 golden 不变。
- 跑相关测试文件，最后跑一次全量 pytest。已知 3 个老失败：`test_mobile_polish` 的 snippet 测试 webkit 和 chromium 各一个、`test_relay_mobile_layout` 的 account home。

## 3 规矩

照 `docs/handoff-1126-fixes.md` 第 9 节。再加几条：
- 绝不操作正在运行的遥应电脑端、Codex、Claude；
- 不读真实记录、日志、`remote_config.json`；
- 不改系统时间，不启动、不配置 Windows 时间服务，这件事由用户决定。

## 4 结果

结论：第 2.1、2.2、2.3 节都做完了。钟差为 0 时所有输出和原来逐字节一样（`tests/test_action_golden.py` 通过，golden 没有重新生成）；新增 31 个测试全过；相关测试文件全过；全量 pytest 1696 通过、7 跳过，只剩那 3 个已知的老失败。审后补了过程卡片那一族（下条 `f95c375`）。

**做了什么**

第 2.1 节（commit `ce5eb49`）：
1. 新模块 `pc_clock.py`。`Clock` 保留最近 15 个样本，取中位数为钟差；绝对值小于 3 秒当作 0；和已公布的钟差相差不超过 2 秒就不动，超过才更新并写一行：慢 `时钟：这台电脑比中转慢 46 秒，发给手机的时间已校正`，快写「快」，回到 0 写 `时钟：和中转的时间对上了，不再校正`。只有数字，没有标题、没有消息文字；写日志失败不影响连接。
2. `relay_agent.Agent.run` 的 `ClientSession` 挂一个 `aiohttp.TraceConfig`，`on_request_end` 读每个回答的 HTTP `Date` 头（秒级）：样本 = 中转时间 − 本机收到回答时的时间。日志接到本 Agent 的 `LinkLog.write`（`test_http` 里没有 link 就不写）。
3. 没有新开连接、没有访问时间服务器、没有改系统时间、没有读 `remote_config.json`、没有碰 Windows 时间服务。
4. 只从 `/tunnel/connect` 和每个 `/tunnel/stream/<id>` 的握手回答取样；`Date` 是秒级、且有往返延迟，样本本身有最多约 1 秒的误差，3 秒门槛把它吞掉。

第 2.3 节（commit `fc5884d`）：
1. `agents/antigravity.py` 的 `_seconds`、`_millis`：换算结果早于 1971-01-01（含小于等于 0）时返回 0，并接住 Windows 上的 `OSError`/`OverflowError`（原先只接 `TypeError`/`ValueError`）。一条 `0001-01-01` 的行现在 `turn_started` 是 0，不再是 -62135596800。
2. 新增 `notify.time_text`：小于等于 0、大于 4102444800、或不是整数一律当「没有时间」返回空串，只有合理值才调 `datetime.fromtimestamp`。`agents/antigravity.py`、`agents/deepseek.py`、`agents/testing.py` 的 `notify_poll` 都改用它——全仓库直接对 `turn_started` 调 `datetime.fromtimestamp` 的就是这三处。
3. 顺手查过其它同类调用，不用改：`chats.py` 的 `datetime.fromtimestamp(since - 1)` 用的是 `time.time()` 派生的查询下界；`live_events.py` 用的是 Codex 自己窗口里的 `turnStartedAtMs`；`deepseek_stream.py` 用的是事件时间，都只做 ISO 文本，不参与计时。

第 2.2 节（commit `c5a2e29`）：在下面这些「发出去的地方」统一加 `pc_clock.to_true_seconds`（`command.since_ms` 用 `to_true_ms`）。开始和结束一起加，所以差值不变；值为 0、`None`、空串或不是数字时原样返回；电脑内部的判断一律用原始值（`chats.summary_for` 的输出、`claude_control._hook_status` 里 hook 与记录的比较、`compacting_now`、列表排序、`used_text` 都是原值）。

**改了哪些发出点**

- 列表行：`chat_history.conversations`（`/api/chats` 每行）的 `turn_started`、`turn_ended`；`chats.list_conversations`（任务汇总的行，同一族，虽然现在没有路由直接用它）。
- 对话页：`chat_history.conversation` 的页面 `turn_started`/`turn_ended`，以及每条消息上带的 `turn_started`/`turn_ended`（由 `activity_turns` 的 `started_at`/`ended_at` 换算成秒后加）。
- 控制状态（`/api/chat/state`，同时也是实时帧里的 `control`）：
  - `codex_control.Bridge.status`：`turn_started`、`turn_ended`、`compact_started`（legacy 路由）；
  - `codex_apptools.AppToolsBridge.status`：同样三个（apptools 路由）；
  - `codex_apptools.command_state`：`command.since_ms`（毫秒）；
  - `claude_control.Controller._held`：`turn_started`、`turn_ended`（`state()` 的每个返回都经过它，动作回答里的 `state` 也是）；
  - `deepseek_control.Bridge.state`：`turn_started`、`turn_ended`、`compact_started`；
  - `agents/antigravity.py` 的 `state()`：`turn_started`、`turn_ended`。
- 非文件型助手的对话页：`deepseek_control.Bridge.conversation`、`agents/antigravity.py` 的 `read()`。
- 过程卡片（`activity_turns`，毫秒；审后补的 `f95c375`）：`chat_history.conversation` 发出去的 `activity_turns[*]` 里 `started_at`、`ended_at`、`paused_at` 和 `pauses` 里每一段的起止，用 `to_true_ms` 一起平移（`chat_history.true_activity_clock`）；`paused_ms` 是时长，不动。网页的过程卡片就是拿它们减 `Date.now()`（`static/interaction-ui.js:91`）；`/api/chat` 和实时帧的 `meta.activity_turns` 都来自这一处，只加一次，`entry` 里留着的那份仍是原始值。
- 通知和灵动岛事件（`notify.py` 发给中转的 Feed）：`_tell`（完成/失败/在等你选，`asking()` 也走它）的 `started`、`ended`；`_running` 的 `since`、`started`；`_step` 的 `since`；`_snapshot` 里每个 running/waiting 项的 `since`、`started`。各助手的 `notify_poll` 只把原始值交给这四个出口，没有各自再加。

**没有改的，和原因**

- 消息的 `time`（ISO 字符串）、`created`、`updated`、`accepted_at`、送达记录的时间、文件的 `modified`：按第 2.2 节不动；它们主要彼此比较（发送记录的 `created` 配消息的 `time`）。
- `notify.used_text`（「用了 N 分钟」）和 `notice_state`：两者相减，钟差抵消，改了反而多绕一圈。
- `claude_hooks` 里自己记的 `turn_started`/`turn_ended`：只做内部比较（手工 Stop 与记录对照），不直接发给手机；经 `claude_control._held` 出去时才加。
- `agents/testing.py` 的 `state()`/`summary()`：`TELEPLY_TEST_AGENTS=1` 才加载的测试专用假助手，不是真实的发出路径。
- 中转侧（`relay_push.py`）没改：它只用事件里 `started`/`ended` 的差算「用了 N 分钟」和岛的起点，差值我们已经保证不变。

**测试**

- 新增 `tests/test_pc_clock.py`（13 个）：没有样本为 0；中位数；3 秒门槛；变化不超过 2 秒不动、超过才动；回落进门槛后不再校正；每次变化只写一行且只有数字；写日志抛异常不影响；0/空值/字符串原样；开始与结束的差不变；假 `Date` 头喂 `on_request_end`；没有 `Date` 头不取样；真 aiohttp 回答走同一个 `TraceConfig`；`Agent.run` 确实建了带这个回调的 `ClientSession`。
- 新增 `tests/test_clock_correction.py`（13 个）：钟差 46 秒时，列表行、任务行、控制状态（运行/完成/压缩）、通知事件（done/running/step/snapshot）里的开始、结束都加了 46 秒且差值不变；过程卡片的 `started_at`、`ended_at`、`paused_at`、`pauses` 都加了 46 000 毫秒，`ended_at - started_at - paused_ms` 不变；钟差为 0 时列表行、事件和过程卡片逐字节是原来的值。
- 第 2.3 节新增 5 个：`tests/test_antigravity.py` 3 个（占位时间得到 0、真时间照旧、通知线程遇到它不报错）、`tests/test_notify.py` 2 个（`time_text`）。
- 相关测试：`test_antigravity` + `test_notify` + 上面两个新文件 183 通过（5 subtests）；`test_action_golden`、`test_summary_turn_timer`、`test_chats_visible_apps`、`test_codex_status`、`test_live_history`、`test_read_golden` 47 通过；Claude 的 5 个文件 191 通过（2 subtests）；Codex/DeepSeek/agents 的 5 个文件 255 通过（36 subtests）；中转的 6 个文件 113 通过、5 跳过（4 subtests）；过程卡片改动后又跑了 `test_activity_records`、`test_live_history`、`test_history_cache_speed`、`test_history_projection`、`test_chat_delegation`、`test_action_golden`、`test_read_golden` 51 通过，`test_claude_hooks`、`test_claude_record_repeats`、`test_summary_turn_timer`、`test_codex_hooks` 122 通过。
- 全量 pytest（19 分 16 秒）：1696 通过、7 跳过、136 subtests 通过、3 失败，就是已知那 3 个（`test_mobile_polish` 的 snippet webkit 和 chromium 各一个、`test_relay_mobile_layout` 的 account home），和其它改动无关。这次全量是在审后补过程卡片之前跑的；按你说的，补完没有再跑全量，只跑了上面那些相关文件。

**改了哪些文件**：`pc_clock.py`（新）、`relay_agent.py`、`chats.py`、`chat_history.py`、`codex_control.py`、`codex_apptools.py`、`claude_control.py`、`deepseek_control.py`、`agents/antigravity.py`、`agents/deepseek.py`、`agents/testing.py`、`notify.py`、`tests/test_pc_clock.py`（新）、`tests/test_clock_correction.py`（新）、`tests/test_antigravity.py`、`tests/test_notify.py`、本设计第 4 节。没有改版本号和更新说明。

**要我看的地方**

1. 钟差是秒级 `Date` 头算的，46 秒会落在 45.5～46 秒之间（中位数），门槛之内的抖动不会写日志。
2. 钟差只在连上中转、收到回答之后才有样本；进程刚起来还没连上时是 0，行为和现在一样；连上过之后即使掉线也保持最后一次的值（进程内）。
3. 钟差变化的那行日志会进当天的日志文件，一行一次，只在变化超过 2 秒时写。
4. 过程卡片的平移也把 `pauses` 里每一段的起止一起加了（只加一端会让暂停时长对不上）；`paused_ms` 是已经算好的时长，没有动，网页那张卡的时长不受影响。

