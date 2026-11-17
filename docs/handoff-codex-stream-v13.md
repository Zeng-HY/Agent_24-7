# 交接：Codex 26.1111 把对话状态消息升到版本 13，遥应要同时认 11 和 13（2026-11-17）

写给接手的 DeepSeek Harness 会话（就是上午做「电脑上打开核对接手」的那个对话），由 Claude 监督。原因已经查清、在真 Codex 上试过：你照第 3 节改 `codex_control.py`、补测试、本地提交，在第 9 节记结果。行号按 main 的 `b90d6f9` 写。

---

## 0. 结论

上午的修复（`8a29ffb`）装到那位安卓用户的电脑以后，他手机上写的是：「Codex 已接手，但遥应读不到它的状态：电脑上的 Codex 是 26.1111.2228.0，遥应要更新」。用户把这台电脑的 Codex 也升到 26.1111.2228.0，这台也发不出去了；当天日志 11:39–11:41 先是「电脑端尚未打开这个对话」，点「电脑上打开」后是「没有取得当前会话快照」。

**原因：26.1111 只把 `thread-stream-state-changed`（窗口发给跟随者的对话状态：快照和补丁）的版本号从 11 改成了 13。** 遥应 `DesktopPipe._read` 只收版本 11，别的版本一律把快照扔掉，所以 Codex 接手了，遥应却一直等不到快照。额度用完那晚只是碰巧，那天 Codex 自己更新了。

| 编号 | 现在 | 要改成 |
|---|---|---|
| 版-1 | `_read` 只认 `thread-stream-state-changed` 版本 11 | 认 11 和 13；别的版本照旧扔掉 |
| 版-2 | `TESTED_APP_VERSION` 是 26.1106.6628.0 | 改成 26.1111.2228.0（11-17 在这台电脑上核对过） |
| 版-3 | 「Codex 已接手但读不到状态」时，日志那一行不写状态给的原因 | 把 `status()` 给的原因原文接在那一行后面 |

---

## 1. 证据（都在工作区子文件夹 `20261117-codex-open-check`）

- `stream-versions-1106-vs-1111.txt`：两版 Codex 主进程的消息版本表（`early-bootstrap*.js` 里的 `i6`）。二十几种消息里**只有 `thread-stream-state-changed` 从 11 变成 13**。`thread-owner-discovery` 1、`thread-stream-following-changed` 1、`thread-follower-start-turn` 2、`thread-follower-steer-turn` 1、`thread-follower-interrupt-turn` 4、`thread-follower-submit-user-input` 1、两种批准 1、`thread-follower-compact-thread` 1、`thread-follower-set-queued-follow-ups-state` 3 等都没变。
- 消息的样子没变（两版 webview 代码一字不差，只有压缩后的短名字不同）：快照 `{type:"snapshot", revision, conversationState}`，补丁 `{type:"patches", baseRevision, revision, patches, acceptedTextChanges}`；接收端（`onStreamStateChanged` 那一段）也一字不差；补丁由 Immer 生成和应用（只有 add / replace / remove，路径是数组），和遥应的 `apply_patches` 一致。`conversationState` 是对话状态的浅拷贝，新建对话状态的字段两版完全一样。
- `v13-snapshot-shape.txt`：11-17 在这台电脑的 Codex 26.1111.2228.0 上只读跟随一次，抓到的真 v13 快照：`id`、`hostId`、`turnHistory`（canonical，`history.entitiesByKey`）、`requests`、`latestCollaborationMode`、`latestThreadSettings`、`threadRuntimeStatus` 都在；`ordered_turns`、`is_running`、`selected_settings`、`native_questions`、`native_approvals`、`latest_plan`、`compacting_now` 都读得出、没有报错。（标题和路径去掉了。原始快照里有对话内容，没放进工作区。）
- `v13-trial.txt`：只在内存里把收到的 13 改成 11 再交给 `codex_control`（不改仓库）：`Bridge.status(tid, fresh=True)` 可用、设置读对，`confirm_open` 回「电脑上已打开「…」，可以发了」。

---

## 2. 现在的代码（`codex_control.py`，行号按 `b90d6f9`）

- 1–6：模块说明写着 "Protocol verified against Codex Windows 26.1007.2314.0"。
- 41 附近：`TESTED_APP_VERSION = "26.1106.6628.0"` 和它的注释。
- 131–157，`DesktopPipe._read` 里处理 `thread-stream-state-changed` 的三处：
  - 140：`msg.get("version") != 11` 时把这个对话的快照和版本记录扔掉；
  - 143：`== 11` 且 `change.type == "snapshot"` 时存快照；
  - 153：`== 11` 且 `change.type == "patches"` 时应用补丁。
- 133：`thread-queued-followups-changed` 只收版本 2（Codex 两版都发 3）。它存进的 `self.queues` 别处没人读，**这次不改**。
- `Bridge.confirm_open`：有 owner 但 `self.status(tid, fresh=True)` 不可用时，日志那一行只写「读不到状态」或「版本较新」，不写 `status()` 的原因。

---

## 3. 要改成的样子

1. 模块级常量，例如 `STREAM_STATE_VERSIONS = (11, 13)`，注释写来历：11 是 26.1106 及以前，13 是 26.1111.2228.0（11-17 核对：只升了版本号，快照和补丁的样子、接收端代码都没变，Immer 补丁，真快照遥应读得对）。`_read` 那三处改用它：不在里面的照旧扔掉快照；在里面的照原样存快照、应用补丁。**不要**改成「什么版本都收」：以后 Codex 真换了格式，扔掉比读错安全，那时 `confirm_open` 会说「读不到状态」。
2. `TESTED_APP_VERSION = "26.1111.2228.0"`，注释改成 11-17 在这台电脑上核对的结果（问 owner、v13 快照、读状态、`confirm_open`）。模块说明那一句改成两版都核对过（26.1106.6628.0 和 26.1111.2228.0）。
3. `confirm_open`：有 owner 但状态不可用时，日志那一行后面接上 `；状态：<status() 给的 reason，最多 80 字>`。手机上的文字不变。
4. 别的一概不动：发消息、停止、回答、排队这些请求的版本号，`thread-queued-followups-changed`，手机、网页、`remote.py`。

---

## 4. 边界

- **只改**：`codex_control.py`；测试（加在 `tests/test_codex_open_check.py` 里，或者新建 `tests/test_codex_stream_versions.py`）；本文件第 9 节。
- 改之前跑 `git status --short codex_control.py tests/`：有不是你改的改动就停下来告诉 Claude。**现在工作区里另一个会话还没提交的文件**（`usage_limits.py`、`tests/test_usage_limits.py`、安卓 `Usage.kt`/`UsageUi.kt`/`UsageTest.kt`、iPhone `UsageView.swift`/`Usage.swift`/`UsageTests.swift`）一概不碰，用户没提交的 `deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py` 也不碰。`git add` 一个一个加。
- 不碰电脑上的 Codex 窗口：不发 `codex://` 链接、不发 `thread-follower-*` 请求、不发消息、不启动或关闭 Codex。可以做的只读核对：问 owner；对 Codex 窗口**正显示着**的那个对话调 `Bridge().status(tid, fresh=True)` 和 `Bridge().confirm_open(tid)`（它们只问 owner、跟随一下读快照）。
- 不打包、不安装、不启动或重启遥应，不 push、不 rebase、不 amend。

---

## 5. 验证

1. **基线**：仓库根目录 `D:\Personal\agent_remote\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests`，改前跑一遍，原样输出存子文件夹。`ceedfd9` 修好了 `test_open_speed`，已知坏项现在应该只剩 Playwright 浏览器缺的那些；以实际跑出来的为准，改后不能多。
2. **新测试**（先在旧代码上跑一遍确认会失败，输出存起来）：
   - 版本 13 的快照被存下，`Bridge.status` 读得出（照 `v13-snapshot-shape.txt` 的字段造一个最小的假快照，不要用真对话内容）；
   - 版本 13 的补丁接在版本 13 的快照后面照常应用（`baseRevision` 对得上才用）；
   - 版本 11 照旧能用；
   - 版本 12、14 照旧被扔掉（快照不存，已有的也清掉）；
   - `version_newer("26.1111.2228.0", TESTED_APP_VERSION)` 为 False，`version_newer("26.1112.0.0", TESTED_APP_VERSION)` 为 True；
   - 有 owner 但状态不可用时，日志那一行带上状态原因（最多 80 字），手机拿到的文字不变。
3. **全部测试**再跑一遍，和基线逐条比。
4. **真 Codex 只读核对**（这台电脑已是 26.1111.2228.0）：用改好的代码，对 Codex 窗口正显示的对话跑 `Bridge().status(tid, fresh=True)`（要 `available: True`）和 `confirm_open(tid)`（要「可以发了」），输出存子文件夹。

---

## 6. 发布（不是你的事）

本地提交以后停下。Claude 审完再问用户：打 Windows dev.40、装到这台电脑、发给那位安卓用户，每一步都先问。

---

## 9. 结果记录（接手的会话填）

### 9.1 改了什么

**`codex_control.py`**

- 模块说明改成两版都核对过（26.1106.6628.0、26.1111.2228.0），并写明 26.1111 只把 `thread-stream-state-changed` 从 11 升到 13、快照和补丁的样子没变。
- `TESTED_APP_VERSION = "26.1111.2228.0"`，注释写 11-17 在这台电脑上核对的结果（问 owner、v13 快照、读状态、`confirm_open`；`v13-snapshot-shape.txt`、`v13-trial.txt`）。
- 新增 `STREAM_STATE_VERSIONS = (11, 13)`，注释写两版对比和理由（11 是 26.1106 及以前，13 是 26.1111.2228.0；快照、补丁、接收端都没变，Immer 的 add/replace/remove 和 `apply_patches` 一致；不在里面的照旧扔掉——以后真换格式时扔掉比读错安全，那时 `confirm_open` 会说读不到状态）。
- `DesktopPipe._read` 的三处版本判断改用它：**不在**里面照旧把这个对话的快照和版本记录扔掉；**在**里面照旧存快照、按 `baseRevision` 应用补丁。`thread-queued-followups-changed`（只收版本 2）、各请求的版本号、`remote.py`、手机、网页都没动。
- `Bridge.confirm_open`：有 owner 但 `status(tid, fresh=True)` 不可用时，日志那一行后面接上 `；状态：<status() 给的 reason，最多 80 字>`；手机拿到的文字一字不变。

**`tests/test_codex_open_check.py`**

- 新增 `StreamVersionTests` 6 个测试。假快照只照 `v13-snapshot-shape.txt` 的字段造（`id`、`hostId`、`turnHistory`、`latestCollaborationMode`、`latestThreadSettings`、`threadRuntimeStatus` 等），没有真对话内容；用真的 `_read` 跑，读管道那两步换成假帧（`win32file.ReadFile` / `GetOverlappedResult`）。
- 老测试 `test_no_owner_ever_says_so_and_writes_one_line` 里「遥应测过 26.1106.6628.0」这一处断言改成 `'遥应测过 '+codex_control.TESTED_APP_VERSION`：被核对的那个版本号正是这次要改的，断言跟着改；别的断言没动。

### 9.2 新测试和在旧代码上的结果

6 个，全在 `tests/test_codex_open_check.py` 的 `StreamVersionTests`。旧代码按 main 的 `b90d6f9` 取，原样输出在工作区 `v13-tests-on-old-code.log`：**3 个 FAIL、1 个 ERROR、2 个通过**（通过的两个是防回退的）。改完以后再跑，21 个（15 个旧的 + 6 个新的）全过（`v13-tests-after-code.log`）。

| 测试 | 旧代码 | 对应 |
|---|---|---|
| `test_a_version_13_snapshot_is_stored_and_status_reads_it` | FAIL：快照没存（`{}`） | 版-1、3-1（v13 快照，`Bridge.status` 读得出） |
| `test_version_13_patches_follow_a_version_13_snapshot` | ERROR：`revisions` 里没有这个对话 | 版-1（v13 补丁接在 v13 快照后） |
| `test_version_11_still_works` | 通过（防回退） | 3-1（11 照旧） |
| `test_other_versions_are_still_thrown_away` | 通过（防回退） | 3-1（12、14 照旧扔掉） |
| `test_the_tested_version_is_26_1111` | FAIL：还是 `26.1106.6628.0` | 版-2 |
| `test_an_owner_whose_state_cannot_be_read_logs_the_states_reason` | FAIL：那行没有「状态：」，旧版本号还让它走了「版本较新」那句 | 版-3 |

### 9.3 全部测试（和基线比）

- 改前基线（`b90d6f9` 加工作区里别人未提交的改动，原样在 `baseline-v13-before.log`）：`Ran 935 tests`，`FAILED (errors=22, skipped=6)`，失败 0。22 条全是 Playwright 浏览器缺（webkit/chromium 那些），`test_open_speed` 已经好了，和交接文档说的一样。
- 改后（原样在 `after-v13-change.log`）：`Ran 941 tests`，`FAILED (errors=22, skipped=6)`。
- 逐行比对 22 条失败/出错：改前改后**完全一样**（`Compare-Object` 无差异；清单 `baseline-v13-failures.txt`、`after-v13-failures.txt`）。941 − 935 = 6 就是新加的 6 个测试，全过。
- 这次跑期间另一个会话还在改 Usage 相关文件（没提交），总条数以后还会变；比较以失败/出错清单为准。

### 9.4 真 Codex 只读核对

- 这台电脑的 Codex 是 26.1111.2228.0。用改好的代码只读问了最近 8 个对话谁是 owner：**2 个有 owner**（Codex 现在开着两个对话），两个都核对了。
- 两个都跑 `Bridge().status(tid, fresh=True)` 和 `Bridge().confirm_open(tid)`：都是 `available: True`、`running: False`、设置读到 `gpt-6-astra / low`；第二个还读到 1 张提问卡。`confirm_open` 两个都 `ok`，文字都以「可以发了」结尾，没有一条落到「读不到状态」。
- 没有发消息、没有发 `codex://` 链接、没有发 `thread-follower-*` 请求、没有动 Codex 窗口；连接用完 `close()`。标题和路径没打印。脚本 `v13-real-check.py`、输出 `v13-real-codex-check.txt` 只在工作区。

### 9.5 没做的、拿不准的

- 没打包、没安装、没启动或重启遥应和 Codex，没 push、没 rebase、没 amend，没动版本号和发版脚本。
- 没在手机上验证：手机端和网页这次一行没改，读的还是原来那些状态字段。
- **拿不准**：如果以后 Codex 改了快照格式却仍然用版本 13，遥应会按旧格式读——`apply_patches` 对不上的补丁会把快照扔掉，不会读错，`status` 会回到「读不到状态」；版本号再变（14…）会被照旧扔掉，`confirm_open` 会写原因、手机提示更新遥应。
- `thread-queued-followups-changed` 只收版本 2（Codex 两版都发 3）按文档没动，`self.queues` 目前别处没人读。
- 真机核对时正好有两个对话开着，两个都过了；没有第三个窗口可试，也没有在手机上看实际效果。

### 9.6 Claude 审查（11-17 12:1x）

- **代码**：读过 `0d13c28` 的全部改动，和第 3 节一致：`STREAM_STATE_VERSIONS = (11, 13)` 用在 `_read` 的三处，不在里面的照旧扔掉；`TESTED_APP_VERSION` 和模块说明改对了；`confirm_open` 只读一次状态，有 owner 而状态不可用时日志接上原因。老测试那处断言改成跟着 `TESTED_APP_VERSION` 走，理由成立。
- **测试（自己重跑）**：`tests.test_codex_open_check` 21 个全过；全量 `Ran 941 tests`，`FAILED (errors=22, skipped=6)`，0 个失败，22 条出错和 `after-v13-failures.txt` 逐条相同，全是缺 Playwright 浏览器的那些。
- **真 Codex 只读核对**（这台电脑 26.1111.2228.0，用提交后的代码，没在内存里改任何东西）：Codex 正显示的对话 `confirm_open` 0.1 秒回「…可以发了」，`status` 可用；没显示的对话 10.1 秒后照旧给原因，日志写「Codex 26.1111.2228.0，遥应测过 26.1111.2228.0」。
- **这台电脑上试不了的**：26.1106 的真 Codex（这台已经升级）；版本 11 由 `test_version_11_still_works` 保着。
- **发布要知道的**：这台电脑上跑着的是 dev.39，还是旧代码，要装新版才好。dev.39（`87b0b0b`）以后 main 上的电脑端改动还有：手机看用量和用 Codex 重置的电脑端（`de3fc3e`、`2c79a40`，`usage_limits.py` 和 `/api/usage`，那个会话审过），中转的 `b90d6f9`（`relay_service.py`）。从 main 打 dev.40 会一起带上用量那部分；手机端的用量页没发版之前，它在电脑上不会被调用。

### 9.7 Windows dev.40 打包、装到用户这台电脑（11-17，Claude）

- 用户 11-17 说「打包并安装」。dev.40 = 提交 `0fa3e04`（只改版本号和发布说明，父提交 `0aa0cd9`），比 dev.39（`87b0b0b`）多带：本文件的版本 13 修复 `0d13c28`；手机看用量和用 Codex 重置的电脑端 `de3fc3e`、`2c79a40`（`usage_limits.py`、`/api/usage`，手机端的用量页没发版之前不会被调用）；中转的 `b90d6f9`（`relay_service.py`）。
- 照 dev.39 的做法，在干净的临时工作树（`git worktree add --detach`）里打包，仓库目录里别人没提交的东西不进包；从仓库拷来 `.toolchain\MicrosoftEdgeWebview2Setup.exe`。打包前在工作树里跑 `test_codex_open_check`、`test_codex_status`、`test_codex_approvals`、`test_codex_delivery`、`test_usage_limits` 共 110 项，全过。
- 安装包 `dist/0.27.0-dev.40/AgentRemote-0.27.0-dev.40-Setup.exe`：32,602,472 字节，SHA-256 `366f6b67add897d4b9432738b0d99f27458119eaca5d6061b7100bb38192df4c`；`build/windows-build.json` 记的提交是 `0fa3e04`。`--self-test`（空数据目录）退出码 0；`PYZ-00.toc` 里有 `codex_control`、`usage_limits`、`relay_agent`。没签更新清单，没传阿里云，没发 GitHub。
- 装法：12:25:31 `taskkill /F /T` 关掉 dev.39 整棵进程树（托盘 48228、本机服务 21044、一个 WebView2 子进程），静默安装（`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`）退出码 0，装在原来的 `G:\AgentRemote`，`_internal\windows-build.json` 是 dev.40 / `0fa3e04`。用 `explorer.exe` 打开启动文件夹里的 `Agent Remote 027.lnk` 启动（带 `--tray`），12:25:48 起来，12:25:56 当天日志写「中转：连上了」。手机这边断了约 25 秒。
- **12:27 用户在手机上实际发通**：当天日志 `12:27:38 codex request=f9f38bd4-… state=accepted intent=start elapsed_ms=160`（这台电脑 Codex 26.1111.2228.0，遥应 dev.40）。
- **12:3x 传阿里云**（用户说「推送阿里云这些吧」）：`publish.py windows --dist dist/0.27.0-dev.40`，签了清单（`dist/0.27.0-dev.40/windows-update.json.sig`），按安装包、签名、清单的顺序传到阿里云 `windows/` 和 `windows/dev/`，脚本取回核对通过。再用应用自己的 `relay_updates.check_aliyun` 以 dev.39 的身份核对：拿到 `0.27.0-dev.40` / build 40，32,602,472 字节，SHA-256 `366f6b67…`，签名验过。**测试版的电脑（dev.37 起）现在检查更新都会看到 dev.40**，那位安卓用户的 dev.39 也在内。
- **GitHub 还没做**：这台电脑这会儿连不上 GitHub（`git ls-remote` 握手失败；系统代理关着，`clash_verge_service` 停着）。推送 main 和建预发布 `windows-v0.27.0-dev.40`（三个文件：安装包、`windows-update.json`、`.sig`；照 dev.37 用 Git 凭据管理器的登录走 GitHub API，先建草稿）等代理开了再做。
- **GitHub（12:5x）**：这台电脑的代理是 Clash TUN（`clash-core-service`，github.com 解析到 198.18.0.11），一直开着；前面「连不上 GitHub」是 Claude 自己命令的沙盒挡住了，不是网络问题。main 已由「手机看用量」那个会话推到 `b2e2fbe`。预发布 `windows-v0.27.0-dev.40`（指向 `0fa3e04`）照 dev.37 用 Git 凭据管理器的登录走 GitHub API 建：先草稿，传安装包、`windows-update.json`、`.sig` 三个文件，GitHub 记下的大小和 SHA-256 和本地一致，再发出。说明里另列了没单独发布的 dev.38、dev.39 的要点。用 `relay_updates.check_github` 以 dev.39 身份核对：拿到 dev.40，签名验过；`relay_updates.check`（阿里云优先）也拿到 dev.40。
