# 交接：Claude 会话开着侧边对话时，手机消息要发进主对话自己的输入框（2026-11-17）

写给接手的 DeepSeek Harness 会话，由 Claude 监督。原因和界面结构已经查清：你照第 3 节改 `chats.py`、补测试、本地提交，在第 9 节记结果。行号按 main 的 `0e90118` 写，可能前后差几行。

---

## 0. 结论

11-17 07:26:07 和 07:26:24，手机给 Claude 会话「Source First 工作流顶层设计优化」（`local_5db34450-a774-4577-91a7-186d39317c1e`）发的两条消息都被电脑端拒绝：「Claude 输入框不唯一或尚未就绪，尚未发送」（当天日志 `%LOCALAPPDATA%\AgentRemote\Data\logs\20261117.log`）。

原因：这个会话开着 Claude 新加的**侧边对话**（Side chat，用 `/btw` 开的子会话 `local_1dbd4d2a-fc4d-438b-8ebc-1f383dd5db9f`，标题 "Side chat"）。侧边对话在会话右边占一栏，有自己的输入框和 Send 按钮，名字也叫 `Prompt`、`Send`。`chats.py` 的 `_claude_verified_prompt` 要求整页只有一个 `Prompt` 框，所以拒绝。用户看到框里的灰字（Claude 建议的下一句）不是原因：框里读到 0 个字，第一行标着 `is-editor-empty`。

现在的代码还有比「拒绝」更糟的情况，这次一起改掉：

- 主对话的输入框被提问卡片顶掉时（Claude 问问题会这样），页面上只剩侧边对话一个框，现在的代码会把手机消息**写进侧边对话**。
- 主对话的 Send 还没亮、侧边对话里有草稿时，整页只有侧边对话的 Send 能按，现在的代码会**按下它**，把侧边对话的草稿发出去。
- 侧边对话里出现提问卡片时，`_claude_ask` 取最新一张，可能把它当成主对话的提问，手机上点选项就点到侧边对话里。

改法：认出侧边对话里的东西，凡是找输入框、Send、提问区的地方都把它们排除；排除以后还是分不清，照旧拒绝。

| 编号 | 现在 | 要改成 |
|---|---|---|
| 侧-1 | 开着侧边对话就拒绝（找到两个框） | 写进主对话自己的框，按主对话自己的 Send |
| 侧-2 | 主对话没有框、只剩侧边对话的框时，写进侧边对话 | 拒绝，手机上的提示照旧 |
| 侧-3 | Send 在整页找，可能按到侧边对话的 Send | 只在主对话框所在的 dock 里找 |
| 侧-4 | `_claude_dock`、`_claude_ask` 不分侧边对话 | 跳过侧边对话里的框、dock 和提问卡片 |
| 侧-5 | 拒绝时日志只有一句话 | 日志加上看到几个框、几个在侧边对话里（手机上的文字不变） |

---

## 1. 证据：Claude 窗口里的结构

11-17 09:00 用 UI Automation 只读查看，Claude 桌面版 5.11492.5.0（`C:\Program Files\WindowsApps\Claude_5.11492.5.0_x64__pzs8sxrjxfjjc`）。会话占左边一栏，侧边对话占右边一栏，中间一条分隔条叫 "Resize Chat and Side chat"。两栏在**同一个网页**里（同一个 `DocumentControl`，网址是父会话的 `https://claude.ai/epitaxy/local_5db34450-…`），所以网页身份核对分不出它们。

主对话的框往上（只列有用的几层）：

```
EditControl  "Prompt"  class "tiptap ProseMirror"                 (364,967)-(943,989)
 第 5 层  Group  class "bg-surface-3 … rounded-composer …"         输入区
 第 6 层  Group  class "group/approval-dock pointer-events-auto …" dock（_claude_dock 现在找的就是它）
 第 10 层 Group  class "relative isolate min-w-0 epitaxy-chat-panel"
 第 13 层 Group  class "tiles-slot"                                 x 288–1375
 第 19 层 Group  名字 "Primary pane"
 第 26 层 Document  名字 "Source First 工作流顶层设计优化 - Claude Code"
```

侧边对话的框往上：

```
EditControl  "Prompt"  class "tiptap ProseMirror"                 (1398,991)-(1868,1013)
 第 5 层  Group  class "bg-surface-3 … rounded-composer …"         它自己的输入区，它的 Send 在这里面
 第 6 层  Group  名字 "Side chat"   class "flex h-full min-h-0 flex-col"
 第 7 层  Group  名字 "Side chat"   ARIA 角色 region（地标）
 第 9 层  Group  class "tiles-slot"                                 x 1376–1920
 第 15 层 Group  名字 "Primary pane"
 第 22 层 Document（同一个网页）
```

侧边对话那一栏还有工具条 "Side chat controls"、标签条 "Side chat tabs"（每个侧边对话一个标签）、按钮 "New side chat"。它的输入区**不在** `group/approval-dock` 里，也不在 `epitaxy-chat-panel` 里，也没有 `Add` 按钮。它的框空着时，它的 Send 是灰的（`IsEnabled` 为 False），所以 07:26 那次只是「两个框」被拒，Send 还没轮到。

分辨的办法（两样都实测过；从框往上走到网页 21–25 层，只用 0.015–0.018 秒）：

- **侧边对话里的东西**：往上有一层的名字是 "Side chat"（group 和 region 两层都是）。
- **主对话的框**：往上有一层的 class 里有 `group/approval-dock` 这个词（也在 `epitaxy-chat-panel` 里）。

原始记录在工作区：`F:\Android-Dev\work\20261101-island-duplicates\20261117-side-chat\uia-side-chat-open.txt`（开着侧边对话），`uia-side-chat-closed.txt`（另一个会话，没开侧边对话，只有一个框）。

Claude 自己的记录也说明它是侧边对话（这次的修改用不到）：会话索引里 `title` 是 "Side chat"，`forkedFromSessionId` 是父会话，`spawnedFrom` 里有 `sideSession: true`、`btw: true`；Claude 日志 11-16 16:16:13 有一行 `LocalSessions.startBtwChild: parentSessionId=local_5db34450-…`。

---

## 2. 现在的代码（`chats.py`，行号按 `0e90118`）

- **1639–1644 `_claude_verified_prompt(root, conv_id)`**：先核对网页是这个会话（`_claude_document`），再在整页找名为 `Prompt`、在屏幕上、可用的 `EditControl`，必须正好一个，否则 `InputNotSubmitted('Claude 输入框不唯一或尚未就绪，尚未发送')`。读写输入框的地方都经过它：
  - `_fill_claude_prompt`（1693–1737）：读草稿、写入、每 0.1 秒读回一次；
  - `_claude_wait_prompt`（1944–1956）：切到会话后最多等 8 秒；
  - `_paste_claude_image`（2119–2171）：图片，先 `SetFocus` 到这个框再按 Ctrl+V；
  - `_send_claude_now`（2214、2219）：按 Send 前再核一次；
  - 新建会话：`_claude_new_buttons`（2282–2286）、`exact_folder`（2332）、`_new_claude_now`（2415 写入、2420 核对）；
  - `claude_control.py` 393 行 `_new_page`。
- **2216–2217 `_send_claude_now` 的 Send**：整页找名为 `Send`、在屏幕上、可用的按钮，必须正好一个。
- **2422–2423 `_new_claude_now` 的 Send**：同上。
- **1958–1972 `_claude_dock(root)`**：整个窗口找 `Prompt` 框，从每个框往上 12 层找 class 含 `approval-dock` 的；都没找到就整窗口搜 `approval-dock`。
- **1974–1986 `_claude_ask(root, doc=None)`**：在 `doc`（没给就整个窗口）里按 class 找提问卡片 `epitaxy-approval-card`，从最新的往回，取第一张还有可按按钮的；没有就用 `_claude_dock`。`claude_options`（2446、2454）、`claude_press`（2501）和 `claude_control.py` 281、474 行都靠它。
- **2088–2117 `_claude_image_count(edit)`**：从框往上找第一个含 `Add` 按钮的部分来数附件。侧边对话在另一棵子树里，也没有 `Add`，这个函数不用改。
- **2055–2057 `send()`**：发送失败时写日志 `没发给 Claude「…」（… 秒）：<错误文字>`。
- **1612–1630 `_find`、1632–1637 `_find_class`**：一次问 Windows 拿到全部结果。新代码也用它们，不要逐个元素遍历整页（整页遍历要 0.7 秒）。
- 已有测试：`tests/test_claude_send.py`（`test_message_box_comes_from_one_query_and_must_be_the_only_one` 27–33 行、`test_question_area_is_found_by_going_up_from_the_message_box` 379–389 行、`test_a_question_card_among_the_messages_is_where_claude_asks` 390–412 行等），`tests/test_claude_new_environment.py`，`tests/test_claude_control.py`。

---

## 3. 要做成什么样

### 3.1 新函数：一个控件在页面的哪儿

在 `Desktop` 里加一个函数（名字你定，比如 `_claude_where(ctrl)`）。从控件往上一层层取父元素（`GetParentControl()`），走到网页（`ControlTypeName == 'DocumentControl'`）或窗口（`'WindowControl'`）或 `None` 为止，最多 40 层。**网页这一层本身不看**：会话可以就叫 "Side chat"，网页的名字是「<标题> - Claude Code」。它告诉调用的地方两件事：

- **在不在侧边对话里**：路上任何一层的名字（`Name`）去掉首尾空白后，不分大小写以 `side chat` 开头。
- **最近的 dock**：路上第一个 class 里有**独立的词** `group/approval-dock` 的那一层（按空白拆开比较，和 `question_card()` 一样；不要用「包含」，子元素的 class 里可能有带 `/approval-dock` 的变体）。没有就是空。

往上走时出任何错（Claude 正好重画时的 `COMError`，或者别的异常），返回「说不清」（比如 `None`）。调用的地方把「说不清」一律当成**不是**主对话的东西。

侧边对话的名字写成常量，放在文件开头那些 Claude 常量旁边，注释写明来历（11-17，Claude 5.11492.5.0，侧边对话的 region 和 group 都叫 "Side chat"）。

### 3.2 输入框：`_claude_verified_prompt`

一个框算这个会话自己的，要同时满足：

1. 在屏幕上、可用（和现在一样）；
2. 不在侧边对话里，也不是「说不清」；
3. 已有会话（`conv_id != '__new__'`）还要在 dock 里。新建页（`'__new__'`）不要求 dock：这一版新建页的结构没实测过。

满足的正好一个就返回它；一个也没有或者不止一个，照旧拒绝。**手机上看到的文字一个字都不改**：`Claude 输入框不唯一或尚未就绪，尚未发送`。返回值的样子不变（`(doc, edit)`），别的地方不用跟着改。

拒绝时让当天日志多一点信息，手机上的文字不变：屏幕上可用的 `Prompt` 框有几个，其中几个在侧边对话里、几个不在 dock 里、几个说不清。做法你定，比如给异常加一个 `detail` 属性，`send()` 那句「没发给 …」把它接在后面。注意 `_claude_verified_prompt` 在读回时每 0.1 秒调一次，**不要在它里面直接写日志**，会刷屏。

### 3.3 Send 按钮：`_send_claude_now` 和 `_new_claude_now`

两处写成一个小函数共用（名字你定）：

- **已有会话**：从核对过的框重新算出它的 dock，只在这个 dock 里找 `Send`（`self._find(dock, 'ButtonControl', 'Send')`），再去掉在侧边对话里的和说不清的。在屏幕上、可用的必须正好一个，否则照旧 `没有唯一可用的 Claude 发送按钮，尚未发送`。
- **新建页**：和现在一样在整页找，但去掉在侧边对话里的和说不清的。必须正好一个，否则照旧 `Claude 新对话发送按钮尚未就绪`。

### 3.4 提问区：`_claude_dock` 和 `_claude_ask`

- `_claude_dock(root)`：跳过侧边对话里的框和说不清的框，返回主对话框的 dock（用 3.1 的结果）。整窗口兜底搜 dock 时，也跳过在侧边对话里的 dock。
- `_claude_ask(root, doc)`：跳过在侧边对话里的提问卡片和说不清的卡片。

### 3.5 图片

`_paste_claude_image` 先 `SetFocus` 的框来自 `_claude_verified_prompt`，3.2 改好就对了；`_claude_image_count` 不改。在第 9 节写清你是怎么核对这两处的。能不碰真剪贴板就写出测试的话，加一个测试：开着侧边对话时，粘贴图片前拿到焦点的是主对话的框。

### 3.6 不变的

- 网页身份核对（`_claude_document`）、草稿保护、读回核对、`input_lock`、不抢键盘的做法，全都不变。
- 侧边对话**从来不写、不按**：不往它的框里写字，不按它的 Send、Stop 和任何选项。
- 分不清时照旧拒绝。**不要按位置（左边、右边、宽窄）挑框**，位置不能用。

---

## 4. 边界

- **只改**：`chats.py`；`tests/` 下的测试（可以新建 `tests/test_claude_side_chat.py`，也可以加在 `tests/test_claude_send.py` 里）；本文件第 9 节。已有测试里的假控件，可能要补上 dock 和网页那几层才能过；**断言不改**，非改不可的，先在第 9 节写清为什么。已知有一处要跟着改：`test_claude_send_has_no_ctrl_a_clipboard_or_enter` 断言 Send 是在整页（`'doc'`）里找的，改完以后是在 dock 里找，这正是侧-3。
- **不要碰**：
  - `claude_control.py`、`claude_archive.py`：它们按整页读 Stop、Send now、Model 等按钮，侧边对话的按钮也会混进来，这是另一件事，Claude 之后另做。它们调用的 `_claude_ask`、`_claude_verified_prompt` 改了以后自然跟着对。
  - `remote.py`；`relay_*.py`（另一个 DeepSeek 会话正在改 `relay_agent.py`、`relay_controller.py`、`relay_desktop.py`）；iOS、安卓、网页（`remote.html`、`static/`）；`windows-version.json` 和发版脚本；`docs/` 里别的文件。
  - 用户没提交的 `deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`。
- **不碰电脑上的 Claude 窗口**：不点、不打字、不切会话、不开关侧边对话。只读的 UI Automation 查看也不用做，第 1 节已经给了结构。
- 不打包、不安装，不启动或重启遥应（`G:\AgentRemote`）。
- 不 push、不 rebase、不 amend。main 上有别的会话还没推送的提交，原样留着。

---

## 5. 验证

### 5.1 先跑基线

`D:\Personal\agent_remote\.venv\Scripts\python.exe -m unittest discover -s tests`，在仓库根目录跑。改之前跑一遍，原样输出存到工作区子文件夹 `20261117-side-chat`。以前就坏的（和这次无关）：Playwright 浏览器被删（约 21 项出错，`C:\Users\39011\AppData\Local\ms-playwright` 不在），`test_mobile_polish` 找「复制命令」按钮（1 项）。Claude 11-17 上午在 `0e90118`（加上工作区里别人没提交的改动）也跑了一遍，原样输出在子文件夹的 `baseline-claude-0e90118.log`。改完以后不能多出新的失败或出错。

### 5.2 新测试

先写测试，在旧代码上跑一遍，确认该失败的失败，原样输出存到子文件夹；再改代码。假控件照第 1 节的结构造：每层有 `Name`、`ClassName`、`ControlTypeName`、`GetParentControl`，框和按钮还有 `IsOffscreen`、`IsEnabled`。可以写一个小函数，按「从下到上」的列表搭出一串父元素，最上面是名为「<标题> - Claude Code」的 `DocumentControl`。

1. **11-17 那次**：主对话的框（在 dock 里）和侧边对话的框（往上有名为 "Side chat" 的 group 和 region）都在 → 返回主对话的框。旧代码：拒绝。
2. **主对话的框不在**（被提问卡片顶掉），只剩侧边对话的框 → 拒绝。旧代码：返回侧边对话的框，这正是要修的危险。
3. 两个框都在 dock 里、都不在侧边对话里（比如以后的分屏）→ 拒绝。
4. 侧边对话的框以后也有了 dock（往上既有 dock 又有 "Side chat"）→ 不算。
5. 往上走到一半出错（`GetParentControl` 抛 `COMError(chats.ELEMENT_GONE, …)`）→ 这个框不算。
6. 会话标题就叫 "Side chat"：网页名字 "Side chat - Claude Code"，框在 dock 里 → 算（网页本身的名字不看）。
7. 新建页（`'__new__'`）：没有 dock 的框 → 算；再加一个侧边对话的框 → 还是返回新建页的框。
8. **发送**：dock 里的 Send 和侧边对话的 Send 都可用 → 按 dock 里的。dock 里没有可用的 Send、只有侧边对话的 Send 可用 → 拒绝，侧边对话的 Send 的 `Invoke` 一次都没被调用。旧代码：按了侧边对话的 Send。
9. 新建页发送：侧边对话的 Send 不算。
10. `_claude_dock`：侧边对话的框排在前面时，返回主对话的 dock；兜底搜索不返回侧边对话里的 dock。
11. `_claude_ask`：最新的提问卡片在侧边对话里、较早的一张在主对话里 → 返回主对话那张；只有侧边对话里有卡片 → 用 dock。
12. **日志**：拒绝时日志那一行有框的个数（3.2）；手机拿到的错误文字和现在逐字相同。

### 5.3 全部测试

5.1 的命令再跑一遍，和基线逐行比对失败和出错的清单，写进第 9 节。

### 5.4 这台电脑上你做不了的

真的开着侧边对话从手机发一条：要打包、安装新版遥应，由 Claude 问过用户再做。Claude 审你的提交时，会先在开着侧边对话的窗口上只读核对新代码挑中的是不是主对话的框。

---

## 6. 发布（不是你的事）

本地提交以后停下。不打包、不改版本号、不 push、不发版。Claude 审完再问用户要不要出 Windows 新版。

---

## 9. 结果记录（接手的会话填）

### 9.1 改了哪些文件、各改了什么

### 9.2 新测试的名字，和在旧代码上的结果

### 9.3 全部测试（和基线比）

### 9.4 没做的、拿不准的
