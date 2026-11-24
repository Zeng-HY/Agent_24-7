# 交接：Codex 批准——人不在电脑前就交给手机，一直等

2026-11-24 晚，主会话设计，交给 DeepSeek 实现。分支 `codex-approval-away`（从 agent-registry 的 6ae0ea7 开），工作树 `D:\Personal\agent_remote_lanes\cxappr`。

## 结论

| 现在 | 要改成 |
|---|---|
| Codex 要批准时，钩子只在「手机正看着这个对话」（20 秒内拉过它的控制态，或这一轮是手机发起的）时才接住，最多 60 秒；否则马上交回电脑上的批准框 | 手机看着，或者**电脑前没人**（2 分钟没碰键盘鼠标），都接住交给手机，**一直等**：直到手机回答、电脑前有人动、或这一轮被停 |
| 接住期间电脑上的 Codex 不弹批准框，坐在电脑前的人点不了 | 接住期间，电脑上一有键盘鼠标输入，立刻放手，电脑上的批准框马上出来 |
| hooks.json 里 PermissionRequest 的超时是 90 秒 | 改成 86400 秒（24 小时，Codex 不收「无限」，24 小时等于一直等） |

用户原话：「电脑前没人……也把批准交给手机……为啥只能等 10 分钟，不能一直等吗？」——所以不设遥应这边的上限，只受钩子超时（24 小时）限制。**绝不自动批准**，只认手机上对这一条请求的明确回答。

## 证据

- 安卓用户 11-24 22:22 的截图：Codex 长任务（做 PPT）要运行命令，手机上是「Codex 想运行命令 · 终端 / 在等你在电脑上批准 / 请在电脑上处理这次请求」，电脑上是 Codex 自己的「拒绝 / 允许一次」框。卡片上没有「去信任钩子」的提示，说明钩子是信任过的，只是这次没接住。
- `codex_apptools.py` 的 `_build_questions`：Codex 报 `waitingOnApproval` 而钩子手里没有待批的卡片时，补一张 `answerable: False` 的「在等你在电脑上批准」卡片，就是截图里那张。
- `codex_hooks.py` 模块说明和 `_handle_permission_request`：只在 watching 时等，最多 60 秒，超时或没在看就回空。
- 设计原文（`D:\Personal\agent_remote_lanes\20261124-codex\design.md` 第 74、136 行）：限 60 秒、只在手机看着时等，是怕钩子接住期间电脑上的批准框出不来、电脑前的人点不了。

## 代码位置

- `codex_hooks.py`：模块说明；钩子清单（PermissionRequest 90 秒那一行）；`watching` 的算法；`_handle_permission_request`；`pending_cards`；`trust_status()`（读 config.toml 的 `hooks.state` 和 trusted_hash）；hooks.json 的安装函数。
- `deploy/windows/TeleplyCodexHook.cs`：`ResolveReadTimeoutMs()`（约 147 行）、读回复的等待（约 282 行）。管道读等待必须撑得住 24 小时；快事件（PreToolUse、Stop）保持快。
- `codex_apptools.py`：`_build_questions`、`_hook_notice`。
- 通知：`notify.py`（Codex 在等你时有没有推送）。

## 怎么改

1. **判断要不要接住**（PermissionRequest 到达时）：
   - watching（现有规则）→ 接住；
   - 否则电脑闲置 ≥ `AWAY_SECONDS = 120` 秒 → 接住；
   - 否则 → 立刻回空（电脑上的框马上出来）。
   - 闲置时间用 Windows 的 `GetLastInputInfo`（ctypes；`dwTime` 是 32 位 tick，用 `GetTickCount()` 相减再 `& 0xFFFFFFFF`），包成一个可替换的函数，测试里用假的。
2. **接住以后**：每秒看一次。
   - 手机回答 → 照现在的格式回 allow / deny；
   - 接住之后电脑上有新的键盘鼠标输入（最后输入时刻晚于开始接住的时刻）→ 回空，交给电脑；
   - 遥应这边不设上限；只在离钩子超时还剩 60 秒时回空（安全余量），免得 Codex 先把钩子掐断。
   - watching 的情况也加上「电脑上有输入就放手」。
3. **超时一起改**：hooks.json 的 PermissionRequest 超时 → 86400；`TeleplyCodexHook.cs` 对 PermissionRequest 的管道读等待 ≥ 86400 秒减几秒（毫秒数 86,400,000 在 int 范围内），别的事件不变。遥应重启或管道断开时，exe 照旧回空，电脑上的框出来。
4. **手机要知道**：电脑前没人时手机多半没开着这个对话，要能收到提醒。先查现在 Codex 在等批准时有没有推送（`notify.py`、中转的「在等你」、安卓 1.0.10 的遥应通知）：
   - 有，就写明证据，不改；
   - 没有，就在接住时，走现有的通知通道发一条「Codex 想运行命令：<命令开头>」。不另造通道，不改三家原有通知的文字和字段，标准答案不能变。
5. **卡片**：接住的请求，用现有的钩子卡片（`pending_cards`，可回答）显示，不管手机当时有没有在看。
6. **信任**：hooks.json 内容一变，每台电脑都要在 Codex「设置 → Hooks」里重新信任 3 个遥应钩子一次。核对 `trust_status()` 在内容变了以后报 `pending_trust`（手机上会出现现有的「去信任钩子」提示）。如果它只看「有没有记录」而不比哈希，修好并加测试。

## 边界

- 只改：`codex_hooks.py`、`deploy/windows/TeleplyCodexHook.cs`、确有需要时的 `codex_apptools.py`、确实缺通知时的 `notify.py`、`tests/` 下的测试。
- 不改：`remote.py`、`agents/*`、`claude_hooks.py`、`claude_control.py`、`chat_history.py`、`chats.py`、`relay_*.py`、`setup.iss`、`version.py`、`static/`、`apps/`、`tests/fixtures/*`、`tests/conftest.py`、版本号和更新说明文件。真要改这些，停下来写明原因。
- 不碰真的 `C:\Users\39011\.codex`；测试用现有的临时目录或 `set_default_codex_home_override`。不跑真的 Codex，不结束任何进程，不联网。

## 验证

- 测试（新加）：电脑前没人 → 接住且卡片可回答；有人 → 立刻回空；接住期间有输入 → 回空；手机回答 → allow / deny 原样传回；离超时 60 秒 → 回空；绝不自动批准；hooks.json 超时 ≥ 86400；内容变了 → `pending_trust`。
- 现有的 Codex 钩子、apptools、通知测试：改前跑一遍记基线，改后再跑。
- 两份标准答案测试（`tests/test_action_golden.py`、`tests/test_read_golden.py`）必须原样通过。
- 最后跑一遍完整 pytest。已知会失败的 3 条：`test_mobile_polish` 两个引擎各一条、`test_relay_mobile_layout` 一条；`test_relay_push` 在电脑忙时偶尔超时，单独重跑会过。

## 发版

不升版本号、不打包、不推送。主会话合并后打进 dev.53；更新说明里要写「装好后在 Codex 设置 → Hooks 里重新信任 3 个遥应钩子」。

## 结果（DeepSeek 填）

- 提交：
- 通知查到的情况：
- 测试数字（基线 / 改后 / 完整 pytest）：
- 风险和没做的：
