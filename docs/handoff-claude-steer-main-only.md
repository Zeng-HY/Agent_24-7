# 交接：手机插话只交给主对话，不交给它派出去的助手

2026-11-24 深夜，主会话设计，交给 DeepSeek 实现。分支 `claude-steer-main-only`（从 agent-registry 的 e2c8de6 开），工作树 `D:\Personal\agent_remote_lanes\steer`。

## 结论

| 现在（dev.52） | 要改成 |
|---|---|
| Claude 在跑时，手机上的插话存在遥应的「插话位」，**下一次任何工具调用结束（PostToolUse）**就交出去 | 只在**主对话自己的**工具调用结束时交出；这次调用如果是主对话派出去的助手（子代理）做的，插话留着，等主对话下一次工具调用 |

## 证据

- 11-24 晚，用户在手机上给一个 Claude 对话发了「请查看这些图片」（带两张图）。当时主对话正等着一个子代理干活，插话被那个子代理某次工具调用的 PostToolUse 拿走，出现在**子代理**的工具结果里，主对话一直没看到。子代理照规矩没理它，用户这条话就这样丢了。
- `claude_hooks.py` 的 `_handle_fast` 里，`PostToolUse` / `PostToolUseFailure` 分支：只要 `not st.stop_requested`，就 `self.queues.take_steer(tid)`，用 `additionalContext` 交出。它不看这次工具调用是谁做的。子代理的工具调用也会触发同一个对话的钩子（同一个 `session_id`）。
- 钩子请求里有哪些字段（`D:\Personal\agent_remote_lanes\20261124-claude\research\hook-records.md` 第 7 节，11-24 实测，那次没有子代理）：每个事件都有 `session_id`、`transcript_path`、`cwd`、`permission_mode`、`hook_event_name`、`prompt_id`、`effort`、`scratchpad_dir`；工具事件另有 `tool_name`、`tool_input`、`tool_use_id`，PostToolUse 另有 `tool_response`、`duration_ms`。子代理的事件会不会多带 `agent_id` / `agent_type` 之类的字段，没有实测过。

## 怎么改

1. 新增一个判断「这次工具调用是不是主对话自己的」，按顺序看：
   - 钩子请求里有表示子代理的字段（比如 `agent_id`、`agent_type`，以 Claude Code 文档或现有代码里认得的为准），就当作子代理，不交；
   - 没有这类字段时，看主对话记录（这个对话的记录文件，不是 `transcript_path` 指向的别的文件）末尾一段（几百 KB）里，有没有这次的 `tool_use_id`，即 assistant 记录里 `type: tool_use` 且 `id` 等于它的块：有，就是主对话自己的，交；没有，就当作子代理，不交，插话留在插话位。
   - 如果请求里的 `transcript_path` 和主对话记录文件不是同一个文件，也当作子代理。
   - 读文件出错时不交（宁可晚交，不能交错人），也不能让钩子报错。
2. 只改 PostToolUse / PostToolUseFailure 交插话这一处。PreToolUse 的停止拒绝照旧对所有工具调用生效（用户按停止时，子代理也要停），Stop 钩子交排队消息不变（Stop 只在主对话结束一轮时来）。
3. 要快：这些是快通道事件（目标几毫秒）。只在插话位里真有东西时才去读记录；读的只是末尾一段，可以按 `tool_use_id` 缓存结果。

## 边界

- 只改：`claude_hooks.py`（交插话那一处加判断、新加一个小函数）和 `tests/` 下的测试。
- 另有两条线也在改 `claude_hooks.py`：一条只在 `_handle_permission` 加日志，一条可能改交出插话、排队后的记录方式。你只动交插话之前的那个判断，别碰别的函数，方便合并。
- 不改：`remote.py`、`agents/*`、`chat_history.py`、`claude_control.py`、`chats.py`、`codex_*.py`、`relay_*.py`、`static/`、`apps/`、`tests/fixtures/*`、`tests/conftest.py`、版本号和更新说明文件。
- 测试只用编造的记录和假的钩子请求，不碰真的 `C:\Users\39011\.claude`，不起真的 Claude，不结束进程。

## 验证

- 新测试：
  - 主对话的工具调用（记录里有这个 `tool_use_id`）结束 → 交出插话；
  - 子代理的工具调用（记录里没有这个 id，或者带子代理字段，或者 `transcript_path` 是别的文件）结束 → 不交，插话还在；
  - 接下来主对话的工具调用结束 → 交出；
  - 读记录出错 → 不交、不报错；
  - 停止标记照旧拒绝子代理的工具调用。
- `tests/test_claude_hooks.py` 和两份标准答案测试：改前跑一遍记基线，改后通过。
- 最后跑一遍完整 pytest。已知会失败的 3 条：`test_mobile_polish` 两个引擎各一条、`test_relay_mobile_layout` 一条；`test_relay_push` 在电脑忙时偶尔超时，单独重跑会过。

## 发版

不升版本号、不打包、不推送。主会话合并后打进 dev.53。

## 结果（DeepSeek 填）

- 提交：`claude-steer-main-only` 的「手机插话只交给主对话自己的工具调用」一条，含 `claude_hooks.py`、`tests/test_claude_hooks.py` 和这一节；本节和代码在同一个提交里，所以自己的短哈希写在会话汇报里。
- 子代理字段查到的情况（出处）：
  - `agent_id` 有文档出处：Claude Code 的 Agent SDK 参考里，`HookInput` 的 `agent_id` 写作「子代理标识符，当 hook 在子代理内触发时存在」（https://code.claude.com/docs/zh-CN/agent-sdk/python）。
  - 它在 PreToolUse / PostToolUse 这类**工具事件**上带不带，没有准信：anthropics/claude-code#29068（要求所有 hook 事件都带 `agent_id`）和 #40140（要求 PreToolUse/PostToolUse 带 `agent_id`）都还开着，说明至少有些版本的工具事件上没有这个字段。`agent_type` 没找到文档出处，按防御多认一个。
  - 这两个字段都只在请求真带了非空值时才当作子代理，所以字段名对不上也不会把主对话误判成子代理，只会退回记录判断；真正兜底的是记录判断。11-24 那次实测没有子代理，仓库里也没有子代理的钩子样本，所以「子代理事件带不带这些字段」这次仍没有实测数据（设计里也说没实测过）。
- 测试数字（基线 / 改后 / 完整 pytest）：
  - 基线（改前 `tests/test_claude_hooks.py tests/test_action_golden.py tests/test_read_golden.py`，含两份标准答案测试）：**53 项全过**，6.27 s（`baseline-hooks.log`）。
  - 改后同一条命令：**61 项全过**，5.63 s，多出的 8 项是新增的 `SteerMainOnlyTests`（`after-hooks-4.log`）。
  - 完整 pytest：**1252 passed、30 failed、6 skipped、100 subtests passed**，484.68 s（`full-pytest.log`）。这 30 条和这次改动无关：29 条报 `BrowserType.launch: Executable doesn't exist … ms-playwright\webkit-2359\Playwright.exe`（这台电脑没装 WebKit），分布在 `test_web_agents`、`test_web_antigravity`、`test_page_parts`、`test_list_status_filter`、`test_dev6_navigation_links`、`test_home_startup` 和设计里点名的 `test_mobile_polish`（2 条）、`test_relay_mobile_layout`（1 条）。为了坐实不是这次改出来的，把 HEAD（`bc5965c`）用 `git archive` 解到工作区的干净副本（`head-copy`），只跑这 8 个文件：同样 **30 failed、10 passed、8 subtests passed**，失败清单与改后逐条一致（`Compare-Object` 无输出，日志 `head-failures.log`）。`test_relay_push` 这次没有超时。
- 风险和没做的：
  - 记录判断按设计看 `tool_use` 块，另外多看一眼 `isSidechain`：同一文件里带这个标记的调用是子代理的，不算主对话的。如果 Claude Code 把子代理的调用写进主记录、却既不带这个标记、`tool_use_id` 又能对上，这条判断就会放过去（现在手上没有这种样本）。
  - 记录读不到、或主记录路径解析不出（例如会话刚建、`cliSessionId` 还没和记录对上）时**不交**：插话留到这一轮 Stop 再交（Stop 钩子照旧）。最坏是晚交一会儿，不会交错人。
  - 快通道没有变慢：插话位空时一次记录都不读（`HookQueues.has_steer` 只看插话位，有测试 `test_an_empty_steer_slot_reads_no_record` 守着）；真有插话时才读主记录末尾 512 KB，结果按 `tool_use_id` 缓存（上限 512 条）。
  - 只动了交插话这一处：`_handle_fast` 的 PostToolUse/PostToolUseFailure 分支加了一个条件，新加 `Bridge._steer_goes_to_main`、模块级 `is_main_conversation_call` / `_record_holds_call` / `_same_record`、`HookQueues.has_steer`（新方法，没改别的函数）。PreToolUse 的停止拒绝、Stop 分支、`_handle_permission` 都照旧，`remote.py`、`agents/*`、`chat_history.py`、`claude_control.py`、`chats.py`、`codex_*.py`、`relay_*.py`、`static/`、`apps/`、`tests/fixtures/*`、`tests/conftest.py`、版本号和更新说明文件都没碰。
  - 没做的：没有在真的 Claude 上跑子代理（不碰真的 Claude 设置和窗口），没有推送、合并、打包。

