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

- 提交：本文件与代码同一提交（分支 `codex-approval-away`，说明「Codex 批准：电脑前没人也交给手机，一直等」）。改到的文件只有 `codex_hooks.py`、`deploy/windows/TeleplyCodexHook.cs`、`tests/test_codex_hooks.py`、本文件。
- 通知查到的情况：**已经有推送，没有改 `notify.py`**。接住的卡片一建好就调 `on_waiting`（`codex_hooks.py:1388`），`agents/codex.py:460` 把它转成 `notifier.asking()`（`notify.py:835`）→ `_tell(..., asks=True)`（`notify.py:845`）：Bark 推一条（副标题「<电脑名> · Codex 在等你选」，正文是命令开头）；ntfy 打开时推「Codex · <电脑名> · 在等你选」＋命令开头；中转在线时发 `kind="waiting"`（`notify.py:949`），`relay_push.py:47` 写成「有个对话在等你处理」，iPhone 的遥应通知和岛都收得到。另外 `agents/codex.py:874` 的 `notify_check_approvals` 每轮轮询看到 `hooks.pending_cards` 非空会补报一次（`notify.py:616`），第一推漏了也还有。手机正开着这个对话时不另推（`_quiet`），只更新岛——那时它本来就看得到卡片。
- 测试数字（基线 / 改后 / 完整 pytest）：
  - 基线（改动前）：`tests/test_codex_hooks.py tests/test_codex_apptools.py tests/test_notify.py tests/test_codex_approvals.py tests/test_agents.py` → 129 passed（20.08 s）。
  - 改后：同一组 → 143 passed（19.47 s）；加两份标准答案（`test_action_golden` 1 条、`test_read_golden` 1 条）→ 145 passed（19.64 s），标准答案原样通过。
  - 完整 pytest（最终代码）：30 failed, 1231 passed, 6 skipped, 98 subtests passed（444.42 s）。
  - 完整 pytest 的 30 条失败全是 Playwright 浏览器没装（`BrowserType.launch: Executable doesn't exist at …\ms-playwright\webkit-2359\Playwright.exe`），和这次改动无关：`test_list_status_filter` 7、`test_web_agents` 7、`test_page_parts` 6（含 4 个子测试）、`test_mobile_polish` 3（含 2 个子测试）、`test_home_startup` 3 个子测试、`test_dev6_navigation_links` 2、`test_relay_mobile_layout` 1、`test_web_antigravity` 1；交接里写的 3 条已知失败都在里面，`test_relay_push` 这次没超时。
  - 验证那 8 条对应的新测试（都在 `tests/test_codex_hooks.py`）：电脑前没人 → 接住且卡片可回答是 `test_away_without_watching_holds_an_answerable_card_for_allow_and_deny`（同时核对 `on_waiting` 被调、卡片 `answerable`）；有人 → 立刻回空是 `test_someone_at_the_pc_gets_the_desktop_dialog_at_once`；接住期间有输入 → 回空是 `test_keyboard_input_during_the_hold_hands_the_approval_back_to_the_desktop` 和 `test_watching_also_hands_back_when_the_desktop_gets_input`（后者是手机在看着时也一样放手）；手机回答 allow / deny 原样传回同上；离超时 60 秒 → 回空且绝不自动批准是 `test_hold_ends_sixty_seconds_before_the_hook_timeout_and_never_approves`；hooks.json 超时 ≥ 86400 是安装测试里的断言加 `test_existing_ninety_second_permission_hook_is_upgraded_in_place`（老 90 秒的条目原地换成一条 86400，不重复）；内容变了 → `pending_trust` 是 `test_stale_hash_after_a_content_change_reads_as_pending_trust`，哈希口径另有 `test_hash_matches_the_published_codex_digests` 钉住公开的已知答案。
- 风险和没做的：
  - 没在真的 Codex 上试 24 小时：按要求不跑真 Codex、不碰 `C:\Users\39011\.codex`。`timeout = 86400` 是否被 Codex 26.1117 接受按设计给定，没有真机验证；C# 只验证了编译、管道往返、超时/断开仍回空（`HookExeTests`），以及读等待的毫秒数够 24 小时。
  - 装好后必须在 Codex 设置 → Hooks 里重新信任 3 个遥应钩子（hooks.json 内容变了）。`trust_status()` 以前只看「有没有 trusted_hash」，现在真的比哈希：Codex 写 `sha256:<hex>`，按 codex-rs 的 `command_hook_hash` 复算并比对，内容变了就报 `pending_trust`，手机上出现现有的「去信任钩子」提示。口径来自两个公开复现（nodeterm 的 `codex-trust.ts`、reverie 的 `codex_hooks.rs`），测试里钉了它们发布的 3 条已知答案。为防口径差异把手机锁死，比哈希时接受「有/无 matcher」「有/无 async」几种身份形状；只有 `sha256:` 开头的才比对，老格式仍按「有没有记录」。**没在真机核对 Codex 26.1117 写出的哈希**——若它和公开口径不同，会一直显示 `pending_trust`（手机上的停止/批准/回答被挡住，但不会误批准）。
  - 电脑上的程序也会产生键盘鼠标输入（`notify.py` 开头记过 10-26 的 UI 测试每秒打字），那种情况不算「电脑前没人」，批准仍走电脑框。没为它加特殊处理。
  - 闲置判定读的是本会话的 `GetLastInputInfo`；远程桌面、锁屏、多会话这些没有单独验证。
  - 没改 `notify.py`（已有推送）、没改 `codex_apptools.py`（接住时 `pending_cards` 原样带出可回答卡片，`answerable: False` 的兜底卡片只在钩子没接住时出现）。没推送、没合并、没打包、没升版本号；`git add` 是一个文件一个文件加的，没动别的工作树和分支。
