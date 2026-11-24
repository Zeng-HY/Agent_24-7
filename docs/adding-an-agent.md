# 如何接入一家新助手

遥应（Teleply）电脑端通过 `agents/` 目录下的助手模块和 `agents/registry.py` 里的唯一名单管理所有桌面助手。新增一家助手（例如后续的 Antigravity）不需要在电脑端公共业务代码、老路由兼容表或网页公共代码里按名字加分支。

本文档按当前代码实际结构编写，所有示例均使用占位名称与测试数据。

---

## 一、一句话流程

1. 复制 `agents/testing.py` 作为模板，新建 `agents/<id>.py`（文件名必须与 `agent.id` 一致）。
2. 在模块里实现 `Agent` 子类：填写 `build_manifest()`、`detect()`，以及这家助手真正支持的读取/操作方法；文件末尾导出 `AGENT = YourAgentClass`。
3. 在 `agents/registry.py` 的 `AGENT_MODULES` 元组里加一行 `"agents.<id>"`。
4. 补齐单元测试并跑过 `tests/test_agents.py`、`tests/test_no_hardcoded_agents.py` 等检查。

Windows 打包配置 `deploy/windows/AgentRemote.spec` 使用 `collect_submodules('agents', filter=lambda name: name != 'agents.testing')` 自动收集 `agents/` 下的模块，因此不用改 `.spec`。打包后的自检（`AgentRemote.exe --self-test`，见 `relay_desktop.py`）会自动验证 `AGENT_MODULES` 中的每个模块都能加载、`agent.id` 与文件名一致，且 `testing` 不在正式包里。如果新助手带额外小程序，或需要在卸载时清理本机文件，目前还要改 `deploy/windows/version.py`、`setup.iss`、`relay_desktop.py`（以后会改成按名单统一处理）。

---

## 二、模块位置、命名与生命周期

- **文件路径**：`agents/<id>.py`。
- **ID 规则**：`^[a-z][a-z0-9_-]{0,31}$`（小写字母开头，可含数字、下划线和连字符，最长 32 字符）。
- **导出方式**：模块顶层必须有 `AGENT = YourAgentClass`（无参可调用，返回 `Agent` 实例）。
- **注册位置**：`agents/registry.py` 的 `AGENT_MODULES`。元组里的顺序不影响界面展示顺序，排序只看说明书的 `order`。
- **无状态提醒**：`registry.get(app)` 每次都会新建一个适配器实例，**不要把跨请求需要保留的业务状态存在 `self` 属性里**。真实助手直接读写自己的文件、数据库或本地服务；若内存测试桩需要跨请求保存状态，请参考 `agents/testing.py` 使用模块级字典并提供 `reset()`。

---

## 三、说明书（`manifest`）字段说明

每个助手在 `build_manifest()` 里调用 `agents.base.make_manifest(...)` 生成说明书。能力分成两层：
- **说明书（`manifest()`）固定、便宜**：只写这一版电脑程序能做什么，由基类在 `__init__` 里算一次，**不许读文件、查管道或走网络**，也不要为了动态能力覆写 `manifest()` 或 `can()`。
- **此刻的能力（`capabilities_now(server, conv_id)`）**：如果某家助手的能力会在运行中变化，覆写 `capabilities_now()`，返回 `{"capabilities": {...}, "notes": {"<能力名>": "<中文原因>"}}`（不变的助手保持默认返回 `None`）。它只在协议 2 的控制态接口和实时推送里下发 `capabilities_now` 与 `capability_notes`；`capabilities` 的键和类型必须和说明书一致，且每一项只能比说明书更窄（说明书为 `False` 的不能变 `True`，列表只能是子集），并附上不能做的中文原因。因为每个打开着的对话每秒都会调一次，读文件或管道的结果必须自己缓存（至少 2 秒）。服务端判断会变的能力时，改用 `can_now(capability, server, conv_id)`。

以 Codex 为例：说明书固定保留老路线的完整能力；运行时在老路线、新版应用工具路线（按钩子是否已信任区分停止、批准、回答）和未运行三条状态间切换时，由 `capabilities_now()` 返回此刻可用能力与中文原因。

`remote.py` 会在两个地方下发说明书：
- `GET /api/agents`（协议 2 客户端按需拉取）；
- 网页首屏注入 `window.MACHINE.agents`。

### 1. 基础与显示字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | `int` | 固定为 `1`（由 `make_manifest` 自动填入）。 |
| `id` | `str` | 助手唯一标识，与模块文件名一致。 |
| `name` | `{"zh": str, "en": str}` | 中英文显示名；网页端优先显示 `zh`，缺省退回 `en`，再缺退回 `id`。 |
| `order` | `int` | 展示顺序，正式名单里不能重复。当前已占：`codex=10`、`claude=20`、`deepseek=30`（假测试助手 `testing=99`）。新助手建议从 `40` 起。 |
| `color` / `color_dark` | `str` | 浅色 / 深色模式下的十六进制品牌色（如 `#4285F4`）；未传 `color_dark` 时自动复用 `color`。 |
| `icon` | `dict` | 图标描述，支持两种形式：`{"kind": "builtin", "key": "..."}` 或 `{"kind": "url", "path": "/...", "etag": "..."}`。 |
| `legacy` | `bool` | **新助手一律填 `False`**。只有历史三家为 `True`。 |
| `min_protocol` | `int` | **新助手一律填 `2`**。只有历史三家为 `1`。 |
| `ui` | `dict` | `{"card_layout": "generic.v1", "waiting_text": "等待你处理"}`。 |
| `sources` | `dict` | 可选的诊断信息（例如 `{"catalog": "sqlite", "transcript": "jsonl", "control": "none", "live": "file-poll"}`）。 |

> 关于 `icon` 的当前实现：网页端 `static/agents.js` 内置了 `codex`、`claude`、`deepseek` 三个矢量图标和一套通用图标（`key: "generic"` 或任何未知 key 都会回退到通用图标）。自定义图标目前没有按助手提供的图标地址，新助手先用通用图标（`{"kind": "builtin", "key": "generic"}`）；**不要为了某一家助手去改 `remote.py` 的 `STATIC_FILES`**。

### 2. 能力位（`capabilities`）

`agents/base.py` 中的 `CAPABILITIES` 默认全部为 `False` 或空列表。说明书**只把模块真正实现的能力标成 `True`**，未实现的保持 `False`，客户端会自动隐藏对应按钮或入口：

| 字段 | 默认值 | 含义 |
|---|---|---|
| `list` | `False` | 能在列表里列出对话 |
| `read` | `False` | 能读取对话内容 |
| `search` | `False` | 支持按关键词搜索 |
| `open` | `False` | 支持在电脑端打开/聚焦该对话 |
| `stop` | `False` | 支持停止当前正在跑的一轮 |
| `queue` | `False` | 支持发送排队及队列管理 |
| `steer` | `False` | 支持运行中插话补充 |
| `approve` | `False` | 支持审批/权限卡片确认 |
| `answer` | `False` | 支持回答提问卡片 |
| `new` | `False` | 支持从手机新建对话 |
| `new_projectless` | `False` | 支持不选项目目录直接新建 |
| `new_permission` | `False` | 新建时需要选择权限级别 |
| `archive` / `restore` / `delete` | `False` | 支持归档、恢复、永久删除 |
| `usage` | `False` | 支持读取额度/用量 |
| `waiting` | `False` | 有「等你处理」状态（批准或提问） |
| `attachments` | `False` | 支持上传图片/附件 |
| `slash_commands` | `False` | 支持 `/` 斜杠命令列表 |
| `settings` | `[]` | 支持调整的设置项列表（如 `["model", "effort"]`） |
| `send_modes` | `[]` | 支持的发送方式，取值子集为 `["send", "steer", "queue"]`；只读助手留 `[]`，网页和手机会自动禁用发送按钮 |
| `statuses` | `["running", "waiting", "idle", "unknown"]` | 这家助手可能出现的状态集合；没有等待态的助手应设为 `["running", "idle", "unknown"]` |

### 3. 运行参数（`params`）

`agents/base.py` 的 `PARAMS` 提供 8 个默认值，按需覆写：

```python
{
    "state_timeout_s": 40,       # 读控制态超时（秒）
    "send_timeout_s": 60,        # 发消息超时（秒）
    "open_timeout_s": 45,        # 电脑上打开超时（秒）
    "new_timeout_s": 60,         # 新建对话超时（秒）
    "refresh_ms": 2500,          # 轮询刷新间隔（毫秒）
    "max_images": 5,             # 单次最多附件图片数
    "max_image_bytes": 52428800, # 单张上限（50 MB）
    "max_text": 20000,           # 单条文本上限（字符）
}
```

### 4. `card_layout` 说明

- 历史三家保留各自专属面板布局：`codex.v1`、`claude.v1`、`deepseek.v1`。
- 新助手一律填 `"generic.v1"`，网页与新版手机端会自动使用通用对话控制面板，不需要在前端新增按名字判断的代码。

---

## 四、模块要实现哪些方法

基类 `agents.base.Agent` 已经为所有动作提供了默认实现：未实现的方法会抛出 `Unsupported`（统一 HTTP 路由会转成 `400 {"error": "...", "code": "unsupported"}`）；对话不存在时请抛出 `NotFound`（转成 `404`）。

### 1. 最小只读助手（第一阶段推荐）

先让手机能「看到并读到」对话，只需实现：

- `build_manifest(self) -> dict`：返回固定的说明书（不读文件、管道或网络）。
- `detect(self) -> bool`：检查本机是否安装了该助手（只做轻量目录/文件存在性检查，**绝不启动程序或碰桌面窗口**）。
- **测试隔离路径**：`detect()` 和所有读取本地文件的路径，都必须通过 `machines.HOME`、`machines.LOCALAPPDATA`、`machines.APPDATA` 这类测试能替换的变量拼接，不要直接用 `Path.home()` 或硬编码用户目录；开发用的电脑上可能真装着那个桌面应用，直接读用户目录会让测试读到真东西。
- `catalog(self, *, limit=40, cursor="", query="", sort="updated", status="all") -> dict`：分页列出对话，返回 `{"items", "has_more", "next_cursor", "total"}`。
- `catalog_entries(self, limit: int) -> list[dict]`：给统一列表/项目树读取近期对话行（通常直接调 `self.catalog(limit=limit)["items"]`）。
- `find(self, conv_id: str) -> dict`：按 ID 找到单条记录，找不到抛 `NotFound`。
- `summary(self, item: dict) -> dict`：返回 `status`、`preview`、`modified`、`turn_started`、`turn_ended`、`step`。
- `read(self, conv_id: str, *, limit=60, before="", around="", lite=False) -> dict`：读取消息页。
- `transcript(self, tid: str)`：若助手不是按 `chats.py` 通用 JSONL 文件路径读取，实现此方法返回 `(item, entry)`（参见 `agents/testing.py`）；若走本地记录文件，则实现 `transcript_path(item)` 与 `parse_lines(lines, ...)`。
- `project_group(self, item: dict)`：返回 `(group_key, display_name, place)` 供侧栏项目树分组。
- `state(self, conv_id: str, *, fresh=False) -> dict`：返回当前运行状态（至少含 `available`、`running`、`status`）。

### 2. 按能力逐项补齐的动作方法

只有把对应 `capabilities` 改成 `True`（或把模式加入 `send_modes`）时才需要实现：

- **发送与回执**：`send(payload)`、`check(conv_id, offset, text)`
- **停止 / 队列 / 回答 / 电脑上打开**：`stop(payload)`、`queue(payload)`、`answer(payload)`、`open(conv_id)`
- **新建对话**：`new_options(svc)`、`create(payload)`、`create_status(request_id)`（若直接自己管理新建流程而非走 `new_conversations.NewConversations` 状态机，将类属性设为 `new_managed = False`，参考 `agents/testing.py`）
- **归档 / 恢复 / 删除**：`archive(conv_id)`、`restore(conv_id)`、`delete(conv_id)`、`archived_list(svc)`
- **用量 / 附件 / 命令**：`usage(live=False)`、`upload(conv_id, name, raw)`、`commands(conv_id, *, references=None, deepseek=None)`（其中 `deepseek` 参数是历史遗留，新助手忽略它即可）
- **运行中变化的能力**：`capabilities_now(server, conv_id)` 返回此刻的能力字典与中文原因（不变返回 `None`），并自带至少 2 秒缓存；服务端检查会变的能力用 `can_now(capability, server, conv_id)`。
- **服务生命周期**：`on_server_start(cfg, apps, log)`（服务启动前准备）、`on_server_init(server)`（HTTP 服务建好后启动后台任务或连接）、`on_server_close(server)`（服务退出时清理关闭）。
- **实时推送（SSE）**：`watch(bridge, tid)`、`control(bridge, tid)`、`wait_update(bridge, tid, timeout)`。注意：这三个方法收到的 `bridge` 参数目前总是 Codex 的连接对象（见 `remote.py:928`），**新助手不要用它**；需要一直开着的后台东西（例如本地监听、长连接），应在 `on_server_init(server)` 里建立、存在自己模块的模块级对象里，并在 `on_server_close(server)` 里关闭，不要挂在 `self` 上，也不要挂在 `server.codex` 上。
- **通知监控**：非文件扫描类助手将类属性设为 `notify_uses_file = False`，实现 `notify_conversations(limit)` 和 `notify_poll(notifier, found, item)`；文件扫描类助手实现 `notify_turn_end(lines)` / `notify_scan_record(scan, rec)`

### 3. 统一 HTTP 地址自动接好

`remote.py` 和 `Agent.http_get` / `http_post` 已经为所有助手接好了 13 条统一动作路由，实现上述方法即可生效，无需改 `remote.py`：

- `GET`：`/api/agents/<id>/state`、`receipt`、`options`、`commands`、`usage`、`create/state`
- `POST`：`/api/agents/<id>/send`、`stop`、`queue`、`answer`、`open`、`create`、`upload`

读取和归档继续共用通用路由：`/api/chats`、`/api/chat`、`/api/events`、`/api/chat/projects`、`/api/chat/archive`、`/api/chat/unarchive`、`/api/chat/delete`、`/api/chat/archived`。

---

## 五、为什么不用动老路由前缀表（`agents/legacy.py`）

`agents/legacy.py` 集中存放重构前遗留给老版本客户端的兼容映射：
- `/api/codex/*`、`/api/claude/*`、`/api/deepseek/*` 三个旧前缀；
- 默认助手 `DEFAULT_APP = "codex"`；
- 旧网页标记 `claude_archive` 和 `/api/chat/send|enter|check` 对 DeepSeek 的旧提示。

这些路由只为保证未升级的老手机还能正常连三家旧助手。**任何新助手都通过 `/api/agents/<id>/…` 与通用路由工作，永远不需要往 `agents/legacy.py` 里加任何条目。**

---

## 六、协议 1 和协议 2 的区别

客户端通过以下方式告知电脑端自己支持说明书协议：
- 普通 HTTP 请求带请求头 `X-Teleply-Protocol: 2`（网页版 `api()` 和新版手机端会自动带上）；
- 不能自定义请求头的连接（如 `EventSource` 访问 `/api/events`）带查询参数 `protocol=2`；
- 两者都没带或格式不合法时，电脑端一律按协议 `1` 处理。

电脑端（`remote.py` 的 `_client_protocol()`、`_app_visible()`、`_visible_apps()`、`_agent_for_unified()`）的过滤规则：

| 行为 | 协议 1（老客户端） | 协议 2（新网页 / 新手机） |
|---|---|---|
| `GET /api/agents` | 返回 `404` | 返回 `200` 及当前电脑已安装助手的说明书 |
| 列表 / 详情 / 项目树 / 归档 / 搜索 / 命令 / 引用 | 只显示 `legacy=True` 的三家；访问 `legacy=False` 的助手返回 `404` | 显示全部已安装助手 |
| `/api/agents/<id>/…` | 只能访问 `legacy=True` 的助手；访问新助手返回 `404` | 可访问全部已安装助手 |
| `GET /api/usage` | 只返回旧的顶层字段 | 保留旧字段并额外带上 `agents` 字典 |

经中转隧道访问电脑端时，`relay_transport.py` 的 `REQUEST_HEADERS` 已放行 `X-Teleply-Protocol` 和 `X-Teleply-Client`，因此经 `relay_agent.py` 转来的请求也能正常识别协议 2。

---

## 七、网页和手机怎么显示新助手与不认识的助手

- **网页版（`static/agents.js` + `remote.html`）**：
  - 打开页面时从 `window.MACHINE.agents` 读取说明书（只在打开时读一次），动态渲染筛选标签、侧栏图标、新建面板按钮、归档说明以及各操作按钮的显隐；运行中会变的能力从控制态里的 `capabilities_now` 读取（`Agents.canNow` / `settingsNow` / `modesNow` / `noteNow`）。
  - `card_layout` 不是三家专属布局时，自动走通用面板 `window.genericAgentUI`（调用 `/api/agents/<id>/state|send|stop|receipt`）；如果 `send_modes` 为空，发送按钮自动禁用，只读不出错。
  - 遇到说明书里没有的未知助手 ID 时，不会冒充 Claude 或 Codex，而是直接用 ID 作为显示名、使用中性灰 `#6b7280` 和通用图标，可以正常阅读且禁用发送、打开、停止按钮。
  - 如果网页连上的是还没下发 `window.MACHINE.agents` 的老电脑，`static/agents.js` 会自动启用内置三家兜底。
- **手机端（安卓 / iOS）**：
  - 按电脑版本号缓存 `/api/agents` 说明书（启动或切换电脑、电脑升级时刷新），并按说明书显示名字、颜色、图标和能力；未知布局走通用面板，未知助手用通用样式且不崩溃；连老电脑时回退内置三家与老路由。
  - 因为网页和手机都会按电脑版本缓存说明书，**运行中会变的能力必须走控制态的 `capabilities_now`，不能靠改说明书**。

---

## 八、中转怎么放行与发布顺序

1. **隧道请求头**：`relay_transport.py` 中的 `REQUEST_HEADERS` 包含 `X-Teleply-Protocol` 和 `X-Teleply-Client`，中转服务与电脑端保持同一白名单，放行这两个头并继续丢弃名单外的头。
2. **推送事件与通知**：
   - 电脑端 `notify.py` 通过 `/api/notify/push` 向中转发送 `running`、`step`、`waiting`、`done`、`failed`、`snapshot` 事件。
   - 中转侧需要完成第 3 步升级部署（取消 `relay_push.py` 里的三家白名单，新增 `push_phone_protocol` 和 `push_agent_meta` 表，按每部手机登记的 `protocol` 过滤 `min_protocol > 1` 的助手），让老手机收不到新助手的通知和灵动岛，新手机按推送携带的名称/颜色/图标展示。
3. **发布顺序要求**：
   - 在中转完成上述一次性部署之前，电脑端 `notify.py` 保持原有推送字段不变（不发 `app_name` / `min_protocol`）。
   - 以后接入第一个正式新助手（`legacy=False`）前，先确认中转已部署第 3 步；之后每再加一家新助手，**只需发布 Windows 电脑端新版，中转和已支持协议 2 的手机端都不用再改代码或重新发版**。

---

## 九、测试清单（以假测试助手为例）

`agents/testing.py` 是仓库内置的假测试助手（`id="testing"`，`legacy=False`，`min_protocol=2`），全部数据在内存里编造，不碰任何真实文件。它**不在** `AGENT_MODULES` 正式名单里，只在源码测试时通过 `TELEPLY_TEST_AGENTS=1` 或 `include_testing=True` 加载；打包版（`sys.frozen`）会无视该环境变量，且 `AgentRemote.spec` 会排除该文件。

新增助手后，按下面顺序验证：

1. **统一契约与全链路测试**：
   ```powershell
   python -m pytest tests/test_agents.py tests/test_unified_routes.py tests/test_relay_protocol_headers.py tests/test_web_agents.py
   ```
   - `tests/test_agents.py` 会自动对 `registry.load()` 里的每个助手检查说明书字段、`order` 唯一性、JSON 可序列化、`detect()` 行为，并用假测试助手验证 `/api/agents` → `/api/chats` → 动作 → 中转推送事件的完整流程以及协议 1 隐藏。
   - 注意：`tests/test_agents.py` 的 `ManifestTests` 里目前有三条针对现有三家的断言（正式名单顺序、全部为 `legacy=True`、以及 `name.zh == name.en`）；正式加入第 4 家助手时按新助手实际情况更新这几条断言，并额外补充它的 `detect()` 测试和假数据读写/动作单测。
2. **公共代码写死名字检查**：
   ```powershell
   python -m pytest tests/test_no_hardcoded_agents.py
   ```
   - 自动用 `ast` 扫描电脑端公共 Python 文件中的助手 ID 字符串、私有模块导入与按助手名取属性。只要公共分发代码里出现新增的写死分支就会失败。**不要为了过测试往白名单或冻结表里加新条目**，应把按家差异收进 `agents/<id>.py`。
3. **三家老行为回归测试**：
   ```powershell
   python -m pytest tests/test_read_golden.py tests/test_read_compat.py tests/test_action_golden.py
   ```
4. **打包自检**：
   - 打包后在临时数据目录下执行 `AgentRemote.exe --self-test`，确认退出码为 `0`，新模块已打包进 `PYZ`，且 `agents.testing` 不在包内。

---

## 十、公开仓库隐私提醒

本仓库为公开仓库。编写助手模块、示例文档、测试夹具和提交说明时：
- 所有测试和示例数据一律编造（如 `example`、`测试助手`、`测试对话 A`、`C:\测试\项目`）；
- 严禁写入真实用户的对话标题、消息内容、本地真实项目路径、个人姓名、电脑名、账号、令牌或密钥。
