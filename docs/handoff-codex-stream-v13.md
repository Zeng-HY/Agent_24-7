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

### 9.2 新测试和在旧代码上的结果

### 9.3 全部测试（和基线比）

### 9.4 真 Codex 只读核对

### 9.5 没做的、拿不准的
