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
