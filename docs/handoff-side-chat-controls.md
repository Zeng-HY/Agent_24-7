# 交接：侧边对话里的按钮不算主对话的（停止、排队、运行状态、设置、任务卡片、下一步框）（2026-11-17，第二件）

写给接手的 DeepSeek Harness 会话，由 Claude 监督。这是第一件（`docs/handoff-side-chat-send.md`，提交 `c3d12cb`）的后续：第一件只管发消息，这一件管手机读会话状态和按按钮。你照第 3 节改 `claude_control.py`、补测试、本地提交，在第 9 节记结果。行号按 main 的 `a01a529` 写，可能前后差几行。

---

## 0. 结论

`claude_control.py` 给手机读 Claude 会话的状态、替手机按按钮时，都是**在整页里按名字找按钮**。会话开着侧边对话时，侧边对话的按钮也在这一页里，也被算进去。

最危险的一处：**侧边对话在跑、主对话空闲时**，整页只有一个 `Stop`，是侧边对话的。手机于是显示主对话「正在运行」，并给出「停止这一轮」；用户一按，电脑上唯一能按的 `Stop` 是侧边对话的，**停掉的是侧边对话**。

改法：每处按名字挑出候选按钮以后，用第一件加的 `chats.Desktop._claude_where(ctrl)` 去掉在侧边对话里的和「说不清」的。**只对候选做**，不要对整页每个按钮都往上走。

| 编号 | 地方 | 现在 | 要改成 |
|---|---|---|---|
| 控-1 | `_read_once` 446–453：`running='Stop' in names` | 侧边对话的 Stop 也算主对话在跑 | 只算主对话自己的 Stop；对话记录说在跑的那半（`chats.summary(...)=='running'`）不变 |
| 控-2 | `choose` 883–886：停止 | 按整页唯一可按的 Stop，可能是侧边对话的 | 只按主对话自己的 Stop；没有或不止一个，照旧拒绝 |
| 控-3 | `_queued` 243–263（`Send now`，排队的消息） | 侧边对话排队的消息算成主对话的，手机上「立即补充」会按到侧边对话 | 只算主对话的 |
| 控-4 | `_read_once` 的 Model / Effort / Usage / 模式；`_menu` 545–554、`_dismiss_popup` 405–408 的设置按钮 | 11-17 侧边对话还没有这些按钮；以后有了，就会「不唯一」或者点错 | 只认主对话的 |
| 控-5 | `_waiting_tasks` 219–227、`_task_buttons` 973–982（任务卡片） | 侧边对话提议的任务卡片算成主对话的，手机能替它点 Start | 只算主对话的 |
| 控-6 | `_next_box` 918–938（下一步框） | 侧边对话的下一步框可能被当成主对话的；或者让主对话的框被判成「问的是别的」 | 只看主对话的 |

---

## 1. 证据

- 页面结构见第一件第 1 节，原始记录 `F:\Android-Dev\work\20261101-island-duplicates\20261117-side-chat\uia-side-chat-open.txt`。侧边对话的输入区和主对话的是同一套（class `bg-surface-3 … rounded-composer`），它的 `Send` 就在它自己的输入区里，往上有两层名字叫 "Side chat"。
- 11-17 那次侧边对话是空闲的，没见到它的 `Stop`。按同一套输入区推断：它在跑时，`Stop` 出现在它自己的输入区里，往上同样有那两层 "Side chat"。测试照这个造。
- 11-17 实测：侧边对话里**没有** Model、Effort、Usage、模式（Auto）按钮，也没有 `Add`。控-4 是防以后。
- 11-17 09:46 在真窗口上只读核对过：`_claude_where` 把主对话的框判成「主对话、在 dock 里」，侧边对话的框判成「侧边对话、没有 dock」。
- 整页可见按钮有几十到上百个（侧边栏、标题栏、对话里、输入区），往上走一次 0.015–0.018 秒。手机开着会话时每 5 秒读一次状态，对每个按钮都走一遍要多花一秒多，所以只能对候选走。

---

## 2. 现在的代码（`claude_control.py`，行号按 `a01a529`）

- **209–217 `_buttons(doc, every)`**：整页可见按钮，一次问 Windows（`every` 是那次问的原始结果，含看不见的）。
- **219–227 `_waiting_tasks(every)`**：名字以 `Dismiss suggestion ` 开头的按钮 → 还在等的任务卡片标题。
- **243–263 `_queued(doc, buttons)`**：名为 `Send now`、可用的按钮 → 排队的消息（往上 5 层找 `Message <n>` 读文字）。`send_steer`（1012 起，1026 和 1032 行）和 `choose` 的 `steer_queued`（879–882）都用它。
- **395–420 `_dismiss_popup`**：405–408 行按前缀 `Model: ` / `Effort: ` 在整页找触发按钮，必须正好一个。
- **433–490 `_read_once`**：446 行整页取按钮和名字；447 任务卡片；448–453 Model、Effort、Usage、`running`、模式；459–464 排队的消息和停止的票（`stop_token`，只在 `running` 而且有 `anchor` 时给）；474 行提问区用 `_claude_ask`（第一件已经排除侧边对话，不用再改）。
- **536–560 `_menu`**：545–554 行按 Model / Effort / 模式找触发按钮，必须正好一个、可用。
- **863–917 `choose`**：879–882 排队消息；883–886 停止：`targets=[c for c in self._buttons(doc) if c.Name=='Stop' and self._enabled(c)]`，895 行必须正好一个。
- **918–938 `_next_box`**：整页找名为 `Suggested next actions` 的组；再找名字等于问题的文字。没对上而整页有这种组时返回 `('other',[])`。
- **973–982 `_task_buttons`**：整页找名字等于任务标题的按钮，在它旁边找 Start / Do it here / 关掉。
- 已有测试：`tests/test_claude_control.py`（文件开头有一个假的 `Desktop` 类，只有 `run`）、`tests/test_claude_next_step.py`、`tests/test_claude_send.py` 末尾几个 steer 测试。

---

## 3. 要做成什么样

### 3.1 一个小函数：这个控件是不是主对话的

在 `Controller` 里加一个函数（名字你定，比如 `_own(ctrl)`）：`self.desktop._claude_where(ctrl)` 返回 `None`（说不清）或者在侧边对话里，就**不是**；否则是。**不要求在 dock 里**：任务卡片、下一步框都在对话里，不在 dock 里。

### 3.2 每一处怎么改

都是**先按名字挑出候选，再对候选调 3.1**，别的不变：

1. `_read_once`：`running`、Model、Effort、Usage、模式，只从主对话的按钮里取。`running` 仍然是「主对话自己的 `Stop`」**或者**对话记录说在跑。`stop_token` 的条件不变（`running` 而且有 `anchor`）。
2. `choose` 的停止：只取主对话的、可用的 `Stop`；正好一个才按，否则照旧拒绝（`选项已变化或不唯一，没有执行`）。
3. `_queued`：跳过不是主对话的 `Send now`。
4. 任务卡片：`_waiting_tasks` 只算主对话的 `Dismiss suggestion …`（它现在是 `staticmethod`，怎么改你定）；`_task_buttons` 只认主对话的标题按钮。
5. `_menu`、`_dismiss_popup` 的触发按钮：只认主对话的。`_menu` 里判断「Model 和 Effort 合成一个按钮」（546 行）用的按钮也一样只看主对话的。
6. `_next_box`：只看主对话的 `Suggested next actions` 组和主对话的问题文字；返回 `('other',[])` 的条件也只数主对话的组。

### 3.3 不变的

- `claude_archive.py`：它在整页查 `Stop`、`Send now`、草稿，侧边对话只会让它**多拒绝**，不会做错，这次不动。
- 新建页那几处（693、714、740 行）不动：新建页上没有侧边对话。
- `_context`（Session details 里的 Context 卡片）不动：那一栏只在主对话里。
- 提问区和选项（`_claude_ask`、`_dock_read`）第一件已经改好，不动。
- 手机上的文字一个字不改。

---

## 4. 边界

- **只改**：`claude_control.py`；`tests/` 下的测试（可以新建 `tests/test_claude_side_chat_controls.py`，也可以加在已有文件里）；本文件第 9 节。
- 测试里的假 `Desktop`（`tests/test_claude_control.py` 开头）要补一个 `_claude_where`，默认回「不在侧边对话里、没有 dock」，旧测试就照常过；**断言不改**，非改不可的，先在第 9 节写清为什么。别的测试文件里的假桌面同样处理。
- **不要碰**：`chats.py`（第一件已经做完；要是觉得 `_claude_where` 非改不可，先停下，在第 9 节写清为什么，等 Claude）；`claude_archive.py`；`remote.py`；`relay_*.py`；iOS、安卓、网页；`windows-version.json` 和发版脚本；`docs/` 里别的文件；用户没提交的 `deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`。
- 不碰电脑上的 Claude 窗口（不点、不打字、不切会话、不开关侧边对话，只读查看也不用）。不打包、不安装、不启动或重启遥应。不 push、不 rebase、不 amend。

---

## 5. 验证

### 5.1 先跑基线

`D:\Personal\agent_remote\.venv\Scripts\python.exe -m unittest discover -s tests`，在仓库根目录跑，原样输出存到工作区子文件夹 `20261117-side-chat-controls`。第一件做完后的结果（Claude 跑的，`2131839`）：833 项，1 失败、22 出错、6 跳过，全是旧问题（Playwright 浏览器缺；`test_open_speed` 那 1 条是测试没跟上 11-16 的改动）。改完以后不能多出新的失败或出错。

### 5.2 新测试

先写测试，在旧代码上跑一遍，确认该失败的失败，原样输出存到子文件夹；再改代码。假按钮照第一件的结构造：主对话的在 dock 里，侧边对话的往上有名为 "Side chat" 的 group 和 region；也可以用真的 `chats.Desktop._claude_where` 走假控件。

1. **侧边对话在跑、主对话空闲**（整页只有侧边对话的 `Stop`，对话记录说空闲）→ `_read_once` 的 `running` 是 False，没有 `stop_token`。旧代码：`running` 为 True，给了 `stop_token`。
2. **两个都在跑** → `running` 为 True；`choose` 停止只按主对话的 `Stop`，侧边对话的 `Stop` 一次都没被按。旧代码：两个 Stop，拒绝。
3. **只有侧边对话的 `Stop`，手里有一张停止的票**（比如上一次读的时候主对话还在跑）→ `choose` 拒绝，侧边对话的 `Stop` 没被按。旧代码：按了侧边对话的 `Stop`。
4. 排队：侧边对话的 `Send now` 不在 `queued` 里；`send_steer` 找新排队的消息时也看不到它。
5. 设置：侧边对话里有一个 `Model: …` 按钮时，`_read_once` 的模型取主对话的；`_menu` 找到的触发按钮是主对话那一个。
6. 任务卡片：侧边对话的 `Dismiss suggestion T` 不在 `tasks` 里；`task_step` 只按主对话那张卡片上的按钮。
7. 下一步框：侧边对话里的 `Suggested next actions` 组不算；主对话的照常找到。只有侧边对话有这种组时，返回「不在」（`None`），不是 `('other',[])`。
8. 说不清（`_claude_where` 回 `None`）的候选：不算、不按。
9. **只对候选往上走**：整页有 50 个无关的按钮和几个候选时，`_read_once` 调 `_claude_where` 的次数只等于候选数。

### 5.3 全部测试

5.1 的命令再跑一遍，和基线逐行比对失败和出错的清单，写进第 9 节。

### 5.4 这台电脑上你做不了的

侧边对话真在跑的时候从手机看状态、按停止：要打包、安装新版遥应，由 Claude 问过用户再做。

---

## 6. 发布（不是你的事）

本地提交以后停下。不打包、不改版本号、不 push、不发版。

---

## 9. 结果记录（接手的会话填）

### 9.1 改了哪些文件、各改了什么

**`claude_control.py`**

- 新增 `Controller._own(ctrl)`：`desktop._claude_where(ctrl)` 回 `None`（说不清）或者在侧边对话里 → 不是主对话的；否则是。**不要求在 dock 里**（任务卡片、下一步框都在对话里，不在 dock 里）。`_claude_where` 出任何错也当「不是」。
- 新增 `Controller._candidate(ctrl)`：名字是 `Stop`、`Model: …`、`Effort: …`、`Usage: …`、`Permissions: …` 或模式按钮之一（`MODE_BUTTONS`）的按钮才是候选。只有候选才调 `_own`：整页几十个按钮，每 5 秒读一次，每个都往上走要多花一秒多。
- `_read_once`：`names` 只取候选里主对话自己的按钮，所以 `running`（`Stop`）、Model、Effort、Usage、模式都只来自主对话；`result['tasks']` 传 `self._own`。`running` 仍然是「主对话自己的 `Stop`」或者「对话记录说在跑」，`stop_token` 的条件（`running` 而且有 `anchor`）没变。
- `_queued`：`Send now` 先看名字、再看是不是主对话的，不是就跳过（不往上找 `Message <n>`，所以说不清的那个也不会抛 COMError）。`send_steer` 和 `choose` 的排队消息都走它。
- `_dismiss_popup`：按 `Model: ` / `Effort: ` 找的触发按钮只认主对话的。
- `_menu`：按钮列表只留候选里主对话的；`Model` / `Effort` 合成一个按钮的判断、以及 6 秒重试时重新取按钮，也用它、也过滤。
- `choose` 的停止：只取主对话的、可用的 `Stop`，正好一个才按，否则照旧抛 `选项已变化或不唯一，没有执行`。
- `_waiting_tasks`：加了可选的 `own` 参数（默认 `None`，直接调用的老测试照旧），只算主对话的 `Dismiss suggestion …`；`_read_once` 传 `self._own`。
- `_task_buttons`：标题按钮、以及卡片上的 Start / Do it here / 关掉，都只认主对话的。
- `_next_box`：`Suggested next actions` 组、问题文字、以及「有没有别的框」的判断（`('other',[])` 还是 `None`）都只数主对话的；只有侧边对话有这种组时返回 `None`。
- 没碰：`chats.py`、`claude_archive.py`、`remote.py`、`relay_*.py`、新建页那几处、`_context`、提问区和选项；手机上的文字一个字没改。

**`tests/test_claude_side_chat_controls.py`（新建，18 个测试）**：假的页面照 `uia-side-chat-open.txt` 搭（composer → dock，或者 composer → 两层 "Side chat" → 网页，按钮和卡片挂在这些层下面）；假的 `Desktop` 把 `_claude_where` 接到真的 `chats.Desktop._claude_where` 上走假页面，还记下每个被往上走的控件。

**`tests/test_claude_control.py`**：文件开头的假 `Desktop` 补一个 `_claude_where`（默认回「不在侧边对话、没有 dock」）。断言没改。

**`tests/test_claude_next_step.py`**：里面那个假 `Desktop` 同样补 `_claude_where`。断言没改（`Controller._waiting_tasks([…])` 还是可以只传一个参数）。

### 9.2 新测试的名字，和在旧代码上的结果

18 个，全在 `tests/test_claude_side_chat_controls.py`。旧代码按 HEAD（`1de1180`，代码同 `a01a529`）取出来的 `claude_control.py` 当模块跑，原样输出在工作区 `new-tests-on-old-code.log`：**16 个失败或出错，2 个本来就能过**（防回退用的）。

| 测试 | 旧代码 | 对应 |
|---|---|---|
| `test_a_side_chat_that_runs_does_not_make_the_session_look_busy` | `running` 为 True，还给了 `stop_token` | 控-1 |
| `test_the_records_running_state_is_unchanged` | 通过（记录说在跑还是算在跑） | 3.2.1 |
| `test_two_stops_press_the_sessions_own` | 两个 Stop，拒绝 | 控-2 |
| `test_a_stop_only_in_the_side_chat_is_not_pressed` | 按了侧边对话的 Stop | 控-2 |
| `test_a_stop_whose_place_cannot_be_told_is_not_pressed` | 当成主对话在跑 | 3.1 |
| `test_a_side_chats_queued_message_is_not_the_sessions` | 算成主对话排队的 | 控-3 |
| `test_a_queued_message_whose_place_cannot_be_told_is_not_the_sessions` | 读它的父元素时抛 COMError | 3.1 |
| `test_the_sessions_model_is_read_from_its_own_button` | 取了侧边对话的模型 | 控-4 |
| `test_the_sessions_mode_comes_from_its_own_button` | 取了侧边对话的模式 | 控-4 |
| `test_the_menus_trigger_is_the_sessions_own` | 两个触发按钮，拒绝 | 控-4 |
| `test_the_popups_trigger_is_the_sessions_own` | 两个触发按钮，没收起主对话那个 | 控-4 |
| `test_a_side_chats_task_card_is_not_offered` | 两张同名卡片，拒绝 | 控-5 |
| `test_only_the_side_chat_has_the_card` | 通过（没有卡片，拒绝） | 控-5 |
| `test_the_sessions_own_next_step_box_is_used` | 先取到侧边对话那个框 | 控-6 |
| `test_a_box_in_the_side_chat_is_never_taken_for_the_sessions` | 把侧边对话的框当成主对话的 | 控-6 |
| `test_only_the_side_chat_has_a_next_step_box` | 返回侧边对话的框 | 控-6 |
| `test_a_plain_list_in_the_side_chat_is_not_the_sessions` | 把侧边对话的列表当主对话的 | 控-6 |
| `test_only_candidates_are_walked_up` | 一次都没调 `_claude_where`（新代码正好走 4 个候选） | 性能 |

### 9.3 全部测试（和基线比）

- 基线：交接文档里的 `2131839` 基线日志不在工作区，所以在一个临时 worktree 里按 HEAD（`1de1180`）跑了一遍，跑完把 worktree 删掉了。`Ran 834 tests`，`FAILED (failures=1, errors=22, skipped=6)`，原样输出在工作区 `baseline-1de1180.log`。
  - 工作区里的 `tests/test_activity_records.py` 是用户没提交的改动（少一个测试），所以工作区跑出来是 833 项，和文档说的 Claude 那次 833 一致；834 是 HEAD 上没这个改动的数。
- 改后：`Ran 851 tests`，`FAILED (failures=1, errors=22, skipped=6)`，原样输出在工作区 `after-deepseek-change.log`。
- 逐行比对失败/出错清单（各 23 条）：**完全一样**，没有新的失败或出错。多的 18 项就是新测试，全部通过；`tests/test_claude_control.py`、`tests/test_claude_next_step.py` 里改过和没改过的也都通过。
- 旧坏项照旧、和这次无关：Playwright 浏览器缺（那些 webkit/chromium 的 ERROR）、`test_open_speed` 那 1 条 FAIL。

### 9.4 没做的、拿不准的

- 没在真窗口上验证：没点、没切 Claude 窗口、没开侧边对话。侧边对话「在跑时的 `Stop`」是照它输入区的结构推的（11-17 那天它是空闲的，没见到）；Claude 审的时候可以开着侧边对话只读核对一次。
- 没打包、没安装、没启动或重启遥应，没 push、没 rebase、没 amend，没动版本号。
- 手机上的文字一个字没改；`claude_archive.py` 没动（它只会多拒绝，不会做错）。
- 每 5 秒读一次状态会多走几次（每次往上 0.015–0.018 秒）：一般 2–6 个候选（`Stop`、`Model: `、`Effort: `、`Usage: `、模式、`Dismiss suggestion …`、`Send now`），按这个数算最多一百毫秒上下；`test_only_candidates_are_walked_up` 卡住了「只走候选」这件事。真窗口上这笔开销没有实测。
- 拿不准：以后侧边对话如果也有了 Model / Effort 按钮，`_menu` 里「Model 和 Effort 合成一个按钮」的判断现在只看过滤后（主对话）的按钮列表，按逻辑不会把侧边对话的算进来；但没有那样的窗口可以实测。
- 基线是用临时 worktree 跑的（跑完删了），因为交接文档说的工作区基线日志没有出现；如果 Claude 那边有 `2131839` 的原始日志，可以拿来再对一次。

