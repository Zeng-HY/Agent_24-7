# 交接：锁屏岛卡在「工作中」、消息显示两次、「正在压缩上下文」不消失（2026-11-01）

写给接手修复的 DeepSeek Harness 会话。原因已经查清，证据和代码位置都在下面；你要做的是照第 4 节改、补测试、在第 9 节记结果。代码位置按 main 的 3ef2010 写，行号可能前后差几行。

---

## 0. 结论

用户 11-01 早上在 iPhone（遥应 0.7.0，构建 25）上报了三个问题，一共查出八处毛病：

| 编号 | 用户看到的 | 原因（一句话） | 改哪边 |
|---|---|---|---|
| 岛-1 | 两个早就做完的对话，锁屏岛上还写「2 个对话工作中」 | 中转读电脑事件的那条连接昨晚 23:17–23:22 断了，至少到 00:11 还没连回来；两个对话 23:28 的「做完了」一直留在电脑上等补报 | 中转（查原因 + 重连更快） |
| 岛-2 | 同上，而且岛一直不变灰 | 中转听不到电脑的时候，照样每 10 分钟把岛上的旧内容再推一遍，所以岛永远不显示「可能不是最新」，也不会收起 | 中转 |
| 岛-3 | 同上 | 连回来以后也补不全：中转重启后只要最近 10 分钟的事件；电脑重连时只发一次空快照，而中转要连续两次快照里都没有，才认为那个对话停了 | 中转 + 电脑 |
| 岛-4 | 计时显示 8:48:54、8:52:17，一动不动 | iOS 的实时活动最长 8 小时，到点系统自己收掉，锁屏上留着最后一刻的画面最多 4 小时；中转不管这个上限 | 中转 |
| 两-1 | 这个 Claude 对话里，10-28 到 10-30 的旧对话又出现了一遍 | /compact 之后，Claude 桌面版把 1226 条旧记录原样又写进文件（每条的 uuid 都和前面重复）；电脑没去重，当成新消息 | 电脑 |
| 两-2 | 带图片的消息，实心气泡出来了，下面还留着一个淡色的同样内容，标「已送达」 | 这台电脑的时钟慢了 13 秒。手机判断「记录里有这条了」时，要求记录时间不早于手机发出时间 5 秒以上；带图片的消息 2–3 秒就进了记录，按电脑的钟算反而「早」了约 10 秒，永远对不上 | 手机 + 电脑 |
| 压-1 | 「/compact」显示两行；聊别的时显示「正在压缩上下文」 | 电脑自己记着一份 Claude 的排队清单。10-31 22:05 有条别的会话发来的消息，排队时带 `hop-chain="…"`，撤下时不带，清单删不掉它，从那以后每次取出都错一位。今早 08:02 的 /compact 留在清单里，08:06:59 发图片消息时被当成「刚取出来的 /compact」 | 电脑 |
| 压-2 | 「正在压缩上下文」一直挂到下一个工具步骤（08:12 才变成「正在跑命令」） | 电脑逐行读记录、合并状态时跳过空值，所以「压缩完了」「新一轮开始了」这种把步骤清空的行不起作用 | 电脑 |

时间都是北京时间，除非写了 Z（世界时）。

---

## 1. 用户看到的现象

1. **08:01 锁屏**：岛写「2 个对话工作中」，列两个对话：Codex「今天开始了好几个语言桥项目，除…」查资料 8:48:54；DeepSeek「你接手遥应（Teleply）网站 pocke」跑命令 8:52:17。两个对话昨晚 23:28 左右就做完了。
2. **08:07 Claude 对话「灵动岛创意玩法」**：「对话已压缩」下面有两行「/compact」；刚发的带图消息出现了实心的一条，下面又有一条淡色的同样文字，标「已送达」。「对话已压缩」上面紧挨着的是 10-30 的旧回复（「运行中」不准的原因是 iPhone 回到前台后要等 10 秒…）。
3. **08:09**：思考行写「正在压缩上下文 · 40 秒」，其实没在压缩。淡色气泡变成两条。
4. **08:12**：Claude 已经在跑命令，最底下还留着三条淡色气泡，三条都是带图片的消息；中间那条没带图的（「探测好了问题…」）正常消失了。

---

## 2. 证据，怎么复现

### 2.1 文件在哪（都只读，不要改、不要删）

- 电脑服务的日志：`%LOCALAPPDATA%\AgentRemote\Data\logs\20261031.log`、`20261101.log`。
- Codex 那个对话：`C:\Users\39011\.codex\sessions\2026\10\31\rollout-2026-10-31T00-11-39-01a18d94-c34b-7e00-9955-b028fa498980.jsonl`，最后一行是 `task_complete`，时间 `2026-10-31T15:28:36Z`（23:28:36）。
- DeepSeek 那个对话：`session-8a70c5aa-14ec-457b-af7e-89381c86673f`，现在是空闲，阶段一报告早就交了（`dsh.py show` 能看）。
- Claude 对话记录：`C:\Users\39011\.claude\projects\D--Personal-agent-remote\c372939b-b2bb-4686-9a25-becf4887f24a.jsonl`。**这是正在进行的对话，文件一直在变长。只读；要用就先复制一份到你的工作区。里面是用户的真实对话，不要把任何内容贴进仓库，测试一律用自己编的行。**
- 装在这台电脑上的是 Windows dev.32（`G:\AgentRemote`，本机 8765 端口），代码和 main 的 `chats.py`、`chat_history.py`、`notify.py` 一致。

### 2.2 岛：电脑日志

`20261031.log` 里 22:00 以后：

- 23:16:10 是最后一条「遥应通知已交给中转」。
- 23:22:13 Codex（语言桥）「好了，中转现在没连着，连上后会补报」。
- 23:28:08 DeepSeek（网站）「好了，中转现在没连着，连上后会补报」。
- 23:28:40 Codex（语言桥）同上。
- `20261101.log` 00:11:31 另一个 Codex 对话「好了」，仍然「中转现在没连着」。之后到 08:00 没有别的通知行。

这句话来自 `notify.py` 第 810 行：`self.relay.listening` 为 0，意思是中转那时没在读这台电脑的事件流（`/api/notify/push`）。这种断开很常见：10-30 的日志里出现 11 次，10-31 出现 24 次；平时几分钟内就连回来，这次至少 50 分钟。

锁屏上的计时：08:01 时 8:52:17 和 8:48:54，倒推出两个对话的这一轮在 23:09 和 23:12 开始，岛大约 23:10 从中转远程开启，到 07:10 左右满 8 小时。

### 2.3 消息两次、压缩状态：照电脑的读法逐行重放

电脑读 Claude 记录的方式是 `chat_history.Transcript.refresh()`：从头逐行调用 `chats._parse('claude', [一行], context)`，状态只在值不为空时合并（第 41–44 行）。在你的工作区写个脚本照做一遍，就能看到下面这些（行号按 `bytes.splitlines()` 数）：

```
5612  10-31T14:05:45Z enqueue  '<cross-session-message … hop-chain="4f0e…" from-name=…'   （928 字）
5615  10-31T14:08:45Z remove   '<cross-session-message … from-name=…'                      （891 字，少了 hop-chain）
      → 清单里这条删不掉，此后每次 dequeue 都取到上一条
6511  11-01T00:02:46.227Z enqueue '/compact'          清单：['<pasted_content…', '/compact']
6512  11-01T00:02:46.229Z dequeue                     取出 '<pasted_content…'，/compact 留下
6513–7738                                              1226 条 10-28 00:31 到 10-30 09:51 的旧记录，uuid 全部在前面出现过
7739  11-01T00:02:46.357Z system compact_boundary     （precomputed: true，durationMs 108）
7761  11-01T00:06:59.963Z enqueue（图片消息，没有 content）
7762  11-01T00:06:59.964Z dequeue                     取出 '/compact' → 多出一行「/compact」，step = compact
7763  11-01T00:07:00.027Z user [图片] 这俩对话早结束了…  → 本行把 step 清空，但合并时空值被跳过
…     合并后的状态里 step 一直是 compact，直到 08:12 出现跑命令
```

再统计整份文件：带 uuid 的行里有 1226 个 uuid 出现了两次，全在 6513–7738 这一段。`Transcript` 给消息编号用的是 `时间+角色+文字` 的摘要加序号（第 61–64 行），重复的那一段拿到 `…:2` 的新编号，被当成新消息排在文件末尾，于是手机上旧对话又出现一遍。

### 2.4 带图片的消息对不上：电脑时钟慢 13 秒

```
w32tm /stripchart /computer:ntp.aliyun.com /samples:3 /dataonly
08:23:14, +12.9638850s
```

正数表示网络时间比本机快，也就是这台电脑慢了约 13 秒。iPhone 的钟是准的。

手机的对照在 `apps/ios/TeleplyCore/Sources/TeleplyModel/Outbox.swift` 第 43–50 行：文字相同（去掉「[图片]」后），并且记录时间 ≥ 手机发出时间 − 5 秒。Claude 记录的时间用的是电脑的钟。电脑日志里四条消息的「提交」耗时：

| 消息 | 带图 | 电脑提交完成 | Claude 记录时间（北京） | 结果 |
|---|---|---|---|---|
| 这俩对话早结束了… | 是 | 08:07:00（2.6 秒） | 08:07:00.027 | 淡色一直在 |
| 怎么又显示两次… | 是 | 08:07:39（2.1 秒） | 08:07:42.410 | 淡色一直在 |
| 探测好了问题… | 否 | 08:08:38（1.4 秒） | 08:08:57.901 | 正常消失 |
| 怎么还显示正在压缩上下文 | 是 | 08:09:48（2.4 秒） | 08:09:51.248 | 淡色一直在 |

带图的三条，记录时间只比手机按下发送晚 2–3 秒（真实时间），减去电脑慢的 13 秒，就比手机的发出时间早了约 10 秒，超过 5 秒的容差。没带图那条记录晚了 19 秒才出现，减 13 秒还晚 6 秒，碰巧对上了。`Outbox.swift` 第 35 行的规则是：10 分钟以后、并且记录里有更晚的用户消息，淡色气泡才放弃，所以用户会看到它挂好几分钟。

电脑这边的图片对照（`SentPictures.swift`）用的是电脑自己记的发送时间，两边是同一个钟，所以实心气泡里的小图是对的。

---

## 3. 逐条原因和代码位置

### 岛-1：中转读事件的连接断了很久

- `relay_push.py` 第 569–592 行 `watch()`：读流出错时按 5、10、20…秒退避，最长 300 秒；遇到 `Refused` 且状态码 404 就等 **1800 秒**（本意是「老电脑没有这个接口」）。电脑隧道一抖、中转那一刻拿到 404，就会整整 30 分钟不读这台电脑。
- `look()`（第 554–567 行）只在任务结束或电脑不在了才重建 watcher；正在睡 30 分钟的 watcher 不会被叫醒，哪怕电脑已经连回来。
- 电脑这边只在「做完了」那一刻顺带记一句「没连着」，从不记中转什么时候断、什么时候连上，所以断了多久只能靠中转的日志看（第 5 节）。
- 断开次数也偏多（每天十几到二十几次），值得找原因：电脑的流每 45 秒发一次 keepalive（`ntfy_feed.py` KEEPALIVE），看中转或隧道是不是有更短的超时。

### 岛-2：听不到也照常「刷新」

- `relay_push.py` `sweep_islands()` 第 1199–1209 行：干活中的岛每 10 分钟（`ISLAND_REFRESH`）用中转现有的状态再推一次，带新的 stale-date。判断电脑在不在线（变灰、30 分钟后收起，`OFFLINE_AFTER`、`OFFLINE_END_AFTER`）只看隧道连没连着（`self.hub.connections`），不看事件流有没有在读。
- 结果：事件流断了，中转的状态停在 23:16，岛却每 10 分钟被刷成「新的」，用户看不出它其实过时了。

### 岛-3：连回来也补不全

- `relay_push.py` 第 73 行 `SINCE = '10m'`：中转记着每台电脑读到哪条（`self.since`，只在内存里）；中转一重启就丢，只要最近 10 分钟，更早留着的「做完了」都跳过。
- `relay_push.py` `snapshot()` 第 810–876 行：干活中的对话要连续两次快照里都没有（`SNAPSHOT_MISSES = 2`）才标成停了。
- `notify.py` `_snapshot()` 第 637–664 行：电脑在中转连上时强制发一次快照；没有对话在跑时，发完一次空快照就不再发（`if not items and self.last_snapshot_empty and not force: return`）。所以只要「做完了」事件丢了，那两个对话就一直挂着。

### 岛-4：8 小时上限

- iOS 规定实时活动最长 8 小时，到点系统结束它，锁屏上保留最后的内容最多 4 小时，之后的推送一律无效。中转从不在 8 小时前主动结束、也不换一个新的。截图里冻住的计时就是这个。

### 两-1：压缩后旧记录又写了一遍

- Claude 桌面版 2.1.309 用「预先算好的压缩」（compact_boundary 的 `precomputed: true`），这次在 /compact 时把 10-28 到 10-30 的 1226 行原样追加到文件末尾，uuid 与前面完全相同。这是 Claude 的行为，我们只能在读的时候去重。
- `chat_history.py` 第 61–72 行按 `时间+角色+阶段+文字` 编号，同样的内容第二次出现时编号带 `:2`，成了新消息。
- 同样要查：`notify.py` 读 Claude 记录（`_scan_file` / `_scan_claude`）只读新增的字节，这 1226 行会不会被当成一轮新的开始或结束。08:02:46 的日志里没有误报，但要用测试确认。

### 两-2：手机拿自己的钟比电脑的钟

- `Outbox.swift` 第 43–50 行（见 2.4）。DeepSeek 的记录时间也来自这台电脑（Harness 在本机），同样受影响。
- 手机发 Claude 消息时，电脑的回复里已经有 `offset`（发送那一刻记录文件的长度），手机存在 `_claude_offset`（`ChatModel.swift` 第 559 行）；电脑给每条消息的 `order` 就是它在文件里的位置（`chat_history.py` 第 65 行，手机读成 `message.order`）。也就是说，Claude 可以完全不比时间。

### 压-1：电脑自记的排队清单错位

- `chats.py` 第 785–803 行：`enqueue` 把文字放进清单，`remove` 按完全相同的文字删，`dequeue` 取清单第一条；取到的是斜杠命令就显示一行，并且 /compact 把 step 设成 compact。
- `remove` 对不上就什么也不做，清单从此多一条，之后永远错一位，不会自己恢复。已知的对不上：别的会话发来的消息（`<cross-session-message …>`）排队时有 `hop-chain="…"`，撤下时没有。
- 这份清单放在 `Transcript.context` 里，跟着电脑服务进程一直活着。

### 压-2：合并状态时清不掉

- `chat_history.py` 第 43–44 行：`if v is not None and v!='': self.state[k]=v`。逐行解析时 `parse_claude` 每行都从 `{"step": "", "turn_ended": "", …}` 开始，分不清「这行把 step 清空了」和「这行没碰 step」，所以只好跳过空值，结果是清空永远不生效。
- 影响：「压缩上下文」挂到下一个工具步骤；平时一轮里「跑命令」之后 Claude 在想，也还显示「跑命令」。`turn_ended` 同样清不掉，要看 `conversation()`（第 212 行起）有没有因此算错。
- Codex 也走同一个合并（`parse_codex` 不带 context），一起检查。

---

## 4. 修法

按这个顺序做：先电脑（压-1、压-2、两-1），再手机和电脑一起（两-2），最后中转（岛-1 到岛-4）。每一条都要有测试，测试用自己编的记录行，不用用户的真实内容。

### 4.1 压-2：逐行解析要能清空状态（`chats.py`、`chat_history.py`）

- 逐行模式（传了 context）下，`parse_claude` 只返回这一行真的设置过的字段，包括设成空的；`Transcript.refresh()` 照单合并，空值也写进去。整份解析（不传 context）的返回格式不变，别的调用者不受影响。
- 确认这些行会清空 step：新的用户消息、`compact_boundary`、`Compacted` 输出、一轮结束、被打断。
- 检查 `turn_ended` 改成能清空以后，`conversation()` 和列表的「运行中 / 用时」算得对不对。
- Codex 那边同样处理，或者证明 Codex 不受影响，并写进第 9 节。

### 4.2 压-1：排队清单要能自己纠正（`chats.py`）

- 比较文字前先规范化：去掉 `<cross-session-message …>` 开头标签里的属性（至少 `hop-chain`），再压空白。
- `remove` 精确对不上时，删掉规范化后相同的那条；还对不上，就删掉开头 60 个字相同的最早一条。
- 自我纠正：一条用户消息或带标签的命令行（`<command-name>/compact</command-name>`）出现时，如果清单里有与它相同的一条，就把这条和排在它前面的全部删掉。这样即使将来又有新的写法对不上，错位也只影响一条消息。
- 清单里放了超过 30 分钟的条目直接丢掉（清单里每条记下入队时间）。
- 保留 0.6.6 的行为：手机发 /compact 时，Claude 取出它的那一刻就显示「/compact」一行和「正在压缩上下文」；`compact_boundary` 之后恢复。

### 4.3 两-1：按 uuid 去重（`chat_history.py`，必要时 `notify.py`）

- `Transcript` 在 context 里记下读过的 uuid；再遇到同一个 uuid 的行，整行跳过（不出消息、不改状态、不改排队清单）。
- `notify.py` 读 Claude 记录的地方同样跳过重复 uuid，并加测试：在一轮做完以后追加一段旧记录的副本，不能产生新的「开始」「做完了」或通知。
- 列表摘要（`chats.summary`）和 `claude_open_next` 读文件末尾时，也不能被这段副本带偏，加一个测试。

### 4.4 两-2：发出的消息按电脑的钟或位置对照（手机 + 电脑）

- 电脑：三个来源的发送结果都加上 `accepted_at`（电脑自己的时间，毫秒）。只加字段，别的不动。
- 手机（`ChatModel.swift` 的 `dispatch`）：把 `accepted_at` 存进这条发送的备注，和 `_claude_offset` 放在一起。
- 手机（`Outbox.swift`）：
  - Claude：文字相同，并且消息的 `order` 大于这条发送的 `_claude_offset`，就算对上，不比时间。
  - 有 `accepted_at` 的：记录时间 ≥ `accepted_at` − 5 秒。
  - 都没有（老电脑）：容差放宽到 120 秒。
  - 「10 分钟后放弃」那条规则也改用同样的时间基准。
- 测试：手机的钟比电脑快 13 秒、图片消息 3 秒进记录，淡色气泡要消失；同样的文字连发两次，各对各的，不能一条吃掉两条。
- 网页（`mobile/src`）如果也有同样的对照，一起改；安卓 `apps/android` 先别动，见第 6 节。

### 4.5 岛-2：听不到电脑就当它离线（`relay_push.py`）

- 每台电脑记下「最后一次从它的事件流读到东西」的时间（keepalive 也算，45 秒一次）。超过 `OFFLINE_AFTER`（60 秒）没读到，就按电脑离线处理：岛变灰（显示「可能不是最新」），不再做 10 分钟刷新；超过 `OFFLINE_END_AFTER`（30 分钟）收起。
- 事件流恢复后，等电脑的快照到了再把岛改回正常内容。

### 4.6 岛-3：连回来要补全（`relay_push.py`、`notify.py`）

- 每台电脑读到的最后一个事件编号存进中转的数据库，重启也不丢。数据库里没有时，问电脑要 12 小时内的（电脑留 12 小时，`ntfy_feed.KEEP_SECONDS`），已经处理过的靠 `push_events` 表去重。
- 补回来的事件里，超过 10 分钟的只改岛，不弹横幅、不响。
- 快照：一个干活中的对话不在快照里，如果它最后一次事件已经是 60 秒以前，就马上标成停了；只有刚开始的对话才等第二次快照（保留 `SNAPSHOT_MISSES` 防竞争的本意）。
- 电脑：空快照之后 60 秒再补发一次空快照（只补一次），给老中转兜底。

### 4.7 岛-1：重连要快，断开要留记录（`relay_push.py`、`notify.py`）

- `watch()`：404 不再等 30 分钟。电脑当前还连着就最多等 60 秒；只有电脑明确是老版本（握手时报的版本里没有这个接口）才长等。退避上限改成 60 秒。
- `look()`：电脑的隧道连接换了一条（重连），就取消旧的 watcher 立刻建新的。
- 电脑日志加两种行：「中转开始读通知」「中转停止读通知（读了多久）」，每次状态变化记一行，不要每秒都记。
- 用第 5 节拿到的中转日志找出 23:17 前后断开的真正原因，写进第 9 节；如果是隧道或超时设置，按查到的改。

### 4.8 岛-4：8 小时以前主动收（`relay_push.py`，可能要改手机）

- 中转知道每个岛是哪天几点开的（`push_activities`）。开了 7 小时 45 分还在干活的岛：先用最终内容结束它（立即收起），如果电脑上还有对话在跑，再远程开一个新的。
- 远程开新岛受 `START_HOLD`（30 分钟一次）限制，这里要允许例外；测试用缩短的常量。
- 手机端如果有「岛开了多久」之类的假设，一并检查。

---

## 5. 要用户帮忙拿的证据（只读）

中转的日志在服务器上，你不能直接看。请用户在阿里云 Workbench 里运行下面这条（只读，不改任何东西），把输出贴给你：

```bash
sudo journalctl -u agent-relay-027 --since "2026-10-31 15:00" --until "2026-11-01 08:30" --no-pager | grep -E "push|island" | tail -n 400
```

时间段故意放宽（服务器可能用世界时，也可能用北京时间）。要找的：23:16 以后最后一条 `push: done …`；之后有没有 `push: snapshot`；`refresh island` 是不是一直每 10 分钟一条；中转有没有重启（启动时的日志行）。日志里的令牌只显示前几位，没有密钥。

---

## 6. 边界

- **只动这次要改的文件**：`chats.py`、`chat_history.py`、`notify.py`、`relay_push.py`、`remote.py`（只加 `accepted_at`）、对应的 `tests/`、`apps/ios/TeleplyCore` 里的 `Outbox.swift`、`ChatModel.swift` 及测试、`mobile/src` 里同样的对照（如果有）、`apps/ios/README.md`、`deploy/relay/README-027.md`、本文件第 9 节。
- **不要碰**：`deploy/site/`、仓库根目录的 `pocketagentdesk.com.png`（另一个 DeepSeek 会话的网站改版，没提交）；`tests/test_activity_records.py`（别人改的，没提交）；`relay_service.py`、`relay_identity.py`、`relay_account.*`、`relay_desktop.py`、`relay_controller.py`、`PrivacyInfo.xcprivacy`（别的会话在管）。
- **安卓 `apps/android`**：很可能有同样的「淡色气泡对不上」问题，但要用户明确同意才能改。先查清楚、写进第 9 节，然后问用户。
- **Obsidian 里的设计规范**：不改。
- 用户的电脑时钟慢 13 秒，这是 Windows 的系统设置，由用户自己去「设置 → 时间和语言 → 日期和时间 → 立即同步」，你不要动。代码修好以后，钟不准也必须正常。

---

## 7. 验证

### 7.1 本地

- `D:\Personal\agent_remote\.venv\Scripts\python.exe -m pytest tests -q` 全过（`test_mobile_polish` 里找「复制命令」按钮的两个是原来就坏的，与这次无关，记一笔即可）。
- iOS 核心：在 `apps/ios/TeleplyCore` 里 `swift test` 全过。
- 新测试至少覆盖：hop-chain 撤下对不上之后，下一条普通消息不出「/compact」；/compact 取出 → 压缩中 → compact_boundary 后清空 → 下一条消息显示「正在思考」；重复 uuid 的整段副本不出新消息、不出通知；手机的钟快 13 秒时图片消息的淡色气泡消失；事件流断 60 秒岛变灰、不再刷新；中转重启后补回 12 小时内的「做完了」且不响；快照里缺的旧对话一次就去掉；开了 7 小时 45 分的岛被收起并在需要时重开。

### 7.2 真机（新版本装上以后，请用户照做）

1. Claude 对话里从手机发 /compact：只出现一行「/compact」；压缩时显示「正在压缩上下文」；出现「对话已压缩」后，再发一条消息，显示「正在思考」；上面不再出现重复的旧对话。
2. 发一条带图片的消息：实心气泡出现后，淡色的那条几秒内消失（在用户同步电脑时钟之前测，最能说明问题）。
3. 开两个对话干活，等岛出来；让用户在 Workbench 重启一次中转（`sudo systemctl restart agent-relay-027`，要先问）：岛在一两分钟内要么回到正确内容，要么变灰；两个对话做完以后，岛上不再列它们。
4. 第二天早上看锁屏：不再有冻住的「工作中」。

---

## 8. 发布（每一步都先问用户，上一次同意不算这一次）

- **Windows dev.33**：照 `deploy/windows/build.ps1`，在干净的临时工作树（`git worktree add`）里打包，因为仓库目录里有别人没提交的改动；装到 `G:\AgentRemote`。打包、安装、发布各问一次。
- **中转**：同样在干净的临时工作树里，用 `deploy/relay/pack-027.py` 打包（中转包一律用 HEAD 的 `relay_push.py`）；服务器上由用户自己运行 `update-027.sh`。**永远不要运行 `switch-domain.py`。** 写清楚上传和运行的步骤给用户。
- **iOS 0.7.1**：改 `apps/ios/project.yml` 的 `MARKETING_VERSION`，走 Codemagic 的 `ios-native-check`、`ios-native-testflight`；构建号取 TestFlight 现有最大号加一。传之前问。
- 用完的临时工作树要删掉（仓库只留 main）。

---

## 9. 结果记录（接手的会话填）

- 中转日志看到的断开原因（11-01 查，证据在下面）：
  - **不是文档原先猜的「404 睡 30 分钟」**。中转日志里 10-31 23:17:29 是最后一次读到电脑（`push: snapshot …298b1d -> 2 个在干活/等你`）；到 11-01 08:23:28 为止一条 `push: running / step / done / snapshot` 都没有。这中间中转没有重启（进程号 150477 一直不变），岛每 10 分钟照常 `refresh island`，手机回前台时还 `register island` 补推旧状态。
  - 日志里也没有「电脑断开超过一分钟，变灰」那一行，说明中转一直认为电脑的隧道连着；断的是「读电脑事件的那条流」。
  - 数据库：`/var/lib/agent-relay/accounts.sqlite3` 的 `push_phones` 表是**空的**（09:54 查）；同时 `devices` 里这台电脑（`c9f98709…`，名「🤩」）和 `push_activities` 里那座岛（`state=working`）都属于同一个账号 `029ec66e…`。
  - 代码：`relay_push.py` 的 `look()` 只为「`hub.connections` 里、且它所属账号在 `push_phones` 里有手机」的电脑建读流任务；账号没有推送手机时，`owners` 为空，所有电脑一条流都不读。岛的刷新和「变灰/收起」只看 `push_activities` 与 `hub.connections`，跟 `push_phones` 无关。所以推送手机登记一没（23:14 重启后还能读到，23:17:29 起读不到了），读流就停了；岛却每 10 分钟被刷新成「新的」，直到 8 小时被苹果收掉。
  - 触发「推送手机登记没了」的具体动作日志里没有：可能是在 App 里关了遥应通知/解绑了令牌，也可能是找回密码（会清 `push_phones`）。下一次有 4.7 加的「中转开始读通知」和读流状态日志，就能直接看到。
  - 4.5 起把「有没有手机」和「读不读电脑」解耦（有岛也读），并且读流 60 秒没动静就按离线处理，这一类断法就不会再让岛冻住。
- 每条毛病的改法、提交号、测试名：
  - **压-1、压-2、两-1：提交 `7ec157e`**（`chats.py`、`chat_history.py`、`notify.py`）。
    - 压-2：逐行解析（传了 context）只返回这一行真的设置过的字段，空值也合并；`compact_boundary`、新的用户消息、`Compacted` 输出、一轮结束、被打断都会清空 step；Codex 同样处理。测试 `tests/test_claude_send.py::LineStateTests`（两条）、`tests/test_live_history.py::test_a_new_codex_turn_clears_the_step_and_the_turn_end`。
    - 压-1：排队清单每条记入队时间，超过 30 分钟丢掉；`remove` 先精确、再规范化（去掉 cross-session-message 开头标签的属性，如 hop-chain）、再比前 60 字；用户消息或带标签命令出现时，把清单里相同的一条及它前面的全部删掉。测试 `QueueShadowTests`（三条）。
    - 两-1：`Transcript` 和 `notify` 的增量读取按 uuid 整行跳过（不出消息、不改状态、不改排队清单）；`summary`、`claude_open_next`、`turn_end` 在同一次读取里也去重。测试 `tests/test_claude_record_repeats.py`（四条）、`tests/test_notify.py::ClaudeCopy`。
  - **两-2：提交 `de4fee2`**（`remote.py`、`Outbox.swift`、`ChatModel.swift`）。
    - 电脑三个发送结果都加 `accepted_at`（电脑自己的时间，毫秒，只加字段）；手机把 `accepted_at` 存进发送备注；Claude 按记录位置对照（消息 `order` 大于 `_claude_offset`）、不比时间，其它情况用 `accepted_at − 5 秒`，老电脑两者都没有时放宽到 120 秒；「10 分钟后放弃」也用同一时间基准。测试 `tests/test_send_accepted_at.py`（两条）、`OutboxTests.swift` 新增五条、`ChatModelTests.swift` 的 `theComputersTimeOfAcceptingIsKeptOnTheSend`。
  - **岛-1 到岛-4：提交 `0915366`**（`relay_push.py`、`notify.py`、`remote.py`）。
    - 岛-1：读流不再只看「账号有没有推送手机」——有岛的电脑也读（这次断开的真正开关）；404 不再等 30 分钟，一分钟重试；退避上限 60 秒；隧道连接换了立刻重建；电脑和中转都加「开始/停止读通知」日志。测试 `IslandTests::test_a_computer_with_an_island_is_read_even_with_no_phone_registered`、`test_a_reconnected_tunnel_gets_a_new_reader_at_once`、`test_a_refused_route_is_retried_in_a_minute_and_a_break_within_seconds`。
    - 岛-2：每台电脑记最后一次从事件流读到东西的时间（keepalive 也算），60 秒没有就当离线：岛变灰、不再做 10 分钟刷新；恢复后等电脑快照到了才改回内容。测试 `test_a_silent_stream_turns_the_island_grey_though_the_tunnel_is_up`；老测试 `test_a_computer_gone_goes_grey_and_comes_back` 按新规矩改成「先变灰，快照到了再恢复」。
    - 岛-3：读到的位置从 `push_events` 取，重启不丢，没有就问 12 小时；超过 10 分钟的补报事件只改岛、不弹不响；快照里缺席、最后一次事件已过 60 秒的对话一次就标停（刚开始的仍等第二次快照）；空快照 60 秒后再补一次。测试 `test_the_last_event_read_is_kept_for_a_restart_and_twelve_hours_are_asked_first`、`test_a_replayed_old_event_changes_the_island_but_shows_no_banner`、`test_a_snapshot_drops_a_conversation_whose_last_event_is_a_minute_old`、`test_notify.py::test_an_empty_snapshot_is_sent_once_when_the_last_work_ends`（按新规矩改了期望）。
    - 岛-4：开了 7 小时 45 分的岛先用最终状态结束（立即收起）；电脑上还有对话在跑就立刻远程开一个新的（不受 `START_HOLD` 限制）。测试 `test_an_island_seven_hours_and_45_minutes_old_is_ended_and_started_again`。手机端查过：没有「岛开了多久」的假设，`since/turn` 只用来显示计时，不用改。
- 没做或改了方案的地方，和原因：
  - 4.7 的「只有电脑明确是老版本才长等」没做：中转手里没有电脑版本号（握手只报带不带这个接口，没把版本存下来），所以 404 一律 60 秒重试。代价是老电脑会每分钟问一次；等握手报出版本再细分。
  - 岛-1 的真实原因和文档原先猜的「404 退避 30 分钟」不同（见上面的日志和数据库证据）。所以 4.5 多了一条文档原文没有的改动：**有岛也读**——这是这次真正把它救回来的开关。
  - 因为离线判断改成看事件流，两条老测试按新规矩改了期望：`test_a_computer_gone_goes_grey_and_comes_back`（恢复要等快照）、`test_an_empty_snapshot_is_sent_once_when_the_last_work_ends`（空快照要多补一次）；另有一条计数测试改成看最后一次推送（running 的静默更新现在是分开的）。不是悄悄改。
  - 中转数据库里 `push_phones` 是空的：这部 iPhone 现在没有向中转登记「遥应通知」的令牌（岛是另一套）。有岛之后读流不再依赖它，岛能正常跟；要收普通通知得在 App 的 设置 → 手机通知 里把「遥应通知」打开（这一步我没动）。
  - 本机 `.venv` 原来没装 pytest，这次装了 9.0.3（只是测试工具，不进仓库）。
- 安卓查到的情况、用户的决定：
  - 安卓的淡色气泡只显示 `label == "提交中"`，电脑一回「已接收」就撤掉（`ChatUi.kt:270`），不会像 iPhone 那样留一条重复的淡色气泡。
  - 安卓的图片对照（`SentPictures.kt:36`）两边都用电脑时间和电脑记的 `created`，同一个钟，不受手机快 13 秒影响。
  - 结论：安卓没有这两个症状，不需要改。只查没改；要不要以后也保留淡色气泡，等用户决定。
- 发布情况（哪个版本、谁在什么时候同意的）：
  - **Windows `0.27.0-dev.33`（build 33）**：11-01 14:00 左右用户同意打包、14:05 左右同意安装。从 `ac29323` 的干净工作树打包；`dist/AgentRemote-0.27.0-dev.33-Setup.exe`，32,530,487 字节，SHA256 `2AC356E3…`。已装到 `G:\AgentRemote` 并启动，本机接口回 `ui_version 0.27.0-dev.33`、`chat.available: true`。16:18 用户同意发布到阿里云：`publish.py windows` 已上传安装包、签名和清单，并取回核对（`windows/dev/windows-update.json` 是 0.27.0-dev.33、大小和 SHA-256 与本地一致、`.sig` 返回 200）。GitHub 预发布 `windows-v0.27.0-dev.33` 没有建，也不用再建：11-04 用户同意发布后，`0.27.0-dev.36`（从 `83c5437` 打，32,531,232 字节，SHA-256 `0B17BF9B…`）同时发到了阿里云和 GitHub（`windows-v0.27.0-dev.36`，用 git 存的 GitHub 登录走接口建，这台电脑其实建得了）。照电脑端的选版代码读过：dev.31、dev.33、dev.35 从两边都选中 dev.36，从阿里云下载后校验通过。
  - **中转包**：11-01 14:14 用户同意打包并更新。从 `b2cdb1f` 的干净工作树打包；`dist/agent-relay-0.27.0-dev.zip`，128,920 字节，SHA256 `71C969FE…`，包里的 `relay_push.py` 与 HEAD 一致。用户 14:16 在 Workbench 运行 `update-027.sh`，换下的文件在 `/opt/agent-relay-027/previous-20261101-141633`；**没有运行 `switch-domain.py`**。更新后 14:17:01 `push: watch … 开始读通知`（没有推送手机也读了），14:17:13 读到 `snapshot … 0 个在干活/等你`；电脑日志 14:16:48「中转开始读通知」、14:17:44「停止（读了 56 秒）」。旧岛开了十几个小时、令牌已被苹果作废，这次更新时被丢掉。
  - **iOS `0.7.1`（build 26）**：11-01 14:30 用户同意改版本号（`MARKETING_VERSION 0.7.0 -> 0.7.1`，提交 `da25568`）；14:32 同意 `ios-native-check`（`6ae6dcf9a9a1f6e314c1f983`，2 分钟，Mac 上 241 项全过）；15:06 同意 `ios-native-testflight`（`6ae6e4fa6c3d28efa550f660`，6 分钟，Delivery UUID `6a15ec8b-ab3d-403b-a0f8-205d5302f782`），已进内部测试，没提交审核。`apps/ios/README.md` 已补 0.7.1 一节。
  - 真机还没验：0.7.1 装上以后照 `apps/ios/README.md` 的 0.7.1 三条和本文 7.2 做。
- 验证记录（11-01）：
  - 全量 pytest（`.venv`）：703 项通过，3 项失败都是原来就有的——`test_mobile_polish` 找「复制命令」按钮的两项，和 `test_relay_mobile_layout::test_account_home_and_connection_panel`（在干净的 HEAD 临时工作树上复跑同样失败，确认与这次无关）。
  - iOS `swift test`：241 项全过（本机 Swift 6.4.1 + VS 2022 Build Tools；`--scratch-path` 指到工作区，没碰仓库里的 `.build`）。
  - 真机没验，等新版本装上以后照 7.2 做。
