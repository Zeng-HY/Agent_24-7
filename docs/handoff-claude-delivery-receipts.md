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
- 两条为什么没认出来：
- 提交：
- 测试数字（基线 / 改后 / 完整 pytest）：
- 需要 iOS 改的地方（如果有）：
