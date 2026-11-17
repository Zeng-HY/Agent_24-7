# 交接：Codex「电脑上打开」要核对 Codex 真接手了，手机不再把电脑给的原因盖住（2026-11-17）

写给接手的 DeepSeek Harness 会话，由 Claude 监督。原因已经查清到能改的程度：你照第 3 节改电脑端（`codex_control.py`、`remote.py`）和两个手机端，补测试，本地提交，在第 9 节记结果。行号按 main 的 `be6ef28` 写，可能前后差几行。

---

## 0. 结论

11-17 一位安卓用户报告：前一晚 Codex 周额度用完，重置以后手机一直发不出 Codex 消息。截图（安卓，09:14，Codex 对话「更新C-Brain论文材料」，项目「脑转移」）：输入框上方写「电脑上已打开「更新C-Brain论文材料」」，输入框下面的芯片还是「电脑上打开」，发送键是灰的。那台电脑是用户的，不在手边；那边的证据还在要。

**手机能不能发 Codex，只看一件事：电脑上有没有一个 Codex 窗口"接手"（owner）这个对话。** 遥应经 Codex 的本机管道问 `thread-owner-discovery`，Codex 主进程挨个问自己的窗口；只有已经把这个对话重新加载成功、正显示着它的窗口才回答。没人回答，就是 `no-client-found`，遥应说「电脑端尚未打开这个对话…」，手机上发送键变灰、芯片变「电脑上打开」。

那台电脑上 Codex 为什么没接手，现在定不了（见第 1 节的几种可能）。但不管原因是什么，遥应自己有两个毛病，这次先改：

1. 「电脑上打开」不核对：`chats.py` 的 `Desktop.open()` 发出 `codex://threads/<id>`、把 Codex 拉到前面，就回「电脑上已打开「…」」。
2. 手机把这句结果排在电脑给的原因前面，而且一直不清：安卓和 iPhone 都这样，只有离开这个对话再进来才清掉。所以用户看不到真正的原因。另外，遥应当天日志里从来不写这个原因。

| 编号 | 现在 | 要改成 |
|---|---|---|
| 开-1 | Codex「电脑上打开」一律回「电脑上已打开「…」」 | 等最多 10 秒：有 Codex 窗口接手、遥应也读得到它的状态，才回「电脑上已打开「…」，可以发了」 |
| 开-2 | 没接手时手机看不出为什么 | 回 400，`code` 为 `codex_not_taken`，文字说清原因和怎么办；之后 10 分钟内，电脑给手机的原因（状态里的 `reason`）也用这一句；Codex 接手了就清掉 |
| 开-3 | 当天日志里没有原因 | 没接手时写一行（对话 id 前 8 位、等了几秒、Codex 版本、遥应测过的版本、这个对话的模型提供商、当前提供商）；一个对话从能发变成不能发、再变回来，各写一行 |
| 手-1 | 安卓、iPhone 输入框上方，一行结果排在电脑给的原因前面 | 电脑说这个对话现在发不了时，那行结果不显示，显示电脑给的原因 |
| 手-2 | 「电脑上打开」失败时显示红字，也不重读状态 | 收到 `codex_not_taken`：不显示红字，马上重读状态（原因会出现在那一行）；别的失败照旧 |

---

## 1. 证据：Codex 26.1106.6628.0 自己的代码

这台电脑装的是 Codex for Windows 26.1106.6628.0（`C:\Program Files\WindowsApps\OpenAI.Codex_26.1106.6628.0_x64__2p2nqsd0c76g0`，进程 `app\ChatGPT.exe`）。Claude 11-17 解开它的 `app.asar` 读过，摘录在工作区子文件夹 `20261117-codex-open-check`：

- `codex-owner-discovery.txt`：主进程里 `thread-owner-discovery` 的处理（`discoverOwner` → 窗口的 `getThreadRole`，只有 `owner` 才算）；窗口回答之前先核版本号（`handleClientDiscoveryRequest`：版本对不上直接答 `canHandle:false`，结果也是 `no-client-found`）；各消息的版本表。
- `codex-resume-failure.txt`：窗口重新加载对话（`thread/resume`）失败时，把 `resumeState` 设回 `needs_resume`、清掉 owner，对话只读显示。已知的失败原因：模型提供商挡住（`modelProviderMismatch` / `modelProviderNotConfigured` / `modelProviderPolicyConflict`，Codex 界面写「模型提供商不匹配：此聊天使用的是 {provider}，但你当前的提供商是 {currentProvider}。请切换至 {provider} 以继续。」），或者这个对话正被另一个进程写着（报错含 "already has an active writer" / "already has a live local writer"）。
- `codex-luna-reserve.txt`：用量限额。26.11 有「Luna Reserve」：高级模型额度用完后，对话改用隐藏模型 `gpt-reserve` 继续；Codex 记下每个对话原来的模型和推理强度，额度重置时逐个改回去（失败只记一条 `model_restore_failed`）。还有「此聊天仍受用量限制。请先查看你的用量，然后继续。」这些本身不会让对话失去 owner。
- `owner-probe-20261117.txt`：11-17 在这台电脑上只读问了最近 8 个对话：只有 Codex 窗口正显示的那 1 个有 owner，另外 7 个都是 `no-client-found`，0–16 毫秒就答。

所以会出现「Codex 显示着这个对话、却没人接手」的情况有这几种，那台电脑是哪种要等证据：

1. 模型提供商对不上（比如额度用完那晚换过提供商或 API key）。Codex 的线程表 `~/.codex/state_5.sqlite` 的 `threads.model_provider` 记着每个对话的提供商（这台电脑上全是 `openai`）；当前提供商在 `~/.codex/config.toml` 的 `model_provider`（没写就是 `openai`；`profile = "x"` 时看 `[profiles.x]` 里的）。
2. 对话被别的 Codex 进程占着。
3. Codex 自己更新了、改了版本号：那样**所有** Codex 对话都发不了（`thread-owner-discovery` 升版 → 全部 `no-client-found`；`thread-stream-state-changed` 升版 → 「没有取得当前会话快照…」）。

---

## 2. 现在的代码（行号按 `be6ef28`）

**电脑端**

- `codex_control.py`
  - 36：`TESTED_APP_VERSION = "26.1007.2314.0"`，别处没用到。
  - 51–54：`ControlError(message, status=409)`，没有 `code`。
  - 172–196：`DesktopPipe.call()`。`no-client-found` 变成 `ControlError("电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试")`，别的错误变成 `"Codex 未完成操作：" + error`，超时变成「Codex 响应超时，结果未确认；不会自动重试」。**这三句话的文字不要改**：两个手机的测试和示例数据、`tests/` 都按原文核对。
  - 211–227：`DesktopPipe.snapshot()`：问 owner，跟随（follow）一下，最多等 6 秒拿 v11 快照，拿不到就「没有取得当前会话快照，请在电脑打开该对话后重试」。
  - 543–554：`Bridge.__init__`；`self.log` 由 `remote.py` 1176 行设成当天日志的 `write`（每行自动带时间）；`_log()` 556–564 不会抛错。
  - 586–594：`Bridge._pipe()`：连不上就「无法连接 Codex 桌面，请确认客户端已打开」。
  - 746–793：`Bridge.status(tid, fresh)`：任何 `ControlError`/`ChatError`/`OSError` 都变成 `{"available": False, "reason": str(exc), …}`。手机的实时连接每秒调一次（`live_events.py` 123 行），`/api/codex/state` 也调。
- `remote.py`
  - 250–270：`_chat_call(fn, *args, timeout)`：`timeout > 0` 时 `fn` 在桌面工作线程（`self.desktop.run`）里跑；`ChatError` → 400 `{"ok":False,"error":…,"text":…,"not_submitted":…,"code":…}`；`TimeoutError` → 504；别的 → 写 traceback、500。
  - 767–775：`/api/chat/open`：DeepSeek 单独处理；Codex 和 Claude 都是 `self._chat_call(self.desktop.open, app, id, timeout=45)`。
  - 1175–1176：`server.codex = codex_control.Bridge()`，`server.codex.log = log.write`。
- `chats.py` 2340–2347：`Desktop.open()`：Codex 是 `os.startfile("codex://threads/<id>")` 加 `self._front(CODEX_PROCESS, 6.0)`，回 `{"ok": True, "text": "电脑上已打开「<标题>」"}`。**这次不改 `chats.py`**（另一个会话在改它）。
- `chats.py` 337–343：`codex_db()` 找最新的 `state_*.sqlite`；48：`CODEX_HOME`。

**安卓**（`apps/android/app/src/main/java/com/pocketagentdesk/teleply/`）

- `ComposerUi.kt` 237–276 `StatusLine`：顺序是 `chat.error` → `ws.error`（无面板时）→ `local` → `ws.result`（无面板时）→ `unknown` → `away` → 回执。`opens`（262）为真时这一行带「电脑上打开」按钮、最多 3 行。
- `ComposerUi.kt` 454 `notOnComputer`、461 `chipAway`、475 `awayReason`、484 `sendsWhileAway`。
- `WorkspaceController.kt` 595–608 `openOnComputer()`：成功 `result = text` 并 `changed()`；失败 `error = e.message`，不重读。610 `clearResult()` 没有人调用。
- `RelayApi.kt` 126–130：非 2xx 抛 `ServiceFailure(status, code, detail, …)`；`Models.kt` 61：409+`device_offline` 或 **503** 都说成「电脑已离线」，别的显示 `detail`。
- `FixtureApi.kt`：207 `away` 集合，241 示例对话 `AWAY_CODEX`，355 它的状态，452–455 `open()` 让它变成可发，680 `CODEX_AWAY`。
- 测试：`app/src/test/.../ComposerAwayTest.kt`；`app/src/sharedTest/.../ReaderUiScenarios.kt` 222–237（`codexNotOpenOnTheComputerSaysWhyAndOpensFromTheChip`）。

**iPhone**

- `apps/ios/Teleply/Composer/ComposerView.swift` 516 起 `lines`：顺序 `chat.error` → `workspace.error` → `workspace.result` → `unknown` → `away` → 回执；所有行 `lineLimit(2)`。
- `apps/ios/TeleplyCore/Sources/TeleplyState/WorkspaceModel.swift` 631–650 `openOnComputer()`、653 `clearResult()`（没人调用）。
- `apps/ios/TeleplyCore/Sources/TeleplyModel/ComposerChips.swift` 60–95：`notOnComputer`、`chipAway`、`awayReason`、`sendsWhileAway`。
- `apps/ios/TeleplyCore/Sources/TeleplyModel/Relay.swift` 470–510：`ServiceFailure`，有 `code`。
- 测试：`apps/ios/TeleplyCore/Tests/TeleplyCoreTests/ComposerAwayTests.swift`。

**网页**（`remote.html` 970 `openOnPC()`、`static/codex-ui.js` 56）用几秒就消失的提示条，打开后再刷新状态，**不受影响，不改**。

---

## 3. 要改成的样子

### 3.1 `codex_control.py`

1. `ControlError` 加 `code`（默认 `""`）。`DesktopPipe.call()`：`no-client-found` 带 `code="no-client-found"`；别的错误带 `code=error[:80]`；超时带 `code="timeout"`。三句话的文字一字不改。
2. `TESTED_APP_VERSION = "26.1106.6628.0"`，注释写来历：11-17 在用户这台电脑上，问 owner、v11 快照、发消息都正常。
3. 新函数 `codex_version(pipe) -> str`：用 `win32pipe.GetNamedPipeServerProcessId(pipe.handle)` 拿到管道那头的进程，`QueryFullProcessImageNameW` 拿完整路径（写法照 `winctl._process_name`，但要整条路径），从 `OpenAI.Codex_<版本>_` 里取出版本；取不到返回 `""`。同一个管道连接只取一次。
4. 新函数 `version_newer(a, b) -> bool`：按四段数字比，任一边是空的就 False。
5. 新函数 `thread_provider(tid) -> str`：只读打开 `chats.codex_db()`，`select model_provider from threads where id=?`；没有、读不了返回 `""`。
6. 新函数 `current_provider() -> str`：用 `tomllib` 读 `chats.CODEX_HOME / "config.toml"`：顶层 `profile` 指向的 `[profiles.<名>]` 里有 `model_provider` 就用它，否则顶层 `model_provider`，都没有就 `"openai"`；文件读不了、解析不了返回 `""`（表示不知道，不拿来下结论）。
7. 新类 `CodexNotTaken(chats.ChatError)`，`code = "codex_not_taken"`。
8. 新方法 `Bridge.owner(tid, timeout=3) -> str | None`：问一次 `thread-owner-discovery`；`code == "no-client-found"` 返回 None；别的 `ControlError` 照抛。
9. 新方法 `Bridge.confirm_open(tid, seconds=10.0, step=0.5) -> dict`，`remote.py` 在「电脑上打开」之后调：
   1. 每 `step` 秒问一次 `owner(tid)`，直到有 owner 或者到时间。中间抛别的 `ControlError`（比如 Codex 刚被链接拉起来、管道还没开）记下来接着等。**等的时候不要拿着 `self.lock`**（`status()` 每秒都要用它）。
   2. 有 owner：`st = self.status(tid, fresh=True)`。`st["available"]` 为真 → 清掉这个对话的失败记录，返回 `{"ok": True, "text": "电脑上已打开「<标题>」，可以发了"}`（标题用 `chats.find("codex", tid)["title"]`）。
   3. 否则按下面的顺序挑一句原因，记进 `self._open_failed[tid] = (time.monotonic(), 原因)`，写一行日志（第 10 条），抛 `CodexNotTaken(原因)`。

   原因（手机上原样显示，**一字不差照抄**；`{}` 里的名字超过 24 个字符就截断）：

   | 情况 | 原因 |
   |---|---|
   | 一直连不上管道 | 连不上电脑上的 Codex，请确认 Codex 开着，再点「电脑上打开」 |
   | 没有 owner，对话的提供商和当前提供商都知道、而且不同 | Codex 没接手：这个对话用 {对话提供商}，电脑上的 Codex 现在用 {当前提供商}，请在电脑上切回 {对话提供商} |
   | 有 owner，但 `status` 还是不可用，Codex 比测过的新 | Codex 已接手，但遥应读不到它的状态：电脑上的 Codex 是 {版本}，遥应要更新 |
   | 有 owner，但 `status` 还是不可用 | Codex 已接手，但遥应还读不到它的状态，请稍后再点「电脑上打开」 |
   | 没有 owner，Codex 比测过的新 | Codex 没接手。电脑上的 Codex 是 {版本}，比遥应测过的新，可能要更新遥应 |
   | 别的 | Codex 没接手这个对话。请看电脑上这个对话有没有提示，或重启 Codex 再试 |

10. 日志（`self._log`，不写消息内容、标题和路径）：
    - 没接手时一行：`Codex：电脑上打开 <id 前 8 位> 后 <秒数> 秒没接手（<连不上|提供商不同|读不到状态|版本较新|原因不明>）；Codex <版本或「未知」>，遥应测过 <TESTED_APP_VERSION>；这个对话的提供商 <…或「未知」>，当前 <…或「未知」>`，最后见到的错误 `code` 有就接在后面。
    - `status()` 里，每个对话记住上次的结果；变成不可用（或不可用的原因变了）写 `Codex 对话 <id 前 8 位>：手机发不了（<reason>）`，变回可用写 `Codex 对话 <id 前 8 位>：手机又能发了`。第一次见到一个对话时只在不可用时写。最多记 64 个对话。用一把小锁；写日志出错不能影响 `status()` 的结果。
11. `status()`：
    - 抛出的 `ControlError` 的 `code` 是 `no-client-found`、而且这个对话 600 秒内有 `_open_failed` 记录 → `reason` 用那句原因，别的字段照旧。
    - 结果可用 → 删掉这个对话的 `_open_failed` 记录。
    - 其余一概不变。

### 3.2 `remote.py` 的 `/api/chat/open`

Claude 和 DeepSeek 的分支不动。Codex 走一个新方法 `_open_codex(tid)`：

1. `self.desktop.run(self.desktop.open, "codex", tid, timeout=45)`：开窗口这一步照旧在桌面工作线程里做。
2. 然后在这个请求自己的线程里调 `self.server.codex.confirm_open(tid)`：最多 10 秒的等待**不能占着桌面工作线程**（Claude 的发送也排在那条线程上）。
3. 回复：成功回 `confirm_open` 的结果。`chats.ChatError`（含 `CodexNotTaken`）和 `codex_control.ControlError` → 400 `{"ok": False, "error": 文字, "text": 文字, "code": exc 的 code 或 null}`；`TimeoutError` → 504 `{"ok": False, "error": "超过 45 秒没做完"}`；别的 → 写 traceback、500（同 `_chat_call`）。**不要用 503**：两个手机都把 503 说成「电脑已离线」。

整个请求最长约 6 秒（拉到前台）+ 10 秒（等接手）+ 6 秒（读一次状态）。安卓默认读超时 30 秒，iPhone 40 秒，够。

### 3.3 安卓

1. `StatusLine`：`away != null` 时不显示 `ws.result`，其他顺序都不变（错误、`local`、`unknown` 照旧）。把「这一行说什么」挑出来做成一个不碰界面的 `internal fun`，`StatusLine` 调它，JVM 测试也测它。`opens` 和按钮的逻辑不变。
2. `WorkspaceController.openOnComputer()`：捕获到 `ServiceFailure` 而且 `code == "codex_not_taken"` 时，`error`、`result` 都不设，调 `changed()` 重读状态；别的异常照旧。成功照旧。
3. 示例数据（`FixtureApi.kt`）：加一个「电脑上打开也接不上」的 Codex 示例对话：点「电脑上打开」时抛 `ServiceFailure(400, "codex_not_taken", <第 3.1 节"别的"那句>)`，之后它的状态 `reason` 变成同一句，仍然不可用。原来的 `AWAY_CODEX` 不变。
4. 测试：`ComposerAwayTest.kt` 测第 1 条的函数（不可用时结果不显示、显示原因；可用时结果照常显示；错误仍然排第一；`unknown` 仍排在原因前）。`ReaderUiScenarios.kt` 加一个场景：打开新示例对话，点「电脑上打开」→ 这一行显示那句原因、不出现「本地示例：没有真的打开电脑上的窗口」也不出现红字、发送键仍是灰的。原来的 `codexNotOpenOnTheComputerSaysWhyAndOpensFromTheChip` 照样要过。

### 3.4 iPhone

**这台电脑编不了 Swift**（11-12 工具链被删了），只能推到 GitHub 以后在 Codemagic 上编，所以改动越少越好，每一行都要对着现有代码的写法核对。

1. `ComposerChips.swift`（TeleplyCore）：加一个和安卓同样规则的纯函数，挑这一行说什么。
2. `ComposerView.swift` 的 `lines`：用这个函数；只有电脑给的原因那一行（带「电脑上打开」按钮的那行）`lineLimit(3)`，其余仍是 2。
3. `WorkspaceModel.openOnComputer()`：`catch` 里 `if let failure = error as? ServiceFailure, failure.code == "codex_not_taken"` → 不设 `error`，调 `changed()`；别的照旧。
4. `ComposerAwayTests.swift`：照安卓第 4 条的单元测试写同样几条。
5. `DemoTransport.swift` 不改。

---

## 4. 边界

- **只改**：`codex_control.py`；`remote.py`（只动 `/api/chat/open` 的 Codex 分支，加 `_open_codex`）；新建 `tests/test_codex_open_check.py`；安卓 `ComposerUi.kt`、`WorkspaceController.kt`、`FixtureApi.kt`、`ComposerAwayTest.kt`、`ReaderUiScenarios.kt`；iPhone `ComposerChips.swift`、`ComposerView.swift`（只动 `lines`）、`WorkspaceModel.swift`（只动 `openOnComputer`）、`ComposerAwayTests.swift`；本文件第 9 节。
- **改每个文件之前**先跑 `git status --short <文件>`：要是它已经有不是你改的改动，**停下来告诉 Claude**，别动它（同一个仓库里还有别的会话在做「手机上看 Codex/Claude 限额」）。提交前 `git diff` 只能看到你的改动。
- **不要碰**：`chats.py`（另一个会话在改）；`claude_control.py`、`claude_archive.py`；`relay_*.py`（另一个会话在改 `relay_service.py`、`relay_transport.py`，还没提交）；`live_events.py`；网页（`remote.html`、`static/`）；`windows-version.json` 和发版脚本；`docs/` 里别的文件；用户没提交的 `deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`。
- **不碰电脑上的 Codex 窗口**：不发 `codex://` 链接，不发 `thread-follower-*` 请求，不发消息，不启动、不关 Codex。只读地问 `thread-owner-discovery` 可以；对 Codex 窗口**正显示着**的那个对话调一次 `Bridge().confirm_open(tid)` 核对成功的路子也可以（它只问 owner、读一次状态）。
- 不打包、不安装、不启动或重启遥应（`G:\AgentRemote`）。不 push、不 rebase、不 amend。main 上别的会话没推送的提交原样留着。

---

## 5. 验证

### 5.1 基线

- Python：在仓库根目录跑 `D:\Personal\agent_remote\.venv\Scripts\python.exe -m unittest discover -s tests`，改之前跑一遍，原样输出存到工作区子文件夹 `20261117-codex-open-check`。以前就坏的（和这次无关）：Playwright 浏览器缺（约 22 项出错）、`test_open_speed` 1 项失败。改完不能多出新的失败或出错。
- 安卓：在 `apps\android` 跑 `.\scripts\build.ps1`（默认 `assembleDebug`、`testDebugUnitTest`、`lintDebug`、`assembleDebugAndroidTest`），改前改后各一次，记 JVM 测试条数（从 `app/build/test-results/testDebugUnitTest/*.xml` 统计）。

### 5.2 新的 Python 测试（`tests/test_codex_open_check.py`）

先写测试，在旧代码上跑一遍，确认该失败的失败，原样输出存到子文件夹；再改代码。时间用假的（打桩 `time.monotonic`、`time.sleep`），测试不能真等 10 秒。管道用假对象（不连真 Codex）。

1. 第 3 次问才有 owner、状态可用 → 返回「电脑上已打开「<标题>」，可以发了」；等待中没拿 `self.lock`。
2. 一直没有 owner → 抛 `CodexNotTaken`，`code` 是 `codex_not_taken`，文字是"别的"那句；日志正好一行，有 id 前 8 位、秒数、版本、提供商，没有标题和内容。
3. 提供商不同 → 提供商那句（名字超长时截断）。
4. Codex 比测过的新、没有 owner → 版本那句。
5. 有 owner 但状态不可用 → 「读不到状态」两句（新版本和不是新版本各一条）。
6. 一直连不上管道 → 「连不上」那句。
7. 失败以后 600 秒内，`status()` 的 `reason` 是那句原因；超过 600 秒恢复原文；有 owner 以后记录被清掉。
8. `status()` 的日志：变成不可用写一行，重复不写，变回可用写一行，第一次见到可用的对话不写。
9. `DesktopPipe.call()`：`no-client-found` 的 `code` 和原来一字不差的文字。
10. `codex_version`：从 `...\WindowsApps\OpenAI.Codex_26.1106.6628.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe` 取出 `26.1106.6628.0`；别的路径返回空。`version_newer` 的几种情况。
11. `current_provider`：顶层、profile 覆盖、没写（`openai`）、文件坏了（空）。
12. `remote.py`：`/api/chat/open` 的 Codex 分支：`desktop.open` 在桌面工作线程里调；成功回 JSON；`CodexNotTaken` 回 400 带 `code`；状态码不是 503。照 `tests/test_locked_send.py` 那样造一个假 handler。

### 5.3 全部测试

5.1 的两样再跑一遍，和基线逐条比对，写进第 9 节。

### 5.4 这台电脑上做不了的

- iPhone 编译和 `TeleplyCore` 测试：Claude 问过用户、推送以后在 Codemagic 跑 `ios-native-check`。
- 真手机、真额度用完的情况：要打包装新版，等那位安卓用户的电脑证据。Claude 审你的提交时会在这台电脑上只读核对一次成功的路子。

---

## 6. 发布（不是你的事）

本地提交以后停下。不打包、不改版本号、不 push、不发版。Claude 审完再问用户：推送、Codemagic 编 iPhone、Windows dev.38、安卓新版、iPhone TestFlight，每一步都先问。

---

## 9. 结果记录（接手的会话填）

### 9.1 改了哪些文件、各改了什么

**`codex_control.py`**

- `TESTED_APP_VERSION` 改成 `26.1106.6628.0`，注释写了来历（11-17 在用户这台电脑上问 owner、v11 快照、发消息都正常）。
- `ControlError` 多了 `code`（默认空）；`DesktopPipe.call()` 的 `no-client-found` 带 `code="no-client-found"`，别的错误带 `code=error[:80]`，超时带 `code="timeout"`。三句话的文字一字未改。
- 新增 `_short`（话里出现的名字最多 24 个字符）、`version_newer`（按数字分段比，任一边为空或不是数字就 False）、`_codex_version_in_path`（从 `OpenAI.Codex_<版本>_` 取版本）、`_image_path`（进程完整路径，写法照 `winctl._process_name`）、`codex_version(pipe)`（取管道那头进程的路径，同一个连接只问一次，取不到返回空）、`thread_provider(tid)`（只读 `chats.codex_db()` 的 `threads.model_provider`）、`current_provider()`（`tomllib` 读 `chats.CODEX_HOME/config.toml`：profile 的 `model_provider` → 顶层 → `"openai"`；读不了/解析不了返回空）、`CodexNotTaken(chats.ChatError)`（`code = "codex_not_taken"`）。
- 新增 `Bridge.owner(tid, timeout=3)`：问一次 `thread-owner-discovery`，`no-client-found` 返回 None，别的 `ControlError` 照抛。
- 新增 `Bridge.confirm_open(tid, seconds=10.0, step=0.5)`：每 0.5 秒问一次 owner，最多 10 秒，**等待时不拿 `self.lock`**；有 owner 再 `status(tid, fresh=True)`。可用就清掉失败记录、返回「电脑上已打开「<标题>」，可以发了」；否则按第 3.1 节的顺序挑一句原因（连不上 / 提供商不同 / 有 owner 但读不到状态（分版本较新和不是）/ 没 owner 但版本较新 / 别的），原因存进 `_open_failed`（600 秒）、写一行日志、抛 `CodexNotTaken`。日志格式照第 3.1 节第 10 条，最后见到的 `code` 有就接在后面。
- 新增 `_remember_open_failure` / `_forget_open_failure` / `_open_failure`（都走一把小锁 `_open_lock`，最多记 64 个对话）。
- `Bridge.status()`：抛出的 `ControlError` 的 `code` 是 `no-client-found` 且这个对话 600 秒内有 `_open_failed` 记录时，`reason` 用那句原因，别的字段照旧；结果可用时删记录。新增 `_note_sendable`：每个对话记住上次的结果，变成不可用（或原因变了）写 `Codex 对话 <id 前 8 位>：手机发不了（<reason>）`，变回可用写 `…手机又能发了`，第一次见到且可用时不写；最多 64 个对话；写日志出错不影响 `status()` 的结果。

**`remote.py`**

- 新增 `Handler._open_codex(tid)`：`self.desktop.run(self.desktop.open, "codex", tid, timeout=45)` 照旧在桌面工作线程里开窗口，然后在请求自己的线程里调 `self.server.codex.confirm_open(tid)`（10 秒的等待不占桌面工作线程）。`chats.ChatError`（含 `CodexNotTaken`）和 `ControlError` → 400 `{"ok": False, "error", "text", "code"}`（`code` 没有就是 null）；`TimeoutError` → 504「超过 45 秒没做完」；别的 → 写 traceback、500。**不用 503。**
- `/api/chat/open` 的 Codex 分支改走 `_open_codex`；DeepSeek 和 Claude 的分支没动。

**安卓**

- `ComposerUi.kt`：把这一行说什么抽成 `internal fun statusLineText(chatError, wsError, paneOpen, local, result, unknown, away, receipt)`；`away != null` 时不显示 `result`，其他顺序不变。`StatusLine` 调它，颜色、`opens`、按钮、行数规则都不变。
- `WorkspaceController.kt`：`openOnComputer()` 捕获到 `ServiceFailure` 且 `code == "codex_not_taken"` 时，`error`、`result` 都不设，`changed()` 重读状态；别的异常照旧；成功照旧。
- `FixtureApi.kt`：新增示例对话 `codex-away-stuck`「电脑上打开也接不上的 Codex 对话」；点「电脑上打开」抛 `ServiceFailure(400, "codex_not_taken", <"别的"那句>)`，之后它的状态 `reason` 变成同一句，仍不可用。`AWAY_CODEX` 没动。
- `ComposerAwayTest.kt`：新单元测试 `theComputersReasonComesBeforeAnOlderResult`（不可用时结果不显示、显示原因；可用时结果照常；错误第一；`local`、`unknown`、回执的位置；`pane` 打开时错误和结果都不进这一行）。
- `ReaderUiScenarios.kt`：新场景 `codexOpenThatIsNotTakenShowsTheReasonInsteadOfAnError`（点「电脑上打开」→ 那一行是那句原因，没有「本地示例：没有真的打开电脑上的窗口」，没有红字，发送键仍灰）。因为多了一个示例对话，两处列表条数断言跟着改：`chats.size` 9→10、加载更多后 10→11（同一文件，必须跟着改）。

**iPhone**（这台电脑编不了，只改这四处）

- `ComposerChips.swift`：新增 `statusLineText(chatError, workspaceError, note, result, unknown, away, receipt)`，规则和安卓一样：`away` 时不显示 `result`，其余顺序照 iOS 原来的（这一行 iOS 没有安卓的 `pane` 参数）。
- `ComposerView.swift` 的 `lines`：改用它；只有电脑给的原因那一行（带「电脑上打开」按钮的那行）`lineLimit(3)`，其余仍是 2。
- `WorkspaceModel.swift` 的 `openOnComputer()`：`catch` 里 `ServiceFailure.code == "codex_not_taken"` 时不设 `error`、调 `changed()`；别的照旧。
- `ComposerAwayTests.swift`：和安卓同样的单元测试 `theComputersReasonComesBeforeAnOlderResult`。`DemoTransport.swift` 没动。

**`tests/test_codex_open_check.py`（新建，14 个测试）**：`FakeClock`（`monotonic` 只在 `sleep` 时前进，测试不真等 10 秒）、假 pipe（`SimpleNamespace(closed=False, handle=…)`，不连真 Codex）、照 `tests/test_locked_send.py` 造一个假 handler。

### 9.2 新测试的名字，和在旧代码上的结果

14 个，全在 `tests/test_codex_open_check.py`。旧代码按 main 的 `0f18d1e` 取（工作区里已有的改动不算），原样输出在工作区 `new-tests-on-old-code.log`：**14 个全部 ERROR**（`confirm_open`、`codex_version`、`thread_provider`、`CodexNotTaken`、`_codex_version_in_path` 在旧代码里都还没有，`ControlError` 也不认 `code`）。改完以后再跑，14 个全过（`new-tests-after-code.log`）。

| 测试 | 旧代码 | 对应 |
|---|---|---|
| `test_a_taken_conversation_says_it_can_send_and_the_lock_is_free_while_waiting` | 没有 `confirm_open` | 3.1-9、3.1-10（等待不拿 `self.lock`） |
| `test_no_owner_ever_says_so_and_writes_one_line` | 没有 `confirm_open` | 开-1、开-3（日志一行） |
| `test_a_provider_mismatch_says_which_provider_to_switch_back_to` | 没有 `confirm_open` | 提供商那句、24 字截断 |
| `test_a_newer_codex_that_does_not_take_it_says_it_may_need_an_update` | 没有 `confirm_open` | 版本那句（没有 owner） |
| `test_an_owner_whose_state_cannot_be_read_says_what_to_do` | 没有 `confirm_open` | 「读不到状态」两句 |
| `test_a_pipe_that_never_connects_says_codex_is_not_reachable` | 没有 `confirm_open` | 「连不上」那句 |
| `test_the_reason_last_ten_minutes_and_goes_once_taken` | 没有 `confirm_open` / `_open_failed` | 开-2、3.1-11 |
| `test_status_writes_one_line_on_each_change_of_being_sendable` | 没有 `_note_sendable` | 开-3、3.1-10 |
| `test_desktop_pipe_call_keeps_the_words_and_adds_the_code` | `ControlError` 没有 `code` | 3.1-1 |
| `test_the_codex_version_comes_from_its_package_folder_and_compares_by_numbers` | 没有 `codex_version` | 3.1-3、3.1-4 |
| `test_current_provider_reads_the_profile_then_the_top_level` | 没有 `current_provider` | 3.1-6 |
| `test_thread_provider_reads_the_conversations_own_provider` | 没有 `thread_provider` | 3.1-5 |
| `test_opening_a_codex_conversation_waits_outside_the_desktop_worker` | 没有 `_open_codex` | 3.2 |
| `test_a_codex_conversation_that_is_not_taken_is_a_400_with_its_code` | 没有 `_open_codex` | 3.2（400 带 code，不是 503） |

### 9.3 全部测试（和基线比）

**Python**（仓库根目录，`python -m unittest discover -s tests`）

- 改前基线（第一次，`-X utf8`，原样在 `baseline-deepseek-before.log`）：`Ran 851 tests`，`FAILED (failures=1, errors=22, skipped=6)`。
- 先写测试、在旧代码上跑：`Ran 877 tests`，`FAILED (failures=1, errors=36, skipped=6)`——多出来的 14 个 ERROR 就是新测试。23 条已知失败/出错的清单和第一次基线逐条相同（`baseline-failures.txt`）。
- 改后（最后一次，原样在 `after-deepseek-change-final.log`）：`Ran 878 tests`，`FAILED (failures=1, errors=22, skipped=6)`。
- 逐行比对 23 条已知失败/出错：改前改后**完全一样**（`Compare-Object` 无差异）。新测试 14 个全过。
- 总数 877→878 是这期间另一个会话又加了一个测试（这个仓库里同时有别的会话在干活），和这次无关；两次的 23 条已知项相同。
- 两台旧的坏项照旧，和这次无关：Playwright 浏览器缺（`C:\Users\39011\AppData\Local\ms-playwright` 不在，webkit/chromium 那些 ERROR），`test_open_speed` 那 1 条 FAIL。

**安卓**（`apps\android` 里 `.\scripts\build.ps1`，四个任务都过）

- 改前：`BUILD SUCCESSFUL in 46s`（92 个任务 up-to-date），`app/build/test-results/testDebugUnitTest` 20 个 XML，**226** 个 JVM 测试，0 失败 0 出错。
- 改后：`BUILD SUCCESSFUL in 1m 54s`，**228** 个 JVM 测试，0 失败 0 出错。多出的两条就是 `ComposerAwayTest.theComputersReasonComesBeforeAnOlderResult` 和 `ReaderRobolectricTest.codexOpenThatIsNotTakenShowsTheReasonInsteadOfAnError`；原来的 `codexNotOpenOnTheComputerSaysWhyAndOpensFromTheChip` 照旧过。

**iPhone**：这台电脑没有 Swift 工具链，没编译、没跑 `TeleplyCore` 测试（见 9.4）。

### 9.4 没做的、拿不准的

- **没在真窗口上验证成功的路子**：没有发 `codex://` 链接、没有往 Codex 窗口发消息、没有发 `thread-follower-*` 请求、没有启动/重启/关闭 Codex 或遥应。只做了一次只读核对：用 `Bridge()._app_version()` 连上 Codex 的 IPC（只发 `initialize`，用完立刻 `close()`），读到 `26.1106.6628.0`；`current_provider()` 读到 `openai`；`thread_provider('01a1e40d-…')` 读到 `openai`。**没有对任何对话调 `confirm_open`**，那一步留给 Claude 审的时候核对。
- **iPhone 没编译过**：改动逐行对照了现有写法（`if let x` 简写、`ServiceFailure` 在 `TeleplyModel`、`TeleplyState` 已经 `import TeleplyModel`），但 `ComposerChips.swift`、`ComposerView.swift`、`WorkspaceModel.swift`、`ComposerAwayTests.swift` 都没编过；`openOnComputer()` 的 `codex_not_taken` 分支也只有纯函数测试，没有异步测试（要加得改测试用的假 transport，属于本次不让改的文件，所以没加）。推送后请在 Codemagic 上跑 `ios-native-check`。
- **拿不准：`current_provider()` 的 profile 读法**：按交接文档第 1 节写的（`profile = "x"` 时看 `[profiles.x]`），这台电脑的 `config.toml` 是顶层 `openai`，profile 那条路没在真的文件上试过；读不懂时返回空、不拿它下结论。
- **拿不准：版本号的取法**：这次在真管道上取到了；如果以后 Codex 换打包方式（路径里不再有 `OpenAI.Codex_<版本>_`），`codex_version` 返回空，日志写「未知」，原因句不会误报「版本较新」，会落到「原因不明」/「读不到状态」。
- **600 秒的覆盖范围**：只覆盖 `no-client-found` 那一种；如果之后 Codex 换了原因（比如管道断了），手机上会先看到上次那句，最多 10 分钟。原因变了会再写一行日志（这是 3.1-10 要的）。
- 安卓多了一个示例对话，所以 `ReaderUiScenarios.kt` 里两处列表条数断言（9→10、10→11）跟着改了；其他断言没动。
- 没打包、没安装、没启动或重启遥应，没 push、没 rebase、没 amend，没动版本号和发版脚本。`chats.py`、`relay_*.py`、`live_events.py`、网页、`windows-version.json` 都没碰；提交前 `git status --short` 只有一个会话自己的文件，`git add` 一个一个加。
