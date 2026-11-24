# 交接：Claude 选择卡片——钩子没接住的权限请求，退回桌面点

2026-11-24 晚，主会话设计，交给 DeepSeek 实现。分支 `claude-card-fallback`（从 agent-registry 的 6ae0ea7 开），工作树 `D:\Personal\agent_remote_lanes\cards`。

## 结论

| 现在（dev.51 起） | 要改成 |
|---|---|
| 输入框上方的零散按钮，只有「钩子正接着请求」或「记录里有没答完的 AskUserQuestion / ExitPlanMode」时才算选项，否则全部丢掉 | 再加一种：**记录里 Claude 刚请求运行一个工具、还没有结果，并且按钮看起来就是权限按钮**（允许 / 拒绝之类），也算选项 |
| 钩子没接住的权限请求，手机上没有卡片 | 手机上出现卡片，点了由电脑去点桌面上的按钮（原来的办法） |
| 钩子接住的请求 | 不变：照旧用钩子在手机上回答 |

用户原话：「我的 claude 也是失去了选择卡片的功能……如果 hook 没办法批准，能不能用原先 claude 的逻辑，直接桌面点？但是尽量还是能用 hook 去批准吧」。

## 证据

- `claude_control.py`（a101ba1，`_read` 里约 585 行）：
  ```
  if dock is not None and not chats.question_card(dock) and self.hooks is not None and not self._claude_waiting(item['id'],path):
      prompt=None; result['prompt']=None   # 按钮也不进 actions
  ```
  `_claude_waiting`（约 610 行）= `hooks.layout(tid)` 不为空，或 `has_pending_prompt(path)`（约 144–160 行，只认 AskUserQuestion / ExitPlanMode）。所以钩子没接住的工具权限请求，窗口上的按钮被整个滤掉。
- 这是 dev.51 修「Stop N nested sessions 假卡片」时加的第三道防护。前两道（输入框那块里的控件一律不算；名字含 nested session 或以 Stop 开头的一律不算）要保留。
- 遥应日志：19:27 装 dev.52 后，没有一条「Claude「…」：…，等手机或电脑回答」，也就是 `claude_hooks._handle_permission` 一次都没接住。它在这些情况下会直接放过：工具在 `NOT_HELD`（`ExitPlanMode`）；AskUserQuestion 的问题格式不对；`self.find(session_id)` 找不到对话（最多等 10 秒）。这些情况都没打日志，所以查不到是哪一种。

## 代码位置

- `claude_control.py`：`has_pending_prompt`、`PENDING_PROMPT_TOOLS`、`_dock_read`、`_read` 里的那道门、`_claude_waiting`；手机回答后点桌面按钮的那条路（`action` 票据、点按钮的函数）。
- `claude_hooks.py`：`_handle_permission`（几种直接放过的情况）。
- 测试：`tests/test_claude_fake_prompt.py`（dev.51 的假卡片录制，改后必须原样通过）、`tests/test_claude_hooks.py`。
- 录制资料：`D:\Personal\agent_remote_lanes\20261124-claude\research\`（窗口录制、`hook-records.md`）；`tests/` 里已有的 Claude 窗口录制。从这些资料里找 Claude 桌面版（6.28899）权限按钮实际的名字。

## 怎么改

1. 新增 `has_open_tool_call(path)`：和 `has_pending_prompt` 一样只读记录末尾一段（几百 KB），找最新一条 assistant 记录里的 `tool_use`，看后面的记录里有没有对应 id 的 `tool_result`；有没结果的，返回 True。只要真/假，不改记录。
2. 新增「像权限按钮」的判断：窗口里的按钮至少有一个「允许」类、一个「拒绝」类，名字按 Claude 桌面版实际显示来定（英文和中文都要，比如 Allow / Allow once / Always allow / Deny / Reject、允许 / 总是允许 / 拒绝）。从录制里找实际名字，别凭空猜；找不到就写进结果里。
3. `_claude_waiting` 增加一条：像权限按钮 且 `has_open_tool_call(path)` → 等同于在等用户，放这些按钮进 actions 和 prompt，手机点了走原来的桌面点击。
4. 前两道防护原样保留：假卡片的录制里就算有没结果的工具调用（子对话在跑），nested session / Stop 按钮也不能变成选项。
5. `claude_hooks._handle_permission`：每种「直接放过」的情况各打一行日志，写原因和工具名，不写对话内容和命令全文，方便下次查为什么钩子没接住。不改它接住、回答的逻辑。

## 边界

- 只改：`claude_control.py`（只动上面这几个函数，另有一条线在改 `state()` 那一段，别碰它）、`claude_hooks.py`（只加日志）、`tests/` 下的测试。
- 不改：`remote.py`、`agents/*`、`chat_history.py`、`chats.py`、`codex_*.py`、`relay_*.py`、`static/`、`apps/`、`tests/fixtures/*`、`tests/conftest.py`、版本号和更新说明文件。
- 测试只用编造的数据和已有录制，不读真的 `C:\Users\39011\.claude`，不碰真的 Claude 窗口，不结束进程。

## 验证

- 新测试：
  - 权限按钮 + 有没结果的工具调用 → 出卡片，且带点击票据；
  - 权限按钮 + 工具都有结果 → 不出卡片；
  - 假卡片录制 + 有没结果的工具调用 → 仍然不出卡片；
  - 钩子接住时 → 照旧用钩子的卡片。
- `tests/test_claude_fake_prompt.py`、`tests/test_claude_new_folder_layout.py`、`tests/test_claude_hooks.py`、两份标准答案测试：改前跑一遍记基线，改后原样通过。
- 最后跑一遍完整 pytest。已知会失败的 3 条：`test_mobile_polish` 两个引擎各一条、`test_relay_mobile_layout` 一条；`test_relay_push` 在电脑忙时偶尔超时，单独重跑会过。

## 发版

不升版本号、不打包、不推送。主会话合并后打进 dev.53。

## 结果（DeepSeek 填）

- 提交：
- 权限按钮的实际名字（出处）：
- 测试数字（基线 / 改后 / 完整 pytest）：
- 风险和没做的：
