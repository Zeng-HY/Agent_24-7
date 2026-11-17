# 交接：手机上看 Codex 和 Claude 的用量，还能用掉一次 Codex 重置（2026-11-17）

写给接手的 DeepSeek Harness 会话，由 Claude 监督。要做的东西已经查清楚，用户 11-17 同意做「看用量 + Codex 重置」。你照第 3 节写电脑端和两个手机端，补测试，本地提交，在第 9 节记结果。行号按 main 的 `6f244e3` 写，可能前后差几行。

**开工前提**：另一个会话的 `docs/handoff-codex-open-check.md` 已经做完、审完，在 main 上（代码 `8a29ffb`、`05c24ce`，审查记录 `6f244e3`）。它改了 `codex_control.py`、`remote.py` 的 `/api/chat/open`（新的 `_open_codex`）、安卓 `ComposerUi.kt`（状态行改成调 `statusLineText(...)`）、iPhone `ComposerChips.swift`（`statusLineText(...)`）等。这次的改动避开了它那些地方（见第 4 节）。

---

## 0. 结论

11-17 一位安卓用户想要两样：手机上看用量（Codex 的每周限额和可能有的 5 小时限额，Claude 的 5 小时和每周限额，各自几点重置）；不去电脑也能用掉一次重置（用户叫它「重置卡」）。

| 编号 | 要做的 | 怎么做 | 新不新 |
|---|---|---|---|
| 电-1 | Codex 用量（不联网） | 读 Codex 自己的对话记录：每轮回复都写一行 `token_count`，里面有 `rate_limits` | 截至电脑上 Codex 最近一次回复 |
| 电-2 | Codex 用量和重置次数（实时） | 遥应临时开一个 Codex 自己的后台程序（`codex.exe app-server`，和 `archives.py` 归档、删除时一样），问 `account/rateLimits/read`，问完就关 | 实时，缓存 30 秒 |
| 电-3 | 用掉一次 Codex 重置 | 同样开后台程序，调 `account/rateLimitResetCredit/consume`；手机必须先确认，带一个请求编号，重试不会多用 | — |
| 电-4 | Claude 用量 | 读 Claude 窗口上的「Usage」按钮的名字（UI Automation，只读，不点不碰窗口） | Claude 自己几分钟刷新一次 |
| 电-5 | 两个接口 | `GET /api/usage`、`POST /api/usage/codex-reset` | — |
| 手-1 | 安卓「用量」页 | 设置和对话菜单里各一个入口；看两边的用量；Codex 有重置时能用掉一次，先弹确认框（3.3、3.4） | 打开时读一次，下拉再读 |
| 手-2 | iPhone「用量」页 | 同上（3.3、3.5） | 同上 |

做不到、这次不做的：

- Claude 的重置：只有部分账号在试用（服务器开关决定），用的时候要带登录调 Anthropic 的接口。遥应不碰登录，**不做**。
- Claude 的完整几档（每周、各模型每周）：只有点开卡片才看得到，**不做**。窗口上的按钮只显示 Claude 自己挑的那一档：平时是 5 小时，每周那档更紧时换成每周。
- 买重置（Codex 里「支付 {price} 重置」「购买即时重置」）：**永远不做**。
- 对话里「Codex 用量用完了」那一行字（输入框上方）：要动 `StatusLine` / `lines`，等另一个会话改完以后另做，**这次不做**。
- 网页（`remote.html`）：**这次不做**。

---

## 1. 证据（Claude 11-17 在这台电脑上查的）

这台电脑：Codex for Windows 26.1106.6628.0（进程 `ChatGPT.exe`，它自己的后台程序是 `%LOCALAPPDATA%\OpenAI\Codex\bin\9e1da79431da526b\codex.exe app-server`，`codex-cli 0.167.0-alpha.4.1`）；Claude 5.11492.5.0（内置 Claude Code 2.1.325）。完整调查记录在 `C:\Users\39011\AppData\Roaming\Claude\side-session-notes\local_11ed7929-21cc-46ad-a1d2-d00e531dda08\usage-limits-resets-2026-11-17.md`。

### 1.1 Codex 的对话记录里有用量

`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，每轮回复写一行（这一行很长，下面只留相关部分）：

```json
{"timestamp":"2026-11-17T02:22:02.354Z","type":"event_msg","payload":{"type":"token_count", "...":"...",
 "rate_limits":{"limit_id":"codex","limit_name":null,
   "primary":{"used_percent":84.0,"window_minutes":10080,"resets_at":1795006481},
   "secondary":null,
   "credits":{"has_credits":false,"unlimited":false,"balance":"0"},
   "individual_limit":null,"spend_control_reached":null,"plan_type":"pro","rate_limit_reached_type":null}}}
```

- `window_minutes`：10080 是每周，300 是 5 小时。这台电脑是 Pro，只有每周一档（`secondary` 是 null）；别的套餐可能 `primary` 是 5 小时、`secondary` 是每周。
- `resets_at`：Unix 秒。1795006481 是 2026-11-18 20:54（北京时间）。
- `rate_limit_reached_type`：撞到限额时不是 null（`rate_limit_reached`、`workspace_member_usage_limit_reached` 等）。
- `limit_id` 可能有别的值（别的计量桶）；只取 `"codex"` 或没写的。
- 这一行只在电脑上的 Codex 回话时写。在网页、别的电脑上用掉的（12 月起 ChatGPT 聊天也算进同一个限额），要等电脑上下一次回话才反映出来。
- 本机查最近的记录：`state_5.sqlite` 的 `threads` 表按 `updated_at_ms` 倒排取 `rollout_path`（0.001 秒）。最近更新的对话不一定是普通对话，子任务（`thread_source = 'subagent'`）、`codex exec` 的也一样写 `token_count`，都算。
- 重置次数**不在**本机任何文件里（rollout、`.codex-global-state.json`、`logs_2.sqlite` 都查过）。

### 1.2 Codex 自己的后台程序能读用量、能用重置

遥应现在用的 `\\.\pipe\codex-ipc` 只有对话类的方法（全表在 Codex 的 `.vite/build/early-bootstrap.js` 里），**没有**用量和重置。但 Codex 的后台程序（app-server）有，而且是正式协议（`codex app-server generate-json-schema` 生成，不是 experimental 那部分）：

- `account/rateLimits/read`，参数可以是 null 或 `{"excludeResetCreditDetails": false}`。回：
  - `rateLimitsByLimitId`：`{"codex": 快照}`（优先用它）；`rateLimits`：旧的单桶写法（没有前者时用）。快照里 `primary`/`secondary` 是 `{usedPercent, windowDurationMins, resetsAt}`，另有 `planType`、`rateLimitReachedType`、`credits`。
  - `rateLimitResetCredits`：`{availableCount, credits}`；`credits` 是数组或 null（null＝只知道次数）。每条 `{id, title, description, grantedAt, expiresAt, status, resetType}`，时间是 Unix 秒，`expiresAt` 可能是 null（不过期），`status` 是 `available`/`redeeming`/`redeemed`/`unknown`。
  - `ordinaryUsageAllowed`：true/false/null。null 表示不知道，Codex 说"不要拿百分比和重置时间推断已经恢复"。
  - `accountId`：**不要传给手机，不要写日志**。
- `account/rateLimitResetCredit/consume`，参数 `{"idempotencyKey": "...", "creditId": "..."}`（`creditId` 可不给，由后台挑）。回 `{"outcome": ...}`：
  - `reset`：用掉了一次，限额恢复了；
  - `nothingToReset`：现在没有能重置的限额，没用掉；
  - `noCredit`：没有可用的重置，没用掉；
  - `alreadyRedeemed`：这个 `idempotencyKey` 之前已经用成了，这次没再用。
  - 结果不确定时，**只能用同一个 `idempotencyKey` 重试**。
- **11-17 只读试过一次**（不是用遥应，是一个临时脚本，照 `archives.CodexServer` 的做法：开 `codex.exe app-server` → `initialize` → `initialized` → `account/rateLimits/read` → 关）：0.2 秒握手，1.9 秒拿到结果，进程正常退出；Codex 的登录文件 `~/.codex/auth.json` 前后修改时间不变（没刷新登录），电脑上的 Codex 照常。读到：Pro；每周已用 84%，2026-11-18 20:54 重置；`ordinaryUsageAllowed: true`；重置 1 次：标题 `Full reset`，说明 "Thanks for using Codex! You've been granted one free rate limit reset."，2026-11-13 06:48 给的，**2026-12-13 06:48 到期**。顺带收到两条通知 `account/updated`、`remoteControl/status/changed`（忽略即可；`remote_control` 功能在这个版本是 removed）。
- Codex 界面的叫法（中文）：设置 → 用量：「使用一次重置，即可恢复你的 5 小时限额、每周限额，或同时恢复两者」，每条「将于 {date} 到期」，按「使用重置」再「确认」；没有时「无可用重置次数」。历史叫「储备重置次数」。
- Codex 给它自己的助手定的规矩（「允许助手使用用量重置次数」，默认关）：只有用户在对话里明确要求、而且剩余不超过 10% 才用，绝不自动用。我们的手机也照这个精神：**每次都要用户在手机上确认**，剩得多时在确认框里提醒。

### 1.3 Claude 窗口上一直挂着用量

Claude 窗口开着某个 Code 对话时，模型按钮旁边有个按钮，UI Automation 读到的名字是：

```
Usage: 35% of 5-hour limit, Resets at 12:20 PM
```

（11-17 10:01 读到 31%，10:06 读到 35%：几分钟就跟着变。）文字的规矩（Claude 的 `ion-dist.asar` 里 `assets/v1/c82492f2c-ClkNDsFq.js`）：

- 固定以 `Usage: ` 开头，后面是逗号加空格分开的几段（英文列表格式）。
- 第一段：5 小时那档写 `{pct}% of 5-hour limit`；别的档写 `{label}: {pct}%`，比如 `Weekly · all models: 85%`、`Weekly · Fable: 3%`。
- 后面一段 `Resets at 12:20 PM`（当天）或 `Resets ...`（别的写法，比如带星期），照原文。可能还有别的段，不认识就忽略。
- 取不到时按钮写 `Plan usage unavailable`（这时没有 `Usage: ` 前缀），当作读不到。
- Claude 界面是英文，没有中文翻译。
- 同一时刻 Claude 自己的完整数据（桌面给它自己的会话用的工具读到的，遥应拿不到）：Max；5 小时 34%，12:20 重置；每周·全部模型 31%，11-21 15:00 重置；每周·Fable 0%。所以按钮只是其中最紧的一档。

读法（11-17 只读试过）：整窗一次 `FindAll` 拿到全部按钮（344 个元素，很快），挑名字以 `Usage: ` 开头的第一个。Claude 窗口最小化时 UI Automation 读到的可能是旧的（`chats.py` 1758–1767 `_claude_unminimize` 的说明）；**读用量时不要恢复窗口**，只告诉手机"窗口最小化了，可能是旧的"。

---

## 2. 现在的代码（行号按 `0f18d1e`）

### 2.1 电脑端

- `archives.py` 46–126 `CodexServer`：开 `codex.exe app-server`（`new_conversations.codex_cli()` 找程序，`CREATE_NO_WINDOW`），`initialize`（`clientInfo`、`experimentalApi: true`）+ `initialized`，`call(method, params, timeout)` 只认 `id` 对得上的回复、别的通知一律跳过，`close()` 关输入、等 5 秒、再 `terminate`/`kill`；能当 `with` 用。出错抛 `ArchiveError`：找不到 Codex、进程意外退出是 **503**，超时是 504；后台程序回错误时抛 `CodexRefused`（409，文字是 Codex 原话）。**这些状态码别原样给手机**：两个手机都把 503 说成「电脑已离线」。
- `new_conversations.py` 34–44 `codex_cli()`：优先 `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` 里最新的，没有再找 npm 装的。
- `tests/test_archives.py` 13–30：假的 `CodexServer`（`Archives(..., server=FakeServer)` 注入）。照这个写法测。
- `chats.py`：48 `CODEX_HOME`；54 `CLAUDE_PROCESS = "claude.exe"`；337–343 `codex_db()`；1441–1444 `app_window(process)`；1531–1556 `Desktop`（UI Automation 只在它自己的一条线程上用，`run(fn, *args, timeout)` 把活交给那条线程）；1579–1582 `_need_auto()`；1629–1647 `_find(scope, kind, name=None)`（一次 `FindAll`，读到一半消失的元素会跳过）。**这次不改 `chats.py`**，只调用它。
- `remote.py`：
  - 472 起 `_get()`：按 `path` 一条条判断；`/api/notify` 在 519–521，新的 `/api/usage` 加在它后面。
  - 648 起 `_post()`：`body = self._body()`（673），`_bad` 时 400；`/api/notify` 那组在 697 起，新的 `/api/usage/codex-reset` 加在那组前后都行。
  - `_open_codex` 是另一个会话刚加的，不要动。
  - `_json(obj, status=200)`；出错一律回 JSON `{"error": 文字, ...}`。
  - 1179 起 `main()`：1199 `server.desktop`，1216 `server.archives`。新对象加在 `server.archives` 那几行后面。
  - 1222 `server.machine = machine_facts(cfg)`，`server.machine["apps"]` 是这台电脑装了的（`"codex"`、`"claude"`、`"deepseek"`）。注意它在 1222 才设，新对象要用 `apps=lambda: server.machine["apps"]` 这种晚取的写法（`archives` 就是这样）。
  - 日志：`log.write(文字)`，自动带时间，写进当天的日志文件。
- `app_paths.py` 的 `DATA`：遥应的数据目录（打包后在 `%LOCALAPPDATA%\AgentRemote\Data`）。
- 中转（`relay_transport.py`）对路径不设限制，新接口不用改中转。

### 2.2 安卓（`apps/android/app/src/main/java/com/pocketagentdesk/teleply/`，下面简写文件名）

- 没有导航库，页面靠 `ReaderViewModel.kt` 52 的 `enum class Screen` 切换；`MainActivity.kt` 150–165 `when(s.screen)`。
- `RelayApi.kt` 150–153 `detail(device, route, query, body)`：路径是 `/api/$route`，只认 164–165 `DetailRoutes` 白名单里的；167 `SlowRoutes` 是各路由的秒数（不在表里就是默认 40 秒）。没有 body 是 GET，有 body 是 POST JSON。
- `ReaderViewModel.kt` 685–688 `deviceCall(route, query, body)`：对当前选中的电脑调 `detail`。
- `Models.kt` 61–68 `ServiceFailure(status, code, …)`：409 带 `device_offline` 或 503 →「电脑已离线…」；其他用电脑给的 `error` 原文。所以电脑这边一律回 409/400 加中文 `error`。
- `MainActivity.kt` 255–294 `SettingsScreen`：261–264 只有选了电脑才有的「对话 → 已归档对话」（`archived=true` → 289 `ArchivedSheet(vm) { archived=false }`）。
- `ArchiveUi.kt`：266 `LaunchedEffect(Unit) { vm.deviceCall(…) }` 一打开就读；311–330 删除前的 `AlertDialog`（确认按钮 `TextButton { Text("删除", color = p.error) }`，取消按钮 `TextButton { Text("取消") }`），确认后 `vm.deviceCall("chat/delete", …, confirmed=true)`。照这页的写法做「用量」。
- `Overlays.kt` 107 `SheetHost`、134 `TeleplySheet(title, onClose) { … }`。
- `ChatUi.kt` 449–466 `ChatMenu`（对话右上角 ⋯）：「电脑上打开」「会话状态」「查找消息」（`sheets.search = true`）「对话文件」「常用提示语」（`sheets.prompts = true`）…。`ChatSheets` 的定义和画出来的地方照 `search`、`prompts` 找。
- `FixtureApi.kt` 30 `reply()` 的 `when(route)`：本地示例数据。
- 中文直接写在代码里，安卓没有英文版。
- 测试：`app/src/test/java/com/pocketagentdesk/teleply/*Test.kt`（JUnit 4、MockWebServer、Robolectric）；`RelayApiTest.kt` 17–35 是典型写法；界面场景在 `app/src/sharedTest/.../ReaderUiScenarios.kt`。

### 2.3 iPhone（`apps/ios/`）

- `TeleplyCore/Sources/TeleplyModel/Relay.swift`：95–98 `slowRoutes`；276–284 `detailRoutes` 白名单；288–294 `detail(device:route:query:body:)`，路径 `"/api/" + route`；470–502 `ServiceFailure`（`status`、`code`、`detail`…）。
- `TeleplyCore/Sources/TeleplyModel/JSONValue.swift`：动态 JSON，`v["k"].string()`、`.bool()`、`.int64()`、`.array`；字面量能直接写 `["confirmed": true, "request_id": .string(id)]`。
- `TeleplyCore/Sources/TeleplyState/AppModel+Archive.swift` 122–125 `AppModel.deviceCall(_:query:body:)`：对当前电脑调 `detail`。
- `Teleply/Settings/SettingsView.swift` 10–86：设置是一个自带 `NavigationStack` 的 sheet；选了电脑才有的几组（对话 → `ArchivedView`、`NotifySection`、`VoiceSection`）。
- `Teleply/Settings/ArchivedView.swift`：`let model: AppModel`、`@State data: JSONValue?`、`.task { await load() }`、`.refreshable`；94–99 `.alert(… isPresented:) { Button("取消", role: .cancel) {}; Button("删除", role: .destructive) { … } } message: { Text(…) }`；148 带 `confirmed: true` 的 POST。照这页的写法做「用量」。
- `Teleply/Chat/ConversationView.swift` 431 起 `ConversationMenu`（对话右上角 ⋯）：446「电脑上打开」、「会话状态」、「查找消息」…
- `TeleplyCore/Sources/TeleplyModel/UserFacingError.swift` 12 `describe(error)`；`Hints.swift`：电脑给的中文句子在英文界面里怎么翻（52–56 有例子）。
- 界面文字：中文字面量当键，英文在 `Teleply/Resources/Localizable.xcstrings`（源语言 zh-Hans）。运行时拼的用 `Design/Localized.swift` 的 `L()`/`LK()`。
- 示例数据：`TeleplyCore/Sources/TeleplyDemo/DemoTransport.swift` 174 起的 `switch route` 按路由回假数据。
- 测试：`TeleplyCore/Tests/TeleplyCoreTests/*.swift`（Swift Testing：`@Test`、`#expect`）；`RelayReadTests.swift` 10–29 用 `RecordingTransport`（`TestTransports.swift` 39）。
- 灵动岛早有"额度用完 · 几点恢复"的样子（`TeleplyIsland/IslandState.swift` 的 `limited`、`resets`，`IslandWords.swift`），是 `docs/handoff-dynamic-island.md` 方案七的计划，还没接数据。**这次不碰灵动岛**；以后做方案七时可以用这次的 `usage_limits.py`。
- **这台电脑编不了 Swift**（11-12 工具链被删了），只能推到 GitHub 以后在 Codemagic 上编。改动越少越好，每一行都对着现有代码的写法核对。

---

## 3. 要改成的样子

### 3.1 新文件 `usage_limits.py`

文件头写清楚：数据从哪来、为什么用 Codex 自己的后台程序（遥应的管道没有这个方法；遥应不读登录，登录由 Codex 自己拿着）、为什么 Claude 只读窗口、11-17 试过什么。

1. `class UsageError(chats.ChatError)`：`__init__(text, status=409, code="")`，带 `status`、`code`。

2. **Codex：读记录** `codex_records(now=None) -> dict | None`
   1. 只读打开 `chats.codex_db()`，`select rollout_path from threads order by updated_at_ms desc limit 8`（没有 `updated_at_ms` 列就用 `updated_at`；不过滤来源、不过滤归档）。路径去掉 `\\?\` 前缀（`chats._strip_unc`）。读不了库返回 None。
   2. 每个文件只读最后 512 KB（`seek` 到末尾往前），丢掉第一行（可能是半行），从后往前逐行 `json.loads`，坏行跳过。找第一条：`type == "event_msg"`，`payload.type == "token_count"`，`payload.rate_limits` 是 dict，`limit_id` 是 `"codex"` 或 null。记下它的 `timestamp`。
   3. 8 个文件里挑 `timestamp` 最新的那条。都没有返回 None。
   4. 整理成（下面"窗口"的格式第 4 条通用）：

      ```json
      {"source": "records", "as_of": 1794882122354, "plan": "pro",
       "windows": [{"kind": "weekly", "minutes": 10080, "used_percent": 84, "resets_at": 1795006481, "name": "每周"}],
       "reached": null, "resets": null, "ordinary_usage_allowed": null}
      ```

      `as_of` 是毫秒（从 `timestamp` 换算）。

3. **Codex：实时读** `codex_live(server_factory) -> dict`
   1. `with server_factory() as s: r = s.call("account/rateLimits/read", {"excludeResetCreditDetails": False}, 20)`。
   2. 快照：`r["rateLimitsByLimitId"]["codex"]`，没有就 `r["rateLimits"]`。窗口从 `primary`、`secondary`（`usedPercent`、`windowDurationMins`、`resetsAt`）来。
   3. 整理成和第 2 条同样的格式，`source` 是 `"live"`，`as_of` 是现在的毫秒，`plan` 取 `planType`，`reached` 取 `rateLimitReachedType`，`ordinary_usage_allowed` 原样。
   4. `resets`：`rateLimitResetCredits` 是 null → null；否则 `{"available": availableCount, "items": [...]}`，`items` 只留 `status == "available"` 的，每条 `{"id", "title", "description", "granted_at", "expires_at"}`（秒）；`credits` 是 null → `items` 也是 null。
   5. **不要**把 `accountId`、`rateLimitUpsell` 放进去。
   6. 错误：`archives.ArchiveError`（找不到 Codex、进程退出、超时）→ `UsageError("读不到 Codex 的实时用量：" + 原文, 409, "codex_unreachable")`；`archives.CodexRefused`（后台程序回错误，比如老版本没这个方法、没用 ChatGPT 账号登录）→ `UsageError("Codex 没给用量：" + 原文[:120], 409, "codex_refused")`。

4. **窗口的格式**（Codex、Claude 共用）：
   - `kind`：`minutes == 300` → `"5h"`，`10080` → `"weekly"`，其他 → `"other"`。Claude 没有分钟数，按文字判断（见第 6 条）。
   - `used_percent`：四舍五入成整数，夹在 0–100 之间。
   - `resets_at`：Unix 秒，没有就 null。Claude 没有，用 `resets_text`。
   - `name`（给手机直接显示的中文）：`"5h"` → 「5 小时」，`"weekly"` → 「每周」，其他按分钟数写「{n} 小时」或「{n} 天」，Claude 见第 6 条。

5. **Codex：用掉一次重置** `codex_redeem(request_id, credit_id, server_factory) -> dict`
   1. 检查：`request_id` 必须匹配 `[A-Za-z0-9-]{8,64}`，否则 `UsageError("请求编号不对", 400, "bad_request")`。`credit_id` 是 None 或不超过 200 字的字符串。
   2. 记录文件 `data_dir / "attachments" / "codex-resets.jsonl"`（`data_dir` 默认 `app_paths.DATA`；开发时 `DATA` 就是仓库目录，`attachments/` 在 `.gitignore` 里，和 `remote.py` 1224 的 `computers.json` 放一起）。一行一个 JSON，最多留最后 200 行。测试一律传临时目录。这个 `request_id` 已经有最终结果（`reset`、`nothingToReset`、`noCredit`、`alreadyRedeemed`）→ 不再调 Codex，直接回那个结果（`usage` 用缓存的实时读，没有就记录里的）。
   3. 调之前先写一行 `{"request_id", "at", "stage": "sending"}`。
   4. `with server_factory() as s:`
      - `outcome = s.call("account/rateLimitResetCredit/consume", {"idempotencyKey": request_id, **({"creditId": credit_id} if credit_id else {})}, 30)["outcome"]`
      - 再 `s.call("account/rateLimits/read", ...)`，整理成第 3 条的格式，拿不到就 null（不影响结果）。
   5. 写一行 `{"request_id", "at", "outcome"}`；把新的用量放进实时缓存（第 7 条）；写日志（第 8 条）。
   6. 回 `{"ok": True, "outcome": outcome, "text": 下面那句, "usage": 新用量或 null}`。手机上原样显示，**一字不差照抄**：

      | outcome | text |
      |---|---|
      | `reset` | 已用掉 1 次重置，Codex 用量恢复了 |
      | `nothingToReset` | 现在没有能重置的限额，这次没用掉 |
      | `noCredit` | 没有可用的重置次数，这次没用掉 |
      | `alreadyRedeemed` | 这次之前已经用成了，没有再用掉一次 |
      | 别的值 | Codex 回了不认识的结果（{outcome}），请到电脑上的 Codex 里看用量 |

   7. 注意 `archives.CodexRefused` 是 `archives.ArchiveError` 的子类，`except` 要先接 `CodexRefused`。发出 `consume` 之后出错（超时、进程退出、读不懂回复）：写一行 `{"stage": "unconfirmed"}`，抛 `UsageError("没确认这次用成了没有。再点一次会用同一个编号重试，不会多用掉一次。", 409, "reset_unconfirmed")`。**发出之前**出错（开不了后台程序）：抛 `UsageError("没用掉：连不上电脑上的 Codex（" + 原文 + "）", 409, "codex_unreachable")`。后台程序回错误（`CodexRefused`）：`UsageError("Codex 没让用：" + 原文[:120], 409, "codex_refused")`。
   8. 同一时间只许一个 `codex_redeem` 或 `codex_live` 在跑（一把锁，和第 7 条共用）。

6. **Claude：读窗口** `claude_window(desktop) -> dict`，在 `desktop.run(fn, timeout=10)` 里跑（UI Automation 只能在那条线程上用）：
   1. `auto = desktop._need_auto()`；`hwnd = chats.app_window(chats.CLAUDE_PROCESS)`；没有 → `{"available": False, "reason": "电脑上 Claude 没开"}`。
   2. `root = auto.ControlFromHandle(hwnd)`；`buttons = desktop._find(root, "ButtonControl")`；挑第一个 `Name` 以 `"Usage: "` 开头的（区分大小写）。没有 → `{"available": False, "reason": "Claude 窗口上没有用量（要开着一个 Code 对话）"}`。
   3. 解析 `Name[len("Usage: "):]`，按 `", "` 切开：
      - 第一段匹配 `^(\d+)% of (.+)$` → 百分比、标签（如 `5-hour limit`）；或匹配 `^(.+): (\d+)%$` → 标签（如 `Weekly · all models`）、百分比。
      - 以 `Resets ` 开头的段 → `resets_text`：去掉 `Resets `；再是 `at h:mm AM/PM` 的话换成 24 小时制 `HH:MM`（`at 12:20 PM` → `12:20`，`at 9:05 AM` → `09:05`，`at 12:05 AM` → `00:05`）；别的写法原样留着（比如 `Fri 3:00 PM`）。
      - 别的段忽略。
   4. 标签 → `kind` 和 `name`：含 `5-hour` → `"5h"`、「5 小时」；以 `Weekly` 开头 → `"weekly"`，`name` 是「每周」，后面有 `· 名字` 时写「每周（{名字}）」，`all models` 写成「全部模型」；其他 → `"other"`，`name` 用原文。
   5. 回：

      ```json
      {"available": true, "source": "window", "as_of": 毫秒, "text": "Usage: 35% of 5-hour limit, Resets at 12:20 PM",
       "windows": [{"kind": "5h", "label": "5-hour limit", "name": "5 小时", "used_percent": 35, "resets_at": null, "resets_text": "12:20"}],
       "minimized": false}
      ```

      解析不了第一段时 `windows` 是 `[]`，`text` 照给（手机显示原文）。`minimized` 用 `win32gui.IsIconic(hwnd)`。
   6. **只读**：不点、不悬停、不恢复最小化、不拉到前面、不改焦点。出错（窗口读到一半没了等）→ `{"available": False, "reason": "这会儿读不到 Claude 窗口，请稍后再试"}`，不抛到外面。

7. **`class Usage`**（`remote.py` 的 `server.usage`）：`__init__(desktop, log, apps, server_factory=archives.CodexServer, records=codex_records, data_dir=DATA)`。
   - 一把锁（第 5.8 条）；实时缓存 `(monotonic 时间, 结果)`。
   - `read(live: bool) -> dict`：
     - `"codex" in apps()`：
       - `live` 为真：缓存不到 30 秒就用缓存，否则拿着锁调 `codex_live`（拿锁时别人正在读，就等它读完、用它的结果）。实时读失败 → 改用 `codex_records`，结果里加 `"live_error": 文字`。
       - `live` 为假：缓存不到 30 秒用缓存，否则 `codex_records`。
       - 都没有 → `{"available": False, "reason": "电脑上还没有 Codex 的用量记录（用一次 Codex 就会有）"}`；有就在结果里加 `"available": True`。
     - 没装 Codex → `{"available": False, "reason": "这台电脑没装 Codex"}`。
     - `"claude" in apps()` 而且 `desktop` 不是 None → `claude_window(desktop)`；没装 → `{"available": False, "reason": "这台电脑没装 Claude"}`。`desktop.run` 超时 → `{"available": False, "reason": "这会儿读不到 Claude 窗口，请稍后再试"}`。
     - 回 `{"codex": …, "claude": …, "now": 毫秒}`。`now` 让手机算"几分钟前"不受两边时钟差影响。
   - `redeem(body) -> dict`：`body.get("confirmed") is True`，否则 `UsageError("要先在手机上确认", 400, "not_confirmed")`；没装 Codex → `UsageError("这台电脑没装 Codex", 409, "no_codex")`；然后 `codex_redeem(...)`。

8. **日志**（`log(文字)`，不写账号、重置的 id 和标题、请求编号全文）：
   - 用重置：`Codex 重置：手机请求 <request_id 前 8 位> → <outcome>；之后可用 <n 或「未知」> 次`。
   - 没确认：`Codex 重置：手机请求 <前 8 位> 没确认结果（<异常类型名>）`。
   - 实时读失败：`用量：读不到 Codex 的实时用量（<code>）`，同一个 code 10 分钟内只写一次。
   - 读用量成功不写。

### 3.2 `remote.py`

1. `import usage_limits`。
2. `_get()`，在 `/api/notify`（519–521）后面：

   ```python
   if path == "/api/usage":  # 用量：Codex 和 Claude 的限额、几点重置；live=1 时 Codex 实时读（usage_limits.py）
       try:self._json(self.server.usage.read(self._query().get("live") == "1"))
       except usage_limits.UsageError as exc:self._json({"error":str(exc),"code":exc.code},exc.status)
       return
   ```

3. `_post()`，`body` 解析之后：`/api/usage/codex-reset` → `self.server.usage.redeem(body)`；`UsageError` → `{"ok": False, "error": 文字, "text": 文字, "code": code}`，状态码用它的 `status`；别的异常写 traceback、回 500 `{"error": "电脑端出错，没确认这次用成了没有，请到电脑上的 Codex 里看用量"}`。**任何情况都不回 503。**
4. `main()`，`server.archives`（1216 起）那几行后面：`server.usage = usage_limits.Usage(server.desktop, log.write, apps=lambda: server.machine["apps"])`。

### 3.3 手机上的样子（安卓、iPhone 一样）

下面引号里的字照抄。

**入口（两个，打开同一个「用量」页）**

1. 设置：选了电脑才有的那几组旁边，加一组「用量」，一行「Codex 和 Claude 的用量」。
2. 对话右上角 ⋯ 菜单：「会话状态」下面加「用量」。DeepSeek 的对话不加（DeepSeek 没有套餐限额）。

**打开时**：`GET usage?live=1`，没回来之前显示「读取中…」。下拉或点「刷新」再读一次（也是 `live=1`）。**不自动轮询。**

**Codex 那一块**（标题「Codex」）

- `available` 为假：只显示 `reason`。
- `reached` 不是 null：这一块最上面一行红字「Codex 的用量用完了」。
- 每个窗口：`name`（「每周」「5 小时」）和「已用 84%」，一条进度条，再一行重置时间：
  - `resets_at` 在今天：「今天 20:54 重置」；明天：「明天 20:54 重置」；别的日子：「11月18日 20:54 重置」（用手机的时区）。
  - 后面接「（还有 1 天 10 小时）」「（还有 3 小时 12 分）」「（还有 25 分钟）」；不到 1 分钟「（马上）」。
  - `resets_at` 已经过了：「已过重置时间」；`source` 是 `records` 时再接「，等电脑上 Codex 下一次回话就会更新」。
- 来源（小字、灰色）：
  - `source == "live"`：`now - as_of` 不到 60 秒写「刚从 Codex 读到」，否则「{n} 分钟前从 Codex 读到」。（用电脑给的 `now` 算，不用手机时钟。）
  - `source == "records"`：「来自电脑上 Codex 最近一次回话（{HH:mm}）。之后在别处用掉的，这里还没算上。」
  - 有 `live_error`：再一行「读不到实时用量：{live_error}」。
- 重置（只在 `resets` 不是 null 时显示）：
  - `available == 0`：「没有可用的重置次数」。
  - 否则一行「可用重置：{n} 次」，然后：`items` 是数组 → 每条一行：`title`（空的写「用量重置」），下面小字「{M月d日} 到期」（`expires_at` 为 null 写「不会过期」），右边按钮「用掉这一次」；`items` 是 null → 一个按钮「用掉一次」。
  - 请求进行中，按钮都变灰。
- `resets` 是 null、`source` 是 `records`：一行小字「重置次数要实时读到才显示，下拉刷新试试」。

**Claude 那一块**（标题「Claude」）

- `available` 为假：只显示 `reason`。
- 每个窗口：`name` 和「已用 35%」，一条进度条，再一行「{resets_text} 重置」（没有 `resets_text` 就不写这行）。`windows` 是空的：显示 `text` 原文。
- 小字：「读自电脑上的 Claude 窗口。Claude 只显示最紧的那一档。」；`minimized` 为真再接「Claude 窗口最小化了，数字可能是旧的。」
- 没有重置按钮。

**确认框**（点「用掉这一次」或「用掉一次」才出现，每次都出现）

- 标题：「用掉 1 次 Codex 重置？」
- 正文，一句一行：
  1. 「会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。」
  2. 点的是某一条：「这次用：{title}，{M月d日} 到期」（不过期写「这次用：{title}，不会过期」）。
  3. 每个窗口的 `used_percent` 都小于 90 时：「现在{name}还剩 {100 − used_percent}%，还没用完，现在用可能浪费。」只说 `used_percent` 最大的那个窗口。
- 按钮：「用掉 1 次」（红色 / destructive）、「先不用」（取消）。
- 没有任何不经过这个框就能用掉的办法（长按、双击、滑动都不行）。

**点了「用掉 1 次」以后**

1. 生成一个请求编号（UUID 字符串），记在这一页的状态里。`POST usage/codex-reset`，body `{"request_id": 编号, "credit_id": 这一条的 id（"用掉一次"时不放）, "confirmed": true}`。
2. 进行中：按钮变灰，显示「正在用…」。
3. 成功（2xx）：显示电脑给的 `text`（`outcome == "reset"` 用正常颜色，其他用灰色）；用回复里的 `usage` 换掉 Codex 那一块（`usage` 是 null 就再读一次 `usage?live=1`）；清掉请求编号。
4. 失败：
   - `code == "reset_unconfirmed"`，或者根本没拿到电脑的回复（网络断了、超时）：显示「没确认这次用成了没有。」和一个按钮「再试一次（不会多用）」，点它**用同一个请求编号**再 POST（不再弹确认框）。编号一直留到拿到最终结果。
   - 别的 `code`（`not_confirmed`、`bad_request`、`codex_unreachable`、`codex_refused`、`no_codex`）：显示错误原文，清掉编号（这些情况确定没用掉）。
5. 手机**绝不自动重试**。
6. 关掉这一页时编号还没清：下次打开不提它（电脑上有记录；「可用重置」的次数会说明到底用没用掉）。

**示例数据**（本地演示，两边一样）：Codex `source: "live"`，每周 84%，`resets_at` = 现在 + 34 小时，可用 1 次「Full reset」，30 天后到期；点「用掉 1 次」回 `reset` 和新的 `usage`（每周 0%，可用 0 次）。Claude：5 小时 35%，`resets_text` `"12:20"`。

### 3.4 安卓

1. `RelayApi.kt`：`DetailRoutes` 加 `"usage"`、`"usage/codex-reset"`；`SlowRoutes` 加 `"usage" to 45L`、`"usage/codex-reset" to 75L`。
2. 新文件 `Usage.kt`（不碰界面，JVM 能测）：
   - `data class UsageWindow(kind, name, usedPercent: Int, resetsAt: Long?, resetsText: String)`、`data class ResetCredit(id, title, expiresAt: Long?)`、Codex 和 Claude 各一个 data class、`fun parseUsage(json: JSONObject)`。
   - 纯函数：`resetLine(window, source, nowMs, zone)`（3.3 的重置时间那一行）、`sourceLine(…)`、`confirmText(credit, windows, zone)`。
   - `class ResetAttempt`：`id()` 没有就生成、有就复用；`done()` 清掉；`keepsId(e: Throwable)`：`ServiceFailure` 而且 `code == "reset_unconfirmed"`，或者不是 `ServiceFailure`（网络、超时）→ true。
3. 新文件 `UsageUi.kt`：`@Composable fun UsageSheet(vm: ReaderViewModel, onClose: () -> Unit)`，用 `TeleplySheet("用量", onClose)`，`LaunchedEffect(Unit)` 一打开就读；确认框是 `AlertDialog`，照 `ArchiveUi.kt` 311–330（确认按钮 `Text("用掉 1 次", color = p.error)`，取消按钮 `Text("先不用")`）。
4. `MainActivity.kt` `SettingsScreen`（255–294）：在 261 那段 `if(s.device!=null)` 里、「对话」那组后面加 `SectionLabel("用量")` 和 `CardSection { CardRow("Codex 和 Claude 的用量",{ usage=true },chevron=true) }`；加 `var usage by remember { mutableStateOf(false) }` 和 `if(usage) UsageSheet(vm) { usage=false }`（照 257、289 的 `archived`）。
5. `ChatUi.kt` `ChatMenu`（449–466）：452「会话状态」下面加 `if (s.app != "deepseek") MenuRow("用量", { sheets.usage = true }, icon = …)`，图标用已有的（比如 `TeleplyIcons.Clock`），不要新画；`ChatSheets` 加 `usage`，在画 `search`、`prompts` 的地方照样画 `UsageSheet`。
6. `FixtureApi.kt`：`usage`、`usage/codex-reset` 两个路由回 3.3 的示例数据。
7. 测试：
   - 新文件 `app/src/test/.../UsageTest.kt`：`parseUsage`（11-17 那份：每周 84%、1 次重置；只有记录：`resets` 为 null、有 `live_error`；Codex 不可用；Claude 不可用；Claude 解析不了只有 `text`）；`resetLine`（今天、明天、别的日子、已过 × `records`/`live`、"还有…"的几种长度，时区固定成 `Asia/Shanghai`）；`confirmText`（剩得多时有提醒、剩不到 10% 没有、不会过期、"用掉一次"没有条目）；`ResetAttempt`（`reset_unconfirmed` 和网络异常留着同一个编号；`codex_refused` 清掉；成功清掉）。
   - `RelayApiTest.kt` 加两条：`usage?live=1` 的路径；`usage/codex-reset` 的 POST body。
   - `ReaderUiScenarios.kt` 加一个场景（示例数据）：设置 → 用量 → 看到「已用 84%」和「可用重置：1 次」→ 点「用掉这一次」→ 出现确认框 → 点「先不用」，没有发 POST；再点 →「用掉 1 次」→ 显示「已用掉 1 次重置，Codex 用量恢复了」。

### 3.5 iPhone

1. `TeleplyModel/Relay.swift`：`detailRoutes` 加 `"usage"`、`"usage/codex-reset"`；`slowRoutes` 加 `"usage": 45`、`"usage/codex-reset": 75`。
2. 新文件 `TeleplyCore/Sources/TeleplyModel/Usage.swift`：和安卓第 2 条同样的结构和纯函数（从 `JSONValue` 解析），`public`，给 App 用。
3. 新文件 `Teleply/Settings/UsageView.swift`：`struct UsageView: View { let model: AppModel … }`，照 `ArchivedView` 的写法：`List`、`.task { await load() }`、`.refreshable { await load() }`、`.alert`（`Button("先不用", role: .cancel) {}`、`Button("用掉 1 次", role: .destructive) { … }`），导航标题「用量」，出错用 `describe(error)`。
4. `SettingsView.swift`：选了电脑才有的那几组旁边加一组「用量」，一行 `NavigationLink` 到 `UsageView(model: model)`，写法照「已归档对话」那一行。
5. `ConversationView.swift` `ConversationMenu`（431 起）：「会话状态」下面加「用量」（DeepSeek 的对话不加），点了用 `.sheet` 打开 `NavigationStack { UsageView(model: …) }`。
6. `Localizable.xcstrings`：这次新加的界面中文都补英文（比如「用量」Usage、「已用 {n}%」{n}% used、「用掉 1 次 Codex 重置？」Use 1 Codex reset?、「用掉 1 次」Use it、「先不用」Not now）。`Hints.swift`：电脑给的固定句子（3.1 第 5、6、7 条里的 `text`、`reason`）补英文。
7. `DemoTransport.swift`：`usage`、`usage/codex-reset` 回 3.3 的示例数据。
8. 测试：新文件 `TeleplyCore/Tests/TeleplyCoreTests/UsageTests.swift`，照安卓第 7 条的单元测试写同样几条；照 `RelayReadTests.swift` 的写法测两个路由的路径和 body。
9. 编不了：每一处都对着现有代码的写法核对（`JSONValue` 怎么取值、`describe(error)`、`Palette`、字体修饰、`PillStyle`）。第 9 节写清楚哪些地方最没把握。

---

## 4. 边界

- **只改**：新建 `usage_limits.py`、`tests/test_usage_limits.py`；`remote.py`（只加 3.2 那几处）；安卓：`RelayApi.kt`（两张表）、新建 `Usage.kt` `UsageUi.kt`、`MainActivity.kt`（只动 `SettingsScreen`）、`ChatUi.kt`（只动 `ChatMenu` 和 `ChatSheets`）、`FixtureApi.kt`（加两个路由）、新建 `UsageTest.kt`、`RelayApiTest.kt` 和 `ReaderUiScenarios.kt`（各加几条）；iPhone：`Relay.swift`（两张表）、新建 `Usage.swift` `UsageView.swift` `UsageTests.swift`、`SettingsView.swift`、`ConversationView.swift`（只动 `ConversationMenu`）、`Localizable.xcstrings`、`Hints.swift`、`DemoTransport.swift`、`RelayReadTests.swift`（加几条）；本文件第 9 节。
- **改每个文件之前**先跑 `git status --short <文件>`：要是它已经有不是你改的改动，**停下来告诉 Claude**，别动它。提交前 `git diff` 只能看到你的改动。`git add` 一个文件一个文件地加，提交用 `git commit -- <文件…>`，别把别人暂存的东西带进去。
- **不要碰**：`codex_control.py`、`chats.py`、`archives.py`、`new_conversations.py`（只调用，不改）；`claude_control.py`；`relay_*.py`；`live_events.py`；安卓 `ComposerUi.kt`、`WorkspaceController.kt` 的 `openOnComputer`、`ComposerAwayTest.kt`；iPhone `ComposerView.swift`、`ComposerChips.swift`、`WorkspaceModel.swift` 的 `openOnComputer`、`ComposerAwayTests.swift`（另一个会话刚改过）；网页（`remote.html`、`static/`）；`windows-version.json` 和发版脚本；`docs/` 里别的文件；用户没提交的 `deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`，以及别的会话没提交的文件。
- **登录**：不读 `~/.codex/auth.json`，不读 Claude 的任何登录文件，不直接调 chatgpt.com、claude.ai、anthropic 的接口。用量只从 Codex 自己的后台程序、Codex 的对话记录、Claude 的窗口拿。
- **重置次数是用户的东西，这台电脑上只有 1 次（12-13 到期）**：测试和核对里**绝对不能**对真 Codex 调 `account/rateLimitResetCredit/consume`，也不能经遥应的接口去用。测试一律用假的 `CodexServer`。对真 Codex **只许**调 `account/rateLimits/read`（第 5.4 节，一次）。
- **Claude 窗口只读**：不点、不悬停、不恢复、不拉到前面。
- 不打包、不安装、不启动或重启遥应（`G:\AgentRemote`）。不 push、不 rebase、不 amend。

---

## 5. 验证

### 5.1 基线

- Python：在仓库根目录跑 `D:\Personal\agent_remote\.venv\Scripts\python.exe -m unittest discover -s tests`，改之前跑一遍，原样输出存到工作区子文件夹 `20261117-usage-limits`。以前就坏的（和这次无关）：Playwright 浏览器缺（约 22 项出错）、`test_open_speed` 1 项失败；另一个会话的提交可能带来变化，以你开工时 main 上跑出来的为准。改完不能多出新的失败或出错。
- 安卓：在 `apps\android` 跑 `.\scripts\build.ps1`，改前改后各一次，记 JVM 测试条数。

### 5.2 新的 Python 测试（`tests/test_usage_limits.py`）

先写测试，在旧代码上跑一遍（模块不存在，应当全失败），存输出；再写代码。时间、文件、后台程序都用假的。

1. 记录：一个临时 `state_5.sqlite`（照 `tests/test_archives.py` 的 `threads_db` 造）+ 几个假 rollout：最新的 `token_count` 胜出；跨文件按 `timestamp` 比；最后一行是半行也能读；`limit_id` 是别的值的跳过；`secondary` 有 5 小时窗口；`rate_limits` 是 null 的跳过；一个都没有返回 None；文件比 512 KB 大时只读尾巴也能找到。
2. 窗口整理：300/10080/1440/其他分钟数的 `kind` 和 `name`；`used_percent` 83.6 → 84，-1 → 0，130 → 100。
3. 实时读：假 `CodexServer` 回 11-17 那份结果（第 1.2 节的值，`accountId` 填个假的）→ 格式对、没有 `accountId`、`resets.items` 只有 `available` 的；`credits` 为 null 时 `items` 为 null；`rateLimitResetCredits` 为 null 时 `resets` 为 null；只有 `rateLimits` 没有 `rateLimitsByLimitId` 时也行。
4. 实时读失败：`ArchiveError` → 用记录、带 `live_error`；`CodexRefused` → `codex_refused`；两样都没有 → `available: false` 那句。30 秒缓存：两次 `read(True)` 只开一次后台程序；过了 30 秒再开。
5. 用重置：
   - 四种 `outcome` 各一条：回的 `text` 一字不差，`consume` 的参数里 `idempotencyKey` 就是 `request_id`，给了 `credit_id` 才有 `creditId`；之后读了一次用量；记录文件两行；日志一行，**不含** `request_id` 全文、重置的 id 和标题。
   - 同一个 `request_id` 已有最终结果 → 不开后台程序，回原结果。
   - `consume` 超时（假的抛 `ArchiveError(..., 504)`）→ `reset_unconfirmed`，记录里是 `unconfirmed`；再来一次同一个 `request_id`，假的这次回 `alreadyRedeemed` → 回「这次之前已经用成了…」。
   - 开不了后台程序 → `codex_unreachable`、文字以「没用掉」开头，记录里没有 `sending`。
   - `confirmed` 不是 `True`（缺、`"true"` 字符串、1）→ 400 `not_confirmed`，没开后台程序。
   - `request_id` 太短、有怪字符 → 400。
   - 后台程序回的 `outcome` 不认识 → 对应那句，`{outcome}` 换成原值。
6. Claude 文字解析（纯函数，单独测）：`Usage: 35% of 5-hour limit, Resets at 12:20 PM` → 35、5h、「5 小时」、`12:20`；`Usage: Weekly · all models: 85%, Resets Fri 3:00 PM` → 85、weekly、「每周（全部模型）」、`Fri 3:00 PM`；`Usage: Weekly · Fable: 3%` → 「每周（Fable）」、没有 `resets_text`；`at 12:05 AM` → `00:05`；`at 9:05 AM` → `09:05`；`Plan usage unavailable`、`Usage: something new` → 解析不了时 `windows` 空、`text` 照给。
7. Claude 读窗口：假 desktop（`_need_auto`、`_find`、`run` 直接调）+ 打桩 `chats.app_window`、`win32gui.IsIconic`：没窗口、没有按钮、有按钮、最小化（`minimized: true`，**没有**调任何恢复窗口的函数）、读的时候抛 COM 错误。
8. `remote.py`：照 `tests/test_locked_send.py` 造假 handler：`GET /api/usage`、`GET /api/usage?live=1` 调对了 `read`；`POST /api/usage/codex-reset` 成功回 JSON；`UsageError` 回它的状态码和 `code`；别的异常回 500 那句；**状态码没有 503**。

### 5.3 全部测试

5.1 的两样再跑一遍，和基线逐条比对，写进第 9 节。

### 5.4 这台电脑上只读核对一次

写完以后，在仓库根目录用一个临时脚本（放工作区子文件夹，不进仓库）：`usage_limits.Usage(desktop, print, apps=lambda: ["codex", "claude"]).read(True)`，`desktop` 用真的 `chats.Desktop(log, threading.Lock())`。应当读到：Codex 每周已用约 84% 或更多，2026-11-18 20:54 重置（过了这个时间就是新的一周），重置 1 次、12-13 到期；Claude 一档、带重置时间。把结果（去掉 `id`）记进 9.4。**只许调这一次 `read`，不许调 `redeem`。**

### 5.5 这台电脑上做不了的

- iPhone 编译和 `TeleplyCore` 测试：Claude 问过用户、推送以后在 Codemagic 跑 `ios-native-check`。
- 真的用掉一次重置：要用户在手机上自己点。

---

## 6. 发布（不是你的事）

本地提交以后停下。不打包、不改版本号、不 push、不发版。Claude 审完再问用户：推送、Codemagic 编 iPhone、Windows 新版、安卓新版、iPhone TestFlight，每一步都先问。

---

## 9. 结果记录（接手的会话填）

### 9.1 改了哪些文件、各改了什么

**`usage_limits.py`（新建）**

- 文件头写了：数据从哪来（Codex 自己的 app-server 实时读、Codex 对话记录里每轮的 `token_count`、Claude 窗口上的按钮）；为什么用 Codex 自己的后台程序（遥应共用的 `codex-ipc` 只有对话方法，没有用量和重置；遥应不读登录，登录由 Codex 自己拿着）；为什么 Claude 只读窗口；11-17 在这台电脑上试过什么。
- `UsageError(chats.ChatError)`：`status` 默认 409、`code` 默认空。两个手机把 503 读成「电脑已离线」，所以这里从不回 503。
- `usage_window(minutes, used_percent, resets_at)`：窗口的通用格式。300 分钟是「5 小时」、10080 是「每周」、其他按分钟写「{n} 天」或「{n} 小时」（1440 → 「1 天」）；百分比四舍五入成整数、夹在 0–100。
- `codex_records(now=None)`：只读打开 `chats.codex_db()`，按 `updated_at_ms`（没有这列就用 `updated_at`）取最近 8 个 `rollout_path`；路径过 `chats._strip_unc`；每个文件只读最后 512 KB、丢掉可能半截的第一行、从后往前逐行 `json.loads`，坏行跳过；认 `event_msg` + `token_count` + `rate_limits` 是 dict + `limit_id` 是 `codex` 或 null；8 个文件里挑时间戳最新的；返回 `source: "records"`、`as_of`（毫秒）、`plan`、`windows`、`reached`，`resets` 和 `ordinary_usage_allowed` 都是 null。库读不了、或一条都没有时返回 None。`now` 参数按第 3.1 节的签名留着，但没用上（时间只听记录里的 `timestamp`）。
- `codex_live(server_factory)`：`account/rateLimits/read`（参数 `{"excludeResetCreditDetails": False}`，20 秒），拿 `rateLimitsByLimitId["codex"]`、没有就用 `rateLimits`；`resets` 从 `rateLimitResetCredits` 来（null → null；`credits` 是 null → `items` 也是 null；`items` 只留 `status == "available"` 的）；**不放 `accountId`、不放 `rateLimitUpsell`**。`CodexRefused` → `codex_refused`「Codex 没给用量：…」，`ArchiveError` → `codex_unreachable`「读不到 Codex 的实时用量：…」。
- `codex_redeem(request_id, credit_id, server_factory, data_dir=None, log=None, cached=None)`：`request_id` 必须匹配 `[A-Za-z0-9-]{8,64}`（否则 400 `bad_request`「请求编号不对」），`credit_id` 是 None 或不超过 200 字（否则 400「重置编号不对」）。记录文件 `data_dir/attachments/codex-resets.jsonl`（开发时 `data_dir` 就是仓库目录，`attachments/` 在 `.gitignore` 里），最多留 200 行。同一个 `request_id` 已有最终结果就不再开后台程序。先写 `stage: "sending"`，再 `account/rateLimitResetCredit/consume {"idempotencyKey": request_id(, "creditId")}`（30 秒），随后再读一次用量（读不到不影响结果）；四种结果的那四句话一字不差照第 3.1 节，别的值写「Codex 回了不认识的结果（{outcome}），请到电脑上的 Codex 里看用量」。发出之后出错（超时、进程退出、读不懂回复）写 `stage: "unconfirmed"` 并回 `reset_unconfirmed`；开不了后台程序回 `codex_unreachable`「没用掉：连不上电脑上的 Codex（…）」、记录里没有 sending；`CodexRefused` 回 `codex_refused`「Codex 没让用：…」。多出来的三个可选参数是为了第 7 条：`Usage` 拿记录文件、日志和自己的实时缓存，模块级函数要把它们传进来（缓存在重放时作为 `usage` 回给手机）。
- `claude_text(name)`：解析按钮名字（纯函数）。`Usage: ` 之后按 `", "` 切开，只认第一段（`{pct}% of {label}` 或 `{label}: {pct}%`），`Resets …` 段取重置时间：`at h:mm AM/PM` 换成 24 小时制，别的写法原样；`5-hour` → 5h「5 小时」、`Weekly · X` → weekly「每周（X）」（`all models` 写「全部模型」）、其他 → other，名字用原文。解析不了就是空 `windows`，`text` 照给。
- `claude_window(desktop)`：`desktop._need_auto()`、`chats.app_window(chats.CLAUDE_PROCESS)`、`auto.ControlFromHandle`、`desktop._find(root, "ButtonControl")` 挑第一个名字以 `Usage: ` 开头的。**只读**：不点、不悬停、不恢复最小化、不拉到前面。`minimized` 用 `win32gui.IsIconic`。没窗口、没按钮、读不了各回第 3.1 节那三句。
- `class Usage(desktop, log, apps, server_factory=archives.CodexServer, records=codex_records, data_dir=DATA)`：一把 `RLock`（`codex_live`、`codex_redeem` 和 `Usage` 共用；可重入，`Usage.read` 拿着它再调 `codex_live`）；实时缓存 `(monotonic, 结果)` 30 秒。`read(live)`：`live` 为真、缓存不到 30 秒就用缓存（等锁的线程拿到锁后会再查一次缓存，用别人的结果），否则调 `codex_live`，失败就改用 `codex_records` 并在结果里加 `live_error`（失败的结果也会进 30 秒缓存，避免一次刷新连开两次后台程序）；`live` 为假走 `codex_records`；没装 Codex / 没有记录各回第 3.1 节那两句；Claude 在 `desktop.run(claude_window, desktop, timeout=10)` 里读，超时或抛错回「这会儿读不到 Claude 窗口，请稍后再试」；回 `{codex, claude, now}`。`redeem(body)`：`confirmed` 必须是 `True`（否则 400 `not_confirmed`），没装 Codex 回 409 `no_codex`，然后 `codex_redeem`；成功后把新用量放进缓存。
- 日志：用重置一行（请求编号前 8 位、结果、之后可用几次或「未知」）；没确认时一行（前 8 位、异常类型名）；实时读失败一行（code），同一个 code 10 分钟内只写一次；读成功不写。都不写账号、重置的 id 和标题、请求编号全文。

**`remote.py`**（只加 3.2 那几处）

- `import usage_limits`。
- `_get()` 在 `/api/notify` 后面加 `/api/usage`：`read(self._query().get("live") == "1")`，`UsageError` 回 `{"error", "code"}` 和它的状态码。
- `_post()` 在 `/api/notify` 那组前面加 `/api/usage/codex-reset`：成功回 `redeem` 的结果；`UsageError` 回 `{"ok": False, "error", "text", "code"}`；别的异常写 traceback、回 500「电脑端出错，没确认这次用成了没有，请到电脑上的 Codex 里看用量」。**任何情况都不回 503。**
- `main()` 在 `server.archives` 后面加 `server.usage = usage_limits.Usage(server.desktop, log.write, apps=lambda: server.machine["apps"])`（`apps` 晚取）。

**`tests/test_usage_limits.py`（新建，51 个测试）**

- 假的 `CodexServer`（记录每次调用，按方法回 `answers`，`refuse` 抛 `CodexRefused`，`errors` 抛指定的异常）、临时 `state_5.sqlite` + 假 rollout 文件、假 `chats.Desktop`（`run` 直接调，`_need_auto`/`_find` 照真的形状，`run_error` 当超时）、`Clock`（移动 `time.monotonic`，不真等 30 秒），照 `tests/test_locked_send.py` 造假 handler 测 `remote.py` 的两条路由。没有一处碰到真的 Codex。

**安卓**

- `RelayApi.kt`：`DetailRoutes` 加 `"usage"`、`"usage/codex-reset"`；`SlowRoutes` 加 `"usage" to 45L`、`"usage/codex-reset" to 75L`。
- 新建 `Usage.kt`（不碰界面，JVM 能测）：`UsageWindow`、`ResetCredit`、`CodexUsage`、`ClaudeUsage`、`UsageReport`；`parseUsage`/`parseCodexUsage`/`parseClaudeUsage`；纯函数 `resetLine`（今天/明天/M月d日 + HH:mm + 「还有 …」/「马上」/「已过重置时间」，`records` 时接「，等电脑上 Codex 下一次回话就会更新」）、`sourceLine`、`confirmText`（三句，按第 3.3 节）；`ResetAttempt`：`id()` 没有就生成、有就复用，`done()` 清掉，`keepsId(e)` 只有 `reset_unconfirmed` 和「不是 `ServiceFailure`」留着编号。
- 新建 `UsageUi.kt`：`@Composable fun UsageSheet(vm, onClose)`，用 `TeleplySheet("用量", onClose)`（sheet 自己已经带滚动，里面不再套 `verticalScroll`，否则同方向嵌套会崩）；`LaunchedEffect(Unit)` 一打开就读 `usage?live=1`，右上「刷新」再读一次，不轮询；Codex/Claude 两块照第 3.3 节的顺序和文字；确认框是 `AlertDialog`（「用掉 1 次」红字、「先不用」），**两个按钮都先进这个框**；`reset_unconfirmed` 或没拿到回复时显示「没确认这次用成了没有。」和「再试一次（不会多用）」（用同一个编号、不再弹框）；时间都用电脑给的 `now` 算。
- `MainActivity.kt` `SettingsScreen`：`var usage`，「对话」那组后面加 `SectionLabel("用量")` + `CardRow("Codex 和 Claude 的用量")`，`if(usage) UsageSheet(vm) { usage=false }`。
- `ChatUi.kt`：`ChatSheets` 加 `usage`；`ChatMenu` 在「会话状态」下面加 `if (s.app != "deepseek") MenuRow("用量", …, icon = TeleplyIcons.Clock)`；`ChatSheetsHost` 里画 `UsageSheet`。
- `FixtureApi.kt`：两个路由；`FixtureWorld.usage()`（Codex `live`、每周 84%、`resets_at` = 现在 + 34 小时、1 次「Full reset」30 天后到期；Claude 5 小时 35%、`12:20`）和 `usageReset(body)`（`confirmed` 不对回 400 `not_confirmed`；对了回 `reset` 和新的 `usage`：每周 0%、0 次）。
- `UsageTest.kt`（12 个）、`RelayApiTest.kt` 加 2 个、`ReaderUiScenarios.kt` 加 1 个场景（设置 → 用量 → 看到「已用 84%」「可用重置：1 次」→「用掉这一次」→ 确认框 →「先不用」不发 POST → 再来一次「用掉 1 次」→ 显示「已用掉 1 次重置，Codex 用量恢复了」、变成「已用 0%」「没有可用的重置次数」）。

**iPhone**

- `Relay.swift`：`detailRoutes` 加 `"usage"`、`"usage/codex-reset"`；`slowRoutes` 加 `"usage": 45`、`"usage/codex-reset": 75`。
- 新建 `TeleplyModel/Usage.swift`：和安卓一样的结构（`UsageWindow`、`ResetCredit`、`CodexUsage`、`ClaudeUsage`、`UsageReport`）和纯函数（`UsageReport.parse`、`resetLine`、`sourceLine`、`confirmText`，另加 `resetExpiryLine` 给列表那行用）；`ResetAttempt` 是 `final class`（安卓也是 class），`id()`/`done()`/`keepsId(_:)`。
- 新建 `Teleply/Settings/UsageView.swift`：`List` + `.task`/`.refreshable` + `.alert`（「先不用」取消、「用掉 1 次」destructive），导航标题「用量」，出错用 `describe(error)`；电脑给的固定句子过 `Hints.text`。
- `SettingsView.swift`：`if model.device != nil` 里「对话」那组后面加 `Section("用量")` + `NavigationLink("Codex 和 Claude 的用量") { UsageView(model: model) }`。
- `ConversationView.swift` `ConversationMenu`：`@State usageShown`，「查找消息」下面加 `if model.app != "deepseek" { Button("用量", systemImage: "clock") }`，`.sheet` 打开 `NavigationStack { UsageView(model: model) }`。
- `Localizable.xcstrings`：加 16 条英文（纯新增，160 行；「已用 %lld%%」照仓库里「上下文 %lld%%」的写法把 % 写成 %%；文件保持原来的顺序和 LF 换行）。
- `Hints.swift`：电脑给的固定句子补英文（四种 `text`、没确认那句、四种 reason、`codex_unreachable`/`codex_refused`/`used` 的几种前缀）。
- `DemoTransport.swift` + `DemoWorld.swift`：`/api/usage`、`/api/usage/codex-reset` 回第 3.3 节的示例数据（`codexResetUsed` 记着用没用掉）。
- `UsageTests.swift`（12 个，和安卓同样的几条）、`RelayReadTests.swift` 加 1 个（`usage?live=1` 的路径和 45 秒、`usage/codex-reset` 的 POST body 和 75 秒）。

### 9.2 新测试的名字，和在旧代码上的结果

51 个，全在 `tests/test_usage_limits.py`。旧代码（`usage_limits.py` 还不存在）跑这份文件只有 **1 个 ERROR**：`ModuleNotFoundError: No module named 'usage_limits'`（模块导入失败，整个文件没跑起来），原样输出在工作区 `new-tests-on-old-code.log`。改完以后再跑：`Ran 51 tests ... OK`（`new-tests-after-code.log`）；全量里这 51 个也全过。

| 类 | 测试 |
|---|---|
| `RecordTests`（9） | `the_newest_token_count_wins_across_conversations`、`the_newest_line_of_one_conversation_wins`、`another_limit_id_and_a_null_rate_limits_are_skipped`、`a_secondary_five_hour_window`、`a_half_last_line_and_a_file_over_512_kb_are_read_from_the_tail`、`a_line_older_than_the_tail_is_not_used`、`no_conversation_with_usage_is_none`、`an_unreadable_thread_table_is_none`、`the_table_without_updated_at_ms_orders_by_updated_at` |
| `WindowTests`（2） | `kinds_names_and_minutes`、`used_percent_is_rounded_and_kept_within_0_and_100` |
| `LiveTests`（5） | `what_the_phone_shows_and_what_it_never_gets`、`credits_null_means_items_null_and_no_credits_means_no_resets`、`the_single_bucket_shape_works_too`、`a_server_that_cannot_start_says_codex_is_unreachable`、`a_codex_that_refuses_says_so_in_its_own_words` |
| `UsageReadTests`（8） | `live_then_the_cache_for_thirty_seconds`、`a_live_read_that_fails_falls_back_to_the_records_with_its_reason`、`a_refusal_is_logged_once_per_ten_minutes`、`neither_live_nor_records_says_there_is_no_usage_yet`、`a_read_without_live_uses_the_records`、`a_computer_without_an_app_says_so`、`claude_comes_from_its_window_and_a_timeout_says_so`、`now_is_given_so_the_phone_need_not_trust_its_own_clock` |
| `RedeemTests`（12） | `each_outcome_says_its_words_and_sends_the_request_id`、`no_credit_id_means_no_credit_id_in_the_call`、`two_record_lines_and_a_log_line_without_the_whole_request_id`、`a_request_that_already_has_its_answer_is_not_sent_again`、`an_unanswered_reset_keeps_the_same_request_id_and_may_have_worked`、`a_server_that_cannot_start_uses_nothing_and_records_nothing`、`the_phone_has_to_say_yes_first`、`a_request_id_that_is_short_or_odd_is_refused`、`a_reset_on_a_computer_without_codex_is_refused`、`a_refusal_from_codex_says_its_words`、`an_outcome_nobody_knows_is_shown_as_it_came`、`the_new_usage_replaces_the_cached_one` |
| `ClaudeTextTests`（5） | `the_five_hour_limit_with_its_reset_time`、`a_weekly_limit_with_another_reset_spelling`、`a_weekly_limit_for_one_model_and_no_reset_time`、`midnight_and_morning_are_twenty_four_hours`、`words_it_does_not_know_leave_the_windows_empty_and_the_text_whole` |
| `ClaudeWindowTests`（5） | `a_window_with_the_usage_button`、`a_minimised_window_is_only_said_to_be_minimised`、`no_claude_window_says_so`、`a_window_without_the_button_says_what_to_open`、`a_window_that_cannot_be_read_at_all_is_not_an_error_on_the_phone` |
| `RemoteRouteTests`（5） | `the_usage_route_asks_for_a_live_read_only_when_asked`、`a_usage_error_comes_back_with_its_code_and_status`、`a_reset_is_answered_with_the_computers_words`、`a_reset_error_keeps_its_code_and_its_status`、`another_error_is_a_500_and_never_a_503` |

### 9.3 全部测试（和基线比）

**Python**（仓库根目录，`python -m unittest discover -s tests`）

- 改前基线（11:09 起跑，`baseline-python-tests.txt`）：`Ran 879 tests`，`FAILED (failures=1, errors=22, skipped=6)`；23 条失败/出错的清单单独存成 `baseline-failures.txt`。
- 改后（`after-python-tests-verbose.txt`）：`Ran 930 tests`，`FAILED (failures=1, errors=22, skipped=6)`。930 = 879 + 51。
- 逐行比对 23 条：**完全一样**（`Compare-Object` 无差异，改后清单 `after-failures.txt`）。51 个新测试全过，6 条跳过和基线一样。
- 这 23 条和这次无关，都是以前就坏的：Playwright 浏览器缺（22 个 ERROR，webkit/chromium 那段）、`test_open_speed` 1 个 FAIL。

**安卓**（`apps\android` 里 `.\scripts\build.ps1`，四个任务都过）

- 改前：`BUILD SUCCESSFUL in 1s`（92 个任务 up-to-date）。为了确是跑出来的，又清掉 `app/build/test-results/testDebugUnitTest` 单跑 `testDebugUnitTest`：`BUILD SUCCESSFUL in 32s`，20 个 XML、**228** 个 JVM 测试、0 失败 0 出错（`baseline-android-tests.txt`）。
- 改后：`BUILD SUCCESSFUL in 1m 14s`，93 个任务，21 个 XML、**243** 个 JVM 测试、0 失败 0 出错（`after-android-build.txt`）。多出的 15 条 = `UsageTest` 12 条 + `RelayApiTest` 2 条 + `ReaderRobolectricTest.usageShowsBothAppsAndOneResetGoesThroughAConfirmation` 1 条；原来的场景照样过。
- lint 也过（`lintDebug` 没有报错）。

**iPhone**：这台电脑没有 Swift 工具链，没编译、没跑 `TeleplyCore` 测试（见 9.5）。

### 9.4 这台电脑上的只读核对（5.4）

用工作区的临时脚本（不进仓库）跑 `usage_limits.Usage(desktop, print, apps=lambda: ["codex", "claude"]).read(True)`，`desktop` 是真的 `chats.Desktop(log, threading.Lock())`（原样在 `read-only-check.txt`，下面是去掉 `id` 的结果）：

- Codex：`source: "live"`，`plan: "pro"`，每周 `used_percent: 85`、`resets_at: 1795006481`（2026-11-18 20:54 北京时间），`reached: null`，`ordinary_usage_allowed: true`；重置 1 次：`Full reset`、"Thanks for using Codex! You've been granted one free rate limit reset."，`expires_at: 1797115689`（2026-12-13 06:48 北京时间）。
- Claude：`source: "window"`，按钮原文 `Usage: 63% of 5-hour limit, Resets at 12:20 PM` → 一档 5 小时 63%、`resets_text: "12:20"`、`minimized: false`。（10:01 是 31%、10:06 是 35%，现在是 63%：它自己几分钟一变。）
- `as_of` 1794885752742 / 1794885752813，`now` 1794885752814；日志一行也没有（读成功不写）。
- **只调了这一次 `account/rateLimits/read`**，没有调 `consume`；没读 `~/.codex/auth.json`；没点、没恢复、没拉到前面 Claude 的窗口；没启动/关闭 Codex、Claude 或遥应。

### 9.5 没做的、拿不准的

- **iPhone 没编译过**：这台电脑没有 Swift 工具链，`Usage.swift`、`UsageView.swift`、`UsageTests.swift`、`Relay.swift`/`SettingsView.swift`/`ConversationView.swift`/`Hints.swift`/`DemoTransport.swift`/`DemoWorld.swift`/`RelayReadTests.swift` 的改动都只逐行对照了现有写法（`JSONValue` 的下标 + `string()/bool()/int64()/has()`、`describe(error)`、`Palette`、`captionFont()/noteFont()`、`PillStyle(wide:)`、`.alert(_:isPresented:)`、`Section`/`NavigationLink`、`#expect`）。推送后请在 Codemagic 上跑 `ios-native-check`。最没把握的地方，按没关系排序：
  1. `Text("已用 \(window.usedPercent)%")` 抽出来的键是「已用 %lld%%」（照仓库里「上下文 %lld%%」的写法加的）。如果 Xcode 抽成别的形式，英文界面会显示中文这一行。
  2. `data.map(UsageReport.parse)` 把静态方法当函数值传给 `Optional.map`。编译不过的话改成 `data.map { UsageReport.parse($0) }`。
  3. `UsageWindow` 的名字（「每周」「5 小时」）和 `resetLine`/`sourceLine`/`confirmText` 返回的是 `TeleplyModel` 里拼好的中文字符串，没走 `Localizable.xcstrings`；英文界面里这些句子仍是中文（电脑给的四句话走了 `Hints`）。
  4. `ResetAttempt` 是 `final class` 放在 `@State` 里：只用它的 `id()`/`done()`，界面不靠它重绘；`SWIFT_DEFAULT_ACTOR_ISOLATION: MainActor` 下没有隔离问题，但没编译验证过。
  5. `DemoWorld.usage()` 里 `.array([[...]])` 的嵌套字典字面量靠 `JSONValue` 的 `ExpressibleByDictionaryLiteral` 推断；同类写法 `DemoTransport` 里已有。
- **拿不准：实时读失败也进 30 秒缓存**。交接第 3.1 节只写了成功时的缓存；我把失败后的「记录 + live_error」也缓存了，免得一次刷新连开两次后台程序。想改成失败不缓存也很容易。
- **`codex_redeem` 多了三个可选参数**（`data_dir`、`log`、`cached`）：第 3.1 节给的是三个参数，但记录文件、日志和「缓存的实时读」都在 `Usage` 里，模块级函数只能靠参数拿。
- **`codex_records(now=None)` 的 `now` 没用上**：第 3.1 节只规定 `as_of` 从记录里的 `timestamp` 换算。
- **没做的事**：没对真 Codex 调 `account/rateLimitResetCredit/consume`，也没经遥应的接口用掉重置（这台电脑只有 1 次，是用户的）；没读任何登录文件；没直接调 chatgpt.com、claude.ai、anthropic；没打包、没安装、没启动或重启遥应；没 push、没 rebase、没 amend、没改版本号；没动 `chats.py`、`archives.py`、`codex_control.py`、`claude_control.py`、`relay_*.py`、`live_events.py`、两个 `ComposerUi.kt`/`ComposerChips.swift` 那条线、网页（`remote.html`、`static/`、`deploy/site/`）、`windows-version.json`、发版脚本、灵动岛；没碰用户没提交的 `deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`。
- 安卓 `UsageUi.kt` 一开始有个错：Codex 那两个按钮直接调了 `use()`，没先进确认框；`ReaderUiScenarios` 的场景当场发现（找「用掉 1 次 Codex 重置？」找不到），已改成先弹框。现在没有任何绕过确认框就能用掉重置的路子。

