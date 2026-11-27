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

（待填）
