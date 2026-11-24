# 交接：iPad 发给 Claude 的消息已经送到，却一直「送达状态待确认」

2026-11-24 晚，主会话设计，交给 DeepSeek 先查后修。分支 `claude-delivery-receipts`（从 agent-registry 的 6ae0ea7 开），工作树 `D:\Personal\agent_remote_lanes\rcpt`。

## 现象

- 设备：iPad mini，iOS 遥应 TestFlight 0.8.0 (33)。源码在 `ipad-adapt` 分支，工作树 `D:\Personal\agent_remote\.claude\worktrees\ipad-adapt\apps\ios`。电脑端装的是 Windows dev.52（a101ba1）。
- 22:23 用户在一个 Claude 对话里发了一条带两张图的消息；22:32 Claude 正在跑命令时，又发了一句带一张图的补充。
- **两条都送到了**：
  - 第一条，模型当作普通的用户消息收到（带两张图，走的是操作窗口那条路）；
  - 第二条，是 dev.52 的钩子在工具调用之后作为「插话」交给模型的，文字是「用户刚在手机上补充（遥应）：……[附图] <电脑上图片的路径>（请先用 Read 工具打开这张图片）」。
- 但 iPad 上两条都显示「送达状态待确认」，顶上一直是「上一条送达状态待确认 / 核对待发送消息」，按「核对待发送消息」也没用（截图见主会话，22:32）。
- 电脑日志（时间是电脑时钟）：`22:23:50 codex request=78412ec9-4b8c-4311-bc70-cefd3a7803e7 state=accepted … elapsed_ms=94`、`22:32:40 codex request=6702f872-31da-4435-a007-3319ac51ede4 state=accepted … elapsed_ms=332`。
- 主会话试过 `GET /api/claude/receipt?id=<对话>&request_id=<上面的 id>`，装着的 dev.52 回 404。可能地址不对（还有 `/api/agents/claude/...` 的统一地址），也可能这个地址确实没有。

## 要查清的问题

1. iPad 怎么判断「送到了」：看 `ipad-adapt` 的 iOS 代码（只读，不改）。
   - 找「送达状态待确认」「核对待发送消息」出现的地方，看它请求哪个电脑地址、带什么参数（`client_request_id`、`request_id` 等），拿回来认哪些字段（`delivery_kind`、`source_id`、`client_request_id`、文字匹配、`[图片]` / `[N 张图片]` 标记……）。
   - 看 `SentPictures.swift` 这类认图片消息的逻辑。
2. 电脑怎么回答这个判断：
   - 找到对应的地址和函数，比如 `agents/claude.py` 的 `http_receipt`、`chats.py` 或别处的 check / 回执；
   - 再看 dev.52 钩子交出的插话、排队（提交 90b8290「送达回执认这两种」）在记录里是什么样、回执怎么认。
3. 为什么这两条认不出来：
   - (a) 走窗口发的、带图片的普通消息；
   - (b) 钩子交出的、带「[附图] 路径」的插话。

用编造的记录复现：写一个假的 Claude 记录 JSONL，按真实结构放进这两种消息，调用电脑端的判断函数，看它回什么。

## 怎么改

- 尽量只改电脑端，这样不用发新的 iOS 版。让 iPad 现有的判断能认出这两种消息已送到，并加测试。
- 如果非改 iOS 不可：iOS 代码一行都不改，在「结果」里写清楚要改哪个文件、哪个函数、怎么改，以及为什么电脑端解决不了。
- 别影响老手机、安卓和网页：它们收到的现有字段只能加，不能改、不能删。两份标准答案测试必须原样通过。

## 边界

- 可以改：`agents/claude.py` 里回执相关的函数、`chats.py` 里回执或核对相关的函数、`claude_hooks.py` 里交出插话、排队的记录方式（只在确有需要时），以及 `tests/` 下的测试。
- 尽量别动：`claude_control.py`、`chat_history.py`（另有两条线在改；真要改，只动跟回执有关的独立函数，并在结果里写明）。
- 不改：`remote.py`、`codex_*.py`、`relay_*.py`、`static/`、`apps/`（iOS、安卓都不改）、`tests/fixtures/*`、`tests/conftest.py`、版本号和更新说明文件。
- 真实数据：可以用脚本读这台电脑上真的 Claude 记录来核对结构，但只许打印个数、真假、字段名，不许打印对话内容、标题和图片路径。不打开 `remote_config.json`。

## 验证

- 新测试：
  - 带图片的窗口消息被认作已送达；
  - 钩子插话、排队（带图和不带图）被认作已送达；
  - 没送到的消息照旧是「待确认」。
- 相关的现有测试（回执、`test_claude_hooks.py`、统一地址、两份标准答案）：改前跑一遍记基线，改后通过。
- 最后跑一遍完整 pytest。已知会失败的 3 条：`test_mobile_polish` 两个引擎各一条、`test_relay_mobile_layout` 一条；`test_relay_push` 在电脑忙时偶尔超时，单独重跑会过。

## 发版

不升版本号、不打包、不推送。主会话合并后打进 dev.53。

## 结果（DeepSeek 填）

- iPad 怎么判断、电脑怎么回答（各写清函数和字段）：
  - iPad（`ipad-adapt` 的 `apps/ios/TeleplyCore/Sources/TeleplyState/ChatModel.swift`，只读）：Claude 的发送没有回执，只看它的记录。
    - `dispatch()`：答复里 `pressed` 为真时，把答复里的 `offset`、`check_text` 存进这次发送的 body（`_claude_offset`、`_claude_check_text`），标签写「已接收」，再起 `confirmClaude()`。
    - `confirmClaude()`：1.5 秒问一次、约 25 秒；`claudeCheck()` 发 `POST /api/chat/check`，body 是 `{app:"claude", id, offset, text}`，只认 `delivered`（已送达）和 `queued`（已排队）两个字段。
    - 之后每 5 秒的 `poll()`（`claudePending()`）和重新进对话时的恢复会再问一遍，但只挑 body 里**有 `_claude_offset`** 的发送；「核对」按钮走 `check()` → `reconcile()`，Claude 的发送同样要 `_claude_offset`，没有就直接返回、什么都不问。
  - 电脑：`remote.py` 的 `/api/chat/check` → `chats.Desktop.check(app, tid, offset, text)`（先 `clean_text`）→ `agents/claude.py` 的 `desktop_check()` → `chats.claude_delivery_stage(path, offset, text)`，回 `{delivered, queued, stage}`。`claude_delivery_stage` 从发送前记下的文件位置往后逐行看：钩子记录（`_teleply_hook_text`）、插话（`_claude_steer_message`）、`type=user`、`queue-operation` + `enqueue`。
- 两条为什么没认出来：
  - 手机上那两条在电脑的投递台账（`attachments/delivery.sqlite`）里是：`78412ec9…`（22:23:50，两张图、没有文字）和 `6702f872…`（22:32:39，一句话加一张图）。两条的答复都有 `pressed`、`offset`、`check_text`（走的是排队 `_hook_queue_send`，94 ms / 332 ms，没有窗口操作，当晚只有 22:23:23 一次窗口发送）。
  - 第二条（`6702f872…`）：22:32:59 以 `attachment/hook_additional_context`、文字带 `[附图] <路径>（请先用 Read 工具打开这张图片）` 落地。拿手机存下的 offset（86116665）和文字（check_text 71 字）真跑一遍 `chats.Desktop.check`，回 `delivered: true`——它的记录和电脑的回答今天都对，22:32 的截图是在记录落地之前 20 秒拍的，之后按手机每 5 秒一次的 poll 应该会自己变成「已送达」。这一条我找不到电脑端还要改的地方（答复里有手机需要的全部字段），所以它一直显示「待确认」只剩设备侧的可能（答复没到、poll 没跑），见最后一节。
  - 第一条（`78412ec9…`）：两张图、没有文字，排队交给钩子。这条在记录里根本找不到——22:23:50 之后那整份 87 MB 记录没有任何一行含「请查看这些图片。」或那两张图的路径（`claude-images` 里存的是 `05daf6e8…`、`e16a8f20…`）；队列文件 `claude-queues/…json` 里 queue/steer 都空了，`recent` 里有它（入队时就写，不能证明交出去了）。所以电脑如实回 `unknown`，「核对」也就无从说起：这条是投递侧（Stop 交接）没落地，不是回执判错，回执这边没法把它变成「已送达」。
  - 设计里「第一条带两张图、走窗口那条路」在这台电脑上对不上：当晚 `发给 Claude` 的窗口发送只有 22:23:23 一条（1.4 秒，纯文字；记录里 22:23:23 那条 141 字 user 记录的正文开头就是日志里那句话），它自己能认出来；22:29:15 那条带两张图的 user 记录，两张图（base64 237410 + 162797 字节）跟手机上传的两张（213922 / 151200 字节）不是同一份，投递台账 277 条里也没有一条的文字等于它——那条不是手机发的。
  - 真正的代码缺口（回执/核对），两个：
    - 交接写成「用户自己的话」这种形状：`用户在手机上发来下一条消息（遥应）：…` / `用户刚在手机上补充（遥应）：…`，带图时后面还跟着我们自己的 `[附图] <路径>（…）` 行。`claude_delivery_stage` 对 user 记录是整行相等比对，前缀和附图行都在，永远对不上（90b8290 只认了钩子附件那种形状）。带图的排队消息正好落在这一条上，所以就算落地也一直是「待确认」。现在先去掉我们自己的前缀和附图行再比，并且只在记录行确实以我们的前缀开头时才这么做（摘要、工具输出里引用到我们的话不算）；钩子一次交出好几条时，在去掉前缀后的那段里找。
    - 「立即补充」的答复（`claude_control.py::send_steer`）带 `offset`、`check_text`，却没有 `pressed`：iPad 和安卓据此不存 `_claude_offset`、不起 `confirmClaude`，之后的 poll 和「核对」都不会去问，这条路上的补充永远停在「待确认」。已在 `agents/claude.py` 补上（只加字段，老字段不动，老手机、安卓、网页照旧；网页本来就用 `offset` 自己核对）。

- 提交：本分支最新一条，标题是「Claude 送达回执：钩子交回的排队/补充写成用户自己一行时也认得出，补充的答复带上核对所需的位置」。改了 `chats.py`、`agents/claude.py`、`tests/test_claude_send.py`、`tests/test_claude_hooks.py`、`tests/test_unified_routes.py` 和本文档；没碰 `claude_control.py`、`chat_history.py`、`remote.py`、`static/`、`apps/`、`tests/fixtures/*`、`tests/conftest.py`、版本号和更新说明。
- 测试数字（基线 / 改后 / 完整 pytest）：
  - 基线（`tests/test_claude_send.py test_claude_hooks.py test_unified_routes.py test_action_golden.py test_read_golden.py`）：116 通过、1 失败——`test_claude_hooks.py::Address::test_only_claude_code_with_the_hook_key_gets_in`（`ConnectionResetError`，单独重跑通过）。
  - 改后同一组：121 通过、0 失败（117 + 4 条新测试）。
  - 完整 pytest：1240 通过、6 跳过、3 失败，正好是设计里已知的那 3 条（`test_mobile_polish` 两个引擎各一条、`test_relay_mobile_layout` 一条）。注意本机 `%LOCALAPPDATA%\ms-playwright` 没有浏览器，浏览器测试要带 `PLAYWRIGHT_BROWSERS_PATH=D:/Personal/agent_remote_lanes/ms-playwright` 才会跑；不带的话 30 条浏览器测试全部起不来。
- 需要 iOS 改的地方（如果有）：没有必须的（这次只改电脑端，iPad 现有的判断就能认出来）。三点，不改也能用：
  - 第二条那个「一直待确认」：电脑的答复（`pressed`、`offset`、`check_text`）和记录都对，剩下的可能只在设备侧——那条答复没到手机上（丢了就只会写「待确认」、没有 `_claude_offset`），或者 poll/`confirmClaude` 那段时间没跑（退到后台、被系统挂起）。要在手机上确认，可看那次发送在本地记录里的 body 有没有 `_claude_offset`；没有的话就是答复没落地。
  - `claudeCheck()`：记录里没有 `_claude_offset` 时（比如发送的答复丢了）它直接返回，「核对」就什么都不问。如果想在这种情况也能核对，可以退化成 `offset=0`（或最近 1 MB）再问一次 `/api/chat/check`——电脑那边按 offset 往后找，找不到还是 `unknown`，不会误报。
  - 显示：交回成「用户自己的话」的排队/补充，时间线上会露出我们自己的前缀和 `[附图]` 路径（`parse_claude` 只给钩子附件那种形状剥了前缀）；不在这次回执范围，没动。

