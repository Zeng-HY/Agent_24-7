# 交接：用户目录被误删后，新建对话报 502、Codex 对话一直「连接中断」（2026-11-12）

写给接手修复的 DeepSeek Harness 会话。原因已经查清，两个看得见的毛病都在临时目录里重演过；你要做的是照第 5 节改代码、补测试，在第 9 节记结果。代码位置按 main 的 589e57a 写，行号可能前后差几行。

---

## 0. 结论

今天 14:40 左右，用户目录 `C:\Users\39011` 下的大量文件被误删（一个 DeepSeek 会话在 PowerShell 里把 `$home` 当变量名用了）。遥应电脑端（`G:\AgentRemote`，dev.35）从 11-04 起一直在跑，它的数据文件夹 `%LOCALAPPDATA%\AgentRemote\Data` 被删空了，但进程没重启，还在用内存里的东西。

问题出在电脑端的写法：好几个小数据库只在**启动时**建一次表。文件被删以后，下次用到时 `sqlite3.connect` 自动建出一个空库，里面没有表，于是抛 `sqlite3.OperationalError: no such table`。这个错不在处理函数接的那几种错误里，处理函数没回答就断了连接；电脑端连中转的那一段（`relay_agent.py`）把它报成 502，手机上就看到 502 或者「连接中断」。这些错也没写进日志（`Server` 没有记录未接住的错误，打包版的 stderr 接到了 DEVNULL），所以当天日志里一行痕迹都没有。

| 编号 | 用户看到的 | 原因（一句话） | 状态 |
|---|---|---|---|
| 删-1 | 新建对话面板一打开就红字「请求失败（HTTP 502），请核对后重试」，加图片也 502；Codex、Claude、DeepSeek 都一样 | `new-conversations.sqlite` 被删；19:03 再用时建出 0 字节的空库，`create_draft`、`upload`、`submit` 都抛 `no such table: requests` | 已坐实，已重演 |
| 删-2 | Codex 对话页反复出现「连接中断，正在重连」；Claude、DeepSeek 不会 | `delivery.sqlite` 被删；17:40 再用时只建回 `deliveries` 表，`desktop_dismiss` 表没了（它只在启动时由 `DismissManager` 建）。凡是状态里有提问卡（答过的也算）的 Codex 对话，`Bridge.status()` 都抛 `no such table: desktop_dismiss`：读状态的接口回 502，实时流第一圈就断 | 已坐实，已重演 |
| 删-3 | 还没出现：手机给 DeepSeek 发消息、新建 DeepSeek 对话会 502 | `deepseek-requests.sqlite` 也只在启动时建表；删了以后还没人从手机发过 DeepSeek，所以文件还不存在，第一次发就会出错 | 读代码推断 |
| 删-4 | 还没人注意到：Claude 的提问卡和权限请求不再推到手机 | `~/.claude/settings.json` 整个没了，电脑端装在里面的 PermissionRequest hook 也没了；电脑端只在启动时装一次 | 已查到文件不存在 |
| 删-5 | 下次重启才出现：电脑端重启后会变成一台没绑定的新电脑 | `remote_config.json`、`device-v2.bin`、`desktop-preferences.json` 都被删了。正在跑的进程把它们留在内存里，所以现在还能用；一重启就会新生成口令和配置，读不到设备凭证，要重新登录绑定 | 已查到文件不存在 |

**今晚的临时办法由用户自己决定，接手的会话不要做**：重启电脑端（托盘图标右键退出，再从开始菜单打开），删-1 到删-4 当场就好，因为启动时会重新建表、重新装 hook；代价是删-5：要重新登录，绑定时选原来那台电脑。

---

## 1. 用户看到的现象（11-12 晚，iPhone）

1. **19:04**：Codex 对话「安排领取下载并启动新单」（项目 语言桥），顶部黄条「连接中断，正在重连」。用户说 Codex 的对话经常这样，Claude 的不会。
2. **19:05**：新建对话面板（选的 Claude），红字「请求失败（HTTP 502），请核对后重试。」，图片附件那一格也写着「请求失败 (H…」。用户说三家都这样。
3. **21:04**：同一部手机给一个已有的 Claude 对话发两张图，成功了（`Data\attachments` 下多了两个图片文件夹）。所以**已有对话**的图片上传没坏，坏的是新建面板。

---

## 2. 证据（都只读，不要改、不要删）

### 2.1 数据文件夹现在的样子

`%LOCALAPPDATA%\AgentRemote\Data` 下只剩：

- `account-webview\`（10-23 的，没被删）
- `logs\`：只剩 `20261112.log`（进程一直开着它，所以删不掉），更早的日志都没了
- `attachments\`：17:40:36 重新建的，里面只有 `delivery.sqlite`（17:40:36）、`new-conversations.sqlite`（19:03:42，0 字节）和 21:04 那两张图的文件夹

用 `mode=ro` 只读打开查到：

- `new-conversations.sqlite`：0 字节，一张表都没有。
- `delivery.sqlite`：只有 `deliveries` 一张表（5 行），没有 `desktop_dismiss`。
- `deepseek-requests.sqlite`：不存在。
- `remote_config.json`、`device-v2.bin`、`desktop-preferences.json`：不存在。

### 2.2 别处的损失（和遥应有关的）

- `~/.claude/settings.json` 不存在（`~/.claude` 是 14:40:16 重新建的）。
- `~/.codex/sessions` 是 15:22 重新建的，以前的 Codex 记录都没了。旧对话已经被归档；现在没归档的只有今天新开的两个，记录文件都在：`01a1cea3-012e-7841-a16b-eba09af6abcc`（hello）、`01a1cee1-5979-7021-861f-00c65e76a1cc`（安排领取下载并启动新单）。
- Codex 桌面版 15:45 重开过，还是 26.1021.2667.0。15:49 商店装好了 26.1106.6628.0，要等下次 Codex 重开才换上。电脑端的 Codex 通道是照 26.1021 核对的，换版以后要再核对一次（不在这次范围里，记在第 9 节就行）。
- `C:\Users\39011\AppData\Local\ms-playwright` 整个没了，所以要用浏览器的页面测试跑不起来（见 7.1）。

### 2.3 Codex 那个对话确实有提问卡

用一个只读的小脚本，以单独的 clientType（`agent-remote-probe`）连 `\\.\pipe\codex-ipc`，读 `01a1cee1-…` 的状态：0.14 秒拿到，`available=True`、`questions=1`。所以正在跑的电脑端每次读这个对话的状态，都会走到 `dismiss_manager.latest()`，查那张已经没有的 `desktop_dismiss` 表。

**你不要连真的 Codex 管道**：测试一律用假的快照（见 7.1）。

### 2.4 怎么重演（用临时目录，`AR_DATA_DIR` 指过去）

- **删-1**：在临时目录里建 `new_conversations.NewConversations(None, None, None, None, root=<临时目录>)`，`create_draft()` 正常；删掉它的 `.db` 文件，再 `create_draft()`，抛 `sqlite3.OperationalError: no such table: requests`，库文件变成 0 字节。和现场一模一样。
- **删-2**：建 `codex_control.Bridge()`，再照 `remote.py` 那样挂上 `codex_question_dismiss.DismissManager(bridge)`；对一个有提问卡的对话 `status()` 正常；删掉 `attachments` 里的文件，等 2.5 秒（过了 Bridge 2 秒的快照缓存），再 `status()`，抛 `sqlite3.OperationalError: no such table: desktop_dismiss`。它不是 `ControlError`、`ChatError`、`OSError` 的子类，`/api/codex/state` 接不住。（我做这一步时用的是真的 Codex 管道；你写测试时换成假的快照。）

### 2.5 和这次无关、但日志里看得到的

`20261112.log` 里从 07:57 到 17:44，几乎每条「好了」都写着「中转现在没连着，连上后会补报」。这在误删之前就开始了，是另一个问题（早上另一个 Claude 会话开过任务「中转经常不读这台电脑的通知」）。**不在这次范围里，不要改。**

---

## 3. 逐条原因和代码位置

### 删-1：新建对话

- `new_conversations.py` 第 84–92 行：`NewConversations.__init__` 里建 `requests`、`client_timings` 两张表。
- 第 94–99 行：`_db()` 每次只 `sqlite3.connect`，不建表。文件被删后，`connect` 建出空库。
- 第 134 行 `create_draft()`（INSERT）、第 139 行起 `_read()`（SELECT）、第 148 行 `upload()`、`submit()`：全都抛 `no such table: requests`。
- `remote.py` 第 705–706 行：`/api/chat/new/draft` 没有任何 try；第 702–704 行 `/api/chat/new` 只接 `ChatError, OSError, ValueError, TypeError`；第 978–990 行 `_codex_upload` 只接 `ControlError, ChatError, OSError, ValueError`。`sqlite3.OperationalError` 都接不住。
- 接不住的错：`BaseHTTPRequestHandler` 不回答就关连接 → `relay_agent.py` 第 62–67 行在还没回答时给中转发 `status 502` → 手机看到 502。

### 删-2：Codex 实时连接

- `codex_question_dismiss.py` 第 85–92 行：`DismissManager.__init__` 用 `bridge._db()` 建 `desktop_dismiss` 表，只这一次。
- `codex_control.py` 第 690–700 行：`Bridge._db()` 每次打开只建 `deliveries`。
- `codex_control.py` 第 636–673 行 `status()`：第 646–647 行对每张提问卡调 `self.dismiss_manager.latest(tid, q["id"])`（`codex_question_dismiss.py` 第 107–110 行，SELECT `desktop_dismiss`）；第 671 行只接 `ControlError, ChatError, OSError`。`native_questions()` 会带上答过的提问卡（最近 4 张），所以只要对话里出现过提问卡就会走到这里。
- `remote.py` 第 854–880 行 `_codex_get`：`/api/codex/state` 只接 `ControlError, ChatError, OSError` → 断连接 → 502。
- `live_events.py` 第 84 行起 `stream()`：Codex 每秒调一次 `bridge.status(tid)`；第 128 行 `except Exception: pass` 把错吞掉、直接结束这条流，不留痕迹。
- 手机这边（`apps/ios/TeleplyCore/Sources/TeleplyState/ChatModel.swift` 第 200–245 行）：先读状态，再开实时流；任何一步出错、或者流结束，都显示「连接中断，正在重连」，隔 1、2、4…最多 15 秒再试。所以页面一直在重连。
- Claude、DeepSeek 不会：它们读状态走别的接口，不碰 `desktop_dismiss`。

### 删-3：DeepSeek 发消息

- `deepseek_control.py` 第 343–351 行：`Bridge.__init__` 建 `requests` 表，只这一次；第 352–357 行 `_db()` 不建表。
- 第 567–580 行 `once()`（发消息、新建对话都走它）、第 547 行 `receipt()`：SELECT/INSERT `requests`。
- `remote.py` 第 824–852 行 `_deepseek`：只接 `DeepSeekError, ControlError, ChatError` 和 `ValueError, TypeError, KeyError`。

### 删-4：Claude 的 hook

- `remote.py` 第 1056–1068 行 `hook_settings()`，只在第 1130 行启动时调一次。
- `claude_hooks.py` 第 402 行 `install()`：把 hook 合并写进 `~/.claude/settings.json`。用户 10-27 同意过装这个 hook（见 `claude_hooks.py` 开头的说明）。

### 删-5：配置和设备凭证

- `relay_desktop.py` 第 140–157 行 `initialize()`：没有 `remote_config.json` 时生成新口令、用主机名当电脑名。
- `relay_controller.py` 第 36–37 行：启动时 `relay_vault.load()`（读 `device-v2.bin`），读不到就生成一把没绑定的新钥匙。
- `relay_controller.py` `start_agent()`（约第 201–221 行）会把内存里的配置写回 `remote_config.json`，但只在连中转时做；`device-v2.bin` 只在绑定时写。

---

## 4. 为什么只看日志查不出来

- 当天日志只记「发给…」「通知：…」这类事；接口出错只有少数地方（比如 `_chat_call`）会把 Traceback 写进日志。
- `remote.py` 第 1071 行的 `Server` 没有覆盖 `handle_error`，没接住的错打到 stderr；打包版由 `relay_desktop.py` 第 259–260 行用 `stderr=subprocess.DEVNULL` 启动服务，所以全丢了。

---

## 5. 修法

### 5.1 数据库每次打开都补表（必做）

- `new_conversations.py`：两句 `CREATE TABLE IF NOT EXISTS` 挪进 `_db()`，每次打开都执行（很便宜）。
- `deepseek_control.py`：`requests` 表同样挪进 `_db()`。
- `codex_control.py` 的 `Bridge._db()`：把 `desktop_dismiss` 的建表也放进来。建表语句只留一份，比如在 `codex_question_dismiss.py` 里写一个 `ensure_schema(db)`，`Bridge._db()` 和 `DismissManager.__init__` 都调它。`DismissManager.__init__` 里把 pending/invoking 改成 retained 的那句 UPDATE 是启动时的收尾，留在原处。
- `codex_control.py` 第 675–688 行 `delivery_locations()` 用 `mode=ro` 打开 `delivery.sqlite`：表不在时当成「没有记录」，返回空，不要抛错。
- 全仓库查一遍：凡是我们自己放在 `DATA` 下的 SQLite，建表都要跟着每次打开走；放在 `DATA` 下的 JSON 状态文件（比如 `attachments/computers.json`），读不到就当空的，写之前 `mkdir(parents=True, exist_ok=True)`。查过哪些文件、改了哪些，写进第 9 节。

### 5.2 出了没料到的错，要回答、要记日志（必做）

- `remote.py`：给所有请求加一层兜底（包住 `do_GET`、`do_POST`，或者覆盖 `Server.handle_error`，选一种，说明理由）。任何没接住的错：
  - 把 Traceback 写进当天日志，开头写请求方法和路径；**不写查询参数、请求内容、口令和消息文字**；
  - 还没开始回答时，回 500 和 JSON：`{"error": "电脑端出错（<错误类名>），已记入日志"}`；
  - 已经在流式输出（实时流、下载）时，只关连接。
- `live_events.py` 第 128 行：不要再静悄悄地 `pass`。记一行日志（同一个对话一分钟最多记一次，免得刷屏）再结束这条流。DeepSeek 那段流（第 157、189 行）一样处理。
- `codex_control.py` 的 `status()`：`dismiss_manager.latest()` 出错时当成没有结果（`None`），记一行日志，不要让整个状态读不出来。它只是「电脑上的提问卡有没有自动关掉」的附加信息。
- 手机端不用改：iOS、安卓、网页对非 2xx 都显示错误或者重连，500 带着电脑的错误文字，比 502 更好懂。核对一遍三端对 500 的处理，确认不会被当成「电脑掉线」或者「要重新登录」，写进第 9 节。

### 5.3 数据被删了能自己补回（先问用户，同意了再做）

5.1、5.2 做完、测试过、提交以后，停下来问用户要不要做这一节。它动的是登录和设备凭证，要用户点头。

- Claude hook：除了启动时装一次，之后每 5 分钟检查一次 `~/.claude/settings.json` 里还有没有这条 hook，没有就用 `claude_hooks.install()` 补回。`install()` 本来就是合并写入，不会覆盖用户别的设置；文件不存在时要能新建。用户把 `remote_config.json` 里的 `claude_hooks` 设成 `false` 时不补。
- `remote_config.json`：控制进程和服务进程都有内存里的配置。定时检查（比如每分钟），文件不见了就写回。注意两个进程不要互相覆盖：想清楚由谁负责写，写进第 9 节。
- `device-v2.bin`：控制进程内存里有 `self.binding`。文件不见了就用 `relay_vault.save(self.binding)` 写回（和原来一样用 DPAPI 加密）。这样以后再被删，重启也不用重新绑定。

---

## 6. 边界

- **只改**：`new_conversations.py`、`deepseek_control.py`、`codex_control.py`、`codex_question_dismiss.py`、`live_events.py`、`remote.py`、对应的 `tests/`、本文件第 9 节。用户同意做 5.3 以后，再加 `claude_hooks.py`、`relay_controller.py`、`relay_desktop.py`、`relay_vault.py`。
- **不要碰**：`deploy/site/`、仓库根目录的 `pocketagentdesk.com.png`、`tests/test_activity_records.py`（都是别人的，没提交）；`apps/`（手机端不用改）；`relay_service.py`、`relay_push.py`、`relay_transport.py` 和中转服务器上的任何东西。
- **不要动这台电脑上正在跑的东西**：不重启、不关 `G:\AgentRemote` 的电脑端；不碰 `%LOCALAPPDATA%\AgentRemote\Data`、`~/.codex`、`~/.claude`、`~/.dsh` 里的任何文件；不连 `\\.\pipe\codex-ipc`。
- **删除**：只删你自己在工作区或系统临时目录里建的东西；删之前打印绝对路径；绝不递归删除你自己文件夹以外的路径。PowerShell 里不要用自动变量当变量名（`$home`、`$HOME`、`$pwd`、`$args`、`$input`、`$host`、`$profile`），今天的误删就是这样来的。
- **测试**：`AR_DATA_DIR` 一律指向 `tempfile.mkdtemp()` 建的临时目录。会删文件的测试，删之前先断言要删的路径在这个临时目录里面。

---

## 7. 验证

### 7.1 本地

- 现在的基线（11-12 晚，589e57a 加上工作区里别人的改动）：`.venv\Scripts\python.exe -m unittest discover -s tests` 跑 758 项，730 过、6 跳过、22 出错。22 项里 21 项是这台电脑的 Playwright 浏览器被删了（`C:\Users\39011\AppData\Local\ms-playwright` 不在）；1 项是 `test_mobile_polish` 找「复制命令」按钮，这个按钮 10-24 就改名了，原来就坏。修完以后：这 22 项以外不能有新的失败。浏览器要下载才能装回来，**下载前先问用户**。
- 新测试至少覆盖下面几条，而且要先在旧代码上跑一遍、确认该失败的都失败了：
  1. `NewConversations` 建好以后删掉库文件：`create_draft`、`upload`、`submit` 照常能用。
  2. DeepSeek `Bridge` 建好以后删掉库文件：`once()` 照常能用（假的 client）。
  3. Codex `Bridge` 挂上 `DismissManager` 以后删掉 `delivery.sqlite`：用一个带「答过的提问卡」的假快照调 `status()`，照常返回，`desktop_dismiss` 表被补回来。
  4. `remote.Handler` 里一个接口抛了没料到的错：返回 500 和 JSON，连接没有被直接断开；当天日志里有 Traceback，没有查询参数和口令。
  5. `live_events.stream()` 循环里出错：日志里记了一行。
  6. （做了 5.3 的话）删掉 settings.json 里的 hook、删掉 `remote_config.json`、删掉 `device-v2.bin` 以后，检查一次就都补回来了。

### 7.2 真机（新版装上以后，请用户照做）

1. 新建对话面板，三家各打开一次：没有红字；带一张图新建一个对话，成功。
2. 打开 Codex「安排领取下载并启动新单」：不再出现「连接中断，正在重连」；在电脑上让它再干一轮，手机上能看到实时进度。
3. 给一个 DeepSeek 对话发一句话（带图更好），成功。
4. 电脑上的 Claude 弹出提问卡或权限请求时，手机上能看到并回答。

---

## 8. 发布（每一步都先问用户，上一次同意不算这一次）

- **提交**：可以在 main 上本地提交，一个文件一个文件 `git add`，提交前 `git status` 只看得到你的文件。本文件还没提交，第一次提交时一起提交。**不要 push。**
- **Windows dev.37**：照 `deploy/windows/build.ps1`，在干净的临时工作树（`git worktree add`）里打包，因为仓库目录里有别人没提交的改动。打包、安装、发布各问一次。用完的临时工作树要删掉，删之前打印路径。
- **装新版就会重启电脑端**。因为 `device-v2.bin` 已经没了，重启后会弹出登录窗口：用户要登录，绑定时选原来那台电脑；口令会换新，Claude hook 会重新装上。安装前把这件事告诉用户，由用户决定什么时候装。
- 中转和手机端这次都不用发版。

---

## 9. 结果记录（接手的会话填）

2026-11-12 晚，DeepSeek Harness 会话按 5.1、5.2 节修完，本地提交，没有 push。工作区 `20261112-data-folder-wipe` 里留了两次跑测试的原样输出：`new-tests-on-old-code.log`（新测试在旧代码上）、`full-suite-final.log`（修完跑全部）。

### 9.1 改了哪些文件

- `new_conversations.py`：`requests`、`client_timings` 的建表挪进 `_db()`，每次打开都执行；启动时仍先开一次，把文件建出来。
- `deepseek_control.py`：`requests` 的建表同样挪进 `_db()`；启动时先开一次。
- `codex_question_dismiss.py`：新增 `SCHEMA` 和 `ensure_schema(db)`，建表语句只留这一份；`DismissManager.__init__` 不再自己建表，只保留启动时把 pending/invoking 改成 retained 的 UPDATE。
- `codex_control.py`：
  - `Bridge._db()` 每次打开都调 `codex_question_dismiss.ensure_schema(con)`，`mkdir` 改成 `parents=True`；
  - `status()` 里 `dismiss_manager.latest()` 出错时把 `desktop_dismiss` 当成 `None`，同一对话一分钟最多记一行日志，整个状态照常返回；
  - `delivery_locations()` 以 `mode=ro` 打开时，缺表或文件坏了返回空，不当成错误；
  - `Bridge` 新增 `log` 和 `_log()`（由 `remote.py` 接上当天日志）。
- `live_events.py`：Codex 实时流原来 `except Exception: pass` 改成写一行日志；DeepSeek 流里两处吞掉 `set_subagent_status` 错误的地方同样写。同一个对话一分钟最多一行；对方挂断（`ConnectionError`）不记。
- `remote.py`：
  - 给所有请求加一层兜底：`do_GET`/`do_POST` 只负责调用 `_guarded()`，真正的处理在 `_get()`/`_post()`。没有覆盖 `Server.handle_error`，因为那里拿不到这个请求的响应状态（回答有没有开始、是不是在流式输出），也没法补一个 JSON 500。
  - 没接住的错：把 Traceback 写进当天日志，开头是 `请求方法 路径`（不含查询串、正文、消息文字；口令在文本里出现时替换成 `***`）；还没开始回答就回 500 和 `{"error": "电脑端出错（<错误类名>），已记入日志"}`；已经开始输出（实时流、下载）就只关连接。
  - 用 `end_headers()` 记「这个请求已经回答」，避免 keep-alive 的下一个请求被误当成「已经在流式输出」（写测试时发现的问题）。
  - `load_config()` 把空/写坏的 `remote_config.json` 当成没有；`save_config()` 写之前先建目录；启动时把 `server.codex.log` 接到当天日志。
- 新测试：`tests/test_data_folder_wipe.py`（7 个）。没有改手机端、中转、`deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`。

### 9.2 新测试的名字和结果（对应 7.1）

先在旧代码上跑（6 个，写第 7 个之前），全部 ERROR，确认都能抓到原来的毛病：

1. `test_draft_upload_and_submit_work_after_the_database_is_deleted`（删-1）
2. `test_once_and_receipt_work_after_the_database_is_deleted`（删-3）
3. `test_status_survives_a_deleted_database_and_makes_the_dismiss_table_again`（删-2）
4. `test_an_unexpected_error_is_answered_with_500_and_logged_without_the_query`（5.2）
5. `test_an_error_after_output_starts_closes_the_connection_without_a_second_answer`（5.2，流式）
6. `test_a_stream_that_fails_is_written_down_once_a_minute`（5.2）

第 7 个是补 5.1 的 `delivery_locations` 时加的：`test_delivery_locations_reads_a_wiped_file_as_no_records`。旧写法在 0 字节文件上确实抛 `sqlite3.OperationalError: no such table: deliveries`（用临时目录单独确认过）。

修完 7 个全过。测试里的数据目录一律 `tempfile.mkdtemp()`；会删文件的测试删之前先断言路径在那个临时目录里。

### 9.3 全部测试

`.venv\Scripts\python.exe -m unittest discover -s tests`：**765 项，6 跳过，22 出错，0 失败**。

22 项和基线完全相同，没有新增失败：21 项是 Playwright 浏览器被删（`Executable doesn't exist at C:\Users\39011\AppData\Local\ms-playwright\...`），1 项是 `test_mobile_polish` 找「复制命令」按钮 30 秒超时（那个按钮 10-24 就改名了，原来就坏）。比对过两次完整运行的 ERROR 清单，逐行相同。

### 9.4 5.1 全仓库检查：查过哪些数据文件

- 我们自己放在 DATA 下的 SQLite 只有三个，都已改成每次打开补表：`attachments\new-conversations.sqlite`、`attachments\deepseek-requests.sqlite`、`attachments\delivery.sqlite`（`deliveries` 和 `desktop_dismiss` 两张表）。
- `attachments\computers.json`（`machines.Computers`）、`attachments\phone-files.json`（`pc_files.Files`）、`attachments\claude-catalog.json` 和 `claude-modes.json`（`claude_control`）：读不到已经当成空的、写之前已经建目录，未改。
- `remote_config.json`：`load_config`/`save_config` 改了（见 9.1）。
- `desktop-preferences.json`（`relay_desktop.py`）：读不到当成空的，写之前 `DATA.mkdir`，未改。
- `attachments\<图片编号>\meta.json`：图片自己的记录，读不到就当图片已移除（`ControlError` 404），写之前目录已由上传建好，未改。
- `voice_terms.txt`（`voice_terms.py`）：读不到用默认词典，但 `save_text()` 写之前没有建目录，DATA 目录不在时会失败。它不在这次允许改的文件里，记在这里，没改。
- `relay_accounts.py`、`relay_gateway.py`、`relay_identity.py` 里的 SQLite 是中转服务器自己的（不在电脑端 DATA 下，属于 `relay_service` 一侧），按边界没碰。
- Codex 自己的 `~/.codex/state_*.sqlite` 和对话记录是只读的，不是我们的数据库；按边界没碰。

### 9.5 三端对 500 的处理（核对过，都不用改）

- **iOS**：`Relay.swift` 把非 2xx 变成 `ServiceFailure(status, body)`；`ChatModel.swift` 只有 401 显示「登录失效，请返回账号页重新登录」并停下，403/404 停，其它（含 500）显示「连接中断，正在重连」，按 1、2、4…最多 15 秒重试。新建对话的 500 由 `describe()` 把电脑端 `error` 文字显示出来。
- **安卓**：`RelayApi.kt` 把非 2xx 变成 `ServiceFailure(code, error)`；`Models.kt` 里只有 401（登录）、409 `device_offline` / 503（电脑已离线）有专门文案，500 落到电脑端的 `error` 文字或「请求失败（HTTP 500）」；实时流 `onFailure` 只对 401 清登录，其它重连。
- **网页**：`remote.html` 的 `api()` 对非 2xx 抛出 `Error(j.error || 'HTTP ' + status)`，只有 401 走「登录失效」；`reading-ui.js` 的实时流 `EventSource` 出错后 8 秒重连（DeepSeek 1 秒）。500 不会被当成电脑掉线或要重新登录。

### 9.6 没做

- 5.3（Claude hook、`remote_config.json`、`device-v2.bin` 的自动补回）：等用户决定。
- Windows dev.37 打包、安装、发布：等用户决定。
- 没 push；没动中转服务器、苹果后台、Codemagic、TestFlight、Obsidian。
- 7.2 真机验证：要等新版装上后由用户照做。
- 2.2 节提到的 Codex 26.1106 换版后核对通道：不在这次范围。

### 9.7 提交

- `main` 上本地提交 `（提交编号待填）`：上面 6 个源码文件、`tests/test_data_folder_wipe.py` 和本文件。没有 push。
- 本节的提交编号由紧接着的那一次只改本文件的提交补上。
