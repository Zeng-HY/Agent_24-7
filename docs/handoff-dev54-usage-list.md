# dev.54：Antigravity 用量；旧手机列表第一页不再变短

交接设计，2026-11-25，主会话（Claude）写，DeepSeek 实现。分支 `dev54`，从 `agent-registry` 的 57b32ad（已发布的 dev.53）切出，工作树 `D:/Personal/agent_remote_lanes/d54`。

## 0. 结论

- **A. Antigravity 用量。** 电脑端读 Antigravity 本机服务的额度汇总，按现有的用量格式交给手机，说明书里 Antigravity 的 `usage` 改成 true。已发布的安卓 1.0.10 已经有「其他助手的用量」区块，电脑装上 dev.54 就能看到；iOS 下一版加显示。
- **B. 旧手机列表。** 协议 1 的 `/api/chats`：先滤掉这台手机看不了的助手，再取一页、算翻页位置和总数。现在是先取 100 行再滤，第一页会变短。

## 1. 证据（主会话 11-25 核对过）

### A
1. Antigravity 的 `language_server.exe` 有 `RetrieveUserQuotaSummary`。11-25 用 `ag.py quota`（`C:\Users\39011\.claude\skills\antigravity\scripts\ag.py`，只打印形状，账号类字段隐藏）调用一次，body `{}`，回答的形状是：
   - `response.groups[]`：`displayName`（「Gemini Models」「Claude and GPT models」）、`description`（长文本）、`buckets[]`
   - 每个 bucket：`bucketId`、`displayName`（「Weekly Limit Remaining」「Five Hour Limit Remaining」）、`description`、`window`（`weekly` / `5h`）、`remainingFraction`（0–1 的小数，满额时是 1）、`resetTime`（UTC ISO，如 `2026-11-30T20:03:35Z`；满额时可能没有）
   - `response.description`：长文本
2. 电脑端的用量已经是通用的：
   - `usage_limits.Usage.read(live, include_agents=True)`（协议 2 的 `/api/usage`）对每个 `can("usage")` 的助手调 `read_usage` → `usage()`，结果放在 `agents.<id>`。
   - 统一地址 `/api/agents/<id>/usage` 走 `read_agent`。
   - `agents/base.py` 的 `usage()` 默认抛 `Unsupported`。
3. 一个窗口的格式：`usage_limits.usage_window(minutes, used_percent, resets_at)` → `{kind, minutes, used_percent, resets_at（秒）, name}`。
4. 安卓 1.0.10（`git show cfef820:apps/android/app/src/main/java/com/pocketagentdesk/teleply/Usage.kt`、`UsageUi.kt`）：
   - `parseAgentUsage` 读 `available`、`reason`、`source`、`as_of`（毫秒）、`text`、`windows[]`；每个窗口读 `kind`、`name`（或 `label`）、`used_percent`、`resets_at`、`resets_text`。
   - `GenericUsageBlock` 显示布局不是 `codex.v1` / `claude.v1` 的助手；`resetLine` 按 `source` 措辞。
5. `agents/antigravity.py` 已经有调本机服务的 `_hub()`（第 835 行附近）和 `_rpc(method, body, timeout)`（第 854 行附近），发送、批准、停止都用它们。

### B
1. dev.53 装后核对：协议 1 的 `/api/chats?app=all&limit=100` 只回 86 行。电脑先取最新 100 行（含 14 行 Antigravity），再对老手机滤掉；`total` 仍把 Antigravity 的约 490 行算进去。手机按 `has_more` / `cursor` 翻页，不会丢，但一页可能很短，甚至是空的。
2. 代码：`remote.py` 的 `/api/chats` 分支先调 `self.history.conversations(...)`，再按 `_visible_apps()` 过滤 `items`；`chat_history.py` 的 `conversations(app, limit, cursor, query, sort, status, status_resolver)`。

## 2. 怎么改

### A. Antigravity 用量
1. `agents/antigravity.py` 实现 `usage(self, *, live=False)`：
   - 用模块里的 `_rpc` 调 `RetrieveUserQuotaSummary`，body `{}`，超时 10 秒。
   - 每组的每个 bucket 生成一个窗口，用 `usage_limits.usage_window` 生成：
     - `window` 是 `5h` → 300 分钟，`weekly` → 10080，别的 → 0（kind 会是 `other`）；
     - `used_percent` = round((1 − remainingFraction) × 100)，夹在 0–100；缺 `remainingFraction` 的 bucket 跳过；
     - `resets_at` = `resetTime` 换成秒，没有就 None；
     - `name` = 组名 + 「 · 」+ 窗口名，比如「Gemini 模型 · 每周」。认识的组名翻成中文：`Gemini Models` → 「Gemini 模型」，`Claude and GPT models` → 「Claude 和 GPT 模型」；不认识的原样用。
   - 返回 `{"available": True, "source": "live", "as_of": 毫秒, "windows": [...]}`。顺序：组按 Antigravity 给的顺序；组内 5 小时在前、每周在后，和 Codex 一样。
   - 读不到时不抛错：Antigravity 没开 → `{"available": False, "reason": "Antigravity 没有打开，读不到用量"}`；接口出错 → `{"available": False, "reason": "读 Antigravity 用量没成功：<一句简短原因>"}`。日志照模块里 `_log_once` 的做法，同一个原因只记一次。
   - 缓存 30 秒（`usage_limits.CACHE_SECONDS`）；`live=1` 也用这份缓存，因为这个接口本身就是实时的。
   - `bucketId`、`description` 不往外传；csrf 令牌不打印、不记日志。
2. 说明书：只把 Antigravity 的 `capabilities.usage` 改成 true。
3. 测试（`tests/test_antigravity.py` 或新文件）：用假的本机服务回答，照上面的真实形状编。测这些：
   - 窗口换算、排序、中文组名、不认识的组名；
   - 没有 `resetTime`、`remainingFraction` 越界或缺失；
   - 服务没开、HTTP 出错、缓存；
   - 协议 2 的 `/api/usage` 里 `agents.antigravity` 有窗口；协议 1 的回答和现在一样，只有 `codex`、`claude`、`now`；
   - 统一地址 `/api/agents/antigravity/usage` 能读。
   - 测试不碰真的 Antigravity，也不碰真实数据。

### B. 旧手机列表
1. `/api/chats`：把这台客户端看得见的助手（`_visible_apps()`）传进 `history.conversations`。在那里先过滤，再取 `limit`、算 `cursor` 和 `total`。搜索、子对话、未分组那一行，规则都和现在一样，只是看不见的助手不算进来。
2. 协议 2 的结果必须和现在一字不差。
3. 测试：
   - 协议 1、混有新助手的对话时：数据够的话，一页正好满 `limit` 行；`total` 不含新助手；逐页翻完不重复、不遗漏；
   - 协议 2 不变；
   - `tests/test_read_golden.py`、`tests/test_action_golden.py` 不变。

## 3. 边界

- 三家一点不变：Codex、Claude 的用量格式和 `/api/usage` 协议 1 的回答都不变。
- 只读 Antigravity 的额度，不调用其他会改东西的接口。
- 不推送、不打包、不装、不发布、不改版本号文件（`windows-version.json`、`windows-release-notes.json`），这些由主会话做。

## 4. 验证

- 全量 pytest：和基线一样，只有 3 个已知的旧测试失败。
- 两套 golden 测试不变。
- 主会话会在本机用真的 Antigravity 读一次（只看形状），再打包 dev.54。

## 5. 结果（DeepSeek 填）

2026-11-25 做完。两件事分开提交，后来补了一个测试替身的修复和本节。没有推送、合并、打包、安装、发布，没改版本号文件；没有调用真的 Antigravity，也没有运行 `ag.py`；测试只用编的数据、假的本机服务和临时目录。

### 提交

- `911120b` A：Antigravity 用量（`agents/antigravity.py`、`tests/antigravity_fixtures.py`、`tests/test_antigravity.py`、`tests/test_unified_routes.py`）。
- `8e5e3aa` B：旧手机列表先滤再分页（`chat_history.py`、`remote.py`、`tests/test_chats_visible_apps.py`）。
- 之后一个提交：`tests/test_machines.py` 的假 `conversations` 跟上新参数，以及本文这一节。

### A 做了什么

- `AntigravityAgent.usage()` 用 `_rpc("RetrieveUserQuotaSummary", {}, 10)` 读本机服务的额度汇总：
  - `window` 为 `5h` → 300 分钟，`weekly` → 10080，别的 → 0；组内 5 小时在前、每周在后，组按 Antigravity 给的顺序。
  - `used_percent = round((1 − remainingFraction) × 100)`，夹在 0–100；缺 `remainingFraction`（或不是数字）的 bucket 跳过；`resetTime` 换成秒，没有或读不懂就 `None`。
  - 名字是「组名 · 窗口名」：`Gemini Models` → 「Gemini 模型」、`Claude and GPT models` → 「Claude 和 GPT 模型」，别的组名原样；输出只有 `kind`、`minutes`、`used_percent`、`resets_at`、`name`，不带 `bucketId`、`description`。
- 缓存 30 秒（`usage_limits.CACHE_SECONDS`），`live=1` 也用同一份缓存；测试里数过假服务的请求次数。
- 读不到不抛错：没开 → `{"available": False, "reason": "Antigravity 没有打开，读不到用量"}`；接口出错 → `"读 Antigravity 用量没成功：<一句简短原因>"`。失败照 `_log_once` 每天同一原因只记一次；返回值和日志里都没有 csrf 令牌。
- 说明书只改了 `capabilities.usage = true`。协议 1 的 `/api/usage` 仍只有 `codex`、`claude`、`now`；协议 2 的 `agents.antigravity` 有窗口；`/api/agents/antigravity/usage` 能读（协议 1 仍是 404）。
- 测试：`tests/antigravity_fixtures.py` 的 `FakeHub` 增加 `RetrieveUserQuotaSummary`（`quota`/`fail`）；`tests/test_antigravity.py::UsageTests` 覆盖窗口换算与排序、中文/不认识的组名、没有 `resetTime`、`remainingFraction` 越界或缺失、没开、HTTP 出错、回的格式不对、缓存、失败只记一次；`RouteTests` 覆盖协议 1/2 的 `/api/usage` 与统一地址。

### B 做了什么

- `chat_history.conversations(..., apps=None)`：给了 `apps` 就先滤 `found` 和 `stray`，再取 `limit`、算 `cursor` 和 `total`；搜索、子对话、未分组那一行也只在看得见的助手里找。
- `/api/chats` 协议 1 把 `_visible_apps()` 传进去；协议 2 仍按原来的范围取数，末尾的过滤照旧，所以结果和改前一字不差。
- 测试 `tests/test_chats_visible_apps.py`：14 条新助手 + 12 条旧助手时，协议 1 第一页正好满 `limit`（10 行）、`total = 12`；逐页翻是 5、5、2 共 12 条，不重复不遗漏；搜索和未分组不漏出新助手；协议 2 的回答和不带 `apps` 的同一调用逐字相同（去掉 `now` 后对比）。
- `tests/test_read_golden.py`、`tests/test_action_golden.py` 原样通过。

### 测试数字

- A 改前（`tests/test_antigravity.py tests/test_usage_limits.py`）：154 passed，24 subtests passed。
- A 改后：`tests/test_antigravity.py` 108 passed、5 subtests；`tests/test_usage_limits.py tests/test_unified_routes.py` 59 passed、19 subtests。
- B 改后：`tests/test_chats_visible_apps.py tests/test_agents.py` 32 passed；`tests/test_machines.py` 42 passed。
- golden 与列表相关的合并跑：76 passed；同一次里 `tests/test_list_status_filter.py` 的 7 条失败都是本机缺 Playwright webkit（`BrowserType.launch: Executable doesn't exist …webkit-2359\Playwright.exe`），与这次改动无关。
- 完整 pytest（`full-pytest-2.log`，2026-11-25）：**34 failed, 1360 passed, 6 skipped, 105 subtests passed**，10 分 23 秒。34 条失败里 33 条是这台机器没装 Playwright webkit（启动就失败），1 条是设计里已知的 `test_mobile_polish` 点击超时（`Locator.tap: Timeout 30000ms exceeded`）。没有本次改动引起的失败。
  - 第一次完整跑（`full-pytest.log`）多出 1 条 `tests/test_machines.py::PageTests::test_the_list_holds_only_the_apps_this_computer_has` 的 `KeyError: 'items'`：那条旧测试的假 `conversations` 只收 7 个参数，不接受新的 `apps`。已让假函数接受并按 `apps` 过滤，`tests/test_machines.py` 42 passed，重跑全量后这条不再出现（35 → 34，`KeyError` 0 条）。
- 这台机器没装 Playwright 浏览器，所以全量失败数比设计里写的「3 条」多；33 条启动失败是环境问题，和 dev.53 那几份交接里记的基线一致。

### 没做 / 留给主会话

- 没有推送、合并、打包、安装、发布；没改 `windows-version.json`、`windows-release-notes.json`。
- 没有用真的 Antigravity 读额度，也没有运行 `ag.py`：按设计，形状来自已有的证据，测试用假回答；真机读一次留给主会话。
- 没修这台机器缺 Playwright 浏览器的问题（要下载安装，属于停下来问用户的事）。

